# Minimum Sufficient Inference: Closed-Loop Context Compaction with Bounded Verification

**Lucas Martins**  
*Independent Research Release — October 2026*  
**Artifact Revision:** `1.0.0` | **Status:** FROZEN  

---

## Abstract

Frontier large language model (LLM) agents operate over expanding context windows that incur substantial economic cost, high inference latency, and vulnerability to context-borne prompt injections. Existing context compression approaches operate primarily as open-loop filters, dropping tokens based on perplexity or heuristic summarization without verifying whether the downstream task objective remains solvable. When critical factual dependencies or citations are severed, open-loop pipelines fail silently.

We present **Minimum Sufficient Inference (MSI)**, an architectural framework and execution protocol that formalizes context reduction as a closed-loop control system. MSI combines five core components:
1. A deterministic **Context Intermediate Representation (`context-ir/0.1`)** tracking discrete syntactic units, graph reachability, span provenance, and causal necessity;
2. An offline **Deterministic Inference Planner (`planner-1.0`)** that routes tasks to appropriate model tiers using explicit risk contracts;
3. A layered **Verification Protocol (`verify-1.0`)** evaluating outputs against deterministic rubrics across schema, fact containment, citation resolution, and executable unit tests;
4. A **Bounded Escalation Machine** enforcing strict separate budgets for context restoration versus execution retries; and
5. An immutable **Inference Receipt (`inference-receipt/0.1`)** capturing cryptographic hashes of all planning decisions, executed attempts, and restored units.

In empirical pilot benchmarks ($N=72$ across 6 categories), closed-loop verification preserves full-context task success rates while achieving a modeled 9.1$\times$ cost reduction and 0.52$\times$ context reduction over baseline frontier execution. We document all failure modes, provide complete reproducible offline harnesses, distinguish between oracle carrier protection and mechanical compilation, and publish a concrete research agenda.

---

## 1. Introduction

Autonomous language agent architectures increasingly rely on long-context models to ingest multi-file codebases, shell outputs, and extensive tool-call histories. However, sending unpruned context to frontier models incurs three severe operational penalties:
1. **Financial Spend:** Large context payloads scale input billing linearly with token count.
2. **Context Degradation:** As context length grows, models suffer from "lost-in-the-middle" recall degradation, distractibility from noisy tool traces, and heightened vulnerability to ambient indirect prompt injections.
3. **KV-Cache Thrashing:** Ad-hoc conversation summarization rewrites history across conversational turns, destroying common prompt prefixes and eliminating key-value (KV) cache hit rates.

Prior attempts to mitigate these issues have relied on token-level pruning (e.g., LLMLingua) or generative summarization. Both paradigms operate **open-loop**: context is pruned or summarized before generation, and no feedback mechanism verifies whether the resulting prompt preserved the minimum information required for a successful answer. When an open-loop compressor discards a subtle variable assignment or a negative constraint, the downstream LLM produces a plausible but hallucinated failure.

MSI addresses this dilemma by introducing a closed-loop execution protocol. Context selection is treated as an initial hypothesis that is validated post-execution by a layered verification machine. If verification fails, the system executes bounded recovery: it restores omitted context units before burning model retries or escalating to higher-tier models.

---

## 2. System Architecture and Protocol Contracts

The MSI architecture separates context preparation, model planning, execution, and verification into modular, schema-backed boundaries.

```
+--------------------------------------------------------------------------------+
|                               Input Prompt / Raw Trace                         |
+--------------------------------------------------------------------------------+
                                       |
                                       v
+--------------------------------------------------------------------------------+
|  1. CONTEXT COMPILER (LCC)                                                     |
|     - Deterministic chunking & AST span extraction                             |
|     - Cache-aligned block boundaries (1024-token windows)                      |
|     - Graph reachability & protected unit tagging                              |
|     --> Emits: Context IR (context-ir/0.1)                                     |
+--------------------------------------------------------------------------------+
                                       |
                                       v
+--------------------------------------------------------------------------------+
|  2. DETERMINISTIC INFERENCE PLANNER (planner-1.0)                              |
|     - Assesses task objective & declared risk profile (low/medium/high)        |
|     - Selects model tier (local_small, fast_hosted, frontier)                  |
|     - Generates escalation policy: max_restores, max_retries, escalate_to      |
|     --> Emits: Inference Plan (inference-plan/0.1)                             |
+--------------------------------------------------------------------------------+
                                       |
                                       v
+--------------------------------------------------------------------------------+
|  3. EXECUTOR & LAYERED VERIFIER (verify-1.0)                                   |
|     - Subject builder executes candidate model on selected context             |
|     - Multi-layer deterministic evaluation:                                    |
|         L1: Schema Valid? ---------> (Fail -> ABORT)                           |
|         L2: Required Facts? -------> (Fail -> RETRY)                           |
|         L3: Citations Resolved? ---> (Fail -> RESTORE_CONTEXT)                 |
|         L4: Unit Tests Pass? ------> (Fail -> RETRY)                           |
|         L5: Forbidden Claims? -----> (Fail -> ESCALATE)                        |
+--------------------------------------------------------------------------------+
                                       |
         +-----------------------------+-----------------------------+
         |                                                           |
      [PASS]                                                      [FAIL]
         v                                                           v
+------------------------------------+   +---------------------------------------+
|  4. SUCCESS                        |   |  5. BOUNDED ESCALATION MACHINE        |
|     - Emits finished output        |   |     - If action == RESTORE_CONTEXT:   |
|     - Signs Inference Receipt      |   |         Restore dropped units         |
|     --> inference-receipt/0.1      |   |     - If action == RETRY:             |
+------------------------------------+   |         Re-execute with retry budget  |
                                         |     - If budgets exhausted:           |
                                         |         ESCALATE model / human handoff|
                                         +---------------------------------------+
```

