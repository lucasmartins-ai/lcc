#!/usr/bin/env python3
"""Exploratory pilot for intake-distill-v1 on dev (Part R's 22 dictations): raw prompt against an XML brief.

    python benchmarks/research/intake-distill-v1/pilot_downstream.py

Not part of the pre-registered test: it runs on dev only and never touches T. Steps, each resumable:

1. Jev labels every sentence of each dictation with one of six categories (one request per message).
2. Code assembles a verbatim XML brief: `ruido` is dropped, a low-confidence sentence goes to <a_confirmar>.
3. Antigravity (agy, plan mode, empty folder) answers each dictation twice, raw and as the brief, without
   executing anything: what it understood and what it would deliver.
4. Codex (read-only, empty folder) judges the two answers blind, in random order, against the raw message and the
   owner's Part R gold for the main ask.

Texts and per-message rows stay in ~/.lcc-private/intake-distill-v1/pilot/. Prints aggregates only.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from typing import Any

import tiktoken

from lcc.relevance.jev import JevClient

PRIV = Path.home() / ".lcc-private"
SRC = PRIV / "intake-objective-v1"
OUT = PRIV / "intake-distill-v1" / "pilot"
SEED = 20261125
TAU = 0.5
CHUNK = 10
FEATURE = "lcc_intake_distill_pilot"
CATS = {
    "pedido_principal": "The request the speaker most needs done (or a repeat of it).",
    "pedido_lateral": "Another request, besides the main one.",
    "contexto": "Background the task needs: situation, history, why.",
    "entrega": "What should come out: format, file, place, audience.",
    "regra": "A constraint on how to do it: must, never, only, without, before.",
    "ruido": "Thinking aloud, filler, or a repeat that adds nothing new.",
}
TAGS = [
    ("pedido_principal", "pedido"),
    ("pedido_lateral", "outros_pedidos"),
    ("entrega", "entrega"),
    ("regra", "regras"),
    ("contexto", "contexto"),
    ("a_confirmar", "a_confirmar"),
]
ANSWER = (
    "Você é um agente de código. Abaixo está a mensagem de um usuário. NÃO execute nada, não leia nem altere "
    "arquivos, não use ferramentas. Responda em pt-BR, em no máximo 200 palavras, com estas seções:\n"
    "1. Pedido principal (o que você entendeu que ele mais precisa)\n2. Outros pedidos\n"
    "3. O que você vai entregar\n4. Regras e restrições que vai seguir\n5. Perguntas antes de começar\n\n"
    "<mensagem>\n{msg}\n</mensagem>"
)
JUDGE = (
    "You are grading two answers from a coding agent to the same user message. Do not run anything, do not use "
    "tools. The user wrote MESSAGE. The user later marked GOLD as the sentence(s) holding their main request.\n"
    "Score each answer: main_ask 2 = names the GOLD request, 1 = partly, 0 = misses it; side_asks, delivery and "
    "rules 0-2 = how completely it captures the message's other requests, expected output and constraints; "
    "invented = true if it states a requirement the message does not contain. Then say which answer would serve "
    "the user better.\nReply with JSON only: "
    '{{"X": {{"main_ask": n, "side_asks": n, "delivery": n, "rules": n, "invented": bool}}, '
    '"Y": {{...same...}}, "better": "X" | "Y" | "tie"}}\n\n'
    "<MESSAGE>\n{raw}\n</MESSAGE>\n<GOLD>\n{gold}\n</GOLD>\n<ANSWER_X>\n{x}\n</ANSWER_X>\n<ANSWER_Y>\n{y}\n</ANSWER_Y>"
)
ENC = tiktoken.get_encoding("o200k_base")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def load_dev() -> list[dict[str, Any]]:
    cands = {c["id"]: c for c in json.loads((SRC / "candidates.json").read_text("utf-8"))["items"]}
    out = []
    for d in json.loads((SRC / "labels.json").read_text("utf-8"))["items"]:
        if d.get("decision") != "use":
            continue
        c = cands[d["id"]]
        if sha(c["text"]) != c["sha256"] or d["sha256"] != c["sha256"]:
            raise SystemExit(f"refused: {d['id']} text does not match its label")
        out.append(
            {"id": c["id"], "text": c["text"], "sentences": c["sentences"], "gold": d["gold"]}
        )
    if len(out) != 22:
        raise SystemExit(f"refused: expected Part R's 22 dictations, found {len(out)}")
    return out


def cached(path: Path, make: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    # ponytail: the cache is keyed by message id only; TAU, CATS and the prompts are constants of this
    # one-off pilot, so changing one means deleting the pilot folder first.
    value = make()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), "utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)  # atomic: an interrupted write never leaves a truncated cache file
    return value


def jev_labels(client: JevClient, item: dict[str, Any]) -> list[dict[str, Any]]:
    """One request per CHUNK sentences: the whole message as numbered sentences is the state, and each
    request asks about CHUNK of them, so a long dictation fits System One's context."""
    text = item["text"]
    sents = {f"s{i:02d}": text[a:b] for i, (a, b) in enumerate(item["sentences"])}
    keys = list(sents)
    answers: dict[str, Any] = {}
    for start in range(0, len(keys), CHUNK):
        questions = {
            k: {
                "type": "choice",
                "instructions": f"`sentences` is a message the speaker dictated to an AI coding assistant. "
                f"Which category fits `sentences.{k}`, read in context?",
                "criteria": CATS,
            }
            for k in keys[start : start + CHUNK]
        }
        answers |= client.evaluate({"sentences": sents}, questions)["answers"]
    return [
        {
            "cat": answers[k]["choice"],
            "p": round(float(answers[k]["probabilities"][answers[k]["choice"]]), 4),
        }
        for k in keys
    ]


