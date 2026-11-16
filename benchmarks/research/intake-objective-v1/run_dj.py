#!/usr/bin/env python3
"""Arm DJ of intake-objective-v1: one Jev choice over D's top five eligible blocks.

    python benchmarks/research/intake-objective-v1/run_dj.py --split dev

Jev reads the whole message and picks the passage that holds the main request among D's top five
eligible blocks, shown in input order. DJ takes Jev's pick when its probability is at least 0.6;
below that, or when the call fails, DJ keeps D's pick. A case with one eligible block makes no call.
The objective is the first ask sentence of the chosen block, as in D. Writes
``results_dj_<split>.json`` with ids, spans, labels and probabilities, never case text, and refuses
to overwrite one: the protocol caps DJ at 700 calls. Each call is one HTTP attempt, and rows go to
``results_dj_<split>.partial.jsonl`` as they are made, so an interrupted run resumes without
asking Jev again. Needs a TypeSafe key.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_arms  # noqa: E402
from run_arms import HERE, WEIGHTS, hit, load  # noqa: E402

from lcc.intake.objective import analyse, choose  # noqa: E402
from lcc.relevance.jev import JevClient, default_ledger_path  # noqa: E402

FEATURE = "lcc_intake_objective_dj"
TOP = 5
THRESHOLD = 0.6
LABELS = "ABCDE"
INSTRUCTIONS = (
    "state.message is a long message someone dictated to an AI assistant. It mixes context, side "
    "errands and thinking aloud with the request the speaker most needs done. Each option is one "
    "passage of the message. Which passage holds that main request?"
)


def dj_pick(client: Any, text: str, a: Any, pick: Any) -> dict[str, Any]:
    """DJ's objective span for one case, with what Jev answered."""
    top = sorted(pick.ranking[:TOP])  # input order, so the options do not carry D's ranking
    out: dict[str, Any] = {
        "span": list(pick.objective_span),
        "called": False,
        "jev": None,
        "p": None,
    }
    if len(top) < 2:
        return out
    options = {LABELS[n]: text[slice(*pick.blocks[i].span)].strip() for n, i in enumerate(top)}
    question = {"main": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": options}}
    out["called"] = True
    try:
        answer = client.evaluate({"message": text}, question)["answers"]["main"]
        label, p = answer["choice"], float(answer["probabilities"][answer["choice"]])
    except Exception as exc:  # noqa: BLE001 - any failure keeps D's pick
        out["error"] = type(exc).__name__
        return out
    if label not in options:
        out["error"] = "label outside the options"
        return out
    out["jev"], out["p"] = label, round(p, 4)
    if p >= THRESHOLD:
        block = pick.blocks[top[LABELS.index(label)]]
        first = next(j for j in block.sentences if a.roles[j] == "ask")
        out["span"] = list(a.spans[first])
    return out


def run(split: str, client: Any, log: Path) -> dict[str, Any]:
    """DJ on every case of ``split``. Each row is appended to ``log`` as soon as it is made, and a
    rerun after an interruption takes the logged rows instead of asking Jev again."""
    done: dict[str, dict[str, Any]] = {}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:  # a line cut by the interruption: that case runs again
                continue
            done[row["id"]] = row
        log.write_text("".join(json.dumps(r) + "\n" for r in done.values()), encoding="utf-8")
    rows = []
    with log.open("a", encoding="utf-8") as out:
        for case in load(split):
            if case["id"] in done:
                rows.append(done[case["id"]])
                continue
            a = analyse(case["text"])
            pick = choose(a, WEIGHTS)
            t0 = time.perf_counter()
            dj = dj_pick(client, case["text"], a, pick)
            row = {
                "id": case["id"],
                "DJ": hit(dj["span"], case["main"]),
                "DJ_span": dj["span"],
                "DJ_ms": round((time.perf_counter() - t0) * 1000, 1),
                **{k: v for k, v in dj.items() if k != "span"},
            }
            if dj["called"]:
                row["model"] = str(getattr(client, "last_resolved_model", "") or "")
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
    calls = [r for r in rows if r["called"]]
    summary = {
        "n": len(rows),
        "DJ_hit": round(sum(r["DJ"] for r in rows) / len(rows), 4),
        "calls": len(calls),
        "errors": sum("error" in r for r in rows),
        "used_jev": sum(r["p"] is not None and r["p"] >= THRESHOLD for r in rows),
        # Every model Jev resolved to, so a model change inside the run shows.
        "model": ",".join(sorted({r["model"] for r in calls if r.get("model")})),
    }
    return {"split": split, "top": TOP, "threshold": THRESHOLD, "rows": rows, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    args = parser.parse_args(argv)
    out = HERE / f"results_dj_{args.split}.json"
    if out.exists():
        print(f"refused: {out.name} exists; DJ runs once per split (700-call cap)")
        return 2
    if args.split == "test" and (
        run_arms._code_sha256() != run_arms.FROZEN_OBJECTIVE_SHA256
        or run_arms.run("dev", WEIGHTS)["summary"]["d_sha256"] != run_arms.FROZEN_D_SHA256
    ):
        print("refused: D is not the frozen D (code or dev output differ from Amendment 2)")
        return 2
    # One HTTP attempt per case: the design allows one call per case, and a failure keeps D's pick.
    client = JevClient.from_env(ledger_path=default_ledger_path(), feature=FEATURE, attempts=1)
    if client is None:
        print("refused: no TypeSafe key or network disabled; DJ without Jev is D")
        return 2
    log = HERE / f"results_dj_{args.split}.partial.jsonl"
    result = run(args.split, client, log)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    log.unlink()
    print(json.dumps(result["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
