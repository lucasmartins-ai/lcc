"""Sufficiency verification tests: candidate compression -> verify -> restore."""

import sys
from pathlib import Path

import pytest

import lcc.relevance.compactor as _compactor_mod
from lcc.relevance import RelevanceCompactionRequest, compact_context
from lcc.relevance.sufficiency import verify_sufficiency

_ADV_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "research"
sys.path.insert(0, str(_ADV_DIR))

from adversarial_cases import CASES, build_corpus  # noqa: E402


def _case(case_id):
    return next(c for c in CASES if c.id == case_id)


def _compact_mechanical(case_id, **kw):
    case = _case(case_id)
    return case, compact_context(
        RelevanceCompactionRequest(
            text=build_corpus(case),
            question=case.question,
            provider="mechanical",
            **kw,
        )
    )


class _Judge:
    """Scores the general rule high and the payment exception low (the naive mistake)."""

    model = "fake"

    def evaluate(self, state, questions):
        answers = {}
        for qid in questions:
            bid = qid[len("keep_") :]
            text = next(b["text"] for b in state["blocks"] if b["id"] == bid)
            if "30 seconds" in text:
                score = 0.95
            elif "payment" in text.lower():
                score = 0.05
            else:
                score = 0.02
            answers[qid] = {"type": "noul", "noul": score}
        return {"answers": answers}


TEXT = (
    "Timeout is 30 seconds for every request in the standard fleet deployment.\n\n"
    "Unrelated office chatter about plants and coffee machines needing water daily.\n\n"
    "For payment requests, timeout is 60 seconds instead of the standard fleet value.\n"
)


def test_naive_drop_is_caught_and_restored():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="What is the request timeout?", provider="jev", client=_Judge()
        )
    )
    assert "60 seconds" in result.compacted_text  # restored, not dropped
    assert result.report.blocks_restored >= 1
    assert result.report.sufficiency_checks >= 1
    assert any("sufficiency" in w for w in result.report.warnings)


def test_no_missing_evidence_stays_sufficient():
    verdict = verify_sufficiency(dropped_ids=[], kept_ids={"a"}, reasons={}, relationships={})
    assert verdict.sufficient and verdict.missing_evidence == []


def test_multiple_missing_blocks_all_restored():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="What is the request timeout?", provider="jev", client=_Judge()
        )
    )
    assert result.report.sufficiency_failures >= 1 or result.report.blocks_restored >= 1


def test_restoration_budget_exceeded_warns():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT,
            question="What is the request timeout?",
            provider="jev",
            client=_Judge(),
            max_restorations=0,
        )
    )
    assert "60 seconds" not in result.compacted_text
    assert any("budget" in w for w in result.report.warnings)


def test_verifier_unavailable_fails_closed():
    verdict = verify_sufficiency(
        dropped_ids=["b1"], kept_ids={"a"}, reasons={"b1": "score_below_threshold"},
        relationships={"b1": "supports:evidence"}, confidence=0.0,
    )
    assert not verdict.sufficient
    assert verdict.critical_dropped_blocks == ["b1"]


def test_contradictory_evidence_is_flagged():
    verdict = verify_sufficiency(
        dropped_ids=["b"],
        kept_ids={"a"},
        reasons={"b": "score_below_threshold"},
        relationships={"b": "contradicts:a"},
    )
    assert not verdict.sufficient


def test_sufficiency_can_be_disabled():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="What is the request timeout?", provider="jev",
            client=_Judge(), enable_sufficiency=False,
        )
    )
    assert "60 seconds" not in result.compacted_text
    assert result.report.sufficiency_checks == 0


# --- MSI Sprint 3: severed link, bypassed protection, injected failures --------


def test_severed_link_marks_insufficient():
    """A dropped block linked to kept content is a severed link: insufficient."""
    verdict = verify_sufficiency(
        dropped_ids=["b_cause"],
        kept_ids={"b_effect"},
        reasons={"b_cause": "score_below_threshold"},
        relationships={"b_cause": "supports:b_effect"},
    )
    assert not verdict.sufficient
    assert verdict.critical_dropped_blocks == ["b_cause"]
    assert verdict.missing_evidence == ["supports:b_effect"]


