"""provider="rules", rules_mode="recoverable": replace an old output only when it can be recovered.

A result is replaced by a recovery pointer only when the agent can get it back by re-reading a
file nothing later writes (checked against the disk when a workspace root is given) or by
re-running a read-only command from an explicit allowlist. Everything lossless removes is
removed too. Text and tool inputs never change.
"""

from __future__ import annotations

import copy

import pytest

import lcc.relevance.transcript as transcript_module
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
    assert verify_recoverable({"messages": messages}, compacted) == []
    assert [m["text"] for m in compacted] == [m["text"] for m in messages]
    return result, compacted, {d["id"]: d for d in result.decisions}


def text_of(payload: list[dict], call_id: str) -> str:
    for message in payload:
        for item in message.get("toolResults", []):
            if item["tool_use_id"] == call_id:
                return item["text"]
    raise KeyError(call_id)


def filler(n: int = 1):
    return [("Bash", {"command": "pytest -q"}, f"{n} passed")]


# -- file reads -----------------------------------------------------------------------


def test_whole_file_read_is_replaced_by_a_reread_pointer():
    result, compacted, d = run(convo(("Read", {"file_path": "src/p.py"}, NUMBERED), *filler()))
    assert d["c1"]["decision"] == "replace"
    assert d["c1"]["reason"] == "recoverable_file_read"
    assert text_of(compacted, "c1") == "[removed: re-read src/p.py to recover]"
    assert d["c1"]["recoverability_check"] == "transcript_proxy"
    assert result.report["rules_mode"] == "recoverable"
    assert result.report["recoverability_check"] == "transcript_proxy"
    assert result.report["semantic_guarantee"] == "recoverable"
    assert result.report["tool_calls_replaced"] == 1
    assert compacted[1]["toolUses"][0]["input"] == {"file_path": "src/p.py"}


def test_partial_read_pointer_names_its_lines():
    part = "\n".join(NUMBERED.split("\n")[4:12])
    _r, compacted, _d = run(
        convo(("Read", {"file_path": "p.py", "offset": 5, "limit": 8}, part), *filler())
    )
    assert text_of(compacted, "c1") == "[removed: re-read p.py (lines 5-12) to recover]"


@pytest.mark.parametrize(
    "cmd,pointer",
    [
        ("cat src/p.py", "[removed: re-read src/p.py to recover]"),
        ("sed -n '5,12p' src/p.py", "[removed: re-read src/p.py (lines 5-12) to recover]"),
        ("head -n 12 src/p.py", "[removed: re-read src/p.py (lines 1-12) to recover]"),
    ],
)
def test_shell_reads_of_one_file_are_file_reads(cmd, pointer):
    _r, compacted, d = run(convo(("Bash", {"command": cmd}, FILE), *filler()))
    assert d["c1"]["reason"] == "recoverable_file_read"
    assert text_of(compacted, "c1") == pointer


def test_codex_exec_read_is_a_file_read():
    out = "Chunk ID: 1\nWall time: 0.1s\nProcess exited with code 0\nOutput:\n" + FILE
    _r, compacted, d = run(
        convo(("exec_command", {"cmd": "sed -n '1,39p' p.py", "workdir": "/r"}, out), *filler())
    )
    assert d["c1"]["decision"] == "replace"
    assert text_of(compacted, "c1") == "[removed: re-read p.py (lines 1-39) to recover]"


def test_codex_exec_read_with_nonzero_exit_is_kept():
    out = "Process exited with code 1\nOutput:\nsed: p.py: No such file or directory" + "x" * 80
    _r, _c, d = run(convo(("exec_command", {"cmd": "sed -n '1,9p' p.py"}, out), *filler()))
    assert d["c1"]["decision"] == "keep"


