# MSI Sprint 0 — Current State (verified against code, 2026-10-02)

> Rule: README claims separated from code. Status labels: implemented / experimental / planned / deprecated / research-only.

## 1. lcc (`/Users/Master/LCC`, v1.0.0, branch `fix/thread-safe-guard-and-laya-cache`, dirty)

**Purpose:** deterministic, local-first context compiler: clean → dedupe → relevance-compact (verbatim, never summarize) → sufficiency/restore → report. Thesis in ADR 0014/0015: smallest context preserving task outcome.

**Implemented (code-verified):**
- Deterministic core: `src/lcc/cleaning/`, `token_budget/`, `inspection/`, `pipeline.py`, `lexical_selection.py`, `compressor.py`. Offline, stdlib + typer/rich/yaml; tiktoken optional.
- Intake: `src/lcc/intake/parser.py` — 4 states (`READY_TO_EXECUTE`, `NEEDS_LIGHT_REFINEMENT`, `NEEDS_INTAKE`, `BLOCKED`) + scores/questions/assumptions/brief; `pipeline.py: IntakeResult`.
- Relevance compaction `src/lcc/relevance/`: providers `mechanical` (offline lexical), `laya` (local 512/1024 budget, `HEAD_RESERVATION 192`, fail-safe keep), `jev` (remote System One, 32K pre-flight guard `JevStateTooLargeError`); `blocks.py`, `decisions.py` (sticky cache epochs, ADR 0013), `graph.py` (7 edge types, lexical construction), `sufficiency.py` (structural/dependency guard), `verifier.py` (independent PASS/REVIEW/FAIL, single-shot, no loop), `trim.py` (type-aware), `transcript.py` (tool-call mode), `safety.py`, `jev.py`, `laya.py`.
- Router `src/lcc/router/`: deterministic `policy.py::choose_route` → `LOCAL_THEN_VERIFY` / `COMPRESS_THEN_LOCAL` / `COMPRESS_THEN_REMOTE` / `REMOTE_DIRECT`; `features.py`, `schemas.py:RouteDecision`, `token_accounting.py`.
- Agents `src/lcc/agents/`: `local_agent.py` (Gemma 4 e4b / Qwen3.5-4B via ollama), `local_verifier.py`, `cloud_client.py` (Fireworks escalation).
- Surfaces: CLI (`intake/optimize/inspect/agent/route/compact/explain/mcp/bench`), MCP stdio server, Python + Node APIs (Node = deterministic cleaning only, ADR 0014 parity boundary).
- Evidence: `benchmarks/research/` stress matrix (mechanical −26→−70%, Jev −21→−52%, Laya ≈0% @100% recall, N small), `TRANSCRIPT_AB.md` (vs fast-jev-compaction), `REAL_SESSIONS.md` (−66%/−82%, texts preserved), `RESEARCH_STATUS.md` (CURRENT/EXPERIMENTAL/HISTORICAL/BENCHMARK split). Tests: 283+ pytest + node + `test_docs.py`.

**Experimental:** semantic verifier (`--semantic-verify`, REVIEW-heavy 30/20/0 over 50 tasks, FAIL band unobserved); Laya typed-decisions checkpoint; tool-call mode.
**Planned (roadmap, not code):** Node `compact` parity, cloud infra.
**Gaps vs MSI:** no versioned Context IR schema (has `relevance-compaction-1.2` report, not IR); no unified Task Contract (has ParsedIntake/TaskInput/TaskFeatures fragments); no Inference Plan / Inference Receipt (has report.json + cache accounting); no causal ablation harness (has comparative/AB, not remove-and-replay).

## 2. cognitive-triage-benchmark (1 commit `a133294`, no tests/)

**Implemented:** `scripts/` ×7 (dataset gen, benchmark_suite 610L, Antigravity runner, hybrid gate, analysis, charts, final report); `data/dataset_1200.json` (SYNTHETIC N=1200, 7 cats); `results/` ×7; `PAPER.md` (=TR-2026-004). Gate `integrate_agy_results.py:151`: escalate iff `j_dec==escalate OR risk≥0.60 OR conf<0.65`. Remote Jev + OpenRouter Gemini, keys via env.
**Claim (unverified here):** 58.2% calls eliminated, p50 16.2s→0.33s, $27.19→$11.43/1K, F1 75.7 vs 74.0 (p=0.507). Status: **research-only**, SYNTHETIC, no pytest.
**Reusable:** pricing/loss constants (`C_FN=10,FP=2,EM=5`), `(decision,confidence,escalate_risk)→route` interface, dataset schema, metrics template.

## 3. agenttrace-studio (1 commit `f22e4bb`, 19 test files, pnpm monorepo)

**Implemented:** `services/agent-api/` (issue_triage workflow → citation_auditor, deterministic hybrid RAG, `evals/checks.py` 9 checks, `evals/ci_gate.py` 100%/0-regression gate, observability reason taxonomy, github import allowlist+redaction); `evals/cases/` 10 JSON + smoke suite + baselines; `apps/web` Next.js; CI gate workflow; docker-compose.
**Stubs (planned, not code):** eval-worker no-op, empty `prompts/*/`, placeholder prompt-registry/shared-types, no live model provider / LLM judges / Langfuse / auth / billing.
**Reusable:** `checks.py` + `ci_gate.py` + citation_auditor + redaction/policy + observability codes + case schema → MSI verification protocol source.

## 4. agentic-prompt-intake (v0.4.0, JS, 1 commit, no tests/)

**Implemented:** `schemas/intake-router.schema.json` (3 states — **no BLOCKED**), `prompts/`, `templates/`, `bin/cli.js` installer, `evals/intake-cases.jsonl`, `scripts/validate_structure.py`.
**Verdict:** ~100% duplicated by LCC `src/lcc/intake/` (superset: +BLOCKED, deterministic parser, pipeline composition). Keep as portable spec at most; no logic merge.

## 5. lcc-act2-router (1 commit 2026-07-04, 13 test files)

**Implemented:** deterministic clean/dedupe/lexical/token-budget/templates/inspection/benchmarking + 6 cases. **No router/policy, no relevance/.**
**Verdict:** strict subset of LCC, obsolete. Archive/reposition; at most salvage benchmark cases.

## 6. recallgraph-ai (1 commit `e01b55b`, 16 unit + 8 integration tests)

**In code:** fixture parsers (openFDA/CPSC/SEC_EDGAR), hybrid retrieval + deterministic rerank + citations + injection rejection + abstention, `scoring/risk.py` (severity/novelty/velocity/exposure/reliability), entity resolution, model_registry, traces, citation-audit gate + human-review routing, `source_record` lineage + content-hash idempotency.
**Claim-only:** evidence/knowledge graphs (no graph code). `services/*` = placeholder READMEs.
**Role:** reference patterns only (provenance, determinism, auditability, risk scoring). No domain logic import.

## 7. lookaorchestrator (private, uninspectable)

Role: integration testbed / trace source only. No spec coupling to its business logic.
