import hashlib
import json
import os
import struct
import subprocess
import sys
import tomllib
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lcc.intake import category as cat
from lcc.intake import parse_intake
from lcc.intake.pipeline import LccIntake


def test_packaged_models_match_frozen_hashes():
    for resource, sha256, _ in cat.MODELS.values():
        raw = resources.files("lcc.intake").joinpath(resource).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == sha256, resource


def test_probabilities_are_a_distribution_over_fourteen_labels():
    model = cat._load()
    assert model is not None and len(model.labels) == 14
    assert abs(sum(model.proba("faz o commit e push")) - 1) < 1e-9
    assert set(model.labels) <= set(model.notes)


def test_threshold_gates_the_category():
    text = "faz o commit e push"
    assert cat.classify(text, threshold=0.0) is not None
    assert cat.classify(text, threshold=1.01) is None
    assert cat.classify("   ") is None


def test_confident_category_reaches_parsed_intake_and_outputs():
    parsed = parse_intake("faz o commit e push")
    assert parsed.category == "git_ship"
    assert parsed.category_probability >= cat._load().threshold
    assert parsed.category_context
    result = LccIntake(optimize_context=False).process("faz o commit e push")
    assert 'lcc-intake:category id="git_ship"' in result.formatted_prompt


def test_category_never_changes_readiness():
    with mock.patch.object(cat, "_load", return_value=None):
        without = parse_intake("faz o commit e push")
    with_cat = parse_intake("faz o commit e push")
    assert without.category == ""
    assert (without.readiness, without.reasons) == (with_cat.readiness, with_cat.reasons)


def test_altered_model_disables_category_instead_of_failing():
    cat._load.cache_clear()
    try:
        resource, _, threshold = cat.MODELS[cat.DEFAULT_MODEL]
        with mock.patch.dict(cat.MODELS, {cat.DEFAULT_MODEL: (resource, "0" * 64, threshold)}):
            assert cat.classify("faz o commit e push") is None
            assert parse_intake("faz o commit e push").category == ""
    finally:
        cat._load.cache_clear()


ROOT = Path(__file__).resolve().parents[1]


def test_unknown_is_reported_as_no_category():
    fake = SimpleNamespace(
        labels=["UNKNOWN", "git_ship"],
        proba=lambda t, prev=None: [0.9, 0.1],
        notes={},
        threshold=0.5,
    )
    with mock.patch.object(cat, "_load", return_value=fake):
        assert cat.classify("???") is None


def test_wrong_length_weights_disable_category():
    cat._load.cache_clear()
    try:
        with mock.patch.object(cat, "_Model", side_effect=struct.error("bad length")):
            assert cat._load() is None
    finally:
        cat._load.cache_clear()


def test_probabilities_are_identical_across_hash_seeds():
    code = (
        "import json; from lcc.intake.category import _load; m=_load();"
        "print(json.dumps([m.proba(t) for t in ['faz o commit e push', 'deu erro no deploy', 'sim']]))"
    )
    outs = set()
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")}
        outs.add(
            subprocess.run(
                [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
            ).stdout
        )
    assert len(outs) == 1


def test_only_the_head_of_long_inputs_is_classified():
    head = "faz o commit e push\n" + "x " * 600
    assert cat._load().proba(head + "deu erro " * 5000) == cat._load().proba(head)


def test_category_fields_have_one_shape_in_every_output():
    keys = {"category", "category_probability", "category_context"}
    intake = LccIntake(optimize_context=False)
    payload = json.loads(
        intake.process("faz o commit e push", output_format="json").formatted_prompt
    )
    assert keys <= payload.keys() and payload["category"] == "git_ship"
    toon = intake.process("faz o commit e push", output_format="toon").formatted_prompt
    assert all(k in toon for k in keys)
    from lcc.mcp_server import _tool_intake

    out = _tool_intake({"text": "faz o commit e push"})
    assert keys <= out.keys() and out["category"] == "git_ship"


def test_category_line_sits_after_the_static_template():
    prompt = LccIntake(optimize_context=False).process("faz o commit e push").formatted_prompt
    assert prompt.index("lcc-intake:readiness") < prompt.index("lcc-intake:category")


def test_sdist_manifest_ships_every_packaged_json():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"][
        "package-data"
    ]["lcc"]
    manifest = (ROOT / "MANIFEST.in").read_text()
    for name in data:
        if name.endswith(".json"):
            assert f"include src/lcc/{name}" in manifest, name


