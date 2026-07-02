# Project Presentation

This page is a short, visitor-facing presentation of Local Context Compiler (`lcc`). Use it
as a quick briefing for maintainers, contributors, or users evaluating whether the project
fits their workflow.

## 1. One-Sentence Summary

`lcc` is a deterministic, local-first CLI that prepares cleaner, smaller, measurable context
packages before an LLM call.

## 2. The Problem

LLM context often arrives as pasted documents, email threads, notes, logs, or transcripts with
duplicate paragraphs, signatures, page markers, decorative rules, and inconsistent spacing.
That noise increases input cost and can hide the evidence the model needs.

At the same time, aggressive compression is dangerous. A summary can remove the detail that
makes the final answer grounded.

## 3. The Product Position

`lcc` is not a model, agent, retrieval system, or hosted service. It is the deterministic
pre-processing layer before those systems.

Its promise is narrow and auditable:

- clean context without rewriting it;
- deduplicate repeated text without losing the first copy;
- count tokens honestly as exact or approximate;
- estimate input cost from editable pricing;
- build an evidence-aware prompt package;
- emit a deterministic JSON report.

## 4. What Works Today

Current release scope: `v0.2.0`.

| Surface | What it does |
| --- | --- |
| `lcc optimize` | Cleans context, builds an optimized prompt, and writes a JSON report. |
| `lcc inspect` | Profiles an input and projects safe cleanup without generating a prompt. |
| `lcc bench` | Runs deterministic fixture cases and reports mechanical optimization metrics. |
| Tokenizer guard | Blocks runtime tokenizer downloads and falls back to labelled approximate counts. |

## 5. What Is Deliberately Out of Scope

`lcc` does not currently provide:

- semantic retrieval or RAG;
- embeddings or vector stores;
- local or remote LLM calls;
- hosted APIs;
- model routing;
- response verification;
- semantic answer-quality scoring;
- voice, audio, or transcript ingestion adapters.

Those ideas are tracked in the roadmap, but they are not implemented.

## 6. Core Workflow

```text
raw context
  -> deterministic cleaning
  -> token and cost measurement
  -> evidence-aware prompt rendering
  -> JSON report
  -> downstream LLM call by your own application
```

The downstream model call is outside `lcc`.

## 7. Why Visitors Should Care

Use `lcc` when you want:

- lower input-token waste before LLM calls;
- a repeatable local process for preparing context;
- measurable before-and-after reports;
- clear privacy boundaries;
- prompt packages that preserve source evidence;
- deterministic behavior that can be tested in CI.

Avoid `lcc` when you need semantic retrieval, automatic summarization, or an application that
calls models for you. Those are different layers.

## 8. Quick Demo

```bash
python -m pip install local-context-compiler

printf 'Alpha point.\n\nAlpha point.\n\nRegards,\nTeam\n' > /tmp/lcc_sample.txt

lcc optimize /tmp/lcc_sample.txt \
  --question "What are the key points and risks?" \
  --output optimized_prompt.md \
  --report report.json

lcc inspect /tmp/lcc_sample.txt --report inspect_report.json
```

Expected result:

- `optimized_prompt.md` contains the cleaned, structured prompt;
- `report.json` explains token savings, cost estimates, cleaning steps, warnings, and token
  count method;
- `inspect_report.json` profiles the input without creating a prompt.

## 9. Trust Boundaries

`lcc` is designed to be easy to audit:

- no API keys;
- no telemetry;
- no model calls;
- no runtime network access by default;
- optional `tiktoken` use only when tokenizer assets are locally available;
- deterministic reports without timestamps, random values, absolute paths, or machine-specific
  values.

## 10. Reading Path

Recommended order for a new visitor:

1. [README](../README.md) - install, quick start, command guide, and architecture summary.
2. [Architecture](architecture.md) - module boundaries and deterministic pipeline.
3. [Evaluation](evaluation.md) - how to interpret savings and quality-preservation limits.
4. [Roadmap](roadmap.md) - what is implemented now and what is intentionally future work.
5. [ADRs](adr/) - frozen design decisions.
