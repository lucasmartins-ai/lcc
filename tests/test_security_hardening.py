"""Regression tests for the security hardening pass (see SECURITY.md, "Threat model").

Each test pins one demonstrated gap: a file oracle over HTTP, a crash on nested JSON,
quadratic cleaning on adversarial input, remote scoring without explicit opt-in, the
network kill switch, terminal escapes in ``lcc explain``, and secrets in local logs.
"""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lcc import chatgpt_server, mcp_server

SRC = Path(__file__).resolve().parents[1] / "src"
FILE = "".join(f"line {n} of the secret config\n" for n in range(1, 40))


# -- 1. path handling -----------------------------------------------------------------------


def _probe_call(target: Path, guess: str, **extra: object) -> dict:
    """A crafted transcript that asks the disk check whether ``target`` holds ``guess``."""
    messages = [
        {"role": "user", "text": "tidy up"},
        {"role": "assistant", "text": "reading",
         "toolUses": [{"id": "c1", "tool": "Bash", "input": {"command": f"cat {target}"}}]},
        {"role": "user", "text": "", "toolResults": [{"id": "c1", "text": guess}]},
        {"role": "assistant", "text": "grep",
         "toolUses": [{"id": "c2", "tool": "Grep", "input": {"pattern": "x"}}]},
        {"role": "user", "text": "", "toolResults": [{"id": "c2", "text": "0 matches"}]},
        {"role": "assistant", "text": "done"},
    ]
    arguments = {"messages": messages, "question": "tidy up", "provider": "rules",
                 "rules_mode": "recoverable", "preserve_recent": 1, **extra}
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "compact_transcript", "arguments": arguments}}


def test_disk_check_is_an_oracle_locally_so_http_must_refuse_it(tmp_path, monkeypatch):
    import re

    import lcc.relevance.transcript_recoverable as recoverable_module

    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.delenv(chatgpt_server.TOKEN_ENV, raising=False)
    # tmp_path lives in /tmp, which the policy never trusts; a real target would not.
    monkeypatch.setattr(recoverable_module, "_TEMP", re.compile(r"(?!)"))
    secret = tmp_path / "secret.cfg"
    secret.write_text(FILE)
    # Over stdio the caller is the local agent: the disk check may confirm a guess.
    local = mcp_server.handle_message(_probe_call(secret, FILE, workspace_root=str(tmp_path)))
    decisions = json.loads(local["result"]["content"][0]["text"])["decisions"]
    assert decisions[0]["reason"] == "replace_disk_verified"
    # Over HTTP (anonymous or not) the same probe would confirm the host's file contents.
    for extra in ({"workspace_root": str(tmp_path)}, {"laya_model": str(tmp_path)}):
        response, _ = chatgpt_server._handle(_probe_call(secret, FILE, **extra))
        assert response is not None and response["error"]["code"] == -32602
        assert "never over HTTP" in response["error"]["message"]


def test_http_errors_never_echo_exception_text(monkeypatch):
    def boom(_message, **_):
        raise RuntimeError("contents of /etc/shadow")

    monkeypatch.setattr(chatgpt_server, "handle_message", boom)
    response, _ = chatgpt_server._handle({"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert response == {"jsonrpc": "2.0", "id": 7,
                        "error": {"code": -32603, "message": "internal error"}}


def test_http_transcript_shape_errors_keep_their_reason(monkeypatch):
    from lcc.relevance.transcript import TranscriptError

    def shape_error(_message, **_):
        raise TranscriptError("message 0 has text under 'content'")

    monkeypatch.setattr(chatgpt_server, "handle_message", shape_error)
    response, _ = chatgpt_server._handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call"})
    assert response == {"jsonrpc": "2.0", "id": 8,
                        "error": {"code": -32602,
                                  "message": "message 0 has text under 'content'"}}


@pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "abc", "A" * 64,
                                 "0123456789ab/..", "0123456789ab*"])
def test_recall_refuses_ids_that_are_not_hex(bad, tmp_path, monkeypatch):
    from lcc.relevance.transcript_stash import StashError, recall

    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path))
    with pytest.raises(StashError, match="not a stash id"):
        recall(bad)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_stash_is_private(tmp_path, monkeypatch):
    from lcc.relevance.transcript_stash import put, recall

    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    digest = put("session output")
    assert stat.S_IMODE((tmp_path / "stash").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "stash" / digest).stat().st_mode) == 0o600
    assert recall(digest[:12]) == "session output"


# -- 2. network boundary --------------------------------------------------------------------


class _Judge:
    model = "jev-latest"
    last_resolved_model = "jev-latest"

    def evaluate(self, state, questions):  # pragma: no cover - must never run
        raise AssertionError("auto sent text to a remote judge without opt-in")


