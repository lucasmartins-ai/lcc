#!/usr/bin/env python3
"""Tool-call mode: a config decision reversed by a later tool call.

A `Read` shows `engine: postgres`; several filler pairs later an `Edit` switches it to
`sqlite`. The objective asks which engine is in use. The failure this probes: the judge
keeps the old pair and drops the Edit, so the compacted session still reads "postgres".

Variants:
  * `restated`: the Edit result restates the change ("postgres -> sqlite");
  * `generic`: the Edit result is the bare "updated successfully" Claude Code returns, so
    the change lives only in the call's input.

Pass: whenever the old pair is kept, the new pair is kept too. Needs a live Jev key
(TYPESAFE_API_KEY); tool-call mode is Jev-only by design.

Run: python3 benchmarks/research/run_reversal_tool_calls.py [--runs 3]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LCC = Path(sys.executable).with_name("lcc")
OBJECTIVE = "write the README section documenting which engine the session store uses"
EDIT_RESULTS = {
    "restated": "The file config/session.yaml has been updated: engine: postgres -> engine: sqlite",
    "generic": "The file config/session.yaml has been updated successfully.",
}


def build(variant: str) -> tuple[dict, str, str]:
    """Transcript plus the ids of the old (Read) and new (Edit) pairs."""
    msgs: list[dict] = [{"role": "user", "text": "Set up the session store for the checkout "
                         "service and keep the config in config/session.yaml."}]

    def pair(tool: str, inp: dict, result: str) -> str:
        tid = f"toolu_{len(msgs):02d}"
        msgs.append({"role": "assistant", "text": "",
                     "toolUses": [{"tool_use_id": tid, "tool": tool, "input": inp}]})
        msgs.append({"role": "user", "toolResults": [{"tool_use_id": tid, "text": result}]})
        return tid

    def filler(i: int) -> None:
        pair("Bash", {"command": f"npm run lint -- src/module{i}"},
             f"src/module{i}: 0 errors, 2 warnings (no-unused-vars) in {40 + i} files checked")

    for i in range(4):
        filler(i)
    old = pair("Read", {"file_path": "config/session.yaml"},
               "session_store:\n  engine: postgres\n  host: db.internal\n  pool_size: 20\n")
    for i in range(4, 10):
        filler(i)
    new = pair("Edit", {"file_path": "config/session.yaml", "old_string": "engine: postgres",
                        "new_string": "engine: sqlite"}, EDIT_RESULTS[variant])
    for i in range(10, 16):
        filler(i)
    msgs.append({"role": "user", "text": "ok, now write the README section for the session store."})
    return {"messages": msgs}, old, new


def run_once(work: Path, variant: str, run: int) -> dict:
    transcript, old, new = build(variant)
    src, out, rep = (work / f"{variant}_{run}{s}" for s in (".json", ".out.json", ".report.json"))
    src.write_text(json.dumps(transcript), encoding="utf-8")
    proc = subprocess.run(
        [str(LCC), "compact", str(src), "-q", OBJECTIVE, "--mode", "tool-calls",
         "--preserve-recent", "2", "-o", str(out), "-r", str(rep)],
        capture_output=True, text=True,
    )
    if proc.returncode:
        return {"variant": variant, "run": run, "error": proc.stderr[-400:]}
    report = json.loads(rep.read_text(encoding="utf-8"))
    kept = set()
    emitted = json.loads(out.read_text(encoding="utf-8"))
    for msg in emitted["messages"] if isinstance(emitted, dict) else emitted:
        kept |= {u["tool_use_id"] for u in msg.get("toolUses", [])}
    old_kept, new_kept = old in kept, new in kept
    return {
        "variant": variant, "run": run, "harness": "real",
        "provider_used": report.get("provider_used"), "degraded": report.get("degraded"),
        "tokens_before": report.get("tokens_before"), "tokens_after": report.get("tokens_after"),
        "pairs_kept": sorted(kept), "old_pair_kept": old_kept, "new_pair_kept": new_kept,
        "pass": not (old_kept and not new_kept),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for variant in EDIT_RESULTS:
            for run in range(args.runs):
                row = run_once(Path(tmp), variant, run)
                rows.append(row)
                print(json.dumps(row))
    # A degraded pass keeps every pair, which passes vacuously, so it does not count.
    ok = all(r.get("pass") and r.get("provider_used") == "jev" and not r.get("degraded")
             for r in rows)
    dest = HERE / "results" / "reversal_tool_calls.json"
    dest.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(bool(r.get('pass')) for r in rows)}/{len(rows)} pass -> {dest}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
