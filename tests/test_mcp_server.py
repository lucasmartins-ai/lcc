"""MCP stdio server: protocol, tools, and offline guarantees (no key, no net)."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lcc.mcp_server import TOOLS, _read_message, handle_message

ROOT = Path(__file__).resolve().parents[1]

DOSSIER = (
    "The clinic booking widget loses mobile visitors at step two of the funnel.\n\n"
    "LOG: worker heartbeat ok in 554ms, backlog 287 jobs waiting.\n\n"
    "Chatter about office plants and coffee machines needing water daily.\n\n"
)
QUESTION = "reduce mobile booking friction"


def test_tools_registered():
    assert set(TOOLS) == {
        "compact",
        "compact_transcript",
        "inspect",
        "prepare",
        "explain",
        "intake",
        "recall",
    }
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
    assert names == [
        "compact",
        "compact_transcript",
        "inspect",
        "prepare",
        "explain",
        "recall",
        "intake",
    ]
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


def test_compact_transcript_offline_keeps_every_call(monkeypatch):
    import lcc.relevance.transcript as transcript_module

    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.setattr(transcript_module, "_resolve_client", lambda *_: None)
    resp = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "compact_transcript",
                "arguments": {
                    "messages": [
                        {"role": "user", "text": "Fix the parser."},
                        {
                            "role": "assistant",
                            "toolUses": [
                                {"tool_use_id": "toolu_1", "tool": "Bash", "input": {"command": "pytest"}}
                            ],
                        },
                        {
                            "role": "user",
                            "toolResults": [{"tool_use_id": "toolu_1", "text": "1 failed"}],
                        },
                    ],
                    "question": "fix the parser",
                    "preserve_recent": 0,
                },
            },
        }
    )
    assert resp is not None and "error" not in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["report"]["mode"] == "tool-calls"
    assert payload["report"]["semantic_guarantee"] == "none"
    assert [message["role"] for message in payload["messages"]] == ["user", "assistant", "user"]
    assert payload["messages"][2]["toolResults"][0]["text"] == "1 failed"


def test_compact_transcript_accepts_the_local_laya_judge(monkeypatch):
    """Laya is a valid judge here: local, offline, and it answers the same question.

    Driven through the library API with an injected client, so the wiring is proven
    without downloading a checkpoint or any weights.
    """
    from lcc.relevance.transcript import TranscriptCompactionRequest, compact_transcript

    class FakeLaya:
        """Answers the two questions ``_questions`` asks, in the shape Laya returns."""

        last_resolved_model = "fake/laya-typed-decisions"

        def evaluate(self, state, questions):
            answers = {}
            for key, definition in questions.items():
                assert definition["type"] == "noul", key
                # toolu_2 is the call this fixture says is spent, so the fake judge
                # keys off the question id rather than parsing prose.
                spent = key.endswith("toolu_2")
                answers[key] = {
                    "type": "noul",
                    "noul": 0.05 if spent else 0.95,
                    "confidence": 0.9,
                }
            return {"model": "fake/laya", "answers": answers, "latency_ms": 1}

    messages = [
        {"role": "user", "text": "Fix the parser."},
        {
            "role": "assistant",
            "toolUses": [
                {"tool_use_id": "toolu_1", "tool": "Read", "input": {"path": "parser.py"}}
            ],
        },
        {
            "role": "user",
            "toolResults": [{"tool_use_id": "toolu_1", "text": "def parse(): ..."}],
        },
        {
            "role": "assistant",
            "toolUses": [
                {"tool_use_id": "toolu_2", "tool": "Bash", "input": {"command": "sleep 5"}}
            ],
        },
        {"role": "user", "toolResults": [{"tool_use_id": "toolu_2", "text": "done"}]},
    ]

    result = compact_transcript(
        TranscriptCompactionRequest(
            payload=messages,
            question="fix the parser",
            provider="laya",
            preserve_recent=0,
            min_reduction=0.0,
            client=FakeLaya(),
        )
    )

    # The report must name Laya, not Jev, everywhere a judge is recorded.
    assert result.report["provider_requested"] == "laya"
    assert result.report["provider_used"] == "laya"
    assert result.report["semantic_guarantee"] == "judged"
    assert not [w for w in result.report["warnings"] if w.startswith("jev_")]

    decisions = {d["id"]: d for d in result.decisions}
    assert decisions["toolu_1"]["decision"] == "keep"
    assert decisions["toolu_2"]["decision"] == "drop"
    assert all(d["source"] == "laya" for d in result.decisions)


def test_compact_transcript_rejects_mechanical_before_any_work():
    """mechanical cannot answer the question, so it must fail before scoring."""
    from lcc.relevance.transcript import (
        TranscriptCompactionRequest,
        UnsupportedTranscriptProviderError,
        compact_transcript,
    )

    with pytest.raises(UnsupportedTranscriptProviderError):
        compact_transcript(
            TranscriptCompactionRequest(
                payload=[{"role": "user", "text": "hi"}],
                question="q",
                provider="mechanical",
            )
        )


def test_compact_transcript_refuses_a_non_semantic_provider():
    resp = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "compact_transcript",
                "arguments": {
                    "messages": [{"role": "user", "text": "hi"}],
                    "question": "q",
                    "provider": "mechanical",
                },
            },
        }
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
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
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
    assert len(responses[1]["result"]["tools"]) == 7
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


def test_stdio_newline_delimited_json():
    """MCP stdio spec framing (Claude Code, Codex): one JSON object per line."""
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "lcc.mcp_server"],
        input=b"".join(json.dumps(m).encode() + b"\n" for m in lines),
        capture_output=True, timeout=60, cwd=str(ROOT), env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [r["id"] for r in responses] == [1, 2]
    assert responses[0]["result"]["serverInfo"]["name"] == "lcc"
    assert any(t["name"] == "compact_transcript" for t in responses[1]["result"]["tools"])


def test_stdio_survives_malformed_messages():
    """A bad line gets a JSON-RPC error and the server keeps serving.

    Regression: a parse error ended the read loop, a JSON array crashed the error
    handler (``list.get``) and non-object ``arguments`` raised AttributeError.
    """
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    lines = [
        b"{not json",
        b"[1, 2]",
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "compact", "arguments": ["x"]}}).encode(),
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": "x"}).encode(),
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": {}}).encode(),
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "lcc.mcp_server"],
        input=b"\n".join(lines) + b"\n",
        capture_output=True, timeout=60, cwd=str(ROOT), env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [(r["id"], r.get("error", {}).get("code")) for r in responses] == [
        (None, -32700), (None, -32600), (3, -32602), (4, -32602), (5, None),
    ]


def test_stdio_answers_a_line_that_is_neither_json_nor_a_header():
    """A stray line is a parse error, not the start of LSP headers, and ``ping`` is answered.

    Regression: any line not starting with ``{`` or ``[`` (a BOM, a bare ``null``, a wrapper's
    log line) was read as a header. Newline-delimited clients send no blank line to end the
    headers, so every later request was swallowed while the process stayed up.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    lines = [
        b"\xef\xbb\xbf" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
        b"null",
        b"INFO: wrapper starting",
        json.dumps({"jsonrpc": "2.0", "method": "ping"}).encode(),  # a notification: no reply
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}).encode(),
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "lcc.mcp_server"],
        input=b"\n".join(lines) + b"\n",
        capture_output=True, timeout=60, cwd=str(ROOT), env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert responses == [
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}},
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}},
        {"jsonrpc": "2.0", "id": 2, "result": {}},
    ]


