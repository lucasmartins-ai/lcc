#!/usr/bin/env python3
"""Stress and edge-case suite for `lcc compact`.

Two questions this answers that the matrix cannot:

  1. Does behaviour hold at the stress scale? `xl` is roughly four times `large`, so category
     recall, reduction and cache byte-stability are re-measured where the corpus stops being
     small enough to fit comfortably.

  2. Does it survive inputs nobody designs for? Empty files, whitespace, a single oversized
     block, CRLF, unicode, and hundreds of blocks below the scoring floor. A compaction pass that
     crashes or silently empties a file is worse than one that compacts badly.

Writes results/stress.json and exits non-zero on any failure.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent
CORPORA = ROOT / "corpora"
WORK = ROOT / "work_stress"
OUT = ROOT / "results"
OBJECTIVE = "What is wrong with the clinic's booking operation, and what limits what we can change?"


def _run(src: pathlib.Path, dest: pathlib.Path, report: pathlib.Path, extra: list[str] | None = None):
    started = time.time()
    proc = subprocess.run(
        [
            "lcc", "compact", str(src),
            "-q", OBJECTIVE,
            "--provider", "jev",
            "-o", str(dest),
            "-r", str(report),
            *(extra or []),
        ],
        capture_output=True,
        text=True,
    )
    return proc, int((time.time() - started) * 1000)


def stress_scale() -> dict:
    """`xl`: category recall, reduction, and cold/warm byte stability in one pair of runs."""
    src = CORPORA / "xl.md"
    if not src.exists():
        return {"skipped": "corpora/xl.md not generated"}
    index = json.loads((CORPORA / "index.json").read_text(encoding="utf-8"))["xl"]
    cache = WORK / "xl_decisions.jsonl"
    cold_out, cold_rep = WORK / "xl_cold.md", WORK / "xl_cold.json"
    warm_out, warm_rep = WORK / "xl_warm.md", WORK / "xl_warm.json"

    proc_cold, cold_ms = _run(src, cold_out, cold_rep, ["--decisions-cache", str(cache)])
    if proc_cold.returncode != 0:
        return {"error": (proc_cold.stderr or proc_cold.stdout)[-300:]}
    proc_warm, warm_ms = _run(src, warm_out, warm_rep, ["--decisions-cache", str(cache)])
    if proc_warm.returncode != 0:
        return {"error": (proc_warm.stderr or proc_warm.stdout)[-300:]}

    text = cold_out.read_text(encoding="utf-8")
    cold, warm = json.loads(cold_rep.read_text()), json.loads(warm_rep.read_text())
    per_category = {}
    for category in index["categories"]:
        items = [i for i in index["items"] if i["category"] == category]
        kept = sum(1 for i in items if re.search(i["marker"], text))
        per_category[category] = {"kept": kept, "total": len(items), "recall": round(kept / len(items), 3)}

    return {
        "corpus_chars": len(src.read_text(encoding="utf-8")),
        "blocks_total": cold["blocks_total"],
        "reduction_pct": round(cold["reduction_ratio"] * 100, 1),
        "tokens_before": cold["tokens_before"],
        "tokens_after": cold["tokens_after"],
        "token_count_method": cold["token_count_method"],
        "calls": cold["calls"],
        "cold_wall_ms": cold_ms,
        "warm_wall_ms": warm_ms,
        "warm_calls": warm["calls"],
        "warm_reused_decisions": warm["reused_decisions"],
        "byte_identical_cold_warm": cold_out.read_text(encoding="utf-8") == warm_out.read_text(encoding="utf-8"),
        "sha_match": cold["output_sha256"] == warm["output_sha256"],
        "semantic_guarantee": cold["semantic_guarantee"],
        "break_even_reuses": cold.get("break_even_reuses"),
        "per_category": per_category,
        "perfect_recall": all(v["recall"] == 1.0 for v in per_category.values()),
    }


def _edge_case(name: str, content: str, *, expect_substring: str | None = None,
               expect_max_ratio: float | None = None, expect_empty_ok: bool = False) -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    src = WORK / f"edge_{name}.md"
    src.write_text(content, encoding="utf-8")
    dest, report = WORK / f"edge_{name}.out.md", WORK / f"edge_{name}.json"
    proc, wall = _run(src, dest, report)
    result: dict = {"case": name, "input_chars": len(content), "exit_code": proc.returncode,
                    "wall_ms": wall}
    if proc.returncode != 0:
        result["passed"] = False
        result["error"] = (proc.stderr or proc.stdout)[-200:]
        return result
    out = dest.read_text(encoding="utf-8")
    result["output_chars"] = len(out)
    if expect_substring is not None:
        result["kept_expected"] = expect_substring in out
    if expect_max_ratio is not None:
        result["output_ratio"] = round(len(out) / max(1, len(content)), 3)
    result["report"] = json.loads(report.read_text())
    checks = [result.get("exit_code") == 0]
    if expect_substring is not None:
        checks.append(result["kept_expected"])
    if expect_max_ratio is not None:
        checks.append(result["output_ratio"] <= expect_max_ratio)
    if expect_empty_ok and not content.strip():
        checks.append(len(out) <= len(content))
    result["passed"] = all(checks)
    return result


def edges() -> list[dict]:
    giant = "AUDIT VERDICT: safe to ship.\n\n" + ("Supporting detail line for the stress case.\n" * 6000)
    many_tiny = "\n\n".join(f"CHECK {i}: FAILED" for i in range(400))
    return [
        _edge_case("empty", "", expect_empty_ok=True),
        _edge_case("whitespace_only", "   \n\n\t\n   \n", expect_empty_ok=True),
        _edge_case("single_tiny_block", "Short note."),
        _edge_case(
            "giant_single_block", giant, expect_substring="AUDIT VERDICT", expect_max_ratio=0.6
        ),
        _edge_case(
            "crlf_line_endings",
            "Constraint: rebooking only within 48 hours.\r\n\r\nNoise line.\r\n\r\nAnother noise line.\r\n",
        ),
        _edge_case(
            "unicode_and_emoji",
            "OdontoVero — Clínica Odontológica 🦷\n\nRegra: não contactar sem consentimento.\n\n"
            + ("Ruído de log repetido para dar volume ao corpus e permitir descarte.\n\n" * 6),
            expect_substring="OdontoVero",
        ),
        _edge_case(
            "many_tiny_blocks", many_tiny, expect_substring="CHECK 399: FAILED"
        ),
        _edge_case(
            "one_very_long_line",
            "FACT: " + ("x" * 40000),
            expect_substring="FACT:",
        ),
    ]


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== stress: escala xl ===")
    scale = stress_scale()
    if "error" in scale or "skipped" in scale:
        print(f"  {scale}")
    else:
        print(
            f"  {scale['corpus_chars']:,} chars | {scale['blocks_total']} blocks | "
            f"reducao {scale['reduction_pct']}% | {scale['tokens_before']}->{scale['tokens_after']} tok "
            f"({scale['token_count_method']}) | {scale['calls']} calls | "
            f"frio {scale['cold_wall_ms']}ms quente {scale['warm_wall_ms']}ms"
        )
        print(f"  byte-identico frio/quente: {scale['byte_identical_cold_warm']} | "
              f"quente calls={scale['warm_calls']} reused={scale['warm_reused_decisions']}")
        for category, stats in scale["per_category"].items():
            mark = "OK " if stats["recall"] == 1.0 else "LOST"
            print(f"    {mark} {category:20} {stats['kept']}/{stats['total']}")

    print("\n=== stress: casos de borda ===")
    rows = edges()
    for row in rows:
        verdict = "PASS" if row["passed"] else "FAIL"
        detail = ""
        if "report" in row:
            r = row["report"]
            detail = f" red={round(r['reduction_ratio'] * 100, 1)}% dropped={r['blocks_dropped']}"
        if "error" in row:
            detail = f" {row['error'][:80]}"
        print(f"  {row['case']:22} exit={row['exit_code']} {row['input_chars']:>7} -> "
              f"{row.get('output_chars', 0):>7} chars{detail}  {verdict}")

    payload = {"scale": scale, "edges": [{k: v for k, v in r.items() if k != "report"} for r in rows]}
    (OUT / "stress.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    failed = [r["case"] for r in rows if not r["passed"]]
    scale_ok = scale.get("perfect_recall", False) and scale.get("byte_identical_cold_warm", False)
    print(f"\nescala xl: {'OK' if scale_ok else 'PROBLEMA'} | casos de borda: "
          f"{len(rows) - len(failed)}/{len(rows)} passam")
    if failed:
        print(f"falhas: {failed}")
    print(f"-> {OUT / 'stress.json'}")
    raise SystemExit(0 if scale_ok and not failed else 1)


if __name__ == "__main__":
    main()
