# Prior-Art Review and Claims Audit

**Document version:** 1.0.0  
**Freeze date:** 2026-10-03  
**Status:** RELEASE-FROZEN  

This document reviews existing academic and industrial work related to the Minimum Sufficient Inference (MSI) framework and Local Context Compiler (LCC). It classifies technical contributions into prior art, incremental adaptations, and MSI-specific architectures, establishing a rigorous null hypothesis: **no claim of novelty or superiority is made without a paired experimental measurement or formal prior-art citation.**

---

## 1. Related Work Taxonomy

### 1.1 Context Compression and Prompt Pruning

| System / Paper | Mechanism | Comparison with LCC / MSI |
| --- | --- | --- |
| **LLMLingua** (Jiang et al., EMNLP 2023) | Uses a small language model (e.g., LLaMA-7B or GPT-2) to compute token perplexity; removes low-information tokens. | Non-deterministic, requires GPU/model inference for pruning, produces ungrammatical text fragments that destroy byte-faithfulness and prompt caching. LCC operates deterministically by default (no model required) and preserves whole syntactic units byte-for-byte. |
| **LongLLMLingua** (Jiang et al., ACL 2024) | Extends LLMLingua with question-aware reranking and dynamic budget allocation for long-context question answering. | Still model-dependent for filtering; lacks closed-loop execution verification or structured provenance. LCC Context IR tracks exact span provenance, graph dependencies, and causal necessity. |
| **Selective Context** (Li et al., 2023) | Computes token-level self-information (negative log-likelihood) using small base models and filters tokens below percentile thresholds. | Suffers from paraphrase sensitivity and boundary destruction; does not account for tool call structures or KV-cache prefix boundaries. |
| **AutoCompressor** (Chevalier et al., NeurIPS 2023) | Compresses long contexts into learned dense summary vectors ("summary tokens"). | Incompatible with commercial black-box APIs (OpenAI, Anthropic) which only accept discrete text tokens; breaks exact byte-matching and cache reuse. |
| **Prompt Compression via Summarization** (Standard LLM Agent pattern) | Calls an LLM to "summarize previous messages" into natural language prose. | High latency, high token cost for the summary call itself, hallucination risk, and destruction of exact quotations, IDs, and code syntax. LCC replaces whole-conversation rewriting with structured tool-result retention and cache-aligned boundaries. |

### 1.2 Model Routing and Cascading

| System / Paper | Mechanism | Comparison with LCC / MSI |
| --- | --- | --- |
| **FrugalGPT** (Chen et al., NeurIPS 2023) | Sequential cascade: queries cheaper LLMs first, uses a learned scoring function to decide if the answer is acceptable, escalates to larger models if score is below threshold. | FrugalGPT relies on a continuous quality scorer trained on task data; does not compress context or verify structural invariants. MSI integrates model routing with context selection, deterministic risk overlays, and multi-layer deterministic verification. |
| **RouteLLM** (Ong et al., 2024) | Evaluates preference router models (matrix factorization, BERT, causal LLMs) to dispatch queries between cheap and strong models. | Focuses on single-turn prompt-to-model routing without context compaction, recovery stages, or execution receipts. MSI routes using a deterministic risk contract (`DeterministicPlanner`) coupled to escalation budgets. |
| **Hybrid LLM Systems** (Ding et al., 2024) | Routes between edge/local models and cloud models based on task intent and system resource constraints. | Focuses on device latency and bandwidth. LCC implements this via `--provider laya` (local non-autoregressive classifier) and `--provider jev` (remote System 1 API) with fail-closed mechanical fallback. |

### 1.3 Agent Verification and Error Recovery

| System / Paper | Mechanism | Comparison with LCC / MSI |
| --- | --- | --- |
| **ReAct** (Yao et al., ICLR 2023) | Interleaves reasoning traces and action execution in-context. | Self-guided; errors accumulate in the prompt context, causing context bloat and degraded performance over extended horizons. |
| **Reflexion** (Shinn et al., NeurIPS 2023) | Evaluates task feedback and generates linguistic self-reflections that are appended to working memory for subsequent trials. | Reflective verbal feedback consumes additional context tokens in subsequent attempts. MSI enforces a strict separation: verification is external and deterministic (`verify-1.0`), and error handling triggers bounded context restoration or model escalation with immutable receipts (`inference-receipt/0.1`). |
| **Self-Refine** (Madaan et al., NeurIPS 2023) | Iterative generation, feedback, and refinement using the same language model. | Relies on generative self-evaluation (susceptible to confirmation bias and sycophancy). MSI uses deterministic, non-generative rubric layers (schema, required facts, forbidden claims, citation resolution, unit tests). |

