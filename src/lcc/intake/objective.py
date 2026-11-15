"""The main ask of a long input, by ranking topic blocks (arm D of intake-objective-v1).

Under evaluation: ``benchmarks/research/intake-objective-v1/PROTOCOL.md`` defines it and
``parse_intake`` does not call it yet. Offline and deterministic.

1. *Blocks.* Adjacent sentences form a block; a block ends before a topic-shift marker or where
   two neighbouring sentences share no content word.
2. *Score.* Four signals: recurrence (BM25 of the block's terms against every other block), a
   priority marker, a restatement at the end, and the parser's ask cues.
3. *Pick.* Only blocks holding a sentence with the role ``ask`` are ranked. The objective is the
   first ask sentence of the top block; with no eligible block it is ``brief.objective``. Blocks
   sharing a content word with the objective are linked; the rest go to the stash.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from lcc.intake.parser import _ASK_CUE, _EN_STOP, _PT_STOP, parse_intake
from lcc.relevance.compactor import fold_accents
from lcc.relevance.specialist import _bm25

SIGNALS = ("recurrence", "marker", "restate", "ask")
#: Tuned on the dev split only and frozen by amendment before the test run.
WEIGHTS: dict[str, float] = {"recurrence": 0.0, "marker": 0.5, "restate": 0.5, "ask": 0.5}

# ponytail: cue lists, not a parser. Ceiling: a priority or recap said in words these miss.
_TOPIC_SHIFT = re.compile(
    r"(?i)^\W*(?:(?:ah|ah sim|e|ok|bom|enfim|oh|and|ok so|so)[,\s]+)?"
    r"(?:outra coisa|outro assunto|mudando de assunto|voltando|falando nisso|enfim"
    r"|another thing|one more thing|anyway|on another note|by the way|speaking of|back to)\b"
)
_PRIORITY = re.compile(
    r"(?i)\b(?:o\s+(?:mais\s+)?importante|o\s+principal|a\s+principal|prioridade|priorit[aá]ri"
    r"|o\s+que\s+(?:mais\s+)?importa|acima de tudo|antes de (?:qualquer|tudo)|o\s+foco"
    r"|mais urgente|urgente|crucial|essencial|uma coisa s[oó]"
    r"|main thing|most important|the priority|top priority|priority one|what (?:really )?matters"
    r"|above all|before anything else|the big one|the key (?:thing|one)|most urgent|urgent"
    r"|crucial|essential|care about most|one thing today|matters most)"
)
_RECAP = re.compile(
    r"(?i)^\W*(?:ent[aã]o,?\s+)?(?:resumindo|em resumo|recapitulando|no fim das contas"
    r"|pra fechar|deixando claro|voltando ao que importa|resumo"
    r"|to sum up|in short|to recap|bottom line|long story short|at the end of the day"
    r"|just to be clear|coming back to|in summary|so,? basically)\b"
)
_WORD = re.compile(r"[^\W\d_]+")
_STOP = {fold_accents(w) for w in _PT_STOP | _EN_STOP}


def content_terms(text: str) -> list[str]:
    """Content words of ``text``: accent-folded, four letters or more, outside the parser's
    stopwords, cut to their first five letters so "fotos" and "foto" meet."""
    words = _WORD.findall(fold_accents(text))
    return [w[:5] for w in words if len(w) >= 4 and w not in _STOP]


@dataclass
class Block:
    """Consecutive sentences of the input; ``span`` covers them and the whitespace after. An input
    with no sentence (empty or whitespace) is one block with no sentence, so it still rebuilds."""

    sentences: list[int]
    span: tuple[int, int]
    eligible: bool
    signals: dict[str, float] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class ObjectivePick:
    """Arm D's answer for one input. Spans index the text given to :func:`pick_objective`."""

    objective: str
    objective_span: tuple[int, int]
    #: Blocks in input order; ``ranking`` lists the eligible ones, best first.
    blocks: list[Block]
    ranking: list[int]
    linked: list[int]
    stash: list[int]
    fallback: bool


def split_blocks(text: str, spans: list[tuple[int, int]]) -> list[list[int]]:
    """Sentence indexes grouped into topic blocks."""
    groups: list[list[int]] = []
    previous: set[str] = set()
    for i, (s, e) in enumerate(spans):
        terms = set(content_terms(text[s:e]))
        if not groups or _TOPIC_SHIFT.search(text[s:e]) or not terms & previous:
            groups.append([i])
        else:
            groups[-1].append(i)
        previous = terms
    return groups


