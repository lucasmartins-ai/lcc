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

# Ground truth is loaded from the corpus index so the categories and markers live in one place
# (make_corpora.py) instead of being duplicated here and drifting.
def _scales() -> list[str]:
    """Every corpus the index knows about, in canonical order, so adding a scale is one edit."""
    index = json.loads((CORPORA / "index.json").read_text(encoding="utf-8"))
    order = ("small", "medium", "large", "xl")
    return [scale for scale in order if scale in index] + [
        scale for scale in index if scale not in order
    ]


def _load_items(scale: str) -> list[dict[str, str]]:
    index = json.loads((CORPORA / "index.json").read_text(encoding="utf-8"))
    return index[scale]["items"]


DISTRACTOR_PAT = r"DISTRACTOR \d"


def recall(text: str, scale: str) -> dict:
    items = _load_items(scale)
    found = {item["marker"]: bool(re.search(item["marker"], text)) for item in items}
    by_category: dict[str, list[bool]] = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(found[item["marker"]])
    missing = [item["marker"] for item in items if not found[item["marker"]]]
    return {
        "found": found,
        "recall": round(sum(found.values()) / len(found), 4),
        "missing": missing,
        "by_category": {
            category: {
                "kept": sum(hits),
                "total": len(hits),
                "recall": round(sum(hits) / len(hits), 4),
            }
            for category, hits in by_category.items()
        },
        "distractor_leak": len(re.findall(DISTRACTOR_PAT, text)),
    }

OBJECTIVE = "What is wrong with the clinic's booking operation, and what limits what we can change?"

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
        row.update(recall(text, scale))
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
    for scale in _scales():
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
    _print_category_table(rows)


def _print_category_table(rows: list[dict]) -> None:
    """Recall per information category, averaged over every arm that emits a context.

    A flat fact count hides which kind of information a transform loses. This table is the
    answer to "is it good at keeping constraints, exceptions and dated values, or only at
    keeping the easy stuff?"
    """
    categories: list[str] = []
    for row in rows:
        for category in (row.get("by_category") or {}):
            if category not in categories:
                categories.append(category)
    by_arm: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        arm = row["arm"]
        for category, stats in (row.get("by_category") or {}).items():
            by_arm.setdefault(arm, {}).setdefault(category, []).append(stats["recall"])
    if not categories or not by_arm:
        return
    header = f"{'arm':24}" + "".join(f"{c[:12]:>14}" for c in categories)
    print("\nrecall by information category")
    print(header)
    print("-" * len(header))
    for arm in sorted(by_arm, key=lambda a: (-_arm_mean(by_arm[a]), a)):
        line = f"{arm:24}"
        for category in categories:
            values = by_arm[arm].get(category)
            line += f"{sum(values) / len(values):>13.2f} " if values else f"{'-':>13} "
        print(line)


def _arm_mean(stats: dict[str, list[float]]) -> float:
    values = [v for per_category in stats.values() for v in per_category]
    return sum(values) / len(values) if values else 0.0


if __name__ == "__main__":
    main()