@pytest.mark.parametrize(
    "later",
    [
        ("Edit", {"file_path": "src/p.py", "old_string": "a", "new_string": "b"}, "ok"),
        ("Write", {"file_path": "src/p.py", "content": "x"}, "ok"),
        ("apply_patch", {"input": "*** Begin Patch\n*** Update File: src/p.py\n@@\n-a\n+b"}, "ok"),
        ("Bash", {"command": "rm src/p.py"}, ""),
        ("Bash", {"command": "sed -i 's/a/b/' src/p.py"}, ""),
        ("Bash", {"command": "git checkout -- ."}, ""),
    ],
)
def test_file_written_later_is_kept(later):
    _r, compacted, d = run(convo(("Read", {"file_path": "src/p.py"}, NUMBERED), later, *filler()))
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


def test_disk_check_passes_when_the_file_still_holds_the_content(tmp_path):
    (tmp_path / "p.py").write_text(FILE)
    result, compacted, d = run(convo(("Read", {"file_path": "p.py"}, NUMBERED), *filler()),
                               workspace_root=str(tmp_path))
    assert d["c1"]["decision"] == "replace"
    assert d["c1"]["recoverability_check"] == "disk"
    assert result.report["recoverability_check"] == "disk"


def test_disk_check_keeps_a_read_the_file_no_longer_matches(tmp_path):
    (tmp_path / "p.py").write_text(FILE.replace("line 7 of", "line seven of"))
    _r, compacted, d = run(convo(("Read", {"file_path": "p.py"}, NUMBERED), *filler()),
                           workspace_root=str(tmp_path))
    assert d["c1"]["decision"] == "keep"
    assert d["c1"]["reason"] == "disk_content_differs"
    assert text_of(compacted, "c1") == NUMBERED


def test_disk_check_partial_range(tmp_path):
    (tmp_path / "p.py").write_text(FILE)
    _r, _c, d = run(convo(("Bash", {"command": "sed -n '5,12p' p.py"},
                                    "\n".join(LINES[4:12]) + "\n"), *filler()),
                    workspace_root=str(tmp_path))
    assert d["c1"]["decision"] == "replace"
    (tmp_path / "p.py").write_text("short\n")
    _r, _c, d = run(convo(("Bash", {"command": "sed -n '5,12p' p.py"},
                                    "\n".join(LINES[4:12]) + "\n"), *filler()),
                    workspace_root=str(tmp_path))
    assert d["c1"]["decision"] == "keep"


def test_disk_check_missing_file_is_kept(tmp_path):
    _r, _c, d = run(convo(("Read", {"file_path": "gone.py"}, NUMBERED), *filler()),
                    workspace_root=str(tmp_path))
    assert d["c1"]["decision"] == "keep"


def test_disk_check_can_be_turned_off(tmp_path):
    result, _c, d = run(convo(("Read", {"file_path": "gone.py"}, NUMBERED), *filler()),
                        workspace_root=str(tmp_path), disk_check=False)
    assert d["c1"]["decision"] == "replace"
    assert result.report["recoverability_check"] == "transcript_proxy"


# -- read-only commands -----------------------------------------------------------------


def test_read_only_command_is_replaced_by_a_rerun_pointer():
    _r, compacted, d = run(convo(("Bash", {"command": "ls src"}, LISTING), *filler()))
    assert d["c1"]["reason"] == "recoverable_read_only_command"
    assert text_of(compacted, "c1") == "[removed: re-run `ls src` to recover]"


@pytest.mark.parametrize(
    "cmd",
    ["ls -la", "find . -name '*.py'", "rg -n foo src", "grep -rn foo .", "git status",
     "git diff HEAD~1", "git log --oneline -5", "git show HEAD", "wc -l a.py", "tree src", "pwd",
     "node --version", "python3 -V", "cat a.py", "head a.py", "tail -n 5 a.py"],
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
     "git log --output=x", "git branch -D x", "sed -n 1,5p a.py b.py"],
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
                                 ("Bash", {"command": "ls src"}, LISTING), *filler()))
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