def test_a_null_body_in_lsp_framing_is_a_parse_error_not_eof():
    with pytest.raises(ValueError):
        _read_message(io.BytesIO(b"Content-Length: 4\r\n\r\nnull"))


def test_compact_transcript_runs_the_offline_rules_policy():
    resp = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "compact_transcript",
                "arguments": {
                    "messages": [
                        {"role": "user", "text": "fix it"},
                        {"role": "assistant", "text": "", "toolUses": [
                            {"tool_use_id": "a", "tool": "Read", "input": {"file_path": "x.py"}}]},
                        {"role": "user", "text": "", "toolResults": [
                            {"tool_use_id": "a", "text": "old body"}]},
                        {"role": "assistant", "text": "", "toolUses": [
                            {"tool_use_id": "b", "tool": "Read", "input": {"file_path": "x.py"}}]},
                        {"role": "user", "text": "", "toolResults": [
                            {"tool_use_id": "b", "text": "new body"}]},
                    ],
                    "question": "fix it",
                    "provider": "rules",
                    "rules_mode": "lossy",
                    "preserve_recent": 2,
                },
            },
        }
    )
    assert resp is not None and resp["result"].get("isError") is not True
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["report"]["provider_used"] == "rules"
    decisions = {d["id"]: d for d in payload["decisions"]}
    assert decisions["a"]["decision"] == "drop"
    assert decisions["a"]["reason"] == "superseded_by_later_call:b"


