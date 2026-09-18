"""Instant relevance compaction: opt-in block dropping driven by narrow model judgment.

Blocks can end in three states: ``keep`` (bytes re-emitted exactly), ``trim`` (a bounded
head is kept plus a one-line note; the middle gear adopted in the 2026-09-18 review of
tamaratran/fast-jev-compaction), or ``drop``. Scoring batches run concurrently, the newest
blocks can be pinned untouched (``preserve_tail_blocks``) for live append-only contexts, and
the report carries a reduction ratio with a worth-it flag so callers can skip a cache epoch
that saves too little.

Boundary (ADR 0013): this package is NOT part of the deterministic core. It only runs when
explicitly opted in, it fails safe (when in doubt, keep), and it falls back to a fully local
mechanical pass when the model provider is unavailable. The compactor never rewrites kept
blocks: kept bytes are re-emitted exactly, and everything before the first dropped block is
byte-identical to the input, so cache-aligned prefixes survive a compaction pass.

Cache alignment (why this is incremental, not a re-judge on every run):
- ``decisions_cache_path`` pins an ``(objective, block content)`` decision so unchanged
  blocks keep identical outcomes across runs (byte-stable output -> stable cached prefix).
- ``protect_prefix_chars`` / ``prefix_marker`` hard-protect an initial region so the pass
  can only ever mutate the tail while a live cache is warm.
- The report publishes ``first_mutation_offset`` and ``prefix_sha256`` so orchestrators can
  detect exactly where a cache epoch must be rebuilt, instead of finding out via costs.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lcc.relevance.blocks import (
    DEFAULT_MAX_BLOCK_CHARS,
    DEFAULT_MIN_BLOCK_CHARS,
    TextBlock,
    gaps_between,
    split_blocks,
)
from lcc.relevance.decisions import (
    BLOCK_PARSER_VERSION,
    POLICY_VERSION,
    PROTECTION_VERSION,
    RELATIONSHIP_VERSION,
    CachedDecision,
    DecisionCache,
    build_decision_identity,
    decision_key_v2,
)
from lcc.relevance.graph import build_graph
from lcc.relevance.jev import JevClient, JevError, parse_noul_answer
from lcc.relevance.sufficiency import verify_sufficiency
from lcc.relevance.trim import TRIM_POLICY_VERSION, detect_content_type, trim_block_safe
from lcc.token_budget import count_tokens
from lcc.token_budget.counters import tokenizer_identity_for_count

RELEVANCE_SCHEMA_VERSION = "relevance-compaction-1.1"
POLICY_VERSION_ALIAS = POLICY_VERSION

#: Prompt-cache cost factors from ``docs/CACHE_ALIGNMENT.md``: a cache read costs ~0.10x the
#: base token price and a cache write ~1.25x. Used to report the break-even reuse count of a
#: pass that mutates a warm prefix. Override per provider before trusting the figure.
_CACHE_READ_FACTOR = 0.10
_CACHE_WRITE_FACTOR = 1.25

_DEFAULT_THRESHOLD = 0.4
_DEFAULT_BATCH_SIZE = 8
_DEFAULT_MAX_STATE_CHARS = 12000
_DEFAULT_TRIM_HEAD_CHARS = 300
_DEFAULT_MAX_WORKERS = 4
_DEFAULT_MIN_REDUCTION = 0.25
_SCORE_CLIP_HEAD = 4000
_SCORE_CLIP_TAIL = 1100

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?")
_STOPWORDS = {
    "about", "after", "also", "and", "are", "can", "for", "from", "has", "have", "how",
    "into", "its", "our", "should", "that", "the", "their", "this", "was", "what", "when",
    "where", "which", "who", "why", "with",
}


@dataclass(frozen=True)
class RelevanceCompactionRequest:
    """All inputs for a single relevance compaction pass."""

    text: str
    question: str
    threshold: float = _DEFAULT_THRESHOLD
    # Middle gear: blocks scoring in [trim_threshold, threshold) keep a bounded head
    # instead of being dropped. ``None`` resolves to ``threshold * 0.5``; set
    # ``trim_head_chars`` to 0 to keep the pass strictly binary (keep/drop).
    trim_threshold: float | None = None
    trim_head_chars: int = _DEFAULT_TRIM_HEAD_CHARS
    # Live append-only contexts: the newest N blocks are never scored or mutated.
    preserve_tail_blocks: int = 0
    # Scoring batches sent concurrently; 1 keeps the strictly sequential path.
    max_workers: int = _DEFAULT_MAX_WORKERS
    # Below this share of removed characters the pass is flagged as not worth a cache epoch.
    min_reduction: float = _DEFAULT_MIN_REDUCTION
    batch_size: int = _DEFAULT_BATCH_SIZE
    min_block_chars: int = DEFAULT_MIN_BLOCK_CHARS
    max_block_chars: int = DEFAULT_MAX_BLOCK_CHARS
    max_state_chars: int = _DEFAULT_MAX_STATE_CHARS
    keep_patterns: tuple[str, ...] = ()
    marker: bool = True
    #: Put scorer values inside the inline drop marker. Off by default: live scores wobble
    #: between calls, and a marker that embeds them changes the emitted bytes on every run,
    #: which defeats the prompt cache the pass is meant to protect. Scores stay in the report.
    marker_scores: bool = False
    #: Apply the deterministic safety net to locally scored blocks: negations, literals,
    #: quoted speech, foreign-language evidence and rare-term dependencies survive overlap
    #: scoring. On by default, because the local scorer is a fallback and a fallback should
    #: err toward keeping evidence.
    deterministic_protection: bool = True
    provider: str = "auto"  # auto | jev | mechanical
    model: str = "gpt-4.1"  # token counting model (ADR 0005 honesty contract)
    jev_model: str = "jev-latest"
    protect_prefix_chars: int | None = None
    prefix_marker: str | None = None
    decisions_cache_path: Path | None = None
    client: JevClient | None = None  # dependency injection for tests
    #: Semantic sufficiency verification (P0-6): after candidate compression, verify the
    #: remaining context still entails the objective and restore linked evidence.
    enable_sufficiency: bool = True
    #: Maximum dropped blocks restored by sufficiency in one pass.
    max_restorations: int = 8
    #: Confidence below which a DROP degrades to TRIM, and below half of which to KEEP.
    #: Risk scales it: high-risk content requires higher confidence to drop.
    confidence_threshold: float = 0.5
    #: Independent semantic verification (feedback P0): a second Jev question over
    #: {objective, candidate_context} only — never scores/decisions. Off by default
    #: so existing cold runs pay zero extra calls; E1/E2 harness opts in. When the
    #: verifier flags insufficiency the pass emits REVIEW (KEEP + flag), never trust.
    enable_semantic_verify: bool = False


@dataclass(frozen=True)
class BlockDecision:
    """One auditable keep/trim/drop decision."""

    id: str
    index: int
    line_start: int
    line_end: int
    chars: int
    decision: str  # keep | trim | drop
    source: str  # protected | reused | jev | mechanical | mechanical_fallback | degraded
    score: float | None
    reason: str
    chars_after: int | None = None  # set for ``trim`` (head kept + note)
    #: Confidence in this decision (Jev answer confidence when present, else 1.0 for
    #: deterministic rules). A policy input, not decoration: low confidence degrades
    #: DROP->TRIM->KEEP.
    confidence: float | None = None
    #: Typed relationships that affected the decision (e.g. ``QUALIFIES:blk_0003_…``).
    relationships: tuple[str, ...] = ()
    #: Policy that produced the decision (``relevance-compaction-1.1``).
    policy_version: str = POLICY_VERSION
    #: Content type used for the trim policy (prose, json, code, …).
    content_type: str | None = None


@dataclass(frozen=True)
class RelevanceCompactionReport:
    """Machine-readable compaction report (schema-versioned like every lcc report)."""

    schema_version: str
    provider_requested: str
    provider_used: str
    degraded: bool
    objective: str
    threshold: float
    trim_threshold: float | None
    trim_head_chars: int
    blocks_total: int
    blocks_scored: int
    blocks_protected: int
    blocks_dropped: int
    blocks_trimmed: int
    chars_before: int
    chars_after: int
    chars_removed: int
    tokens_before: int
    tokens_after: int
    token_count_method: str
    reduction_ratio: float
    worth_it: bool
    min_reduction: float
    calls: int
    latency_ms: int
    reused_decisions: int
    prefix_protected: bool
    prefix_untouched: bool
    first_mutation_offset: int | None
    prefix_sha256: str
    output_sha256: str
    #: Why the run degraded, when ``degraded`` is true (``jev_unavailable``,
    #: ``jev_unavailable_mechanical_fallback``, ``jev_batch_failed``).
    degradation_reason: str | None = None
    #: What the pass can promise about semantic judgment: ``judged`` (every scored block was
    #: decided by the model provider), ``partial`` (some blocks fell back), or ``none``
    #: (mechanical or degraded scoring only). Callers that need evidence preservation must
    #: refuse ``none``.
    semantic_guarantee: str = "judged"
    #: Tokens to the right of the first mutation. Everything here is recomputed by a prompt
    #: cache whose prefix was warm, so it is the real cost of the pass.
    invalidated_tokens: int = 0
    #: Reuses of the pruned context needed before the invalidation pays for the drop, using
    #: the read/write factors in ``docs/CACHE_ALIGNMENT.md``. ``None`` when nothing was
    #: dropped or nothing was invalidated.
    break_even_reuses: float | None = None
    #: Tokenizer contract: what actually counted the tokens (never imply equivalence
    #: across tokenizers). ``token_count_method`` stays for back-compat; the identity
    #: fields say which tokenizer and whether the figures are estimates.
    tokenizer: str = "heuristic"
    tokenizer_id: str = "heuristic-v1"
    tokenizer_version: str | None = None
    is_estimate: bool = True
    #: Model identity: requested vs resolved (a moving alias like ``jev-latest`` is never
    #: the only recorded identifier).
    jev_model_requested: str = "jev-latest"
    jev_model_resolved: str | None = None
    #: Sufficiency + relationship observability (machine-readable, never in the prompt).
    blocks_restored: int = 0
    sufficiency_checks: int = 0
    sufficiency_failures: int = 0
    sufficiency_confidence: float | None = None
    relationship_edges: int = 0
    semantic_decisions: int = 0
    semantic_cache_hits: int = 0
    semantic_cache_misses: int = 0
    #: Marker economics: markers cost tokens too. ``marker_tokens`` is measured, and the
    #: report warns when markers erase the saving they were meant to protect.
    marker_tokens: int = 0
    policy_version: str = POLICY_VERSION
    trim_policy_version: str = TRIM_POLICY_VERSION
    parser_version: str = BLOCK_PARSER_VERSION
    protection_version: str = PROTECTION_VERSION
    relationship_version: str = RELATIONSHIP_VERSION
    #: Wall-clock cost of the whole pass (deterministic + semantic + sufficiency).
    #: Compare `mechanical only` vs `mechanical + Jev` vs `mechanical + cached Jev` by
    #: reading this alongside `calls`/`latency_ms`/`reused_decisions`.
    compilation_ms: int = 0
    #: Fourth decision REVIEW (signal-only): True when the independent verifier or
    #: low confidence says "I don't know whether this is safe to remove". The bytes
    #: stay KEEP; only the flag + warning change so callers can quarantine.
    needs_review: bool = False
    review_reason: str | None = None
    #: Independent semantic verifier outcome (None when disabled/unavailable).
    semantic_verifier_sufficient: bool | None = None
    semantic_verifier_confidence: float | None = None
    semantic_verifier_model: str | None = None
    warnings: list[str] = field(default_factory=list)
    decisions: list[BlockDecision] = field(default_factory=list)


@dataclass(frozen=True)
class RelevanceCompactionResult:
    """Compacted text plus the report explaining every decision."""

    compacted_text: str
    report: RelevanceCompactionReport


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lexical_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in _WORD_RE.finditer(text.lower()):
        term = match.group(0).strip("'")
        if len(term) >= 3 and term not in _STOPWORDS:
            terms.add(term)
    return terms


# --- deterministic safety net for the local scorer --------------------------------------
#
# The local scorer judges a block by how many words it shares with the objective, and that is
# a reasonable first filter with three measurable blind spots. Measured against the adversarial
# suite, the deterministic scorer fails exactly three of twenty cases:
#
#   * `dependency_causal`  a cause and its effect share no words with the objective, and the
#                          conclusion survives without the evidence that supports it;
#   * `quoted_instruction` a customer's quoted request reads as noise to overlap scoring;
#   * `multilingual`       evidence in another language shares no tokens with an English
#                          objective written by the analyst.
#
# Only those three are addressed here. Two broader rules were implemented, measured and
# removed: protecting every block that contains a negation cue, and every block that contains
# a literal. Both sound reasonable and both are unusable in practice — on the twenty cases
# they took compaction from 56% mean reduction to 0.0%, because chatter, log lines and filler
# are full of words like "not" and numbers with units. A protection that keeps everything is
# not a protection, it is a disabled compressor. The hazards those rules targeted
# (negation_consent, numeric_precision, unit_conversion) already pass without them.

#: Third-party speech: it is evidence about what someone said, not background chatter.
_QUOTED_SPEECH_RE = re.compile(
    r"[\u201c\"'][^\"\u201c\u201d]{12,}[\u201d\"']"
    r"|\b(?:wrote|said|reported|stated|asked|complained|replied)\b[^.]{0,40}:",
    re.IGNORECASE,
)

#: Function words that identify the language of a passage without a model. Entries must be
#: unambiguous: a word that is common in two languages would blur the signal.
_LANGUAGE_MARKERS: dict[str, frozenset[str]] = {
    "pt": frozenset(
        {
            "nao", "são", "sao", "cerca", "porque", "tambem", "também", "muito", "qual",
            "quando", "onde", "entre", "sobre", "ainda", "depois", "cada", "pode", "ser",
            "estar",
        }
    ),
    "es": frozenset(
        {"para", "pero", "porque", "tambien", "cuando", "donde", "entre", "sobre", "muy", "cada"}
    ),
    "fr": frozenset(
        {"pour", "mais", "parce", "quand", "dont", "entre", "sur", "tres", "très", "avec", "chaque"}
    ),
    "de": frozenset(
        {"und", "nicht", "auch", "wenn", "wo", "zwischen", "uber", "über", "sehr", "jede", "sein"}
    ),
}


def _detect_language(text: str) -> str | None:
    """Best-effort language tag from unambiguous function words; ``None`` when unsure.

    Only a clear signal counts, so English text and short blocks stay ``None`` rather than
    being guessed at.
    """
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if len(words) < 12:
        return None
    hits: dict[str, int] = {}
    for tag, markers in _LANGUAGE_MARKERS.items():
        hits[tag] = sum(1 for w in words if w in markers)
    if not hits:
        return None
    best = max(hits, key=lambda tag: hits[tag])
    # Require a real signal and a clear winner, so a stray word cannot flip the verdict.
    if hits[best] < 3 or hits[best] <= 1.5 * max(
        (count for tag, count in hits.items() if tag != best), default=0
    ):
        return None
    return best


def _deterministic_protection(block_text: str, question_language: str | None) -> str | None:
    """Return the reason a block must survive local scoring, or ``None`` when it may be judged."""
    if _QUOTED_SPEECH_RE.search(block_text):
        return "quoted_speech_present"
    block_language = _detect_language(block_text)
    if block_language and question_language and block_language != question_language:
        return f"evidence_in_{block_language}_not_{question_language}"
    return None


#: Shortest term that can act as a link between two blocks. Four rather than five because
#: concrete nouns and month names are often exactly four characters ("flow", "June"), and a
#: floor of five silently cut the causal case down to a single shared term.
_DISTINCTIVE_MIN_TERM_CHARS = 4


#: Cues that a block restates a value another block already carries. Dropping the restatement
#: while keeping the original leaves a stale figure with no sign that it was superseded, which
#: is the one category the deterministic scorer lost in the categorized benchmark. Kept narrow
#: on purpose: a broad cue set here would protect half the corpus, which is the mistake the
#: negation and literal rules already made.
_SUPERSESSION_CUE_RE = re.compile(
    r"\b(?:revised|revision|superseded|supersedes|corrected|correction|amended|amendment|"
    r"restated|restatement|down from|up from)\b",
    re.IGNORECASE,
)


def _distinctive_terms(
    blocks: list[TextBlock], question_terms: set[str]
) -> dict[str, set[str]]:
    """Map each distinctive term to the ids of blocks containing it.

    Distinctive means two things: the term is not part of the objective (a question term is the
    topic, not a link between two specific blocks) and it is not corpus-wide boilerplate. The
    ceiling is relative to the corpus, so a term repeated by duplicated filler stops counting as
    distinctive while still linking genuinely specific blocks.
    """
    ceiling = max(2, len(blocks) // 2)
    occurrences: dict[str, set[str]] = {}
    for block in blocks:
        for term in _lexical_terms(block.text):
            if len(term) < _DISTINCTIVE_MIN_TERM_CHARS or term in question_terms:
                continue
            occurrences.setdefault(term, set()).add(block.id)
    return {term: ids for term, ids in occurrences.items() if 1 < len(ids) <= ceiling}


def _dependency_closures(
    blocks: list[TextBlock],
    kept_ids: set[str],
    question_terms: set[str],
    min_shared_terms: int = 2,
    max_hops: int = 1,
) -> dict[str, str]:
    """Blocks pulled in because they share distinctive vocabulary with a kept block.

    Two shared distinctive terms are required rather than one, so a single incidental overlap
    cannot drag half the corpus back in.

    ``max_hops`` bounds how far the pull propagates. One hop fixes the measured failure (a
    cause block pulled in by its effect). Multi-hop was implemented and measured: it keeps
    pulling in blocks that merely mention the same nouns, which in the adversarial suite means
    the trap blocks come along too, and it cost roughly twenty points of mean reduction for no
    additional case passing. One hop is the default for that reason.
    """
    distinctive = _distinctive_terms(blocks, question_terms)
    terms_for: dict[str, set[str]] = {}
    for term, ids in distinctive.items():
        for block_id in ids:
            terms_for.setdefault(block_id, set()).add(term)
    supersedes = {
        block.id: bool(_SUPERSESSION_CUE_RE.search(block.text)) for block in blocks
    }

    pulled: dict[str, str] = {}
    seen = set(kept_ids)
    frontier = set(kept_ids)
    hops = 0
    while frontier and hops < max_hops:
        shared: dict[str, set[str]] = {}
        for block_id in set(terms_for) - seen:
            common = set()
            for source_id in frontier:
                common |= terms_for.get(source_id, set()) & terms_for[block_id]
            if len(common) >= min_shared_terms:
                shared[block_id] = common
        next_frontier: set[str] = set()
        for block_id, common in shared.items():
            pulled[block_id] = f"link_terms:{','.join(sorted(common)[:3])}"
            seen.add(block_id)
            next_frontier.add(block_id)
        frontier = next_frontier
        hops += 1

    # Supersession pass, deliberately not part of the loop above. A restatement needs one shared
    # term, not two, because it names the same metric in different words; and it may attach to a
    # block the closure just pulled in, because a revision often qualifies evidence that was
    # itself linked rather than natively kept. What it must NOT do is seed further links: making
    # the general closure transitive cost twenty-seven points of reduction on the medium corpus,
    # so the extra reach is confined to this one rule.
    for block_id in set(terms_for) - seen:
        if not supersedes.get(block_id):
            continue
        common = set()
        for source_id in seen:
            common |= terms_for.get(source_id, set()) & terms_for[block_id]
        if common:
            pulled[block_id] = f"supersedes_value:{','.join(sorted(common)[:3])}"
    return pulled


def _clip_for_scoring(text: str, limit: int = _SCORE_CLIP_HEAD + _SCORE_CLIP_TAIL) -> str:
    if len(text) <= limit:
        return text
    tail = text[-_SCORE_CLIP_TAIL:]
    removed = len(text) - _SCORE_CLIP_HEAD - _SCORE_CLIP_TAIL
    return (
        f"{text[:_SCORE_CLIP_HEAD]}\n"
        f"…[lcc-compact: {removed} chars clipped for scoring]…\n{tail}"
    )


def _resolve_client() -> JevClient | None:
    """Default provider resolution; tests monkeypatch this seam to stay offline."""
    from lcc.relevance.jev import default_ledger_path

    return JevClient.from_env(ledger_path=default_ledger_path())


_TRIM_HEAD_SLACK = 200


def _render_trimmed(
    block_text: str,
    score: float | None,
    trim_threshold: float | None,
    threshold: float,
    head_chars: int,
) -> str:
    """Rendered form of a trimmed block: safe head plus one audit note line.

    Type-aware: structured content trims only at safe boundaries (valid syntax,
    whole table rows, whole code lines); when no safe boundary exists the caller
    must KEEP instead — this function then returns the whole block and the caller
    is expected to check :func:`trim_block_safe` first. Kept for back-compat: the
    safe path is resolved here so existing callers get safety by default.
    """
    head, ok, _ctype = trim_block_safe(block_text, head_chars)
    if not ok:
        head = _cut_prose_head(block_text, head_chars)
    if score is None:
        score_part = ""
    elif trim_threshold is not None:
        score_part = f", score {score:.2f} in band {trim_threshold:.2f}-{threshold:.2f}"
    else:
        score_part = f", score {score:.2f}"
    return (
        f"{head.rstrip()}\n"
        f"[lcc-compact: trimmed {len(block_text) - len(head)} of {len(block_text)} chars "
        f"of this block{score_part}]"
    )


def _cut_prose_head(text: str, budget: int) -> str:
    cut = text.rfind(" ", 0, budget)
    if cut < max(20, budget // 2):
        cut = budget
    return text[:cut]


def _safe_trim_head(block_text: str, head_chars: int) -> tuple[str, bool, str]:
    """Safe head for a trim decision; ``ok=False`` means the block must be kept whole."""
    return trim_block_safe(block_text, head_chars)


def _marker_for_run(
    run: list[BlockDecision], threshold: float, *, include_scores: bool = False
) -> str:
    """Inline replacement for a run of dropped blocks.

    Scores are deliberately left out by default. Live scorer values wobble between calls, so
    a marker that embeds them makes every run emit different bytes and invalidates the prompt
    cache the pass was supposed to protect. The per-block scores stay in the report, where
    they can be audited without touching the emitted context. Pass ``include_scores=True``
    (CLI: ``--marker-scores``) to put them back inline.
    """
    total_chars = sum(decision.chars for decision in run)
    scores = [decision.score for decision in run if decision.score is not None]
    label = "block" if len(run) == 1 else "blocks"
    base = f"{len(run)} {label} ({total_chars} chars)"
    if not include_scores:
        return f"[lcc-compact: dropped {base}]"
    if len(run) == 1:
        score_part = f"score {scores[0]:.2f} < {threshold:.2f}" if scores else "no score"
        return f"[lcc-compact: dropped 1 block ({total_chars} chars, {score_part})]"
    if scores:
        score_part = f"scores {min(scores):.2f}-{max(scores):.2f} < {threshold:.2f}"
    else:
        score_part = f"threshold {threshold:.2f}"
    return f"[lcc-compact: dropped {len(run)} blocks ({total_chars} chars, {score_part})]"


def _marker_tokens(compacted: str, model: str) -> int:
    """Tokens consumed by inline drop/trim markers in the emitted context."""
    markers = re.findall(r"\[lcc-compact: (?:dropped|trimmed)[^\]]*\]", compacted)
    if not markers:
        return 0
    try:
        return count_tokens("\n".join(markers), model).value
    except Exception:
        return 0


def _batch_blocks(
    blocks: list[TextBlock], batch_size: int, max_state_chars: int
) -> list[list[TextBlock]]:
    batches: list[list[TextBlock]] = []
    current: list[TextBlock] = []
    current_chars = 0
    for block in blocks:
        clipped_len = len(_clip_for_scoring(block.text))
        too_many = len(current) >= batch_size
        too_big = current_chars + clipped_len > max_state_chars
        if current and (too_many or too_big):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(block)
        current_chars += clipped_len
    if current:
        batches.append(current)
    return batches


def _score_with_jev(
    client: JevClient,
    blocks: list[TextBlock],
    request: RelevanceCompactionRequest,
) -> tuple[dict[str, tuple[float, str, float | None]], int, int, list[str], str | None]:
    """Score blocks with Jev, concurrently when several batches exist.

    Returns (results, calls, latency_ms, warnings, resolved_model). Each result is
    ``(score, source, confidence)``. Answers that are missing, malformed, or outside
    [0, 1] are left out so the caller scores them mechanically (fail-safe, unchanged
    contract); every such case is reported as a warning with a typed reason.
    """
    results: dict[str, tuple[float, str, float | None]] = {}
    warnings: list[str] = []
    batches = _batch_blocks(blocks, request.batch_size, request.max_state_chars)

    def score_batch(
        batch_index: int, batch: list[TextBlock]
    ) -> tuple[int, dict[str, Any] | None, int, str | None]:
        state = {
            "objective": request.question,
            "blocks": [{"id": block.id, "text": _clip_for_scoring(block.text)} for block in batch],
        }
        questions = {
            f"keep_{block.id}": {
                "type": "noul",
                "instructions": (
                    f"Judge the probability that block {block.id} (in the state) is relevant and "
                    "worth keeping in the context that will be shown to a larger model. The "
                    "objective is also in the state. Irrelevant noise, redundant logs, and "
                    "unrelated chatter should score low; when unsure, prefer keeping."
                ),
                "criteria": {
                    "true": "The block is relevant or plausibly useful for the objective.",
                    "false": "The block is unrelated noise for the objective.",
                },
            }
            for block in batch
        }
        started = time.perf_counter()
        try:
            response = client.evaluate(state, questions)
        except JevError as exc:
            return (
                batch_index,
                None,
                int((time.perf_counter() - started) * 1000),
                f"jev_batch_{batch_index}_failed: {exc}; those blocks scored mechanically",
            )
        return batch_index, response, int((time.perf_counter() - started) * 1000), None

    workers = max(1, min(8, int(request.max_workers)))
    if workers == 1 or len(batches) <= 1:
        outcomes = [score_batch(index, batch) for index, batch in enumerate(batches, start=1)]
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as pool:
            futures = [
                pool.submit(score_batch, index, batch)
                for index, batch in enumerate(batches, start=1)
            ]
            outcomes = [future.result() for future in futures]

    calls = 0
    latency_ms = 0
    resolved_model: str | None = None
    for batch_index, response, batch_latency, failure in outcomes:
        latency_ms += batch_latency
        if response is None:
            fallback = failure or f"jev_batch_{batch_index}_failed: unknown; scored mechanically"
            warnings.append(fallback)
            continue
        calls += 1
        resolved_model = getattr(client, "last_resolved_model", None) or resolved_model
        batch = batches[batch_index - 1]
        answers = response.get("answers") if isinstance(response, dict) else None
        if not isinstance(answers, dict):
            warnings.append(f"jev_malformed_response:batch_{batch_index}")
            continue
        for block in batch:
            answer = answers.get(f"keep_{block.id}")
            score, confidence, problem = parse_noul_answer(answer)
            if score is None:
                if problem == "out_of_range":
                    warnings.append(f"jev_answer_out_of_range:{block.id}")
                else:
                    warnings.append(f"jev_missing_answer:{block.id}")
                continue
            if problem in ("confidence_missing", "confidence_out_of_range"):
                warnings.append(f"jev_{problem}:{block.id}")
                confidence = None
            results[block.id] = (score, "jev", confidence)
    return results, calls, latency_ms, warnings, resolved_model


def _score_mechanically(
    blocks: list[TextBlock],
    question: str,
    *,
    protect: bool = True,
    question_language: str | None = None,
) -> dict[str, tuple[float, str, str | None]]:
    """Local fallback: drop only blocks with zero lexical overlap with the objective.

    The returned triple is ``(score, source, protection_reason)``. ``score`` stays the honest
    lexical overlap even when a block is protected, so the report shows both what overlap said
    and why the block survived anyway. A non-``None`` reason means the deterministic safety net
    kept it; the caller turns that into a keep decision.
    """
    question_terms = _lexical_terms(question)
    if not question_terms:
        # No objective terms: nothing can be judged irrelevant locally; keep everything.
        return {block.id: (1.0, "mechanical", None) for block in blocks}
    results: dict[str, tuple[float, str, str | None]] = {}
    for block in blocks:
        overlap = question_terms & _lexical_terms(block.text)
        denominator = max(1, min(6, len(question_terms)))
        score = round(min(1.0, len(overlap) / denominator), 2)
        reason = _deterministic_protection(block.text, question_language) if protect else None
        results[block.id] = (score, "mechanical", reason)
    if protect:
        # Relational pass: a block linked by distinctive vocabulary to something we are keeping
        # is pulled in too, so a conclusion does not outlive the evidence that supports it.
        kept = {
            block_id
            for block_id, (score, _, reason) in results.items()
            if score > 0.0 or reason is not None
        }
        for block_id, reason in _dependency_closures(blocks, kept, question_terms).items():
            score, source, existing = results[block_id]
            if existing is None:
                results[block_id] = (score, source, reason)
    return results


def compact_context(request: RelevanceCompactionRequest) -> RelevanceCompactionResult:
    """Run an opt-in relevance compaction pass over ``request.text``."""
    started_total = time.perf_counter()
    warnings: list[str] = []
    text = request.text
    if not request.question.strip():
        raise ValueError("relevance compaction requires a non-empty objective (--question)")
    blocks = split_blocks(
        text,
        min_block_chars=request.min_block_chars,
        max_block_chars=request.max_block_chars,
    )
    gaps = gaps_between(text, blocks)

    # --- prefix protection (cache alignment): blocks starting before the boundary never drop
    protect_boundary: int | None = None
    if request.protect_prefix_chars is not None:
        protect_boundary = max(0, request.protect_prefix_chars)
    elif request.prefix_marker:
        marker_index = text.find(request.prefix_marker)
        if marker_index == -1:
            warnings.append("prefix_marker_not_found: no protection applied")
        else:
            protect_boundary = marker_index

    keep_regexes = [re.compile(pattern) for pattern in request.keep_patterns]
    protected_reasons: dict[str, str] = {}
    for block in blocks:
        if block.protected:
            protected_reasons[block.id] = block.protected_reason or "short_block"
            continue
        if protect_boundary is not None and block.character_start < protect_boundary:
            protected_reasons[block.id] = "prefix_protect"
            continue
        if any(regex.search(block.text) for regex in keep_regexes):
            protected_reasons[block.id] = "keep_pattern"

    # --- live contexts: pin the newest N blocks untouched (fast-jev-compaction review)
    if request.preserve_tail_blocks > 0:
        for block in blocks[-request.preserve_tail_blocks :]:
            protected_reasons.setdefault(block.id, "tail_preserve")

    # --- middle gear resolution: trim band [trim_threshold, threshold)
    if request.trim_head_chars <= 0:
        trim_threshold: float | None = None
    elif request.trim_threshold is None:
        trim_threshold = request.threshold * 0.5
    elif 0.0 <= request.trim_threshold < request.threshold:
        trim_threshold = request.trim_threshold
    else:
        warnings.append("trim_threshold_out_of_range: trim disabled")
        trim_threshold = None

    scoreable = [block for block in blocks if block.id not in protected_reasons]

    # --- sticky decisions (cache alignment): reuse previous outcomes for unchanged blocks
    # v1.1 identity: same content + same policy = reusable; any policy/model/threshold
    # change is a different decision (a cache epoch, fail-safe direction).
    cache = DecisionCache(request.decisions_cache_path)
    cache.load()
    try:
        _tokenizer_id = tokenizer_identity_for_count(count_tokens("", request.model))[
            "tokenizer_id"
        ]
    except Exception:
        _tokenizer_id = "heuristic-v1"
    # Tokenizer identity for the key should reflect the counting model, not the probe
    # above (which counted empty text). Recompute cheaply without counting.
    try:
        from lcc.token_budget.counters import tokenizer_identity as _tok_ident

        _tokenizer_id = _tok_ident(request.model)["tokenizer_id"]
    except Exception:
        pass
    resolved_trim = (
        None
        if request.trim_head_chars <= 0
        else (
            request.trim_threshold
            if request.trim_threshold is not None
            else request.threshold * 0.5
        )
    )

    # Neighborhood-aware cache identity (feedback P1): same block + same objective
    # is NOT always the same decision — a new neighbour X can change B's semantic
    # role. Isolated blocks keep content-only identity; blocks in QUALIFIES /
    # CONTRADICTS / SUPERSEDES / DEPENDS_ON edges also bind a neighbourhood
    # fingerprint so a stale semantic decision cannot hit after the graph changed.
    _neighbourhood: dict[str, str | None] = {}
    try:
        _pre_graph = build_graph(
            [(b.id, b.text) for b in blocks],
            _lexical_terms(request.question),
            min_shared_terms=2,
        )
        for _b in blocks:
            _rel_edges = [
                e
                for e in _pre_graph.edges_touching(_b.id)
                if e.type.value
                in ("QUALIFIES", "CONTRADICTS", "SUPERSEDES", "DEPENDS_ON")
            ]
            if not _rel_edges:
                _neighbourhood[_b.id] = None
                continue
            _sig = "|".join(
                sorted(
                    f"{e.type.value}:{(e.target if e.source == _b.id else e.source)}"
                    for e in _rel_edges
                )
            )
            _neighbourhood[_b.id] = hashlib.sha256(_sig.encode("utf-8")).hexdigest()[:16]
    except Exception:
        _neighbourhood = {}

    def _cache_key_for(block_text: str, block_id: str | None = None) -> str:
        return decision_key_v2(
            build_decision_identity(
                objective=request.question,
                block_text=block_text,
                provider=request.provider,
                model=request.jev_model,
                policy_version=POLICY_VERSION,
                threshold=request.threshold,
                trim_threshold=resolved_trim,
                trim_head_chars=request.trim_head_chars,
                trim_policy_version=TRIM_POLICY_VERSION,
                parser_version=BLOCK_PARSER_VERSION,
                protection_version=PROTECTION_VERSION,
                relationship_version=RELATIONSHIP_VERSION,
                tokenizer_id=_tokenizer_id,
                deterministic_protection=request.deterministic_protection,
                relationship_context=_neighbourhood.get(block_id or "", None),
            )
        )

    decisions: dict[str, BlockDecision] = {}
    pending: list[TextBlock] = []
    reused = 0
    for block in scoreable:
        key = _cache_key_for(block.text, block.id)
        cached = cache.get(key) if request.decisions_cache_path is not None else None
        if cached is not None:
            reused += 1
            chars_after: int | None = None
            if cached.decision == "trim":
                chars_after = len(
                    _render_trimmed(
                        block.text,
                        cached.score,
                        trim_threshold,
                        request.threshold,
                        request.trim_head_chars,
                    )
                )
            decisions[block.id] = BlockDecision(
                id=block.id,
                index=block.index,
                line_start=block.line_start,
                line_end=block.line_end,
                chars=len(block.text),
                decision=cached.decision,
                source="reused",
                score=cached.score,
                reason=f"sticky_decision:{cached.provider}",
                chars_after=chars_after,
                confidence=None,
                relationships=(),
                policy_version=POLICY_VERSION,
                content_type=detect_content_type(block.text),
            )
        else:
            pending.append(block)

    # --- provider resolution
    provider_requested = request.provider
    provider_used = "mechanical"
    degraded = False
    degradation_reason: str | None = None
    semantic_guarantee = "judged"
    calls = 0
    latency_ms = 0
    jev_resolved: str | None = None
    client: JevClient | None = None
    if provider_requested in ("auto", "jev"):
        client = request.client if request.client is not None else _resolve_client()
        if client is None:
            if provider_requested == "jev":
                degraded = True
                provider_used = "degraded"
                degradation_reason = "jev_unavailable"
                semantic_guarantee = "none"
                warnings.append(
                    "jev_unavailable: no API key or network disabled; kept every block (fail-safe)"
                )
            else:
                # ``auto`` used to keep ``degraded: false`` here while quietly swapping the
                # semantic judge for a lexical scorer. The fallback itself is fine; hiding it
                # is not, so the degradation is now reported like any other.
                degraded = True
                degradation_reason = "jev_unavailable_mechanical_fallback"
                semantic_guarantee = "none"
                warnings.append(
                    "jev_unavailable: fell back to mechanical scoring; semantic judgment is "
                    "unavailable (degraded)"
                )
        elif request.jev_model:
            client.model = request.jev_model

    # Which language the objective is written in, so evidence in another language is not
    # dropped for sharing no tokens with it. The marker lists only non-English languages, so a
    # question too short to classify falls back to English; that errs toward keeping blocks.
    question_language: str | None = None
    if request.deterministic_protection:
        question_language = _detect_language(request.question) or "en"

    if pending and provider_used == "degraded":
        for block in pending:
            decisions[block.id] = BlockDecision(
                id=block.id,
                index=block.index,
                line_start=block.line_start,
                line_end=block.line_end,
                chars=len(block.text),
                decision="keep",
                source="degraded",
                score=None,
                reason="jev_unavailable_fail_safe",
                confidence=None,
                relationships=(),
                policy_version=POLICY_VERSION,
                content_type=detect_content_type(block.text),
            )
    elif not pending and reused:
        provider_used = "cache"
    elif pending:
        results: dict[str, tuple[float, str, str | None, float | None]] = {}
        jev_resolved = None
        if client is not None:
            provider_used = "jev"
            jev_results, calls, latency_ms, jev_warnings, jev_resolved = _score_with_jev(
                client, pending, request
            )
            warnings.extend(jev_warnings)
            # Normalise to the quad shape the rest of this function uses.
            results = {
                block_id: (score, source, None, conf)
                for block_id, (score, source, conf) in jev_results.items()
            }
            if len(results) < len(pending):
                # partial or total Jev failure: score whatever is left mechanically
                missing = [block for block in pending if block.id not in results]
                for block_id, (s, src, prot) in _score_mechanically(
                    missing,
                    request.question,
                    protect=request.deterministic_protection,
                    question_language=question_language,
                ).items():
                    results[block_id] = (s, src, prot, None)
                if any(source.startswith("mechanical") for _, source, _, _ in results.values()):
                    provider_used = "jev+mechanical_fallback"
                    degraded = True
                    degradation_reason = "jev_batch_failed"
                    semantic_guarantee = "partial"
        else:
            provider_used = "mechanical"
            semantic_guarantee = "none"
            for block_id, (s, src, prot) in _score_mechanically(
                pending,
                request.question,
                protect=request.deterministic_protection,
                question_language=question_language,
            ).items():
                results[block_id] = (s, src, prot, None)

        # Identical content must receive an identical decision within a run. The decisions
        # cache is content-addressed, so a cold run that scores two copies of the same block
        # independently can disagree with the single cached score a warm run reuses, which
        # changes the emitted bytes. Pin the first judgment per content and reuse it.
        per_content: dict[str, tuple[float, str, str | None, float | None]] = {}
        for block in pending:
            score, source, protection, confidence = results.get(
                block.id, (0.0, provider_used, None, None)
            )
            first = per_content.setdefault(block.text, (score, source, protection, confidence))
            score, source, protection, confidence = first
            chars_after = None
            ctype = detect_content_type(block.text)
            if protection is not None:
                # The deterministic safety net keeps the block whatever overlap said. The
                # score stays as measured so the report shows both halves of that.
                decision = "keep"
                reason = protection
            elif source == "jev":
                if score >= request.threshold:
                    decision = "keep"
                    reason = "score_above_threshold"
                elif trim_threshold is not None and score >= trim_threshold:
                    if len(block.text) > request.trim_head_chars + _TRIM_HEAD_SLACK:
                        head, ok, _ = trim_block_safe(block.text, request.trim_head_chars)
                        if not ok:
                            decision = "keep"
                            reason = "trim_unsafe_kept_whole"
                        else:
                            decision = "trim"
                            reason = "score_in_trim_band"
                            chars_after = len(
                                _render_trimmed(
                                    block.text,
                                    score,
                                    trim_threshold,
                                    request.threshold,
                                    request.trim_head_chars,
                                )
                            )
                    else:
                        decision = "keep"
                        reason = "score_in_trim_band_kept_whole"
                else:
                    decision = "drop"
                    reason = "score_below_threshold"
                # Confidence is a policy input, not decoration: low confidence degrades
                # toward safety. High-risk content needs high confidence to drop at all.
                if ctype == "high_risk" and decision in ("drop", "trim") and score < 0.9:
                    decision = "keep"
                    reason = "high_risk_conservative_retention"
                    chars_after = None
                elif confidence is not None:
                    if decision == "drop" and confidence < request.confidence_threshold:
                        if confidence < request.confidence_threshold / 2:
                            decision = "keep"
                            reason = "low_confidence_kept"
                        else:
                            head, ok, _ = trim_block_safe(
                                block.text, request.trim_head_chars
                            )
                            if ok and trim_threshold is not None:
                                decision = "trim"
                                reason = "low_confidence_trimmed"
                                chars_after = len(
                                    _render_trimmed(
                                        block.text,
                                        score,
                                        trim_threshold,
                                        request.threshold,
                                        request.trim_head_chars,
                                    )
                                )
                            else:
                                decision = "keep"
                                reason = "low_confidence_kept"
                                chars_after = None
            else:
                if ctype == "high_risk" and score <= 0.0:
                    # Mechanical zero-overlap on high-risk text is not evidence of
                    # irrelevance; the fallback must err toward keeping.
                    decision = "keep"
                    reason = "high_risk_conservative_retention"
                else:
                    decision = "drop" if score <= 0.0 else "keep"
                    reason = "no_lexical_overlap" if decision == "drop" else "lexical_overlap"
            decisions[block.id] = BlockDecision(
                id=block.id,
                index=block.index,
                line_start=block.line_start,
                line_end=block.line_end,
                chars=len(block.text),
                decision=decision,
                source=source,
                score=score,
                reason=reason,
                chars_after=chars_after,
                confidence=confidence,
                relationships=(),
                policy_version=POLICY_VERSION,
                content_type=ctype,
            )
            if request.decisions_cache_path is not None:
                cache.put(
                    _cache_key_for(block.text, block.id),
                    objective=request.question,
                    block_text=block.text,
                    entry=CachedDecision(
                        score=score, decision=decision, provider=source
                    ),
                    identity=build_decision_identity(
                        objective=request.question,
                        block_text=block.text,
                        provider=request.provider,
                        model=request.jev_model,
                        policy_version=POLICY_VERSION,
                        threshold=request.threshold,
                        trim_threshold=resolved_trim,
                        trim_head_chars=request.trim_head_chars,
                        trim_policy_version=TRIM_POLICY_VERSION,
                        parser_version=BLOCK_PARSER_VERSION,
                        protection_version=PROTECTION_VERSION,
                        relationship_version=RELATIONSHIP_VERSION,
                        tokenizer_id=_tokenizer_id,
                        deterministic_protection=request.deterministic_protection,
                        relationship_context=_neighbourhood.get(block.id, None),
                    ),
                )

    # --- relationship graph + sufficiency verification (P0-6, P1-7)
    # Candidate compression asks "is this block relevant?". Sufficiency asks the second
    # question: "after these drops, can the objective still be solved from what remains?"
    # The typed graph makes cross-block dependencies explicit; the verifier restores
    # dropped evidence linked to kept content, up to a bounded restoration budget.
    relationship_edges = 0
    blocks_restored = 0
    sufficiency_checks = 0
    sufficiency_failures = 0
    sufficiency_confidence: float | None = None
    graph_relationships: dict[str, str] = {}
    _graph = None
    try:
        _qterms = _lexical_terms(request.question)
        _graph = build_graph(
            [(b.id, b.text) for b in blocks], _qterms, min_shared_terms=2
        )
        relationship_edges = len(_graph.edges)
        kept_candidate = {
            d.id for d in decisions.values() if d.decision == "keep"
        } | set(protected_reasons.keys())
        # Annotate every scored decision with the relationships touching it.
        annotated: dict[str, BlockDecision] = {}
        for bid, dec in decisions.items():
            rels = tuple(
                f"{e.type.value}:{e.target if e.source == bid else e.source}"
                for e in _graph.edges_touching(bid)
            )
            annotated[bid] = BlockDecision(
                id=dec.id, index=dec.index, line_start=dec.line_start,
                line_end=dec.line_end, chars=dec.chars, decision=dec.decision,
                source=dec.source, score=dec.score, reason=dec.reason,
                chars_after=dec.chars_after, confidence=dec.confidence,
                relationships=rels, policy_version=dec.policy_version,
                content_type=dec.content_type,
            )
        decisions = annotated
        graph_relationships = _graph.closure(kept_candidate, max_hops=1)
        # NOTE: no legacy _dependency_closures backstop here. Its union-across-frontier
        # counting (1 term from each of two kept blocks summing to 2) over-restores:
        # measured, it kept a zero-overlap funnel block via "block"+“mobile” split across
        # two different kept blocks. The graph requires >=2 shared terms with a single
        # kept block, which is the correct per-pair link strength.
    except Exception as exc:  # graph must never break compaction
        warnings.append(f"relationship_analysis_failed: {exc}")
        _graph = None
    # Restoration is part of the deterministic safety net: --no-deterministic-protection
    # disables it, so the flag keeps its meaning ("raw scoring, no safety nets") and the
    # adversarial suite can still prove what the net fixes.
    if request.enable_sufficiency and request.deterministic_protection and graph_relationships:
        sufficiency_checks += 1
        dropped_candidate = [
            bid for bid, d in decisions.items() if d.decision == "drop"
        ]
        reasons_map = {bid: d.reason for bid, d in decisions.items()}
        verdict = verify_sufficiency(
            dropped_ids=dropped_candidate,
            kept_ids={
                bid for bid, d in decisions.items() if d.decision == "keep"
            } | set(protected_reasons.keys()),
            reasons=reasons_map,
            relationships={
                bid: rel
                for bid, rel in graph_relationships.items()
                if bid in set(dropped_candidate)
            },
        )
        sufficiency_confidence = verdict.confidence
        if not verdict.sufficient:
            sufficiency_failures += 1
            # Restore critical blocks, highest semantic risk first, within budget.
            # Score = edge_count + Σconfidence + risk bonus (QUALIFIES/CONTRADICTS/
            # SUPERSEDES/DEPENDS_ON weigh more) + kept dependents. Deterministic
            # tie-break by block id so identical runs emit identical bytes.
            restorable = list(verdict.critical_dropped_blocks)
            kept_ids_for_rank = {
                bid for bid, d in decisions.items() if d.decision == "keep"
            } | set(protected_reasons.keys())

            def _restoration_score(bid: str) -> float:
                if _graph is None:
                    return 0.0 if bid in graph_relationships else -1.0
                edges = _graph.edges_touching(bid)
                if not edges:
                    return -1.0
                score = float(len(edges))
                for e in edges:
                    score += float(e.confidence or 0.0)
                    if e.type.value in (
                        "QUALIFIES",
                        "CONTRADICTS",
                        "SUPERSEDES",
                        "DEPENDS_ON",
                    ):
                        score += 1.0
                    other = e.target if e.source == bid else e.source
                    if other in kept_ids_for_rank:
                        score += 0.5
                return score

            # Prefer restoring blocks linked to kept content over pure protection hits.
            restorable.sort(key=lambda b: (-_restoration_score(b), b))
            # Bounded closure: a restored high-risk block can introduce a new
            # dependency (A kept → B restored → C depends on B) that the first
            # max_hops=1 closure never examined. Inspect immediate neighbours of
            # restored high-risk blocks one level only — never a global hops=2.
            if _graph is not None:
                primary = list(restorable)
                seen_extra: set[str] = set(primary)
                for bid in primary:
                    for e in _graph.edges_touching(bid):
                        if e.type.value not in (
                            "QUALIFIES",
                            "CONTRADICTS",
                            "SUPERSEDES",
                            "DEPENDS_ON",
                        ):
                            continue
                        if float(e.confidence or 0.0) < 0.7:
                            continue
                        other = e.target if e.source == bid else e.source
                        if (
                            other in kept_ids_for_rank
                            or other in seen_extra
                            or decisions.get(other) is None
                            or decisions[other].decision != "drop"
                        ):
                            continue
                        seen_extra.add(other)
                        restorable.append(other)
            budget = max(0, int(request.max_restorations))
            for bid in restorable[:budget]:
                existing = decisions.get(bid)
                if existing is None or existing.decision == "keep":
                    continue
                rel = graph_relationships.get(bid, "")
                decisions[bid] = BlockDecision(
                    id=existing.id, index=existing.index, line_start=existing.line_start,
                    line_end=existing.line_end, chars=existing.chars, decision="keep",
                    source=existing.source, score=existing.score,
                    reason="semantic_sufficiency_restoration",
                    chars_after=None, confidence=existing.confidence,
                    relationships=tuple([rel] if rel else list(existing.relationships)),
                    policy_version=existing.policy_version,
                    content_type=existing.content_type,
                )
                blocks_restored += 1
            if len(restorable) > budget:
                warnings.append(
                    f"sufficiency_restoration_budget_exceeded: {len(restorable)} critical "
                    f"blocks, restored {blocks_restored} (max {budget}); "
                    "KEEP more context instead of trusting this output"
                )
            else:
                warnings.append(
                    f"semantic_sufficiency_restoration: restored {blocks_restored} "
                    f"block(s) linked to kept content ({', '.join(restorable[:budget])})"
                )
            # Verify again after restoration (bounded: one re-check, no loop).
            sufficiency_checks += 1
            remaining = [
                bid for bid, d in decisions.items() if d.decision == "drop"
            ]
            verdict2 = verify_sufficiency(
                dropped_ids=remaining,
                kept_ids={
                    bid for bid, d in decisions.items() if d.decision == "keep"
                } | set(protected_reasons.keys()),
                reasons={bid: d.reason for bid, d in decisions.items()},
                relationships={
                    bid: rel
                    for bid, rel in graph_relationships.items()
                    if bid in set(remaining)
                },
            )
            sufficiency_confidence = verdict2.confidence
            if not verdict2.sufficient:
                sufficiency_failures += 1
    elif request.enable_sufficiency:
        sufficiency_checks += 1
        sufficiency_confidence = 1.0

    # --- assemble output: keep bytes exact; replace dropped runs with one marker line
    ordered: list[BlockDecision] = []
    for block in blocks:
        if block.id in protected_reasons:
            ordered.append(
                BlockDecision(
                    id=block.id,
                    index=block.index,
                    line_start=block.line_start,
                    line_end=block.line_end,
                    chars=len(block.text),
                    decision="keep",
                    source="protected",
                    score=None,
                    reason=protected_reasons[block.id],
                    confidence=None,
                    relationships=tuple(
                        f"{e.type.value}:{e.target if e.source == block.id else e.source}"
                        for e in (_graph.edges_touching(block.id) if _graph is not None else [])
                    ),
                    policy_version=POLICY_VERSION,
                    content_type=detect_content_type(block.text),
                )
            )
        else:
            ordered.append(decisions[block.id])

    dropped_ids = {decision.id for decision in ordered if decision.decision == "drop"}
    trimmed_ids = {decision.id for decision in ordered if decision.decision == "trim"}
    mutated_ids = dropped_ids | trimmed_ids
    if not mutated_ids:
        compacted = text  # byte-identical identity for keep-only runs
    else:
        pieces: list[str] = []
        index = 0
        total = len(ordered)
        while index < total:
            decision = ordered[index]
            if decision.id in dropped_ids:
                run = []
                while index < total and ordered[index].id in dropped_ids:
                    run.append(ordered[index])
                    index += 1
                pieces.append(gaps[run[0].index - 1])
                if request.marker:
                    pieces.append(
                        _marker_for_run(
                            run, request.threshold, include_scores=request.marker_scores
                        )
                    )
            else:
                pieces.append(gaps[decision.index - 1])
                if decision.decision == "trim":
                    pieces.append(
                        _render_trimmed(
                            blocks[index].text,
                            decision.score,
                            trim_threshold,
                            request.threshold,
                            request.trim_head_chars,
                        )
                    )
                else:
                    pieces.append(blocks[index].text)
                index += 1
        pieces.append(gaps[-1])
        compacted = "".join(pieces)

    first_mutation_offset: int | None = None
    for block in blocks:
        if block.id in mutated_ids:
            first_mutation_offset = block.character_start
            break

    before_count = count_tokens(text, request.model)
    after_count = count_tokens(compacted, request.model)
    if first_mutation_offset is None:
        prefix_source = compacted
    else:
        prefix_source = compacted[:first_mutation_offset]

    chars_before = len(text)
    chars_after = len(compacted)
    reduction_ratio = (chars_before - chars_after) / chars_before if chars_before else 0.0
    mutated = bool(mutated_ids)
    worth_it = (
        not mutated or request.min_reduction <= 0.0 or reduction_ratio >= request.min_reduction
    )
    if mutated and not worth_it:
        warnings.append(
            f"low_reduction: removed {reduction_ratio:.1%} of chars "
            f"(< {request.min_reduction:.0%} target); a cache epoch may not be worth it"
        )

    if after_count.method.value != "exact":
        warnings.append(
            "approximate_token_count: every token figure in this report is an estimate, not a "
            "measurement. The tokenizer assets are not cached locally and lcc will not fetch "
            "them. Set TIKTOKEN_CACHE_DIR to a populated directory before relying on any token "
            "or cost decision, or pass --require-exact-tokens to fail instead of guessing."
        )

    if request.trim_head_chars == 0 and mutated:
        warnings.append(
            "strict_keep_drop: --trim-head-chars 0 disabled the trim middle gear, so "
            "borderline-scored blocks are dropped outright instead of keeping a bounded head. "
            "Trimming is the safety net for near-miss evidence; leaving it on is the safer "
            "default."
        )

    # --- cache-epoch accounting: what the pass costs a warm prefix, and whether it can pay
    invalidated_tokens = 0
    break_even_reuses: float | None = None
    if mutated and first_mutation_offset is not None:
        prefix_tokens = count_tokens(text[:first_mutation_offset], request.model).value
        invalidated_tokens = max(0, before_count.value - prefix_tokens)
        dropped_tokens = max(0, before_count.value - after_count.value)
        if invalidated_tokens and dropped_tokens:
            # docs/CACHE_ALIGNMENT.md factors: read 0.10x, write 1.25x.
            saving_per_reuse = dropped_tokens * _CACHE_READ_FACTOR
            invalidation_cost = invalidated_tokens * (_CACHE_WRITE_FACTOR - _CACHE_READ_FACTOR)
            break_even_reuses = round(invalidation_cost / saving_per_reuse, 1)
            if break_even_reuses > 1.0:
                warnings.append(
                    f"cache_epoch_risk: this pass invalidates {invalidated_tokens} tokens at "
                    f"offset {first_mutation_offset} to drop {dropped_tokens}; it only pays off "
                    f"after ~{break_even_reuses:g} reuses of the pruned context. Protect the "
                    f"prefix (--prefix-marker/--protect-prefix) or wait for a cache epoch."
                )

    # --- marker economics: markers cost tokens too; a pass whose markers erase its
    # saving is pathological and must say so explicitly.
    if mutated and chars_after >= chars_before:
        warnings.append(
            "marker_overhead_pathological: markers consumed the entire saving; "
            "compression produced equal or larger output (use --no-marker or keep more)"
        )
    if mutated and after_count.value >= before_count.value:
        warnings.append(
            "marker_overhead_pathological: token count did not decrease after markers; "
            "the pass is not worth a cache epoch"
        )

    # --- independent semantic verification (opt-in, 1 extra Jev call max).
    # Receives ONLY {objective, candidate_context} — never scores/decisions.
    # REVIEW is signal-only: bytes stay KEEP, only the flag + warning change.
    needs_review = False
    review_reason: str | None = None
    verifier_sufficient: bool | None = None
    verifier_confidence: float | None = None
    verifier_model: str | None = None
    if request.enable_semantic_verify and mutated and client is not None:
        try:
            from lcc.relevance.verifier import verify_semantic as _verify_semantic

            verdict_sem = _verify_semantic(
                objective=request.question,
                candidate_context=compacted,
                client=client,
            )
            calls += 1
            verifier_sufficient = verdict_sem.sufficient
            verifier_confidence = verdict_sem.confidence
            verifier_model = verdict_sem.model_resolved
            if not verdict_sem.sufficient:
                needs_review = True
                review_reason = verdict_sem.reason
                warnings.append(
                    f"needs_review:{verdict_sem.reason} "
                    f"(confidence {verdict_sem.confidence:.2f}); "
                    "KEEP more context instead of trusting this output"
                )
            elif verdict_sem.contradiction_risk >= 0.7:
                needs_review = True
                review_reason = "high_contradiction_risk"
                warnings.append(
                    f"needs_review:high_contradiction_risk "
                    f"({verdict_sem.contradiction_risk:.2f}); "
                    "both sides of the contradiction were kept — verify downstream"
                )
        except Exception as exc:  # verifier must never break compaction
            warnings.append(f"semantic_verifier_failed: {exc}")
    elif request.enable_semantic_verify and mutated and client is None:
        needs_review = True
        review_reason = "verifier_unavailable_no_client"
        warnings.append(
            "needs_review:verifier_unavailable_no_client; "
            "semantic verification was requested but no Jev client exists"
        )
    # E2 safety calibration without a verifier: structural failure that survived
    # restoration, or a budget overflow, is also a REVIEW signal (bytes unchanged).
    if not needs_review and sufficiency_failures > 0 and mutated:
        # A second structural check after restoration still failing means the
        # remaining context severed a link we could not restore within budget.
        needs_review = True
        review_reason = "structural_sufficiency_unresolved"
        warnings.append(
            "needs_review:structural_sufficiency_unresolved; "
            "linked evidence was dropped and not restored within budget"
        )

    report = RelevanceCompactionReport(
        schema_version=RELEVANCE_SCHEMA_VERSION,
        provider_requested=provider_requested,
        provider_used=provider_used,
        degraded=degraded,
        objective=request.question,
        threshold=request.threshold,
        trim_threshold=trim_threshold,
        trim_head_chars=request.trim_head_chars,
        blocks_total=len(blocks),
        blocks_scored=len(scoreable),
        blocks_protected=len(protected_reasons),
        blocks_dropped=len(dropped_ids),
        blocks_trimmed=len(trimmed_ids),
        chars_before=chars_before,
        chars_after=chars_after,
        chars_removed=chars_before - chars_after,
        tokens_before=before_count.value,
        tokens_after=after_count.value,
        token_count_method=after_count.method.value,
        reduction_ratio=reduction_ratio,
        worth_it=worth_it,
        min_reduction=request.min_reduction,
        calls=calls,
        latency_ms=latency_ms,
        compilation_ms=int((time.perf_counter() - started_total) * 1000),
        reused_decisions=reused,
        prefix_protected=protect_boundary is not None,
        prefix_untouched=(
            not mutated
            or (
                protect_boundary is not None
                and first_mutation_offset is not None
                and first_mutation_offset >= protect_boundary
            )
        ),
        first_mutation_offset=first_mutation_offset,
        prefix_sha256=_sha256(prefix_source),
        output_sha256=_sha256(compacted),
        degradation_reason=degradation_reason,
        semantic_guarantee=semantic_guarantee,
        invalidated_tokens=invalidated_tokens,
        break_even_reuses=break_even_reuses,
        tokenizer=tokenizer_identity_for_count(after_count)["tokenizer"],
        tokenizer_id=tokenizer_identity_for_count(after_count)["tokenizer_id"],
        tokenizer_version=tokenizer_identity_for_count(after_count)["tokenizer_version"],
        is_estimate=after_count.method.value != "exact",
        jev_model_requested=request.jev_model,
        jev_model_resolved=jev_resolved,
        blocks_restored=blocks_restored,
        sufficiency_checks=sufficiency_checks,
        sufficiency_failures=sufficiency_failures,
        sufficiency_confidence=sufficiency_confidence,
        relationship_edges=relationship_edges,
        semantic_decisions=calls,
        semantic_cache_hits=reused,
        semantic_cache_misses=len(pending) - reused if pending else 0,
        marker_tokens=_marker_tokens(compacted, request.model),
        policy_version=POLICY_VERSION,
        trim_policy_version=TRIM_POLICY_VERSION,
        parser_version=BLOCK_PARSER_VERSION,
        protection_version=PROTECTION_VERSION,
        relationship_version=RELATIONSHIP_VERSION,
        needs_review=needs_review,
        review_reason=review_reason,
        semantic_verifier_sufficient=verifier_sufficient,
        semantic_verifier_confidence=verifier_confidence,
        semantic_verifier_model=verifier_model,
        warnings=warnings,
        decisions=ordered,
    )
    cache.flush()
    return RelevanceCompactionResult(compacted_text=compacted, report=report)


def report_to_dict(report: RelevanceCompactionReport) -> dict[str, Any]:
    """JSON-ready dict for the compaction report."""
    payload = {
        "schema_version": report.schema_version,
        "provider_requested": report.provider_requested,
        "provider_used": report.provider_used,
        "degraded": report.degraded,
        "objective": report.objective,
        "threshold": report.threshold,
        "trim_threshold": report.trim_threshold,
        "trim_head_chars": report.trim_head_chars,
        "blocks_total": report.blocks_total,
        "blocks_scored": report.blocks_scored,
        "blocks_protected": report.blocks_protected,
        "blocks_dropped": report.blocks_dropped,
        "blocks_trimmed": report.blocks_trimmed,
        "blocks_restored": report.blocks_restored,
        "chars_before": report.chars_before,
        "chars_after": report.chars_after,
        "chars_removed": report.chars_removed,
        "tokens_before": report.tokens_before,
        "tokens_after": report.tokens_after,
        "token_count_method": report.token_count_method,
        "tokenizer": report.tokenizer,
        "tokenizer_id": report.tokenizer_id,
        "tokenizer_version": report.tokenizer_version,
        "is_estimate": report.is_estimate,
        "jev_model_requested": report.jev_model_requested,
        "jev_model_resolved": report.jev_model_resolved,
        "reduction_ratio": report.reduction_ratio,
        "worth_it": report.worth_it,
        "min_reduction": report.min_reduction,
        "calls": report.calls,
        "latency_ms": report.latency_ms,
        "compilation_ms": report.compilation_ms,
        "reused_decisions": report.reused_decisions,
        "semantic_decisions": report.semantic_decisions,
        "semantic_cache_hits": report.semantic_cache_hits,
        "semantic_cache_misses": report.semantic_cache_misses,
        "sufficiency_checks": report.sufficiency_checks,
        "sufficiency_failures": report.sufficiency_failures,
        "sufficiency_confidence": report.sufficiency_confidence,
        "relationship_edges": report.relationship_edges,
        "marker_tokens": report.marker_tokens,
        "policy_version": report.policy_version,
        "trim_policy_version": report.trim_policy_version,
        "parser_version": report.parser_version,
        "protection_version": report.protection_version,
        "relationship_version": report.relationship_version,
        "prefix_protected": report.prefix_protected,
        "prefix_untouched": report.prefix_untouched,
        "first_mutation_offset": report.first_mutation_offset,
        "prefix_sha256": report.prefix_sha256,
        "output_sha256": report.output_sha256,
        "degradation_reason": report.degradation_reason,
        "semantic_guarantee": report.semantic_guarantee,
        "invalidated_tokens": report.invalidated_tokens,
        "break_even_reuses": report.break_even_reuses,
        "needs_review": report.needs_review,
        "review_reason": report.review_reason,
        "semantic_verifier_sufficient": report.semantic_verifier_sufficient,
        "semantic_verifier_confidence": report.semantic_verifier_confidence,
        "semantic_verifier_model": report.semantic_verifier_model,
        "warnings": list(report.warnings),
        "decisions": [
            {
                "id": decision.id,
                "index": decision.index,
                "line_start": decision.line_start,
                "line_end": decision.line_end,
                "chars": decision.chars,
                "decision": decision.decision,
                "source": decision.source,
                "score": decision.score,
                "reason": decision.reason,
                "chars_after": decision.chars_after,
                "confidence": decision.confidence,
                "relationships": list(decision.relationships),
                "policy_version": decision.policy_version,
                "content_type": decision.content_type,
            }
            for decision in report.decisions
        ],
    }
    return json.loads(json.dumps(payload))  # normalize tuples/sets to plain JSON types
