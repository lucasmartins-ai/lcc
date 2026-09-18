"""Typed context graph: relationships between blocks as explicit edges.

The previous dependency logic (shared distinctive vocabulary) was a useful heuristic,
not a semantic model. This module represents it explicitly so policy can reason about
*why* two blocks are linked instead of accumulating more regex rules.

Nodes are block ids. Edges are typed::

    SUPPORTS / DEPENDS_ON / QUALIFIES / CONTRADICTS / SUPERSEDES / DUPLICATES / DERIVED_FROM

Construction is deliberately conservative and deterministic today (lexical links +
supersession cues + exact duplicates + negation/qualifier cues); a Jev-assisted pass
can add edges later through :meth:`ContextGraph.add_edge`. Compaction only needs two
operations: ``edges_touching(kept)`` and ``closure(kept_ids)``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum

RELATIONSHIP_VERSION = "relationships-1.0"


class EdgeType(StrEnum):
    SUPPORTS = "SUPPORTS"
    QUALIFIES = "QUALIFIES"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"
    DEPENDS_ON = "DEPENDS_ON"
    DUPLICATES = "DUPLICATES"
    DERIVED_FROM = "DERIVED_FROM"


@dataclass(frozen=True)
class GraphEdge:
    source: str  # dependent / qualifying / newer block
    target: str  # block it relates to
    type: EdgeType
    confidence: float = 0.7
    reason: str = ""


@dataclass
class ContextGraph:
    nodes: set[str] = field(default_factory=set)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_edge(self, edge: GraphEdge) -> None:
        self.nodes.add(edge.source)
        self.nodes.add(edge.target)
        self.edges.append(edge)

    def edges_touching(self, block_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.source == block_id or e.target == block_id]

    def neighbours_of(self, kept_ids: set[str]) -> dict[str, GraphEdge]:
        """Blocks linked to any kept block, mapped to their strongest edge."""
        out: dict[str, GraphEdge] = {}
        for edge in self.edges:
            if edge.target in kept_ids and edge.source not in kept_ids:
                prev = out.get(edge.source)
                if prev is None or edge.confidence > prev.confidence:
                    out[edge.source] = edge
            elif edge.source in kept_ids and edge.target not in kept_ids:
                prev = out.get(edge.target)
                if prev is None or edge.confidence > prev.confidence:
                    out[edge.target] = edge
        return out

    def closure(self, kept_ids: set[str], *, max_hops: int = 1) -> dict[str, str]:
        """Pull in blocks linked to kept blocks; returns ``{block_id: reason}``."""
        pulled: dict[str, str] = {}
        seen = set(kept_ids)
        frontier = set(kept_ids)
        for _ in range(max(0, max_hops)):
            nxt: dict[str, GraphEdge] = {}
            for edge in self.edges:
                if edge.target in frontier and edge.source not in seen and (
                    edge.source not in nxt or edge.confidence > nxt[edge.source].confidence
                ):
                    nxt[edge.source] = edge
                elif edge.source in frontier and edge.target not in seen and (
                    edge.target not in nxt or edge.confidence > nxt[edge.target].confidence
                ):
                    nxt[edge.target] = edge
            if not nxt:
                break
            frontier = set()
            for block_id, edge in nxt.items():
                if edge.reason:
                    pulled[block_id] = f"{edge.type.value.lower()}:{edge.reason}"
                else:
                    pulled[block_id] = edge.type.value.lower()
                seen.add(block_id)
                frontier.add(block_id)
        return pulled


_SUPERSESSION_CUE_RE = re.compile(
    r"\b(?:revised|revision|superseded|supersedes|corrected|correction|amended|amendment|"
    r"restated|restatement|down from|up from|deprecated|supersede)\b",
    re.IGNORECASE,
)
_QUALIFIER_RE = re.compile(
    r"\b(except|exception|unless|however|but |although|though|nevertheless|"
    r"for payment|for .* requests?,|normally|generally|in general)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"\b(not|no\b|never|n't\b|without|forbidden|prohibited|must not|do not|don't|cannot|can't)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?")
_STOPWORDS = frozenset(
    {"about", "after", "also", "and", "are", "can", "for", "from", "has", "have", "how",
     "into", "its", "our", "should", "that", "the", "their", "this", "was", "what", "when",
     "where", "which", "who", "why", "with"}
)


def _terms(text: str) -> set[str]:
    out: set[str] = set()
    for m in _WORD_RE.finditer(text.lower()):
        t = m.group(0).strip("'")
        if len(t) >= 4 and t not in _STOPWORDS:
            out.add(t)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_graph(
    blocks: list[tuple[str, str]],
    question_terms: set[str],
    *,
    min_shared_terms: int = 2,
) -> ContextGraph:
    """Build a deterministic graph from ``[(block_id, text)]``.

    - exact content duplicates -> DUPLICATES
    - >= ``min_shared_terms`` distinctive shared terms -> SUPPORTS (dependency link)
    - supersession cue + >=1 shared term with another block -> SUPERSEDES
    - qualifier cue + shared terms with another block -> QUALIFIES
    - negation cue + shared terms with another block -> CONTRADICTS (conservative:
      a negation sharing vocabulary with kept content must be reviewed, not dropped)
    """
    graph = ContextGraph()
    for block_id, _ in blocks:
        graph.nodes.add(block_id)
    # Duplicates (exact bytes): link later copies to the first.
    seen_text: dict[str, str] = {}
    for bid, txt in blocks:
        h = _sha(txt)
        if h in seen_text:
            graph.add_edge(GraphEdge(source=bid, target=seen_text[h],
                                     type=EdgeType.DUPLICATES, confidence=1.0,
                                     reason="identical_bytes"))
        else:
            seen_text[h] = bid
    # Distinctive terms (not question terms, not corpus-wide boilerplate).
    ceiling = max(2, len(blocks) // 2)
    occurrences: dict[str, set[str]] = {}
    terms_for: dict[str, set[str]] = {}
    for bid, txt in blocks:
        terms = {t for t in _terms(txt) if t not in question_terms}
        terms_for[bid] = terms
        for t in terms:
            occurrences.setdefault(t, set()).add(bid)
    distinctive = {t: bids for t, bids in occurrences.items() if 1 < len(bids) <= ceiling}
    dterms: dict[str, set[str]] = {bid: set() for bid, _ in blocks}
    for term, bids in distinctive.items():
        for bid in bids:
            dterms[bid].add(term)
    ordered = [bid for bid, _ in blocks]
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            common = dterms[a] & dterms[b]
            if len(common) >= min_shared_terms:
                reason = ",".join(sorted(common)[:3])
                graph.add_edge(GraphEdge(source=b, target=a, type=EdgeType.SUPPORTS,
                                         confidence=0.6, reason=f"link_terms:{reason}"))
    # Supersession / qualifier / contradiction passes (one shared term suffices: a
    # restatement names the same metric in different words).
    for bid, txt in blocks:
        if _SUPERSESSION_CUE_RE.search(txt):
            for other, oterms in dterms.items():
                if other == bid:
                    continue
                common = dterms[bid] & oterms
                if common:
                    graph.add_edge(GraphEdge(
                        source=bid, target=other, type=EdgeType.SUPERSEDES,
                        confidence=0.75,
                        reason=f"supersedes_value:{','.join(sorted(common)[:3])}"))
                    break
        elif _QUALIFIER_RE.search(txt):
            for other, oterms in dterms.items():
                if other == bid:
                    continue
                common = dterms[bid] & oterms
                if len(common) >= 2 and len(txt) >= 80:
                    graph.add_edge(GraphEdge(
                        source=bid, target=other, type=EdgeType.QUALIFIES,
                        confidence=0.7,
                        reason=f"qualifies:{','.join(sorted(common)[:3])}"))
                    break
        elif _NEGATION_RE.search(txt):
            for other, oterms in dterms.items():
                if other == bid:
                    continue
                common = dterms[bid] & oterms
                if len(common) >= min_shared_terms:
                    graph.add_edge(GraphEdge(
                        source=bid, target=other, type=EdgeType.CONTRADICTS,
                        confidence=0.6,
                        reason=f"negation_shares:{','.join(sorted(common)[:3])}"))
                    break
    return graph
