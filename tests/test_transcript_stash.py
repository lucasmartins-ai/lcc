"""provider="rules", rules_mode="stashed": removed outputs go to a local content-addressed stash.

The exact bytes of every removed result are written to ``<stash>/<sha256>`` and the result is
replaced by ``[removed: N lines, S KB · lcc recall <sha12>]``. ``recall`` re-hashes on read, so what
comes back is provably what was removed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lcc.relevance.transcript as transcript_module
from lcc.cli import app
from lcc.mcp_server import handle_message
from lcc.relevance.transcript import (
    TranscriptCompactionRequest,
    TranscriptError,
    compact_transcript,
    messages_to_payload,
)
from lcc.relevance.transcript_stash import StashError, put, recall, stash_dir, verify_stashed

NOTE = re.compile(r"^\[removed: (\d+) lines?, (\d+(?:\.\d)? K?B) · lcc recall ([0-9a-f]{12})\]$")
BODY = "\n".join(f"line {n} of the old parser module" for n in range(1, 80))


@pytest.fixture(autouse=True)
def _stash(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    stash = tmp_path / "stash"
    monkeypatch.setenv("LCC_STASH_DIR", str(stash))

    def refuse(*_args, **_kwargs):
        raise AssertionError("provider='rules' must never resolve a judge")

    monkeypatch.setattr(transcript_module, "_resolve_client", refuse)
    return stash


def convo(*calls: tuple[str, dict, str]) -> list[dict]:
    messages: list[dict] = [{"role": "user", "text": "fix the parser"}]
    for n, (tool, tool_input, output) in enumerate(calls, start=1):
        messages.append(
            {
                "role": "assistant",
                "text": f"step {n}",
                "toolUses": [{"id": f"c{n}", "tool": tool, "input": tool_input}],
            }
        )
        messages.append(
            {"role": "user", "text": "", "toolResults": [{"id": f"c{n}", "text": output}]}
        )
    messages.append({"role": "assistant", "text": "done"})
    return messages


def run(messages: list[dict], mode: str = "stashed"):
    original = copy.deepcopy(messages)
    result = compact_transcript(
        TranscriptCompactionRequest(
            payload={"messages": messages},
            question="fix the parser",
            provider="rules",
            preserve_recent=1,
            rules_mode=mode,
        )
    )
    assert messages == original, "the input payload must not be mutated"
    return result, messages_to_payload(result.messages), {d["id"]: d for d in result.decisions}


def result_text(payload: list[dict], call_id: str) -> str:
    for message in payload:
        for res in message.get("toolResults", []):
            if res["tool_use_id"] == call_id:
                return res["text"]
    raise KeyError(call_id)


def stale_read_session() -> list[dict]:
    # Old reads of files nothing writes later: recoverable would replace c1 and c2.
    return convo(
        ("Read", {"file_path": "/repo/src/old.py"}, BODY),
        ("Read", {"file_path": "/repo/src/other.py"}, BODY.replace("old", "other")),
        (
            "Read",
            {"file_path": "/repo/src/missing.py"},
            "<tool_use_error>File does not exist: /repo/src/missing.py and more words here</tool_use_error>",
        ),
    )


def test_removed_output_is_stashed_verbatim_and_pointer_replaces_it(_stash: Path):
    messages = stale_read_session()
    result, compacted, by_id = run(messages)

    decision = by_id["c1"]
    assert decision["decision"] == "replace"
    assert decision["reason"].startswith("stashed:")
    note = result_text(compacted, "c1")
    match = NOTE.match(note)
    assert match, note
    digest = hashlib.sha256(BODY.encode()).hexdigest()
    assert decision["stash"]["sha256"] == digest
    assert match.group(3) == digest[:12]
    assert int(match.group(1)) == len(BODY.splitlines())
    assert match.group(2) == f"{len(BODY) / 1024:.1f} KB"

    blob = _stash / digest
    assert blob.read_bytes() == BODY.encode()
    if os.name != "nt":
        assert stat.S_IMODE(blob.stat().st_mode) == 0o600
        assert stat.S_IMODE(_stash.stat().st_mode) == 0o700

    report = result.report
    assert report["rules_mode"] == "stashed"
    assert report["semantic_guarantee"] == "stashed"
    assert report["lossless_violations"] == []
    assert report["tool_calls_stashed"] >= 1
    assert report["stash_dir"] == str(_stash)
    # Calls, inputs and texts are never touched.
    assert [m.get("text") for m in compacted] == [m.get("text") for m in messages]
    assert verify_stashed({"messages": messages}, compacted) == []


def test_recall_returns_exact_bytes_and_line_ranges():
    messages = stale_read_session()
    _result, compacted, _ = run(messages)
    sha12 = NOTE.match(result_text(compacted, "c1")).group(3)

    assert recall(sha12) == BODY
    assert (
        recall(sha12, lines=(2, 3))
        == "line 2 of the old parser module\nline 3 of the old parser module\n"
    )


def test_recall_refuses_tampered_unknown_and_malformed_ids(_stash: Path):
    run(stale_read_session())
    digest = hashlib.sha256(BODY.encode()).hexdigest()
    (_stash / digest).write_bytes(b"tampered")
    with pytest.raises(StashError, match="hash"):
        recall(digest[:12])
    with pytest.raises(StashError, match="not found"):
        recall("0" * 12)
    for bad in ("../etc/passwd", "abc", "Z" * 12, ""):
        with pytest.raises(StashError):
            recall(bad)


def test_verify_stashed_rejects_pointer_without_blob(_stash: Path):
    messages = stale_read_session()
    _result, compacted, _ = run(messages)
    for blob in _stash.iterdir():
        blob.unlink()
    assert verify_stashed({"messages": messages}, compacted)


def test_protected_results_stay_verbatim():
    messages = stale_read_session()
    _result, compacted, by_id = run(messages)
    # The latest error and the pinned tail are never stashed.
    assert result_text(compacted, "c3").startswith("<tool_use_error>")
    assert by_id["c3"]["decision"] == "keep"


def test_existing_modes_do_not_stash(_stash: Path):
    for mode in ("lossless", "recoverable", "lossy"):
        result, _compacted, _ = run(stale_read_session(), mode=mode)
        assert "tool_calls_stashed" not in result.report or result.report["tool_calls_stashed"] == 0
    assert not _stash.exists()


def test_cli_recall(tmp_path: Path):
    _result, compacted, _ = run(stale_read_session())
    sha12 = NOTE.match(result_text(compacted, "c1")).group(3)
    out = CliRunner().invoke(app, ["recall", sha12, "--lines", "1-2"])
    assert out.exit_code == 0, out.output
    assert out.stdout == "line 1 of the old parser module\nline 2 of the old parser module\n"
    bad = CliRunner().invoke(app, ["recall", "../x"])
    assert bad.exit_code == 2


def test_mcp_recall_and_stashed_mode():
    messages = stale_read_session()
    response = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "compact_transcript",
                "arguments": {
                    "messages": messages,
                    "question": "fix the parser",
                    "provider": "rules",
                    "rules_mode": "stashed",
                    "preserve_recent": 1,
                },
            },
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    sha12 = NOTE.match(result_text(payload["messages"], "c1")).group(3)

    response = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "recall", "arguments": {"id": sha12, "lines": "3-3"}},
        }
    )
    recalled = json.loads(response["result"]["content"][0]["text"])
    assert recalled["text"] == "line 3 of the old parser module\n"
    assert recalled["sha256"].startswith(sha12)


def test_lossy_only_removal_is_stashed_not_trimmed(_stash: Path):
    # A big old build log is not re-readable (recoverable keeps it); lossy would trim it.
    log = "\n".join(f"compiling unit {n}" for n in range(600))
    filler = [("Read", {"file_path": f"/repo/f{n}.py"}, f"body {n}") for n in range(25)]
    messages = convo(("Bash", {"command": "make build"}, log), *filler)
    result, compacted, by_id = run(messages)

    assert by_id["c1"]["reason"] == "stashed:large_old_output_trimmed"
    assert recall(NOTE.match(result_text(compacted, "c1")).group(3)) == log
    assert result.report["lossless_violations"] == []


def test_note_does_not_depend_on_the_token_counter(monkeypatch: pytest.MonkeyPatch):
    """Invariant 5 across machines: with tiktoken or without it, one output, one placeholder."""
    from lcc.token_budget import counters

    def notes() -> str:
        _, compacted, _ = run(stale_read_session())
        return result_text(compacted, "c1")

    exact = notes()
    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", False)
    assert notes() == exact
    assert NOTE.match(exact)


def test_old_token_pointer_is_still_a_fixed_point():
    old = "[removed: 1380 tokens · lcc recall 0123456789ab]"
    messages = convo(("Read", {"file_path": "/repo/a.py"}, old), ("Bash", {"command": "ls"}, "ok"))
    _, compacted, by_id = run(messages)
    assert result_text(compacted, "c1") == old
    assert by_id["c1"]["decision"] != "replace"


def test_lone_surrogate_in_a_result_is_rejected_before_anything_is_stashed(_stash: Path):
    """stash_note and put encode strictly; parsing must reject a lone surrogate first."""
    body = BODY + "\n\ud800 dangling surrogate"
    messages = convo(
        ("Read", {"file_path": "/repo/src/old.py"}, body),
        ("Read", {"file_path": "/repo/src/other.py"}, BODY.replace("old", "other")),
        ("Bash", {"command": "ls"}, "ok"),
    )
    with pytest.raises(TranscriptError, match="unpaired surrogate"):
        run(messages)
    assert not _stash.exists() or not any(_stash.iterdir())


def test_stash_dir_windows_uses_localappdata(monkeypatch, tmp_path: Path):
    """Windows default is %LOCALAPPDATA%/lcc/stash; LCC_STASH_DIR still wins."""
    import lcc.relevance.transcript_stash as stash_mod

    monkeypatch.delenv("LCC_STASH_DIR", raising=False)
    monkeypatch.setattr(stash_mod, "_is_windows", lambda: True)
    local = tmp_path / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    assert stash_dir() == local / "lcc" / "stash"

    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(stash_mod.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert stash_dir() == tmp_path / "home" / "AppData" / "Local" / "lcc" / "stash"

    override = tmp_path / "custom-stash"
    monkeypatch.setenv("LCC_STASH_DIR", str(override))
    assert stash_dir() == override


def test_stash_dir_posix_uses_xdg_cache(monkeypatch, tmp_path: Path):
    import lcc.relevance.transcript_stash as stash_mod

    monkeypatch.delenv("LCC_STASH_DIR", raising=False)
    monkeypatch.setattr(stash_mod, "_is_windows", lambda: False)
    monkeypatch.setattr(stash_mod.Path, "home", classmethod(lambda cls: tmp_path))
    assert stash_dir() == tmp_path / ".cache" / "lcc" / "stash"


def test_put_skips_chmod_on_windows(monkeypatch, tmp_path: Path):
    import lcc.relevance.transcript_stash as stash_mod

    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    monkeypatch.setattr(stash_mod, "_is_windows", lambda: True)

    def refuse_chmod(*_args, **_kwargs):
        raise AssertionError("put must not call os.chmod on Windows")

    monkeypatch.setattr(stash_mod.os, "chmod", refuse_chmod)
    digest = put("windows stash body")
    assert (tmp_path / "stash" / digest).read_text(encoding="utf-8") == "windows stash body"
