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
from lcc.relevance.decisions import CachedDecision, DecisionCache, decision_key
from lcc.relevance.jev import JevClient, JevError
from lcc.token_budget import count_tokens

RELEVANCE_SCHEMA_VERSION = "relevance-compaction-1.1"

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
    provider: str = "auto"  # auto | jev | mechanical
    model: str = "gpt-4.1"  # token counting model (ADR 0005 honesty contract)
    jev_model: str = "jev-latest"
    protect_prefix_chars: int | None = None
    prefix_marker: str | None = None
    decisions_cache_path: Path | None = None
    client: JevClient | None = None  # dependency injection for tests


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
    """Rendered form of a trimmed block: bounded head plus one audit note line."""
    head = block_text[:head_chars]
    if score is None:
        score_part = ""
    elif trim_threshold is not None:
        score_part = f", score {score:.2f} in band {trim_threshold:.2f}-{threshold:.2f}"
    else:
        score_part = f", score {score:.2f}"
    return (
        f"{head.rstrip()}\n"
        f"[lcc-compact: trimmed {len(block_text) - head_chars} of {len(block_text)} chars "
        f"of this block{score_part}]"
    )


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
) -> tuple[dict[str, tuple[float, str]], int, int, list[str]]:
    """Score blocks with Jev, concurrently when several batches exist.

    Returns (results, calls, latency_ms, warnings). A failed batch does not abort the
    remaining ones: blocks left without an answer are reported so the caller scores them
    mechanically (fail-safe, unchanged contract).
    """
    results: dict[str, tuple[float, str]] = {}
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
    for batch_index, response, batch_latency, failure in outcomes:
        latency_ms += batch_latency
        if response is None:
            fallback = failure or f"jev_batch_{batch_index}_failed: unknown; scored mechanically"
            warnings.append(fallback)
            continue
        calls += 1
        batch = batches[batch_index - 1]
        answers = response.get("answers") or {}
        for block in batch:
            answer = answers.get(f"keep_{block.id}") or {}
            noul = answer.get("noul")
            if isinstance(noul, (int, float)):
                results[block.id] = (float(noul), "jev")
        for block in batch:
            if block.id not in results:
                warnings.append(f"jev_missing_answer:{block.id}")
    return results, calls, latency_ms, warnings


def _score_mechanically(
    blocks: list[TextBlock], question: str
) -> dict[str, tuple[float, str]]:
    """Local fallback: drop only blocks with zero lexical overlap with the objective."""
    question_terms = _lexical_terms(question)
    if not question_terms:
        # No objective terms: nothing can be judged irrelevant locally; keep everything.
        return {block.id: (1.0, "mechanical") for block in blocks}
    results: dict[str, tuple[float, str]] = {}
    for block in blocks:
        overlap = question_terms & _lexical_terms(block.text)
        denominator = max(1, min(6, len(question_terms)))
        score = round(min(1.0, len(overlap) / denominator), 2)
        results[block.id] = (score, "mechanical")
    return results


def compact_context(request: RelevanceCompactionRequest) -> RelevanceCompactionResult:
    """Run an opt-in relevance compaction pass over ``request.text``."""
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
    cache = DecisionCache(request.decisions_cache_path)
    cache.load()
    decisions: dict[str, BlockDecision] = {}
    pending: list[TextBlock] = []
    reused = 0
    for block in scoreable:
        key = decision_key(request.question, block.text)
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
            )
    elif not pending and reused:
        provider_used = "cache"
    elif pending:
        results: dict[str, tuple[float, str]] = {}
        if client is not None:
            provider_used = "jev"
            results, calls, latency_ms, jev_warnings = _score_with_jev(client, pending, request)
            warnings.extend(jev_warnings)
            if len(results) < len(pending):
                # partial or total Jev failure: score whatever is left mechanically
                missing = [block for block in pending if block.id not in results]
                results.update(_score_mechanically(missing, request.question))
                if any(source == "mechanical" for _, source in results.values()):
                    provider_used = "jev+mechanical_fallback"
                    degraded = True
                    degradation_reason = "jev_batch_failed"
                    semantic_guarantee = "partial"
        else:
            provider_used = "mechanical"
            semantic_guarantee = "none"
            results = _score_mechanically(pending, request.question)

        # Identical content must receive an identical decision within a run. The decisions
        # cache is content-addressed, so a cold run that scores two copies of the same block
        # independently can disagree with the single cached score a warm run reuses, which
        # changes the emitted bytes. Pin the first judgment per content and reuse it.
        per_content: dict[str, tuple[float, str]] = {}
        for block in pending:
            score, source = results.get(block.id, (0.0, provider_used))
            first = per_content.setdefault(block.text, (score, source))
            score, source = first
            chars_after: int | None = None
            if source == "jev":
                if score >= request.threshold:
                    decision = "keep"
                    reason = "score_above_threshold"
                elif trim_threshold is not None and score >= trim_threshold:
                    if len(block.text) > request.trim_head_chars + _TRIM_HEAD_SLACK:
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
            )
            if request.decisions_cache_path is not None:
                cache.put(
                    decision_key(request.question, block.text),
                    objective=request.question,
                    block_text=block.text,
                    entry=CachedDecision(
                        score=score, decision=decision, provider=source
                    ),
                )

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
        "chars_before": report.chars_before,
        "chars_after": report.chars_after,
        "chars_removed": report.chars_removed,
        "tokens_before": report.tokens_before,
        "tokens_after": report.tokens_after,
        "token_count_method": report.token_count_method,
        "reduction_ratio": report.reduction_ratio,
        "worth_it": report.worth_it,
        "min_reduction": report.min_reduction,
        "calls": report.calls,
        "latency_ms": report.latency_ms,
        "reused_decisions": report.reused_decisions,
        "prefix_protected": report.prefix_protected,
        "prefix_untouched": report.prefix_untouched,
        "first_mutation_offset": report.first_mutation_offset,
        "prefix_sha256": report.prefix_sha256,
        "output_sha256": report.output_sha256,
        "degradation_reason": report.degradation_reason,
        "semantic_guarantee": report.semantic_guarantee,
        "invalidated_tokens": report.invalidated_tokens,
        "break_even_reuses": report.break_even_reuses,
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
            }
            for decision in report.decisions
        ],
    }
    return json.loads(json.dumps(payload))  # normalize tuples/sets to plain JSON types
