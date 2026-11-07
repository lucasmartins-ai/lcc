"""Recall hint caches: the session index and the per-blob terms give the hints the slow path gives.

The slow path reads every sidecar and tokenises every candidate blob. A missing, stale, torn or
corrupt cache must send it back there, never change a hint.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from lcc.relevance import recall_hints as rh
from lcc.relevance.stash_lifecycle import gc, parse_age
from lcc.relevance.transcript_stash import (
    index_path,
    put,
    read_index,
    session_hash,
    sidecar_path,
    terms_path,
)

OLD = 400 * 86400


@pytest.fixture
def stash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "stash"
    monkeypatch.setenv("LCC_STASH_DIR", str(root))
    return root


@contextlib.contextmanager
def slow_path() -> Iterator[None]:
    """The code before the caches: every sidecar read, every blob tokenised, nothing written."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(rh, "read_index", lambda root, key: None)
        mp.setattr(rh, "append_index", lambda *a, **k: None)
        mp.setattr(rh, "_cached_terms", lambda blob: None)
        mp.setattr(rh, "_store_terms", lambda root, fresh: None)
        yield


@contextlib.contextmanager
def no_scan() -> Iterator[None]:
    """Fail if session_blobs lists the whole stash to read every sidecar."""
    def boom() -> list[str]:
        raise AssertionError("every sidecar read")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(rh, "_stash_names", boom)
        yield


@contextlib.contextmanager
def all_cached() -> Iterator[None]:
    """Fail if find_hints tokenises a blob: every blob it tokenises it stores."""
    def store(root: Path, fresh: dict[Path, list[str]]) -> None:
        assert not fresh, "a blob was tokenised"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(rh, "_store_terms", store)
        yield


def index_file(stash: Path, session: str) -> Path:
    key = session_hash(session)
    assert key
    return index_path(stash, key)


# --- the session index --------------------------------------------------------------------


def test_put_records_each_blob_and_the_first_hint_vouches_for_the_index(stash: Path) -> None:
    first = put("output of make check_7\n", session="s1")
    second = put("output of make check_8\n", session="s1")
    put("output of make check_8\n", session="s1")  # a re-put records it again, harmlessly
    path = index_file(stash, "s1")
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text() == f"\n{first}\n\n{second}\n\n{second}\n"
    assert read_index(stash, session_hash("s1") or "") is None  # no full scan yet

    expected = rh.session_blobs("s1")
    assert set(expected) == {first[:12], second[:12]}
    assert path.read_text().endswith("\nscanned\n")
    with no_scan():
        assert rh.session_blobs("s1") == expected


def test_a_session_that_never_stashed_scans_once(stash: Path) -> None:
    put("someone else's output\n", session="other")
    assert rh.session_blobs("quiet") == []
    with no_scan():
        assert rh.session_blobs("quiet") == []
    later = put("now it stashes order_77\n", session="quiet")
    with no_scan():
        assert rh.session_blobs("quiet") == [later[:12]]


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "never scanned",
        "torn record",
        "torn record then garbage",
        "not ascii",
        "a directory",
    ],
)
def test_an_index_that_cannot_vouch_falls_back_to_every_sidecar(stash: Path, damage: str) -> None:
    older = put("pytest output for ticket_42\n", session="s1")
    rh.session_blobs("s1")  # vouched
    newer = put("curl output for order_5521\n", session="s1")
    path = index_file(stash, "s1")
    # A blob the index lacks, as if an older lcc had stashed it: only the fallback finds it.
    lacking = path.read_text().replace(f"\n{older}\n", "")
    if damage == "missing":
        path.unlink()
    elif damage == "never scanned":
        path.write_text(lacking.replace("\nscanned\n", ""))
    elif damage == "torn record":
        path.write_text(lacking + "\n" + newer[:20])
    elif damage == "torn record then garbage":
        path.write_text(lacking + "\nxyz\n" + f"\n{newer}\n")
    elif damage == "not ascii":
        path.write_bytes(lacking.encode() + "\nMüller\n".encode())
    else:
        path.unlink()
        path.mkdir()
    with slow_path():
        expected = rh.session_blobs("s1")
    assert set(expected) == {older[:12], newer[:12]}
    assert rh.session_blobs("s1") == expected
    if damage != "a directory":  # vouched again by the scan it just made
        with no_scan():
            assert rh.session_blobs("s1") == expected


def test_a_torn_record_before_a_later_scan_is_ignored(stash: Path) -> None:
    digest = put("trace for invoice_991\n", session="s1")
    index_file(stash, "s1").write_text(f"\n{digest}\n\nabc")
    assert rh.session_blobs("s1") == [digest[:12]]  # torn after the last scan: falls back
    with no_scan():
        assert rh.session_blobs("s1") == [digest[:12]]


