#!/usr/bin/env python3
"""Run the adversarial suite against `lcc compact` and report what broke.

Two levels of assertion per case:

  survival   the first 60 characters of each critical block must appear in the emitted
             context. `compact` re-emits kept bytes exactly and trimmed blocks keep a
             bounded head, so a missing head means the block was dropped outright.
  checks     the case's own regex assertions, which encode the semantics the case is
             about (the negation survived, both sides of the contradiction survived, the
             authoritative value survived, and so on).

Writes results/adversarial.json and prints one row per case. Exits non-zero when any
case fails, so it can gate a change.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from adversarial_cases import CASES, build_corpus  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
CASES_DIR = ROOT / "adversarial"
WORK = ROOT / "work_adversarial"
OUT = ROOT / "results"
HEAD_CHARS = 60


def block_survived(block: str, output: str) -> bool:
    head = block.strip()[:HEAD_CHARS]
    return head in output


def run_case(case, provider: str = "jev", pressure: int = 1, extra: list[str] | None = None) -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    corpus_path = CASES_DIR / f"{case.id}.md"
    if pressure == 1:
        # The committed corpora are the pressure-1 shape; higher factors stay in the scratch
        # directory so a sweep does not rewrite the evidence files under version control.
        corpus_path.write_text(build_corpus(case, pressure), encoding="utf-8")
    elif not corpus_path.exists():
        corpus_path.write_text(build_corpus(case), encoding="utf-8")
    dest = WORK / f"{case.id}.md"
    report_path = WORK / f"{case.id}.report.json"

    started = time.time()
    proc = subprocess.run(
        [
            "lcc", "compact", str(corpus_path),
            "-q", case.question,
            "--provider", provider,
            "-o", str(dest),
            "-r", str(report_path),
            *(extra or []),
        ],
        capture_output=True,
        text=True,
    )
    wall_ms = int((time.time() - started) * 1000)
    if proc.returncode != 0:
        return {
            "id": case.id, "hazard": case.hazard, "error": (proc.stderr or proc.stdout)[-400:],
            "passed": False, "wall_ms": wall_ms,
        }

    output = dest.read_text(encoding="utf-8")
    report = json.loads(report_path.read_text())

    survival = [
        {"index": i, "survived": block_survived(block, output), "head": block.strip()[:HEAD_CHARS]}
        for i, block in enumerate(case.critical)
    ]
    # `lost_blocks` is everything that went missing; `lost_required` is the subset the case
    # actually fails on. A distractor block may be dropped on purpose.
    lost = sorted(s["index"] for s in survival if not s["survived"])
    required = set(case.must_survive) if case.must_survive else set(range(len(case.critical)))
    lost_required = [i for i in lost if i in required]

    check_results = []
    for name, pattern, expectation in case.checks:
        found = bool(re.search(pattern, output, re.I | re.S))
        ok = found if expectation == "present" else not found
        check_results.append({"name": name, "expectation": expectation, "ok": ok})

    failed_checks = [c["name"] for c in check_results if not c["ok"]]
    return {
        "id": case.id,
        "hazard": case.hazard,
        "description": case.description,
        "critical_blocks": len(case.critical),
        "lost_blocks": lost,
        "lost_required": lost_required,
        "checks": check_results,
        "failed_checks": failed_checks,
        "survival_ratio": round(
            (len(required) - len(lost_required)) / len(required), 3
        ) if required else 1.0,
        "reduction_pct": round(report["reduction_ratio"] * 100, 1),
        "blocks_dropped": report["blocks_dropped"],
        "blocks_trimmed": report["blocks_trimmed"],
        "semantic_guarantee": report.get("semantic_guarantee"),
        "provider_used": report["provider_used"],
        "token_count_method": report["token_count_method"],
        "break_even_reuses": report.get("break_even_reuses"),
        "passed": not lost_required and not failed_checks,
        "wall_ms": wall_ms,
    }


def main() -> None:
    provider = "jev"
    pressure = 1
    extra: list[str] = []
    for arg in sys.argv[1:]:
        if arg.isdigit():
            pressure = int(arg)
        elif arg == "noprot":
            extra.append("--no-deterministic-protection")
        else:
            provider = arg
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    suffix = "_noprot" if extra else ""
    print(f"provider={provider} pressure={pressure} extra={extra or 'none'}")
    print(f"{'case':28} {'hazard':11} {'surv':>5} {'checks':>7} {'red':>7} {'drop':>5}  verdict")
    for case in CASES:
        row = run_case(case, provider, pressure, extra)
        row["pressure"] = pressure
        rows.append(row)
        if "error" in row:
            print(f"{case.id:28} {case.hazard:11} {'-':>5} {'-':>7} {'-':>7} {'-':>5}  ERROR")
            continue
        checks_ok = f"{sum(1 for c in row['checks'] if c['ok'])}/{len(row['checks'])}"
        verdict = "PASS" if row["passed"] else "FAIL"
        detail = ""
        if row["failed_checks"]:
            detail += " checks=" + ",".join(row["failed_checks"])
        if row["lost_required"]:
            detail += " lost=" + ",".join(str(i) for i in row["lost_required"])
        elif row["lost_blocks"]:
            detail += " (dropped distractors: " + ",".join(str(i) for i in row["lost_blocks"]) + ")"
        print(
            f"{case.id:28} {row['hazard']:11} {row['survival_ratio']:>5.2f} "
            f"{checks_ok:>7} {row['reduction_pct']:>6.1f}% {row['blocks_dropped']:>5}  {verdict}{detail}"
        )

    passed = sum(1 for r in rows if r.get("passed"))
    payload = {
        "provider": provider,
        "pressure": pressure,
        "cases": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "rows": rows,
    }
    name = f"adversarial_{provider}_p{pressure}{suffix}.json"
    (OUT / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(rows)} cases pass -> {OUT / name}")
    raise SystemExit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    main()
