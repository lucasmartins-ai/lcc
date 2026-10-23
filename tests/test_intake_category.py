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


def test_packaged_model_matches_frozen_hash():
    raw = resources.files("lcc.intake").joinpath(cat.MODEL_RESOURCE).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == cat.MODEL_SHA256


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
    assert parsed.category_probability >= cat.THRESHOLD
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
        with mock.patch.object(cat, "MODEL_SHA256", "0" * 64):
            assert cat.classify("faz o commit e push") is None
            assert parse_intake("faz o commit e push").category == ""
    finally:
        cat._load.cache_clear()


ROOT = Path(__file__).resolve().parents[1]


def test_unknown_is_reported_as_no_category():
    fake = SimpleNamespace(labels=["UNKNOWN", "git_ship"], proba=lambda t: [0.9, 0.1], notes={})
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