def test_compact_transcript_accepts_rules_mode_recoverable_with_a_workspace(
    tmp_path, monkeypatch
):
    import re

    import lcc.relevance.transcript_recoverable as recoverable

    monkeypatch.setattr(recoverable, "_TEMP", re.compile(r"(?!)"))  # tmp_path is a temp dir
    body = "\n".join(f"line {n}" for n in range(1, 60)) + "\n"
    (tmp_path / "x.py").write_text(body)
    numbered = "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(body.splitlines(), 1))
    resp = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "compact_transcript",
                "arguments": {
                    "messages": [
                        {"role": "user", "text": "fix it"},
                        {"role": "assistant", "text": "", "toolUses": [
                            {"tool_use_id": "a", "tool": "Read", "input": {"file_path": str(tmp_path / "x.py")}}]},
                        {"role": "user", "text": "", "toolResults": [
                            {"tool_use_id": "a", "text": numbered}]},
                        {"role": "assistant", "text": "", "toolUses": [
                            {"tool_use_id": "b", "tool": "Grep", "input": {"pattern": "x"}}]},
                        {"role": "user", "text": "", "toolResults": [
                            {"tool_use_id": "b", "text": "1 passed"}]},
                        {"role": "assistant", "text": "done"},
                    ],
                    "question": "fix it",
                    "provider": "rules",
                    "rules_mode": "recoverable",
                    "workspace_root": str(tmp_path),
                    "preserve_recent": 1,
                },
            },
        }
    )
    assert resp is not None and resp["result"].get("isError") is not True
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["report"]["recoverability_check"] == "disk"
    decisions = {d["id"]: d for d in payload["decisions"]}
    assert decisions["a"]["decision"] == "replace"
    assert decisions["a"]["reason"] == "replace_disk_verified"
    assert decisions["a"]["note"] == (
        f"[removed: re-read {tmp_path / 'x.py'} to recover; "
        "content verified on disk at compaction time]"
    )



def test_compact_transcript_ref_unchanged_is_the_same_answer_smaller():
    body = "def parse(x):\n    return x\n" * 200
    messages = [
        {"role": "user", "text": "fix the parser"},
        {"role": "assistant", "text": "", "toolUses": [
            {"tool_use_id": "t1", "tool": "Read", "input": {"file_path": "p.py"}}]},
        {"role": "user", "text": "", "toolResults": [{"tool_use_id": "t1", "text": body}]},
        {"role": "assistant", "text": "done"},
    ]

    def call(**extra):
        resp = handle_message(
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
             "params": {"name": "compact_transcript",
                        "arguments": {"messages": messages, "question": "fix the parser",
                                      "provider": "rules", "rules_mode": "lossless", **extra}}}
        )
        assert resp is not None and "error" not in resp
        return json.loads(resp["result"]["content"][0]["text"])

    full = call()
    compact = call(ref_unchanged=True)
    assert "decisions" not in compact and "decisions" not in compact["report"]
    assert compact["report"]["tokens_before"] == full["report"]["tokens_before"]
    expanded = [messages[m["ref"]] if "ref" in m else m for m in compact["messages"]]
    assert expanded == full["messages"]
    assert len(json.dumps(compact)) < len(json.dumps(full)) / 2


