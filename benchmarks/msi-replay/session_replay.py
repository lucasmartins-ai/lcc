"""Replay allowlisted local tool-result windows through the public MSI API.

Collect once with --collect <project-session-directory>, then freeze/replay
without access to that directory. Only pytest summaries and progress markers
are published. This narrow sampling frame cannot measure agent task success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from replay import check_payload, receipt_hash

from lcc.msi import MSI_API_VERSION, compile
from lcc.router.escalate import ExecutionReceipt, ReceiptVersions
from lcc.router.verify import VerificationSubject, run_verification
from lcc.token_budget.counters import approximate_token_count

HERE = Path(__file__).resolve().parent
SESSIONS_PATH = HERE / "sessions.json"
RESULTS_PATH = HERE / "session_results.json"
DATASET = "msi-session-replay-9-2026-10-03"
_COUNT = r"\d+ (?:passed|failed|skipped|deselected|xfailed|xpassed|warnings?|errors?)"
SUMMARY = re.compile(rf"{_COUNT}(?:, {_COUNT})* in [0-9.]+s")
PROGRESS = re.compile(r"[.sFxEX]{5,}(?:\s*\[\s*\d+%\])?")
OBJECTIVE = "Report the pytest passed count and duration."


def safe_excerpt(text: str) -> str:
    """Positive allowlist: everything outside the output grammar is discarded."""
    lines = []
    for line in text.splitlines():
        summary = SUMMARY.search(line)
        if summary:
            lines.append(summary.group())
        elif PROGRESS.fullmatch(line.strip()):
            lines.append(line.strip())
    return "\n\n".join(lines)


def collect(directory: Path) -> dict:
    paths = sorted(directory.glob("*.jsonl"))
    traces: list[dict[str, Any]] = []
    for index, path in enumerate(paths, 1):
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        for number, line in enumerate(raw.decode().splitlines(), 1):
            record = json.loads(line)
            message = record.get("message", {})
            if not isinstance(message, dict) or not isinstance(message.get("content"), list):
                continue
            for block in message["content"]:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                text = block.get("content", "")
                if not isinstance(text, str) or not SUMMARY.search(text):
                    continue
                excerpt = safe_excerpt(text)
                traces.append({
                    "trace_id": f"local-pytest-{len(traces) + 1:03}",
                    "session_alias": f"session-{index:03}",
                    "source_sha256": source_hash,
                    "record_number": number,
                    "collected_at": record["timestamp"],
                    "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                    "context": excerpt,
                    "required_facts": SUMMARY.findall(excerpt),
                })
    return {
        "dataset": DATASET, "data_class": "REPLAYED",
        "capture_date": "2026-10-03", "source_files_scanned": len(paths),
        "selection_rule": "All tool_result blocks with a pytest outcome/duration summary "
                          "in every top-level JSONL in the local LCC project session directory; "
                          "keep repetitions; publish only summaries and progress markers.",
        "anonymization": "Positive output grammar; omit paths, ids, commands, prompts, "
                         "names and nonmatching output. Source filenames replaced by aliases.",
        "traces": traces,
    }


def run(trace: dict, arm: str) -> dict:
    started = time.perf_counter()
    context = trace["context"]
    if arm == "msi_api":
        compiled = compile(OBJECTIVE, context, task_id=trace["trace_id"])
        candidate = compiled.context
        receipt = compiled.receipt.to_spec_dict()
        sufficiency_failures = compiled.sufficiency["failures"]
    elif arm == "full":
        candidate = context
        sufficiency_failures = 0
        receipt = ExecutionReceipt(
            receipt_id=f"{trace['trace_id']}:full", task_id=trace["trace_id"],
            selected_units=[trace["excerpt_sha256"]],
            versions=ReceiptVersions(compiler="full-context-1.0", model="local_small"),
        ).to_spec_dict()
    else:
        raise ValueError(f"unknown arm: {arm}")
    verification = run_verification(VerificationSubject(
        output={"summary": candidate}, required_fields=["summary"],
        required_facts=trace["required_facts"], objective=OBJECTIVE,
    ), "standard")
    tokens = approximate_token_count(candidate)
    wall = round((time.perf_counter() - started) * 1000, 4)
    receipt["verification"]["profile"] = "standard"
    receipt["versions"]["dataset"] = DATASET
    receipt["cost"].update(
        tokens_in=approximate_token_count(context), tokens_out=tokens, latency_ms=int(wall)
    )
    missing = [f for f in trace["required_facts"] if f not in candidate]
    return {
        "trace_id": trace["trace_id"], "arm": arm,
        "success": verification.status == "PASS" and not sufficiency_failures,
        "verification_result": verification.status,
        "verification_failures": int(verification.status != "PASS"),
        "missing_facts": missing, "sufficiency_failures": sufficiency_failures,
        "full_tokens": approximate_token_count(context), "retained_tokens": tokens,
        "cost_usd_external": 0.0, "model_calls": 0, "frontier_calls": 0,
        "frontier_calls_avoided": 0, "verification_calls": 1,
        "restores": len(receipt["restorations"]["restored"]),
        "retries": receipt["restorations"]["retries"],
        "escalations": len(receipt["restorations"]["escalations"]),
        "wall_ms_measured": wall, "receipt": receipt,
        "receipt_hash": receipt_hash(receipt),
    }


def build() -> dict:
    source = json.loads(SESSIONS_PATH.read_text())
    runs = [run(t, a) for t in source["traces"] for a in ("full", "msi_api")]
    aggregate = {}
    for arm in ("full", "msi_api"):
        selected = [r for r in runs if r["arm"] == arm]
        aggregate[arm] = {
            "n": len(selected), "successes": sum(r["success"] for r in selected),
            "wall_ms_p50": sorted(r["wall_ms_measured"] for r in selected)[len(selected) // 2],
        }
        for key in ("retained_tokens", "full_tokens", "cost_usd_external", "model_calls",
                    "frontier_calls", "frontier_calls_avoided", "verification_calls",
                    "verification_failures", "restores", "retries", "escalations"):
            aggregate[arm][key] = sum(r[key] for r in selected)
    regressions = [{
        "trace_id": r["trace_id"], "arm": r["arm"], "missing_facts": r["missing_facts"],
        "sufficiency_failures": r["sufficiency_failures"],
        "root_cause": "Required summary absent from compiled context" if r["missing_facts"]
                      else "Structural sufficiency check did not pass",
        "next_experiment": "Inspect mechanical decision rationales on this frozen excerpt; "
                           "evaluate any fix on a disjoint session split.",
    } for r in runs if not r["success"]]
    # Two arms: frontier dominance needs only this direct comparison.
    full, msi = aggregate["full"], aggregate["msi_api"]
    pareto = ["msi_api"] if (msi["successes"] >= full["successes"]
                              and msi["retained_tokens"] < full["retained_tokens"]) else [
        "full", "msi_api"
    ]
    return {
        "dataset": DATASET, "data_class": "REPLAYED", "evidence_class": "CURRENT",
        "api_version": MSI_API_VERSION, "planner": "planner-1.0", "evaluator": "verify-1.0",
        "tokenizer": "heuristic-v1", "source": source,
        "quality_rubric": "Required pytest summaries preserved verbatim AND structural "
                          "sufficiency passes; this is retention quality, not agent task success.",
        "cost_scope": "No model/network calls; external API spend = 0. CPU/energy not priced.",
        "runs": runs, "aggregate": aggregate, "regressions": regressions, "pareto_arms": pareto,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", type=Path, help="Freeze anonymous excerpts before evaluation")
    parser.add_argument("--check", action="store_true", help="Replay and assert the frozen payload")
    args = parser.parse_args()
    if args.collect:
        if args.check:
            parser.error("--collect and --check are separate capture/replay steps")
        captured = collect(args.collect)
        SESSIONS_PATH.write_text(json.dumps(captured, indent=2) + "\n")
        print(f"captured {len(captured['traces'])} windows; "
              f"{captured['source_files_scanned']} files")
    else:
        payload = build()
        if args.check:
            check_payload(payload, json.loads(RESULTS_PATH.read_text()))
            print(f"public API replay reproducible: {len(payload['runs'])} runs")
        else:
            RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
            print(json.dumps(payload["aggregate"], indent=2))
