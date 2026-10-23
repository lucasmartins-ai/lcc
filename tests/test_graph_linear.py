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
    # kappa* and sigma* sit in n/2 and n/3 blocks (boilerplate); groupNNN and teamNNN in 4
    # blocks each, so the 4 blocks of a group share two terms.
    return [
        (f"b{i}", f"build step kappa{i % 2} sigma{i % 3} group{i // 4:03d} team{i // 4:03d}")
        for i in range(n)
    ]


def test_edges_grow_linearly_with_blocks() -> None:
    n = 600
    graph = build_graph(_boilerplate_session(n), set())
    # Before the cap kappa+sigma linked i = j mod 6: 29,700 SUPPORTS edges, quadratic in n.
    # Now only the groups link: 150 groups * C(4, 2) pairs.
    assert sum(e.type == EdgeType.SUPPORTS for e in graph.edges) == 150 * 6


def _scan_graph(blocks: list[tuple[str, str]], min_shared: int = 2) -> list[tuple[str, ...]]:
    """The edges of the pairwise scan ``build_graph`` replaced (duplicates aside)."""
    occurrences: dict[str, set[str]] = {}
    for bid, txt in blocks:
        for t in graph_module._terms(txt):
            occurrences.setdefault(t, set()).add(bid)
    ceiling = max(2, len(blocks) // 2)
    dterms: dict[str, set[str]] = {bid: set() for bid, _ in blocks}
    for t, bids in occurrences.items():
        if 1 < len(bids) <= ceiling:
            for bid in bids:
                dterms[bid].add(t)

    def why(a: str, b: str) -> str:
        return ",".join(sorted(dterms[a] & dterms[b])[:3])

    out = []
    ids = [bid for bid, _ in blocks]
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if len(dterms[a] & dterms[b]) >= min_shared:
                out.append((b, a, "SUPPORTS", f"link_terms:{why(a, b)}"))
    passes = (
        (graph_module._SUPERSESSION_CUE_RE, 1, 0, "SUPERSEDES", "supersedes_value"),
        (graph_module._QUALIFIER_RE, 2, 80, "QUALIFIES", "qualifies"),
        (graph_module._NEGATION_RE, min_shared, 0, "CONTRADICTS", "negation_shares"),
    )
    for bid, txt in blocks:
        for cue, at_least, min_chars, kind, label in passes:
            if cue.search(txt):
                for other in ids:
                    shared = dterms[bid] & dterms[other]
                    if other != bid and len(shared) >= at_least and len(txt) >= min_chars:
                        out.append((bid, other, kind, f"{label}:{why(bid, other)}"))
                        break
                break
    return out


_CUES = [
    ("c0", "The invoice export runs nightly from the billing worker queue."),
    ("c1", "Revised: the invoice export now runs hourly from the billing worker."),
    ("c2", "However, for invoice export requests the billing worker queue waits on row locks first."),
    ("c3", "However short."),
    ("c4", "The billing worker must not retry the invoice export after a timeout."),
    ("c5", "The ledger reconcile job reads the billing worker output."),
    ("c6", "Never touch the ledger reconcile job by hand, it owns the billing state."),
    *((f"f{i}", f"Unrelated filler paragraph number{i} about weather{i}.") for i in range(6)),
]


@pytest.mark.parametrize("source", ["synthetic", "cues"])
def test_postings_build_matches_the_pairwise_scan(
    source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(graph_module, "MAX_TERM_BLOCKS", 10**9)  # same ceiling as the old scan
    if source == "cues":
        blocks = _CUES
    else:
        text, _ = render_transcript(parse_transcript(synthetic_payload(seed=3, turns=20)))
        blocks = [(b.id, b.text) for b in split_blocks(text)]
    graph = build_graph(blocks, set())
    edges = [
        (e.source, e.target, e.type.value, e.reason)
        for e in graph.edges
        if e.type != EdgeType.DUPLICATES
    ]
    assert edges == _scan_graph(blocks)
    if source == "cues":
        assert {"SUPERSEDES", "QUALIFIES", "CONTRADICTS"} <= {e[2] for e in edges}