def test_ref_unchanged_sends_changed_and_dropped_messages_whole():
    from lcc.mcp_server import _ref_unchanged

    a, b, c, d = ({"role": "user", "text": t} for t in "abcd")
    changed = {"role": "user", "text": "[removed: 9 tokens]"}
    assert _ref_unchanged([a, b, c, d], [a, changed, d]) == [{"ref": 0}, changed, {"ref": 3}]
    # Equal messages map in order, never backwards.
    assert _ref_unchanged([a, a, b], [a, a, b]) == [{"ref": 0}, {"ref": 1}, {"ref": 2}]
    assert _ref_unchanged([a, b], [b, a]) == [{"ref": 1}, a]


def _expand_blocks(answer: list[dict], source: list[dict]) -> list[dict]:
    """The hook's expandRefs, in Python: UTF-16 offsets, as JavaScript's ``slice`` counts."""

    def splice(text: str, block: dict) -> str:
        units = text.encode("utf-16-le")
        head, tail = block.get("head", 0) * 2, block.get("tail", 0) * 2
        end = units[len(units) - tail :] if tail else b""
        return units[:head].decode("utf-16-le") + block["text"] + end.decode("utf-16-le")

    out = []
    for message in answer:
        if "ref" not in message:
            out.append(message)
            continue
        original = source[message["ref"]]
        if "toolUses" not in message and "toolResults" not in message:
            out.append(original)
            continue
        entry = {"role": original["role"], "text": original["text"]}
        if message["toolUses"]:
            entry["toolUses"] = [original["toolUses"][i] for i in message["toolUses"]]
        results = [
            original["toolResults"][block] if isinstance(block, int)
            else {"tool_use_id": block["tool_use_id"],
                  "text": splice(original["toolResults"][block["ref"]]["text"], block)}
            for block in message["toolResults"]
        ]
        if results:
            entry["toolResults"] = results
        out.append(entry)
    return out


def _ci_transcript(runs: int = 40) -> list[dict]:
    """A long session: ``runs`` large command outputs, two of them per message (parallel calls)."""
    messages: list[dict] = [{"role": "user", "text": "Summarise the build failures in the CI logs."}]
    for i in range(0, runs, 2):
        ids = (f"t{i}", f"t{i + 1}")
        messages.append({"role": "assistant", "text": "", "toolUses": [
            {"tool_use_id": t, "tool": "Bash", "input": {"command": f"cat logs/{t}.txt"}}
            for t in ids]})
        messages.append({"role": "user", "text": "", "toolResults": [
            {"tool_use_id": t, "text": f"{t} step ok ✓ \U0001f600\n" * 1200} for t in ids]})
    messages.append({"role": "assistant", "text": "Looked at all runs."})
    messages.append({"role": "user", "text": "Now list which runs failed."})
    return messages


