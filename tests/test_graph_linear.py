"""``build_graph`` stays linear on a long session whose blocks share boilerplate vocabulary.

A real 60 MB Claude Code session (4,604 blocks) built 2.9M SUPPORTS edges twice per ``auto``
compaction: 30 s and 2.2 GB on its own, 1,276 s with every core measuring other sessions.
The shape: many tool results that repeat the same few identifiers, each in under half the
blocks, so the relative ceiling called them distinctive and linked nearly every pair.
"""

from __future__ import annotations

import pytest

from lcc.relevance import graph as graph_module
from lcc.relevance.blocks import split_blocks
from lcc.relevance.graph import EdgeType, build_graph
from lcc.relevance.specialist import render_transcript
from lcc.relevance.transcript import parse_transcript
from specialist_synthetic import synthetic_payload


def _boilerplate_session(n: int) -> list[tuple[str, str]]:
    # kappa* and sigma* each sit in n/2 and n/3 blocks; blocks i, j share both when i = j mod 6.
    return [(f"b{i}", f"build step kappa{i % 2} sigma{i % 3} unique{i:05d}") for i in range(n)]


def test_edges_grow_linearly_with_blocks() -> None:
    n = 600
    graph = build_graph(_boilerplate_session(n), set())
    # Before the cap: 6 * C(100, 2) = 29,700 SUPPORTS edges, quadratic in n.
    assert len(graph.edges) <= 2 * n


def _pairwise_supports(blocks: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """The scan ``build_graph`` replaced: every pair, >= 2 shared distinctive terms."""
    occurrences: dict[str, set[str]] = {}
    for bid, txt in blocks:
        for t in graph_module._terms(txt):
            occurrences.setdefault(t, set()).add(bid)
    ceiling = max(2, len(blocks) // 2)
    dterms = {bid: set() for bid, _ in blocks}
    for t, bids in occurrences.items():
        if 1 < len(bids) <= ceiling:
            for bid in bids:
                dterms[bid].add(t)
    out = []
    ids = [bid for bid, _ in blocks]
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            common = dterms[a] & dterms[b]
            if len(common) >= 2:
                out.append((b, a, "link_terms:" + ",".join(sorted(common)[:3])))
    return out


def test_postings_build_matches_the_pairwise_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "MAX_TERM_BLOCKS", 10**9)  # same ceiling as the old scan
    text, _ = render_transcript(parse_transcript(synthetic_payload(seed=3, turns=20)))
    blocks = [(b.id, b.text) for b in split_blocks(text)]
    graph = build_graph(blocks, set())
    supports = [(e.source, e.target, e.reason) for e in graph.edges if e.type == EdgeType.SUPPORTS]
    assert supports
    assert supports == _pairwise_supports(blocks)
