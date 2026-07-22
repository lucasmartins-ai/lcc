<div align="center">

# ⚡ Local Context Compiler (`lcc`)

**High-performance, local-first CLI & programmatic engine for prompt context optimization and token estimation.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![npm version](https://img.shields.io/badge/npm-v0.2.0-red.svg)](https://github.com/vetlucasmartins/lcc)
[![PyPI version](https://img.shields.io/badge/pypi-v0.2.0-orange.svg)](https://github.com/vetlucasmartins/lcc)
[![CI Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/vetlucasmartins/lcc/actions/workflows/ci.yml)
[![Local-First](https://img.shields.io/badge/privacy-100%25_local_--_zero_telemetry-success.svg)](SECURITY.md)

</div>

---

## 📌 Overview

**`lcc` (Local Context Compiler)** is a deterministic, local-first toolkit designed to clean, deduplicate, structure, and measure text context before sending it to a Large Language Model (LLM).

`lcc` operates in a dual capacity:
1. **Standalone CLI Tool**: Allows developers and SREs to inspect, optimize, and benchmark prompt files locally.
2. **Ecosystem Core Engine & Library**: Exports programmatic interfaces (`LccCompressor` / `LccOptimizer`) for both **Python** and **TypeScript / Node.js**, powering downstream AI agents and ingestion pipelines like [`agentic-intake`](https://github.com/vetlucasmartins/agentic-prompt-intake).

---

## 📊 At a Glance

| Question | Answer |
| --- | --- |
| **What is it?** | A local CLI, Python module, and Node.js/TypeScript library for context optimization. |
| **What does it improve?** | Token count, cost visibility, repeated text, boilerplate, and prompt structure. |
| **What does it preserve?** | Original evidence, user intent, and an auditable report of every cleaning step. |
| **What does it avoid?** | Runtime network calls, API keys, LLM calls, embeddings, vector stores, and lossy summarization. |
| **Ecosystem Role** | Powering prompt context optimization in `agentic-intake` and AI agent workflows. |

---

## ⚡ Key Features

- ⚡ **Local-First & Zero Telemetry**: Privacy & security focused. Runtime network access is strictly blocked by default—no data ever leaves your machine.
- 📊 **Token Estimation via `tiktoken`**: Honest token counting with explicit `exact` vs `approximate` labeling ([ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)).
- 🎯 **Prompt Context Optimization**: Deterministic whitespace normalization, conservative boilerplate removal, exact & near-duplicate paragraph deduplication, and token budget guardrails.
- 🧱 **Architectural Integrity**: Core engine designed around modular, auditable boundaries, including deterministic preparation ([ADR 0010](docs/adr/0010-deterministic-first-preparation-model-assistance.md)).
- 🔌 **Dual Language Programmatic API**: `LccCompressor` exported in both Python (`src/lcc/compressor.py`) and TypeScript/JavaScript (`index.js` / `index.d.ts`).
- 🔍 **Read-Only Diagnostics (`lcc inspect`)**: Analyzes raw context, line counts, duplicate ratios, and projected savings without modifying the source file ([ADR 0009](docs/adr/0009-inspection-command-boundary.md)).
- 🧪 **Deterministic Benchmark Harness (`lcc bench`)**: Measures mechanical compression ratio, token savings, and selection states deterministically across test suites ([ADR 0007](docs/adr/0007-deterministic-benchmark-harness.md)).

---

## 🌐 Ecosystem & Integrations

### Official Adoption: `agentic-intake`

`lcc` powers the context optimization layer in [`agentic-intake`](https://github.com/vetlucasmartins/agentic-prompt-intake), an intelligent ingestion engine for AI agents:

```text
[Raw Input Data] ──► [agentic-intake Triage] ──► [lcc Local Compression Engine] ──► [LLM Dispatch]
```

When `agentic-intake` receives user input or voice notes, `lcc` cleans boilerplate, deduplicates prompt context, and enforces token guardrails 100% locally before sending the request to external LLM providers.

---

## 🚀 Programmatic Library API Usage

### Python API

```python
from lcc import LccCompressor

# Initialize compressor with target model and token guardrail
compressor = LccCompressor(model="gpt-4.1", max_tokens=1000)

raw_text = """
CONFIDENTIAL NOTICE: Intended for recipient only.
Sent from my iPhone

Here is the primary context paragraph.

Here is the primary context paragraph.
"""

result = compressor.compress(raw_text, question="Summarize key content")

print("Cleaned Context:\n", result.compressed_text)
print("Original Tokens:", result.original_tokens)
print("Compressed Tokens:", result.compressed_tokens)
print("Savings Percentage:", f"{result.savings_percentage}%")
```

### TypeScript / Node.js API

```typescript
import { LccCompressor, LccOptions } from 'local-context-compiler';

const options: LccOptions = {
  model: 'gpt-4.1',
  maxTokens: 1000,
  removeBoilerplate: true,
  removeNearDuplicates: true
};

const compressor = new LccCompressor(options);
const result = compressor.compress(rawText);

console.log(`Original: ${result.originalTokens} | Compressed: ${result.compressedTokens}`);
console.log(`Saved: ${result.savingsPercentage}%`);
```

---

## 🖥️ Command Guide & Terminal Output

### 1. `lcc inspect` — Diagnostic Inspection

```bash
lcc inspect examples/sample_input.txt --model gpt-4.1 --report inspect_report.json
```

### 2. `lcc optimize` — Context Optimization

```bash
lcc optimize examples/sample_input.txt \
  --question "What are the key points and risks?" \
  --model gpt-4.1 \
  --output optimized_prompt.md \
  --report report.json
```

### 3. `lcc prepare` — Inspect-First Orchestration

```bash
lcc prepare examples/sample_input.txt \
  --question "What are the key points?" \
  --model gpt-4.1 \
  --output optimized_prompt.md \
  --report prepare_report.json
```

### 4. `lcc bench` — Deterministic Suite Evaluation

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

---

## 🏛️ Architecture & Boundaries

`lcc` is engineered around strict architectural boundaries ([ADRs](docs/adr/)):

| Module | Responsibility |
| --- | --- |
| `lcc.compressor` | High-level `LccCompressor` / `LccOptimizer` programmatic interface. |
| `lcc.cleaning` | Normalize text, remove conservative boilerplate, deduplicate paragraphs. |
| `lcc.token_budget` | Count tokens exactly or approximately, estimate input cost. |
| `lcc.prompt_builder` | Render evidence-aware prompt template specs. |
| `lcc.reporting` | Build deterministic JSON reports (`schema_version: "1.0"`). |
| `lcc.pipeline` | Compose the deterministic core modules. |
| `lcc.cli` | Handle Typer/Rich CLI interface, stdin, files, and config. |

---

## 🧪 Development & Testing

Run all test suites and quality gates for Python & Node.js:

```bash
# Python test suite & quality gates
source .venv/bin/activate
python -m pytest
ruff check .
ruff format --check .
mypy

# Node.js / JS test suite
node test/index.test.js
```

---

## 📄 License

Open-source software licensed under the [MIT License](LICENSE).
