"""The pass receipt (one line, and --receipt) and the opt-in ledger (counts only)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.cli import app
from lcc.mcp_server import _tool_compact_transcript
from lcc.receipt import ledger_record, pass_stands, receipt_full, receipt_line, session_key

runner = CliRunner()
MEDIUM = Path(__file__).resolve().parents[1] / "benchmarks/research/corpora/transcripts/medium.json"

STASHED = {
    "tokens_before": 48210,
    "tokens_after": 31004,
    "token_count_method": "exact",
    "tool_calls_stashed": 2,
    "tool_calls_replaced": 2,
    "tool_calls_deduped": 1,
    "tool_calls_dropped": 0,
    "tool_calls_trimmed": 0,
    "cache_effect": {
        "cache_state": "cold",
        "stable_prefix_tokens": 1200,
        "rewritten_tokens": 29804,
        "estimated_relative_cost_delta": -0.3571,
        "recommended": True,
        "reason": "saves_cost_cold_cache",
    },
    "decisions": [
        {"tool": "Read", "decision": "replace", "stash": {"sha256": "a" * 64, "tokens": 9000}},
        {"tool": "Bash", "decision": "replace", "stash": {"sha256": "b" * 64, "tokens": 8000}},
        {"tool": "Grep", "decision": "dedupe"},
    ],
}


def test_receipt_line_says_what_went_how_much_and_how_to_recall():
    assert receipt_line(STASHED) == (
        "lcc: 48,210 -> 31,004 tokens (-17,206, -35.7%) · 2 stashed, 1 deduped · "
        "recall: lcc recall aaaaaaaaaaaa (+1 more)"
    )


def test_receipt_line_without_decisions_still_points_at_recall():
    report = {key: value for key, value in STASHED.items() if key != "decisions"}
    assert receipt_line(report).endswith(
        "recall: lcc recall <id> from each [removed: ...] placeholder"
    )


def test_receipt_line_is_honest_about_what_cannot_come_back():
    dropped = {"tokens_before": 100, "tokens_after": 40, "tool_calls_dropped": 2}
    assert receipt_line(dropped) == (
        "lcc: 100 -> 40 tokens (-60, -60.0%) · 2 dropped · "
        "dropped/trimmed outputs are not recallable (use rules_mode stashed for that)"
    )
    lossless = {"tokens_before": 100, "tokens_after": 70, "tool_calls_deduped": 1}
    assert receipt_line(lossless).endswith(
        "nothing to recall: each removed output is still in context or on disk"
    )
    assert receipt_line({"tokens_before": 100, "tokens_after": 100}) == (
        "lcc: nothing removed (100 tokens)"
    )


def test_full_receipt_snapshot():
    assert receipt_full(STASHED) == "\n".join(
        [
            receipt_line(STASHED),
            "  token count: exact",
            "  largest stashed outputs (2 of 2):",
            "    lcc recall aaaaaaaaaaaa  9,000 tokens  Read",
            "    lcc recall bbbbbbbbbbbb  8,000 tokens  Bash",
            "  cache (cold): 1,200 tokens stay cached, 29,804 re-written, est. cost -35.7%; "
            "recommended (saves_cost_cold_cache)",
        ]
    )


def test_session_key_matches_the_statusline():
    # test/statusline.test.mjs pins the same value on the Node side.
    assert session_key("fixture-session-a") == "e279159a3ffc189d"
    assert session_key("") is None and session_key(None) is None


def test_ledger_record_holds_counts_only():
    record = ledger_record(STASHED | {"provider_used": "rules"}, session_id="s-1")
    assert set(record) == {
        "v",
        "ts",
        "session",
        "provider",
        "tokens_before",
        "tokens_after",
        "stashed",
        "deduped",
        "replaced",
        "dropped",
        "trimmed",
    }
    assert record["session"] == session_key("s-1") and record["stashed"] == 2


def test_pass_stands_mirrors_the_hook_rule():
    assert pass_stands({"worth_it": True, "tool_calls_deduped": 1})
    assert not pass_stands({"worth_it": False, "tool_calls_deduped": 1})
    assert not pass_stands({"worth_it": True, "degraded": True, "tool_calls_deduped": 1})
    assert not pass_stands({"worth_it": True})


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    monkeypatch.setenv("LCC_LEDGER_PATH", str(tmp_path / "ledger" / "ledger.jsonl"))
    monkeypatch.delenv("LCC_LEDGER", raising=False)
    return tmp_path / "ledger" / "ledger.jsonl"


def _call(**extra):
    payload = json.loads(MEDIUM.read_text())
    return _tool_compact_transcript(
        {
            "messages": payload["messages"],
            "question": "cut the retry storm",
            "provider": "rules",
            "rules_mode": "stashed",
            "min_reduction": 0,
            **extra,
        }
    )


def test_mcp_answer_carries_the_receipt_and_writes_no_ledger_by_default(env: Path):
    answer = _call(ref_blocks=True)
    assert answer["receipt"].startswith("lcc: ") and "lcc recall " in answer["receipt"]
    assert not env.exists()


def test_mcp_ledger_is_opt_in_private_and_has_no_text(env: Path, monkeypatch):
    _call(ledger=True, ledger_session="sess-1")
    lines = env.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["session"] == session_key("sess-1") and record["stashed"] > 0
    assert "sess-1" not in lines[0] and "retry" not in lines[0]
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert stat.S_IMODE(env.parent.stat().st_mode) == 0o700
    # LCC_LEDGER=1 turns it on without the argument; the idle stash is never recorded.
    monkeypatch.setenv("LCC_LEDGER", "1")
    _call()
    _call(trigger="idle")
    assert len(env.read_text().splitlines()) == 2


def test_mcp_ledger_skips_a_pass_the_hook_would_not_apply(env: Path):
    _call(ledger=True, min_reduction=0.99)
    assert not env.exists()


def test_cli_prints_one_line_and_full_receipt_on_request(env: Path, tmp_path: Path):
    base = [
        "compact",
        str(MEDIUM),
        "-q",
        "cut the retry storm",
        "--mode",
        "tool-calls",
        "--provider",
        "rules",
        "--rules-mode",
        "stashed",
        "-o",
        str(tmp_path / "out.json"),
    ]
    short = runner.invoke(app, base)
    assert short.exit_code == 0, short.output
    last = short.output.strip().splitlines()[-1]
    assert last.startswith("lcc: ") and "stashed" in last and "lcc recall " in last
    assert "largest stashed outputs" not in short.output
    full = runner.invoke(app, [*base, "--receipt"])
    assert full.exit_code == 0, full.output
    assert "largest stashed outputs" in full.output and "cache (" in full.output
    assert not env.exists(), "the CLI never writes the ledger"


def test_cli_refuses_receipt_outside_tool_calls(tmp_path: Path):
    src = tmp_path / "in.txt"
    src.write_text("some context\n")
    result = runner.invoke(app, ["compact", str(src), "-q", "x", "--receipt"])
    assert result.exit_code == 2 and "--receipt" in result.output


def test_full_receipt_escapes_control_characters_in_tool_names():
    report = STASHED | {
        "decisions": [
            {
                "tool": "Evil\x1b[2J",
                "decision": "replace",
                "stash": {"sha256": "c" * 64, "tokens": 5},
            }
        ]
    }
    full = receipt_full(report)
    assert "\x1b" not in full and "Evil\\x1b[2J" in full


def test_ledger_tightens_an_existing_world_readable_file(env: Path):
    env.parent.mkdir(parents=True)
    env.write_text("")
    env.chmod(0o644)
    _call(ledger=True)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_explicit_ledger_false_beats_the_env(env: Path, monkeypatch):
    monkeypatch.setenv("LCC_LEDGER", "1")
    _call(ledger=False)
    assert not env.exists()
