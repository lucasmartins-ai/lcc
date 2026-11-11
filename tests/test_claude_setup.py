"""`lcc setup`: one command for the Claude Code settings that make lcc run on its own."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.claude_setup import (
    HINT,
    OFFER,
    PLUGIN,
    THRESHOLD,
    TOOLS,
    WINDOW,
    SetupError,
    load,
    plan,
    window,
    write,
)
from lcc.cli import app


def test_plan_from_nothing_sets_the_whole_profile_and_a_second_plan_changes_nothing() -> None:
    new, changes = plan({})
    assert new["env"] == {"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"}  # no threshold by default
    assert new["pluginConfigs"][PLUGIN]["options"] == {"provider": "rules", "rulesMode": "stashed"}
    assert new["permissions"]["allow"] == list(TOOLS)
    assert new["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == HINT
    assert new["hooks"]["SessionStart"][0]["matcher"] == "startup"
    assert new["hooks"]["SessionStart"][0]["hooks"][0]["command"] == OFFER
    assert len(changes) == 7
    assert plan(new) == (new, [])


def test_the_window_comes_from_the_file_then_the_environment_then_200k() -> None:
    assert window({}) == 200_000
    assert window({}, {WINDOW: "300000"}) == 300_000
    assert window({"env": {WINDOW: "500000"}}, {WINDOW: "300000"}) == 500_000
    assert window({"env": {WINDOW: "100k"}}, {WINDOW: "nope"}) == 200_000  # unreadable: unset
    # A key in the file overrides the environment even when empty: no fallback to it.
    assert window({"env": {WINDOW: ""}}, {WINDOW: "1000000"}) == 200_000
    assert window({}, {WINDOW: "2000000"}) == 1_000_000  # capped


def test_a_threshold_that_compacts_under_150k_is_refused_or_removed() -> None:
    # The incident: 40 % of a 300k window is 120k, about a session's fixed load, so Claude Code
    # compacted again right after each compaction. setup wrote that 40 itself.
    incident = {"env": {THRESHOLD: "40", WINDOW: "300000"}}
    new, changes = plan(incident)
    assert THRESHOLD not in new["env"] and new["env"][WINDOW] == "300000"
    assert any(c.startswith(f'env.{THRESHOLD}: "40" -> unset (40 % of the 300000') for c in changes)
    with pytest.raises(SetupError, match="use 50 or more"):
        plan({}, 40, {WINDOW: "300000"})
    with pytest.raises(SetupError, match="use 75 or more"):
        plan({}, 40)  # the 200k default window
    with pytest.raises(SetupError, match="leave it unset"):
        plan({}, 90, {WINDOW: "100000"})  # no percentage of a 100k window reaches 150k
    assert plan({}, 50, {WINDOW: "300000"})[0]["env"][THRESHOLD] == "50"
    assert plan({}, 15, {WINDOW: "1000000"})[0]["env"][THRESHOLD] == "15"
    # A large window with no threshold named: none is written.
    assert THRESHOLD not in plan({"env": {WINDOW: "1000000"}})[0]["env"]
    # Claude Code reads "40.0" as 40: removed too.
    assert THRESHOLD not in plan({"env": {THRESHOLD: "40.0", WINDOW: "300000"}})[0]["env"]
    with pytest.raises(SetupError):
        plan({}, 10, {WINDOW: "2000000"})  # 10 % of the 1M cap is 100k
    # Not a number: not ours to judge, left alone.
    assert plan({"env": {THRESHOLD: "auto"}})[0]["env"][THRESHOLD] == "auto"


def test_plan_keeps_what_the_user_already_has() -> None:
    theirs = {
        "theme": "dark",
        "env": {THRESHOLD: "35", WINDOW: "1000000", "OTHER": "x"},
        "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Read(.env)"]},
        "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "mine"}]}]},
        "pluginConfigs": {PLUGIN: {"options": {"provider": "jev", "idleStash": True}}},
        "statusLine": {"type": "command", "command": "theirs"},
    }
    before = json.dumps(theirs)
    new, changes = plan(theirs)
    assert json.dumps(theirs) == before  # the input is not mutated
    assert new["theme"] == "dark" and new["statusLine"] == theirs["statusLine"]
    assert new["env"][THRESHOLD] == "35" and new["env"]["OTHER"] == "x"  # their threshold stands
    assert not any(THRESHOLD in change for change in changes)
    assert new["permissions"] == {"allow": ["Bash(ls:*)", *TOOLS], "deny": ["Read(.env)"]}
    assert [h["hooks"][0]["command"] for h in new["hooks"]["UserPromptSubmit"]] == ["mine", HINT]
    assert new["pluginConfigs"][PLUGIN]["options"] == {
        "provider": "rules",
        "idleStash": True,
        "rulesMode": "stashed",
    }
    assert f'{PLUGIN} provider: "jev" -> "rules"' in changes  # an overwrite is always shown
    assert plan(theirs, 30)[0]["env"][THRESHOLD] == "30"  # named on the command line: it wins


def test_a_hook_wired_under_a_matcher_that_leaves_startup_out_is_not_wired() -> None:
    def wired(matcher: str) -> dict:
        group = {"matcher": matcher, "hooks": [{"type": "command", "command": OFFER}]}
        return {"hooks": {"SessionStart": [group]}}

    assert len(plan(wired("compact"))[0]["hooks"]["SessionStart"]) == 2
    assert len(plan(wired("not-startup"))[0]["hooks"]["SessionStart"]) == 2  # a regex, not a word
    for covers in ("startup", "startup|resume", "*", ""):
        assert len(plan(wired(covers))[0]["hooks"]["SessionStart"]) == 1


@pytest.mark.parametrize(
    "broken", [{"env": []}, {"hooks": {"SessionStart": {}}}, {"permissions": {"allow": "x"}}]
)
def test_plan_refuses_a_section_of_the_wrong_type_instead_of_replacing_it(broken: dict) -> None:
    with pytest.raises(SetupError):
        plan(broken)


def test_write_keeps_the_original_once_the_mode_and_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text('{"theme": "dark"}', encoding="utf-8")
    os.chmod(real, 0o640)
    link = tmp_path / "settings.json"
    link.symlink_to(real)

    current, raw = load(link)
    backup = write(link, plan(current)[0], raw)
    assert backup is not None and link.is_symlink()
    assert backup == real.with_name("settings.json.before-lcc-setup")
    assert backup.read_text(encoding="utf-8") == '{"theme": "dark"}'
    assert stat.S_IMODE(real.stat().st_mode) == 0o640
    written, raw = load(link)
    assert written["theme"] == "dark" and written["env"]["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] == "1"

    # A second write never overwrites the first backup: it is the file before lcc touched it.
    assert write(link, plan(written, 80)[0], raw) is None
    assert backup.read_text(encoding="utf-8") == '{"theme": "dark"}'
    assert [p.name for p in real.parent.iterdir() if p.name.startswith(".tmp-")] == []


def test_write_refuses_when_the_file_changed_since_it_was_read(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    current, raw = load(path)
    path.write_text('{"theme": "light"}', encoding="utf-8")  # Claude Code wrote it meanwhile
    with pytest.raises(SetupError, match="changed while"):
        write(path, plan(current)[0], raw)
    assert path.read_text(encoding="utf-8") == '{"theme": "light"}'
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]  # no backup, no leftover


def test_cli_lists_by_default_writes_with_apply_and_then_has_nothing_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(WINDOW, raising=False)
    path = tmp_path / "claude" / "settings.json"
    args = ["setup", "--settings", str(path)]
    listed = CliRunner().invoke(app, args)
    assert listed.exit_code == 0 and "would set" in listed.output and "--apply" in listed.output
    assert not path.exists()

    refused = CliRunner().invoke(app, [*args, "--apply", "--compact-at", "40"])
    assert refused.exit_code == 2 and "use 75 or more" in " ".join(refused.output.split())
    assert not path.exists()
    monkeypatch.setenv(WINDOW, "300000")
    applied = CliRunner().invoke(app, [*args, "--apply", "--compact-at", "50"])
    assert applied.exit_code == 0, applied.output
    assert json.loads(path.read_text(encoding="utf-8"))["env"][THRESHOLD] == "50"
    assert "already set up" in CliRunner().invoke(app, args).output


def test_cli_leaves_a_file_it_cannot_read_as_settings_alone(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    out = CliRunner().invoke(app, ["setup", "--settings", str(path), "--apply"])
    assert out.exit_code == 2 and "nothing was changed" in " ".join(out.output.split())
    assert path.read_text(encoding="utf-8") == "{ not json"
    assert CliRunner().invoke(app, ["setup", "--compact-at", "0"]).exit_code == 2
