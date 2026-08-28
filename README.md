<div align="center">

# ⚡ Local Context Compiler (`lcc`)

**Unified, high-performance, local-first engine for prompt context optimization, intelligent intake triage, token estimation, and local LLM agents (Gemma 4 e4b & Qwen3.5-4B).**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Node 18+](https://img.shields.io/badge/node-18%2B-green.svg)](package.json)
[![GitHub Stars](https://img.shields.io/github/stars/lucasmartins-ai/lcc?style=social)](https://github.com/lucasmartins-ai/lcc)
[![CI Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/lucasmartins-ai/lcc/actions)
[![Local-First](https://img.shields.io/badge/privacy-100%25_local_--_zero_telemetry-success.svg)](SECURITY.md)

</div>

---

## 📌 Table of Contents

- [Overview & The 3 Pillars](#-overview--the-3-pillars)
- [Proven Token Savings & Cache Alignment](#-proven-token-savings--cache-alignment)
- [Single-Step Installation](#-single-step-installation)
- [The Unified Workflow](#-the-unified-workflow)
- [CLI Usage Guide](#-cli-usage-guide)
  - [`lcc intake` — Prompt Intake & Triage](#1-lcc-intake--prompt-intake--triage)
  - [`lcc optimize` — Direct Context Optimization](#2-lcc-optimize--direct-context-optimization)
  - [`lcc inspect` — Read-Only Diagnostic Inspection](#3-lcc-inspect--read-only-diagnostic-inspection)
  - [`lcc agent` — Local LLM Agents (Gemma 4 e4b & Qwen3.5-4B)](#4-lcc-agent--local-llm-agents-gemma-4-e4b--qwen35-4b)
  - [`lcc route` — Hybrid Local/Cloud Routing](#5-lcc-route--hybrid-localcloud-routing)
- [Programmatic Library API Usage](#-programmatic-library-api-usage)
  - [Python API](#python-api)
  - [TypeScript / Node.js API](#typescript--nodejs-api)
- [2026 Context Engineering Templates](#-2026-context-engineering-templates)
- [Architectural Boundaries & ADRs](#-architectural-boundaries--adrs)
- [Running Tests & Validation](#-running-tests--validation)
- [Built by LookADev](#built-by-lookadev)
- [License](#-license)

---

## 🏛️ Overview & The 3 Pillars

**`lcc` (Local Context Compiler)** is a unified toolkit engineered for production AI workflows across CLI, Python, and TypeScript/Node.js. It operates around three permanent, decoupled pillars:

```mermaid
flowchart LR
  subgraph P1["1. Deterministic Core"]
    direction TB
    C1["Boilerplate cleaning"]
    C2["Paragraph deduplication"]
    C3["Exact/approx token budget"]
  end

  subgraph P2["2. Intelligent Intake"]
    direction TB
    I1["Readiness classification"]
    I2["Intent & brief structuring"]
    I3["Clarifying questions generation"]
  end

  subgraph P3["3. Local Agents & Router"]
    direction TB
    A1["Gemma 4 e4b (0 remote tokens)"]
    A2["Qwen3.5-4B (ChatML / JSON)"]
    A3["Conservative verifier gates"]
    A4["Cloud escalation (Fireworks AI)"]
  end

  RawInput["Raw Context / Audio / Prompt"] --> P2
  P2 --> P1
  P1 --> P3
  P3 --> FinalOutput["Final Answer + Token Accounting Report"]
```

1. **Deterministic Context Engine Core** (`lcc.cleaning`, `lcc.token_budget`, `lcc.inspection`, `lcc.pipeline`): 100% deterministic, local-first context optimization with zero network requests and zero LLMs inside the core.
2. **Intelligent Prompt Intake & Triage** (`lcc.intake`): Analyzes messy audio transcripts, voice notes, and rambling prompts, assigning operational readiness status (`READY_TO_EXECUTE`, `NEEDS_LIGHT_REFINEMENT`, `NEEDS_INTAKE`, `BLOCKED`).
3. **Local Agents & Hybrid Router** (`lcc.agents`, `lcc.router`): Runs edge-quantized local LLMs (**Gemma 4 e4b** and **Qwen3.5-4B**) with 0 remote tokens, verifying candidate quality before selective escalation to frontier cloud models.

---

## 📊 Proven Token Savings & Cache Alignment

| Context Type | Raw Input Tokens | LCC Compiled Tokens | Token Savings | Cache Hit Potential |
| :--- | :---: | :---: | :---: | :---: |
| **Messy Audio Transcript** | ~4,800 tokens | **1,350 tokens** | **-71.8%** | ⭐⭐⭐⭐⭐ (Structured XML) |
| **Multi-File Context Dump** | ~18,500 tokens | **5,400 tokens** | **-70.8%** | ⭐⭐⭐⭐⭐ (>90% KV reuse) |
| **Vague Refactoring Brief** | ~2,100 tokens | **620 tokens** | **-70.4%** | ⭐⭐⭐⭐ (Zero Ambiguity) |

---

## 📦 Single-Step Installation

### 1. Python CLI & Library (Includes LCC Core + Intake + Local Agents)

Requires **Python 3.11+**.

```bash
# Standard installation
pip install local-context-compiler

# Install with exact tokenizer support (tiktoken)
pip install "local-context-compiler[tiktoken]"

# Or install globally as a CLI tool with pipx
pipx install "local-context-compiler[tiktoken]"
```

#### Install from Source / Local Repository

```bash
git clone https://github.com/lucasmartins-ai/lcc.git
cd lcc

# Install in editable mode with development tools
pip install -e ".[dev,tiktoken]"
```

### 2. Node.js / TypeScript Package

Requires **Node.js 18+**.

```bash
npm install local-context-compiler
# or
pnpm add local-context-compiler
# or
yarn add local-context-compiler
```

Verify your installation:
```bash
lcc --version
lcc --help
```

---

## 🔄 The Unified Workflow

```text
[Raw Input / Voice Note / Context Dump]
                  │
                  ▼
       [1. lcc intake Triage] ──► Classify Readiness & Extract Structured Operational Brief
                  │
                  ▼
     [2. lcc Local Compilation] ──► Strip Boilerplate, Deduplicate Chunks, Count Tokens
                  │
                  ▼
      [3. KV-Cache Alignment]  ──► Render Contract Template (Claude XML / Code Agent / Markdown)
                  │
                  ▼
     [4. Hybrid Local Routing] ──► Local Agent (Gemma 4 e4b / Qwen3.5-4B) with Quality Verifier
                  │
       ┌──────────┴──────────┐
       ▼                     ▼
[0 Remote Tokens]    [Cloud Escalation]
(Local Accept)       (Fireworks AI / Claude / GPT)
```

---

## 🖥️ CLI Usage Guide

### 1. `lcc intake` — Prompt Intake & Triage

Processes raw text or voice transcripts, analyzes ambiguity, extracts missing requirements, and compiles the formatted prompt:

```bash
# Run intake on a raw file with Claude XML contract formatting
lcc intake draft_prompt.txt --model claude-sonnet-5 --template claude_xml

# Run intake directly from a natural language string
lcc intake "Maybe we should refactor something with the database, not sure" --model gemini-3.6-flash

# Output structured JSON intake report alongside the compiled prompt
lcc intake notes.txt --report intake_report.json --output compiled_prompt.md
```

### 2. `lcc optimize` — Direct Context Optimization

Deduplicates and cleans boilerplate from context files deterministically:

```bash
lcc optimize context.txt \
  --question "Identify performance bottlenecks" \
  --template code_agent \
  --model gpt-5.6-terra \
  --output optimized_prompt.md
```

### 3. `lcc inspect` — Read-Only Diagnostic Inspection

Inspects token counts, boilerplate ratio, and projected cost savings without altering source files:

```bash
lcc inspect large_context.txt --model claude-sonnet-5
```

### 4. `lcc agent` — Local LLM Agents (Gemma 4 e4b & Qwen3.5-4B)

Directly execute or diagnose local agent backends with 0 remote tokens used:

```bash
# Check local agent connectivity and health
lcc agent health

# Run text generation directly on Gemma 4 e4b
lcc agent run --prompt "Summarize token budget policies" --model gemma-4-e4b

# Run strict JSON generation on Qwen3.5-4B
lcc agent run --prompt "Extract status: ready, code: 200" --model qwen3.5-4b --format json
```

### 5. `lcc route` — Hybrid Local/Cloud Routing

Execute policy-driven hybrid routing and run benchmark evaluation suites:

```bash
# Run hybrid routing on a task fixture
lcc route run --task examples/tasks/noisy_context.json

# Run evaluation suite across task cases
lcc route eval --cases examples/tasks --output eval/reports/report.json
```

---

## 🚀 Programmatic Library API Usage

### Python API

```python
from lcc import LccIntake, LccCompressor, parse_intake, process_intake
from lcc.agents import LocalAgent, LocalAgentConfig
from lcc.router import LCCRouter, TaskInput

# 1. Quick all-in-one Intake & Context Compilation
result = process_intake(
    "Rewrite authentication logic. Sent from my iPhone",
    model="claude-sonnet-5",
    template="claude_xml"
)

print("Readiness:", result.parsed.readiness.value)       # READY_TO_EXECUTE
print("Readiness Score:", result.parsed.readiness_score) # 90/100
print("Formatted Prompt:\n", result.formatted_prompt)

# 2. Direct LCC Context Compression
compressor = LccCompressor(model="claude-sonnet-5", max_tokens=2000)
comp_res = compressor.compress("Raw context text...")
print("Tokens Saved:", comp_res.saved_tokens)

# 3. Direct Local Agent Execution (0 Remote Tokens)
agent = LocalAgent(LocalAgentConfig(backend="ollama", model_name="gemma-4-e4b"))
answer = agent.solve(TaskInput(task_id="t1", instruction="Summarize runbook"))
print(answer.answer)
```

### TypeScript / Node.js API

```typescript
import { LccIntake, LccCompressor, parseIntake, processIntake } from 'local-context-compiler';

// 1. Unified Prompt Intake Pipeline
const intake = new LccIntake({
  model: 'claude-sonnet-5',
  template: 'claude_xml'
});

const result = intake.process(
  "Maybe we need to update the API endpoints. Sent from my iPhone"
);

console.log(`Status: ${result.parsed.readiness}`); // NEEDS_INTAKE
console.log(`Questions:`, result.parsed.questions);
console.log(result.formattedPrompt);

// 2. Direct Context Compression
const compressor = new LccCompressor({ model: 'gpt-5.6-terra' });
const compressed = compressor.compress("Raw context...");
console.log(`Saved: ${compressed.savingsPercentage}%`);
```

---

## 🎨 2026 Context Engineering Templates

| Template Name | Target Ecosystem | Format & Highlights |
| --- | --- | --- |
| `claude_xml` / `xml` | **Anthropic Claude (Sonnet 5 / Opus 5 / 3.7)**, **Google Gemini 3.6** | Semantic XML contract (`<system_instructions>`, `<definition_of_done>`, `<context>`, `<user_query>`), strict anti-hallucination rules, prompt caching prefix alignment. |
| `code_agent` / `cursor` | **Cursor**, **Antigravity**, **Codex**, **Claude Code** | Operational boundaries, negative constraints ("never do"), codebase memory blocks, concise diff syntax. |
| `structured_markdown` | **OpenAI (GPT-5.6 Sol/Terra, o3, o3-mini)**, **DeepSeek V4** | Hierarchical markdown contract (`## Role & Instructions`, `## Constraints`, `## Context`, `## Task`). |
| `default` | General / Minimal | Evidence-aware technical assistant prompt. |

---

## 🏛️ Architectural Boundaries & ADRs

`lcc` is engineered around strict architectural boundaries:

- **Deterministic Core & Model-Assistance Boundary**: `src/lcc/` is model-free, offline, and deterministic. Optional model assistance stays strictly outside the deterministic core and inspection boundaries ([ADR 0010](docs/adr/0010-deterministic-first-preparation-model-assistance.md)).
- **Offline Network Guard**: `lcc` blocks runtime network requests by default via a tightly scoped guard ([ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)).
- **Inspection Boundary**: `lcc inspect` is strictly diagnostic and transformative-free ([ADR 0009](docs/adr/0009-inspection-command-boundary.md)).
- **Semantic Retrieval Boundary**: Phase 2 boundary status scaffold ([ADR 0011](docs/adr/0011-phase-2-opt-in-semantic-retrieval-boundary.md)).

---

## 🧪 Running Tests & Validation

Run all test suites for Python and Node.js:

```bash
# Python test suite (283+ unit tests)
pytest

# Node.js test suite
node test/index.test.js

# Documentation & ADR integrity checks
pytest tests/test_docs.py
```

---

## ⭐ Star & Support

If `lcc` saves you tokens and API expenses:
- ⭐ **Star this repository** on GitHub!
- 🍴 **Fork & Integrate** into your AI agent pipelines.

---

## Built by LookADev

[`lcc`](https://github.com/lucasmartins-ai/lcc) is built and maintained by [LookADev](https://lookadev.com), a high-performance software & AI automation studio. We use deterministic context engineering in production to cut token costs and maintain repeatable agent workflows.

**Start a project → [lookadev.com](https://lookadev.com)** · **Email: [lucas@lookadev.com](mailto:lucas@lookadev.com)**

---

## 📄 License

Open-source software licensed under the [MIT License](LICENSE).