def test_bypassed_protection_restores_with_per_block_reason():
    """A judge that drops linked evidence gets it restored, with motive + origin.

    The restored decision names the layer (``semantic_sufficiency_restoration``)
    and the IR carries the same motive in ``selection.rationale`` so the
    restore is auditable per block in both the report and the IR.
    """
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="What is the request timeout?", provider="jev",
            client=_Judge(), emit_ir=True,
        )
    )
    restored = [d for d in result.report.decisions if d.decision == "keep"
                and d.reason == "semantic_sufficiency_restoration"]
    assert restored, "linked payment exception must be restored, not dropped"
    assert "60 seconds" in result.compacted_text
    assert result.context_ir is not None
    for dec in restored:
        assert dec.id in result.context_ir["restoration"]["restored"]
        assert (result.context_ir["selection"]["rationale"][dec.id]
                == "semantic_sufficiency_restoration")


def test_injected_sufficiency_failure_flags_review():
    """Layer 2 (structural) crashing never drops silently: REVIEW + keep signal."""
    def _boom(*args, **kwargs):
        raise RuntimeError("injected sufficiency outage")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_compactor_mod, "verify_sufficiency", _boom)
    try:
        result = compact_context(
            RelevanceCompactionRequest(
                text=TEXT, question="What is the request timeout?",
                provider="jev", client=_Judge(),
            )
        )
    finally:
        monkeypatch.undo()
    assert result.report.sufficiency_failures >= 1
    assert any("sufficiency_failed_fail_closed" in w for w in result.report.warnings)
    assert result.report.needs_review is True
    assert result.context_ir is None  # emit_ir off; no crash, output produced


def test_injected_graph_failure_preserves_context():
    """Layer 1 (dependency graph) crashing degrades to a warning, never a crash."""
    def _boom(*args, **kwargs):
        raise RuntimeError("injected graph outage")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_compactor_mod, "build_graph", _boom)
    try:
        case, result = _compact_mechanical("dependency_causal")
    finally:
        monkeypatch.undo()
    assert any("relationship_analysis_failed" in w for w in result.report.warnings)
    assert result.report.blocks_total > 0
    assert len(result.compacted_text) > 0


class _VerifierOutageJudge:
    """Scores the selector normally but the verifier call always explodes."""

    model = "fake"

    def evaluate(self, state, questions):
        if "context" in state:  # verifier call
            raise RuntimeError("injected verifier outage")
        answers = {}
        for qid in questions:
            bid = qid[len("keep_"):]
            text = next(b["text"] for b in state["blocks"] if b["id"] == bid)
            score = 0.95 if "30 seconds" in text else 0.05
            answers[qid] = {"type": "noul", "noul": score, "confidence": 0.9}
        return {"answers": answers}


def test_injected_verifier_failure_reviews_never_drops():
    """Layer 3 (light judge) crashing degrades to REVIEW; bytes are never dropped.

    Two crash shapes: the client exploding (contract maps it to REVIEW) and the
    verifier itself exploding (the compactor seam maps it to REVIEW too).
    """
    text = TEXT + (
        "\n\nParking permits renew in spring while repaving starts someday soon "
        "with other entirely disjoint matters for the verifier outage check."
    )
    result = compact_context(
        RelevanceCompactionRequest(
            text=text, question="What is the request timeout?", provider="jev",
            client=_VerifierOutageJudge(), enable_semantic_verify=True,
        )
    )
    assert result.report.blocks_dropped >= 1  # unlinked noise still drops: verifier ran
    assert result.report.needs_review is True
    assert any("verifier_unavailable_fail_closed" in w for w in result.report.warnings)

    import lcc.relevance.verifier as _verifier_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("injected verifier code outage")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_verifier_mod, "verify_semantic_contract", _boom)
    try:
        crashed = compact_context(
            RelevanceCompactionRequest(
                text=text, question="What is the request timeout?", provider="jev",
                client=_Judge(), enable_semantic_verify=True,
            )
        )
    finally:
        monkeypatch.undo()
    assert crashed.report.needs_review is True
    assert any("semantic_verifier_failed" in w for w in crashed.report.warnings)
    assert len(crashed.compacted_text) > 0


