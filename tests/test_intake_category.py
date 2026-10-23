import hashlib
from importlib import resources
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
