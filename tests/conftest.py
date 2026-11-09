"""Suite-wide isolation: no test reaches the developer's real lcc state.

A developer shell can export ``LCC_LEDGER=1``, ``LCC_REQUEST_LOG=1`` or ``LCC_AUTO_REMOTE=1``,
and the ledger, request log, stash and Jev ledger default to paths outside the checkout. A
test that exercises one of them sets the variable itself; ``monkeypatch`` puts this baseline
back afterwards.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_lcc_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    state = tmp_path_factory.mktemp("lcc-state")
    for flag in ("LCC_LEDGER", "LCC_REQUEST_LOG", "LCC_AUTO_REMOTE"):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setenv("LCC_LEDGER_PATH", str(state / "ledger.jsonl"))
    monkeypatch.setenv("LCC_REQUEST_LOG_DIR", str(state / "request-log"))
    monkeypatch.setenv("LCC_STASH_DIR", str(state / "stash"))
    monkeypatch.setenv("LCC_TS_LEDGER", str(state / "jev.jsonl"))
