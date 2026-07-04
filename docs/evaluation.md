# Evaluation

`act2_router.eval_runner` is a local development harness. It is not the official Track 1
benchmark and should not be reported as official accuracy.

This is separate from the pre-existing deterministic LCC benchmark harness. LCC deterministic
prepare and question-aware lexical selection remain governed by
[ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md). The original LCC
harness reports mechanical metrics and is not LLM answer quality evaluation.

Measured today:

- `remote_tokens_total`;
- `remote_tokens_mean`;
- `local_accept_rate`;
- `remote_escalation_rate`;
- `format_pass_rate`;
- LCC compression applied rate;
- average projected savings;
- failure cases;
- estimated accuracy proxy.

The estimated accuracy proxy uses fixture checks:

- exact match when `expected_answer` exists;
- required markers;
- forbidden markers;
- valid JSON or other requested format;
- required fields when provided.

Run:

```bash
python -m act2_router.cli eval --cases examples/tasks --output eval/reports/report.json
```

The runner writes JSON and Markdown reports.
