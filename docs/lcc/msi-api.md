# MSI Python API (minimal, offline)

One function for the 5-minute path. Everything else (`lcc.relevance`,
`lcc.router`) stays available for advanced use.

## `lcc.msi.compile(task, context, *, task_id=None, max_restorations=8)`

```python
from lcc.msi import compile

result = compile("reduce mobile booking friction", open("dossier.md").read())
result.context       # str: compacted text, byte-identical for identical inputs
result.plan          # InferencePlan (planner-1.0, deterministic, risk low)
result.receipt       # ExecutionReceipt; .to_spec_dict() is inference-receipt/0.1
result.sufficiency   # {"checks": int, "failures": int, "restored": int, "result": "PASS"|"REVIEW"}
result.provider_used # "mechanical"
result.degraded      # False on the offline path
result.to_dict()     # JSON-serializable bundle (plan + receipt + sufficiency)
```

Guarantees:

- Offline, no key, no network, no new dependencies. Mechanical scoring with
  deterministic protection on; sufficiency restoration bounded by
  `max_restorations` (default 8, sprint-3 budgets).
- Deterministic `context` bytes for identical inputs (receipt timestamps
  excepted). `task_id` defaults to `msi-<sha12 of task>`.
- Fail-closed: empty `task`/`context` raise `ValueError` naming what to pass;
  negative `max_restorations` raises `ValueError`.
- Logging: `logging.getLogger("lcc.msi")` at DEBUG only; no handlers are
  configured, so importing `lcc.msi` never changes the caller's logging setup.

Non-goals (use the underlying APIs directly):

- Semantic judgment: pass `--provider jev/laya` on the CLI or call
  `lcc.relevance.compact_context` with another provider.
- Full verification chain: `lcc.router.verify.run_verification` +
  `lcc.router.escalate.run_execution` (see `docs/msi/verification.md`,
  `docs/msi/escalation.md`).
- Causal labels: `lcc.router.ablate.run_pilot` (research-only, ADR-0021).

Runnable demo: `python3 examples/msi_quickstart.py`.
