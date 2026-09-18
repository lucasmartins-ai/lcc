#!/usr/bin/env python3
"""Deterministic transform matrix: every LCC function in isolation, vs a no-LCC baseline.

For each corpus and each arm we run the transform, then measure -- with an EXACT tiktoken
count, never a heuristic -- what a downstream model would actually receive:

  tokens_in / tokens_out   exact o200k tokens of raw corpus vs emitted context
  reduction_pct            (in - out) / in
  required_recall          share of the 5 ground-truth figures that survived the transform
  distractor_leak          noisy non-evidence blocks that survived (should be 0 or harmless)
  artifacts                files each arm produced (prompt / report / structured output)

Writes results/matrix.jsonl (one row per corpus x arm) and prints a compact table.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent
CORPORA = ROOT / "corpora"
OUT = ROOT / "results"
WORK = ROOT / "work"
LCC = "lcc"

# Distinctive strings for the 5 ground-truth facts. A transform that drops one of these
# blocks makes the downstream answer impossible, which is the whole point of the metric.
REQUIRED = {
    "A_step1_63pct": r"63 percent",
    "B_p75_4.2s": r"4\.2 seconds",
    "C_after_hours_41pct": r"41 percent",
    "D_chairs_idle": r"3 chairs",
    "E_retype_4min": r"4 minutes",
}
DISTRACTOR_PAT = r"DISTRACTOR \d"

OBJECTIVE = "What is the measured mobile conversion problem for the clinic?"

ARMS: dict[str, dict] = {
    "baseline_raw": {"kind": "identity"},
    "optimize_default": {"kind": "prompt", "cmd": ["optimize", "-q", OBJECTIVE]},
    "optimize_claude_xml": {
        "kind": "prompt",
        "cmd": ["optimize", "-q", OBJECTIVE, "--template", "claude_xml"],
    },
    "optimize_markdown": {
        "kind": "prompt",
        "cmd": ["optimize", "-q", OBJECTIVE, "--template", "structured_markdown"],
    },
    "optimize_no_dedup": {
        "kind": "prompt",
        "cmd": ["optimize", "-q", OBJECTIVE, "--no-near-dedup", "--no-boilerplate"],
    },
    "prepare_default": {"kind": "prompt", "cmd": ["prepare", "-q", OBJECTIVE]},
    "compact_mechanical": {
        "kind": "compact",
        "cmd": ["compact", "-q", OBJECTIVE, "--provider", "mechanical"],
    },
    "compact_jev": {"kind": "compact", "cmd": ["compact", "-q", OBJECTIVE, "--provider", "jev"]},
    "compact_jev_prefix": {
        "kind": "compact",
        "cmd": [
            "compact", "-q", OBJECTIVE, "--provider", "jev",
            "--prefix-marker", "<!-- lcc:cache-break -->",
        ],
    },
    "compact_jev_strict": {
        "kind": "compact",
        "cmd": ["compact", "-q", OBJECTIVE, "--provider", "jev", "--trim-head-chars", "0"],
    },
    "compact_jev_tail6": {
        "kind": "compact",
        "cmd": ["compact", "-q", OBJECTIVE, "--provider", "jev", "--preserve-tail", "6"],
    },
    "intake_default": {"kind": "prompt", "cmd": ["intake", "-q", OBJECTIVE]},
    "chain_compact_optimize": {
        "kind": "chain",
        "cmd": ["compact", "-q", OBJECTIVE, "--provider", "jev"],
        "then": ["optimize", "-q", OBJECTIVE, "--template", "claude_xml"],
    },
}

COMPACT_KEYS = [
    "provider_used", "degraded", "calls", "reused_decisions", "blocks_total", "blocks_scored",
    "blocks_protected", "blocks_dropped", "blocks_trimmed", "reduction_ratio", "worth_it",
    "first_mutation_offset", "prefix_untouched", "prefix_protected", "prefix_sha256",
    "output_sha256", "token_count_method", "tokens_before", "tokens_after", "latency_ms",
    "min_reduction",
]


def exact_tokens(path: pathlib.Path) -> int:
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    return len(enc.encode(path.read_text(encoding="utf-8")))


def recall(text: str) -> dict:
    found = {name: bool(re.search(pat, text)) for name, pat in REQUIRED.items()}
    return {
        "found": found,
        "recall": round(sum(found.values()) / len(found), 4),
        "missing": [k for k, v in found.items() if not v],
        "distractor_leak": len(re.findall(DISTRACTOR_PAT, text)),
    }


def run_arm(scale: str, arm: str, spec: dict) -> dict:
    src = CORPORA / f"{scale}.md"
    arm_dir = WORK / scale / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    artifact = arm_dir / "context.md"
    report_path = arm_dir / "report.json"

    row: dict = {"scale": scale, "arm": arm, "kind": spec["kind"]}
    started = time.time()

    if spec["kind"] == "identity":
        artifact.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    elif spec["kind"] in ("prompt", "compact"):
        cmd = [LCC, *spec["cmd"], str(src), "-o", str(artifact), "-r", str(report_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        row["exit_code"] = proc.returncode
        if proc.returncode != 0:
            row["error"] = (proc.stderr or proc.stdout)[-500:]
    elif spec["kind"] == "chain":
        stage1 = arm_dir / "stage1_compacted.md"
        r1 = arm_dir / "stage1_report.json"
        p1 = subprocess.run(
            [LCC, *spec["cmd"], str(src), "-o", str(stage1), "-r", str(r1)],
            capture_output=True, text=True,
        )
        p2 = subprocess.run(
            [LCC, *spec["then"], str(stage1), "-o", str(artifact), "-r", str(report_path)],
            capture_output=True, text=True,
        )
        row["exit_code"] = max(p1.returncode, p2.returncode)
        if p1.returncode:
            row["error_stage1"] = (p1.stderr or p1.stdout)[-400:]
        if p2.returncode:
            row["error_stage2"] = (p2.stderr or p2.stdout)[-400:]
        if r1.exists():
            row["stage1_report"] = json.loads(r1.read_text())

    row["wall_ms"] = int((time.time() - started) * 1000)
    row["tokens_in"] = exact_tokens(src)
    if artifact.exists():
        row["tokens_out"] = exact_tokens(artifact)
        text = artifact.read_text(encoding="utf-8")
        row.update(recall(text))
        row["chars_out"] = len(text)
    row["chars_in"] = len(src.read_text(encoding="utf-8"))
    if row.get("tokens_out"):
        row["reduction_pct"] = round(
            (row["tokens_in"] - row["tokens_out"]) / row["tokens_in"] * 100, 2
        )
    if report_path.exists():
        try:
            rep = json.loads(report_path.read_text())
            row["report"] = {k: rep[k] for k in COMPACT_KEYS if k in rep}
        except json.JSONDecodeError:
            row["report_error"] = "unreadable report"
    return row


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for scale in ("small", "medium", "large"):
        for arm, spec in ARMS.items():
            row = run_arm(scale, arm, spec)
            rows.append(row)
            print(
                f"{scale:6} {arm:24} in={row['tokens_in']:6} out={row.get('tokens_out', 0):6} "
                f"red={row.get('reduction_pct', 0):6.1f}% recall={row.get('recall', 0):.2f} "
                f"leak={row.get('distractor_leak', 0):3} {row['wall_ms']:5}ms"
                + (f" ERR={row.get('error','')[:60]}" if row.get("error") else "")
            )
    (OUT / "matrix.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )
    print(f"\nwrote {len(rows)} rows -> {OUT / 'matrix.jsonl'}")


if __name__ == "__main__":
    main()
