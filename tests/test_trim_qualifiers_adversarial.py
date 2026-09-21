"""Adversarial qualifier-truncation tests (P1): trimming must never invert a claim.

Each qualifier below changes the meaning of the head that precedes it. A trim
that drops the qualifier (or straddles it) must be refused (ok=False) so the
caller KEEPs the block whole. A control block with no qualifier must still trim.
"""

import pytest

from lcc.relevance.trim import trim_block_safe

PADDING = "Padding detail with neutral filler words. " * 25

CASES = {
    "except": ("Refunds are approved for all plans. ", "except when a chargeback is open."),
    "unless": ("Access is granted to every employee. ", "unless security revoked the badge."),
    "only": ("The benefit applies to members. ", "Only users with two years tenure qualify."),
    "but": ("The migration finished on time. ", "but never on the legacy shard."),
    "however": ("The dosage is standard for adults. ", "however children need half."),
    "provided_that": ("Proceed with the rollout. ", "provided that the canary stays green."),
    "subject_to": ("The payout is confirmed. ", "subject to final audit sign-off."),
    "excluding": ("All records were exported. ", "excluding sealed court files."),
    "without": ("Deploy the release now. ", "without the migration step it fails."),
    "not": ("The account stays active. ", "Do not close it before Friday."),
    "never": ("Retry the job on failure. ", "Never retry on validation errors."),
    "if": ("Approve the refund request. ", "if the audit trail is complete."),
    "despite": ("The launch stayed on schedule. ", "despite the outage on Tuesday."),
    "before": ("Delete the staging bucket. ", "before deleting, snapshot it first."),
    "after": ("Restart the service. ", "Apply the patch only after drain."),
    "until": ("The token stays valid. ", "Valid until Friday at noon."),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_qualifier_in_tail_refuses_trim(name):
    head, tail = CASES[name]
    text = head + PADDING + tail
    _, ok, _ = trim_block_safe(text, 300)
    assert ok is False, f"qualifier {name!r} would be truncated away"


def test_control_without_qualifier_still_trims():
    text = "The clinic opened in June with three rooms. " + PADDING
    head, ok, _ = trim_block_safe(text, 300)
    assert ok is True and len(head) <= 340


def test_qualifier_inside_kept_head_does_not_block():
    # Qualifier fully inside the kept head is safe: nothing is cut away.
    text = "Approve, except for sealed files, the rest now. " + PADDING
    head, ok, _ = trim_block_safe(text, 300)
    assert ok is True
    assert "except" in head


def test_negation_consent_kept_whole():
    text = (
        "The patient consented to the procedure. "
        + PADDING
        + "The patient did not consent to data sharing."
    )
    _, ok, _ = trim_block_safe(text, 300)
    assert ok is False
