"""Head-to-head: `lcc compact --mode tool-calls` vs `fast-jev-compaction` (npm).

Both arms run the **real** TypeSafe Jev backend over the same deterministic transcripts
(`make_transcripts.py`), with matching defaults: keep threshold 0.5, six pinned recent
messages, 300-char trimmed head, 25k state tokens, 30k request tokens. A `none` arm is the
identity baseline.

What is measured per session and arm:

- characters and **exact** tokens before/after (the token counter is LCC's, so both arms are
  counted with the same ruler), and the reduction ratio;
- required-fact recall over the emitted transcript (facts worded away from the objective, so
  only a judge that reads the session can keep them);
- per-pair outcomes derived from the emitted messages — never from either tool's own
  bookkeeping — so the two arms are scored by the same rule:
  ``dropped`` / ``trimmed`` / ``kept`` for each call kind (evidence, spent, noise, pinned);
- latency, request count, and (for the lcc arm) the input/output tokens the TypeSafe ledger
  recorded while the run was in flight.

Usage:

    python3 benchmarks/research/run_transcript_ab.py            # real backends (needs a key)
    python3 benchmarks/research/run_transcript_ab.py --arm lcc  # one arm only

The npm package is installed once into ``work_transcript_ab/`` (gitignored); the arm script is
copied next to it so Node resolves the dependency.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

CORPUS_DIR = HERE / "corpora" / "transcripts"
RESULTS_DIR = HERE / "results"
WORK_DIR = HERE / "work_transcript_ab"
NPM_PACKAGE = "fast-jev-compaction"

DEFAULT_OPTIONS = {
    "threshold": 0.5,
    "preserve_recent": 6,
    "trim_head_chars": 300,
    "max_state_tokens": 25000,
    "max_request_tokens": 30000,
    "jev_model": "jev-latest",
}


def _normalise(text: str) -> str:
    return " ".join(text.split())


def flatten(messages: list[dict[str, Any]]) -> str:
    """The transcript as text: the same rendering for token counts and fact recall."""
    parts: list[str] = []
    for message in messages:
        parts.append(str(message.get("text") or ""))
        for call in message.get("toolUses") or []:
            parts.append(f"{call.get('tool_use_id')} {call.get('tool')} {json.dumps(call.get('input'), sort_keys=True)}")
        for result in message.get("toolResults") or []:
            parts.append(str(result.get("text") or ""))
    return "\n".join(parts)


def results_by_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    found: dict[str, str] = {}
    for message in messages:
        for result in message.get("toolResults") or []:
            found[str(result.get("tool_use_id"))] = str(result.get("text") or "")
    return found


def calls_by_id(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for message in messages:
        for call in message.get("toolUses") or []:
            found.add(str(call.get("tool_use_id")))
    return found


def score_session(
    session: dict[str, Any],
    emitted: list[dict[str, Any]],
    originals: dict[str, str],
) -> dict[str, Any]:
    """Pair outcomes and fact recall for one arm, derived from the emitted messages only."""
    present_calls = calls_by_id(emitted)
    present_results = results_by_id(emitted)
    text = _normalise(flatten(emitted))

    outcomes: dict[str, dict[str, int]] = {}
    for call in session["calls"]:
        kind = call["kind"]
        bucket = outcomes.setdefault(kind, {"kept": 0, "trimmed": 0, "dropped": 0})
        if call["id"] not in present_calls:
            bucket["dropped"] += 1
            continue
        original = originals.get(call["id"], "")
        current = present_results.get(call["id"])
        if current is None:
            bucket["trimmed"] += 1
        elif _normalise(current) == _normalise(original):
            bucket["kept"] += 1
        else:
            bucket["trimmed"] += 1

    missing = [fact for fact in session["required_facts"] if _normalise(fact) not in text]
    return {"outcomes": outcomes, "facts_total": len(session["required_facts"]), "facts_missing": missing}


def count(text: str) -> tuple[int, str]:
    from lcc.token_budget import count_tokens

    result = count_tokens(text, "gpt-4.1")
    return int(result.value), result.method.value


def ledger_snapshot() -> tuple[Path | None, int]:
    from lcc.relevance.jev import default_ledger_path

    path = default_ledger_path()
    if path is None or not path.is_file():
        return path, 0
    return path, len(path.read_bytes())


def ledger_usage(path: Path | None, offset: int) -> dict[str, int] | None:
    if path is None or not path.is_file():
        return None
    try:
        raw = path.read_bytes()[offset:]
    except OSError:
        return None
    totals = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("status") != "ok":
            continue
        totals["calls"] += 1
        totals["input_tokens"] += int(entry.get("input_tokens") or 0)
        totals["output_tokens"] += int(entry.get("output_tokens") or 0)
    return totals


def run_lcc(session: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    import time

    from lcc.relevance.transcript import (
        TranscriptCompactionRequest,
        compact_transcript,
        messages_to_payload,
    )

    started = time.perf_counter()
    result = compact_transcript(
        TranscriptCompactionRequest(
            payload={"messages": session["messages"]},
            question=session["objective"],
            provider="jev",
            threshold=options["threshold"],
            preserve_recent=options["preserve_recent"],
            trim_head_chars=options["trim_head_chars"],
            max_state_tokens=options["max_state_tokens"],
            max_request_tokens=options["max_request_tokens"],
            jev_model=options["jev_model"],
        )
    )
    return {
        "ok": True,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "messages": messages_to_payload(result.messages),
        "report": result.report,
    }


def ensure_npm_package() -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    if not (WORK_DIR / "node_modules" / NPM_PACKAGE).is_dir():
        subprocess.run(["npm", "install", "--no-audit", "--no-fund", NPM_PACKAGE], cwd=WORK_DIR, check=True)
    shutil.copy(HERE / "fast_jev_arm.mjs", WORK_DIR / "fast_jev_arm.mjs")
    return WORK_DIR


def for_fast_jev(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`fast-jev-compaction` iterates `toolUses`/`toolResults` on every message, so both keys
    must exist even when empty; the corpus omits them when a message has none."""
    normalised = []
    for message in messages:
        entry = dict(message)
        entry.setdefault("toolUses", [])
        entry.setdefault("toolResults", [])
        normalised.append(entry)
    return normalised