def test_missing_model_file_disables_category():
    cat._load.cache_clear()
    try:
        broken = mock.MagicMock()
        broken.joinpath.return_value.read_bytes.side_effect = FileNotFoundError("gone")
        with mock.patch.object(cat.resources, "files", return_value=broken):
            assert cat._load() is None
    finally:
        cat._load.cache_clear()


def test_altered_notes_disable_category():
    cat._load.cache_clear()
    try:
        with mock.patch.object(cat, "NOTES_SHA256", "0" * 64):
            assert cat._load() is None
    finally:
        cat._load.cache_clear()


def test_notes_are_single_line_and_cannot_close_a_comment():
    for note in cat._load().notes.values():
        assert "--" not in note and "\n" not in note


def test_context_is_sanitised_inside_the_comment():
    from lcc.intake.parser import ParsedIntake, ReadinessState
    from lcc.intake.pipeline import _intake_block

    parsed = ParsedIntake(
        raw_input="x",
        intent="x",
        readiness=ReadinessState.READY_TO_EXECUTE,
        readiness_score=90,
        ambiguity_score=10,
        category="git_ship",
        category_probability=0.9,
        category_context="a --> b\nc",
    )
    line = [x for x in _intake_block(parsed, None).splitlines() if "lcc-intake:category" in x]
    assert len(line) == 1 and line[0].count("-->") == 1 and line[0].endswith("-->")


def test_v3_matches_the_lcc_judge_reference_implementation():
    cases = json.loads((ROOT / "tests" / "fixtures" / "intake_category_v3_parity.json").read_text())
    model = cat._load("v3")
    for case in cases["cases"]:
        p = model.proba(case["prompt"], case["previous_turn"])
        i = max(range(len(p)), key=p.__getitem__)
        assert model.labels[i] == case["label"], case["prompt"]
        assert abs(p[i] - case["probability"]) < 1e-6, case["prompt"]


def test_previous_turn_is_read_by_v3_only_and_only_its_tail():
    v3, v1 = cat._load("v3"), cat._load("v1")
    prev = "Quer que eu faça o commit e o push agora?"
    assert v3.proba("sim", prev) != v3.proba("sim")
    assert v1.proba("sim", prev) == v1.proba("sim")
    tail = prev * 20
    assert v3.proba("sim", "x" * 5000 + tail) == v3.proba("sim", tail[-cat.PREV_CHARS :])
    # A non-string previous turn from the Python API is ignored, as v1 ignores any previous turn.
    assert v3.proba("sim", 42) == v3.proba("sim")
    assert LccIntake(optimize_context=False).parse("sim", previous_turn=["x"]).category


def test_env_pins_the_model_and_unknown_names_fall_back_to_default():
    with mock.patch.dict(os.environ, {cat.MODEL_ENV: "v1"}):
        assert cat.model_name() == "v1"
        got = cat.classify("deu erro no deploy", threshold=0.0)
        assert got is not None and got.probability == round(
            max(cat._load("v1").proba("deu erro no deploy")), 4
        )
    with mock.patch.dict(os.environ, {cat.MODEL_ENV: "nope"}):
        assert cat.model_name() == cat.DEFAULT_MODEL == "v3"


def test_previous_turn_reaches_the_category_through_every_entry_point():
    from lcc.mcp_server import ToolInputError, _tool_intake

    prev = "Quer que eu faça o commit e o push agora?"
    with_prev = cat.classify("sim", threshold=0.0, previous_turn=prev)
    assert parse_intake("sim", previous_turn=prev).category_probability == with_prev.probability
    out = _tool_intake({"text": "sim", "previous_turn": prev})
    assert out["category_probability"] == with_prev.probability
    try:
        _tool_intake({"text": "sim", "previous_turn": 3})
    except ToolInputError:
        pass
    else:
        raise AssertionError("non-string previous_turn accepted")
