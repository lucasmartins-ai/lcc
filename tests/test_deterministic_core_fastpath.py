"""Regression tests for deterministic core fast paths (graph, compactor, specialist, transcript)."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from unittest import mock

import pytest

from lcc.relevance import compactor as compactor_mod
from lcc.relevance.compactor import RelevanceCompactionRequest, compact_context
from lcc.relevance.graph import _STOPWORDS, _WORD_RE, _terms
from lcc.relevance.specialist import load_judge


def _terms_reference(text: str) -> set[str]:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    out: set[str] = set()
    for m in _WORD_RE.finditer(folded):
        t = m.group(0).strip("'")
        if len(t) >= 4 and t not in _STOPWORDS:
            out.add(t)
    return out


@pytest.mark.parametrize(
    "sample",
    [
        "Plain ASCII text with numbers 1234, underscores_here, and contractions don't fail.",
        "Café naïve résumé São Paulo ação coração — mixed unicode and ASCII tokens!",
        "UPPERCASE 'quoted' ''empty'' a bb ccc dddd with that from",
        "",
    ],
)
def test_graph_terms_ascii_fastpath_matches_reference(sample: str):
    assert _terms(sample) == _terms_reference(sample)


def test_compactor_builds_graph_once_with_and_without_cache(tmp_path: Path):
    text = "\n\n".join(
        f"Section {i}: detailed architecture discussion about module_{i} and service_{i % 3} "
        f"including latency, throughput, and dependency constraints for component_{i}."
        for i in range(12)
    )

    with mock.patch.object(
        compactor_mod, "build_graph", wraps=compactor_mod.build_graph
    ) as spy_no_cache:
        compact_context(
            RelevanceCompactionRequest(
                text=text,
                question="What are the latency constraints for module_2?",
                provider="lexical",
                decisions_cache_path=None,
            )
        )
    assert spy_no_cache.call_count == 1

    cache_path = tmp_path / "decisions.sqlite"
    with mock.patch.object(
        compactor_mod, "build_graph", wraps=compactor_mod.build_graph
    ) as spy_cached:
        compact_context(
            RelevanceCompactionRequest(
                text=text,
                question="What are the latency constraints for module_2?",
                provider="lexical",
                decisions_cache_path=cache_path,
            )
        )
    assert spy_cached.call_count == 1


def test_specialist_raw_matches_reference_lr_and_gbdt():
    judge = load_judge()
    # Deterministic synthetic rows matching the model's feature count.
    n_feats = len(judge._lr[0][0]) if judge._lr else 16
    rows = [[float((r * 7 + c * 3) % 11) / 5.0 - 0.8 for c in range(n_feats)] for r in range(25)]
    got = judge.raw(rows)

    # Reference implementation (pre-optimization formula).
    ref = [0.0] * len(rows)
    for mu, sd, beta, b0 in judge._lr:
        for r, x in enumerate(rows):
            ref[r] += sum((x[j] - mu[j]) / sd[j] * beta[j] for j in range(len(beta))) + b0
    for base, trees in judge._gbdt:
        scores = [base] * len(rows)
        for feats, thrs, leaves, depth in trees:
            first_leaf = (1 << depth) - 1
            for r, x in enumerate(rows):
                k = 0
                for _ in range(depth):
                    k = 2 * k + 1 + (x[feats[k]] > thrs[k])
                scores[r] += leaves[k - first_leaf]
        for r, s in enumerate(scores):
            ref[r] += s
    ref = [v / judge.n_members for v in ref]

    assert len(got) == len(ref)
    for a, b in zip(got, ref, strict=True):
        assert a == pytest.approx(b, rel=0.0, abs=1e-12)


def test_specialist_raw_centered_precision_and_trailing_columns():
    from lcc.relevance.specialist import FEATURES, SpecialistJudge

    n = len(FEATURES)
    zeros = [0.0] * n
    ones = [1.0] * n
    mu_big = [1e16] + [0.0] * (n - 1)
    beta_one = [1.0] + [0.0] * (n - 1)
    model = {
        "kind": "v3",
        "alpha": 0.0,
        "k_goal": 0,
        "k_err": 0,
        "bonus": 0.0,
        "members": [
            {
                "kind": "lr",
                "features": list(FEATURES),
                "mu": mu_big,
                "sd": ones,
                "beta": beta_one,
                "b0": 1.0,
            },
            {
                "kind": "lr",
                "features": list(FEATURES),
                "mu": zeros,
                "sd": ones,
                "beta": zeros,
                "b0": 2.0,
            },
            {
                "kind": "lr",
                "features": list(FEATURES),
                "mu": zeros,
                "sd": ones,
                "beta": zeros,
                "b0": 2.0,
            },
        ],
    }
    judge = SpecialistJudge(model)
    # Trailing extra column is ignored; huge mu stays centered; division preserves exact IEEE rounding.
    assert judge.raw([mu_big + [999.0]]) == [5.0 / 3.0]
