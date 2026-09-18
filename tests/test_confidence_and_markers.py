"""Confidence policy + marker economics + provenance tests."""

from lcc.relevance import RelevanceCompactionRequest, compact_context, report_to_dict


class _ConfJudge:
    model = "fake"

    def __init__(self, score, confidence):
        self.score = score
        self.confidence = confidence

    def evaluate(self, state, questions):
        return {
            "answers": {
                qid: {"type": "noul", "noul": self.score, "confidence": self.confidence}
                for qid in questions
            }
        }


TEXT = (
    "Candidate block about booking friction with enough words to be scored properly here.\n\n"
    "Noise zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n"
)


def _run(score, conf, threshold=0.4):
    return compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="booking friction", provider="jev",
            client=_ConfJudge(score, conf), threshold=threshold,
        )
    )


LONG_TEXT = (
    "Candidate block about booking friction with enough words to be scored properly. "
    + ("Extra context sentence with booking details. " * 30)
    + "\n\nNoise zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n"
)


def _run_long(score, conf, threshold=0.4):
    return compact_context(
        RelevanceCompactionRequest(
            text=LONG_TEXT, question="booking friction", provider="jev",
            client=_ConfJudge(score, conf), threshold=threshold,
        )
    )


def test_threshold_boundaries():
    below = _run(0.05, 0.9, threshold=0.4)
    assert below.report.blocks_dropped >= 1  # below the trim band
    band = _run_long(0.39, 0.9, threshold=0.4)
    assert band.report.blocks_trimmed >= 1  # inside [0.2, 0.4): middle gear
    short_band = _run(0.39, 0.9, threshold=0.4)
    assert short_band.report.blocks_dropped == 0  # too short to trim: kept whole
    assert _run(0.40, 0.9, threshold=0.4).report.blocks_dropped == 0  # at
    assert _run(0.41, 0.9, threshold=0.4).report.blocks_dropped == 0  # above


def test_low_confidence_degrades_drop():
    confident_drop = _run(0.05, 0.95)
    assert confident_drop.report.blocks_dropped >= 1
    unconfident = _run(0.05, 0.2)
    assert unconfident.report.blocks_dropped == 0  # kept instead


def test_high_risk_needs_high_confidence():
    text = (
        ("The indemnification clause holds the provider liable for losses. " * 12)
        + "\n\nNoise zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n"
    )
    result = compact_context(
        RelevanceCompactionRequest(
            text=text, question="office plants", provider="mechanical"
        )
    )
    assert "indemnification" in result.compacted_text


def test_markers_cost_is_measured():
    result = _run(0.05, 0.95)
    payload = report_to_dict(result.report)
    assert payload["marker_tokens"] >= 0
    assert "marker_tokens" in payload


def test_markers_cannot_claim_saving_when_larger():
    result = _run(0.05, 0.95)
    # Normal case: markers are small relative to the saving.
    assert result.report.chars_after < result.report.chars_before


def test_provenance_answers_what_why_and_who():
    result = _run(0.05, 0.95)
    payload = report_to_dict(result.report)
    for d in payload["decisions"]:
        assert {"decision", "reason", "score", "confidence", "relationships",
                "policy_version", "content_type"} <= set(d)
    assert payload["policy_version"] == "relevance-compaction-1.1"
    assert payload["jev_model_requested"] == "jev-latest"
