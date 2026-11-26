"""Teacher gate on dev (PROTOCOL.md, Teachers and the teacher gate). Prints counts only.

    python teacher_dev.py batches N   -> private opus_batch_{i}.json (sentences + definitions, no gold)
    python teacher_dev.py score       -> stats_teacher_dev.json (aggregates only)

Jev is the pilot's question (variant 1), read from the pilot cache; Opus is one fresh agent per batch that
writes opus_out_{i}.json = {id: [category per sentence]}.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

PRIV = Path.home() / ".lcc-private"
OUT = PRIV / "intake-distill-v1"
HERE = Path(__file__).resolve().parent
TAU = 0.5
CATS = ["pedido_principal", "pedido_lateral", "contexto", "entrega", "regra", "ruido"]
DEFS = {  # the same definitions Jev saw in the pilot
    "pedido_principal": "The request the speaker most needs done (or a repeat of it).",
    "pedido_lateral": "Another request, besides the main one.",
    "contexto": "Background the task needs: situation, history, why.",
    "entrega": "What should come out: format, file, place, audience.",
    "regra": "A constraint on how to do it: must, never, only, without, before.",
    "ruido": "Thinking aloud, filler, or a repeat that adds nothing new.",
}
KEEP = {"pedido_principal", "pedido_lateral", "entrega", "regra"}


def dev() -> list[dict]:
    cands = {
        c["id"]: c
        for c in json.loads((PRIV / "intake-objective-v1/candidates.json").read_text())["items"]
    }
    gold_r = {
        x["id"]: x
        for x in json.loads((PRIV / "intake-objective-v1/labels.json").read_text())["items"]
    }
    labels = json.loads((OUT / "labels_dev.json").read_text())["items"]
    out = []
    for x in labels:
        c = cands[x["id"]]
        spans = [list(s) for s in c["sentences"]]
        owner = ["contexto"] * len(spans)
        for lab in x["labels"]:
            if (
                lab["cat"] not in CATS or lab["span"] not in spans
            ):  # error names the id only, never text
                raise SystemExit(
                    f"refused: {x['id']} has a label that is not a category on a sentence"
                )
            owner[spans.index(lab["span"])] = lab["cat"]
        main_r = {spans.index(list(s)) for s in gold_r[x["id"]]["gold"]}
        out.append(
            {"id": c["id"], "text": c["text"], "spans": spans, "owner": owner, "main_r": main_r}
        )
    if len(out) != 22:
        raise SystemExit(f"refused: {len(out)} dev labels, expected 22")
    return out


def write_private(path: Path, data: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def batches(n: int) -> None:
    items = dev()
    for i in range(n):
        part = items[i::n]
        write_private(
            OUT / f"opus_batch_{i}.json",
            {
                "definitions": DEFS,
                "messages": [
                    {"id": x["id"], "sentences": [x["text"][a:b] for a, b in x["spans"]]}
                    for x in part
                ],
            },
        )
        print(f"batch {i}: {len(part)} messages, {sum(len(x['spans']) for x in part)} sentences")


def f1s(gold: list[str], pred: list[str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for c in CATS:
        tp = sum(g == c and p == c for g, p in zip(gold, pred, strict=True))
        g, p = gold.count(c), pred.count(c)
        out[c] = None if g == 0 and p == 0 else (2 * tp / (g + p))
    return out


def score() -> None:
    items = dev()
    opus: dict[str, list[str]] = {}
    for f in sorted(OUT.glob("opus_out_*.json")):
        part = json.loads(f.read_text())
        if set(part) & set(opus):
            raise SystemExit(f"refused: {f.name} repeats an id of another batch")
        opus.update(part)
    stats = {"n": len(items), "owner_counts": dict(Counter(c for x in items for c in x["owner"]))}
    for name in ("jev", "opus"):
        hit = loss = 0
        gold_all: list[str] = []
        pred_all: list[str] = []
        for x in items:
            if name == "jev":
                j = json.loads((OUT / "pilot" / f"{x['id']}.jev.json").read_text())
                pred = [s["cat"] for s in j]
                mains = [(s["p"], k) for k, s in enumerate(j) if s["cat"] == "pedido_principal"]
                top = max(mains)[1] if mains else None
                stashed = [k for k, s in enumerate(j) if s["cat"] == "ruido" and s["p"] >= TAU]
            else:
                pred = opus[x["id"]]
                top = next((k for k, c in enumerate(pred) if c == "pedido_principal"), None)
                stashed = [k for k, c in enumerate(pred) if c == "ruido"]
            if (
                not isinstance(pred, list)
                or len(pred) != len(x["spans"])
                or any(c not in CATS for c in pred)
            ):
                raise SystemExit(f"refused: {name} {x['id']} labels do not match the sentences")
            hit += top in x["main_r"]
            loss += any(x["owner"][k] in KEEP for k in stashed)
            gold_all += x["owner"]
            pred_all += pred
        f = f1s(gold_all, pred_all)
        present = [v for c, v in f.items() if c != "ruido" and v is not None]
        stats[name] = {
            "main_ask_hit1": hit,
            "loss_messages": loss,
            "loss_rate": round(loss / len(items), 3),
            "f1": {c: (round(v, 3) if v is not None else None) for c, v in f.items()},
            "macro_f1_6": round(sum(v or 0.0 for v in f.values()) / 6, 3),
            "macro_f1_5_no_ruido": round(sum(present) / len(present), 3),
            "pred_counts": dict(Counter(pred_all)),
        }
    path = HERE / "stats_teacher_dev.json"
    path.write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    {"batches": lambda: batches(int(sys.argv[2])), "score": score}[sys.argv[1]]()