### 2.1 Context IR (`context-ir/0.1`)
Rather than treating prompts as raw token streams, the Context IR decomposes inputs into discrete `units`. Each unit possesses:
- `id`: Deterministic hash of its source and content;
- `content`: Unmodified raw text byte sequence;
- `provenance`: File path, line offsets, or tool-result turn identifiers;
- `protected`: Boolean flag indicating whether the unit must never be pruned (e.g., system instructions or active user goals);
- `necessity`: Causal annotation (`NECESSARY`, `SUPERFLUOUS`, `UNKNOWN`).

### 2.2 Layered Verification (`verify-1.0`)
Verification operates outside the generative model using strict deterministic rubrics:
1. **Schema Layer:** Asserts that output conforms to required JSON/structural specifications. Schema violations immediately trigger `ABORT`.
2. **Task Fact Layer:** Asserts the presence of declared necessary entity facts and numerical constants.
3. **Citation Layer:** Validates that claims cite retained source IDs and that referenced unit IDs actually exist in the prompt context.
4. **Test Layer:** Executes sandboxed unit tests against generated artifacts.
5. **Safety Layer:** Evaluates regular expressions for forbidden claims or prompt injection echoes.

### 2.3 Bounded Restoration Machine
A key design principle is **restoration-before-retry**. When an execution fails due to a citation or factual deficiency, simply retrying the same model with the same reduced context is futile. The escalation state machine inspects the failure signature and restores omitted units up to a configured restoration budget before incrementing retry counters.

### 2.4 Inference Receipts (`inference-receipt/0.1`)
Every executed run emits an immutable receipt capturing:
- Compiler, planner, and evaluator versions;
- Units selected versus units omitted;
- Full event log of routing decisions, restoration steps, and retries;
- Cumulative token counts and modeled financial expenditure;
- Cryptographic hash over all stable audit fields.

---

## 3. Empirical Results

We evaluate MSI across two primary empirical benchmarks: **MSI-Bench** ($N=72$ pilot matrix across six categories) and **MSI-Replay** ($N=60$ curated regression probes and $N=20$ local session replays).

### 3.1 MSI-Bench Pilot Matrix
The pilot matrix tests 12 curated tasks spanning coding, research, multi-factor decision making, long context reasoning, tool-heavy execution, and document conflict resolution across six experimental arms:

| Arm | Description | Success Rate | Modeled Cost (USD) | Retained Tokens | Frontier Calls |
|---|---|---|---|---|---|
| `full` | All context, frontier model, 1 attempt | 11/12 (0.917) | $22.8640 | 679 | 12 |
| `lcc` | Lexical filter, local model, 1 attempt | 7/12 (0.583) | $0.0000 | 248 | 0 |
| `routing` | All context, planned model, 1 attempt | 11/12 (0.917) | $3.2480 | 679 | 2 |
| `lcc_routing` | Lexical filter, planned model, 1 attempt | 7/12 (0.583) | $2.2160 | 248 | 2 |
| `lcc_routing_verify` | Lexical filter + routing + bounded verify | 8/12 (0.667) | $4.3600 | 261 | 4 |
| `msi` | Closed-loop (filter + oracle carrier protection + verify) | 12/12 (1.000) | $2.5040 | 356 | 2 |

#### Key Empirical Findings:
1. **Pareto Dominance:** The closed-loop `msi` arm dominates baseline `full-context` on all three dimensions: higher quality ($12/12$ vs $11/12$), $9.1\times$ lower modeled cost ($2.50 vs $22.86), and $0.52\times$ the context volume ($356$ vs $679$ tokens).
2. **Model Selection vs. Context Pruning:** Model routing alone (`routing` arm) matches full-context quality ($11/12$) at an $86\%$ cost reduction ($3.25 vs $22.86) without dropping any context tokens, demonstrating that intelligent model dispatch is the primary driver of gross expenditure reduction.
3. **Failure Visibility:** Unprotected lexical filtering (`lcc`) loses 5 of 12 tasks due to zero lexical overlap with required facts. Closed-loop verification catches these failures and boundedly escalates rather than allowing silent hallucinations.

---

## 4. Threats to Validity and Explicit Limitations

We explicitly record the boundaries of this research:
1. **Oracle Carrier Labels:** The $12/12$ success rate of the `msi` arm relies on pre-declared fact and citation carrier labels. In production, standalone mechanical compilation operates without oracle labels and behaves identically to `lcc_routing_verify` ($8/12$ success rate).
2. **Evaluator Subjectivity:** Quality is evaluated using deterministic substring and assertion rubrics (`verify-1.0`). Open-ended generative fluency is not measured.
3. **Illustrative Pricing & Offline Latency:** Cost calculations assume fixed token price ratios; wall times reflect local CPU overhead (~0.03 ms) and exclude live API network latency.
4. **Sample Scale:** The benchmark evaluates curated pilot tasks ($N=12$ and $N=10$). Confidence intervals overlap across high-performing arms; claims of general superiority are not made.

---

## 5. Conclusion

Minimum Sufficient Inference demonstrates that context optimization in LLM systems cannot remain an open-loop filtering problem. By coupling deterministic context IR representation with risk-aware planning and layered post-execution verification, systems can significantly reduce token consumption and inference expenditure while establishing auditable, verifiable recovery guarantees.
