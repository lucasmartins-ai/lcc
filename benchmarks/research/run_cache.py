#!/usr/bin/env python3
"""KV/prompt-cache safety experiments for `lcc compact`.

Answers three concrete questions with measurements, not claims:

  Q1  Is a warm run byte-stable?           cold run vs run with a populated decisions cache
  Q2  Does prefix protection actually hold? unprotected vs --prefix-marker, compare
                                            first_mutation_offset against the marker offset
  Q3  Does compaction ever pay for itself against a warm cache? apply the cost model from
                                            docs/CACHE_ALIGNMENT.md to the measured offsets

Also captures the worth_it / min-reduction gate and the append-only growth case.

Cost model (from docs/CACHE_ALIGNMENT.md, using its own factors):
    cache read  = 0.10x base token price
    cache write = 1.25x base token price
  saving  = dropped_tokens * read_factor * reuse_count
  penalty = invalidated_tokens * (write_factor - read_factor)
  verdict = saving - penalty   (positive => the mutation pays for itself)
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent
CORPORA = ROOT / "corpora"
WORK = ROOT / "work_cache"
OUT = ROOT / "results"
MARKER = "<!-- lcc:cache-break -->"
OBJECTIVE = "What is the measured mobile conversion problem for the clinic?"
READ_FACTOR = 0.10
WRITE_FACTOR = 1.25


def exact_tokens(text: str) -> int:
    import tiktoken

    return len(tiktoken.get_encoding("o200k_base").encode(text))


def compact(src: pathlib.Path, dest: pathlib.Path, *, extra: list[str] | None = None,
            tag: str = "") -> tuple[dict, str]:
    rep = dest.with_suffix(".report.json")
    cmd = ["lcc", "compact", str(src), "-q", OBJECTIVE, "--provider", "jev",
           "-o", str(dest), "-r", str(rep), *(extra or [])]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall = int((time.time() - started) * 1000)
    if proc.returncode != 0:
        raise RuntimeError(f"{tag}: {(proc.stderr or proc.stdout)[-400:]}")
    report = json.loads(rep.read_text())
    report["_wall_ms"] = wall
    report["_output_path"] = str(dest)
    return report, dest.read_text(encoding="utf-8")


def invalidation(report: dict, text_in: str) -> dict:
    """Tokens left of the mutation point stay cached; everything to its right is recomputed."""
    offset = report.get("first_mutation_offset")
    if offset is None:
        return {"invalidated_tokens": 0, "prefix_tokens": exact_tokens(text_in)}
    prefix = text_in[:offset]
    prefix_tokens = exact_tokens(prefix)
    total = exact_tokens(text_in)
    return {
        "invalidated_tokens": total - prefix_tokens,
        "prefix_tokens": prefix_tokens,
        "total_tokens": total,
    }


def economics(report: dict, text_in: str, reuse_count: int = 1) -> dict:
    inv = invalidation(report, text_in)
    dropped = max(0, report["tokens_before"] - report["tokens_after"])
    saving = dropped * READ_FACTOR * reuse_count
    penalty = inv["invalidated_tokens"] * (WRITE_FACTOR - READ_FACTOR)
    net = saving - penalty
    return {
        "dropped_tokens": dropped,
        "invalidated_tokens": inv["invalidated_tokens"],
        "reuse_count": reuse_count,
        "saving_read_equiv": round(saving, 1),
        "penalty_read_equiv": round(penalty, 1),
        "net_read_equiv": round(net, 1),
        "pays_off": net > 0,
        "ratio_penalty_over_saving": (
            round(penalty / saving, 2) if saving else None
        ),
    }


def _scales() -> list[str]:
    """Corpora for the full cache suite.

    Deliberately stops at `large`: this suite runs about ten scored passes per corpus, and the
    `xl` stress scale is checked separately by `stress_edges.py` with a single cold/warm pair.
    """
    index = json.loads((CORPORA / "index.json").read_text(encoding="utf-8"))
    return [scale for scale in ("small", "medium", "large") if scale in index]


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    findings: dict = {}

    for scale in _scales():
        pass
        src = CORPORA / f"{scale}.md"
        original = src.read_text(encoding="utf-8")
        sdir = WORK / scale
        sdir.mkdir(parents=True)
        entry: dict = {"scale": scale, "tokens_in": exact_tokens(original)}

        # ---- Q1: cold vs warm decisions cache -------------------------------------------
        cache = sdir / "decisions.jsonl"
        cold_rep, cold_out = compact(src, sdir / "cold.md",
                                     extra=["--decisions-cache", str(cache)], tag="cold")
        warm_rep, warm_out = compact(src, sdir / "warm.md",
                                     extra=["--decisions-cache", str(cache)], tag="warm")
        entry["q1_cold_vs_warm"] = {
            "cold": {k: cold_rep.get(k) for k in
                     ("calls", "reused_decisions", "output_sha256", "token_count_method")},
            "warm": {k: warm_rep.get(k) for k in
                     ("calls", "reused_decisions", "output_sha256", "token_count_method")},
            "byte_identical": cold_out == warm_out,
            "sha_match": cold_rep["output_sha256"] == warm_rep["output_sha256"],
        }

        # ---- determinism with no cache at all -------------------------------------------
        d1_rep, d1_out = compact(src, sdir / "det1.md", tag="det1")
        d2_rep, d2_out = compact(src, sdir / "det2.md", tag="det2")
        entry["determinism_no_cache"] = {
            "byte_identical": d1_out == d2_out,
            "sha_match": d1_rep["output_sha256"] == d2_rep["output_sha256"],
        }

        # ---- Q2: prefix protection ------------------------------------------------------
        unprotected_rep, _ = compact(src, sdir / "unprot.md", tag="unprot")
        marker_offset = original.index(MARKER) + len(MARKER)
        protected_rep, protected_out = compact(
            src, sdir / "prot.md", extra=["--prefix-marker", MARKER], tag="prot"
        )
        entry["q2_prefix_protection"] = {
            "marker_offset_chars": marker_offset,
            "unprotected_first_mutation_offset": unprotected_rep.get("first_mutation_offset"),
            "protected_first_mutation_offset": protected_rep.get("first_mutation_offset"),
            "protected_prefix_untouched": protected_rep.get("prefix_untouched"),
            "protected_prefix_protected": protected_rep.get("prefix_protected"),
            "protected_blocks_protected": protected_rep.get("blocks_protected"),
            "protected_sha": protected_rep.get("output_sha256"),
            "unprotected_sha": unprotected_rep.get("output_sha256"),
            "protection_changed_output": protected_rep.get("output_sha256")
            != unprotected_rep.get("output_sha256"),
        }

        # ---- Q3: economics at 1x / 5x / 20x reuse ---------------------------------------
        entry["q3_economics"] = {
            "unprotected": {r: economics(unprotected_rep, original, r) for r in (1, 5, 20)},
            "protected": {r: economics(protected_rep, original, r) for r in (1, 5, 20)},
            "unprotected_reduction_ratio": unprotected_rep.get("reduction_ratio"),
            "unprotected_worth_it": unprotected_rep.get("worth_it"),
            "protected_worth_it": protected_rep.get("worth_it"),
        }

        # ---- append-only growth: does the old output stay a byte-stable prefix? ---------
        grown_path = sdir / "grown.md"
        grown_path.write_text(
            original + "\n\nTOOL OUTPUT 999: fresh audit result appended after the last epoch.\n",
            encoding="utf-8",
        )
        grow_rep, grow_out = compact(grown_path, sdir / "grown_out.md",
                                     extra=["--decisions-cache", str(cache)], tag="grow")
        warm_prefix_kept = grow_out.startswith(warm_out.rstrip("\n"))
        entry["append_only"] = {
            "output_extends_warm_prefix": warm_prefix_kept,
            "calls": grow_rep.get("calls"),
            "reused_decisions": grow_rep.get("reused_decisions"),
            "added_tokens": exact_tokens(grow_out) - exact_tokens(warm_out),
        }

        # ---- worth_it gate ---------------------------------------------------------------
        strict_rep, _ = compact(src, sdir / "minred80.md",
                               extra=["--min-reduction", "0.8"], tag="minred80")
        entry["worth_it_gate"] = {
            "default_min_reduction": unprotected_rep.get("min_reduction"),
            "default_worth_it": unprotected_rep.get("worth_it"),
            "min_reduction_0.8_worth_it": strict_rep.get("worth_it"),
            "reduction_ratio": strict_rep.get("reduction_ratio"),
            "warnings": strict_rep.get("warnings"),
        }

        findings[scale] = entry
        print(f"[{scale}] "
              f"warm_identical={entry['q1_cold_vs_warm']['byte_identical']} "
              f"warm_calls={entry['q1_cold_vs_warm']['warm']['calls']} "
              f"unprot_first_mutation={entry['q2_prefix_protection']['unprotected_first_mutation_offset']} "
              f"prot_first_mutation={entry['q2_prefix_protection']['protected_first_mutation_offset']} "
              f"prot_untouched={entry['q2_prefix_protection']['protected_prefix_untouched']}")

    (OUT / "cache_safety.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT / 'cache_safety.json'}")


if __name__ == "__main__":
    main()