@pytest.mark.parametrize("rules_mode", ["lossy", "stashed"])
def test_ref_blocks_answer_stays_small_and_expands_to_the_full_answer(
    rules_mode, tmp_path, monkeypatch
):
    # Regression: Claude Code caps an MCP result (MAX_MCP_OUTPUT_TOKENS, 25,000 tokens by
    # default) and hands a plugin's $.mcp.call a pointer text instead, so /compact on a long
    # session always fell back to the built-in summary. The answer must not grow with it.
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path))
    messages = _ci_transcript()

    def call(**extra):
        resp = handle_message(
            {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
             "params": {"name": "compact_transcript",
                        "arguments": {"messages": messages, "question": "which runs failed",
                                      "provider": "rules", "rules_mode": rules_mode,
                                      **extra}}}
        )
        assert resp is not None and "error" not in resp
        return resp["result"]["content"][0]["text"]

    full = json.loads(call())
    text = call(ref_unchanged=True, ref_blocks=True)
    assert len(json.dumps(messages)) > 1_000_000
    assert len(text) < 20_000, len(text)  # far under 25,000 tokens, whatever the tokenizer
    answer = json.loads(text)
    removed = sum(answer["report"][f"tool_calls_{k}"] for k in ("trimmed", "replaced", "dropped"))
    assert removed > 0
    assert _expand_blocks(answer["messages"], messages) == full["messages"]


def test_ref_blocks_expands_identically_in_the_hook(tmp_path):
    # The same answer through the plugin's own expandRefs (node), byte for byte.
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    messages = _ci_transcript()
    resp = handle_message(
        {"jsonrpc": "2.0", "id": 13, "method": "tools/call",
         "params": {"name": "compact_transcript",
                    "arguments": {"messages": messages, "question": "which runs failed",
                                  "provider": "rules", "rules_mode": "lossy",
                                  "ref_blocks": True}}}
    )
    assert resp is not None
    answer = json.loads(resp["result"]["content"][0]["text"])
    assert answer["report"]["tool_calls_trimmed"] > 0
    (tmp_path / "in.json").write_text(json.dumps({"answer": answer["messages"], "source": messages}))
    hook = Path(__file__).resolve().parents[1] / "plugins/claude-code/hooks/map.mjs"
    script = (
        f"import {{ expandRefs }} from {json.dumps(hook.as_uri())};"
        "import { readFileSync } from 'node:fs';"
        "const { answer, source } = JSON.parse(readFileSync(process.argv[1], 'utf8'));"
        "process.stdout.write(JSON.stringify(expandRefs(answer, source)));"
    )
    out = subprocess.run(
        [node, "--input-type=module", "-e", script, str(tmp_path / "in.json")],
        capture_output=True, text=True, check=True,
    )
    expected = _expand_blocks(answer["messages"], messages)
    got = json.loads(out.stdout)
    # The hook rebuilds every changed message with an explicit (possibly empty) toolUses list.
    for message in got:
        if message.get("toolUses") == []:
            del message["toolUses"]
    assert got == expected


def test_ref_blocks_patches_only_what_changed():
    from lcc.mcp_server import _ref_blocks, _splice

    use = {"tool_use_id": "a", "tool": "Read", "input": {}}
    other = {"tool_use_id": "b", "tool": "Grep", "input": {}}
    source = [
        {"role": "assistant", "text": "x", "toolUses": [use, other]},
        {"role": "user", "text": "", "toolResults": [
            {"tool_use_id": "a", "text": "keep"}, {"tool_use_id": "b", "text": "abcdef"}]},
    ]
    compacted = [
        {"role": "assistant", "text": "x", "toolUses": [other]},
        {"role": "user", "text": "", "toolResults": [
            {"tool_use_id": "a", "text": "keep"}, {"tool_use_id": "b", "text": "ab[cut]"}]},
    ]
    assert _ref_blocks(source, compacted, [0, 1]) == [
        {"ref": 0, "toolUses": [1], "toolResults": []},
        {"ref": 1, "toolUses": [], "toolResults": [
            0, {"ref": 1, "tool_use_id": "b", "head": 2, "text": "[cut]"}]},
    ]
    # A message whose text changed is sent whole; head/tail count UTF-16 units.
    assert _ref_blocks(source, [{"role": "assistant", "text": "y"}], [0]) == [
        {"role": "assistant", "text": "y"}]
    assert _splice("\U0001f600ab", "\U0001f600a!") == {"text": "!", "head": 3}
