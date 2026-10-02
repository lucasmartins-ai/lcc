# MSI Target Architecture v0 (Sprint-0 baseline)

## Component + data flow

```mermaid
flowchart TB
    U[User / Agent] --> TC[1. Task compilation\nraw request → Task Contract]
    TC --> LCC[2. LCC context compilation\ncontext → Context IR → working set]
    LCC --> CT[3. Cognitive triage\nambiguity/risk/complexity/confidence]
    CT --> IP[4. Inference planner/router\nmodel + reasoning + tools + budget]
    IP --> EX[5. Execution]
    EX --> V[6. Verification\ndeterministic + semantic + task]
    V -->|PASS| R[Result + Inference Receipt]
    V -->|FAIL| RST[Restore / Retry / Escalate\nbounded, fail-closed]
    RST --> LCC
    RST --> IP
    RST --> EX
```

## Failure / restoration flow

```mermaid
sequenceDiagram
    participant E as Execution
    participant V as Verification
    participant C as Context IR
    participant P as Planner
    V->>V: checks (schema/assert/citation/tests/semantic/policy)
    alt PASS
        V->>R: Receipt (incl. omitted + rationale)
    else REVIEW/FAIL
        V->>C: RESTORE_CONTEXT (linked drops, bounded budget)
        C->>E: RETRY same plan
        E->>V: re-verify once
        alt still failing
            V->>P: INCREASE_REASONING / SWITCH_MODEL / ADD_TOOL
            P->>E: retry with new plan
            alt still failing
                V->>H: ESCALATE (human/stronger tier) or ABORT
            end
        end
    end
```

Note: verifier never re-runs on its own output (LCC `verifier.py` precedent: single-shot, no loop). Retries bounded; every transition logs a decision event with reason.

## Repository boundaries

- **LCC**: context → Context IR → working set + sufficiency + restoration metadata. No provider routing, no model execution.
- **MSI spec** (new `minimum-sufficient-inference` repo, spec-only at first): Task Contract, Context IR, Inference Plan, Verification Result, Inference Receipt schemas + versioning. No LCC implementation duplication.
- **Triage engines**: pluggable behind `(decision, confidence, escalate_risk) → route`. Jev = one adapter (from triage-benchmark gate), alongside deterministic policy / small local model / rules.
- **Verification**: protocol extracted from AgentTrace (`checks.py`/`ci_gate.py`/citation_auditor shape), not a product dependency.
- **lookaorchestrator**: consumer/testbed only; traces flow out, specs never depend on it.
- **recallgraph-ai**: pattern reference only.
- **lcc-act2-router / agentic-prompt-intake**: no boundaries — archived or spec-only (see 04).
