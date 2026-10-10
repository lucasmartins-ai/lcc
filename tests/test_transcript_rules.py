"""provider="rules": the offline, deterministic tool-call policy.

Each test builds a small synthetic transcript and checks one rule, its decision and the reason
it records. Nothing here may touch the network or a model.
"""

from __future__ import annotations

import pytest

import lcc.relevance.transcript as transcript_module
from lcc.relevance import transcript_rules as rules
from lcc.relevance.transcript import TranscriptCompactionRequest, compact_transcript

GOAL = "finish the parser fix"


@pytest.fixture(autouse=True)
def _no_judge(monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")

    def refuse(*_args, **_kwargs):
        raise AssertionError("provider='rules' must never resolve a judge")

    monkeypatch.setattr(transcript_module, "_resolve_client", refuse)


class Convo:
    """Builder: user/assistant text and call/result pairs, one message each."""

    def __init__(self, first: str = "Work on the parser."):
        self.messages: list[dict] = [{"role": "user", "text": first}]
        self.n = 0

    def say(self, text: str, role: str = "assistant") -> Convo:
        self.messages.append({"role": role, "text": text})
        return self

    def call(self, tool: str, tool_input: dict, result: str = "ok") -> str:
        self.n += 1
        cid = f"c{self.n}"
        self.messages.append(
            {
                "role": "assistant",
                "text": "",
                "toolUses": [{"id": cid, "tool": tool, "input": tool_input}],
            }
        )
        self.messages.append(
            {"role": "user", "text": "", "toolResults": [{"id": cid, "text": result}]}
        )
        return cid

    def filler(self, count: int) -> Convo:
        for i in range(count):
            self.say(f"step {i} noted", role="assistant" if i % 2 else "user")
        return self


def run(convo: Convo, goal: str = GOAL, preserve_recent: int = 2):
    return compact_transcript(
        TranscriptCompactionRequest(
            payload={"messages": convo.messages},
            question=goal,
            provider="rules",
            preserve_recent=preserve_recent,
        )
    )


def by_id(result) -> dict[str, dict]:
    return {d["id"]: d for d in result.decisions}


def test_rules_report_is_offline_and_every_decision_has_a_reason():
    c = Convo()
    c.call("Read", {"file_path": "a.py"}, "x" * 50)
    c.filler(4)
    result = run(c)
    report = result.report
    assert report["provider_used"] == "rules"
    assert report["degraded"] is False
    assert report["calls"] == 0
    assert report["semantic_guarantee"] == "none"
    for decision in result.decisions:
        assert decision["reason"]
        assert decision["source"] in ("rules", "pin")


def test_text_is_never_touched():
    c = Convo()
    c.say("A long plan. " * 400)
    c.call("Read", {"file_path": "old.py"}, "o" * 9000)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    result = run(c)
    texts_before = [m["text"] for m in c.messages if m["text"]]
    texts_after = [m.text for m in result.messages if m.text]
    assert texts_after == texts_before


def test_latest_error_and_the_call_before_it_are_kept_whole():
    c = Convo()
    before = c.call("Edit", {"file_path": "p.py", "old_string": "a", "new_string": "b"}, "z" * 5000)
    error = c.call(
        "Bash", {"command": "pytest"}, "Traceback (most recent call last):\n" + "e" * 5000
    )
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    d = by_id(run(c))
    assert (d[error]["decision"], d[error]["reason"]) == ("keep", "latest_error_result")
    assert (d[before]["decision"], d[before]["reason"]) == ("keep", "call_before_latest_error")


def test_is_error_flag_marks_an_error_result():
    c = Convo()
    cid = c.call("Bash", {"command": "make"}, "nothing to see " * 300)
    c.messages[-1]["toolResults"][0]["is_error"] = True
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    assert by_id(run(c))[cid]["reason"] == "latest_error_result"


def test_latest_git_state_is_kept_and_an_older_identical_one_is_superseded():
    c = Convo()
    old = c.call("Bash", {"command": "git status --short"}, "M a.py\n" * 600)
    new = c.call("Bash", {"command": "git status --short"}, "M b.py\n" * 600)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    d = by_id(run(c))
    assert (d[new]["decision"], d[new]["reason"]) == ("keep", "latest_git_state")
    assert d[old]["decision"] == "drop"
    assert d[old]["reason"] == f"superseded_by_later_call:{new}"


def test_latest_task_state_and_artifact_edit_are_kept():
    c = Convo()
    todo = c.call("TodoWrite", {"todos": [{"content": "fix", "status": "pending"}]}, "t" * 3000)
    edit = c.call("Write", {"file_path": "out.md", "content": "w" * 5000}, "written")
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    d = by_id(run(c))
    assert d[todo]["reason"] == "latest_task_state" and d[todo]["decision"] == "keep"
    assert d[edit]["reason"] == "latest_artifact_edit" and d[edit]["decision"] == "keep"


def test_a_call_naming_a_goal_reference_is_kept():
    c = Convo()
    named = c.call("Read", {"file_path": "src/parser/lexer.py"}, "l" * 8000)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "true"}, "")  # the latest result is protected on its own
    d = by_id(run(c, goal="why does src/parser/lexer.py choke on tabs?"))
    assert (d[named]["decision"], d[named]["reason"]) == ("keep", "named_in_goal")


