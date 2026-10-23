"""provider="rules", rules_mode="recoverable": replace an old output only when it can be recovered.

A result is replaced by a recovery pointer only when the agent can get it back by re-reading a
file nothing later writes (checked against the disk when a workspace root is given) or by
re-running a read-only command from an explicit allowlist. Everything lossless removes is
removed too. Text and tool inputs never change.
"""

from __future__ import annotations

import copy
import re

import pytest

import lcc.relevance.transcript as transcript_module
import lcc.relevance.transcript_recoverable as recoverable_module
from lcc.relevance.transcript import (
    TranscriptCompactionRequest,
    compact_transcript,
    messages_to_payload,
)
from lcc.relevance.transcript_recoverable import is_read_only_command, verify_recoverable

LINES = [f"line {n} of the parser" for n in range(1, 40)]
FILE = "\n".join(LINES) + "\n"
NUMBERED = "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(LINES, start=1))
LISTING = "\n".join(f"src/module_{n}.py" for n in range(30))


@pytest.fixture(autouse=True)
def _no_judge(monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")

    def refuse(*_args, **_kwargs):
        raise AssertionError("provider='rules' must never resolve a judge")

    monkeypatch.setattr(transcript_module, "_resolve_client", refuse)


@pytest.fixture
def disk(tmp_path, monkeypatch):
    monkeypatch.setattr(recoverable_module, "_TEMP", re.compile(r"(?!)"))
    return tmp_path


CMD = {"allow_command_pointers": True}


def convo(*calls, goal: str = "fix the parser", tail: int = 1) -> list[dict]:
    messages: list[dict] = [{"role": "user", "text": goal}]
    for n, call in enumerate(calls, start=1):
        tool, tool_input, output = call[:3]
        is_error = len(call) > 3 and call[3]
        messages.append(
            {"role": "assistant", "text": f"step {n}",
             "toolUses": [{"id": f"c{n}", "tool": tool, "input": tool_input}]}
        )
        result = {"id": f"c{n}", "text": output}
        if is_error:
            result["is_error"] = True
        messages.append({"role": "user", "text": "", "toolResults": [result]})
    for n in range(tail):
        messages.append({"role": "assistant", "text": f"wrap {n}"})
    return messages


def run(messages: list[dict], **kwargs):
    original = copy.deepcopy(messages)
    result = compact_transcript(
        TranscriptCompactionRequest(
            payload={"messages": messages}, question=messages[0]["text"], provider="rules",
            rules_mode="recoverable", preserve_recent=1, **kwargs,
        )
    )
    assert messages == original, "the input payload must not be mutated"
    compacted = messages_to_payload(result.messages)
    allow = kwargs.get("allow_command_pointers", False)
    assert verify_recoverable({"messages": messages}, compacted, allow_command_pointers=allow) == []
    assert [m["text"] for m in compacted] == [m["text"] for m in messages]
    return result, compacted, {d["id"]: d for d in result.decisions}


def text_of(payload: list[dict], call_id: str) -> str:
    for message in payload:
        for item in message.get("toolResults", []):
            if item["tool_use_id"] == call_id:
                return item["text"]
    raise KeyError(call_id)


def filler(n: int = 1):
    # A call that writes nothing: it must not invalidate earlier pointers.
    return [("Grep", {"pattern": f"todo{n}"}, f"{n} matches")]


# -- file reads -----------------------------------------------------------------------


def test_whole_file_read_is_replaced_by_a_reread_pointer():
    result, compacted, d = run(convo(("Read", {"file_path": "/r/src/p.py"}, NUMBERED), *filler()))
    assert d["c1"]["decision"] == "replace"
    assert d["c1"]["reason"] == "recoverable_file_read"
    assert text_of(compacted, "c1") == "[removed: re-read /r/src/p.py to recover]"
    assert d["c1"]["recoverability_check"] == "transcript_proxy"
    assert result.report["rules_mode"] == "recoverable"
    assert result.report["recoverability_check"] == "transcript_proxy"
    assert result.report["semantic_guarantee"] == "recoverable"
    assert result.report["tool_calls_replaced"] == 1
    assert compacted[1]["toolUses"][0]["input"] == {"file_path": "/r/src/p.py"}


def test_partial_read_pointer_names_its_lines():
    part = "\n".join(NUMBERED.split("\n")[4:12])
    _r, compacted, _d = run(
        convo(("Read", {"file_path": "/r/p.py", "offset": 5, "limit": 8}, part), *filler())
    )
    assert text_of(compacted, "c1") == "[removed: re-read /r/p.py (lines 5-12) to recover]"


@pytest.mark.parametrize(
    "cmd,out,pointer",
    [
        ("cat src/p.py", FILE, "[removed: re-read src/p.py (cwd /r) to recover]"),
        ("sed -n '5,12p' src/p.py", "\n".join(LINES[4:12]) + "\n",
         "[removed: re-read src/p.py (lines 5-12) (cwd /r) to recover]"),
        ("head -n 12 src/p.py", "\n".join(LINES[:12]) + "\n",
         "[removed: re-read src/p.py (lines 1-12) (cwd /r) to recover]"),
    ],
)
def test_shell_reads_of_one_file_are_file_reads(cmd, out, pointer):
    _r, compacted, d = run(convo(("Bash", {"command": cmd, "cwd": "/r"}, out), *filler()))
    assert d["c1"]["reason"] == "recoverable_file_read"
    assert text_of(compacted, "c1") == pointer


def test_codex_exec_read_is_a_file_read():
    out = "Chunk ID: 1\nWall time: 0.1s\nProcess exited with code 0\nOutput:\n" + FILE
    _r, compacted, d = run(
        convo(("exec_command", {"cmd": "sed -n '1,39p' p.py", "workdir": "/r"}, out), *filler())
    )
    assert d["c1"]["decision"] == "replace"
    assert text_of(compacted, "c1") == "[removed: re-read p.py (lines 1-39) (cwd /r) to recover]"


def test_codex_exec_read_with_nonzero_exit_is_kept():
    out = "Process exited with code 1\nOutput:\nsed: p.py: No such file or directory" + "x" * 80
    _r, _c, d = run(convo(("exec_command", {"cmd": "sed -n '1,9p' p.py"}, out), *filler()))
    assert d["c1"]["decision"] == "keep"


@pytest.mark.parametrize(
    "later",
    [
        ("Edit", {"file_path": "/r/src/p.py", "old_string": "a", "new_string": "b"}, "ok"),
        ("Write", {"file_path": "/r/src/p.py", "content": "x"}, "ok"),
        ("apply_patch", {"input": "*** Begin Patch\n*** Update File: src/p.py\n@@\n-a\n+b"}, "ok"),
        ("Bash", {"command": "rm src/p.py"}, ""),
        ("Bash", {"command": "sed -i 's/a/b/' src/p.py"}, ""),
        ("Bash", {"command": "git checkout -- ."}, ""),
    ],
)
def test_file_written_later_is_kept(later):
    _r, compacted, d = run(convo(("Read", {"file_path": "/r/src/p.py"}, NUMBERED), later, *filler()))
    assert d["c1"]["decision"] == "keep"
    assert text_of(compacted, "c1") == NUMBERED


def test_failed_read_is_kept():
    _r, _c, d = run(convo(("Read", {"file_path": "p.py"}, "File does not exist." * 5, True),
                          *filler(), *filler(2)))
    assert d["c1"]["decision"] == "keep"


def test_read_named_in_the_goal_is_kept():
    _r, _c, d = run(convo(("Read", {"file_path": "src/p.py"}, NUMBERED), *filler(),
                          goal="fix the bug in p.py"))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "named_in_goal_or_recent_turns"


def test_read_named_in_a_recent_user_turn_is_kept():
    messages = convo(("Read", {"file_path": "src/p.py"}, NUMBERED), *filler(), tail=0)
    messages.append({"role": "user", "text": "look again at src/p.py"})
    _r, _c, d = run(messages)
    assert d["c1"]["decision"] == "keep"


# -- disk check ------------------------------------------------------------------------


def test_disk_check_passes_when_the_file_still_holds_the_content(disk):
    (disk / "p.py").write_text(FILE)
    result, compacted, d = run(convo(("Read", {"file_path": str(disk / "p.py")}, NUMBERED),
                                     *filler()), workspace_root=str(disk))
    assert d["c1"]["decision"] == "replace"
    assert d["c1"]["reason"] == "replace_disk_verified"
    assert d["c1"]["recoverability_check"] == "disk"
    assert result.report["recoverability_check"] == "disk"


def test_disk_check_accepts_claude_codes_trailing_empty_numbered_line(disk):
    # Claude Code 2.1.296's Read: "1\t..." rows, plus an empty row after the final newline.
    (disk / "p.py").write_text(FILE)
    read = "\n".join(f"{n}\t{line}" for n, line in enumerate(LINES, start=1))
    read += f"\n{len(LINES) + 1}\t"
    _r, _c, d = run(convo(("Read", {"file_path": str(disk / "p.py")}, read), *filler()),
                    workspace_root=str(disk))
    assert d["c1"]["reason"] == "replace_disk_verified"
    # A non-empty extra row is content the file does not hold.
    _r, _c, d = run(convo(("Read", {"file_path": str(disk / "p.py")}, read + "x"), *filler()),
                    workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_mismatch"


def test_disk_check_keeps_a_read_the_file_no_longer_matches(disk):
    (disk / "p.py").write_text(FILE.replace("line 7 of", "line seven of"))
    _r, compacted, d = run(convo(("Read", {"file_path": str(disk / "p.py")}, NUMBERED),
                                 *filler()), workspace_root=str(disk))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "keep_disk_mismatch"
    assert text_of(compacted, "c1") == NUMBERED


# Independent of the basetemp path length: the output is far longer than any pointer.
WIDE = [f"{n:04d} " + "x" * 200 for n in range(1, 60)]


def test_disk_check_partial_range(disk):
    sed = ("Bash", {"command": "sed -n '5,40p' p.py", "cwd": str(disk)},
           "\n".join(WIDE[4:40]) + "\n")
    (disk / "p.py").write_text("\n".join(WIDE) + "\n")
    _r, _c, d = run(convo(sed, *filler()), workspace_root=str(disk))
    assert d["c1"]["decision"] == "replace"
    (disk / "p.py").write_text("short\n")
    _r, _c, d = run(convo(sed, *filler()), workspace_root=str(disk))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "keep_disk_mismatch"


# -- disk-authoritative (owner decision 2026-10-11) ------------------------------------


LATER_WRITES = [
    ("Edit", {"file_path": "{p}", "old_string": "a", "new_string": "b"}, "ok"),
    ("Write", {"file_path": "{p}", "content": "x"}, "ok"),
    ("Bash", {"command": "python gen.py"}, ""),
    ("Bash", {"command": "cd {d} && make"}, ""),
    ("mcp__fs__do_things", {"x": 1}, "ok"),
    ("Bash", {"command": "git checkout -- ."}, ""),
]


def _fill(call, disk):
    tool, tool_input, out = call
    sub = {k: v.replace("{p}", str(disk / "p.py")).replace("{d}", str(disk))
           if isinstance(v, str) else v for k, v in tool_input.items()}
    return tool, sub, out


@pytest.mark.parametrize("later", LATER_WRITES)
def test_disk_verified_file_is_replaced_despite_later_writes(disk, later):
    (disk / "p.py").write_text(FILE)
    read = ("Read", {"file_path": str(disk / "p.py")}, NUMBERED)
    _r, compacted, d = run(convo(read, _fill(later, disk), *filler()), workspace_root=str(disk))
    assert d["c1"]["decision"] == "replace"
    assert d["c1"]["reason"] == "replace_disk_verified"
    assert d["c1"]["recoverability_check"] == "disk"
    assert text_of(compacted, "c1") == (
        f"[removed: re-read {disk / 'p.py'} to recover; "
        "content verified on disk at compaction time]"
    )
    # Without a root the transcript proxy still keeps it (v0.8 behaviour).
    _r, _c, d = run(convo(read, _fill(later, disk), *filler()))
    assert d["c1"]["reason"] == "file_written_later"


@pytest.mark.parametrize("later", LATER_WRITES)
def test_disk_mismatch_after_later_writes_is_kept(disk, later):
    (disk / "p.py").write_text(FILE + "appended\n")
    read = ("Read", {"file_path": str(disk / "p.py")}, NUMBERED)
    _r, compacted, d = run(convo(read, _fill(later, disk), *filler()), workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_mismatch"
    assert text_of(compacted, "c1") == NUMBERED


@pytest.mark.parametrize("arrow", [False, True])
def test_disk_verified_partial_read_compares_the_numbered_range(disk, arrow):
    rows = NUMBERED.split("\n")[4:12]
    if arrow:  # Claude Code's other Read format: "     5→content"
        rows = [r.replace("\t", "→", 1) for r in rows]
    read = ("Read", {"file_path": str(disk / "p.py"), "offset": 5, "limit": 8}, "\n".join(rows))
    later = ("Edit", {"file_path": str(disk / "p.py"), "old_string": "x", "new_string": "y"}, "")
    (disk / "p.py").write_text(FILE.replace("line 30 of", "line thirty of"))  # outside 5-12
    _r, compacted, d = run(convo(read, later, *filler()), workspace_root=str(disk))
    assert d["c1"]["reason"] == "replace_disk_verified"
    assert "(lines 5-12)" in text_of(compacted, "c1")
    (disk / "p.py").write_text(FILE.replace("line 9 of", "line nine of"))  # inside 5-12
    _r, _c, d = run(convo(read, later, *filler()), workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_mismatch"


def test_disk_check_is_byte_exact(disk):
    (disk / "p.py").write_bytes(FILE.replace("\n", "\r\n").encode())
    read = ("Bash", {"command": "cat p.py", "cwd": str(disk)}, FILE)
    _r, _c, d = run(convo(read, *filler()), workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_mismatch"
    (disk / "p.py").write_bytes(b"\xff\xfe" + FILE.encode())
    _r, _c, d = run(convo(read, *filler()), workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_unreadable"


def test_disk_check_caps_the_file_size(disk, monkeypatch):
    (disk / "p.py").write_text(FILE)
    monkeypatch.setattr(recoverable_module, "DISK_MAX_BYTES", len(FILE) - 1)
    _r, _c, d = run(convo(("Read", {"file_path": str(disk / "p.py")}, NUMBERED), *filler()),
                    workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_too_large"


def test_disk_check_refuses_symlinks_out_of_the_root_and_non_files(disk, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "real.py"
    outside.write_text(FILE)
    (disk / "link.py").symlink_to(outside)
    _r, _c, d = run(convo(("Read", {"file_path": str(disk / "link.py")}, NUMBERED), *filler()),
                    workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_outside_root"
    (disk / "real.py").write_text(FILE)
    (disk / "inside.py").symlink_to(disk / "real.py")  # stays in the root: allowed
    _r, _c, d = run(convo(("Read", {"file_path": str(disk / "inside.py")}, NUMBERED), *filler()),
                    workspace_root=str(disk))
    assert d["c1"]["reason"] == "replace_disk_verified"
    (disk / "dir.py").mkdir()
    _r, _c, d = run(convo(("Read", {"file_path": str(disk / "dir.py")}, NUMBERED), *filler()),
                    workspace_root=str(disk))
    assert d["c1"]["reason"] == "keep_disk_not_regular"


def test_disk_check_keeps_dotdot_paths_that_a_symlink_would_redirect(disk, tmp_path_factory):
    # ws/link -> other/sub: the kernel resolves link/../f.py to other/f.py, not ws/f.py.
    other = tmp_path_factory.mktemp("other")
    (other / "sub").mkdir()
    (other / "f.py").write_text("CHANGED\n")
    (disk / "f.py").write_text(FILE)
    (disk / "link").symlink_to(other / "sub")
    for path, cwd in ((str(disk / "link" / ".." / "f.py"), None), ("../f.py", str(disk / "link"))):
        call = {"file_path": path} if cwd is None else {"file_path": path, "workdir": cwd}
        _r, compacted, d = run(convo(("Read", call, NUMBERED), *filler()), workspace_root=str(disk))
        assert d["c1"]["decision"] == "keep"
        assert d["c1"]["reason"] == "keep_disk_dotdot"
        assert text_of(compacted, "c1") == NUMBERED


def test_file_changed_between_check_and_emit_is_kept(disk, monkeypatch):
    (disk / "p.py").write_text(FILE)
    decide = transcript_module.recoverable_decisions

    def decide_then_edit(*args, **kwargs):
        decisions = decide(*args, **kwargs)
        (disk / "p.py").write_text(FILE + "late edit\n")
        return decisions

    monkeypatch.setattr(transcript_module, "recoverable_decisions", decide_then_edit)
    result, compacted, d = run(convo(("Read", {"file_path": str(disk / "p.py")}, NUMBERED),
                                     *filler()), workspace_root=str(disk))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "keep_disk_changed_before_emit"
    assert text_of(compacted, "c1") == NUMBERED
    # A demoted decision must not still look like a pointer to report consumers.
    assert not {"note", "recover", "disk", "recoverability_check"} & set(d["c1"])
    assert result.report["tool_calls_replaced"] == 0


def test_verify_accepts_the_disk_verified_pointer():
    messages = convo(("Read", {"file_path": "/r/p.py"}, NUMBERED), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = (
        "[removed: re-read /r/p.py to recover; content verified on disk at compaction time]")
    assert verify_recoverable({"messages": messages}, forged) == []
    forged[2]["toolResults"][0]["text"] = (
        "[removed: re-read /r/q.py to recover; content verified on disk at compaction time]")
    assert verify_recoverable({"messages": messages}, forged)


def test_disk_check_missing_file_is_kept(disk):
    _r, _c, d = run(convo(("Read", {"file_path": str(disk / "gone.py")}, NUMBERED), *filler()),
                    workspace_root=str(disk))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "keep_disk_missing"


def test_disk_check_can_be_turned_off(disk):
    result, _c, d = run(convo(("Read", {"file_path": str(disk / "gone.py")}, NUMBERED),
                              *filler()), workspace_root=str(disk), disk_check=False)
    assert d["c1"]["decision"] == "replace"
    assert result.report["recoverability_check"] == "transcript_proxy"


# -- read-only commands -----------------------------------------------------------------


def test_read_only_command_is_replaced_by_a_rerun_pointer():
    _r, compacted, d = run(convo(("Bash", {"command": "ls src"}, LISTING), *filler()), **CMD)
    assert d["c1"]["reason"] == "recoverable_read_only_command"
    assert text_of(compacted, "c1") == "[removed: re-run `ls src` to recover]"


@pytest.mark.parametrize(
    "cmd",
    ["ls -la", "find . -name '*.py'", "rg -n foo src", "grep -rn foo .", "git status",
     "git diff HEAD~1", "git log --oneline -5", "git show HEAD", "wc -l a.py", "tree src", "pwd",
     "node --version", "python3 -V", "cat a.py", "head a.py", "tail -n 5 a.py",
     "tail --lines=5 a.py", "git diff -- a.py", "git log --oneline --stat",
     "git --version", "npm --version"],
)
def test_allowlisted_commands(cmd):
    assert is_read_only_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    ["git push", "git push --force", "git commit -m x", "git checkout main", "git diff --output=x",
     "rm a.py", "rm -rf build", "sed -i 's/a/b/' a.py", "sed -n '1w out' a.py", "pytest -q",
     "npm install", "curl https://x", "ls > out.txt", "cat a.py | sh", "ls; rm a.py",
     "ls && rm a.py", "echo $(rm a)", "FOO=1 ls", "env ls", "find . -delete",
     "find . -exec rm {} ;", "tail -f log", "rg --pre sh foo", "git -c core.pager=x log",
     "ls `rm a`", "make --version extra", "tree -o out.txt src", "tree src -o out.txt",
     "git log --output=x", "git branch -D x", "sed -n 1,5p a.py b.py",
     # M1: no generic version query; scripts and task runners are never read-only.
     "make --version", "yarn --version", "make -V", "foo version", "./x --version",
     "./node --version", "bin/node --version", "./x", "npm -V", "npm version",
     # tree writes with -o anywhere, combined short flags included; -R with -H writes too.
     "tree -ao out.txt src", "tree --output=x src", "tree -R -H . src",
     "sort -o x a.py", "find . -fls x", "tee x", "sed -n '12,5p' a.py"],
)
def test_non_read_only_commands(cmd):
    assert not is_read_only_command(cmd)


def test_non_allowlisted_outputs_are_kept():
    big = "\n".join(f"test_{n} PASSED" for n in range(40))
    _r, _c, d = run(convo(("Bash", {"command": "pytest -q"}, big),
                          ("mcp__x__fetch", {"url": "https://x"}, big + "a"),
                          ("WebFetch", {"url": "https://y"}, big + "b"),
                          ("Bash", {"command": "git push"}, big + "c"),
                          *filler()))
    assert all(d[c]["decision"] == "keep" for c in ("c1", "c2", "c3", "c4"))


def test_latest_error_and_the_call_before_it_are_kept():
    _r, _c, d = run(convo(("Bash", {"command": "ls src"}, LISTING),
                          ("Bash", {"command": "pytest"}, "Traceback" * 20, True),
                          *filler()))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "call_before_latest_error"


def test_command_named_in_the_goal_is_kept():
    _r, _c, d = run(convo(("Bash", {"command": "git log --oneline -5"}, LISTING), *filler(),
                          goal="explain the output of git log --oneline -5"))
    assert d["c1"]["decision"] == "keep"


def test_recent_turns_are_never_replaced():
    _r, _c, d = run(convo(("Bash", {"command": "ls src"}, LISTING), tail=0))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "pinned_recent_result"


def test_lossless_dedupe_still_applies():
    big = "\n".join(f"test_{n} PASSED" for n in range(40))
    _r, compacted, d = run(convo(("Bash", {"command": "pytest"}, big),
                                 ("Bash", {"command": "pytest"}, big), *filler()))
    assert d["c1"]["decision"] == "dedupe"
    assert text_of(compacted, "c1") == "[identical output kept at c2]"


def test_dedupe_never_targets_a_replaced_result():
    _r, compacted, d = run(convo(("Bash", {"command": "ls src"}, LISTING),
                                 ("Bash", {"command": "ls src"}, LISTING), *filler()), **CMD)
    assert d["c2"]["decision"] == "replace"
    assert d["c1"]["decision"] == "replace"


# -- verifier ---------------------------------------------------------------------------


def test_verify_rejects_a_pointer_that_names_another_call():
    messages = convo(("Read", {"file_path": "a.py"}, NUMBERED), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-read b.py to recover]"
    assert verify_recoverable({"messages": messages}, forged)
    forged[2]["toolResults"][0]["text"] = "[removed: re-run `ls` to recover]"
    assert verify_recoverable({"messages": messages}, forged)


def test_verify_rejects_a_pointer_on_a_non_allowlisted_call():
    messages = convo(("Bash", {"command": "pytest"}, LISTING), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-run `pytest` to recover]"
    assert verify_recoverable({"messages": messages}, forged)


def test_verify_rejects_changed_text_or_inputs():
    messages = convo(("Bash", {"command": "ls src"}, LISTING), *filler())
    forged = copy.deepcopy(messages)
    forged[1]["text"] = "edited"
    assert verify_recoverable({"messages": messages}, forged)
    forged = copy.deepcopy(messages)
    forged[1]["toolUses"][0]["input"] = {"command": "ls"}
    assert verify_recoverable({"messages": messages}, forged)


# -- v0.6 review: H1 shell tools -------------------------------------------------------


@pytest.mark.parametrize(
    "later",
    [
        ("terminal", {"command": "git checkout -- ."}, ""),
        ("terminal", {"command": "git restore ."}, ""),
        ("terminal", {"command": "git stash"}, ""),
        ("terminal", {"command": "rm -rf src"}, ""),
        ("Bash", {"command": "mv src old_src"}, ""),
        ("execute_code", {"code": "import subprocess; subprocess.run('git checkout .')"}, ""),
    ],
)
def test_hermes_terminal_and_dir_level_writes_invalidate_file_pointers(later):
    _r, compacted, d = run(convo(("Read", {"file_path": "/r/src/p.py"}, NUMBERED), later, *filler()))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "file_written_later"


def test_hermes_terminal_read_is_a_shell_read():
    _r, compacted, d = run(convo(("terminal", {"command": "cat src/p.py", "workdir": "/r"}, FILE),
                                 *filler()))
    assert d["c1"]["reason"] == "recoverable_file_read"
    assert text_of(compacted, "c1") == "[removed: re-read src/p.py (cwd /r) to recover]"


def test_background_terminal_output_is_not_command_output():
    _r, _c, d = run(convo(("terminal", {"command": "ls src", "background": True}, LISTING),
                          *filler()))
    assert d["c1"]["decision"] == "keep"


# -- H2 command pointers ---------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd,later",
    [
        ("git status", ("Bash", {"command": "git commit -m x"}, "")),
        ("git status", ("Bash", {"command": "git add -A"}, "")),
        ("git diff", ("Edit", {"file_path": "x.py", "old_string": "a", "new_string": "b"}, "ok")),
        ("git log --oneline -5", ("terminal", {"command": "git pull"}, "")),
        ("git show HEAD", ("apply_patch", {"input": "*** Update File: y.py"}, "ok")),
        ("ls src", ("Write", {"file_path": "src/new.py", "content": "x"}, "ok")),
        ("ls", ("Write", {"file_path": "elsewhere/new.py", "content": "x"}, "ok")),
        ("find . -name '*.py'", ("Write", {"file_path": "a.py", "content": "x"}, "ok")),
        ("rg -n foo src", ("patch", {"path": "src/b.py", "old_string": "a", "new_string": "b"},
                           "ok")),
        ("wc -l src/a.py", ("Bash", {"command": "pytest -q"}, "1 passed")),
        ("ls src", ("Bash", {"command": "python gen.py"}, "")),
    ],
)
def test_command_output_changed_later_is_kept(cmd, later):
    _r, compacted, d = run(convo(("Bash", {"command": cmd}, LISTING), later, *filler()), **CMD)
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "command_output_changed_later"
    assert text_of(compacted, "c1") == LISTING


@pytest.mark.parametrize(
    "cmd,later",
    [
        ("git status", ("Read", {"file_path": "a.py"}, "x")),
        ("ls src", ("Write", {"file_path": "docs/new.md", "content": "x"}, "ok")),
        ("ls src", ("Bash", {"command": "rg -n foo"}, "x")),
        ("pwd", ("Write", {"file_path": "a.py", "content": "x"}, "ok")),
    ],
)
def test_command_output_untouched_later_is_replaced(cmd, later):
    _r, _c, d = run(convo(("Bash", {"command": cmd}, LISTING), later, *filler()), **CMD)
    assert d["c1"]["decision"] == "replace"


# -- M2 cwd in pointers ----------------------------------------------------------------


def test_pointers_name_the_working_directory():
    _r, compacted, _d = run(convo(
        ("terminal", {"command": "ls src", "workdir": "/repo"}, LISTING),
        ("Read", {"file_path": "p.py", "cwd": "/repo"}, NUMBERED),
        *filler()), **CMD)
    assert text_of(compacted, "c1") == "[removed: re-run `ls src` in /repo to recover]"
    assert text_of(compacted, "c2") == "[removed: re-read p.py (cwd /repo) to recover]"


# -- L1 / L2 verifier and ranges -------------------------------------------------------


def test_verify_rejects_wrong_line_range_or_missing_cwd():
    messages = convo(("Read", {"file_path": "a.py"}, NUMBERED), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-read a.py (lines 1-3) to recover]"
    assert verify_recoverable({"messages": messages}, forged)
    part = "\n".join(NUMBERED.split("\n")[4:12])
    messages = convo(("Read", {"file_path": "a.py", "offset": 5, "limit": 8}, part), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-read a.py to recover]"
    assert verify_recoverable({"messages": messages}, forged)
    messages = convo(("Bash", {"command": "ls src", "cwd": "/r"}, LISTING), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-run `ls src` to recover]"
    assert verify_recoverable({"messages": messages}, forged)


@pytest.mark.parametrize("cmd", ["head -n 0 src/p.py", "head -0 src/p.py", "sed -n '12,5p' src/p.py"])
def test_empty_or_reversed_ranges_are_kept(cmd):
    result, compacted, d = run(convo(("Bash", {"command": cmd}, FILE), *filler()))
    assert d["c1"]["decision"] == "keep"
    assert not result.report["degraded"]
    assert text_of(compacted, "c1") == FILE


# -- FS duplicate tool_use_ids ---------------------------------------------------------


def test_duplicate_tool_use_ids_are_kept_without_tripping_the_fail_safe():
    messages = convo(("Bash", {"command": "ls src"}, LISTING),
                     ("Bash", {"command": "ls lib"}, LISTING + "\nlib"),
                     ("Read", {"file_path": "/r/q.py"}, NUMBERED),
                     *filler())
    for message in messages[3:5]:  # second call reuses c1's id
        for block in message.get("toolUses", []) + message.get("toolResults", []):
            block["id"] = "c1"
    result, compacted, _d = run(messages, **CMD)
    assert not result.report["degraded"], result.report["degradation_reason"]
    assert result.report["lossless_violations"] == []
    reasons = [x["reason"] for x in result.decisions if x["id"] == "c1"]
    assert reasons == ["duplicate_tool_use_id", "duplicate_tool_use_id"]
    assert [i["text"] for m in compacted for i in m.get("toolResults", [])][:2] == [
        LISTING, LISTING + "\nlib"]
    assert text_of(compacted, "c3") == "[removed: re-read /r/q.py to recover]"


# -- temp paths (v0.7 DEV audit): a temp file may be gone when the agent re-reads it ----------


@pytest.mark.parametrize(
    "call",
    [
        ("Read", {"file_path": "/tmp/report.txt"}, NUMBERED),
        ("Read", {"file_path": "/private/tmp/claude-501/tasks/b1.output"}, NUMBERED),
        ("Read", {"file_path": "/var/folders/xy/T/out.log"}, NUMBERED),
        ("Bash", {"command": "cat out.log", "cwd": "/tmp/run"}, FILE),
        ("Bash", {"command": "ls /tmp/run"}, LISTING),
        ("terminal", {"command": "ls", "workdir": "/private/var/folders/xy/T"}, LISTING),
    ],
)
def test_temp_paths_are_kept(call):
    _r, compacted, d = run(convo(call, *filler()))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "temp_path"
    assert text_of(compacted, "c1") == call[2]


def test_verify_rejects_a_pointer_to_a_temp_file():
    messages = convo(("Read", {"file_path": "/tmp/report.txt"}, NUMBERED), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-read /tmp/report.txt to recover]"
    assert verify_recoverable({"messages": messages}, forged)


def test_tmp_in_a_repo_path_is_not_a_temp_path():
    _r, compacted, _d = run(convo(("Read", {"file_path": "/repo/tmp/x.py"}, NUMBERED), *filler()))
    assert text_of(compacted, "c1") == "[removed: re-read /repo/tmp/x.py to recover]"


# -- v0.7 review: only ever turn a replace into a keep ---------------------------------------


# H1: a later shell call off the allowlist (or an unknown tool) may write any file it can reach.
@pytest.mark.parametrize(
    "later",
    [
        ("Bash", {"command": "python gen.py"}, ""),
        ("Bash", {"command": "make"}, ""),
        ("Bash", {"command": "npm run build"}, ""),
        ("Bash", {"command": "yarn"}, ""),
        ("Bash", {"command": "pip install -e ."}, ""),
        ("Bash", {"command": "./scripts/fmt.sh"}, ""),
        ("Bash", {"command": "git commit -am x"}, ""),
        ("terminal", {"command": "pytest -q"}, "1 passed"),
        ("exec_command", {"cmd": "cargo fmt", "workdir": "/r"}, ""),
        ("Bash", {"command": "cd /r && make", "cwd": "/elsewhere"}, ""),
        ("mcp__fs__do_things", {"x": 1}, "ok"),
        ("execute_code", {"code": "open('a', 'w')"}, ""),
    ],
)
def test_opaque_later_write_invalidates_file_pointers(later):
    _r, compacted, d = run(convo(("Read", {"file_path": "/r/src/p.py"}, NUMBERED), later, *filler()))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "file_written_later"
    assert text_of(compacted, "c1") == NUMBERED


def test_opaque_later_write_outside_the_file_cwd_does_not_invalidate():
    _r, _c, d = run(convo(("Read", {"file_path": "/r/src/p.py"}, NUMBERED),
                          ("exec_command", {"cmd": "make", "workdir": "/other"}, ""), *filler()))
    assert d["c1"]["decision"] == "replace"
    _r, _c, d = run(convo(("Read", {"file_path": "/r/src/p.py"}, NUMBERED),
                          ("exec_command", {"cmd": "make", "workdir": "/r"}, ""), *filler()))
    assert d["c1"]["decision"] == "keep"


def test_later_read_only_shell_call_does_not_invalidate():
    _r, _c, d = run(convo(("Read", {"file_path": "/r/src/p.py"}, NUMBERED),
                          ("Bash", {"command": "ls src"}, "a"), *filler()))
    assert d["c1"]["decision"] == "replace"


# H2: command pointers are off by default; the path stays, tested both ways.
@pytest.mark.parametrize("allow", [False, True])
def test_command_pointers_are_opt_in(allow):
    _r, compacted, d = run(convo(("Bash", {"command": "ls src"}, LISTING),
                                 ("Bash", {"command": "tail -n 5 /r/p.py"}, FILE), *filler()),
                           allow_command_pointers=allow)
    if allow:
        assert text_of(compacted, "c1") == "[removed: re-run `ls src` to recover]"
        assert text_of(compacted, "c2") == "[removed: re-run `tail -n 5 /r/p.py` to recover]"
    else:
        assert d["c1"]["decision"] == d["c2"]["decision"] == "keep"
        assert d["c1"]["reason"] == d["c2"]["reason"] == "command_pointers_disabled"


def test_verify_rejects_a_command_pointer_unless_allowed():
    messages = convo(("Bash", {"command": "ls src"}, LISTING), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-run `ls src` to recover]"
    assert verify_recoverable({"messages": messages}, forged)
    assert verify_recoverable({"messages": messages}, forged, allow_command_pointers=True) == []


# M1: globs, braces and several files in one read are never file pointers.
@pytest.mark.parametrize(
    "call",
    [
        ("Bash", {"command": "cat src/*.py", "cwd": "/r"}, FILE),
        ("Bash", {"command": "cat src/{a,b}.py", "cwd": "/r"}, FILE),
        ("Bash", {"command": "head -n 3 src/p?.py", "cwd": "/r"}, "\n".join(LINES[:3]) + "\n"),
        ("Bash", {"command": "cat a.py b.py", "cwd": "/r"}, FILE),
        ("Bash", {"command": "cat ~/p.py"}, FILE),
    ],
)
def test_globs_and_multiple_files_are_kept(call):
    _r, compacted, d = run(convo(call, *filler()))
    assert d["c1"]["decision"] == "keep"
    assert text_of(compacted, "c1") == call[2]


# M2: a relative path is a pointer only with an explicit working directory.
@pytest.mark.parametrize(
    "call",
    [
        ("Read", {"file_path": "src/p.py"}, NUMBERED),
        ("Bash", {"command": "cat src/p.py"}, FILE),
        ("Bash", {"command": "cat src/p.py", "cwd": "rel"}, FILE),
        ("terminal", {"command": "sed -n '1,39p' p.py"}, FILE),
    ],
)
def test_relative_path_without_cwd_is_kept(call):
    _r, compacted, d = run(convo(call, *filler()))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "relative_path_without_cwd"
    assert text_of(compacted, "c1") == call[2]


def test_verify_rejects_a_relative_file_pointer_without_cwd():
    messages = convo(("Read", {"file_path": "a.py"}, NUMBERED), *filler())
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[removed: re-read a.py to recover]"
    assert verify_recoverable({"messages": messages}, forged)


# L1: follow modes, stdin and device/proc files are never read-only and never pointers.
@pytest.mark.parametrize(
    "cmd",
    ["tail -fn 20 log", "tail -qf log", "tail -F log", "tail -nf 5 log", "tail --follow=name log",
     "tail --fo log", "tail --foll=name log", "tail --f log", "tail --re log", "tail --r log",
     "git diff --out=x", "git log --outp x", "git diff --ext HEAD", "git show --ext-d HEAD",
     "cat -", "cat", "head -n 5 -", "wc -l", "cat /dev/urandom", "head -c 10 /dev/random",
     "cat /proc/self/status", "nl -"],
)
def test_follow_stdin_and_devices_are_not_read_only(cmd):
    assert not is_read_only_command(cmd)


@pytest.mark.parametrize("path", ["/dev/stdin", "/dev/fd/0", "/proc/1/environ", "-"])
def test_reads_of_devices_or_stdin_are_kept(path):
    _r, compacted, d = run(convo(("Read", {"file_path": path}, NUMBERED), *filler()), **CMD)
    assert d["c1"]["decision"] == "keep"


# L2: a range the output does not fill is kept, not clamped by guess.
@pytest.mark.parametrize(
    "call",
    [
        ("Bash", {"command": "sed -n '5,50p' p.py", "cwd": "/r"}, "\n".join(LINES[4:]) + "\n"),
        ("Bash", {"command": "head -n 100 p.py", "cwd": "/r"}, FILE),
        ("Read", {"file_path": "/r/p.py", "offset": 5, "limit": 3},
         "\n".join(NUMBERED.split("\n")[4:12])),
        ("Read", {"file_path": "/r/p.py", "offset": 7, "limit": 8},
         "\n".join(NUMBERED.split("\n")[4:12])),
    ],
)
def test_ranges_beyond_the_returned_lines_are_kept(call):
    _r, compacted, d = run(convo(call, *filler()))
    assert d["c1"]["decision"] == "keep"
    assert text_of(compacted, "c1") == call[2]


def test_a_very_long_command_is_never_parsed_or_allowlisted() -> None:
    # shlex is quadratic in one token's length; the cap keeps the pass linear (PR: semantic coverage)
    assert is_read_only_command("ls " + "a" * 100)
    assert not is_read_only_command("ls " + "a" * (recoverable_module.MAX_PARSED_COMMAND_CHARS + 1))
