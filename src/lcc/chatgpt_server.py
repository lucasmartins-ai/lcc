"""Streamable-HTTP MCP transport for ChatGPT / Codex plugin submission.

ChatGPT connects to a plugin's MCP server over remote HTTPS (streamable HTTP), not
the stdio transport used by local agents. This module reuses the exact same tool
handlers and JSON-RPC dispatch as :mod:`lcc.mcp_server` — the deterministic core is
untouched, this only changes the transport.

Why this exists
---------------
``lcc`` already exposes six tools over MCP stdio (``compact``, ``compact_transcript``,
``inspect``, ``prepare``, ``explain``, ``intake``). To get in front of ChatGPT's
recommended-plugins surface the same capabilities need one thing the stdio server
cannot do: answer an HTTP POST on a public URL. Everything else the plugin needs
(deployment, store metadata) lives outside this module.

Transport shape (``streamable-http``, per the Apps SDK deployment requirements):

- ``POST /mcp`` with a JSON-RPC 2.0 body; respond with ``text/event-stream`` so the
  client receives results as a single SSE ``message`` event.
- ``GET /mcp`` returns ``405 Method Not Allowed`` — this server holds no
  server-initiated stream, so a client GET must not look like a hanging request.
- ``DELETE /mcp`` reports no session to terminate.
- Protocol header: ``mcp-protocol-version`` (2025-06-18 for streamable HTTP).

Standard library only, like every other module in ``lcc``: no new dependency is
added to the installed base package.

Run: ``lcc mcp --http --host 0.0.0.0 --port 8080``.

Deploy note: the submission portal requires a publicly reachable HTTPS origin and
domain verification (``/.well-known/openai-apps-challenge``). Terminate TLS in front
of this server (a TLS-terminating proxy such as Cloudflare, Fly.io, or Render) and
do not expose it as plain HTTP.
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from lcc import __version__
from lcc.mcp_server import handle_message

LOGGER = logging.getLogger("lcc.chatgpt")

# Streamable HTTP negotiates a newer revision than the stdio server advertises.
HTTP_PROTOCOL_VERSION = "2025-06-18"

__all__ = [
    "HTTP_PROTOCOL_VERSION",
    "build_server",
    "main",
    "resolve_port",
    "serve_forever",
]

# Requests larger than this are refused rather than buffered; the hosted use case is
# a pasted document or transcript, not multi-megabyte uploads. Raising it means a
# larger Content-Length body is read into memory before any handler runs.
MAX_BODY_BYTES = 32 * 1024 * 1024

# Where the OpenAI submission portal looks for domain-ownership proof. It must be on
# the MCP hostname or an eligible parent domain, and must return the exact token as
# plain text.
CHALLENGE_PATH = "/.well-known/openai-apps-challenge"


def resolve_port(flag_value: str) -> int | None:
    """Interpret ``--port``: a number, ``$PORT``, or unset.

    Hosting platforms write start commands like ``lcc mcp --http --port $PORT`` but do
    not run them through a shell, so the program receives the literal text ``$PORT``.
    Typer would reject that as a non-integer before any server code ran, which is
    exactly how the first Railway deploy died. Treating the unexpanded form as "read
    the environment" fixes it for every platform, not just one.

    Returns ``None`` when the caller should let ``$PORT``/8080 decide.
    """
    value = (flag_value or "").strip()
    if not value or value in ("$PORT", "${PORT}", "$PORT_NUMBER"):
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"invalid --port {value!r}: expected a number or $PORT") from exc


def _tool_annotations() -> dict[str, dict[str, bool]]:
    """Per-tool ``readOnlyHint``/``destructiveHint``/``openWorldHint`` for review.

    The submission portal requires explicit booleans on every tool. All six tools are
    read-only: they compute or inspect text the caller supplied and return it in the
    response, never mutating user state or the filesystem.

    ``openWorldHint`` is ``True`` only for the two providers that call a third-party
    judge service over the network (``jev`` via TypeSafe, ``nimble`` via a local
    Nimble checkout). The default ``mechanical`` path, and ``laya``, are fully local,
    so the capability is not declared open-world — the flag describes the tool's
    reachable scope, not whether a non-default argument can widen it.
    """
    return {
        "compact": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
        "compact_transcript": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
        "inspect": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "prepare": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "explain": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "intake": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    }


def _tools_list() -> list[dict[str, Any]]:
    """``tools/list`` payload with review annotations attached.

    Built from :data:`lcc.mcp_server.TOOLS` so the two transports can never drift:
    adding a tool to the stdio server registers it here too.
    """
    from lcc.mcp_server import TOOLS

    annotations = _tool_annotations()
    tools = []
    for name, spec in TOOLS.items():
        tool: dict[str, Any] = {
            "name": name,
            "description": spec["description"],
            "inputSchema": spec["schema"],
        }
        tool_annotations = annotations.get(name)
        if tool_annotations:
            tool["annotations"] = dict(tool_annotations)
        tools.append(tool)
    return tools


def _handle(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """Dispatch one JSON-RPC message through the shared stdio handler.

    Returns ``(response, wants_accepted)`` where ``wants_accepted`` is True for a
    notification (no response body exists, only ``202 Accepted``).
    """
    is_notification = "id" not in payload
    response = handle_message(payload)
    # Streamable HTTP negotiates a newer revision than the stdio server reports;
    # answering with the stdio version would make a conforming client negotiate down.
    if response is not None and payload.get("method") == "initialize":
        result = response.get("result")
        if isinstance(result, dict):
            result["protocolVersion"] = HTTP_PROTOCOL_VERSION
    if is_notification and response is not None:
        # A notification must never receive a body; handle_message already returns
        # None for those, so reaching here means the message was malformed.
        LOGGER.warning("suppressing body for notification: %s", payload.get("method"))
    return response, is_notification


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


class _Handler(BaseHTTPRequestHandler):
    """One request handler wired to a :class:`ThreadingHTTPServer`."""

    protocol_version = "HTTP/1.1"  # keep-alive; the body length is always explicit
    server_version = f"lcc/{__version__}"
    sys_version = ""

    # -- plumbing ----------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib name
        """Route access logs to logging instead of stderr noise."""
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _send_sse(self, response: dict[str, Any]) -> None:
        """Return a JSON-RPC result as a single SSE ``message`` event."""
        body = (
            f"event: message\ndata: {json.dumps(response)}\n\n".encode()
        )
        self._send(200, body, "text/event-stream")

    def _read_body(self) -> bytes | None:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return b""
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json(400, _error_response(None, -32700, "invalid Content-Length"))
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json(
                413,
                _error_response(None, -32600, f"body exceeds {MAX_BODY_BYTES} bytes"),
            )
            return None
        return self.rfile.read(length)

    # -- verbs -------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path not in ("/", "/mcp"):
            self._send_json(404, _error_response(None, -32601, f"no endpoint {path}"))
            return

        raw = self._read_body()
        if raw is None:
            return

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, _error_response(None, -32700, f"invalid JSON: {exc}"))
            return

        # JSON-RPC batch: a list of messages. Respond with a list of responses.
        if isinstance(payload, list):
            if not payload:
                self._send_json(400, _error_response(None, -32600, "empty batch"))
                return
            responses = [
                response
                for response, _ in (_handle(item) for item in payload if isinstance(item, dict))
                if response is not None
            ]
            self._send(200, json.dumps(responses).encode(), "text/event-stream")
            return

        if not isinstance(payload, dict):
            self._send_json(400, _error_response(None, -32600, "expected a JSON-RPC object"))
            return

        method = payload.get("method", "")
        # tools/list needs annotations; everything else reuses the shared handler.
        if method == "tools/list":
            self._send_sse(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {"tools": _tools_list()},
                }
            )
            return

        response, is_notification = _handle(payload)
        if response is None or is_notification:
            self._send(202, b"", "text/plain")
            return
        self._send_sse(response)

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            # Liveness only: no tool call, no input, nothing stored. Platforms that
            # probe a fixed path for a 2xx (Railway, Fly, Cloud Run) would otherwise
            # read the 405 below as "unhealthy" and restart the container.
            self._send(200, b'{"status":"ok"}', "application/json")
            return
        if path == "/robots.txt":
            # The plugin directory's scanner fetches this before probing /mcp. A 404
            # here reads as a broken host, so allow everything explicitly instead.
            self._send(200, b"User-agent: *\nAllow: /\n", "text/plain; charset=utf-8")
            return
        if path == "/favicon.ico":
            # Same reason as robots.txt: scanners probe it and 404 reads as broken.
            # 204 says "nothing here" without claiming an asset exists.
            self._send(204, b"", "image/x-icon")
            return
        if path == CHALLENGE_PATH:
            # OpenAI plugin domain verification. The portal requires the exact token as
            # plain text — not JSON, not a list. Absent an env var there is nothing
            # legitimate to return, so 404 rather than a placeholder that would fail
            # review in a confusing way.
            token = os.environ.get("OPENAI_CHALLENGE_TOKEN", "").strip()
            if not token:
                self._send_json(
                    404, _error_response(None, -32601, "challenge token not configured")
                )
                return
            self._send(200, token.encode("utf-8"), "text/plain; charset=utf-8")
            return
        if path not in ("/", "/mcp"):
            self._send_json(404, _error_response(None, -32601, f"no endpoint {path}"))
            return
        # No server-initiated stream exists, so a GET is answered rather than hung.
        self._send_json(
            405,
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32601,
                    "message": "streamable-http: GET opens a server-initiated stream, "
                    "which this server does not provide. Use POST.",
                },
            },
        )

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib name
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path not in ("/", "/mcp"):
            self._send_json(404, _error_response(None, -32601, f"no endpoint {path}"))
            return
        self._send(200, b"", "text/plain")

    def do_PUT(self) -> None:  # noqa: N802 - stdlib name
        self._send_json(
            405,
            _error_response(None, -32601, "streamable-http uses POST /mcp"),
        )


def build_server(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    """Build (but do not run) the HTTP server. Extracted so tests can use port 0."""
    return ThreadingHTTPServer((host, port), _Handler)


def serve_forever(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Serve until interrupted. Raises ``OSError`` if the port is already bound."""
    server = build_server(host, port)
    LOGGER.info("lcc MCP streamable-http on http://%s:%s/mcp", host, server.server_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    """Entry point for ``lcc mcp --http``: parse flags and serve.

    ``PORT`` is honoured so platforms that inject a random port (Railway, Fly,
    Cloud Run) work without a matching CLI flag; an explicit ``--port`` still wins.
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(prog="lcc mcp --http", add_help=True)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        default=os.environ.get("PORT", ""),
        help="Port to bind. Accepts a number, or the literal $PORT.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"lcc {__version__}",
    )
    args = parser.parse_args()
    # Unset or unexpanded -> fall back to $PORT, then 8080.
    port = resolve_port(args.port)
    if port is None:
        port = int(os.environ.get("PORT") or 8080)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    serve_forever(args.host, port)


if __name__ == "__main__":
    main()
