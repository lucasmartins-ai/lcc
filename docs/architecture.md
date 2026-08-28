# LCC (Local Context Compiler) Architecture

`lcc` is a modular, local-first context optimization and intelligent agent execution toolkit. The system is organized around three permanent, decoupled pillars:

1. **Deterministic Context Engine Core** (`src/lcc/cleaning`, `src/lcc/token_budget`, `src/lcc/inspection`, `src/lcc/lexical_selection`, `src/lcc/pipeline`): 100% deterministic, zero network, zero LLMs inside core. Performs character/token counting, near-duplicate detection, and lexical chunk selection.
2. **Intelligent Prompt Intake & Triage** (`src/lcc/intake`): Structured anamnese, intent extraction, readiness classification, and clarifying question generation for human/voice inputs.
3. **Local Agents & Hybrid Router Subsystem** (`src/lcc/agents`, `src/lcc/router`): Executes local LLMs (Gemma 4 e4b, Qwen3.5-4B via Ollama, llama.cpp, vLLM, MLX) with 0 remote tokens, conservative verification gates, and policy-driven cloud escalation (Fireworks AI).

---

## System Context

```mermaid
flowchart LR
  User["Task / Prompt Input"] --> Router["LCC Hybrid Router (lcc.router)"]
  Router --> Core["Deterministic Context Engine (lcc.core)"]
  Router --> LocalAgent["Local Agent: Gemma 4 e4b / Qwen3.5-4B (lcc.agents)"]
  Router --> Verifier["Local Quality Verifier (lcc.agents.local_verifier)"]
  Router --> Cloud["Cloud Model / Fireworks AI (lcc.router.cloud_client)"]
  Router --> Output["Final Answer + Token Accounting Report"]
```

---

## Container Diagram

```mermaid
flowchart TB
  subgraph DeterministicCore["Deterministic Context Engine Core (src/lcc)"]
    Inspect["inspection (inspect)"]
    Prepare["prepare & lexical_selection"]
    Optimize["pipeline (optimize)"]
    Budget["token_budget & pricing"]
  end
  subgraph PromptIntake["Intelligent Prompt Intake (src/lcc/intake)"]
    Anamnese["Anamnese & Readiness Triage"]
    Brief["Structured Brief Generation"]
    Questions["Clarification Engine"]
  end
  subgraph LocalAgentsAndRouter["Local Agents & Hybrid Router (src/lcc/agents & src/lcc/router)"]
    Adapter["context_adapter"]
    Features["features"]
    Policy["policy"]
    LocalAgentEngine["LocalAgent: Gemma 4 e4b / Qwen3.5-4B"]
    Gate["RuleBasedVerifier & LocalLLMVerifier"]
    Remote["RemoteSolver (Fireworks AI)"]
    Eval["eval_runner"]
  end
  Adapter --> Inspect
  Adapter --> Prepare
  Adapter --> Optimize
  Features --> Policy
  Policy --> LocalAgentEngine
  LocalAgentEngine --> Gate
  Gate --> Remote
  Eval --> LocalAgentsAndRouter
```

---

## Routing Sequence

```mermaid
sequenceDiagram
  participant T as Task / Prompt
  participant R as LCCRouter
  participant C as Context Engine Core (inspect/prepare)
  participant S as Local Agent (Gemma / Qwen)
  participant V as Local Verifier
  participant F as Cloud LLM (Fireworks)
  T->>R: TaskInput
  R->>C: Inspect context & token budget
  C-->>R: LCCReportSummary
  R->>R: Extract quantitative features & choose route
  alt Local-First Route (0 remote tokens)
    R->>S: Execute local solver inference
    S-->>R: LocalAnswer
    R->>V: Verify candidate (format & risk checks)
    V-->>R: Accept or Escalate
  end
  alt Cloud Escalation (Remote Route)
    R->>C: Prepare compressed context when useful
    R->>F: Token-efficient prompt
    F-->>R: Cloud Answer + token usage
  end
  R-->>T: FinalAnswer + token savings report
```

---

## Decision Flow

```mermaid
flowchart TD
  A["Task Input"] --> B["Deterministic LCC Inspect"]
  B --> C["Feature Extraction"]
  C --> D{"High Risk or Token Exceeded?"}
  D -- Yes --> E{"Compression Useful?"}
  E -- Yes --> F["COMPRESS_THEN_REMOTE"]
  E -- No --> G["REMOTE_DIRECT"]
  D -- No --> H{"Long / Noisy with Savings?"}
  H -- Yes --> I["COMPRESS_THEN_LOCAL"]
  H -- No --> J["LOCAL_THEN_VERIFY"]
  I --> K["Local Agent (Gemma 4 e4b / Qwen3.5-4B)"]
  J --> K
  K --> L["Local Verifier Gate"]
  L -- Accept --> M["Final Local Answer (0 Remote Tokens)"]
  L -- Escalate --> F
  F --> N["Cloud Model (Fireworks AI)"]
  G --> N
  N --> O["Final Answer + Token Usage Report"]
```

---

## Evaluation Pipeline

```mermaid
flowchart LR
  Fixtures["examples/tasks/*.json"] --> Runner["lcc.router.eval_runner"]
  Runner --> Router["LCCRouter"]
  Router --> Metrics["Deterministic Benchmark Metrics"]
  Metrics --> JSON["eval/reports/report.json"]
  Metrics --> MD["eval/reports/report.md"]
```

---

## LCC Baseline Boundary

The pre-existing LCC core follows the deterministic Phase 1.7 prepare boundary recorded
in [ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md). `lcc prepare`
uses deterministic inspect-first orchestration and question-aware lexical chunk selection.
Inside `src/lcc`, there is no semantic selection, embeddings, network access, local model call, or remote LLM call. The router and agent subsystem (`src/lcc/agents`, `src/lcc/router`) operate as an extensible orchestration layer outside that deterministic boundary.


---

## Programmatic Module & Ecosystem Integration Architecture

```mermaid
flowchart TD
  subgraph Library Module Exports
    PythonModule["src/lcc/compressor.py (LccCompressor)"]
    NodeModule["index.js / index.d.ts (LccCompressor)"]
    AgentModule["src/lcc/agents (LocalAgent)"]
    RouterModule["src/lcc/router (LCCRouter)"]
  end
  subgraph Ecosystem Integration (Intelligent Intake Pipeline)
    Ingestion["Raw User Input / Voice Transcript"] --> IntakeParse["lcc.intake Readiness Triage"]
    IntakeParse --> LccGuard["lcc Local Token Estimation & Guardrails"]
    LccGuard --> RouterDispatch["lcc.router Hybrid Routing & Execution"]
  end
  PythonModule --> Ecosystem Integration
  NodeModule --> Ecosystem Integration
  AgentModule --> Ecosystem Integration
  RouterModule --> Ecosystem Integration
```