def test_stale_records_are_checked_against_the_sidecar(stash: Path) -> None:
    gone = put("removed by gc: build_1\n", session="s1")
    moved = put("sidecar lost s1: build_2\n", session="s1")
    early = put("put early: build_3\n", session="s1")
    late = put("put late: build_4\n", session="s1")
    rh.session_blobs("s1")
    (stash / gone).unlink()  # gc removed the blob; the record stays
    sidecar_path(stash / moved).write_text('{"sessions": ["0000000000000000"]}')
    time.sleep(0.01)
    put("put early: build_3\n", session="s2")  # another session's put makes it the newest
    with no_scan():
        fast = rh.session_blobs("s1")
    with slow_path():
        assert fast == rh.session_blobs("s1") == [early[:12], late[:12]]


def test_a_failed_index_write_removes_the_index(stash: Path) -> None:
    import lcc.relevance.transcript_stash as ts

    first = put("first output, check_1\n", session="s1")
    rh.session_blobs("s1")

    def full_disk(*_: object, **__: object) -> None:
        raise OSError(28, "No space left on device")

    with pytest.MonkeyPatch.context() as mp:  # not the fixture's: undo would drop the stash env
        mp.setattr(ts, "append_index", full_disk)
        second = put("second output, check_2\n", session="s1")
    assert not index_file(stash, "s1").exists()
    assert set(rh.session_blobs("s1")) == {first[:12], second[:12]}


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX file modes")
def test_a_scan_with_an_unreadable_sidecar_does_not_vouch(stash: Path) -> None:
    readable = put("output of make check_7\n", session="s1")
    hidden = put("output of make check_8\n", session="s1")
    index_file(stash, "s1").unlink()
    sidecar_path(stash / hidden).chmod(0)
    try:
        assert rh.session_blobs("s1") == [readable[:12]]  # as the slow path answers now
        assert read_index(stash, session_hash("s1") or "") is None
    finally:
        sidecar_path(stash / hidden).chmod(0o600)
    with slow_path():
        expected = rh.session_blobs("s1")
    assert set(expected) == {readable[:12], hidden[:12]}
    assert rh.session_blobs("s1") == expected
    with no_scan():
        assert rh.session_blobs("s1") == expected


def test_a_rebuild_waits_for_a_put_whose_record_failed(stash: Path) -> None:
    """A hint that rebuilds the index while such a put is between dropping the index and writing
    its sidecar would vouch for an index without that blob."""
    import threading

    import lcc.relevance.transcript_stash as ts

    first = put("first output, check_1\n", session="s1")
    rh.session_blobs("s1")
    hint = threading.Thread(target=rh.session_blobs, args=("s1",))
    write_private = ts._write_private

    def full_disk(*_: object, **__: object) -> None:
        raise OSError(28, "No space left on device")

    def blob_write(path: Path, data: bytes) -> None:
        if hint.ident is None:  # the blob's write, after the index was dropped
            hint.start()
            hint.join(timeout=0.5)  # unlocked, the hint scans and vouches here
        write_private(path, data)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ts, "append_index", full_disk)
        mp.setattr(ts, "_write_private", blob_write)
        second = put("second output, check_2\n", session="s1")
    hint.join(timeout=10)
    assert not hint.is_alive()
    with no_scan():
        fast = rh.session_blobs("s1")
    with slow_path():
        assert fast == rh.session_blobs("s1")
    assert set(fast) == {first[:12], second[:12]}


# --- the terms cache ----------------------------------------------------------------------


def test_terms_are_cached_per_blob_and_reused(stash: Path) -> None:
    lab = put("Dear colleague,\nwe report on Anna Müller, admitted 2019-03-14.\nHb 9.1 g/dl\n")
    other = put("Dear colleague,\nwe report on John Smith, admitted 2020-01-02.\n")
    prompt = "What was Anna Müller's haemoglobin on 2019-03-14?"
    first = rh.find_hints(prompt, [lab[:12], other[:12]])
    assert [h.id for h in first] == [lab[:12]]
    cache = terms_path(stash / lab)
    assert cache.stat().st_mode & 0o777 == 0o600
    assert "müller" in cache.read_text(encoding="utf-8").split("\n")
    with all_cached():
        assert rh.find_hints(prompt, [lab[:12], other[:12]]) == first


