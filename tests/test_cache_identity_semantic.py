"""Cache identity covers semantic verification state (P1: cache correctness)."""

from lcc.relevance.decisions import build_decision_identity, decision_key_v2


def _ident(**overrides):
    base = {
        "objective": "why did conversion fall",
        "block_text": "Conversion fell from 8.7% to 4.2% after June.",
        "provider": "jev",
        "model": "jev-latest",
    }
    base.update(overrides)
    return build_decision_identity(**base)


def test_semantic_verify_false_preserves_legacy_identity():
    # The verifier keys are appended only when enabled: every pre-verifier
    # sticky record keeps hashing exactly as before (no spurious epoch).
    assert decision_key_v2(_ident()) == decision_key_v2(_ident(semantic_verify=False))
    assert "semantic_verify" not in _ident()
    assert "semantic_verify" not in _ident(semantic_verify=False)


def test_semantic_verify_true_forks_cache_epoch():
    assert decision_key_v2(_ident()) != decision_key_v2(
        _ident(
            semantic_verify=True,
            verifier_model="jev-latest",
            verifier_policy_version="semantic-verifier-1.0",
        )
    )


def test_verifier_model_change_forks_epoch():
    a = _ident(
        semantic_verify=True,
        verifier_model="jev-a",
        verifier_policy_version="semantic-verifier-1.0",
    )
    b = _ident(
        semantic_verify=True,
        verifier_model="jev-b",
        verifier_policy_version="semantic-verifier-1.0",
    )
    assert decision_key_v2(a) != decision_key_v2(b)


def test_verifier_policy_change_forks_epoch():
    a = _ident(
        semantic_verify=True,
        verifier_model="jev-latest",
        verifier_policy_version="semantic-verifier-1.0",
    )
    b = _ident(
        semantic_verify=True,
        verifier_model="jev-latest",
        verifier_policy_version="semantic-verifier-9.9",
    )
    assert decision_key_v2(a) != decision_key_v2(b)


def test_verifier_identity_is_deterministic():
    kwargs = {
        "semantic_verify": True,
        "verifier_model": "jev-latest",
        "verifier_policy_version": "semantic-verifier-1.0",
    }
    assert decision_key_v2(_ident(**kwargs)) == decision_key_v2(_ident(**kwargs))


def test_verifier_is_signal_only_without_client(tmp_path):
    """End-to-end: verifier requested but no client -> REVIEW, bytes unchanged."""
    from lcc.relevance import RelevanceCompactionRequest, compact_context

    text = (
        "Conversion fell from 8.7% to 4.2% after the June release window. "
        + "Detail. " * 40
        + "\n\nChatter about office plants and coffee machines. " * 8
        + "\n\nThe decline followed the mobile redesign rollout. "
        + "Detail. " * 40
        + "\n"
    )
    cache_path = tmp_path / "decisions.jsonl"
    off = compact_context(
        RelevanceCompactionRequest(
            text=text,
            question="Why did conversion fall?",
            provider="mechanical",
            decisions_cache_path=cache_path,
            enable_semantic_verify=False,
        )
    )
    on = compact_context(
        RelevanceCompactionRequest(
            text=text,
            question="Why did conversion fall?",
            provider="mechanical",
            decisions_cache_path=cache_path,
            enable_semantic_verify=True,
        )
    )
    # No client exists on the mechanical path, so verification is unavailable:
    # fail-closed REVIEW flag, but the verifier never drops a byte by itself.
    assert on.report.needs_review is True
    assert on.report.review_reason == "verifier_unavailable_no_client"
    assert on.compacted_text == off.compacted_text
    assert off.report.needs_review is False
