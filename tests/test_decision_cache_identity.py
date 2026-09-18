"""Decision cache identity tests (v1.1): policy state is part of the key."""

from lcc.relevance.decisions import (
    CachedDecision,
    DecisionCache,
    build_decision_identity,
    canonical_dumps,
    decision_key,
    decision_key_v2,
)


def _ident(**overrides):
    base = {
        "objective": "what is the booking problem",
        "block_text": "The clinic booking widget loses 63 percent of mobile visitors.",
        "provider": "jev",
        "model": "jev-latest",
    }
    base.update(overrides)
    return build_decision_identity(**base)


def test_identical_inputs_cache_hit():
    assert decision_key_v2(_ident()) == decision_key_v2(_ident())


def test_different_objective_cache_miss():
    assert decision_key_v2(_ident()) != decision_key_v2(_ident(objective="other question"))


def test_different_policy_version_cache_miss():
    assert decision_key_v2(_ident()) != decision_key_v2(_ident(policy_version="other-policy"))


def test_different_model_cache_miss():
    assert decision_key_v2(_ident()) != decision_key_v2(_ident(model="jev-v2"))


def test_different_threshold_cache_miss():
    assert decision_key_v2(_ident(threshold=0.4)) != decision_key_v2(_ident(threshold=0.7))


def test_different_trim_policy_cache_miss():
    assert decision_key_v2(_ident(trim_head_chars=300)) != decision_key_v2(_ident(trim_head_chars=100))


def test_different_parser_version_cache_miss():
    assert decision_key_v2(_ident()) != decision_key_v2(_ident(parser_version="blocks-9.9"))


def test_reordered_json_fields_same_key():
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert canonical_dumps(a) == canonical_dumps(b)
    assert decision_key_v2({**_ident(), "extra": a}) == decision_key_v2({**_ident(), "extra": b})


def test_whitespace_is_significant_and_explicit():
    assert decision_key("q", "block ") != decision_key("q", "block")
    assert decision_key_v2(_ident(block_text="block ")) != decision_key_v2(_ident(block_text="block"))


def test_legacy_key_ignores_policy_but_v2_does_not():
    # Same content under two policies: legacy collides (documented), v2 separates.
    assert decision_key("q", "b") == decision_key("q", "b")
    assert decision_key_v2(_ident(threshold=0.4)) != decision_key_v2(_ident(threshold=0.9))


def test_v11_records_round_trip_with_identity(tmp_path):
    from pathlib import Path

    path = Path(str(tmp_path)) / "decisions.jsonl"
    cache = DecisionCache(path)
    identity = _ident()
    key = decision_key_v2(identity)
    cache.put(
        key, objective="what is the booking problem",
        block_text="The clinic booking widget loses 63 percent of mobile visitors.",
        entry=CachedDecision(score=0.2, decision="drop", provider="jev"),
        identity=identity,
    )
    cache.flush()
    second = DecisionCache(path)
    second.load()
    entry = second.get(key)
    assert entry is not None and entry.decision == "drop"
    # A v1.0-style key for the same content must NOT hit the v1.1 record.
    assert second.get(decision_key(
        "what is the booking problem",
        "The clinic booking widget loses 63 percent of mobile visitors.",
    )) is None