def _plain_auto():
    from lcc.relevance import RelevanceCompactionRequest, compact_context

    text = "Mobile booking drops at step two.\n\nOffice plants need water."
    return compact_context(
        RelevanceCompactionRequest(text=text, question="booking drop", provider="auto")
    )


def test_auto_never_goes_remote_just_because_a_key_exists(monkeypatch):
    from lcc.relevance import compactor

    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_live_configured_but_not_consented")
    monkeypatch.delenv("LCC_AUTO_REMOTE", raising=False)
    monkeypatch.delenv("LCC_DISABLE_NETWORK", raising=False)
    resolved: list[bool] = []
    monkeypatch.setattr(compactor, "_resolve_client", lambda: resolved.append(True) or _Judge())
    result = _plain_auto()
    assert resolved == []  # the key was never even looked up
    assert result.report.provider_used == "mechanical"
    assert result.report.degradation_reason == "jev_unavailable_mechanical_fallback"
    assert any(w.startswith("auto_local_only") for w in result.report.warnings)


def test_auto_remote_is_an_explicit_opt_in(monkeypatch):
    from lcc.relevance import compactor

    monkeypatch.setenv("LCC_AUTO_REMOTE", "1")
    monkeypatch.delenv("LCC_DISABLE_NETWORK", raising=False)
    resolved: list[bool] = []
    monkeypatch.setattr(compactor, "_resolve_client", lambda: resolved.append(True) or None)
    _plain_auto()
    assert resolved == [True]
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")  # the kill switch still wins
    resolved.clear()
    _plain_auto()
    assert resolved == []


def test_kill_switch_blocks_cloud_and_remote_local_agent(monkeypatch):
    import urllib.request

    from lcc.agents.local_agent import LocalAgent, LocalAgentConfig
    from lcc.router.cloud_client import FireworksRemoteSolver
    from lcc.router.errors import RemoteProviderError
    from lcc.router.schemas import TaskInput

    def no_network(*_args, **_kwargs):
        raise AssertionError("network call with LCC_DISABLE_NETWORK=1")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    task = TaskInput(task_id="t", instruction="q", context="c")
    with pytest.raises(RemoteProviderError, match="LCC_DISABLE_NETWORK"):
        FireworksRemoteSolver(api_key="fw-key").complete(task, "prompt")
    agent = LocalAgent(LocalAgentConfig(backend="ollama", endpoint="http://10.0.0.5:11434"))
    with pytest.raises(ConnectionRefusedError):
        agent._http_post("http://10.0.0.5:11434/api/generate", {})
    assert agent.health_check().healthy is False


# -- 3. MCP / HTTP input robustness ---------------------------------------------------------


def test_stdio_server_survives_deeply_nested_json():
    nested = b"[" * 200_000 + b"]" * 200_000
    stdin = nested + b"\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}).encode()
    proc = subprocess.run(
        [sys.executable, "-m", "lcc.mcp_server"], input=stdin + b"\n", capture_output=True,
        timeout=60, env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    assert proc.returncode == 0, proc.stderr.decode()[-500:]
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 2  # still serving after the bad message


def test_http_rejects_deeply_nested_json():
    import threading
    import urllib.error

    server = chatgpt_server.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/mcp"
        body = b"[" * 200_000 + b"]" * 200_000
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=20)
        assert caught.value.code == 400
        assert "nested too deeply" in caught.value.read().decode()
    finally:
        server.shutdown()
        server.server_close()


def _http_tool_text(arguments, tool="compact"):
    response, _ = chatgpt_server._handle(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": tool, "arguments": arguments}})
    assert response is not None and response["result"]["isError"] is True
    return response["result"]["content"][0]["text"]


@pytest.mark.parametrize("exc", [ValueError, KeyError, TypeError])
def test_http_tool_errors_never_echo_exception_text(exc, monkeypatch):
    def broken(_args):
        raise exc("/srv/secret/path")

    monkeypatch.setitem(mcp_server.TOOLS["compact"], "handler", broken)
    assert _http_tool_text({}) == f"error: tool call failed ({exc.__name__})"


@pytest.mark.parametrize("threshold", ["abc", [1]])
def test_http_bad_numbers_answer_a_fixed_message(threshold):
    text = _http_tool_text({"text": "y", "question": "x", "threshold": threshold})
    assert text == "error: 'threshold' must be a number"


def test_http_infinite_int_answers_a_fixed_message():
    arguments = {"messages": [{"role": "user", "content": "hi"}], "question": "x",
                 "provider": "rules", "preserve_recent": float("inf")}
    text = _http_tool_text(arguments, tool="compact_transcript")
    assert text == "error: 'preserve_recent' must be a number"


def test_http_explain_bad_json_answers_a_fixed_message():
    assert _http_tool_text({"report": "{not json"}, tool="explain") == (
        "error: 'report' must be a JSON object")


def test_http_tool_input_errors_keep_their_reason():
    assert _http_tool_text({"text": "", "question": "x"}) == (
        "error: compact requires non-empty 'text'")


def test_stdio_tool_errors_keep_their_text(monkeypatch):
    def broken(_args):
        raise ValueError("/srv/secret/path")

    monkeypatch.setitem(mcp_server.TOOLS["compact"], "handler", broken)
    response = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "compact", "arguments": {}}})
    assert response is not None
    assert response["result"]["content"][0]["text"] == "error: /srv/secret/path"


