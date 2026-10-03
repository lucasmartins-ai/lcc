"""MSI Sprint 2: Context IR emission (all offline, mechanical or fake-Jev only).

Covers the sprint acceptance: subsetness, provenance survival, restored-in-original,
determinism, protected-never-dropped (unit + seeded property), golden fixtures,
explain covering 100% of drops, and spec-schema validity (jsonschema when present).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lcc.cli import app
from lcc.relevance import (
    RelevanceCompactionRequest,
    build_context_ir,
    compact_context,
    dumps_canonical,
    is_context_ir,
    render_ir_explanation,
)
from lcc.relevance.blocks import split_blocks
from lcc.relevance.ir import IR_SCHEMA_VERSION, RESTORATION_REASONS

jsonschema = pytest.importorskip("jsonschema", reason="spec validation needs jsonschema")

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures" / "ir"
SPEC = Path(__file__).parent / "fixtures" / "msi" / "context-ir.schema.json"

CASES = {
    "corpus-01.txt": "reduce mobile booking friction in the checkout flow",
    "corpus-02.txt": "decide whether the duplicate subscription charge gets a refund",
    "corpus-03.txt": "what caused the search endpoint latency regression",
    "corpus-04.txt": "reduce mobile booking friction in the checkout flow",
}


def _emit(name: str, **overrides: Any):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    base: dict[str, Any] = {
        "text": text,
        "question": CASES[name],
        "provider": "mechanical",
        "emit_ir": True,
        "source_origin": name,
    }
    base.update(overrides)
    result = compact_context(RelevanceCompactionRequest(**base))
    assert result.context_ir is not None
    return result.context_ir


def _spec() -> dict[str, Any]:
    return json.loads(SPEC.read_text(encoding="utf-8"))


# --- golden fixtures -----------------------------------------------------------


def test_golden_fixtures_exist_and_validate():
    spec = _spec()
    for name in CASES:
        golden = FIXTURES / name.replace("corpus", "ir").replace(".txt", ".json")
        assert golden.is_file(), f"missing golden fixture {golden.name}"
        ir = json.loads(golden.read_text(encoding="utf-8"))
        jsonschema.validate(ir, spec)


def test_golden_fixtures_byte_identical_on_reemit():
    for name in CASES:
        golden = FIXTURES / name.replace("corpus", "ir").replace(".txt", ".json")
        assert dumps_canonical(_emit(name)) == golden.read_text(encoding="utf-8")


def test_emit_ir_defaults_off():
    text = (FIXTURES / "corpus-01.txt").read_text(encoding="utf-8")
    result = compact_context(
        RelevanceCompactionRequest(
            text=text, question=CASES["corpus-01.txt"], provider="mechanical"
        )
    )
    assert result.context_ir is None


# --- structural invariants (every golden) --------------------------------------


def test_selection_partitions_units():
    for name in CASES:
        ir = _emit(name)
        ids = [u["id"] for u in ir["units"]]
        sel = ir["selection"]
        assert len(ids) == len(set(ids))
        assert sorted(sel["kept"] + sel["trimmed"] + sel["dropped"]) == sorted(ids)
        assert not (set(sel["kept"]) & set(sel["dropped"]))
        assert not (set(sel["kept"]) & set(sel["trimmed"]))
        assert not (set(sel["trimmed"]) & set(sel["dropped"]))


def test_provenance_survives_on_selected_units():
    for name in CASES:
        ir = _emit(name)
        selected = set(ir["selection"]["kept"]) | set(ir["selection"]["trimmed"])
        assert selected, "fixture must select at least one unit"
        for unit in ir["units"]:
            if unit["id"] in selected:
                prov = unit["provenance"]
                assert prov["origin"] == name
                assert prov["transform"] == "none"
                assert prov["collected_at"]


def test_units_carry_verbatim_bytes():
    for name in CASES:
        text = (FIXTURES / name).read_text(encoding="utf-8")
        ir = _emit(name)
        for unit in ir["units"]:
            assert unit["content"] in text


def test_necessity_defaults_unknown_and_relevance_bounded():
    for name in CASES:
        for unit in _emit(name)["units"]:
            assert unit["necessity"] == "UNKNOWN"
            assert 0.0 <= unit["relevance"] <= 1.0
            assert isinstance(unit["protected"], bool)


def test_restored_subset_of_original_with_matching_reason():
    for name in CASES:
        ir = _emit(name)
        ids = {u["id"] for u in ir["units"]}
        assert set(ir["restoration"]["restored"]) <= ids
        assert ir["restoration"]["budget"] == 8
        if ir["restoration"]["restored"]:
            assert ir["restoration"]["reason"]
        else:
            assert ir["restoration"]["reason"] == ""


def test_determinism_same_input_same_bytes():
    ir_a = dumps_canonical(_emit("corpus-01.txt"))
    ir_b = dumps_canonical(_emit("corpus-01.txt"))
    assert ir_a == ir_b


def test_task_id_deterministic_per_objective():
    assert _emit("corpus-01.txt")["task_id"] == _emit("corpus-01.txt")["task_id"]
    assert _emit("corpus-01.txt")["task_id"] != _emit("corpus-02.txt")["task_id"]


def test_envelope_has_no_provider_fields():
    for name in CASES:
        ir = _emit(name)
        assert "provider" not in ir
        for unit in ir["units"]:
            assert "provider" not in unit
            assert "model" not in unit


def test_negative_extra_field_rejected_by_spec():
    spec = _spec()
    ir = _emit("corpus-01.txt")
    ir["units"][0]["openai_temperature"] = 0.7
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(ir, spec)


# --- protected never silently dropped ------------------------------------------


def test_protected_short_block_survives_irrelevant_text():
    text = (
        "Objective is about mobile booking friction in the checkout flow, discussed at length "
        "across this opening block with plenty of domain words.\n\n"
        "Totally unrelated zzz."
    )
    result = compact_context(
        RelevanceCompactionRequest(
            text=text,
            question="reduce mobile booking friction in the checkout flow",
            provider="mechanical",
            emit_ir=True,
            source_origin="inline",
        )
    )
    ir = result.context_ir
    assert ir is not None
    short = next(u for u in ir["units"] if "zzz" in u["content"])
    assert short["protected"] is True
    assert short["id"] not in ir["selection"]["dropped"]
    assert ir["selection"]["rationale"][short["id"]] == "short_block"


def test_protected_never_dropped_property():
    rng = random.Random(42)
    relevant = [
        "mobile booking flow checkout friction payment screen users conversion funnel",
        "the checkout funnel for mobile booking keeps losing users at the payment step",
    ]
    noise = [
        "granite quarry basalt sediment core samples catalogued by depth and mineral",
        "xylophone zebras quietly juggling kilowatt vortex magnets at midnight",
    ]
    shorts = ["zzz unrelated.", "note: snacks friday.", "ok."]
    for trial in range(50):
        paras = [rng.choice(relevant), rng.choice(noise), rng.choice(shorts)]
        rng.shuffle(paras)
        text = "\n\n".join(paras)
        blocks = split_blocks(text)
        protected_ids = {b.id for b in blocks if b.protected}
        assert protected_ids, f"trial {trial} built no protected block"
        result = compact_context(
            RelevanceCompactionRequest(
                text=text,
                question="reduce mobile booking friction in the checkout flow",
                provider="mechanical",
                emit_ir=True,
                source_origin="inline",
            )
        )
        ir = result.context_ir
        assert ir is not None
        assert not (protected_ids & set(ir["selection"]["dropped"])), f"trial {trial}"
        for bid in ir["selection"]["dropped"]:
            assert ir["selection"]["rationale"].get(bid), f"trial {trial} drop {bid} unexplained"


# --- explain covers 100% of drops ----------------------------------------------


def test_explain_covers_every_drop():
    for name in CASES:
        ir = _emit(name)
        dropped = ir["selection"]["dropped"]
        assert dropped, f"{name} must drop at least one unit for this test"
        for bid in dropped:
            assert ir["selection"]["rationale"].get(bid), f"{name} drop {bid} unexplained"
        rendered = render_ir_explanation(ir)
        for bid in dropped:
            assert bid in rendered


def test_explain_only_filter_and_bad_value():
    ir = _emit("corpus-01.txt")
    rendered = render_ir_explanation(ir, only="drop")
    assert "DROPPED" in rendered and "KEPT" not in rendered
    with pytest.raises(ValueError):
        render_ir_explanation(ir, only="bogus")


# --- restoration mapping --------------------------------------------------------


class _FakeJevClient:
    """Offline scorer: drops everything except blocks naming 'relevant'."""

    def __init__(self) -> None:
        self.model = "fake"

    def evaluate(self, state, questions):
        texts = {b["id"]: b["text"] for b in state["blocks"]}
        answers = {}
        for qid in questions:
            bid = qid[len("keep_") :]
            score = 0.9 if "relevant" in texts.get(bid, "").lower() else 0.05
            answers[qid] = {"type": "noul", "noul": score}
        return {"answers": answers}


RESTORE_TEXT = (
    "This passage is relevant to the booking funnel objective and it discusses the payment "
    "confirmation screen behavior in full detail for the review.\n\n"
    "The payment confirmation screen timeout interacts with the gateway migration schedule and "
    "changes the funnel numbers silently every single night.\n\n"
    "Completely unrelated zzz qqq xxx wwww vvvv jjjj kkkk mmmm nnnn oooo pppp filler with no "
    "shared vocabulary at all inside this very long block here."
)


def test_restoration_represented_in_ir():
    result = compact_context(
        RelevanceCompactionRequest(
            text=RESTORE_TEXT,
            question="booking funnel objective",
            provider="jev",
            client=_FakeJevClient(),
            emit_ir=True,
            source_origin="restore-case",
        )
    )
    ir = result.context_ir
    assert ir is not None
    assert ir["restoration"]["restored"], "linked drop must be restored within budget"
    assert ir["restoration"]["reason"]
    assert set(ir["restoration"]["restored"]) <= {u["id"] for u in ir["units"]}
    for bid in ir["restoration"]["restored"]:
        assert bid in ir["selection"]["kept"]
        assert ir["selection"]["rationale"][bid] in RESTORATION_REASONS
    jsonschema.validate(ir, _spec())


def test_build_context_ir_without_graph():
    blocks = split_blocks("alpha beta gamma " * 8 + "\n\n" + "delta epsilon zeta " * 8)
    ordered = [
        type(
            "D",
            (),
            {
                "id": b.id,
                "index": b.index,
                "decision": "keep",
                "score": 0.8,
                "reason": "lexical_overlap",
            },
        )()
        for b in blocks
    ]
    ir = build_context_ir(
        task_id="t",
        blocks=blocks,
        ordered=ordered,
        graph=None,
        restoration_budget=4,
    )
    assert ir["relationships"] == []
    assert ir["schema_version"] == IR_SCHEMA_VERSION
    jsonschema.validate(ir, _spec())


# --- CLI surface ------------------------------------------------------------------


def test_cli_compact_emit_ir_and_explain_and_inspect(tmp_path):
    src = tmp_path / "in.md"
    src.write_text((FIXTURES / "corpus-01.txt").read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out.md"
    report = tmp_path / "report.json"
    ir_path = tmp_path / "ir.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "--question",
            CASES["corpus-01.txt"],
            "--provider",
            "mechanical",
            "--output",
            str(out),
            "--report",
            str(report),
            "--emit-ir",
            str(ir_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(ir_path.read_text(encoding="utf-8"))
    assert is_context_ir(payload)
    jsonschema.validate(payload, _spec())

    explained = runner.invoke(app, ["explain", str(ir_path), "--only", "drop"])
    assert explained.exit_code == 0, explained.output
    assert "DROPPED" in explained.output

    inspected = runner.invoke(
        app, ["inspect", str(src), "--ir", str(ir_path), "--report", str(tmp_path / "i.json")]
    )
    assert inspected.exit_code == 0, inspected.output


def test_cli_explain_rejects_non_report():
    assert is_context_ir({"schema_version": IR_SCHEMA_VERSION, "units": [], "selection": {}})
    assert not is_context_ir({"schema_version": "relevance-compaction-1.2"})
    assert not is_context_ir({})
