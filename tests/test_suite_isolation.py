"""The suite never resolves the developer's real lcc state (tests/conftest.py)."""

from __future__ import annotations

import pytest

from lcc import receipt, request_log
from lcc.relevance.compactor import auto_remote_enabled
from lcc.relevance.jev import default_ledger_path
from lcc.relevance.transcript_stash import stash_dir


def test_lcc_state_resolves_under_the_pytest_temp_root(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    base = tmp_path_factory.getbasetemp()

    assert not receipt.ledger_enabled()
    assert not request_log.enabled()
    assert not auto_remote_enabled()
    for path in (receipt.ledger_path(), request_log.log_dir(), stash_dir(), default_ledger_path()):
        assert path is not None and path.is_relative_to(base), path