# -- 4. regex / quadratic denial of service -------------------------------------------------


def test_speech_cleaning_is_linear_on_long_blank_runs():
    from lcc.cleaning.speech import clean_speech_transcript

    started = time.perf_counter()
    clean_speech_transcript("a" + " " * 2_000_000 + "b né? ok")  # was ~5 s per 20 KB
    assert time.perf_counter() - started < 10


def test_near_dedup_is_bounded_on_many_similar_paragraphs():
    import random

    from lcc.cleaning.deduplicate import deduplicate_paragraphs

    rng = random.Random(0)
    paragraphs = ["".join(rng.choice("ab ") for _ in range(45)) for _ in range(40_000)]
    started = time.perf_counter()
    result = deduplicate_paragraphs("\n\n".join(paragraphs))  # ~1.9 MB; was hours
    assert time.perf_counter() - started < 20
    assert result.near_duplicate_budget_exhausted is True
    assert result.metrics.paragraphs_after <= len(paragraphs)


def test_near_dedup_results_unchanged_under_the_budget():
    from lcc.cleaning.deduplicate import deduplicate_paragraphs

    base = "The quarterly report shows revenue grew in every region this year."
    text = "\n\n".join([base, base.replace("grew", "grew,"), "Something entirely different here."])
    result = deduplicate_paragraphs(text)
    assert result.metrics.near_duplicates_removed == 1
    assert result.near_duplicate_budget_exhausted is False


def test_optimize_warns_when_near_dedup_stops_early(monkeypatch):
    from lcc.cleaning import deduplicate
    from lcc.pipeline import OptimizationRequest, optimize

    monkeypatch.setattr(deduplicate, "NEAR_DUP_CHAR_BUDGET", 0)
    text = "\n\n".join(f"paragraph number {n} with enough characters to compare" for n in range(5))
    result = optimize(OptimizationRequest(raw_text=text, question="q"))
    assert any("Near-duplicate detection stopped early" in w for w in result.report.warnings)


# -- 5. untrusted text on a terminal --------------------------------------------------------


def test_explain_escapes_terminal_control_sequences(tmp_path):
    from typer.testing import CliRunner

    from lcc.cli import app

    evil = "\x1b]0;pwned\x07\x1b[2J\x1b[31mDROP TABLE\r\x9b31m"
    report = {"decisions": [{"id": "b1", "decision": "drop", "reason": evil, "line_start": 1,
                             "line_end": 1, "chars": 3}], "warnings": [evil]}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    source = tmp_path / "source.txt"
    source.write_text(evil + "\n")
    result = CliRunner().invoke(app, ["explain", str(path), "--source", str(source)])
    assert result.exit_code == 0, result.output
    assert not any(ch in result.stdout for ch in "\x1b\x07\r\x9b")
    assert "\\x1b]0;pwned" in result.stdout


# -- 6. secrets in local logs ---------------------------------------------------------------


@pytest.mark.parametrize("goal", ["deploy with TYPESAFE_API_KEY=ts_live_1234abcd",
                                  "the client_secret=abc123 leaks",
                                  "Cookie: session=abcdef123456"])
def test_request_log_redacts_prefixed_secrets(goal):
    from lcc.request_log import redact

    out = redact(goal)
    assert "ts_live_1234abcd" not in out and "abc123" not in out and "abcdef123456" not in out


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_jev_ledger_is_private_and_never_stores_the_key(tmp_path):
    import urllib.error

    from lcc.relevance.jev import JevClient, JevRequestError

    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "unauthorized", {},
            io.BytesIO(b'{"error": "bad header Authorization: Bearer sk-secret-123"}'),
        )

    ledger = tmp_path / "logs" / "jev.jsonl"
    client = JevClient("sk-secret-123", ledger_path=ledger, opener=opener, attempts=1)
    with pytest.raises(JevRequestError):
        client.evaluate({"blocks": []}, {"q": {"type": "noul", "question": "?"}})
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o600
    assert "sk-secret-123" not in ledger.read_text()