---

## 2. Classification of Contributions

To maintain academic and engineering integrity, contributions are strictly categorized:

### 2.1 Prior Art (Existing Foundations Reused)
1. **Lexical Token Matching:** Standard stopword filtering and set-intersection over word tokens (Lucene, BM25, standard IR).
2. **Token Accounting:** BPE tokenization estimates (cl100k_base / tiktoken) and character heuristics.
3. **Multi-Model Escalation:** Cascading from small/local to frontier models upon failure (FrugalGPT concept).
4. **Unit Test Verification:** Running automated test suites against code outputs (standard automated software engineering).

### 2.2 Incremental Adaptations
1. **Cache-Aligned Compaction:** Aligning compaction cuts to fixed token boundaries (e.g., 1024-token blocks) to preserve upstream KV-cache prefix hits across conversational turns.
2. **Transcript Tool-Result Compaction:** Pruning redundant tool outputs while strictly pinning user goals and system prompts (`transcript-compaction-1.0`).
3. **Pluggable Non-Autoregressive Classifier:** Employing a lightweight token classification backend (Laya / Jev) for binary sentence-level keep/drop judgments without generating text.

### 2.3 MSI-Specific Architectural Contributions
1. **Context IR (`context-ir/0.1`):** A standardized, deterministic graph representation of prompt context with explicit unit IDs, span provenance, structural/dependency edges, protection flags, and causal necessity annotations.
2. **Layered Verification Protocol (`verify-1.0`):** An external, deterministic evaluation machine with six explicit layers (schema, task/facts, citations, tests, safety/forbidden claims, policy) operating with tri-state outcomes (`PASS`, `FAIL`, `ABORT`).
3. **Bounded Restoration-Before-Retry:** An escalation state machine with strict, separate budgets for restoring omitted context units versus burning retries, preventing infinite recovery loops.
4. **Auditable Inference Receipt (`inference-receipt/0.1`):** A machine-verifiable, cryptographically hashed JSON artifact recording every planning decision, execution attempt, restored unit, verification failure reason, and modeled cost.
5. **Honest Oracle vs. Compiler Distinction:** Explicit separation in research benchmarks between oracle-guided unit protection (experimental upper bound) and public mechanical compilation (production reality).

---

## 3. Claims Audit

Every document across the repository has been audited against unmeasured superlatives and marketing vocabulary. The findings are summarized below:

| Audited Term | Occurrence Status | Audit Finding & Action |
| --- | --- | --- |
| **"Novel"** | 0 unbacked occurrences | Retained only in protocol rules prohibiting unbacked novelty claims ("sem prior-art, sem claim de novidade"). |
| **"SOTA" / "State of the Art"** | 0 occurrences | Zero claims of SOTA performance exist in the codebase, documentation, or paper. |
| **"First"** | All contextual | Occurrences refer to "local-first" architecture, "first compile" benchmark timings, "first message" in transcripts, or "first implementation slice" in roadmap. No claim of being "the first system to X" exists. |
| **"Best"** | 1 descriptive occurrence | Used in `docs/LAYA.md` as "Strongest judgment on subtle/paraphrased evidence" for Jev vs local heuristics; verified as comparative guidance between internal options, not a claim against external systems. |
| **"Guarantee"** | Explicitly qualified | Used in `README.md` to state that local timings are *not* a guarantee for other machines, and in `semantic_guarantee: none` to explicitly disclose when a pass lacked semantic validation. |

### Summary of Audit Verdict
- **No unbacked claims of superiority or novelty exist in the release.**
- All reported metrics specify dataset, sample size ($N$), exact configuration, commit hash, and reproduction command.
- Where a method underperformed (e.g., lexical filtering losing 5/12 tasks without protection; full-context failing injection tests; 25/60 curated probe failures), the failures are highlighted alongside the successes.