def run_fast_jev(session: dict[str, Any], options: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    job = WORK_DIR / f"job_{session['id']}.json"
    out = WORK_DIR / f"out_{session['id']}.json"
    job.write_text(
        json.dumps(
            {
                "messages": for_fast_jev(session["messages"]),
                "options": {
                    "preserveRecentMessages": options["preserve_recent"],
                    "threshold": options["threshold"],
                    "trimHeadChars": options["trim_head_chars"],
                    "maxStateTokens": options["max_state_tokens"],
                    "maxRequestTokens": options["max_request_tokens"],
                    "question": session["objective"],
                    "jevModel": options["jev_model"],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    process = subprocess.run(
        ["node", "fast_jev_arm.mjs", job.name, out.name],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=900,
    )
    payload: dict[str, Any] = {"ok": False, "error": f"node exited {process.returncode}: {process.stderr[-400:]}"}
    if out.is_file():
        payload = json.loads(out.read_text(encoding="utf-8"))
    payload["node_exit_code"] = process.returncode
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("none", "lcc", "fast-jev", "all"), default="all")
    parser.add_argument("--sessions", nargs="*", default=None)
    args = parser.parse_args()

    if not os.environ.get("TYPESAFE_API_KEY") and args.arm in ("lcc", "fast-jev", "all"):
        print("no TYPESAFE_API_KEY in the environment; nothing to measure", file=sys.stderr)
        return 9

    sessions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CORPUS_DIR.glob("*.json"))
        if path.name != "index.json"
    ]
    if args.sessions:
        sessions = [session for session in sessions if session["id"] in set(args.sessions)]

    arms = ("none", "lcc", "fast-jev") if args.arm == "all" else (args.arm,)
    work_dir = ensure_npm_package() if "fast-jev" in arms else None

    run_id = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict[str, Any]] = []

    for session in sessions:
        originals = {call["id"]: _original_result(session, call["id"]) for call in session["calls"]}
        before_text = flatten(session["messages"])
        tokens_before, method = count(before_text)
        for arm in arms:
            row: dict[str, Any] = {
                "run_id": run_id,
                "session": session["id"],
                "arm": arm,
                "harness": "real",
                "counts": session["counts"],
                "chars_before": len(before_text),
                "tokens_before": tokens_before,
                "token_count_method": method,
            }
            ledger_path, ledger_offset = ledger_snapshot() if arm in ("lcc", "fast-jev") else (None, 0)
            if arm == "none":
                emitted = session["messages"]
                row.update({"latency_ms": 0, "requests": 0})
            elif arm == "lcc":
                outcome = run_lcc(session, DEFAULT_OPTIONS)
                emitted = outcome.get("messages", [])
                row["latency_ms"] = outcome.get("latency_ms")
                row["ok"] = outcome.get("ok", False)
                row["requests"] = (outcome.get("report") or {}).get("requests")
                row["lcc_report"] = {
                    key: (outcome.get("report") or {}).get(key)
                    for key in (
                        "provider_used",
                        "degraded",
                        "degradation_reason",
                        "semantic_guarantee",
                        "jev_model_resolved",
                        "state_tokens",
                        "state_fit_stage",
                        "calls",
                        "tool_reduction_ratio",
                    )
                }
            else:
                assert work_dir is not None
                outcome = run_fast_jev(session, DEFAULT_OPTIONS, work_dir)
                emitted = outcome.get("messages", []) if outcome.get("ok") else []
                row["latency_ms"] = outcome.get("latency_ms")
                row["ok"] = bool(outcome.get("ok"))
                row["error"] = outcome.get("error")
                row["fast_jev_stats"] = outcome.get("stats")
                row["requests"] = (outcome.get("stats") or {}).get("requests") or (
                    outcome.get("stats") or {}
                ).get("requestCount")
                row["fast_jev_reduction_ratio"] = outcome.get("reduction_ratio")

            if arm != "none" and not row.get("ok", True):
                rows.append(row)
                continue

            scoring = score_session(session, emitted, originals)
            after_text = flatten(emitted)
            tokens_after, _ = count(after_text)
            row.update(
                {
                    "chars_after": len(after_text),
                    "tokens_after": tokens_after,
                    "reduction_ratio": 0.0
                    if not before_text
                    else round(max(0.0, 1 - len(after_text) / len(before_text)), 6),
                    "token_reduction_ratio": 0.0
                    if tokens_before == 0
                    else round(max(0.0, 1 - tokens_after / tokens_before), 6),
                    "messages_after": len(emitted),
                    "outcomes": scoring["outcomes"],
                    "facts_total": scoring["facts_total"],
                    "facts_missing": scoring["facts_missing"],
                    "fact_recall": round(
                        1 - len(scoring["facts_missing"]) / max(1, scoring["facts_total"]), 6
                    ),
                    "ledger_usage": ledger_usage(ledger_path, ledger_offset),
                }
            )
            rows.append(row)
            print(
                f"{session['id']:7} {arm:9} tokens {tokens_before:5}->{tokens_after:5} "
                f"({row['token_reduction_ratio'] * 100:5.1f}%) recall {row['fact_recall']:.2f} "
                f"evidence dropped {scoring['outcomes'].get('evidence', {}).get('dropped', 0)} "
                f"latency {row['latency_ms']} ms"
            )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    # The arm selection is part of the filename: a partial run must never overwrite the
    # canonical artifact of a full run (that is how a canonical table loses its rows).
    label = "all" if args.arm == "all" else args.arm
    json_path = RESULTS_DIR / f"transcript_ab_{stamp}_{label}.json"
    jsonl_path = RESULTS_DIR / f"transcript_ab_{stamp}_{label}.jsonl"
    json_path.write_text(
        json.dumps({"run_id": run_id, "options": DEFAULT_OPTIONS, "rows": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    jsonl_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print(f"\nwrote {json_path.relative_to(HERE.parents[1])} and {jsonl_path.name} ({len(rows)} rows)")
    return 0


def _original_result(session: dict[str, Any], call_id: str) -> str:
    for message in session["messages"]:
        for result in message.get("toolResults") or []:
            if result.get("tool_use_id") == call_id:
                return str(result.get("text") or "")
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
