#!/usr/bin/env python3
"""Final test run on T (68 candidates) for intake-distill-v1 (PROTOCOL.md, Amendments 1-3).

    python benchmarks/research/intake-distill-v1/run_test.py

Refuses to run unless:
- Amendment 1 pinned files match their sha256;
- Amendment 3 frozen arm_p.py and p_weights.json match their sha256;
- stats.json does not already exist (final run never overwrites results).

Per-message artifacts stay in ~/.lcc-private/intake-distill-v1/test_run/ (0700/0600, resumable).
Only aggregate statistics are written to stats.json. Never prints message text.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import arm_p  # noqa: E402
from jev_common import (  # noqa: E402
    OUT,
    check_pins,
    ensure_private_dir,
    write_private_json,
)

# Frozen in Amendment 3 (2026-11-26) before any arm touched T.
FROZEN_ARM_P_SHA256 = "a53c4869a16319347ed89728089b4be85016bcb81cb8e2802358887e4167acad"
FROZEN_P_WEIGHTS_SHA256 = "c145a96274b70dcd053287294febb7091e4cd9b2cdde8cc92d444f5065839540"

SEED_XY = 20261125  # Amendment 1: downstream X/Y order keeps the pilot's seed
RUN_DIR = OUT / "test_run"
STATS_OUT = HERE / "stats.json"
ENC = tiktoken.get_encoding("o200k_base")

# Exact answerer prompt from pilot_downstream.py (Amendment 1).
ANSWER_PROMPT = (
    "Você é um agente de código. Abaixo está a mensagem de um usuário. NÃO execute nada, não leia nem altere "
    "arquivos, não use ferramentas. Responda em pt-BR, em no máximo 200 palavras, com estas seções:\n"
    "1. Pedido principal (o que você entendeu que ele mais precisa)\n2. Outros pedidos\n"
    "3. O que você vai entregar\n4. Regras e restrições que vai seguir\n5. Perguntas antes de começar\n\n"
    "<mensagem>\n{msg}\n</mensagem>"
)

# Amendment 2 item 4: pilot_downstream.py judge prompt changed ONLY by dropping owner gold.
JUDGE_ANSWERS_PROMPT = (
    "You are grading two answers from a coding agent to the same user message. Do not run anything, do not use "
    "tools. The user wrote MESSAGE.\n"
    "Score each answer: main_ask 2 = names the message's main request, 1 = partly, 0 = misses it; side_asks, delivery and "
    "rules 0-2 = how completely it captures the message's other requests, expected output and constraints; "
    "invented = true if it states a requirement the message does not contain. Then say which answer would serve "
    "the user better.\nReply with JSON only: "
    '{{"X": {{"main_ask": n, "side_asks": n, "delivery": n, "rules": n, "invented": bool}}, '
    '"Y": {{...same...}}, "better": "X" | "Y" | "tie"}}\n\n'
    "<MESSAGE>\n{raw}\n</MESSAGE>\n<ANSWER_X>\n{x}\n</ANSWER_X>\n<ANSWER_Y>\n{y}\n</ANSWER_Y>"
)

# Amendment 2 item 4 (H2 guard): blind filing audit on raw message + P's brief (no arm name).
JUDGE_H2_PROMPT = (
    "You are auditing a structured brief built from a user's raw message. Do not run anything, do not use tools. "
    "Every sentence of MESSAGE appears verbatim inside one XML section of BRIEF (<pedido>, <outros_pedidos>, "
    "<entrega>, <regras>, <contexto>, <a_confirmar>).\n"
    "Decide whether ANY request (main or secondary), explicit delivery detail, or explicit rule/constraint from "
    "MESSAGE is filed ONLY inside <contexto> (i.e., appears in <contexto> and not in <pedido>, <outros_pedidos>, "
    "<entrega>, <regras>, or <a_confirmar>).\n"
    'Reply with JSON only: {{"misfiled_in_contexto": bool, "kind": "none" | "request" | "delivery" | "rule" | "multiple"}}\n\n'
    "<MESSAGE>\n{raw}\n</MESSAGE>\n<BRIEF>\n{brief}\n</BRIEF>"
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _cached(path: Path, make: Any) -> Any:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    val = make()
    write_private_json(path, val)
    return val


def _run_cli(cmd: list[str], prompt: str, *, timeout: int = 900) -> str:
    r = None
    err = "unknown"
    with tempfile.TemporaryDirectory(dir=RUN_DIR) as d:
        out = Path(d) / "out.txt"
        full = [*cmd, "-o", str(out), prompt] if cmd[0] == "codex" else [*cmd, prompt]
        for attempt in range(3):
            out.unlink(missing_ok=True)
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
                time.sleep(15 * (attempt + 1))
                continue
            text = out.read_text(encoding="utf-8") if out.exists() else r.stdout
            if r.returncode == 0 and text.strip():
                return text.strip()
            err = f"rc={r.returncode} stderr_len={len(r.stderr or '')}"
            time.sleep(20 * (attempt + 1))
        raise RuntimeError(f"{cmd[0]} failed: {err}")


def _answer(prompt: str) -> str:
    return _run_cli(["agy", "--mode", "plan", "-p"], ANSWER_PROMPT.format(msg=prompt))


def _codex_exec(prompt: str) -> str:
    return _run_cli(
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
        prompt,
    )


def _extract_json(text: str) -> Any:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("judge reply has no JSON object")
    return json.loads(m.group(0))


def _valid_answers_judge(g: Any) -> dict[str, Any]:
    ok = isinstance(g, dict) and g.get("better") in ("X", "Y", "tie")
    for side in ("X", "Y"):
        s = g.get(side) if isinstance(g, dict) else None
        ok = ok and isinstance(s, dict) and isinstance(s.get("invented"), bool)
        ok = ok and all(
            type(s.get(k)) is int and s.get(k) in (0, 1, 2)
            for k in ("main_ask", "side_asks", "delivery", "rules")
        )
    if not ok:
        raise RuntimeError("H1/H3 judge reply failed schema check")
    return g


def _valid_h2_judge(g: Any) -> dict[str, Any]:
    ok = (
        isinstance(g, dict)
        and isinstance(g.get("misfiled_in_contexto"), bool)
        and g.get("kind") in ("none", "request", "delivery", "rule", "multiple")
    )
    if not ok:
        raise RuntimeError("H2 judge reply failed schema check")
    return g


def _judge_pair(raw: str, x: str, y: str) -> dict[str, Any]:
    for attempt in range(3):
        try:
            return _valid_answers_judge(
                _extract_json(_codex_exec(JUDGE_ANSWERS_PROMPT.format(raw=raw, x=x, y=y)))
            )
        except (RuntimeError, json.JSONDecodeError):
            if attempt == 2:
                raise
            time.sleep(10)
    raise RuntimeError("unreachable")


def _judge_h2(raw: str, brief: str) -> dict[str, Any]:
    for attempt in range(3):
        try:
            return _valid_h2_judge(
                _extract_json(_codex_exec(JUDGE_H2_PROMPT.format(raw=raw, brief=brief)))
            )
        except (RuntimeError, json.JSONDecodeError):
            if attempt == 2:
                raise
            time.sleep(10)
    raise RuntimeError("unreachable")


def exact_mcnemar_p(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2.0 * n)) / denom
    half = z * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * n)) / n) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _arm_score(g: dict[str, Any], arm: str) -> dict[str, Any]:
    return g["X"] if (arm == "raw") == g["x_is_raw"] else g["Y"]


def _summarise_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}

    # H1: invented requirement (brief vs raw)
    # Discordant: brief_better = raw invented & not brief invented; raw_better = brief invented & not raw invented
    inv_brief_only = 0
    inv_raw_only = 0
    inv_raw_total = 0
    inv_brief_total = 0
    # H3: main_ask fully captured (== 2)
    main_brief_only = 0
    main_raw_only = 0
    main_raw_full = 0
    main_brief_full = 0

    wins = {"brief": 0, "raw": 0, "tie": 0}
    arm_totals: dict[str, dict[str, float]] = {
        "raw": {"main_ask": 0.0, "side_asks": 0.0, "delivery": 0.0, "rules": 0.0},
        "brief": {"main_ask": 0.0, "side_asks": 0.0, "delivery": 0.0, "rules": 0.0},
    }

    for r in rows:
        g = r["judge_answers"]
        sr = _arm_score(g, "raw")
        sb = _arm_score(g, "brief")
        for k in ("main_ask", "side_asks", "delivery", "rules"):
            arm_totals["raw"][k] += float(sr[k])
            arm_totals["brief"][k] += float(sb[k])

        ir, ib = bool(sr["invented"]), bool(sb["invented"])
        inv_raw_total += int(ir)
        inv_brief_total += int(ib)
        if ir and not ib:
            inv_raw_only += 1  # brief wins (did not invent, raw did)
        elif ib and not ir:
            inv_brief_only += 1  # raw wins (brief invented, raw did not)

        mr, mb = (sr["main_ask"] == 2), (sb["main_ask"] == 2)
        main_raw_full += int(mr)
        main_brief_full += int(mb)
        if mb and not mr:
            main_brief_only += 1  # brief wins
        elif mr and not mb:
            main_raw_only += 1  # raw wins

        b = g["better"]
        if b == "tie":
            wins["tie"] += 1
        elif (b == "X") == g["x_is_raw"]:
            wins["raw"] += 1
        else:
            wins["brief"] += 1

    # H2: misfiled in <contexto>
    h2_misfiled = sum(1 for r in rows if r["judge_h2"]["misfiled_in_contexto"])
    h2_lo, h2_hi = wilson_ci(h2_misfiled, n)
    h2_kinds: dict[str, int] = {}
    for r in rows:
        k = r["judge_h2"]["kind"]
        h2_kinds[k] = h2_kinds.get(k, 0) + 1

    ratios = sorted(r["brief_over_raw"] for r in rows)
    p90_idx = min(len(ratios) - 1, int(math.ceil(0.90 * len(ratios))) - 1)
    p_ms = [r["p_ms"] for r in rows]

    return {
        "n": n,
        "H1_invented": {
            "raw_count": inv_raw_total,
            "raw_rate": round(inv_raw_total / n, 4),
            "brief_count": inv_brief_total,
            "brief_rate": round(inv_brief_total / n, 4),
            "discordant_brief_better": inv_raw_only,
            "discordant_raw_better": inv_brief_only,
            "exact_mcnemar_p": round(exact_mcnemar_p(inv_raw_only, inv_brief_only), 6),
        },
        "H2_filing_guard": {
            "misfiled_count": h2_misfiled,
            "misfiled_rate": round(h2_misfiled / n, 4),
            "wilson_95_lo": round(h2_lo, 4),
            "wilson_95_hi": round(h2_hi, 4),
            "passes_le_10pct": (h2_misfiled / n) <= 0.10,
            "kinds": h2_kinds,
        },
        "H3_main_ask_full": {
            "raw_full_count": main_raw_full,
            "raw_full_rate": round(main_raw_full / n, 4),
            "brief_full_count": main_brief_full,
            "brief_full_rate": round(main_brief_full / n, 4),
            "discordant_brief_better": main_brief_only,
            "discordant_raw_better": main_raw_only,
            "exact_mcnemar_p": round(exact_mcnemar_p(main_brief_only, main_raw_only), 6),
        },
        "better": wins | {"sign_p": round(exact_mcnemar_p(wins["brief"], wins["raw"]), 6)},
        "means": {
            arm: {k: round(v / n, 3) for k, v in vals.items()} for arm, vals in arm_totals.items()
        },
        "tokens": {
            "raw_median": median(r["raw_tokens"] for r in rows),
            "brief_median": median(r["brief_tokens"] for r in rows),
            "brief_over_raw_median": round(median(ratios), 4),
            "brief_over_raw_p90": round(ratios[p90_idx], 4),
            "brief_over_raw_max": round(max(ratios), 4),
        },
        "p_latency_ms": {
            "median": round(median(p_ms), 3),
            "max": round(max(p_ms), 3),
        },
    }


def _load_t_and_verify() -> list[dict[str, Any]]:
    t_data = json.loads((OUT / "t.json").read_text(encoding="utf-8"))
    items = t_data["items"]
    if len(items) < 30:
        raise SystemExit(f"refused: T has {len(items)} items (< 30 minimum)")
    pool_shas = {
        x["sha256"] for x in json.loads((OUT / "pool.json").read_text(encoding="utf-8"))["items"]
    }
    for it in items:
        h = _sha(it["text"])
        if h != it["sha256"]:
            raise SystemExit(f"refused: T item {it['id']} sha256 mismatch")
        if h in pool_shas:
            raise SystemExit(f"refused: T item {it['id']} overlaps pool.json")
    return items


def main() -> int:
    if not FROZEN_ARM_P_SHA256 or not FROZEN_P_WEIGHTS_SHA256:
        raise SystemExit(
            "refused: Amendment 3 hashes (FROZEN_ARM_P_SHA256, FROZEN_P_WEIGHTS_SHA256) not set"
        )
    if STATS_OUT.exists():
        raise SystemExit("refused: stats.json already exists; final test runs once")

    check_pins(
        {
            HERE / "arm_p.py": FROZEN_ARM_P_SHA256,
            HERE / "p_weights.json": FROZEN_P_WEIGHTS_SHA256,
        }
    )
    ensure_private_dir(RUN_DIR)

    items = _load_t_and_verify()
    cues = json.loads((HERE / "cues.json").read_text(encoding="utf-8"))
    model = json.loads((HERE / "p_weights.json").read_text(encoding="utf-8"))
    tau = float(model["tau"])
    matcher = arm_p.CueMatcher(cues)

    # Step 1: deterministic arm P briefs for all 68 T items.
    rows: list[dict[str, Any]] = []
    for it in items:
        t0 = time.perf_counter()
        preds = arm_p.predict_message(model, it["text"], it["sentences"], matcher)
        brief = arm_p.assemble_brief(it["text"], it["sentences"], preds, tau)
        p_ms = (time.perf_counter() - t0) * 1000.0
        raw_toks = len(ENC.encode(it["text"]))
        brief_toks = len(ENC.encode(brief))
        write_private_json(
            RUN_DIR / f"{it['id']}.p.json",
            {"id": it["id"], "tau": tau, "p_ms": round(p_ms, 3), "preds": preds},
        )
        rows.append(
            {
                "it": it,
                "brief": brief,
                "p_ms": p_ms,
                "raw_tokens": raw_toks,
                "brief_tokens": brief_toks,
                "brief_over_raw": brief_toks / max(1, raw_toks),
            }
        )
    print(json.dumps({"stage": "briefs_done", "n": len(rows)}), flush=True)

    # Step 2: agy answerer (2 concurrent workers, resumable per message).
    def _do_answers(idx_row: tuple[int, dict[str, Any]]) -> dict[str, str]:
        idx, r = idx_row
        it = r["it"]
        ans = _cached(
            RUN_DIR / f"{it['id']}.answers.json",
            lambda: {"raw": _answer(it["text"]), "brief": _answer(r["brief"])},
        )
        if (idx + 1) % 10 == 0 or (idx + 1) == len(rows):
            print(json.dumps({"stage": "answers", "done": idx + 1, "total": len(rows)}), flush=True)
        return ans

    with ThreadPoolExecutor(max_workers=2) as pool:
        for r, ans in zip(rows, pool.map(_do_answers, enumerate(rows)), strict=True):
            r["answers"] = ans

    # Step 3: Codex blind judges (sequential: 1 Codex job at a time per harness rule).
    rng = random.Random(SEED_XY)
    order = [rng.random() < 0.5 for _ in rows]  # True => X is raw

    for idx, (r, raw_first) in enumerate(zip(rows, order, strict=True), 1):
        it = r["it"]
        a = r["answers"]
        x, y = (a["raw"], a["brief"]) if raw_first else (a["brief"], a["raw"])
        r["judge_answers"] = _valid_answers_judge(
            _cached(
                RUN_DIR / f"{it['id']}.judge_answers.json",
                lambda it=it, x=x, y=y, rf=raw_first: (
                    _judge_pair(it["text"], x, y) | {"x_is_raw": rf}
                ),
            )
        )
        r["judge_h2"] = _valid_h2_judge(
            _cached(
                RUN_DIR / f"{it['id']}.judge_h2.json",
                lambda it=it, b=r["brief"]: _judge_h2(it["text"], b),
            )
        )
        if idx % 10 == 0 or idx == len(rows):
            print(json.dumps({"stage": "judged", "done": idx, "total": len(rows)}), flush=True)

    # Aggregate full T + declared strata (longo vs base) + origins (descriptive).
    all_stats = _summarise_slice(rows)
    base_rows = [r for r in rows if r["it"]["stratum"] != "longo"]
    longo_rows = [r for r in rows if r["it"]["stratum"] == "longo"]
    by_origin: dict[str, Any] = {}
    for orig in sorted({r["it"]["origin"] for r in rows}):
        by_origin[orig] = _summarise_slice([r for r in rows if r["it"]["origin"] == orig])

    h1 = all_stats["H1_invented"]
    h2 = all_stats["H2_filing_guard"]
    h1_pass = bool(
        h2["passes_le_10pct"]
        and h1["brief_count"] < h1["raw_count"]
        and h1["exact_mcnemar_p"] < 0.05
    )

    out = {
        "n": len(rows),
        "seed_xy": SEED_XY,
        "tau": tau,
        "frozen_arm_p_sha256": FROZEN_ARM_P_SHA256,
        "frozen_p_weights_sha256": FROZEN_P_WEIGHTS_SHA256,
        "answerer": "agy --mode plan -p",
        "judge": "codex exec --ephemeral -s read-only -c model_reasoning_effort=medium",
        "verdict": {
            "H2_guard_passes": h2["passes_le_10pct"],
            "H1_primary_passes": h1_pass,
        },
        "all": all_stats,
        "strata": {
            "base": _summarise_slice(base_rows),
            "longo": _summarise_slice(longo_rows),
        },
        "by_origin": by_origin,
    }

    # Refuse overwrite atomically via O_CREAT | O_EXCL.
    fd = os.open(STATS_OUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
