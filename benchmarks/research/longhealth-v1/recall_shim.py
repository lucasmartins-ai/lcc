"""LongHealth v1: a stdio MCP server exposing exactly one tool, `recall`, over one session's stash.

Adapted from stashed-recall-v1's shim. It wraps `lcc.relevance.transcript_stash.recall` (lcc from PYTHONPATH, the
pin). Every call is logged to $RECALL_LOG (JSONL).

Caps: $RECALL_MAX_CALLS calls per answer (default 8) and $RECALL_MAX_TOKENS tokens per call (default 20000). Longer
text returns its first tokens plus a note to pass `lines`.

The stash is $LCC_STASH_DIR, one directory per session, so a session can only recall its own blobs. Protocol:
newline-delimited JSON-RPC 2.0 (MCP stdio transport).
"""

import json
import os
import sys

TOOL = {
    "name": "recall",
    "description": "Return the exact text of an old tool result that was removed from the context and replaced by a "
                   "marker [removed: N lines, S KB · lcc recall <id>]. Pass the id from the marker.",
    "inputSchema": {"type": "object", "required": ["id"], "properties": {
        "id": {"type": "string", "description": 'the id after "lcc recall" in the marker'},
        "lines": {"type": "string", "description": 'optional 1-based inclusive line range, e.g. "40-120"'}}},
}


def _log(rec):
    path = os.environ.get("RECALL_LOG")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")


def _tokens(text):
    from lcc.token_budget.counters import count_tokens

    return count_tokens(text, "gpt-4.1").value


def _truncate(text, max_tokens):
    if _tokens(text) <= max_tokens:
        return text, False
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if _tokens(text[:mid]) <= max_tokens else (lo, mid - 1)
    return text[:lo], True


def do_recall(args, state):
    from lcc.relevance.transcript_stash import StashError, recall

    max_calls = int(os.environ.get("RECALL_MAX_CALLS", "8"))
    max_tokens = int(os.environ.get("RECALL_MAX_TOKENS", "20000"))
    state["calls"] += 1
    rec = {"n": state["calls"], "id": args.get("id"), "lines": args.get("lines")}
    if state["calls"] > max_calls:
        _log(dict(rec, ok=False, error="cap"))
        return f"recall limit reached ({max_calls} calls per answer); answer with what you have.", True
    sid, lines = args.get("id"), args.get("lines")
    if not isinstance(sid, str) or not (lines is None or isinstance(lines, str)):
        _log(dict(rec, ok=False, error="bad arguments"))
        return 'recall failed: id must be a string and lines a string such as "40-120"', True
    try:
        text = recall(sid.strip(), lines or None, ledger=False)
    except (StashError, TypeError, ValueError) as e:  # a malformed call answers with an error; the server lives on
        _log(dict(rec, ok=False, error=str(e)[:200]))
        return f"recall failed: {e}", True
    text, cut = _truncate(text, max_tokens)
    if cut:
        text += f'\n[recall truncated at {max_tokens} tokens; pass lines="a-b" for the rest]'
    # The emitted text itself is logged (the log stays in the private root): a re-ask replays exactly what was seen.
    _log(dict(rec, ok=True, truncated=cut, chars=len(text), tokens=_tokens(text), text=text))
    return text, False


def handle(msg, state):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "stash", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        p = msg.get("params") or {}
        if p.get("name") != "recall":
            _log({"n": state["calls"], "ok": False, "error": f"unknown tool {p.get('name')}"})
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        text, err = do_recall(p.get("arguments") or {}, state)
        result = {"content": [{"type": "text", "text": text}], "isError": err}
    elif method == "ping":
        result = {}
    elif mid is None:  # notifications (initialized, cancelled, ...)
        return None
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    state = {"calls": 0}
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        out = handle(msg, state)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
