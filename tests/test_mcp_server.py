"""MCP stdio server: protocol, tools, and offline guarantees (no key, no net)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lcc.mcp_server import TOOLS, handle_message

ROOT = Path(__file__).resolve().parents[1]

DOSSIER = (
    "The clinic booking widget loses mobile visitors at step two of the funnel.\n\n"
    "LOG: worker heartbeat ok in 554ms, backlog 287 jobs waiting.\n\n"
    "Chatter about office plants and coffee machines needing water daily.\n\n"
)
QUESTION = "reduce mobile booking friction"


def test_tools_registered():
    assert set(TOOLS) == {"compact", "inspect", "prepare", "explain", "intake"}
    for name, spec in TOOLS.items():
        assert spec["description"] and spec["schema"].get("type") == "object", name


def test_initialize_handshake():
    resp = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp is not None and resp["id"] == 1
    assert resp["result"]["capabilities"] == {"tools": {}}
    assert resp["result"]["serverInfo"]["name"] == "lcc"


def test_tools_list_shape():
    resp = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert resp is not None
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["compact", "inspect", "prepare", "explain", "intake"]
    for tool in resp["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_notifications_get_no_response():
    assert handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_tool_is_error_not_crash():
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}}
    )
    assert resp is not None and resp["error"]["code"] == -32602


def test_compact_mechanical_offline():
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "compact",
                    "arguments": {"text": DOSSIER, "question": QUESTION}}}
    )
    assert resp is not None and "error" not in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["report"]["provider_used"] == "mechanical"
    assert payload["report"]["provider_requested"] == "mechanical"
    assert "compacted_text" in payload


def test_compact_rejects_bad_input_as_tool_error():
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "compact", "arguments": {"text": "", "question": QUESTION}}}
    )
    assert resp is not None and resp["result"]["isError"] is True


def test_inspect_and_prepare_offline():
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "inspect", "arguments": {"text": DOSSIER}}}
    )
    assert resp is not None and "error" not in resp
    assert "recommendation" in json.loads(resp["result"]["content"][0]["text"])["report"]

    resp = handle_message(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "prepare",
                    "arguments": {"text": DOSSIER, "question": QUESTION}}}
    )
    assert resp is not None and "error" not in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["action"] in ("skip", "manual_review", "optimize_safe", "optimize_with_flags")


def test_explain_round_trip_offline():
    compact = handle_message(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "compact",
                    "arguments": {"text": DOSSIER, "question": QUESTION}}}
    )
    assert compact is not None
    report = json.loads(compact["result"]["content"][0]["text"])["report"]
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": "explain",
                    "arguments": {"report": report, "source_text": DOSSIER}}}
    )
    assert resp is not None and "error" not in resp
    assert "lcc explain" in json.loads(resp["result"]["content"][0]["text"])["explanation"]


def test_intake_offline():
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
         "params": {"name": "intake", "arguments": {"text": DOSSIER, "question": QUESTION}}}
    )
    assert resp is not None and "error" not in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["readiness"] and payload["formatted_prompt"]


def _frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def test_stdio_end_to_end_offline():
    """Real subprocess, real framing, no key, no network, no Laya weights."""
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)
    proc = subprocess.run(
        [sys.executable, "-m", "lcc.mcp_server"],
        input=_frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + _frame({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + _frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + _frame({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "compact",
                             "arguments": {"text": DOSSIER, "question": QUESTION}}}),
        capture_output=True, timeout=180, cwd=str(ROOT), env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    out = proc.stdout
    responses = []
    while out:
        head, _, rest = out.partition(b"\r\n\r\n")
        assert head.startswith(b"Content-Length:"), head[:60]
        n = int(head.split(b":")[1])
        responses.append(json.loads(rest[:n]))
        out = rest[n:]
    # 1 notification -> no response: 3 responses for 4 messages.
    assert [r["id"] for r in responses] == [1, 2, 3]
    assert responses[0]["result"]["serverInfo"]["name"] == "lcc"
    assert len(responses[1]["result"]["tools"]) == 5
    payload = json.loads(responses[2]["result"]["content"][0]["text"])
    assert payload["report"]["provider_used"] == "mechanical"


@pytest.mark.skipif(os.getenv("TYPESAFE_API_KEY") is None, reason="needs a Jev key")
def test_compact_jev_with_key():
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
         "params": {"name": "compact",
                    "arguments": {"text": DOSSIER, "question": QUESTION,
                                  "provider": "jev"}}}
    )
    assert resp is not None and "error" not in resp