def test_a_read_superseded_by_a_later_read_of_the_same_file_is_dropped():
    c = Convo()
    first = c.call("Read", {"file_path": "a.py"}, "v1 " * 100)
    second = c.call("Read", {"file_path": "a.py"}, "v2 " * 100)
    c.filler(3)
    d = by_id(run(c))
    assert d[first]["decision"] == "drop"
    assert d[first]["reason"] == f"superseded_by_later_call:{second}"


def test_an_old_successful_read_far_from_recent_work_is_dropped():
    c = Convo()
    old = c.call("Grep", {"pattern": "def parse", "path": "src"}, "hit\n" * 50)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    recent = c.call("Glob", {"pattern": "*.toml"}, "pyproject.toml")
    c.filler(3)
    d = by_id(run(c))
    assert (d[old]["decision"], d[old]["reason"]) == ("drop", "stale_read_far_from_recent_work")
    assert d[recent]["decision"] == "keep"


def test_a_read_of_a_file_named_in_recent_turns_is_not_stale():
    c = Convo()
    old = c.call("Read", {"file_path": "src/config.py"}, "cfg\n" * 50)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "true"}, "")  # the latest result is protected on its own
    c.say("Next I will change src/config.py to read the env var.")
    d = by_id(run(c, preserve_recent=1))
    assert d[old]["decision"] == "keep"
    assert d[old]["reason"] == "named_in_recent_turns"


def test_a_large_old_output_is_trimmed_to_head_and_tail():
    c = Convo()
    body = "HEAD" + "m" * 20000 + "TAIL-LINE"
    cid = c.call("Bash", {"command": "npm run build"}, body)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "true"}, "")  # the latest result is protected on its own
    result = run(c)
    d = by_id(result)[cid]
    assert (d["decision"], d["reason"]) == ("trim", "large_old_output_trimmed")
    trimmed = next(r.text for m in result.messages for r in m.tool_results if r.id == cid)
    assert trimmed.startswith("HEAD") and trimmed.endswith("TAIL-LINE")
    assert "lcc:" in trimmed and len(trimmed) < len(body)
    assert d["chars_after"] < d["chars"]


def test_pinned_recent_messages_are_untouched():
    c = Convo()
    c.call("Read", {"file_path": "a.py"}, "v1")
    last = c.call("Read", {"file_path": "a.py"}, "v2 " * 5000)
    d = by_id(run(c, preserve_recent=2))
    assert (d[last]["decision"], d[last]["source"]) == ("keep", "pin")


def test_rules_are_deterministic():
    c = Convo()
    for i in range(30):
        c.call("Read", {"file_path": f"f{i % 7}.py"}, f"body {i} " * (50 * (i % 5 + 1)))
        c.filler(2)
    first, second = run(c), run(c)
    assert first.decisions == second.decisions
    assert first.report["chars_after"] == second.report["chars_after"]


def test_is_error_survives_a_parse_and_payload_round_trip():
    from lcc.relevance.transcript import messages_to_payload, parse_transcript

    payload = [
        {"role": "user", "text": "go"},
        {"role": "assistant", "text": "", "toolUses": [{"id": "a", "tool": "Bash", "input": {}}]},
        {"role": "user", "text": "", "toolResults": [{"id": "a", "text": "no", "is_error": True}]},
    ]
    back = messages_to_payload(parse_transcript(payload))
    assert back[2]["toolResults"] == [{"tool_use_id": "a", "text": "no", "is_error": True}]
    assert "is_error" not in messages_to_payload(parse_transcript(payload[:2]))[1]


