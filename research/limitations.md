# Limitations and Research Agenda

**Document version:** 1.0.0  
**Freeze date:** 2026-10-03  
**Status:** RELEASE-FROZEN  

This document consolidates all known failure modes, structural constraints, unmeasured operational dimensions, and threats to validity for the Minimum Sufficient Inference (MSI) framework and Local Context Compiler (LCC). Following this, it outlines five precise, falsifiable research questions for future investigation.

---

## Part I: System Limitations

### 1. Scope of the Compiler vs. the Oracle Probe
- **Oracle gap in benchmarks:** In `MSI-Bench` (Sprint 7) and `MSI-Replay` (Sprint 9 curated track), the high-performing `msi` arm uses exact fact-carrier and citation-carrier labels (`tasks.py::carriers`) to protect critical context units. This constitutes an **oracle probe** demonstrating the theoretical upper bound of closed-loop execution.
- **Standalone mechanical compiler:** The public production compiler (`lcc compact` or `lcc compile` in `--provider mechanical` mode) operates purely via lexical overlap, structural AST rules, and deterministic graph reachability. It possesses **zero semantic reasoning**. Where query vocabulary does not overlap fact vocabulary, lexical compaction will drop necessary facts unless protected by user configuration or an opt-in semantic judge (`--provider laya` or `--provider jev`).

### 2. Evaluator and Verification Constraints
- **Sub-symbolic evaluation is absent:** The evaluator (`verify-1.0`) relies on deterministic layers: JSON schema validation, exact-substring fact containment, regex forbidden claims, declared citation resolution, and executable unit tests. It does **not** evaluate stylistic nuance, creative coherence, persuasive quality, or factual validity outside declared substrings.
- **Rubric dependency:** All measured success rates are conditional on this specific rubric. A run that produces a syntactically valid JSON string containing the required substrings is marked `PASS` even if an unmeasured dimension of quality is deficient.
- **First-failure precedence:** In the escalation protocol, failure handling resolves sequentially (`schema -> task -> citation -> tests -> policy`). If a task simultaneously drops a required fact and a citation, the machine resolves to `RETRY` rather than `RESTORE_CONTEXT`, because the task layer precedes the citation layer.

### 3. Cost and Latency Modeling
- **Illustrative pricing:** All dollar values in research reports ($22.864 for full-context, $2.504 for MSI, etc.) are **modeled prices** based on a fixed illustrative pricing schedule ($0.00/1k local, $0.50/$1.50 hosted, $8.00/$24.00 frontier). They do not represent live vendor billing, spot discounts, or enterprise volume pricing. Only the cost *ordering* (local < hosted < frontier) is structural.
- **Deterministic overhead only:** Reported execution latency (e.g., ~0.03 ms per run) measures only the local Python wall-clock execution of the planner, subject-builder, and verifier. **Zero live network or model inference latency is measured in the benchmark matrix.** In a production deployment, actual end-to-end latency depends on provider TTFT (time to first token) and inter-attempt retry round-trips.

### 4. Safety and Adversarial Dynamics
- **No render-time injection defense:** In `toolheavy-02`, keeping full context forwards an injected instruction, causing `full-context` to FAIL. Conversely, aggressive filtering drops the injection simply because it lacks query vocabulary overlap, allowing thin arms to PASS. This is an artifact of lexical selection, **not a robust adversarial defense**.
- **Co-located injection risk:** When an adversary embeds a prompt injection inside a legitimate required-fact block, any selector that retains the fact will also forward the attack payload (as demonstrated in Sprint 9 probe fixture `f1-colocated-injection.json`).

### 5. Sample Size and Generalization
- **Pilot and Curated Scales:** `MSI-Bench` consists of $N=12$ hand-authored tasks; `MSI-Replay` consists of $N=10$ curated traces and $N=10$ local session windows. These small sample sizes mean that bootstrap confidence intervals overlap substantially across arms (e.g., $[0.750, 1.000]$ vs $[1.000, 1.000]$). Overlapping intervals mean **we cannot claim statistical superiority** on general tasks.
- **Absence of human subject testing:** Usability is measured via automated scripted runs ($36/36$ checks, 12 scenarios $\times$ 3 repetitions, 3.14 s first compile). No human developer trial, cognitive load survey, or learning curve study was conducted.

---

## Part II: Research Agenda

The following five research questions represent open investigations required to advance minimum sufficient inference beyond the pilot stage. Each question is phrased as a falsifiable hypothesis with a measurable validation criterion.

### Question 1: Non-Oracle Semantic Carrier Identification
> **Can a sub-100M parameter edge model identify necessary fact carriers with $\ge 95\%$ recall without accessing evaluation task rubrics?**
- *Hypothesis:* A distilled sequence-tagging model trained exclusively on syntax trees and discourse relations can identify dependent clauses and entity citations, closing $\ge 80\%$ of the performance gap between mechanical filtering and the oracle `msi` arm.
- *Falsification Criterion:* If the edge tagger drops more than 5% of ground-truth carriers on a disjoint held-out test set ($N \ge 200$), the hypothesis is rejected.

### Question 2: Real-World Latency Breakeven in Provider Cascades
> **Under multi-tenant API conditions (OpenAI, Anthropic), does the network latency saved by sending fewer input tokens exceed the latency penalty incurred by verification and retries?**
- *Hypothesis:* For context windows $> 16\text{k}$ tokens, a single verified de-escalation from frontier to hosted/local models yields a net reduction in end-to-end wall time ($p_{50}$ and $p_{95}$) even when 15% of tasks require a restoration attempt.
- *Falsification Criterion:* If measured wall-clock time across 500 live API calls is higher for the closed-loop arm than the baseline full-context arm, the latency benefit hypothesis is rejected.

### Question 3: Automatic Cross-Turn Context Graph Inference
> **Can causal dependency edges between conversational turns be inferred with zero false-dependency drops using AST and static dataflow analysis alone?**
- *Hypothesis:* Static analysis of code blocks, shell commands, and file paths in tool outputs can identify prerequisite context units without requiring language model inference.
- *Falsification Criterion:* If static graph extraction fails to retain an essential prerequisite unit in $> 2\%$ of multi-turn tool sessions ($N \ge 100$), the deterministic extraction hypothesis fails.

### Question 4: Benchmark Transfer to General Agentic Software Engineering
> **Does closed-loop context compaction maintain task resolution rates on SWE-bench Lite while reducing frontier model token spend by $\ge 30\%$?**
- *Hypothesis:* Applying LCC tool-call transcript compaction and bounded verification to an open-source agent framework (e.g., Aider or SWE-agent) will achieve parity in issue resolution rates ($\pm 2\%$ margin) while cutting input token volume by at least 30%.
- *Falsification Criterion:* A statistically significant drop ($p < 0.05$ under McNemar's test) in SWE-bench Lite issue resolution.

### Question 5: Disentanglement of Injected Instructions in Protected Spans
> **Can token-level span attribution isolate and redact prompt injections without destroying adjacent required facts co-located within the same source file?**
- *Hypothesis:* Parsing context units into discrete syntax spans and applying differential attention attribution allows stripping imperative commands while preserving declarative facts.
- *Falsification Criterion:* If redaction destroys more than 3% of legitimate assertions or fails to suppress $> 90\%$ of indirect injections across a benchmark of 100 adversarial payloads.
