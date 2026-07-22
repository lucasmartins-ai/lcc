# LCC-Router Architecture

`src/lcc` remains deterministic. `act2_router` is the hackathon layer that decides whether to
answer locally, verify locally, compress context, or escalate to Fireworks AI.

## System Context

```mermaid
flowchart LR
  User["Task input"] --> Router["LCC-Router"]
  Router --> LCC["Pre-existing LCC deterministic core"]
  Router --> Local["Local model / mock local solver"]
  Router --> Verifier["Local verifier"]
  Router --> Fireworks["Fireworks AI"]
  Router --> Report["Final answer + token report"]
```

## Container Diagram

```mermaid
flowchart TB
  subgraph Core["src/lcc"]
    Inspect["inspect"]
    Prepare["prepare / lexical selection"]
    Optimize["optimize"]
  end
  subgraph Router["act2_router"]
    Adapter["lcc_adapter"]
    Features["features"]
    Policy["policy"]
    LocalSolver["local_solver"]
    Gate["local_verifier"]
    Remote["fireworks_client"]
    Eval["eval_runner"]
  end
  Adapter --> Inspect
  Adapter --> Prepare
  Adapter --> Optimize
  Features --> Policy
  Policy --> LocalSolver
  LocalSolver --> Gate
  Gate --> Remote
  Eval --> Router
```

## Routing Sequence

```mermaid
sequenceDiagram
  participant T as Task
  participant R as Router
  participant L as LCC inspect/prepare
  participant S as Local solver
  participant V as Local verifier
  participant F as Fireworks
  T->>R: task input
  R->>L: inspect context
  L-->>R: report summary
  R->>R: extract features and choose route
  alt local first
    R->>S: local attempt
    S-->>R: candidate answer
    R->>V: verify candidate
    V-->>R: accept or escalate
  end
  alt remote needed
    R->>L: prepare compressed context when useful
    R->>F: token-efficient prompt
    F-->>R: answer + usage
  end
  R-->>T: final answer + token report
```

## Decision Flow

```mermaid
flowchart TD
  A["task input"] --> B["LCC inspect"]
  B --> C["feature extraction"]
  C --> D{"high risk or too large?"}
  D -- yes --> E{"compression useful?"}
  E -- yes --> F["COMPRESS_THEN_REMOTE"]
  E -- no --> G["REMOTE_DIRECT"]
  D -- no --> H{"long/noisy with savings?"}
  H -- yes --> I["COMPRESS_THEN_LOCAL"]
  H -- no --> J["LOCAL_THEN_VERIFY"]
  I --> K["local solver"]
  J --> K
  K --> L["local verifier"]
  L -- accept --> M["final local answer, 0 remote tokens"]
  L -- escalate --> F
  F --> N["Fireworks AI"]
  G --> N
  N --> O["final answer + remote token report"]
```

## Evaluation Pipeline

```mermaid
flowchart LR
  Fixtures["examples/tasks/*.json"] --> Runner["eval_runner"]
  Runner --> Router["LCCRouter"]
  Router --> Metrics["local proxy metrics"]
  Metrics --> JSON["eval/reports/*.json"]
  Metrics --> MD["eval/reports/*.md"]
```

Conceptual flow:

```text
task input
  -> LCC inspect
  -> feature extraction
  -> route decision
  -> local solver
  -> local verifier
  -> accept local OR escalate
  -> LCC compressed remote prompt
  -> Fireworks AI
  -> final formatter
  -> final answer + token report
```

## LCC Baseline Boundary

The pre-existing LCC core still follows the deterministic Phase 1.7 prepare boundary recorded
in [ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md). `lcc prepare`
uses deterministic inspect-first orchestration and question-aware lexical chunk selection.
Inside `src/lcc`, there is no semantic selection, embeddings, network access, local model
call, or remote LLM call. The router layer is outside that boundary.

## Programmatic Module & Ecosystem Integration Architecture

```mermaid
flowchart TD
  subgraph Library Module Exports
    PythonModule["src/lcc/compressor.py (LccCompressor)"]
    NodeModule["index.js / index.d.ts (LccCompressor)"]
  end
  subgraph Ecosystem Integration (agentic-intake)
    Ingestion["Raw User Input / Voice Transcript"] --> IntakeParse["agentic-intake Readiness Triage"]
    IntakeParse --> LccGuard["lcc Local Token Estimation & Guardrails"]
    LccGuard --> LLMDispatch["Optimized Payload / LLM Dispatch"]
  end
  PythonModule --> Ecosystem Integration
  NodeModule --> Ecosystem Integration
```