def test_the_options_last_offered_to_the_user_are_kept():
    c = Convo()
    asked = c.call("AskUserQuestion", {"question": "A or B?"}, "q" * 3000)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "true"}, "")
    d = by_id(run(c))
    assert (d[asked]["decision"], d[asked]["reason"]) == ("keep", "latest_user_question")


def test_the_most_recent_tool_result_is_kept_even_when_unpinned():
    c = Convo()
    last = c.call("Grep", {"pattern": "x", "path": "src"}, "r" * 5000)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    d = by_id(run(c))
    assert (d[last]["decision"], d[last]["reason"]) == ("keep", "latest_tool_result")


def test_a_command_run_again_supersedes_the_earlier_run():
    c = Convo()
    first = c.call("Bash", {"command": "npm test"}, "1 failed")
    second = c.call("Bash", {"command": "npm test"}, "all passed")
    c.filler(3)
    d = by_id(run(c))
    assert d[first]["reason"] == f"superseded_by_later_call:{second}"


def test_an_edit_is_superseded_by_a_later_read_but_a_read_is_not_by_an_edit():
    c = Convo()
    read = c.call("Read", {"file_path": "a.py"}, "body")
    edit = c.call("Edit", {"file_path": "a.py", "old_string": "x", "new_string": "y"}, "ok")
    reread = c.call("Read", {"file_path": "a.py"}, "body2")
    c.call("Edit", {"file_path": "b.py", "old_string": "x", "new_string": "y"}, "ok")
    c.filler(3)
    d = by_id(run(c))
    assert d[edit]["reason"] == f"superseded_by_later_call:{reread}"
    # The read before the edit is superseded by the re-read, never by the edit itself.
    assert d[read]["reason"] == f"superseded_by_later_call:{reread}"


def test_an_old_failed_read_is_not_dropped_as_stale():
    c = Convo()
    failed = c.call("Read", {"file_path": "gone.py"}, "Error: file not found")
    c.call("Bash", {"command": "ls"}, "a b")
    c.call("Bash", {"command": "pytest"}, "Traceback (most recent call last):\nboom")
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "true"}, "")
    d = by_id(run(c))
    assert (d[failed]["decision"], d[failed]["reason"]) == ("keep", "kept_default")


def test_an_mcp_read_tool_counts_as_a_read():
    c = Convo()
    old = c.call("mcp__docs__get_page", {"id": "p1"}, "page")
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "true"}, "")
    assert by_id(run(c))[old]["reason"] == "stale_read_far_from_recent_work"


def test_a_small_old_non_read_output_is_kept_by_default():
    c = Convo()
    cid = c.call("Bash", {"command": "ls"}, "a b c")
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "true"}, "")
    d = by_id(run(c))[cid]
    assert (d["decision"], d["reason"], d["chars_after"]) == ("keep", "kept_default", d["chars"])


# --- review regressions (PR #45) ---------------------------------------------------------


def _error_result(c: Convo) -> None:
    c.messages[-1]["toolResults"][0]["is_error"] = True


def test_a_partial_read_does_not_supersede_a_full_read():
    c = Convo()
    full = c.call("Read", {"file_path": "/r/a.py"}, "f" * 5000)
    c.call("Read", {"file_path": "/r/a.py", "offset": 10, "limit": 5}, "five lines")
    c.filler(4)
    assert not by_id(run(c))[full]["reason"].startswith("superseded_by_later_call")


@pytest.mark.parametrize("tool", ["Read", "Write"])
def test_a_failed_later_view_does_not_supersede_a_good_one(tool):
    c = Convo()
    good = c.call("Read", {"file_path": "/r/a.py"}, "f" * 5000)
    c.call("Bash", {"command": "ls"}, "a.py")  # keeps `good` out of call_before_latest_error
    c.call(tool, {"file_path": "/r/a.py", "content": "x"}, "File does not exist.")
    _error_result(c)
    c.filler(4)
    assert not by_id(run(c))[good]["reason"].startswith("superseded_by_later_call")


