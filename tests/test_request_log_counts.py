"""Regression cases for issue #72: preserve counts without exposing credentials."""

import pytest

from lcc.request_log import redact


@pytest.mark.parametrize("goal", ["max_tokens=4000", "tokens: 500", "max-tokens = 4000"])
def test_token_counts_survive(goal):
    assert redact(goal) == goal


@pytest.mark.parametrize(
    "goal",
    [
        "api_key=example",
        "access_token: example",
        "GITHUB_TOKEN=example",
        "otp_secret=482913",
        "password=123456",
        "api_key=4000",
        "access_token=4000",
        "GITHUB_TOKEN=4000",
        "tokens=4000abc",
        "max_tokens=4000-credential",
        "secret_max_tokens=4000",
    ],
)
def test_secret_assignments_stay_redacted(goal):
    assert redact(goal) == "<TOKEN>"


def test_counts_and_credentials_in_one_goal():
    assert redact("max_tokens=4000 tokens: 500 api_key=example") == (
        "max_tokens=4000 tokens: 500 <TOKEN>"
    )
