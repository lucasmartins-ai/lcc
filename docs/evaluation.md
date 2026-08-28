# Evaluation

`lcc` provides two levels of evaluation:


1. **Deterministic Core Benchmark Harness** (`lcc bench`): Reports mechanical metrics (character reduction, token savings, duplicate groups, timing) for the core compression pipeline. LCC deterministic prepare and question-aware lexical selection remain governed by [ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md). The original LCC harness reports mechanical metrics and is not LLM answer quality evaluation.

2. **Hybrid Router & Local Agent Evaluation Harness** (`lcc route eval`): A deterministic development evaluation suite that assesses routing accuracy, token savings, quality gates pass rate, and escalation rates across structured task fixtures.

---

## Router & Agent Evaluation Metrics

The router evaluation harness tracks:

- `remote_tokens_total`: Total cloud tokens consumed across all cases;
- `remote_tokens_mean`: Average cloud tokens per task;
- `local_accept_rate`: Percentage of tasks solved completely locally (0 remote tokens);
- `remote_escalation_rate`: Percentage of tasks escalated to cloud after quality checks;
- `format_pass_rate`: Percentage of outputs strictly satisfying expected schema (e.g. JSON, tables);
- `lcc_compression_applied_rate`: Percentage of cases where context compression was activated;
- `average_projected_savings`: Average token savings predicted by LCC;
- `estimated_accuracy_proxy`: Deterministic verification score based on fixture assertions.

---

## Running the Router Evaluation

To execute evaluation across task fixtures:

```bash
lcc route eval --cases examples/tasks --output eval/reports/report.json
```

The runner automatically generates both machine-readable JSON and human-readable Markdown summaries:

- `eval/reports/report.json`
- `eval/reports/report.md`

---

## Example Tasks Fixtures

The evaluation suite includes test fixtures in `examples/tasks/`:

- `simple_task.json`: Short direct prompt (routed to local agent);
- `noisy_context.json`: Redundant context with high duplication (compressed then local);
- `strict_format.json`: JSON output enforcement (verified by local quality gate);
- `calculation.json`: Numeric calculation with deterministic verifier check;
- `ambiguous_context.json`: Conflicting context requiring escalation to cloud model.
