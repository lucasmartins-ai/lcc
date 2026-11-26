#!/usr/bin/env python3
"""Arm P: deterministic feature model trained on frozen Jev soft labels (PROTOCOL.md).

    python benchmarks/research/intake-distill-v1/arm_p.py fit --variant v1_pilot [--tau 0.5]
    python benchmarks/research/intake-distill-v1/arm_p.py eval-dev

Fits multinomial logistic regression (pure numpy L-BFGS) on the training pool's sentences with
the teacher's 6-class probability distributions as soft targets. L2 strength is chosen on a 10%
message-level held-out slice (seed 20261127, Amendment 1). Evaluates on dev (Part R's 22) only
and never reads T. Writes weights to p_weights.json and dev aggregates to stats_p_dev.json.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import random
import re
import resource
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import tiktoken

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(HERE), str(REPO / "src")]

import teacher_dev  # noqa: E402
from jev_common import (  # noqa: E402
    CATS,
    KEEP,
    OUT,
    PINS,
    check_pins,
    cohen_kappa,
    per_class_f1,
)

from lcc.intake import objective as v1_objective  # noqa: E402
from lcc.intake import parser as intake_parser  # noqa: E402

CUES_PATH = HERE / "cues.json"
WEIGHTS_PATH = HERE / "p_weights.json"
STATS_DEV_PATH = HERE / "stats_p_dev.json"
SEED_L2 = 20261127
L2_GRID = [1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1, 3e-1, 1.0]
TAU_GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
CUE_CATS = ["pedido", "regra", "entrega", "contexto", "ruido"]

# Amendment 2 item 1: no sentence goes to the stash; `ruido` joins <contexto>.
BRIEF_TAGS = [
    ("pedido_principal", "pedido"),
    ("pedido_lateral", "outros_pedidos"),
    ("entrega", "entrega"),
    ("regra", "regras"),
    ("contexto", "contexto"),
    ("a_confirmar", "a_confirmar"),
]

_WORD_RE = re.compile(r"[^\W\d_]+(?:'[a-z]+)?")
_ENC = tiktoken.get_encoding("o200k_base")


class CueMatcher:
    """Frozen cue-list matcher implementing cues.json's exact fuzzy rule."""

    def __init__(self, cues: dict[str, Any]) -> None:
        self.fuzzy_ratio = float(cues["fuzzy_ratio"])
        self._word_cache: dict[tuple[str, str], bool] = {}
        self.lists: dict[str, list[list[str]]] = {}
        for cat in CUE_CATS:
            parsed: list[list[str]] = []
            for entry in cues[cat]:
                toks = _WORD_RE.findall(entry.lower())
                if toks:
                    parsed.append(toks)
            self.lists[cat] = parsed

    def _match_word(self, cue: str, word: str) -> bool:
        if cue == word:
            return True
        if len(cue) < 5:
            return False
        key = (cue, word)
        hit = self._word_cache.get(key)
        if hit is not None:
            return hit
        # Fast length bound for SequenceMatcher ratio = 2*M / (len1 + len2).
        la, lb = len(cue), len(word)
        if 2 * min(la, lb) / (la + lb) < self.fuzzy_ratio:
            self._word_cache[key] = False
            return False
        m = difflib.SequenceMatcher(None, cue, word, autojunk=False)
        res = m.quick_ratio() >= self.fuzzy_ratio and m.ratio() >= self.fuzzy_ratio
        self._word_cache[key] = res
        return res

    def _phrase_hits(self, phrase: list[str], words: list[str], word_set: set[str]) -> bool:
        if len(phrase) == 1:
            cw = phrase[0]
            if len(cw) < 5:
                return cw in word_set
            return any(self._match_word(cw, w) for w in word_set)
        plen = len(phrase)
        if plen > len(words):
            return False
        for start in range(len(words) - plen + 1):
            if all(self._match_word(phrase[k], words[start + k]) for k in range(plen)):
                return True
        return False

    def hits_per_category(self, words: list[str]) -> list[float]:
        word_set = set(words)
        out: list[float] = []
        for cat in CUE_CATS:
            n = 0
            for phrase in self.lists[cat]:
                if self._phrase_hits(phrase, words, word_set):
                    n += 1
                    if n >= 3:
                        break
            out.append(n / 3.0)
        return out


