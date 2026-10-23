"""Stash lifecycle: gc never deletes a referenced blob, survives a concurrent put, verify
catches a planted missing or corrupt blob, and nothing is deleted by default."""

from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.cli import app
from lcc.mcp_server import handle_message
from lcc.relevance import stash_lifecycle
from lcc.relevance.stash_lifecycle import gc, ls, parse_age, verify
from lcc.relevance.transcript_stash import (
    StashError,
    StashMissing,
    put,
    read_sidecar,
    recall,
    session_hash,
    stash_note,
)

OLD = 400 * 86400  # seconds since a blob was last used, well past any threshold below


@pytest.fixture(autouse=True)
def _stash(monkeypatch, tmp_path: Path) -> Path:
    stash = tmp_path / "stash"
    monkeypatch.setenv("LCC_STASH_DIR", str(stash))
    return stash


def age(stash: Path, digest: str, seconds: float = OLD) -> None:
    then = time.time() - seconds
    os.utime(stash / digest, (then, then))


def transcript(path: Path, digests: list[str]) -> Path:
    """A Claude Code style JSONL whose tool results are stash pointers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": stash_note("x\n" * 50, d)}]}}
        for d in digests
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


@pytest.mark.parametrize("seed", range(40))
def test_gc_never_deletes_a_referenced_blob(seed: int, tmp_path: Path, monkeypatch) -> None:
    """Random blob sets, random referenced subsets spread over random files: gc --apply with
    every blob past the threshold removes exactly the unreferenced ones."""
    rng = random.Random(seed)
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    texts = list({f"out {rng.random()}\n" * rng.randint(1, 30) for _ in range(rng.randint(1, 12))})
    digests = [put(t) for t in texts]
    for d in digests:
        age(tmp_path / "stash", d)
    referenced = {d for d in digests if rng.random() < 0.5}
    files = rng.randint(1, 3)
    refs = sorted(referenced)
    for i in range(files):
        transcript(tmp_path / "projects" / f"p{i}" / "s.jsonl", refs[i::files])

    report = gc([tmp_path / "projects"], parse_age("1d"), apply=True)

    for d in digests:
        assert (tmp_path / "stash" / d).exists() == (d in referenced)
    assert sorted(report["removed"]) == sorted(set(digests) - referenced)
    for d in referenced:
        assert recall(d[:12]) == texts[digests.index(d)]


def test_gc_is_a_dry_run_by_default_and_keeps_young_blobs(_stash: Path, tmp_path: Path) -> None:
    old, young = put("old output\n" * 20), put("young output\n" * 20)
    age(_stash, old)
    (tmp_path / "projects").mkdir()

    report = gc([tmp_path / "projects"], parse_age("30d"))

    assert report["candidates"] == [old] and report["removed"] == []
    assert (_stash / old).exists() and (_stash / young).exists()
    gc([tmp_path / "projects"], parse_age("30d"), apply=True)
    assert not (_stash / old).exists() and not (_stash / f"{old}.json").exists()
    assert (_stash / young).exists()


def test_recall_counts_as_use(_stash: Path, tmp_path: Path) -> None:
    digest = put("recalled lately\n" * 20)
    age(_stash, digest)
    recall(digest[:12])
    (tmp_path / "projects").mkdir()
    assert gc([tmp_path / "projects"], parse_age("30d"), apply=True)["removed"] == []


def test_gc_fails_closed(_stash: Path, tmp_path: Path) -> None:
    digest = put("secret\n" * 20)
    age(_stash, digest)
    with pytest.raises(StashError, match="none of the transcript roots exist"):
        gc([tmp_path / "nowhere"], 0, apply=True)
    projects = tmp_path / "projects"
    locked = transcript(projects / "s.jsonl", [])
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("running as root: chmod 0 does not block reads")
        with pytest.raises(StashError, match="deletes nothing"):
            gc([projects], 0, apply=True)
    finally:
        locked.chmod(0o600)
    assert (_stash / digest).exists()


def test_gc_apply_refuses_without_posix_locks(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stash_lifecycle, "_is_windows", lambda: True)
    (tmp_path / "projects").mkdir()
    with pytest.raises(StashError, match="POSIX"):
        gc([tmp_path / "projects"], 0, apply=True)


def test_concurrent_put_survives_gc(_stash: Path, tmp_path: Path, monkeypatch) -> None:
    """gc has scanned and picked the blob as a candidate; a put lands before gc takes the
    exclusive lock (so no pointer exists yet). The put makes the blob young again and gc's
    re-check under the lock keeps it."""
    text = "reused output\n" * 20
    digest = put(text)
    age(_stash, digest)
    (tmp_path / "projects").mkdir()
    about_to_lock, put_done = threading.Event(), threading.Event()
    real_lock = stash_lifecycle.stash_lock

    def late_lock(root, *, exclusive=False):
        about_to_lock.set()
        assert put_done.wait(5)
        return real_lock(root, exclusive=exclusive)

    monkeypatch.setattr(stash_lifecycle, "stash_lock", late_lock)
    reports: list[dict] = []
    worker = threading.Thread(
        target=lambda: reports.append(gc([tmp_path / "projects"], parse_age("1d"), apply=True))
    )
    worker.start()
    assert about_to_lock.wait(5)
    assert put(text) == digest  # the pointer would be written after this returns
    put_done.set()
    worker.join(5)
    assert reports[0]["candidates"] == [digest] and reports[0]["removed"] == []
    assert recall(digest[:12]) == text


def test_put_waits_for_gc_lock(_stash: Path) -> None:
    from lcc.relevance.transcript_stash import stash_lock

    put("prime the stash dir\n" * 5)
    finished = threading.Event()
    with stash_lock(_stash, exclusive=True):
        thread = threading.Thread(target=lambda: (put("blocked\n" * 5), finished.set()))
        thread.start()
        assert not finished.wait(0.3)
    assert finished.wait(5)


def test_verify_catches_planted_missing_and_corrupt_blobs(_stash: Path, tmp_path: Path) -> None:
    good, gone, bad = (put(f"output {n}\n" * 20) for n in range(3))
    session = transcript(tmp_path / "s.jsonl", [good, gone, bad])
    assert verify(session) == []

    (_stash / gone).unlink()
    (_stash / bad).write_bytes(b"tampered")

    assert verify(session) == [
        {"id": gone[:12], "problem": "missing"},
        {"id": bad[:12], "problem": "hash_mismatch"},
    ]
    result = CliRunner().invoke(app, ["stash", "verify", str(session)])
    assert result.exit_code == 1 and gone[:12] in result.stdout


def test_missing_blob_error_says_how_to_recover(_stash: Path) -> None:
    digest = put("gone soon\n" * 20)
    (_stash / digest).unlink()
    with pytest.raises(StashMissing, match="re-read the file or re-run the command"):
        recall(digest[:12])
    reply = handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall", "arguments": {"id": digest[:12]}},
    })
    assert "re-read the file" in json.dumps(reply)


def test_sidecar_holds_hashes_and_times_only(_stash: Path, tmp_path: Path) -> None:
    digest = put("SECRET=hunter2\n" * 5, session="session-abc")
    raw = (_stash / f"{digest}.json").read_text()
    assert "hunter2" not in raw and "session-abc" not in raw
    meta = read_sidecar(_stash / digest)
    assert meta["sessions"] == [session_hash("session-abc")]
    assert {"created_at", "last_put_at"} <= meta.keys()
    if os.name != "nt":
        assert (_stash / f"{digest}.json").stat().st_mode & 0o777 == 0o600

    transcript(tmp_path / "projects" / "s.jsonl", [digest])
    (row,) = ls([tmp_path / "projects"])
    assert row["id"] == digest[:12] and row["refs"] == 1 and row["sessions"] == 1 and row["lines"] == 5


def test_cli_gc_dry_run_deletes_nothing(_stash: Path, tmp_path: Path) -> None:
    digest = put("old\n" * 30)
    age(_stash, digest)
    (tmp_path / "projects").mkdir()
    result = CliRunner().invoke(app, ["stash", "gc", "--root", str(tmp_path / "projects")])
    assert result.exit_code == 0, result.output
    assert f"would remove {digest[:12]}" in result.stdout and (_stash / digest).exists()
