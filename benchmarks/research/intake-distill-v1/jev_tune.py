#!/usr/bin/env python3
"""Run and score up to 4 Jev question variants against v1 (pilot) on dev (Part R's 22).

    python benchmarks/research/intake-distill-v1/jev_tune.py smoke
    python benchmarks/research/intake-distill-v1/jev_tune.py run [variant ...]
    python benchmarks/research/intake-distill-v1/jev_tune.py score

Selection order (PROTOCOL.md, Amendment 2):
1. dev loss <= 10% (messages where any owner KEEP sentence is predicted `ruido` with p >= TAU)
2. main-ask hit@1 (highest-p `pedido_principal` sentence in owner's Part R gold)
3. Cohen's kappa against the owner's 6-category dev labels.

Per-message predictions stay in ~/.lcc-private/intake-distill-v1/dev_variants/.
Aggregates only are written to stats_jev_variants.json. Never prints message text.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import teacher_dev  # noqa: E402
from jev_common import (  # noqa: E402
    CATS,
    KEEP,
    OUT,
    TAU_DEFAULT,
    VARIANTS,
    check_pins,
    cohen_kappa,
    ensure_private_dir,
    label_message_jev,
    ledger_request_count,
    make_jev_client,
    per_class_f1,
    write_private_json,
)

DEV_VAR_DIR = OUT / "dev_variants"
STATS_OUT = HERE / "stats_jev_variants.json"

SMOKE_TEXT = (
    "Preciso que você corrija o bug no checkout que trava no Pix. "
    "Ontem perdemos cinco vendas por causa disso. "
    "Não mexa no módulo de cartão de crédito. "
    "Me devolve um resumo em markdown no final."
)


def cmd_smoke() -> int:
    check_pins()
    client = make_jev_client("lcc_intake_distill_smoke")
    # Build 25 synthetic sentences to verify batching works cleanly on System One.
    sents = [
        "Preciso que você corrija o bug no checkout que trava no Pix.",
        "Ontem perdemos cinco vendas por causa disso.",
        "Não mexa no módulo de cartão de crédito.",
        "Me devolve um resumo em markdown no final.",
    ] + [f"No servidor de teste o erro apareceu na tentativa {i}." for i in range(1, 22)]
    text = " ".join(sents)
    spans: list[list[int]] = []
    pos = 0
    for s in sents:
        spans.append([pos, pos + len(s)])
        pos += len(s) + 1
    item = {"id": "smoke_synth", "text": text, "sentences": spans}
    t0 = time.perf_counter()
    res = label_message_jev(client, item, "v2_owner_prior_en", max_q=30)
    ms = int((time.perf_counter() - t0) * 1000)
    print(
        json.dumps(
            {
                "smoke": "ok",
                "sentences": len(spans),
                "requests": res["requests"],
                "resolved_models": res["resolved_models"],
                "latency_ms": ms,
                "first4_cats": [r["cat"] for r in res["labels"][:4]],
                "ledger_total": ledger_request_count(),
            },
            indent=1,
        )
    )
    return 0


def cmd_run(names: list[str]) -> int:
    check_pins()
    targets = names or [k for k in VARIANTS if k != "v1_pilot"]
    for name in targets:
        if name not in VARIANTS:
            raise SystemExit(f"unknown variant: {name}")
    items = teacher_dev.dev()
    client = make_jev_client("lcc_intake_distill_dev_tune")
    t_start = time.perf_counter()
    for name in targets:
        vdir = ensure_private_dir(DEV_VAR_DIR / name)
        done = 0
        calls = 0
        for x in items:
            cache_path = vdir / f"{x['id']}.json"
            if cache_path.is_file():
                done += 1
                continue
            res = label_message_jev(client, x, name)
            write_private_json(cache_path, res)
            done += 1
            calls += res["requests"]
        print(
            json.dumps(
                {
                    "variant": name,
                    "messages_done": done,
                    "new_requests": calls,
                    "resolved_model": client.last_resolved_model,
                    "ledger_total": ledger_request_count(),
                    "elapsed_s": round(time.perf_counter() - t_start, 1),
                }
            )
        )
    return 0


def _score_one(name: str, items: list[dict[str, Any]], get_rows: Any) -> dict[str, Any]:
    hit = 0
    ruido_loss = 0
    main_all_context = 0
    keep_any_context = 0
    gold_all: list[str] = []
    pred_all: list[str] = []
    models: set[str] = set()
    total_reqs = 0

    for x in items:
        rows, reqs, rmodels = get_rows(x)
        total_reqs += reqs
        models.update(rmodels)
        pred = [r["cat"] for r in rows]
        if len(pred) != len(x["spans"]) or any(c not in CATS for c in pred):
            raise SystemExit(f"refused: {name} {x['id']} does not match sentence count/categories")
        mains = [(r["p"], k) for k, r in enumerate(rows) if r["cat"] == "pedido_principal"]
        top = max(mains)[1] if mains else None
        hit += int(top in x["main_r"])
        stashed = [k for k, r in enumerate(rows) if r["cat"] == "ruido" and r["p"] >= TAU_DEFAULT]
        ruido_loss += int(any(x["owner"][k] in KEEP for k in stashed))
        # Descriptive filing diagnostics (Amendment 2: ruido joins contexto).
        filed_ctx = {k for k, c in enumerate(pred) if c in ("contexto", "ruido")}
        main_all_context += int(all(k in filed_ctx for k in x["main_r"]))
        keep_any_context += int(
            any(x["owner"][k] in KEEP and k in filed_ctx for k in range(len(pred)))
        )
        gold_all.extend(x["owner"])
        pred_all.extend(pred)

    f1 = per_class_f1(gold_all, pred_all)
    f1_5 = [f1[c] or 0.0 for c in CATS if c != "ruido"]
    kappa = cohen_kappa(gold_all, pred_all)
    loss_rate = ruido_loss / len(items)
    return {
        "eligible_loss_le_10pct": loss_rate <= 0.10,
        "main_ask_hit1": hit,
        "main_ask_hit1_rate": round(hit / len(items), 3),
        "dev_loss_messages": ruido_loss,
        "dev_loss_rate": round(loss_rate, 3),
        "kappa_vs_owner": round(kappa, 4),
        "_kappa_raw": kappa,
        "macro_f1_6": round(sum(f1[c] or 0.0 for c in CATS) / 6, 3),
        "macro_f1_5_no_ruido": round(sum(f1_5) / 5, 3),
        "f1": {c: (round(v, 3) if v is not None else None) for c, v in f1.items()},
        "pred_counts": dict(Counter(pred_all)),
        "main_all_filed_contexto_msgs": main_all_context,
        "any_keep_filed_contexto_msgs": keep_any_context,
        "requests": total_reqs,
        "resolved_models": sorted(models),
    }


def cmd_score() -> int:
    check_pins()
    items = teacher_dev.dev()
    results: dict[str, dict[str, Any]] = {}

    # v1 (pilot, already cached)
    results["v1_pilot"] = _score_one(
        "v1_pilot",
        items,
        lambda x: (json.loads((OUT / "pilot" / f"{x['id']}.jev.json").read_text()), 0, []),
    )

    for name in VARIANTS:
        if name == "v1_pilot":
            continue
        vdir = DEV_VAR_DIR / name
        if not all((vdir / f"{x['id']}.json").is_file() for x in items):
            continue

        def _load(
            x: dict[str, Any], vd: Path = vdir
        ) -> tuple[list[dict[str, Any]], int, list[str]]:
            d = json.loads((vd / f"{x['id']}.json").read_text())
            return d["labels"], int(d.get("requests", 0)), list(d.get("resolved_models", []))

        results[name] = _score_one(name, items, _load)

    # Selection order (Amendment 2): dev_loss <= 10%, then main_ask_hit1, then unrounded kappa.
    eligible = [(name, r) for name, r in results.items() if r["eligible_loss_le_10pct"]]
    winner = (
        max(
            eligible,
            key=lambda kv: (kv[1]["main_ask_hit1"], kv[1]["_kappa_raw"]),
        )[0]
        if eligible
        else None
    )
    for r in results.values():
        r.pop("_kappa_raw", None)

    summary = {
        "n_dev": len(items),
        "tau": TAU_DEFAULT,
        "selection_rule": "dev_loss <= 10%, then main_ask_hit1, then kappa_vs_owner",
        "winner": winner,
        "ledger_requests_total": ledger_request_count(),
        "variants": results,
    }
    STATS_OUT.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: jev_tune.py smoke | run [variants...] | score")
    cmd = argv[1]
    if cmd == "smoke":
        return cmd_smoke()
    if cmd == "run":
        return cmd_run(argv[2:])
    if cmd == "score":
        return cmd_score()
    raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