BASE_FEATURE_NAMES = [
    *(f"cue_{c}" for c in CUE_CATS),
    "role_ask",
    "role_constraint",
    "role_context",
    "ends_question",
    "imp_open",
    "ask_cue",
    "const_open",
    "const_any",
    "rel_pos",
    "is_first",
    "is_last",
    "log_words",
    "rel_len",
    "max_earlier_overlap",
]

FEATURE_NAMES = [
    *(f"prev_{n}" for n in BASE_FEATURE_NAMES),
    *(f"cur_{n}" for n in BASE_FEATURE_NAMES),
    *(f"next_{n}" for n in BASE_FEATURE_NAMES),
    "has_prev",
    "has_next",
]


def extract_message_features(
    text: str, spans: list[list[int]] | list[tuple[int, int]], matcher: CueMatcher
) -> np.ndarray:
    """Compute (n_sentences, n_features) matrix for one message."""
    n = len(spans)
    if n == 0:
        return np.zeros((0, len(FEATURE_NAMES)), dtype=np.float64)

    sents = [text[a:b] for a, b in spans]
    word_lists = [_WORD_RE.findall(s.lower()) for s in sents]
    total_words = max(1, sum(len(w) for w in word_lists))
    content_sets = [{w for w in wl if len(w) >= 3} for wl in word_lists]

    base = np.zeros((n, len(BASE_FEATURE_NAMES)), dtype=np.float64)
    # Inverted index from content word to earlier sentence indices for fast Jaccard overlap.
    seen_in: dict[str, list[int]] = {}
    for i, (sent, words, cset) in enumerate(zip(sents, word_lists, content_sets, strict=True)):
        max_jacc = 0.0
        if cset and i > 0:
            inter_counts: dict[int, int] = {}
            for w in cset:
                for prev_i in seen_in.get(w, ()):
                    inter_counts[prev_i] = inter_counts.get(prev_i, 0) + 1
            len_cur = len(cset)
            for prev_i, inter in inter_counts.items():
                union = len_cur + len(content_sets[prev_i]) - inter
                if union > 0:
                    jacc = inter / union
                    if jacc > max_jacc:
                        max_jacc = jacc
        for w in cset:
            seen_in.setdefault(w, []).append(i)

        cues = matcher.hits_per_category(words)
        ask_cue = intake_parser._ASK_CUE.search(sent) is not None
        role = intake_parser.sentence_role(sent, ask_cue=ask_cue)
        base[i] = [
            *cues,
            float(role == "ask"),
            float(role == "constraint"),
            float(role == "context"),
            float(sent.rstrip().endswith("?")),
            float(intake_parser._IMPERATIVE_OPEN.search(sent) is not None),
            float(ask_cue),
            float(intake_parser._CONSTRAINT_OPEN.search(sent) is not None),
            float(intake_parser._CONSTRAINT_ANYWHERE.search(sent) is not None),
            i / max(1, n - 1),
            float(i == 0),
            float(i == n - 1),
            math.log1p(len(words)),
            len(words) / total_words,
            max_jacc,
        ]

    d = len(BASE_FEATURE_NAMES)
    out = np.zeros((n, 3 * d + 2), dtype=np.float64)
    out[:, d : 2 * d] = base
    if n > 1:
        out[1:, 0:d] = base[:-1]
        out[:-1, 2 * d : 3 * d] = base[1:]
        out[1:, 3 * d] = 1.0
        out[:-1, 3 * d + 1] = 1.0
    return out


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exps = np.exp(shifted)
    return exps / np.sum(exps, axis=1, keepdims=True)


def _loss_and_grad(
    params: np.ndarray, X: np.ndarray, Y: np.ndarray, l2: float
) -> tuple[float, np.ndarray]:
    n, d = X.shape
    k = Y.shape[1]
    W = params[: d * k].reshape(d, k)
    b = params[d * k :]
    logits = X @ W + b
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    log_z = np.log(np.sum(np.exp(shifted), axis=1, keepdims=True))
    log_p = shifted - log_z
    P = np.exp(log_p)

    nll = -float(np.sum(Y * log_p)) / n
    reg = 0.5 * l2 * float(np.sum(W * W))
    diff = (P - Y) / n
    gW = X.T @ diff + l2 * W
    gb = np.sum(diff, axis=0)
    return nll + reg, np.concatenate([gW.ravel(), gb])


def _nll_only(params: np.ndarray, X: np.ndarray, Y: np.ndarray) -> float:
    n, d = X.shape
    k = Y.shape[1]
    W = params[: d * k].reshape(d, k)
    b = params[d * k :]
    logits = X @ W + b
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    log_p = shifted - np.log(np.sum(np.exp(shifted), axis=1, keepdims=True))
    return -float(np.sum(Y * log_p)) / n