def _similarity(query: list[str], docs: list[list[str]]) -> list[float]:
    """BM25 of ``query`` against each of ``docs``, the scorer of ``lcc.relevance.specialist``."""
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    qset = set(query)
    for i, doc in enumerate(docs):
        for t, f in Counter(t for t in doc if t in qset).items():
            postings[t].append((i, f))
    lens = [len(d) for d in docs]
    avg = (sum(lens) / len(lens) or 1) if lens else 1
    return _bm25(query, postings, lens, avg)


def _scaled(values: list[float]) -> list[float]:
    top = max(values, default=0.0)
    return [v / top if top > 0 else 0.0 for v in values]


@dataclass
class Analysis:
    """Everything about an input that does not depend on the weights."""

    text: str
    texts: list[str]
    spans: list[tuple[int, int]]
    roles: list[str]
    groups: list[list[int]]
    terms: list[list[str]]
    values: dict[str, list[float]]
    default_objective: str


def analyse(text: str) -> Analysis:
    """Sentences, roles, topic blocks and each block's four signals, scaled to [0, 1]."""
    parsed = parse_intake(text)
    items = parsed.extract
    texts = [item.text for item in items]
    spans = [item.spans[0] for item in items]
    groups = split_blocks(text, spans) or [[]]
    bodies = [" ".join(texts[i] for i in g) for g in groups]
    terms = [content_terms(b) for b in bodies]
    n = len(groups)
    recurrence = []
    for i in range(n):
        sims = _similarity(terms[i], terms)
        recurrence.append(sum(v for j, v in enumerate(sims) if j != i))
    restate = [0.0] * n
    if n > 1 and _RECAP.search(texts[groups[-1][0]]):
        # The recap and the block it repeats both carry the signal.
        restate = [*_scaled(_similarity(terms[-1], terms[:-1])), 1.0]
    values = {
        "recurrence": _scaled(recurrence),
        "marker": [1.0 if _PRIORITY.search(b) else 0.0 for b in bodies],
        "restate": restate,
        # Per sentence: a cue anchored at a sentence start must not depend on how sentences join.
        "ask": _scaled([float(sum(len(_ASK_CUE.findall(texts[i])) for i in g)) for g in groups]),
    }
    roles = [item.role for item in items]
    return Analysis(text, texts, spans, roles, groups, terms, values, parsed.brief.objective)


def choose(
    a: Analysis, weights: dict[str, float] | None = None, *, drop: str | None = None
) -> ObjectivePick:
    """Score the blocks of ``a`` with ``weights`` and pick the main ask. ``drop`` zeroes one
    signal (the protocol's ablations); the other weights stay as they are."""
    weights = dict(weights or WEIGHTS)
    if drop:
        weights[drop] = 0.0
    n = len(a.groups)
    blocks = []
    for i, g in enumerate(a.groups):
        start = 0 if i == 0 else a.spans[g[0]][0]  # leading whitespace joins the first block
        end = a.spans[a.groups[i + 1][0]][0] if i + 1 < n else len(a.text)
        signals = {name: a.values[name][i] for name in SIGNALS}
        blocks.append(
            Block(
                sentences=g,
                span=(start, end),
                eligible=any(a.roles[j] == "ask" for j in g),
                signals=signals,
                score=sum(weights[name] * v for name, v in signals.items()),
            )
        )
    # sorted() is stable: ties go to the earlier block, as the first-ask rule would.
    ranking = sorted(
        (i for i, b in enumerate(blocks) if b.eligible), key=lambda i: -blocks[i].score
    )
    home: int | None = None
    if ranking:
        home = ranking[0]
        first = next(j for j in blocks[home].sentences if a.roles[j] == "ask")
        objective, objective_span, fallback = a.texts[first], a.spans[first], False
    else:  # no ask anywhere: brief.objective is the opening of the input, not a sentence
        objective, objective_span, fallback = a.default_objective, (0, 0), True
    own = set(content_terms(objective))
    linked = [i for i in range(n) if i != home and own & set(a.terms[i])]
    stash = [i for i in range(n) if i != home and i not in linked]
    return ObjectivePick(objective, objective_span, blocks, ranking, linked, stash, fallback)


def pick_objective(
    text: str, weights: dict[str, float] | None = None, *, drop: str | None = None
) -> ObjectivePick:
    """Arm D on ``text``: :func:`analyse` then :func:`choose`."""
    return choose(analyse(text), weights, drop=drop)