def test_source_code_mentioning_error_is_not_the_latest_error():
    c = Convo()
    failing = c.call(
        "Bash", {"command": "pytest"}, "FAILED tests/test_p.py::t - AssertionError\n" + "e" * 3000
    )
    c.call("Bash", {"command": "pwd"}, "/r")
    source = c.call("Read", {"file_path": "/r/p.py"}, "class ParseError(Exception):\n    pass\n")
    c.filler(4)
    d = by_id(run(c))
    assert (d[failing]["decision"], d[failing]["reason"]) == ("keep", "latest_error_result")
    assert d[source]["reason"] != "latest_error_result"


def test_is_error_flag_wins_over_the_text_regex():
    c = Convo()
    flagged = c.call("Bash", {"command": "make"}, "make: *** [all] stopped " + "m" * 3000)
    _error_result(c)
    c.call("Bash", {"command": "grep -rn Error src"}, "src/p.py: raise Error('x')")
    c.filler(4)
    assert by_id(run(c))[flagged]["reason"] == "latest_error_result"


def test_the_read_of_a_goal_named_file_is_kept_after_a_later_listing_mentions_it():
    c = Convo()
    read = c.call("Read", {"file_path": "/r/app.py"}, "a" * 3000)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Glob", {"pattern": "**/*app.py"}, "/r/app.py\n/r/webapp.py")
    c.filler(4)
    d = by_id(run(c, goal="fix the bug in app.py"))
    assert (d[read]["decision"], d[read]["reason"]) == ("keep", "named_in_goal")


def test_a_bare_goal_name_does_not_match_a_longer_file_name():
    c = Convo()
    other = c.call("Read", {"file_path": "/r/webapp.py"}, "w" * 3000)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Bash", {"command": "pwd"}, "/r")
    c.filler(4)
    assert by_id(run(c, goal="fix the bug in app.py"))[other]["reason"] != "named_in_goal"


# --- trim guards (v0.5 DEV round 1) ------------------------------------------------------------
# Each guard keeps a large output whole that the old rule would trim; the reason names the guard.

BIG = "HEAD" + "m" * 20000 + "TAIL-LINE"


def _old_big(c: Convo, tool: str = "exec_command", tool_input: dict | None = None, body: str = BIG):
    cid = c.call(tool, tool_input or {"cmd": "npm run build"}, body)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("exec_command", {"cmd": "true"}, "")  # the latest result is protected on its own
    return cid


def test_a_trim_keeps_a_larger_head_and_tail():
    c = Convo()
    cid = _old_big(c)
    result = run(c)
    d = by_id(result)[cid]
    assert (d["decision"], d["reason"]) == ("trim", "large_old_output_trimmed")
    trimmed = next(r.text for m in result.messages for r in m.tool_results if r.id == cid)
    head, _, tail = trimmed.partition("[... lcc:")
    assert len(head.rstrip("\n")) == rules.TRIM_HEAD_CHARS >= 1000
    assert trimmed.endswith(BIG[-rules.TRIM_TAIL_CHARS :]) and rules.TRIM_TAIL_CHARS >= 1000


def test_an_output_under_the_raised_threshold_is_kept_whole():
    c = Convo()
    cid = _old_big(c, body="x" * (rules.LARGE_RESULT_CHARS - 1))
    assert rules.LARGE_RESULT_CHARS >= 4000
    assert by_id(run(c))[cid]["decision"] == "keep"


def test_a_large_output_within_the_recent_horizon_is_not_trimmed():
    c = Convo()
    cid = c.call("exec_command", {"cmd": "npm run build"}, BIG)
    c.filler(rules.TRIM_MIN_AGE_MESSAGES - 6)
    c.call("exec_command", {"cmd": "true"}, "")
    d = by_id(run(c))[cid]
    assert (d["decision"], d["reason"]) == ("keep", "trim_guard_recent")


def test_a_read_of_a_file_patched_later_is_not_trimmed():
    c = Convo()
    cid = c.call("exec_command", {"cmd": "sed -n '1,400p' src/app/page.tsx"}, BIG)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call(
        "apply_patch",
        {
            "input": "*** Begin Patch\n*** Update File: /r/src/app/page.tsx\n@@\n-a\n+b\n*** End Patch"
        },
        "Success",
    )
    c.filler(4)
    c.call("exec_command", {"cmd": "true"}, "")
    d = by_id(run(c))[cid]
    assert (d["decision"], d["reason"]) == ("keep", "trim_guard_edited_later")


def test_a_read_of_a_file_edited_later_by_a_claude_edit_is_not_trimmed():
    c = Convo()
    cid = c.call("Bash", {"command": "cat src/config.py"}, BIG)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("Edit", {"file_path": "/r/src/config.py", "old_string": "a", "new_string": "b"}, "ok")
    c.filler(4)
    c.call("exec_command", {"cmd": "true"}, "")
    assert by_id(run(c))[cid]["reason"] == "trim_guard_edited_later"


def test_an_unrelated_later_patch_does_not_block_the_trim():
    c = Convo()
    cid = c.call("exec_command", {"cmd": "sed -n '1,400p' src/webapp.py"}, BIG)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call(
        "apply_patch",
        {"input": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-a\n+b\n*** End Patch"},
        "Success",
    )
    c.filler(4)
    c.call("exec_command", {"cmd": "true"}, "")
    assert by_id(run(c))[cid]["decision"] == "trim"


@pytest.mark.parametrize("tool", ["write_stdin", "wait", "multi_agent_v1__wait_agent"])
def test_interactive_and_wait_outputs_are_not_trimmed(tool):
    c = Convo()
    cid = _old_big(c, tool=tool, tool_input={"session_id": 7, "chars": ""})
    d = by_id(run(c))[cid]
    assert (d["decision"], d["reason"]) == ("keep", "trim_guard_interactive")


def test_an_error_bearing_output_is_not_trimmed():
    # No is_error flags in the transcript: error text in command output marks the error.
    c = Convo()
    cid = _old_big(c, body="ok\n" * 3000 + "FAILED tests/test_x.py::test_y\n" + "z" * 3000)
    c.call("exec_command", {"cmd": "pytest"}, "Traceback (most recent call last):\nboom")
    c.filler(4)
    d = by_id(run(c))[cid]
    assert (d["decision"], d["reason"]) == ("keep", "trim_guard_error")


def test_a_flagged_output_is_not_trimmed_and_error_words_in_a_clean_one_are_not_errors():
    c = Convo()
    failed = c.call("exec_command", {"cmd": "npm test"}, BIG)
    c.messages[-1]["toolResults"][0]["is_error"] = True
    source = c.call(
        "exec_command", {"cmd": "cat src/errors.py"}, "class ParseError(Exception):\n" + BIG
    )
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("exec_command", {"cmd": "true"}, "")
    d = by_id(run(c))
    assert d[failed]["decision"] == "keep" and d[failed]["reason"] in (
        "trim_guard_error",
        "latest_error_result",
    )
    assert d[source]["decision"] == "trim"


def test_an_output_whose_call_names_a_goal_reference_is_not_trimmed():
    c = Convo()
    cid = c.call("exec_command", {"cmd": "cat docs/ROADMAP.md"}, BIG)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("exec_command", {"cmd": "cat docs/ROADMAP.md | wc -l"}, "12")  # latest mention
    c.call("exec_command", {"cmd": "true"}, "")
    d = by_id(run(c, goal="update docs/ROADMAP.md with the new dates"))[cid]
    assert (d["decision"], d["reason"]) == ("keep", "trim_guard_named")


def test_an_output_whose_call_names_a_recent_turn_reference_is_not_trimmed():
    c = Convo()
    cid = c.call("exec_command", {"cmd": "cat src/billing.py"}, BIG)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("exec_command", {"cmd": "true"}, "")
    c.say("Next I will fix src/billing.py rounding.")
    assert by_id(run(c, preserve_recent=1))[cid]["reason"] == "trim_guard_named"


def test_guards_do_not_change_drops():
    c = Convo()
    first = c.call("exec_command", {"cmd": "cat src/a.py"}, BIG)
    second = c.call("exec_command", {"cmd": "cat src/a.py"}, BIG)
    c.filler(3)
    d = by_id(run(c, goal="fix src/a.py"))
    assert (
        d[first]["decision"] == "drop"
        and d[first]["reason"] == f"superseded_by_later_call:{second}"
    )


def test_a_shared_workdir_is_not_a_named_reference():
    c = Convo()
    cid = c.call("exec_command", {"cmd": "npm run build", "workdir": "/r/proj"}, BIG)
    c.filler(rules.STALE_AFTER_MESSAGES + 2)
    c.call("exec_command", {"cmd": "true", "workdir": "/r/proj"}, "")
    c.say("Build is done in /r/proj.")
    d = by_id(run(c, goal="ship /r/proj", preserve_recent=2))[cid]
    assert d["decision"] == "trim"