def fit_lbfgs(
    X: np.ndarray,
    Y: np.ndarray,
    l2: float,
    *,
    max_iter: int = 200,
    m: int = 10,
    tol: float = 1e-7,
) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic pure-numpy L-BFGS solver for convex soft-target multinomial logistic."""
    _, d = X.shape
    k = Y.shape[1]
    params = np.zeros(d * k + k, dtype=np.float64)
    # Initialize bias to log empirical class prior for fast convergence.
    prior = np.clip(np.mean(Y, axis=0), 1e-6, 1.0)
    params[d * k :] = np.log(prior)

    f, g = _loss_and_grad(params, X, Y, l2)
    s_hist: list[np.ndarray] = []
    y_hist: list[np.ndarray] = []
    rho_hist: list[float] = []

    for _ in range(max_iter):
        gnorm = float(np.linalg.norm(g))
        if gnorm < tol:
            break
        q = g.copy()
        alphas: list[float] = []
        for s, y, rho in zip(reversed(s_hist), reversed(y_hist), reversed(rho_hist), strict=True):
            a = rho * float(np.dot(s, q))
            alphas.append(a)
            q -= a * y
        if y_hist:
            gamma = float(
                np.dot(s_hist[-1], y_hist[-1]) / max(1e-18, np.dot(y_hist[-1], y_hist[-1]))
            )
            r = gamma * q
        else:
            r = q
        for s, y, rho, a in zip(s_hist, y_hist, rho_hist, reversed(alphas), strict=True):
            beta = rho * float(np.dot(y, r))
            r += s * (a - beta)
        direction = -r
        dg = float(np.dot(g, direction))
        if dg >= 0:
            direction = -g
            dg = -float(np.dot(g, g))

        # Armijo backtracking line search.
        step = 1.0
        f_new = f
        g_new = g
        for _ in range(30):
            cand = params + step * direction
            f_new, g_new = _loss_and_grad(cand, X, Y, l2)
            if f_new <= f + 1e-4 * step * dg:
                break
            step *= 0.5
        else:
            break

        s_vec = step * direction
        y_vec = g_new - g
        sy = float(np.dot(s_vec, y_vec))
        if sy > 1e-12:
            if len(s_hist) == m:
                s_hist.pop(0)
                y_hist.pop(0)
                rho_hist.pop(0)
            s_hist.append(s_vec)
            y_hist.append(y_vec)
            rho_hist.append(1.0 / sy)
        params, f, g = params + s_vec, f_new, g_new

    W = params[: d * k].reshape(d, k)
    b = params[d * k :]
    return W, b


def predict_message(
    model: dict[str, Any],
    text: str,
    spans: list[list[int]] | list[tuple[int, int]],
    matcher: CueMatcher,
) -> list[dict[str, Any]]:
    X = extract_message_features(text, spans, matcher)
    if len(X) == 0:
        return []
    mean = np.asarray(model["mean"], dtype=np.float64)
    std = np.asarray(model["std"], dtype=np.float64)
    W = np.asarray(model["W"], dtype=np.float64)
    b = np.asarray(model["b"], dtype=np.float64)
    probs = _softmax(((X - mean) / std) @ W + b)
    cats = model["cats"]
    out: list[dict[str, Any]] = []
    for row in probs:
        top_i = int(np.argmax(row))
        out.append(
            {
                "cat": cats[top_i],
                "p": round(float(row[top_i]), 4),
                "probs": {c: round(float(row[j]), 6) for j, c in enumerate(cats)},
            }
        )
    return out


def assemble_brief(
    text: str,
    spans: list[list[int]] | list[tuple[int, int]],
    preds: list[dict[str, Any]],
    tau: float,
) -> str:
    """Amendment 2 brief: verbatim, input order per section, `ruido` joins <contexto>, 0 dropped."""
    groups: dict[str, list[str]] = {k: [] for k, _ in BRIEF_TAGS}
    for (a, b), pred in zip(spans, preds, strict=True):
        s = text[a:b].strip()
        if not s:
            continue
        if pred["p"] < tau:
            target = "a_confirmar"
        elif pred["cat"] == "ruido":
            target = "contexto"
        else:
            target = pred["cat"]
        groups[target].append(s)
    parts = [
        f"<{tag}>\n" + "\n".join(groups[k]) + f"\n</{tag}>" for k, tag in BRIEF_TAGS if groups[k]
    ]
    return "\n".join(parts)


def _load_pool_dataset(
    variant: str, matcher: CueMatcher, *, single_line_only: bool = False
) -> tuple[list[str], list[np.ndarray], list[np.ndarray]]:
    pool = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))["items"]
    vdir = OUT / "pool_labels" / variant
    ids: list[str] = []
    Xs: list[np.ndarray] = []
    Ys: list[np.ndarray] = []
    for it in pool:
        if single_line_only and it.get("multi_line"):
            continue
        p = vdir / f"{it['id']}.json"
        if not p.is_file():
            raise SystemExit(f"refused: missing pool label for {it['id']}")
        d = json.loads(p.read_text(encoding="utf-8"))
        labels = d["labels"]
        if len(labels) != len(it["sentences"]):
            raise SystemExit(f"refused: sentence mismatch on pool {it['id']}")
        if not labels:
            continue
        X = extract_message_features(it["text"], it["sentences"], matcher)
        Y = np.array([[float(r["probs"][c]) for c in CATS] for r in labels], dtype=np.float64)
        row_sums = np.sum(Y, axis=1, keepdims=True)
        if np.any(row_sums <= 0):
            raise SystemExit(f"refused: zero probability sum on pool {it['id']}")
        Y = Y / row_sums
        ids.append(it["id"])
        Xs.append(X)
        Ys.append(Y)
    return ids, Xs, Ys


def _fit_with_cv(
    ids: list[str], Xs: list[np.ndarray], Ys: list[np.ndarray]
) -> tuple[dict[str, Any], dict[str, Any]]:
    order = sorted(range(len(ids)), key=lambda i: ids[i])
    rng = random.Random(SEED_L2)
    rng.shuffle(order)
    n_val = max(1, int(round(0.10 * len(order))))
    val_idx = set(order[:n_val])
    tr_idx = [i for i in order if i not in val_idx]
    va_idx = [i for i in order if i in val_idx]

    X_tr = np.vstack([Xs[i] for i in tr_idx])
    Y_tr = np.vstack([Ys[i] for i in tr_idx])
    X_va = np.vstack([Xs[i] for i in va_idx])
    Y_va = np.vstack([Ys[i] for i in va_idx])

    mean_tr = np.mean(X_tr, axis=0)
    std_tr = np.std(X_tr, axis=0)
    std_tr = np.where(std_tr < 1e-8, 1.0, std_tr)
    X_tr_s = (X_tr - mean_tr) / std_tr
    X_va_s = (X_va - mean_tr) / std_tr

    cv_scores: dict[str, float] = {}
    best_l2 = L2_GRID[0]
    best_nll = float("inf")
    for l2 in L2_GRID:
        W, b = fit_lbfgs(X_tr_s, Y_tr, l2)
        params = np.concatenate([W.ravel(), b])
        val_nll = _nll_only(params, X_va_s, Y_va)
        cv_scores[str(l2)] = round(val_nll, 6)
        if val_nll < best_nll:
            best_nll = val_nll
            best_l2 = l2

    # Refit on 100% of the training pool with chosen L2.
    X_all = np.vstack(Xs)
    Y_all = np.vstack(Ys)
    mean_all = np.mean(X_all, axis=0)
    std_all = np.std(X_all, axis=0)
    std_all = np.where(std_all < 1e-8, 1.0, std_all)
    W_all, b_all = fit_lbfgs((X_all - mean_all) / std_all, Y_all, best_l2)

    model = {
        "cats": CATS,
        "feature_names": FEATURE_NAMES,
        "l2": best_l2,
        "mean": [round(float(v), 8) for v in mean_all],
        "std": [round(float(v), 8) for v in std_all],
        "W": [[round(float(v), 8) for v in row] for row in W_all],
        "b": [round(float(v), 8) for v in b_all],
        "n_train_messages": len(ids),
        "n_train_sentences": int(len(X_all)),
    }
    cv_info = {
        "seed": SEED_L2,
        "n_train_msgs_cv": len(tr_idx),
        "n_val_msgs_cv": len(va_idx),
        "n_train_sents_cv": int(len(X_tr)),
        "n_val_sents_cv": int(len(X_va)),
        "val_nll_by_l2": cv_scores,
        "best_l2": best_l2,
        "best_val_nll": round(best_nll, 6),
    }
    return model, cv_info


def _eval_on_dev(model: dict[str, Any], matcher: CueMatcher) -> dict[str, Any]:
    items = teacher_dev.dev()
    gold_all: list[str] = []
    pred_all: list[str] = []
    hit_p = 0
    hit_a0 = 0
    hit_d = 0
    latencies_ms: list[float] = []
    per_item_preds: list[list[dict[str, Any]]] = []

    for x in items:
        t0 = time.perf_counter()
        preds = predict_message(model, x["text"], x["spans"], matcher)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        per_item_preds.append(preds)

        pred_cats = [r["cat"] for r in preds]
        mains = [(r["p"], k) for k, r in enumerate(preds) if r["cat"] == "pedido_principal"]
        top_p = max(mains)[1] if mains else None
        hit_p += int(top_p in x["main_r"])

        # Compare A0 and D on the same dev split (exact frozen v1 definitions).
        a = v1_objective.analyse(x["text"])
        asks = [a.spans[i] for i, role in enumerate(a.roles) if role == "ask"]
        a0_span = asks[0] if asks else None
        d_span = v1_objective.choose(a, v1_objective.WEIGHTS).objective_span
        gold_spans = [x["spans"][k] for k in x["main_r"]]

        def _covers(sp: tuple[int, int] | None, gs: list[list[int]] = gold_spans) -> bool:
            if sp is None:
                return False
            return any(min(sp[1], g[1]) - max(sp[0], g[0]) >= (g[1] - g[0]) / 2 for g in gs)

        hit_a0 += int(_covers(a0_span))
        hit_d += int(_covers(d_span))

        gold_all.extend(x["owner"])
        pred_all.extend(pred_cats)

    f1 = per_class_f1(gold_all, pred_all)
    prec_rec: dict[str, dict[str, float | None]] = {}
    for c in CATS:
        tp = sum(g == c and p == c for g, p in zip(gold_all, pred_all, strict=True))
        g_cnt = gold_all.count(c)
        p_cnt = pred_all.count(c)
        prec_rec[c] = {
            "precision": round(tp / p_cnt, 3) if p_cnt else None,
            "recall": round(tp / g_cnt, 3) if g_cnt else None,
            "f1": round(f1[c], 3) if f1[c] is not None else None,
        }

    # Tau sweep on dev (Amendment 2: ruido joins contexto; p < tau goes to <a_confirmar>).
    tau_sweep: list[dict[str, Any]] = []
    for tau in TAU_GRID:
        a_conf_sents = 0
        total_sents = 0
        main_all_ctx = 0
        any_keep_ctx = 0
        keep_sents = 0
        keep_in_ctx = 0
        ratios: list[float] = []
        for x, preds in zip(items, per_item_preds, strict=True):
            total_sents += len(preds)
            a_conf_sents += sum(1 for r in preds if r["p"] < tau)
            filed_ctx = {
                k
                for k, r in enumerate(preds)
                if r["p"] >= tau and r["cat"] in ("contexto", "ruido")
            }
            main_all_ctx += int(all(k in filed_ctx for k in x["main_r"]))
            any_keep_ctx += int(
                any(x["owner"][k] in KEEP and k in filed_ctx for k in range(len(preds)))
            )
            for k in range(len(preds)):
                if x["owner"][k] in KEEP:
                    keep_sents += 1
                    keep_in_ctx += int(k in filed_ctx)
            b = assemble_brief(x["text"], x["spans"], preds, tau)
            ratios.append(len(_ENC.encode(b)) / max(1, len(_ENC.encode(x["text"]))))
        tau_sweep.append(
            {
                "tau": tau,
                "a_confirmar_share": round(a_conf_sents / max(1, total_sents), 4),
                "main_all_in_contexto_msgs": main_all_ctx,
                "any_keep_in_contexto_msgs": any_keep_ctx,
                "keep_sents_in_contexto_share": round(keep_in_ctx / max(1, keep_sents), 4),
                "brief_over_raw_median": round(median(ratios), 4),
            }
        )

    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    return {
        "n_dev": len(items),
        "main_ask_hit1": {"P": hit_p, "A0": hit_a0, "D": hit_d},
        "kappa_vs_owner": round(cohen_kappa(gold_all, pred_all), 4),
        "macro_f1_6": round(sum(f1[c] or 0.0 for c in CATS) / 6, 3),
        "macro_f1_5_no_ruido": round(sum(f1[c] or 0.0 for c in CATS if c != "ruido") / 5, 3),
        "per_class": prec_rec,
        "pred_counts": dict(Counter(pred_all)),
        "latency_ms_median": round(median(latencies_ms), 3),
        "latency_ms_max": round(max(latencies_ms), 3),
        "rss_mb_max": round(rss_mb, 1),
        "tau_sweep": tau_sweep,
    }


def cmd_fit(variant: str, tau: float | None, *, single_line_only: bool = False) -> int:
    check_pins()
    cues = json.loads(CUES_PATH.read_text(encoding="utf-8"))
    matcher = CueMatcher(cues)

    ids, Xs, Ys = _load_pool_dataset(variant, matcher, single_line_only=single_line_only)
    model, cv_info = _fit_with_cv(ids, Xs, Ys)
    dev_stats = _eval_on_dev(model, matcher)

    # Descriptive ablation: the opposite pool filter (PROTOCOL.md line 74).
    ids_alt, Xs_alt, Ys_alt = _load_pool_dataset(
        variant, matcher, single_line_only=not single_line_only
    )
    model_alt, cv_alt = _fit_with_cv(ids_alt, Xs_alt, Ys_alt)
    dev_alt = _eval_on_dev(model_alt, matcher)

    # Pick tau: explicit flag if supplied, else lowest tau with main_all_in_contexto <= 10% on dev.
    if tau is None:
        feasible = [
            row
            for row in dev_stats["tau_sweep"]
            if row["main_all_in_contexto_msgs"] / dev_stats["n_dev"] <= 0.10
        ]
        chosen = min(feasible or dev_stats["tau_sweep"], key=lambda r: r["tau"])
        tau = float(chosen["tau"])

    model["tau"] = tau
    model["single_line_only"] = single_line_only
    model["teacher_variant"] = variant
    model["cues_sha256"] = PINS[CUES_PATH]
    model["parser_sha256"] = PINS[REPO / "src/lcc/intake/parser.py"]

    WEIGHTS_PATH.write_text(json.dumps(model, indent=1) + "\n", encoding="utf-8")
    weights_sha = hashlib.sha256(WEIGHTS_PATH.read_bytes()).hexdigest()

    # Compare against teacher (v1_pilot) macro-F1 on dev for H4 check on dev.
    teacher_dev_stats = json.loads((HERE / "stats_teacher_dev.json").read_text(encoding="utf-8"))
    t_f1_6 = float(teacher_dev_stats["jev"]["macro_f1_6"])
    t_f1_5 = float(teacher_dev_stats["jev"]["macro_f1_5_no_ruido"])

    alt_key = (
        "ablation_full_pool_with_multiline" if single_line_only else "ablation_single_line_only"
    )
    summary = {
        "teacher_variant": variant,
        "single_line_only": single_line_only,
        "weights_sha256": weights_sha,
        "tau": tau,
        "cv": cv_info,
        "dev": dev_stats,
        "dev_vs_teacher": {
            "p_over_teacher_macro_f1_6": round(dev_stats["macro_f1_6"] / max(1e-9, t_f1_6), 3),
            "p_over_teacher_macro_f1_5": round(
                dev_stats["macro_f1_5_no_ruido"] / max(1e-9, t_f1_5), 3
            ),
        },
        alt_key: {
            "n_train_messages": len(ids_alt),
            "n_train_sentences": int(sum(len(x) for x in Xs_alt)),
            "best_l2": cv_alt["best_l2"],
            "main_ask_hit1": dev_alt["main_ask_hit1"]["P"],
            "kappa_vs_owner": dev_alt["kappa_vs_owner"],
            "macro_f1_6": dev_alt["macro_f1_6"],
            "macro_f1_5_no_ruido": dev_alt["macro_f1_5_no_ruido"],
        },
    }
    STATS_DEV_PATH.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def cmd_eval_dev() -> int:
    check_pins()
    cues = json.loads(CUES_PATH.read_text(encoding="utf-8"))
    model = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    stats = _eval_on_dev(model, CueMatcher(cues))
    print(json.dumps(stats, indent=1))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_fit = sub.add_parser("fit")
    p_fit.add_argument("--variant", required=True)
    p_fit.add_argument("--tau", type=float, default=None)
    p_fit.add_argument("--single-line-only", action="store_true")
    sub.add_parser("eval-dev")
    args = parser.parse_args(argv[1:])
    if args.cmd == "fit":
        return cmd_fit(args.variant, args.tau, single_line_only=args.single_line_only)
    return cmd_eval_dev()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
