<div align="center">

# ⚡ Local Context Compiler (`lcc`)

**High-performance, local-first CLI tool for prompt context optimization and token estimation using tiktoken.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![PyPI version](https://img.shields.io/badge/pypi-v0.2.0-orange.svg)](https://github.com/vetlucasmartins/lcc)
[![CI Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/vetlucasmartins/lcc/actions)
[![Local-First](https://img.shields.io/badge/privacy-100%25_local_--_zero_telemetry-success.svg)](SECURITY.md)

</div>

---

## 📌 Overview

**Local Context Compiler (`lcc`)** is a deterministic, local-first toolkit designed to clean, deduplicate, structure, and measure text context before feeding it to Large Language Models (LLMs).

`lcc` operates completely offline without network calls, API keys, or remote dependencies. It helps developers drastically reduce prompt token usage and API costs while preserving critical evidence and context ground truth.

---

## ⚡ Key Features

- ⚡ **Local-First & Zero Telemetry**: Privacy & security focused. Runtime network access is strictly blocked by default—no data ever leaves your machine.
- 📊 **Token Estimation via `tiktoken`**: Honest token counting with explicit `exact` vs `approximate` labeling. Blocks unauthorized tokenizer downloads offline and gracefully falls back to a labeled heuristic estimator (see [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)).
- 🎯 **Prompt Context Optimization**: Deterministic whitespace normalization, conservative boilerplate removal, exact & near-duplicate paragraph deduplication, and question-aware lexical selection without lossy LLM summarization or hallucination.
- 🛡️ **Zero External Network Dependencies**: Operates 100% offline without requiring API keys, cloud LLMs, or vector databases.
- 🧠 **Smart Context & Policy Router**: Includes an extensible, policy-driven router (`act2_router`) for evaluating prompt context and intelligently selecting local vs. remote model execution strategies based on cost and confidence.
- 🧪 **Deterministic Benchmark Harness**: Built-in benchmark runner (`lcc bench`) to measure mechanical compression ratio, token savings, and selection states deterministically across test suites.

---

## 🚀 Quick Start & Installation

### Requirements
- **Python**: `3.11` or higher.

### Installation

```bash
# Clone the repository
git clone https://github.com/vetlucasmartins/lcc.git
cd lcc

# Create virtual environment and install in editable mode with dev tools
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## 💡 Usage & CLI Examples

`lcc` provides a rich set of subcommands for inspecting, optimizing, preparing, and benchmarking prompt contexts.

### 1. Diagnostic Inspection (`lcc inspect`)

Analyze a raw document without modifying it or building a prompt. Provides projected token and cost savings:

```bash
lcc inspect input_context.txt
```

#### Terminal Output Example

```text
                lcc -- inspection summary                 
Source                             file                   
Decision                           skip                   
Reason                             low_projected_savings  
Characters                         570                    
Model                              gpt-4.1                
Token counting                     approximate (heuristic)
Input tokens                       114                    
Projected tokens                   114                    
Est. input cost                    0.000228 USD           
Duplicate paragraphs (projection)  0 exact + 0 near       
Projected token savings            0.0%                   
Projected char savings             0.2%                   
╭────────────────────────────────── Warnings ──────────────────────────────────╮
│ - Token counts are approximate; treat token and cost figures as estimates.   │
│ tiktoken would need to download encoding assets, which lcc blocks to stay    │
│ offline; used the heuristic estimator. Pre-cache the tokenizer (for example, │
│ set TIKTOKEN_CACHE_DIR to a populated directory) to enable exact counts.     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

---

### 2. Prompt Context Optimization (`lcc optimize`)

Clean, deduplicate, and assemble an evidence-grounded prompt:

```bash
lcc optimize input_context.txt --question "Summarize token rotation policy" --output prompt.md --report report.json
```

#### Terminal Output Example

```text
        lcc -- optimization summary        
Model               gpt-4.1                
Token counting      approximate (heuristic)
Original tokens     114                    
Optimized tokens    114                    
Token savings       0.0%                   
Compression ratio   1.000                  
Full prompt tokens  273                    
Est. cost before    0.000228 USD           
Est. cost after     0.000228 USD           
Est. cost savings   0.000000 USD           

Prompt written to: prompt.md
Report written to: report.json
```

---

### 3. Orchestrated Preparation (`lcc prepare`)

Run inspect-first orchestration that skips prompt generation when inspection recommends `skip` or `manual_review`, and runs lexical selection when safe optimization is beneficial:

```bash
lcc prepare input_context.txt --question "Extract OAuth steps" -o prompt.md -r report.json
```

---

### 4. Deterministic Benchmarking (`lcc bench`)

Run deterministic suite evaluations to verify mechanical optimization behavior across cases:

```bash
lcc bench benchmarks/cases -o suite_report.json --markdown suite_report.md
```

---

### 5. Context Policy Routing (`act2_router`)

Evaluate task context and execute policy-driven routing (e.g. `LOCAL_THEN_VERIFY`, `COMPRESS_THEN_LOCAL`, `COMPRESS_THEN_REMOTE`, `REMOTE_DIRECT`):

```bash
python -m act2_router.cli run --task examples/tasks/noisy_context.json
```

---

## 🏛️ Architecture & Security

`lcc` is engineered around strict boundaries and architectural decision records (ADRs):

- **Deterministic Core**: `src/lcc/` is completely model-free, offline, and deterministic. It performs no network calls, embedding calculations, or LLM inferences. Optional model assistance stays strictly outside the deterministic core and inspection boundaries ([ADR 0010](docs/adr/0010-deterministic-first-preparation-model-assistance.md)).
- **Offline Network Guard**: `lcc` blocks runtime network requests by default—including `tiktoken`'s initial encoding downloads—via a tightly scoped guard in `lcc.token_budget.counters` ([ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)). Exact counting requires locally cached tokenizer assets; otherwise it falls back to a labeled approximation.
- **Inspection Boundary**: `lcc inspect` is strictly diagnostic and transformative-free ([ADR 0009](docs/adr/0009-inspection-command-boundary.md)).
- **Semantic Retrieval Boundary**: Includes a disabled-by-default boundary status scaffold ([ADR 0011](docs/adr/0011-phase-2-opt-in-semantic-retrieval-boundary.md)).
- **JSON Schema Versioning**: Machine-readable output reports adhere strictly to `schema_version: "1.0"` ([ADR 0004](docs/adr/0004-report-schema-versioning.md)).
- **Security Policy**: Comprehensive guidelines on handling sensitive prompt content and credentials can be found in [SECURITY.md](SECURITY.md).

---

## 🧪 Verification & Development

To run the complete test suite, static type checker, and linters:

```bash
# Run pytest tests
python -m pytest

# Run ruff linters & formatters
ruff check .
ruff format --check .

# Run mypy static type checking
mypy
```

---

## 🤝 Contributing

We welcome community contributions! Please read our [CONTRIBUTING.md](CONTRIBUTING.md) guide before submitting pull requests.

All interactions in this repository are governed by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## 📄 License

This project is open-source software licensed under the [MIT License](LICENSE).
