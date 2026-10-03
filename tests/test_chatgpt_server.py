"""ChatGPT streamable-HTTP transport: real HTTP round-trips against a live server.

These are the checks that matter for plugin review: every one of the six tools is
reachable over POST /mcp, each declares the three required annotation booleans, and
the verbs that must not hang (GET, DELETE) answer instead of blocking.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from lcc.chatgpt_server import CHALLENGE_PATH, HTTP_PROTOCOL_VERSION, build_server

DOSSIER = (
    "The clinic booking widget loses mobile visitors at step two of the funnel.\n\n"
    "LOG: worker heartbeat ok in 554ms, backlog 287 jobs waiting.\n\n"
    "Chatter about office plants and coffee machines needing water daily.\n\n"
)
QUESTION = "reduce mobile booking friction"


@pytest.fixture
def mcp_url():
    """Start the real server on an ephemeral port; yield its /mcp URL."""
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(url: str, payload: object, timeout: float = 20.0) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # 4xx/5xx carry a JSON-RPC error body
        return exc.code, exc.read().decode("utf-8")


def _sse_payload(body: str) -> dict:
    """Extract the JSON-RPC message from a single-event SSE frame."""
    data_lines = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
    assert data_lines, f"no SSE data line in {body!r}"
    return json.loads(data_lines[0])


def test_initialize_over_http(mcp_url):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
    request = urllib.request.Request(
        mcp_url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "text/event-stream"
        raw = response.read().decode("utf-8")
    result = _sse_payload(raw)["result"]
    assert result["serverInfo"]["name"] == "lcc"
    # Streamable HTTP negotiates a newer revision than the stdio server advertises.
    assert result["protocolVersion"] == HTTP_PROTOCOL_VERSION


def test_stdio_protocol_version_is_untouched():
    """The HTTP override must not leak into the stdio handshake."""
    from lcc.mcp_server import PROTOCOL_VERSION

    assert PROTOCOL_VERSION != HTTP_PROTOCOL_VERSION


def test_cli_does_not_forward_a_literal_port(monkeypatch):
    """Regression: `lcc mcp --http --port $PORT` crashed on Railway.

    PaaS start commands are not shell-expanded, so the program receives the literal
    text "$PORT". It must resolve from the environment instead of failing validation.
    """
    from typer.testing import CliRunner

    from lcc.cli import app

    seen: list[str] = []

    def fake_main() -> None:
        import sys

        seen[:] = sys.argv

    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr("lcc.chatgpt_server.main", fake_main)
    result = CliRunner().invoke(app, ["mcp", "--http"])

    assert result.exit_code == 0, result.output
    assert "--port" not in seen, seen
    assert "$PORT" not in seen, seen


def test_cli_accepts_an_unexpanded_port_variable(monkeypatch):
    """The literal '$PORT' must be treated as 'read the environment', not a crash."""
    from typer.testing import CliRunner

    from lcc.cli import app

    seen: list[str] = []

    def fake_main() -> None:
        import sys

        seen[:] = sys.argv

    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setattr("lcc.chatgpt_server.main", fake_main)
    result = CliRunner().invoke(app, ["mcp", "--http", "--port", "$PORT"])

    assert result.exit_code == 0, result.output
    assert "$PORT" not in seen, seen


def test_resolve_port_handles_the_platform_forms():
    from lcc.chatgpt_server import resolve_port

    assert resolve_port("") is None
    assert resolve_port("$PORT") is None
    assert resolve_port("${PORT}") is None
    assert resolve_port("9123") == 9123
    with pytest.raises(ValueError):
        resolve_port("not-a-port")


def test_cli_forwards_an_explicit_port(monkeypatch):
    """An explicit --port still wins over $PORT."""
    from typer.testing import CliRunner

    from lcc.cli import app

    seen: list[str] = []

    def fake_main() -> None:
        import sys

        seen[:] = sys.argv

    monkeypatch.setattr("lcc.chatgpt_server.main", fake_main)
    result = CliRunner().invoke(app, ["mcp", "--http", "--port", "9123"])

    assert result.exit_code == 0, result.output
    assert "9123" in seen


def test_tools_list_has_all_six_tools_with_review_annotations(mcp_url):
    status, body = _post(mcp_url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert status == 200
    tools = _sse_payload(body)["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "compact",
        "compact_transcript",
        "inspect",
        "prepare",
        "explain",
        "intake",
    }
    for tool in tools:
        annotations = tool["annotations"]
        assert set(annotations) == {
            "readOnlyHint",
            "destructiveHint",
            "openWorldHint",
        }, tool["name"]
        for key, value in annotations.items():
            assert isinstance(value, bool), f"{tool['name']}.{key} must be a real bool"
        assert annotations["destructiveHint"] is False, tool["name"]


def test_compact_runs_offline_over_http(mcp_url):
    """The default mechanical provider must need no key and no network."""
    status, body = _post(
        mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "compact",
                "arguments": {"text": DOSSIER, "question": QUESTION},
            },
        },
    )
    assert status == 200
    content = _sse_payload(body)["result"]["content"]
    assert content[0]["type"] == "text"
    payload = json.loads(content[0]["text"])
    assert payload["report"]["provider_used"] == "mechanical"
    assert payload["compacted_text"]


def test_bad_tool_call_reports_iserror(mcp_url):
    status, body = _post(
        mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "compact", "arguments": {"text": "", "question": ""}},
        },
    )
    assert status == 200
    assert _sse_payload(body)["result"]["isError"] is True


def test_challenge_endpoint_returns_the_exact_token_as_plain_text(mcp_url, monkeypatch):
    """The portal requires the exact token, not JSON or a list."""
    monkeypatch.setenv("OPENAI_CHALLENGE_TOKEN", "tok-abc123")

    request = urllib.request.Request(mcp_url.replace("/mcp", CHALLENGE_PATH), method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        body = response.read().decode("utf-8")
    # Exactly the token: no JSON object, no quotes, no list.
    assert body == "tok-abc123"
    assert not body.strip().startswith(("{", "["))


def test_challenge_endpoint_is_404_without_a_token(mcp_url, monkeypatch):
    """No configured token must not answer with a placeholder that fails review."""
    monkeypatch.delenv("OPENAI_CHALLENGE_TOKEN", raising=False)
    request = urllib.request.Request(mcp_url.replace("/mcp", CHALLENGE_PATH), method="GET")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=10)
    assert excinfo.value.code == 404


def test_robots_and_favicon_do_not_404(mcp_url):
    """Scanners fetch these before probing /mcp; a 404 reads as a broken host."""
    for path, expected in (("/robots.txt", 200), ("/favicon.ico", 204)):
        request = urllib.request.Request(mcp_url.replace("/mcp", path), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == expected, path
        except urllib.error.HTTPError as exc:
            assert exc.code == expected, f"{path}: got {exc.code}"


def test_get_is_answered_not_hung(mcp_url):
    request = urllib.request.Request(mcp_url, method="GET")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=10)
    assert excinfo.value.code == 405


def test_notification_returns_202_with_no_body(mcp_url):
    status, body = _post(mcp_url, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert status == 202
    assert body == ""


def test_unknown_path_is_404(mcp_url):
    bad = mcp_url.replace("/mcp", "/nope")
    status, _ = _post(bad, {"jsonrpc": "2.0", "id": 5, "method": "initialize"})
    assert status == 404


def test_malformed_json_is_400(mcp_url):
    request = urllib.request.Request(
        mcp_url,
        data=b"{not json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=10)
    assert excinfo.value.code == 400
