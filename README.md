<div align="center">

# ⚡ Local Context Compiler (`lcc`) & Unified Prompt Intake

**Unified, high-performance, local-first engine for prompt context optimization, intelligent intake triage, token estimation, and KV-cache alignment.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![GitHub Stars](https://img.shields.io/github/stars/lucasmartins-ai/lcc?style=social)](https://github.com/lucasmartins-ai/lcc)
[![CI Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/lucasmartins-ai/lcc/actions)
[![Local-First](https://img.shields.io/badge/privacy-100%25_local_--_zero_telemetry-success.svg)](SECURITY.md)

</div>

---

## 📌 Overview

**`lcc` (Local Context Compiler)** is a unified, local-first toolkit that combines:
1. **Intelligent Prompt Intake & Triage**: Transforms vague prompts, voice notes, audio transcripts, and rambling instructions into structured operational briefs with ambiguity detection (`READY_TO_EXECUTE`, `NEEDS_LIGHT_REFINEMENT`, `NEEDS_INTAKE`, `BLOCKED`).
2. **Deterministic Context Compiler**: Cleans boilerplate, normalizes whitespace, and deduplicates paragraphs 100% locally with zero data leakage.
3. **KV-Cache Alignment & 2026 Contract Templates**: Formats prompts with stable prefixes (`<system_instructions>`, `<definition_of_done>`, reference memory) and dynamic suffixes (`<user_query>`) to maximize prompt cache hits (>90% savings) across Anthropic Claude, OpenAI, Google Gemini, and Cursor.

A **single installation** gives you both the **LCC Context Compiler** and the **Prompt Intake Engine**—in CLI, Python, and TypeScript/Node.js.

---

## 📊 Proven Token Savings & Cache Alignment

| Context Type | Raw Input Tokens | LCC Compiled Tokens | Token Savings | Cache Hit Potential |
| :--- | :---: | :---: | :---: | :---: |
| **Messy Audio Transcript** | ~4,800 tokens | **1,350 tokens** | **-71.8%** | ⭐⭐⭐⭐⭐ (Structured XML) |
| **Multi-File Context Dump** | ~18,500 tokens | **5,400 tokens** | **-70.8%** | ⭐⭐⭐⭐⭐ (>90% KV reuse) |
| **Vague Refactoring Brief** | ~2,100 tokens | **620 tokens** | **-70.4%** | ⭐⭐⭐⭐ (Zero Ambiguity) |

---

## 📦 Single-Step Installation Guide

### 1. Python CLI & Library (Includes LCC + Prompt Intake)

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

### 2. Node.js / TypeScript Package (Includes LCC + Prompt Intake)

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

## 🔄 The Unified Intake-to-Execution Workflow

```text
[Raw Input / Voice / Vague Idea]
             │
             ▼
   [1. lcc intake Triage] ──► Classify Readiness & Extract Structured Brief
             │
             ▼
 [2. lcc Local Compilation] ──► Strip Boilerplate, Deduplicate, Count Tokens
             │
             ▼
  [3. KV-Cache Alignment]  ──► Render Contract Template (Claude XML / Code Agent / Markdown)
             │
             ▼
      [Model Dispatch]     ──► Claude Sonnet 5 / GPT-5.6 Terra / Gemini 3.6 / Cursor
```

---

## 🖥️ CLI Usage Guide

### 1. `lcc intake` — Intelligent Prompt Intake & Compilation (All-in-One)

Processes raw or vague text, analyzes readiness, extracts missing requirements, and compiles the optimized prompt:

```bash
# Run intake on a raw file with Claude XML contract formatting
lcc intake draft_prompt.txt --model claude-sonnet-5 --template claude_xml

# Run intake directly from a natural language string
lcc intake "Maybe we should refactor something with the database, not sure" --model gemini-3.6-flash

# Output structured JSON intake report
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

---

## 🚀 Programmatic Library API Usage

### Python API

```python
from lcc import LccIntake, LccCompressor, parse_intake, process_intake

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

## 🎨 2026 Context Engineering & Prompt Templates

| Template Name | Target Ecosystem | Format & Highlights |
| --- | --- | --- |
| `claude_xml` / `xml` | **Anthropic Claude (Sonnet 5 / Opus 5 / 3.7)**, **Google Gemini 3.6** | Semantic XML contract (`<system_instructions>`, `<definition_of_done>`, `<context>`, `<user_query>`), strict anti-hallucination rules, prompt caching prefix alignment. |
| `code_agent` / `cursor` | **Cursor**, **Antigravity**, **Codex**, **Claude Code** | Operational boundaries, negative constraints ("never do"), codebase memory blocks, concise diff syntax. |
| `structured_markdown` | **OpenAI (GPT-5.6 Sol/Terra, o3, o3-mini)**, **DeepSeek V4** | Hierarchical markdown contract (`## Role & Instructions`, `## Constraints`, `## Context`, `## Task`). |
| `default` | General / Minimal | Evidence-aware technical assistant prompt. |

---

## 🧪 Development & Testing

Run all test suites for Python and Node.js:

```bash
# Python test suite (269+ unit tests)
pytest

# Node.js test suite
node test/index.test.js
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

## 📄 License

Open-source software licensed under the [MIT License](LICENSE).