def brief(item: dict[str, Any], labels: list[dict[str, Any]]) -> tuple[str, int]:
    groups: dict[str, list[str]] = {t: [] for t, _ in TAGS}
    dropped = 0
    for (a, b), lab in zip(item["sentences"], labels, strict=True):
        s = item["text"][a:b].strip()
        if lab["cat"] == "ruido" and lab["p"] >= TAU:
            dropped += 1
            continue
        groups["a_confirmar" if lab["p"] < TAU else lab["cat"]].append(s)
    parts = [f"<{tag}>\n" + "\n".join(groups[k]) + f"\n</{tag}>" for k, tag in TAGS if groups[k]]
    return "\n".join(parts), dropped


def run(cmd: list[str], prompt: str, timeout: int = 900) -> str:
    r = None
    # The scratch folder lives in the private folder, so a CLI's output file never lands in /tmp.
    # ponytail: the prompt goes on argv (visible to this user's `ps`); single-user Mac, accepted.
    with tempfile.TemporaryDirectory(dir=OUT) as d:
        out = Path(d) / "out.txt"
        full = [*cmd, "-o", str(out), prompt] if cmd[0] == "codex" else [*cmd, prompt]
        for attempt in range(3):  # agy and codex fail transiently under load
            out.unlink(missing_ok=True)  # a failed attempt's file never passes as this one's
            try:
                r = subprocess.run(
                    full,
                    cwd=d,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                err = "timeout"
                continue
            text = out.read_text("utf-8") if out.exists() else r.stdout
            if r.returncode == 0 and text.strip():
                return text.strip()
            err = f"stderr {len(r.stderr or '')} chars"  # never the text: it may echo the prompt
            time.sleep(20 * (attempt + 1))
        raise RuntimeError(f"{cmd[0]} exit {getattr(r, 'returncode', None)}: {err}")


def answer(prompt: str) -> str:
    return run(["agy", "--mode", "plan", "-p"], ANSWER.format(msg=prompt))


def judge(raw: str, gold: str, x: str, y: str) -> dict[str, Any]:
    text = run(
        [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "read-only",
            "-c",
            'model_reasoning_effort="medium"',
        ],
        JUDGE.format(raw=raw, gold=gold, x=x, y=y),
    )
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("judge reply has no JSON")
    return valid(json.loads(m.group(0)))


def valid(g: Any) -> dict[str, Any]:
    """The judge's verdict, or an error that names the bad field and never echoes its value."""
    ok = isinstance(g, dict) and g.get("better") in ("X", "Y", "tie")
    for side in ("X", "Y"):
        s = g.get(side) if isinstance(g, dict) else None
        ok = ok and isinstance(s, dict) and isinstance(s.get("invented"), bool)
        ok = ok and all(
            s.get(k) in (0, 1, 2) for k in ("main_ask", "side_asks", "delivery", "rules")
        )
    if not ok:
        raise RuntimeError("judge reply is outside the schema")
    return g


def sign_p(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2**n
    return min(1.0, 2 * tail)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.chmod(0o700)
    items = load_dev()
    # Private ledger: an HTTP error body could echo a sentence, so it never goes to the shared one.
    client = JevClient.from_env(
        ledger_path=OUT.parent / "jev-ledger.jsonl", feature=FEATURE, attempts=2
    )
    if client is None:
        print("refused: no TypeSafe key")
        return 2
    rows = []
    for it in items:  # Jev, sequential and resumable
        labels = cached(OUT / f"{it['id']}.jev.json", lambda it=it: jev_labels(client, it))
        b, dropped = brief(it, labels)
        gold_idx = {i for i, s in enumerate(it["sentences"]) if s in it["gold"]}
        lost = sum(1 for i in gold_idx if labels[i]["cat"] == "ruido" and labels[i]["p"] >= TAU)
        hit = (
            max(
                (i for i, lab in enumerate(labels) if lab["cat"] == "pedido_principal"),
                key=lambda i: labels[i]["p"],
                default=None,
            )
            in gold_idx
        )
        rows.append({"it": it, "brief": b, "dropped": dropped, "lost_gold": lost, "jev_hit": hit})
        (OUT / f"{it['id']}.brief.xml").write_text(b, "utf-8")

    def answers(r: dict[str, Any]) -> dict[str, str]:
        return cached(
            OUT / f"{r['it']['id']}.answers.json",
            lambda: {"raw": answer(r["it"]["text"]), "brief": answer(r["brief"])},
        )

    with ThreadPoolExecutor(2) as pool:
        for r, a in zip(rows, pool.map(answers, rows), strict=True):
            r["answers"] = a

    rng = random.Random(SEED)
    order = [rng.random() < 0.5 for _ in rows]  # True: X is raw

    def graded(args: tuple[dict[str, Any], bool]) -> dict[str, Any]:
        r, raw_first = args
        it, a = r["it"], r["answers"]
        gold = "\n".join(it["text"][s:e] for s, e in it["gold"])
        x, y = (a["raw"], a["brief"]) if raw_first else (a["brief"], a["raw"])
        return cached(
            OUT / f"{it['id']}.judge.json",
            lambda: judge(it["text"], gold, x, y) | {"x_is_raw": raw_first},
        )

    with ThreadPoolExecutor(2) as pool:
        for r, g in zip(rows, pool.map(graded, zip(rows, order, strict=True)), strict=True):
            r["judge"] = valid(g)

    def arm(g: dict[str, Any], name: str) -> dict[str, Any]:
        return g["X"] if (name == "raw") == g["x_is_raw"] else g["Y"]

    stats: dict[str, Any] = {
        "n": len(rows),
        "tau": TAU,
        "answerer": "agy plan mode",
        "judge": "codex exec",
    }
    for name in ("raw", "brief"):
        scores = [arm(r["judge"], name) for r in rows]
        stats[name] = {
            k: round(sum(float(s[k]) for s in scores) / len(scores), 3)
            for k in ("main_ask", "side_asks", "delivery", "rules", "invented")
        } | {"main_ask_full": sum(s["main_ask"] == 2 for s in scores)}
    wins = {"brief": 0, "raw": 0, "tie": 0}
    for r in rows:
        g = r["judge"]
        b = g["better"]
        wins["tie" if b == "tie" else ("raw" if (b == "X") == g["x_is_raw"] else "brief")] += 1
    stats["better"] = wins | {
        "sign_p": round(sign_p(wins["brief"], wins["brief"] + wins["raw"]), 4)
    }
    ratios = [len(ENC.encode(r["brief"])) / len(ENC.encode(r["it"]["text"])) for r in rows]
    stats["tokens"] = {
        "raw_median": median(len(ENC.encode(r["it"]["text"])) for r in rows),
        "brief_over_raw_median": round(median(ratios), 3),
        "brief_over_raw_max": round(max(ratios), 3),
        "saving_median": round(1 - median(ratios), 3),
    }
    stats["loss"] = {
        "messages_losing_a_gold_sentence": sum(r["lost_gold"] > 0 for r in rows),
        "sentences_dropped_total": sum(r["dropped"] for r in rows),
        "jev_main_ask_hit1": sum(r["jev_hit"] for r in rows),
    }
    print(json.dumps(stats, indent=1))
    (Path(__file__).parent / "pilot_downstream_stats.json").write_text(
        json.dumps(stats, indent=1) + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
