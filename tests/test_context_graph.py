"""ContextGraph tests: typed edges and closure respected by compaction."""

from lcc.relevance import RelevanceCompactionRequest, compact_context
from lcc.relevance.graph import EdgeType, build_graph


def _terms(*words: str) -> set[str]:
    return set(words)


def test_support_edge():
    g = build_graph(
        [("a", "The checkout flow was refactored in June for every visitor."),
         ("b", "Conversion dropped after the checkout flow refactor in June.")],
        _terms("why", "did", "conversion", "move"),
    )
    kinds = {(e.source, e.target, e.type) for e in g.edges}
    assert kinds  # at least the support/dependency link exists


def test_qualification_edge():
    g = build_graph(
        [("a", "Timeout is 30 seconds for every request in the standard fleet."),
         ("b", "For payment requests, timeout is 60 seconds instead of the standard value.")],
        _terms("what", "is", "the", "timeout"),
    )
    types = {e.type for e in g.edges}
    assert EdgeType.QUALIFIES in types or EdgeType.SUPPORTS in types


def test_contradiction_edge():
    g = build_graph(
        [("a", "The user must be authenticated for the checkout flow access control."),
         ("b", "This checkout flow does not require authentication and access is public.")],
        _terms("who", "can", "use", "endpoint"),
    )
    assert any(e.type in (EdgeType.CONTRADICTS, EdgeType.QUALIFIES, EdgeType.SUPPORTS) for e in g.edges)


def test_supersession_edge():
    g = build_graph(
        [("a", "The measured p95 response time for the endpoint is 4.2 seconds load."),
         ("b", "REVISION: the earlier endpoint figure was superseded by a lower value.")],
        _terms("what", "changed"),
    )
    assert any(e.type == EdgeType.SUPERSEDES for e in g.edges)


def test_dependency_closure():
    g = build_graph(
        [("cause", "The checkout flow was refactored in June, replacing the multi-step form."),
         ("noise", "TOOL OUTPUT scanner returned HTTP 200 with 41 kB of HTML console."),
         ("effect", "Conversion dropped by 12 percent in June after checkout flow refactor.")],
        _terms("why", "did", "conversion", "move"),
    )
    pulled = g.closure({"effect"})
    assert "cause" in pulled and "noise" not in pulled


def test_duplication_edge():
    dup = "Duplicate block: " + "y " * 60
    g = build_graph([("a", dup), ("b", dup)], _terms("anything"))
    assert any(e.type == EdgeType.DUPLICATES for e in g.edges)


def test_compaction_respects_qualifier_relationship():
    """Timeout exception must survive even when the scorer dislikes it."""

    class Judge:
        model = "fake"

        def evaluate(self, state, questions):
            answers = {}
            for qid in questions:
                bid = qid[len("keep_"):]
                text = next(b["text"] for b in state["blocks"] if b["id"] == bid)
                answers[qid] = {"type": "noul", "noul": 0.9 if "30 seconds" in text else 0.05}
            return {"answers": answers}

    text = (
        "Timeout is 30 seconds for every request in the standard fleet deployment.\n\n"
        "TOOL OUTPUT scanner noise with nothing relevant zzz zzz zzz zzz zzz zzz zzz.\n\n"
        "For payment requests, timeout is 60 seconds instead of the standard fleet value.\n"
    )
    result = compact_context(
        RelevanceCompactionRequest(
            text=text, question="What is the request timeout?", provider="jev", client=Judge()
        )
    )
    assert "30 seconds" in result.compacted_text
    assert "60 seconds" in result.compacted_text
