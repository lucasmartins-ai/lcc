# Repository Boundaries & Decisions (Sprint 0)

## lcc — KEEP, authoritative for context compilation
Owns: ingestion, normalization, relevance, graph, protection, selection, sufficiency, restoration, Context IR implementation, compilation receipts (precursor). Must stay independently useful; no orchestration creep. Next: implement Context IR schema (Sprint 2), keep CLI compat.

## agentic-prompt-intake — MERGE-as-spec-only (or ARCHIVE)
LCC intake is a strict superset (4 states incl. BLOCKED + deterministic parser + pipeline). No code merge. At most: port installer UX idea or reference its schema as portable profile. Decision needed in Sprint 1: adapter vs independent (default: independent, frozen).

## cognitive-triage-benchmark — EXTRACT interface, keep repo as research artifact
Extract: `(decision, confidence, escalate_risk) → local/escalate` gate + pricing/loss constants + dataset/metrics template. Do not depend on its scripts, remote-only Jev wiring, or SYNTHETIC-trained thresholds. Alternative engines mandatory (deterministic policy first).

## agenttrace-studio — EXTRACT protocol, no product dependency
Extract: 9-check assertion shape, ci-gate threshold shape, citation_auditor pattern, redaction/policy pattern, observability reason codes, eval-case JSON shape. MSI verification must run without AgentTrace installed.

## lookaorchestrator — consumer/testbed only (private)
May supply replayed/anonymized traces and receive MSI concepts. Public specs stay independent of its business logic. No code import either direction until Sprint 9, then via versioned interfaces.

## lcc-act2-router — ARCHIVE (or clearly reposition)
Strict subset of LCC without router or relevance; last touched 2026-07-04. No maintenance as parallel product. Salvage option: its 6 benchmark cases → MSI-Bench seeds. Needs owner sign-off before archiving (Sprint 1).

## recallgraph-ai — reference only
Reuse patterns (source_record lineage, content-hash idempotency, citation objects, deterministic rerank, abstention, risk scoring, audit gate), never domain logic.

## New: minimum-sufficient-inference — spec repo (create in Sprint 1)
Contains README, docs/theory+architecture+terminology, `spec/*.schema.json`, research agenda/methodology, benchmarks/README, examples. No LCC implementation copy.
