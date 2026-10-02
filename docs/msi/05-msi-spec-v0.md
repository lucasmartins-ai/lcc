# MSI Spec v0 (draft, provider-independent, pre-validation)

Status: `experimental`, version `0.1`. All schemas carry `schema_version`. No provider-specific (Jev/OpenAI/Anthropic) fields in core.

## 1. Task Contract (`task-contract.schema.json`)

```json
{
  "schema_version": "task-contract/0.1",
  "task_id": "uuid",
  "objective": "string",
  "task_type": "coding | investigation | multi_tool | research | structured_decision | long_running | other",
  "success_criteria": [{"id": "string", "statement": "string", "evaluator": "human | test | assertion | judge | other"}],
  "constraints": ["string"],
  "risk_level": "low | medium | high | unknown",
  "required_capabilities": ["string"],
  "allowed_tools": ["string"],
  "quality_threshold": 0.95,
  "budget": {"latency_ms": 3000, "cost_usd": 0.02, "tokens": 20000}
}
```

LCC today has fragments (`ParsedIntake`, `TaskInput`, `TaskFeatures`); the Contract unifies them. `unknown` risk defaults fail-closed (preserve/escalate).

## 2. Context IR (`context-ir.schema.json`)

```json
{
  "schema_version": "context-ir/0.1",
  "ir_version": "0.1",
  "task_id": "uuid",
  "units": [{
    "id": "blk_0001_ab12cd",
    "content": "verbatim bytes",
    "source": "path:lines | tool:call_id | url",
    "provenance": {"origin": "string", "collected_at": "rfc3339", "transform": "none | clean | dedupe"},
    "relevance": 0.0, "necessity": "unknown",
    "semantic_risk": 0.0, "protected": false,
    "dependencies": ["blk_..."], "relationships": [{"to": "blk_...", "type": "SUPPORTS"}]
  }],
  "relationships": [{"from": "blk_a", "to": "blk_b", "type": "SUPPORTS"}],
  "selection": {"kept": ["blk_..."], "trimmed": [], "dropped": [], "policy": "name-version", "rationale": {}},
  "sufficiency": {"sufficient": true, "missing_evidence": [], "confidence": 0.85},
  "restoration": {"restored": [], "budget": 4, "reason": ""}
}
```

Relationship enum: `SUPPORTS QUALIFIES CONTRADICTS SUPERSEDES DEPENDS_ON DUPLICATES DERIVED_FROM` (matches LCC `graph.py`). Necessity labels: `NECESSARY UNNECESSARY CONDITIONALLY_NECESSARY REDUNDANT PROTECTED UNKNOWN` (populated by ablation, §6 of program; default `UNKNOWN`). Deterministic serialization required (Sprint 2 acceptance).

## 3. Inference Plan (`inference-plan.schema.json`)

```json
{
  "schema_version": "inference-plan/0.1",
  "model_class": "local_tiny | local_small | fast_hosted | frontier",
  "provider": "string (adapter-owned, optional)",
  "reasoning_budget": "none | low | medium | high",
  "tools": ["string"],
  "context_profile": "full | compiled | minimal",
  "verification_profile": "strict | standard | light",
  "fallbacks": [{"trigger": "VERIFY_FAIL | TIMEOUT | LOW_CONF", "action": "RESTORE_CONTEXT | RETRY | INCREASE_REASONING | SWITCH_MODEL | ADD_TOOL | ESCALATE | ABORT"}],
  "escalation_policy": {"max_retries": 2, "max_restorations": 4, "escalate_to": "human | frontier | abort"}
}
```

Deterministic-policy baseline first (port LCC `router/policy.py` semantics); Jev/small-model engines are swappable adapters.

## 4. Verification Result (`verification-result.schema.json`)

```json
{
  "schema_version": "verification-result/0.1",
  "status": "PASS | REVIEW | FAIL",
  "checks": [{"id": "citations_resolve", "passed": true, "detail": ""}],
  "confidence": 0.9, "failures": [],
  "recommended_action": "PASS | RESTORE_CONTEXT | RETRY | INCREASE_REASONING | SWITCH_MODEL | ADD_TOOL | ESCALATE | ABORT"
}
```

Tri-state mirrors LCC `verifier.py` + AgentTrace gate. REVIEW/FAIL never silent; FAIL carries bounded restore budget, single re-verify (no loop).

## 5. Inference Receipt (`inference-receipt.schema.json`)

Fields: task, input/selection/omitted units + rationale, model + reasoning config, tools, verification strategy + result, restorations/retries/escalations, latency/token/cost, versions (compiler, policy, model, schema, dataset, evaluator), timestamps, decision events (WHY dropped/restored/routed/failed/escalated), final + evaluation result. Receipt is auditability infrastructure, novelty not claimed; value = link to measured outcomes.

## Versioning
Independent versions: Context IR, Task Contract, Inference Plan, Receipt, dataset, evaluator, routing policy (e.g. `Context IR v0.1`, `MSI-Bench Dataset 2026.10`).
