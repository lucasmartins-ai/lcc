"""``ContextGraph.edges_touching`` uses a per-block index; it must match the linear scan."""

from __future__ import annotations

from lcc.relevance.blocks import split_blocks
from lcc.relevance.graph import ContextGraph, EdgeType, GraphEdge, build_graph
from lcc.relevance.specialist import render_transcript
from lcc.relevance.transcript import parse_transcript
from specialist_synthetic import synthetic_payload


def _scan(graph: ContextGraph, block_id: str) -> list[GraphEdge]:
    return [e for e in graph.edges if e.source == block_id or e.target == block_id]


def test_index_matches_linear_scan_on_a_synthetic_transcript() -> None:
    text, _ = render_transcript(parse_transcript(synthetic_payload(seed=11, turns=40)))
    blocks = [(b.id, b.text) for b in split_blocks(text)]
    graph = build_graph(blocks, set())
    assert graph.edges
    for bid in [*graph.nodes, "missing"]:
        assert graph.edges_touching(bid) == _scan(graph, bid)


def test_self_loop_is_listed_once_and_constructor_edges_are_indexed() -> None:
    loop = GraphEdge(source="a", target="a", type=EdgeType.DEPENDS_ON)
    ab = GraphEdge(source="a", target="b", type=EdgeType.SUPPORTS)
    graph = ContextGraph(edges=[ab, loop])
    graph.add_edge(GraphEdge(source="b", target="a", type=EdgeType.QUALIFIES))
    for bid in ("a", "b", "c"):
        assert graph.edges_touching(bid) == _scan(graph, bid)
    assert graph.edges_touching("a").count(loop) == 1