@pytest.mark.parametrize(
    "damage",
    ["empty", "other version", "body edited", "truncated", "bad utf-8, good hash", "another blob's"],
)
def test_a_damaged_terms_cache_is_rebuilt(
    stash: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    digest = put("pytest output: FAILED tests/test_api.py::test_refund_77\n")
    other = put("pytest output: passed tests/test_api.py::test_login\n")
    prompt = "why does test_refund_77 fail?"
    expected = rh.find_hints(prompt, [digest[:12]])
    assert expected
    rh.find_hints(prompt, [other[:12]])
    cache = terms_path(stash / digest)
    good = cache.read_bytes()
    if damage == "empty":
        cache.write_bytes(b"")
    elif damage == "other version":
        monkeypatch.setattr(rh, "TERMS_VERSION", rh.TERMS_VERSION + 1)
    elif damage == "body edited":
        cache.write_bytes(good.replace(b"test_refund_77", b"test_refund_78"))
    elif damage == "truncated":
        cache.write_bytes(good[:-5])
    elif damage == "bad utf-8, good hash":
        body = b"\xff\nfailed"
        cache.write_bytes(rh._terms_head(stash / digest, body) + b"\n" + body)
    else:  # intact, but it lists the words of the other blob
        cache.write_bytes(terms_path(stash / other).read_bytes())
    with slow_path():
        assert rh.find_hints(prompt, [digest[:12]]) == expected
    assert rh.find_hints(prompt, [digest[:12]]) == expected
    assert rh._cached_terms(stash / digest) is not None  # rewritten valid
    with all_cached():
        assert rh.find_hints(prompt, [digest[:12]]) == expected


def test_a_prompt_with_more_terms_than_a_blob_matches_the_same(stash: Path) -> None:
    short = put("FAILED test_refund_77 in src/billing/refund.py\n")
    long = put(" ".join(f"order_{n}" for n in range(3000)) + " test_refund_77\n")
    pasted = " ".join(f"line_{n} order_{n}" for n in range(0, 3000, 7)) + " test_refund_77"
    ids = [short[:12], long[:12]]
    with slow_path():
        expected = rh.find_hints(pasted, ids)
    assert rh.find_hints(pasted, ids) == expected  # tokenises and stores
    with all_cached():
        assert rh.find_hints(pasted, ids) == expected


def test_a_corrupt_blob_gets_no_terms_and_no_hint(stash: Path) -> None:
    digest = put("trace for ticket_42\n")
    assert rh.find_hints("ticket_42 again", [digest[:12]])
    (stash / digest).write_text("tampered: ticket_42 ticket_42\n")
    assert rh.find_hints("ticket_42 again", [digest[:12]]) == []  # cached terms do not vouch
    terms_path(stash / digest).unlink()
    assert rh.find_hints("ticket_42 again", [digest[:12]]) == []
    assert not terms_path(stash / digest).exists()


def test_terms_are_not_written_for_a_blob_gc_removed_meanwhile(stash: Path) -> None:
    digest = put("trace for ticket_42\n")
    rh._store_terms(stash, {stash / ("f" * 64): ["ticket_42"]})  # blob already gone
    assert not terms_path(stash / ("f" * 64)).exists()
    rh._store_terms(stash, {stash / digest: ["ticket_42"]})
    assert rh._cached_terms(stash / digest) == ["ticket_42"]


# --- gc -----------------------------------------------------------------------------------


def test_gc_removes_terms_with_their_blob_and_old_caches_as_leftovers(
    stash: Path, tmp_path: Path
) -> None:
    old = put("old output, build_9\n" * 20, session="s-old")
    young = put("young output, build_10\n" * 20, session="s-young")
    rh.find_hints("build_9 build_10", [old[:12], young[:12]])
    orphan = terms_path(stash / ("e" * 64))  # e.g. a gc from before the terms cache: goes now
    orphan.write_text("lcc-terms leftover")
    then = time.time() - OLD
    for path in (stash / old, index_file(stash, "s-old")):
        os.utime(path, (then, then))
    (tmp_path / "projects").mkdir()
    report = gc([tmp_path / "projects"], parse_age("30d"), apply=True)
    assert report["removed"] == [old]
    assert not terms_path(stash / old).exists() and terms_path(stash / young).exists()
    assert sorted(report["leftovers"]) == sorted([orphan.name, index_file(stash, "s-old").name])
    assert not orphan.exists() and not index_file(stash, "s-old").exists()
    assert index_file(stash, "s-young").exists()
    assert rh.session_blobs("s-young") == [young[:12]]


def test_gc_removes_the_terms_before_the_blob(stash: Path, tmp_path: Path) -> None:
    old = put("old output, build_9\n" * 20)
    rh.find_hints("build_9", [old[:12]])
    sidecar_path(stash / old).unlink()
    sidecar_path(stash / old).mkdir()  # its removal fails after the blob's
    then = time.time() - OLD
    os.utime(stash / old, (then, then))
    (tmp_path / "projects").mkdir()
    with pytest.raises(OSError):
        gc([tmp_path / "projects"], parse_age("30d"), apply=True)
    assert not terms_path(stash / old).exists()


# --- the property: cached and uncached paths agree ------------------------------------------

VOCAB = [
    "alpha_1", "beta_22", "Gamma", "delta", "zebrafish", "Anna", "Müller", "Straße", "STRASSE",
    "src/app/main.py", "tests/test_x.py::test_y_3", "order_5521", "2019-03-14", "réseau",
    "verifyStashed", "x.y.z", "word", "ticket_42", "ΣΊΣΥΦΟΣ",
]
DAMAGE = [
    "drop index", "unscanned index", "torn index", "drop terms", "edit terms",
    "old terms", "swap terms", "gc a blob", "corrupt a blob", "re-put elsewhere",
]
PROPERTY = settings(
    max_examples=25, deadline=None, database=None, derandomize=True,
    suppress_health_check=list(HealthCheck),
)


def _outputs(prompts: list[str], extra: list[str]) -> list[object]:
    out: list[object] = []
    for session in ("s1", "s2"):
        ids = rh.session_blobs(session)
        out.append(ids)
        for prompt in prompts:
            out.append(rh.find_hints(prompt, [*extra, *ids]))
    return out


def _damage(stash: Path, kind: str, pick: int) -> None:
    blobs = sorted(p for p in stash.iterdir() if len(p.name) == 64 and p.is_file())
    blob = blobs[pick % len(blobs)] if blobs else None
    index = index_file(stash, "s1")
    if kind == "drop index":
        index.unlink(missing_ok=True)
    elif kind == "unscanned index" and index.exists():
        records = [r for r in index.read_text().split("\n") if r and r != "scanned"]
        index.write_text("".join(f"\n{r}\n" for r in records[1:]))  # and one record lost
    elif kind == "torn index" and index.exists():  # a short write whose put still went through
        text = index.read_text()
        records = [r for r in text.split("\n") if len(r) == 64]
        if records:
            lost = records[pick % len(records)]
            index.write_text(text.replace(f"\n{lost}\n", "") + "\n" + lost[:20])
    elif blob is None or (kind.endswith("terms") and not terms_path(blob).exists()):
        return
    elif kind == "re-put elsewhere":
        put(blob.read_text(encoding="utf-8", errors="replace"), session="s3")
    elif kind == "drop terms":
        terms_path(blob).unlink()
    elif kind == "edit terms":  # the blob now seems to hold every word: the hash must catch it
        head = terms_path(blob).read_bytes().partition(b"\n")[0]
        every = sorted({t.casefold() for t in rh._tokens(" ".join(VOCAB))})
        terms_path(blob).write_bytes(head + b"\n" + "\n".join(every).encode())
    elif kind == "old terms":
        raw = terms_path(blob).read_bytes()
        terms_path(blob).write_bytes(raw.replace(b"lcc-terms 1 ", b"lcc-terms 0 ", 1))
    elif kind == "swap terms":  # another blob's intact list
        donors = [b for b in blobs if b != blob and terms_path(b).exists()]
        if donors:
            terms_path(blob).write_bytes(terms_path(donors[0]).read_bytes())
    elif kind == "gc a blob":
        blob.unlink()
    elif kind == "corrupt a blob":
        blob.write_bytes(blob.read_bytes() + b" ticket_42")


# One damage per case, so each is drawn on every example (a random list rarely drew some).
@pytest.mark.parametrize("kind", ["none", *DAMAGE])
@PROPERTY
@given(
    blobs=st.lists(
        st.tuples(
            st.lists(st.sampled_from(VOCAB), min_size=1, max_size=8),
            st.sets(st.sampled_from(["s1", "s2"])),
        ),
        min_size=1,
        max_size=8,
    ),
    prompts=st.lists(
        st.lists(st.sampled_from([*VOCAB, "what", "the", "fix"]), min_size=1, max_size=5).map(
            " ".join
        ),
        min_size=1,
        max_size=3,
    ),
    pick=st.integers(0, 7),
)
def test_cached_and_uncached_paths_give_the_same_hints(
    kind: str, blobs: list[tuple[list[str], set[str]]], prompts: list[str], pick: int
) -> None:
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        stash = Path(tmp) / "stash"
        mp.setenv("LCC_STASH_DIR", str(stash))
        ids = []
        for n, (words, sessions) in enumerate(blobs):
            text = f"output {n}\n" + " ".join(words) + "\n"
            for session in sorted(sessions) or [None]:
                ids.append(put(text, session=session)[:12])
        extra = [ids[0], "0123456789ab"]  # a transcript pointer and one to a missing blob
        cold = _outputs(prompts, extra)  # builds the caches and vouches for the indexes
        _damage(stash, kind, pick)
        fast = _outputs(prompts, extra)
        assert _outputs(prompts, extra) == fast  # the caches it just rebuilt agree too
        with slow_path():
            assert _outputs(prompts, extra) == fast
        assert kind != "none" or cold == fast
