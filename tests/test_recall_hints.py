"""Recall hints: a new prompt that names a stashed output gets one line pointing at its id."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.cli import app
from lcc.relevance.recall_hints import (
    find_hints,
    hint_line,
    hints_for,
    refs_in,
    search,
    session_blobs,
    terms,
)
from lcc.relevance.transcript_stash import put


@pytest.fixture
def stash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "stash"
    monkeypatch.setenv("LCC_STASH_DIR", str(root))
    return root


def note(digest: str) -> str:
    return f"[removed: 3 lines, 0.1 KB · lcc recall {digest[:12]}]"


# --- references and terms ---------------------------------------------------------------


def test_refs_in_lists_each_id_once_most_recent_first() -> None:
    text = (
        "[removed: 4 lines, 1.2 KB · lcc recall aaaaaaaaaaaa]\n"
        '{"content":"[removed: 9 lines, 3 KB \\u00b7 exit 1 \\u00b7 lcc recall bbbbbbbbbbbb]"}\n'
        "later: lcc recall aaaaaaaaaaaa\n"
        "not an id: lcc recall xyz, lcc recall ABCDEF123456"
    )
    assert refs_in(text) == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    assert refs_in("") == []


def test_terms_weigh_identifiers_above_names_above_words() -> None:
    weights = terms("Fix verifyStashed in src/lcc/x.py before 2019-03-14 for Anna Müller, please")
    assert weights["verifystashed"] == 3
    assert weights["src/lcc/x.py"] == 3
    assert weights["2019-03-14"] == 3
    assert weights["anna"] == 2  # capitalised, not the first word
    assert weights["müller"] == 2
    assert "fix" not in weights  # under 4 characters
    assert "please" not in weights  # stop word
    assert "for" not in weights


# --- matching ---------------------------------------------------------------------------


def test_a_prompt_naming_one_stashed_output_gets_one_hint(stash: Path) -> None:
    lab = put("Dear colleague,\nwe report on Anna Müller, admitted 2019-03-14.\nHb 9.1 g/dl\n")
    other = put("Dear colleague,\nwe report on John Smith, admitted 2020-01-02.\n")
    found = find_hints("What was Anna Müller's haemoglobin on 2019-03-14?", [lab[:12], other[:12]])
    assert [h.id for h in found] == [lab[:12]]
    assert set(found[0].terms) >= {"2019-03-14", "anna", "müller"}
    line = hint_line(found[0])
    assert line.endswith(f"lcc recall {lab[:12]}")
    assert '"Dear colleague, we report on Anna' in line
    assert line.isprintable()


def test_common_words_alone_never_hint(stash: Path) -> None:
    digest = put("the build output says what changed and where it failed\n")
    assert find_hints("what changed in the build and where did it fail?", [digest[:12]]) == []


def test_a_three_way_tie_is_ambiguous_but_two_is_shown(stash: Path) -> None:
    ids = [put(f"log for job_{n}\n")[:12] for n in (1, 2, 3)]
    assert find_hints("compare job_1 job_2 job_3", ids) == []
    two = find_hints("compare job_1 and job_2", ids)
    assert sorted(h.id for h in two) == sorted(ids[:2])


def test_missing_and_muted_ids_are_skipped(stash: Path) -> None:
    digest = put("trace for ticket_42\n")
    assert find_hints("ticket_42 again", ["0123456789ab", digest[:12]]) != []
    assert find_hints("ticket_42 again", [digest[:12]], muted={digest[:12]}) == []


def test_hints_are_deterministic_and_capped(stash: Path) -> None:
    ids = [put(f"record {n}: patient_{n}\n")[:12] for n in range(5)]
    prompt = "patient_0 patient_1 patient_2"
    first = find_hints(prompt, ids)
    assert first == find_hints(prompt, list(reversed(ids)))
    assert len(first) <= 2


# --- sources and fatigue ----------------------------------------------------------------


def test_session_blobs_come_from_the_sidecar(stash: Path) -> None:
    mine = put("output of make check_7\n", session="session-a")
    put("output of make check_8\n", session="session-b")
    assert session_blobs("session-a") == [mine[:12]]
    assert session_blobs(None) == []
    found = hints_for("rerun check_7", transcript=None, session_id="session-a")
    assert [h.id for h in found] == [mine[:12]]


def test_an_id_hinted_twice_is_muted_for_that_session(stash: Path) -> None:
    digest = put("stack trace for invoice_991\n")
    transcript = note(digest)
    shown = [
        len(hints_for("invoice_991 fails", transcript=transcript, session_id="s1"))
        for _ in range(3)
    ]
    assert shown == [1, 1, 0]
    # Another session starts fresh; without a session id nothing is remembered.
    assert len(hints_for("invoice_991 fails", transcript=transcript, session_id="s2")) == 1
    assert [
        len(hints_for("invoice_991", transcript=transcript, session_id=None)) for _ in range(3)
    ] == [1, 1, 1]


# --- CLI and the Claude Code hook -------------------------------------------------------


def test_cli_prints_one_line_per_hint(stash: Path, tmp_path: Path) -> None:
    digest = put("pytest output: FAILED tests/test_api.py::test_refund_77\n")
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"content": note(digest)}) + "\n", encoding="utf-8")
    out = CliRunner().invoke(
        app, ["hint", "why does test_refund_77 fail?", "--transcript", str(transcript)]
    )
    assert out.exit_code == 0, out.output
    assert out.output.strip().endswith(f"lcc recall {digest[:12]}")
    empty = CliRunner().invoke(app, ["hint", "hello there", "--transcript", str(transcript)])
    assert empty.exit_code == 0 and empty.output == ""


def test_hook_mode_answers_claude_code_with_additional_context(stash: Path, tmp_path: Path) -> None:
    digest = put("curl output for order_5521: 502 Bad Gateway\n")
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"content": note(digest)}) + "\n", encoding="utf-8")
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s-hook",
        "transcript_path": str(transcript),
        "prompt": "retry order_5521",
    }
    out = CliRunner().invoke(app, ["hint", "--hook"], input=json.dumps(event))
    assert out.exit_code == 0, out.output
    answer = json.loads(out.output)
    context = answer["hookSpecificOutput"]["additionalContext"]
    assert answer["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert f"lcc recall {digest[:12]}" in context


@pytest.mark.parametrize("stdin", ["", "not json", "[]", json.dumps({"prompt": 3})])
def test_hook_mode_never_fails_the_prompt(stash: Path, stdin: str) -> None:
    out = CliRunner().invoke(app, ["hint", "--hook"], input=stdin)
    assert out.exit_code == 0
    assert out.output == ""


def test_hook_mode_survives_a_missing_transcript(stash: Path, tmp_path: Path) -> None:
    event = {
        "session_id": "s",
        "transcript_path": str(tmp_path / "gone.jsonl"),
        "prompt": "order_1",
    }
    out = CliRunner().invoke(app, ["hint", "--hook"], input=json.dumps(event))
    assert out.exit_code == 0 and out.output == ""


def test_only_the_tail_of_a_huge_transcript_is_read(tmp_path: Path) -> None:
    from lcc.cli import _read_tail

    path = tmp_path / "big.jsonl"
    path.write_bytes(b"x" * 1000 + "tail ponto · lcc recall abcdefabcdef]".encode())
    tail = _read_tail(path, limit=60)
    assert tail.endswith("lcc recall abcdefabcdef]")
    assert len(tail.encode()) <= 60
    assert _read_tail(tmp_path / "missing.jsonl") == ""
    assert _read_tail(None) == ""


# --- regressions from the Codex review ---------------------------------------------------


def test_a_blob_over_the_byte_budget_is_skipped_unread(
    stash: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lcc.relevance.recall_hints as rh

    big = put("huge log of build_9000\n" + "x" * 5000)
    small = put("short note on build_1234\n")
    monkeypatch.setattr(rh, "MAX_BYTES", 1000)
    assert find_hints("build_9000 broke", [big[:12], small[:12]]) == []
    assert [h.id for h in find_hints("build_1234 broke", [big[:12], small[:12]])] == [small[:12]]


def test_a_huge_shared_identifier_does_not_blow_up_the_hint(stash: Path) -> None:
    ident = "id_" + "a" * 12000
    digest = put(f"value {ident}\n")
    found = find_hints(f"what is {ident}", [digest[:12]])
    line = hint_line(found[0])
    assert len(line) < 400
    assert line.endswith(f"lcc recall {digest[:12]}")


def test_every_shown_hint_beats_every_omitted_one_by_the_gap(stash: Path) -> None:
    six = put("aa_1 bb_2\n")[:12]  # 3 + 3
    five = put("cc_3 zebrafish\n")[:12]  # 3 + 2
    four = put("dd_4 apple\n")[:12]  # 3 + 1
    assert find_hints("check aa_1 bb_2 cc_3 Zebrafish dd_4 apple", [six, five, four]) == []


def test_scores_are_exact_at_the_threshold(stash: Path) -> None:
    # The target scores 1/7 + 3/7 + 3/7 + 2 = 3 exactly; float sums in hash order could miss it.
    ids = [put(f"orange aa_1 bb_2 copy {n}\n")[:12] for n in range(6)]
    target = put("orange aa_1 bb_2 zebrafish\n")[:12]
    found = find_hints("orange aa_1 bb_2 and the Zebrafish", [*ids, target])
    assert [h.id for h in found] == [target]


def test_a_full_sha_id_still_respects_the_byte_budget(
    stash: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lcc.relevance.recall_hints as rh

    big = put("huge log of build_9000\n" + "x" * 5000)
    monkeypatch.setattr(rh, "MAX_BYTES", 100)
    assert find_hints("build_9000 broke", [big]) == []


def test_hook_mode_survives_a_broken_matcher_import(
    stash: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "lcc.relevance.recall_hints", None)  # import raises
    event = {"session_id": "s", "transcript_path": "", "prompt": "order_1"}
    out = CliRunner().invoke(app, ["hint", "--hook"], input=json.dumps(event))
    assert out.exit_code == 0 and out.output == ""


def test_hook_mode_exits_0_when_claude_code_closes_the_pipe(stash: Path, tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    digest = put("curl output for order_5521: 502 Bad Gateway\n")
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(note(digest) + "\n", encoding="utf-8")
    event = json.dumps(
        {"session_id": "s", "transcript_path": str(transcript), "prompt": "order_5521"}
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", "from lcc.cli import app; app()", "hint", "--hook"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "LCC_STASH_DIR": str(stash)},
    )
    assert proc.stdout is not None and proc.stdin is not None and proc.stderr is not None
    proc.stdout.close()  # the reader is gone before the hook answers
    proc.stdin.write(event.encode())
    proc.stdin.close()
    err = proc.stderr.read()
    assert proc.wait(timeout=60) == 0, err.decode()


# --- search: the whole stash, every session ---------------------------------------------


def test_search_ranks_outputs_of_any_session_without_the_hint_threshold(stash: Path) -> None:
    refund = put("FAILED tests/test_api.py::test_refund_77\n", session="yesterday")
    other = put("refund policy notes\n", session="another")
    put("unrelated build log\n")
    found = search("why did test_refund_77 fail on refund")
    assert [hit.id for hit in found] == [refund[:12], other[:12]]
    assert "test_refund_77" in found[0].terms and found[0].opening.startswith("FAILED")
    assert find_hints("refund", [other[:12]]) == []  # one weight-1 term: below a hint, found here
    assert [hit.id for hit in search("refund", limit=1)] in ([refund[:12]], [other[:12]])
    assert search("nothing_like_this_9") == [] and search("") == []


def test_cli_stash_search_prints_ids_to_recall(stash: Path) -> None:
    digest = put("curl output for order_5521: 502 Bad Gateway\n")
    out = CliRunner().invoke(app, ["stash", "search", "order_5521"])
    assert out.exit_code == 0 and out.output.startswith(digest[:12])
    assert CliRunner().invoke(app, ["stash", "search", "absent_term_1"]).exit_code == 1
