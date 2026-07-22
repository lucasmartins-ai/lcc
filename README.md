<div align="center">

# ⚡ Local Context Compiler (`lcc`)

**High-performance, local-first CLI tool for prompt context optimization and token estimation using tiktoken.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![PyPI version](https://img.shields.io/badge/pypi-v0.2.0-orange.svg)](https://github.com/vetlucasmartins/lcc)
[![CI Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/vetlucasmartins/lcc/actions/workflows/ci.yml)
[![Local-First](https://img.shields.io/badge/privacy-100%25_local_--_zero_telemetry-success.svg)](SECURITY.md)

</div>

---

## 📌 Overview

**`lcc` (Local Context Compiler)** is a deterministic, local-first toolkit designed to clean, deduplicate, structure, and measure text context before sending it to a Large Language Model (LLM).

`lcc` operates completely offline without network calls, API keys, remote dependencies, or lossy LLM summarization. It helps developers drastically reduce prompt token usage and API costs while preserving critical ground-truth evidence.

---

## 📊 At a Glance

| Question | Answer |
| --- | --- |
| **What is it?** | A local CLI and Python package for preparing cleaner LLM prompt context. |
| **What does it improve?** | Token count, cost visibility, repeated text, boilerplate, and prompt structure. |
| **What does it preserve?** | Original evidence, user intent, and an auditable JSON report of every step. |
| **What does it avoid?** | Runtime network calls, API keys, LLM calls, embeddings, vector stores, and lossy summarization. |
| **Current surfaces** | `optimize`, `inspect`, `prepare`, `bench`, tokenizer network guard, and semantic retrieval status scaffold. |

---

## ⚡ Key Features

- ⚡ **Local-First & Zero Telemetry**: Privacy & security focused. Runtime network access is strictly blocked by default—no data ever leaves your machine.
- 📊 **Token Estimation via `tiktoken`**: Honest token counting with explicit `exact` vs `approximate` labeling. Blocks unauthorized tokenizer downloads offline and gracefully falls back to a labeled heuristic estimator ([ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)).
- 🎯 **Prompt Context Optimization**: Deterministic whitespace normalization, conservative boilerplate removal, exact & near-duplicate paragraph deduplication, and question-aware lexical selection without lossy LLM summarization or hallucination.
- 🛡️ **Zero External Network Dependencies**: Operates 100% offline without requiring API keys, cloud LLMs, or vector databases.
- 🔍 **Read-Only Diagnostics (`lcc inspect`)**: Analyzes raw context, line counts, blank-line runs, duplicate ratios, and projected savings without modifying the source file ([ADR 0009](docs/adr/0009-inspection-command-boundary.md)).
- 🧠 **Context & Policy Routing (`act2_router`)**: Optional policy-driven routing layer for evaluating prompt context and selecting local vs. remote LLM execution strategies.
- 🧪 **Deterministic Benchmark Harness (`lcc bench`)**: Measures mechanical compression ratio, token savings, and selection states deterministically across test suites ([ADR 0007](docs/adr/0007-deterministic-benchmark-harness.md)).

---

## 💡 Why It Exists

LLM context is often noisy: repeated paragraphs, email signatures, page markers, decorative rules, inconsistent whitespace, and copied boilerplate all waste tokens. Sending raw context increases cost and can bury the evidence the model needs.

Blind compression is risky. Summaries can remove the detail that makes an answer grounded. `lcc` takes a narrower, safer approach:
- Remove only safe, redundant, or non-meaningful text;
- Never summarize, paraphrase, or rewrite the source content;
- Count tokens honestly as `exact` or `approximate`;
- Estimate cost from editable pricing data;
- Produce a deterministic JSON report explaining every step.

---

## 🚀 Installation & Quick Start

### Requirements
- **Python**: `3.11` or higher.

### Installation

For CLI usage, prefer `pipx`:

```bash
pipx install local-context-compiler
lcc --version
```

Or install into your Python environment:

```bash
python -m pip install local-context-compiler
```

Optional exact token counting with `tiktoken`:

```bash
pipx install "local-context-compiler[tiktoken]"
```

For local development:

```bash
git clone https://github.com/vetlucasmartins/lcc.git
cd lcc
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

---

## 🖥️ Command Guide & Terminal Output

### 1. `lcc inspect` — Diagnostic Inspection

Analyze a raw document without modifying it or building a prompt:

```bash
lcc inspect examples/sample_input.txt --model gpt-4.1 --report inspect_report.json
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

### 2. `lcc optimize` — Context Optimization

Clean, deduplicate, and assemble an evidence-grounded prompt package:

```bash
lcc optimize examples/sample_input.txt \
  --question "What are the key points and risks?" \
  --model gpt-4.1 \
  --output optimized_prompt.md \
  --report report.json
```

#### Terminal Output Example

```text
        lcc -- optimization summary        
Model               gpt-4.1                
Token counting      exact (tiktoken)
Original tokens     236                    
Optimized tokens    128                    
Token savings       45.8%                  
Compression ratio   0.542                  
Full prompt tokens  265                    
Est. cost before    0.000472 USD           
Est. cost after     0.000256 USD           
Est. cost savings   0.000216 USD           

Prompt written to: optimized_prompt.md
Report written to: report.json
```

---

### 3. `lcc prepare` — Inspect-First Orchestration

Runs inspection first and generates a prompt only when safe optimization is recommended:

```bash
lcc prepare examples/sample_input.txt \
  --question "What are the key points?" \
  --model gpt-4.1 \
  --output optimized_prompt.md \
  --report prepare_report.json
```

---

### 4. `lcc bench` — Deterministic Suite Evaluation

Run mechanical benchmark suites to measure compression ratios and token savings:

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

---

### 5. `lcc semantic-retrieval` — Boundary Status Scaffold

Inspect the Phase 2 semantic retrieval boundary status (disabled by default; performs no retrieval):

```bash
lcc semantic-retrieval --report semantic_status.json
```

---

## 🏛️ Architecture & Security

`lcc` is engineered around strict boundaries and architectural decision records (ADRs):

| Module | Responsibility |
| --- | --- |
| `lcc.cleaning` | Normalize text, remove conservative boilerplate, deduplicate paragraphs. |
| `lcc.token_budget` | Count tokens exactly or approximately, estimate input cost. |
| `lcc.prompt_builder` | Render evidence-aware prompt template specs. |
| `lcc.reporting` | Build deterministic JSON reports (`schema_version: "1.0"`). |
| `lcc.pipeline` | Compose the deterministic core modules. |
| `lcc.lexical_selection` | Select literal source chunks for `prepare` using lexical signals. |
| `lcc.cli` | Handle Typer/Rich CLI interface, stdin, files, and config. |
| `lcc.benchmarking` | Run deterministic benchmark fixtures ([ADR 0007](docs/adr/0007-deterministic-benchmark-harness.md)). |
| `lcc.inspection` | Read-only input diagnostics ([ADR 0009](docs/adr/0009-inspection-command-boundary.md)). |
| `lcc.semantic_retrieval` | Phase 2 boundary status scaffold ([ADR 0011](docs/adr/0011-phase-2-opt-in-semantic-retrieval-boundary.md)). |

### Key Boundaries:

- **Deterministic Core & Model-Assistance Boundary**: `src/lcc/` is model-free, offline, and deterministic. Optional model assistance stays strictly outside the deterministic core and inspection boundaries ([ADR 0010](docs/adr/0010-deterministic-first-preparation-model-assistance.md)).
- **Offline Network Guard**: `lcc` blocks runtime network requests by default—including `tiktoken`'s initial encoding downloads—via a tightly scoped guard ([ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)).
- **Inspection Boundary**: `lcc inspect` is strictly diagnostic and transformative-free ([ADR 0009](docs/adr/0009-inspection-command-boundary.md)).
- **Semantic Retrieval Boundary**: Phase 2 boundary status scaffold ([ADR 0011](docs/adr/0011-phase-2-opt-in-semantic-retrieval-boundary.md)).

---

## 🧪 Development & Testing

To run the complete test suite, static type checker, and linters:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run pytest tests
python -m pytest

# Run ruff linters & formatters
ruff check .
ruff format --check .

# Run mypy static type checking
mypy
```

---

## 🤝 Contributing & Security

Contributions are welcome! Please review [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md).

For privacy guidelines and security disclosures, see [SECURITY.md](SECURITY.md).

---

## 📄 License

Open-source software licensed under the [MIT License](LICENSE).
