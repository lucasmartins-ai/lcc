#!/usr/bin/env python3
"""Label the training pool with the frozen Jev variant (PROTOCOL.md, Run order step 5).

    python benchmarks/research/intake-distill-v1/label_pool.py smoke --variant <name>
    python benchmarks/research/intake-distill-v1/label_pool.py run   --variant <name>
    python benchmarks/research/intake-distill-v1/label_pool.py stats --variant <name>

Leakage check: before any network call, verifies no pool message sha256 matches dev, R3 or T.
Resumable per message under ~/.lcc-private/intake-distill-v1/pool_labels/<variant>/<id>.json (0600).
Writes aggregate counts only to stats_pool_labels.json. Never prints message text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from jev_common import (  # noqa: E402
    CATS,
    OUT,
    PRIV,
    VARIANTS,
    check_pins,
    ensure_private_dir,
    label_message_jev,
    ledger_request_count,
    make_jev_client,
    write_private_json,
)

POOL_LABELS_DIR = OUT / "pool_labels"
STATS_OUT = HERE / "stats_pool_labels.json"
BANDS = [
    ("20-49", 0, 49),
    ("50-99", 50, 99),
    ("100-199", 100, 199),
    ("200+", 200, 10**9),
]


def _load_pool_and_verify_no_leakage() -> list[dict[str, Any]]:
    pool = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))["items"]
    t_items = json.loads((OUT / "t.json").read_text(encoding="utf-8"))["items"]
    dev_c = json.loads((PRIV / "intake-objective-v1/candidates.json").read_text("utf-8"))["items"]
    dev_lab = {
        x["id"]: x["decision"]
        for x in json.loads((PRIV / "intake-objective-v1/labels.json").read_text("utf-8"))["items"]
    }
    r3 = json.loads((PRIV / "intake-objective-v1-r3/candidates.json").read_text("utf-8"))["items"]
    forbidden = (
        {x["sha256"] for x in t_items}
        | {x["sha256"] for x in r3}
        | {x["sha256"] for x in dev_c if dev_lab.get(x["id"]) == "use"}
    )
    seen: set[str] = set()
    for it in pool:
        h = hashlib.sha256(it["text"].encode()).hexdigest()
        if h != it["sha256"]:
            raise SystemExit(f"refused: pool item {it['id']} sha256 mismatch")
        if h in forbidden:
            raise SystemExit(f"refused: pool item {it['id']} leaks dev/R3/T")
        if h in seen:
            raise SystemExit(f"refused: duplicate sha256 in pool ({it['id']})")
        seen.add(h)
    return pool


def _run_slice(variant: str, items: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    vdir = ensure_private_dir(POOL_LABELS_DIR / variant)
    client = make_jev_client(feature)
    t0 = time.perf_counter()
    new_msgs = 0
    cached_msgs = 0
    new_reqs = 0
    errors = 0
    models: set[str] = set()

    for idx, it in enumerate(items, 1):
        path = vdir / f"{it['id']}.json"
        if path.is_file():
            cached_msgs += 1
            continue
        try:
            res = label_message_jev(client, it, variant)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(
                json.dumps(
                    {
                        "error_msg_id": it["id"],
                        "error_type": type(exc).__name__,
                        "done": idx - 1,
                        "ledger_total": ledger_request_count(),
                    }
                ),
                flush=True,
            )
            if "budget exhausted" in str(exc):
                break
            time.sleep(2.0)
            continue
        write_private_json(path, res)
        new_msgs += 1
        new_reqs += res["requests"]
        models.update(res["resolved_models"])
        if new_msgs % 100 == 0:
            elapsed = time.perf_counter() - t0
            print(
                json.dumps(
                    {
                        "progress": f"{idx}/{len(items)}",
                        "new_msgs": new_msgs,
                        "new_reqs": new_reqs,
                        "errors": errors,
                        "req_per_sec": round(new_reqs / max(elapsed, 1e-6), 2),
                        "ledger_total": ledger_request_count(),
                    }
                ),
                flush=True,
            )

    elapsed = time.perf_counter() - t0
    return {
        "variant": variant,
        "target_msgs": len(items),
        "cached_msgs": cached_msgs,
        "new_msgs": new_msgs,
        "new_reqs": new_reqs,
        "errors": errors,
        "elapsed_s": round(elapsed, 2),
        "req_per_sec": round(new_reqs / max(elapsed, 1e-6), 2) if new_reqs else 0.0,
        "resolved_models": sorted(models),
        "ledger_total": ledger_request_count(),
    }


def _band(words: int) -> str:
    for name, lo, hi in BANDS:
        if lo <= words <= hi:
            return name
    return "200+"


def cmd_stats(variant: str) -> int:
    check_pins()
    pool = _load_pool_and_verify_no_leakage()
    vdir = POOL_LABELS_DIR / variant
    total_cats: Counter[str] = Counter()
    by_band: dict[str, Counter[str]] = defaultdict(Counter)
    by_band_msgs: Counter[str] = Counter()
    by_multiline: dict[str, Counter[str]] = {"single_line": Counter(), "multi_line": Counter()}
    labelled_msgs = 0
    missing_msgs = 0
    total_sents = 0
    models: set[str] = set()
    total_reqs = 0

    for it in pool:
        p = vdir / f"{it['id']}.json"
        if not p.is_file():
            missing_msgs += 1
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        rows = d["labels"]
        if len(rows) != len(it["sentences"]):
            raise SystemExit(f"refused: label count mismatch on pool {it['id']}")
        labelled_msgs += 1
        total_reqs += int(d.get("requests", 0))
        models.update(d.get("resolved_models", []))
        band = _band(int(it["words"]))
        by_band_msgs[band] += 1
        ml_key = "multi_line" if it.get("multi_line") else "single_line"
        for r in rows:
            cat = r["cat"]
            total_cats[cat] += 1
            by_band[band][cat] += 1
            by_multiline[ml_key][cat] += 1
            total_sents += 1

    under_200 = [c for c in CATS if total_cats[c] < 200]
    summary = {
        "variant": variant,
        "pool_messages": len(pool),
        "labelled_messages": labelled_msgs,
        "missing_messages": missing_msgs,
        "total_sentences": total_sents,
        "jev_requests_for_pool": total_reqs,
        "ledger_requests_total": ledger_request_count(),
        "resolved_models": sorted(models),
        "counts": {c: total_cats[c] for c in CATS},
        "shares": {c: round(total_cats[c] / max(1, total_sents), 4) for c in CATS},
        "categories_under_200": under_200,
        "by_length_band": {
            name: {
                "messages": by_band_msgs[name],
                "sentences": sum(by_band[name].values()),
                "counts": {c: by_band[name][c] for c in CATS},
            }
            for name, _, _ in BANDS
        },
        "by_multiline": {
            k: {"sentences": sum(v.values()), "counts": {c: v[c] for c in CATS}}
            for k, v in by_multiline.items()
        },
    }
    STATS_OUT.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cmd", choices=["smoke", "run", "stats"])
    parser.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    args = parser.parse_args(argv[1:])

    check_pins()
    if args.cmd == "stats":
        return cmd_stats(args.variant)

    pool = _load_pool_and_verify_no_leakage()
    if args.cmd == "smoke":
        res = _run_slice(args.variant, pool[:20], "lcc_intake_distill_pool_smoke")
        print(json.dumps(res, indent=1))
        return 0 if res["errors"] == 0 else 1

    res = _run_slice(args.variant, pool, "lcc_intake_distill_pool")
    print(json.dumps(res, indent=1))
    cmd_stats(args.variant)
    return 0 if res["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