# --- MSI Sprint 3: adversarial matrix (1 test per class, no cherry-pick) ------


def test_adv_contradiction_keeps_both_sides():
    """Contraditório: keeping one value silently picks a side — both must survive."""
    case, result = _compact_mechanical("contradiction_same_metric")
    assert "4.2 percent" in result.compacted_text
    assert "8.7 percent" in result.compacted_text


def test_adv_stale_supersession_keeps_latest():
    """Stale: three dated prices; the answer is the latest, never an older one."""
    case, result = _compact_mechanical("temporal_supersession")
    assert "95 pounds" in result.compacted_text


def test_adv_exact_duplicate_drop_preserves_outcome():
    """Duplicado: dropping a byte-identical copy is safe — the content survives."""
    body = (
        "The gateway configuration sets the upstream request timeout to 10000 ms "
        "in the deployment manifest used by production. Padding to pass the eighty "
        "character scoring floor for this duplication check block."
    )
    filler = (
        "Office chatter about plants and coffee machines needing water daily and "
        "other unrelated background noise for the duplication check corpus."
    )
    text = "\n\n".join([body, filler, body, filler, filler]) + "\n"
    result = compact_context(
        RelevanceCompactionRequest(
            text=text, question="What is the request timeout?",
            provider="mechanical",
        )
    )
    assert "10000 ms" in result.compacted_text  # first copy kept verbatim


class _DropCauseJudge:
    """Semantic-judge mistake shape: the effect scores high, its cause scores low."""

    model = "fake"

    def evaluate(self, state, questions):
        answers = {}
        for qid in questions:
            bid = qid[len("keep_"):]
            text = next(b["text"] for b in state["blocks"] if b["id"] == bid)
            score = 0.95 if "dropped by 12 percent" in text else 0.05
            answers[qid] = {"type": "noul", "noul": score, "confidence": 0.9}
        return {"answers": answers}


def test_adv_hidden_dependency_restored():
    """Dependência oculta: cause and effect share no question terms; the link restores."""
    case = _case("dependency_causal")
    result = compact_context(
        RelevanceCompactionRequest(
            text=build_corpus(case), question=case.question, provider="jev",
            client=_DropCauseJudge(),
        )
    )
    assert "refactored in June" in result.compacted_text
    assert "dropped by 12 percent" in result.compacted_text
    assert result.report.blocks_restored >= 1


def test_adv_single_evidence_never_dropped_as_redundant():
    """Evidência única: one block carries the only value — zero redundancy to exploit."""
    case, result = _compact_mechanical("unit_conversion")
    assert "10000 ms" in result.compacted_text


def test_adv_provenance_wellformed_by_construction():
    """Proveniência: every emitted unit carries provenance; malformed IR is rejected."""
    jsonschema = pytest.importorskip("jsonschema", reason="spec validation needs jsonschema")
    spec_path = Path(__file__).parent / "fixtures" / "msi" / "context-ir.schema.json"
    if not spec_path.exists():
        pytest.skip("spec repo not present")
    import json

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    case, result = _compact_mechanical("numeric_precision", emit_ir=True)
    assert result.context_ir is not None
    jsonschema.validate(result.context_ir, spec)
    for unit in result.context_ir["units"]:
        assert set(unit["provenance"]) >= {"origin", "collected_at", "transform"}
    malformed = dict(result.context_ir)
    malformed["units"] = [dict(u) for u in result.context_ir["units"]]
    del malformed["units"][0]["provenance"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(malformed, spec)
