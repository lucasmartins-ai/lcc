# MSI sprint 9: replay local sessions and publish regression evidence

## Problem and resulting behavior

Sprint 9 needs reproducible integration evidence through versioned MSI
interfaces, with paired quality/cost measurements and every failure
available for investigation. A constructed scenario must not be presented
as production traffic, and retry chains must not be priced as one attempt.

This change adds two explicitly separate tracks:

- **REPLAYED:** ten anonymous pytest-result windows from seven actual local
  LCC sessions, replayed through the public `msi-api-1.0` compiler against
  unchanged full context. Both arms preserve all recorded summaries
  (10/10); estimated retained tokens are 174 versus 122. Neither arm calls
  a model or incurs external API spend. This is summary retention quality,
  not agent task completion or production inference savings.
- **CURATED:** ten authored regression probes across six frozen arms,
  publishing all 60 runs and all 25 terminal failures. Four failures become
  permanent fixtures. This track exercises planner, verification,
  restoration and protection behavior; its MSI arm uses oracle fact-carrier
  labels and is not the public compiler.

## Implementation

- Capture all matching outcome/duration summaries from the local project's
  top-level JSONL files. Repeated observations and failed outcome counts
  remain included. Publish only summaries/progress markers through a
  positive grammar; remove original identifiers, paths, commands, names
  and prompts. Retain source/excerpt SHA-256, record number, anonymous
  session alias and observation timestamp. Original logs are not included.
- Replay published excerpts offline; no access to the original sessions,
  private testbed, credentials or network is required after capture.
- Use `lcc.msi.compile`, `planner-1.0`, `verify-1.0` standard and
  `inference-receipt/0.1`. Runtime code, schemas, thresholds and sprint-7
  benchmark files are unchanged.
- Hash complete receipt audit fields, excluding only clocks/measured wall
  time. Check all stable payload fields, including aggregates, provenance,
  bootstrap results and regression investigations; outcome-only hashes
  cannot mask metric drift.
- Price every executed probe attempt using its recorded model and context.
  Terminal escalation is a request, not an invented execution. Receipt
  dataset/cost fields agree with the replay records.
- Resample the same trace indices across arms for paired bootstrap bands.
  Publish root causes, actual failed-check reasons and a next experiment
  for every failing cell. Empty-context schema ABORT is distinguished from
  retryable task failure.

## Paired results and limits

| Track / arm | N | Quality | Estimated tokens | Cost scope |
|---|---|---|---|---|
| REPLAYED full | 10 | 10/10 summaries | 174 | $0 external spend, no model calls |
| REPLAYED public MSI | 10 | 10/10 summaries | 122 | $0 external spend, no model calls |
| CURATED full | 10 | 7/10 probe PASS | 469 | $16.032 modeled chain cost |
| CURATED MSI oracle | 10 | 8/10 probe PASS | 302 | $3.992 modeled chain cost |

The CURATED failure rate is **25/60 (41.7%)**, with **25/25 investigated**;
attempt-level verification failures total 36. The corrected Pareto set
includes `lcc`, `routing`, `lcc_routing_verify` and `msi`. Full metrics,
denominators and uncertainty bands are in the research report and frozen
JSON artifacts. No unreported successful subset is used for the headline.

The observed local-session window is 2026-06-18 through 2026-06-19;
capture/replay occurred 2026-10-03. Ten windows are correlated within
seven sessions. Redaction and the summary-availability sampling frame limit
generalization. The authored probes overlap existing scenario mechanisms
and use oracle protection. Modeled prices are illustrative, exclude CPU
and energy, and are not vendor quotes. Inference latency, live model task
quality and transfer to production remain unmeasured. No thresholds were
tuned on integration data.

## Validation

- Full suite: **821 passed, 5 existing skips**.
- Integration tests: **20 passed**; offline socket guard, allowlist,
  source freeze, receipt audit hashes, paired resampling, full-chain costs,
  aggregate drift and complete regression coverage included.
- **80/80 receipts** validate against the frozen local receipt schema.
- Both tracks reproduce with `--check`; four fixtures reproduce all six
  recorded outcomes. Published secret/PII grep has zero matches.
- Changed Python files pass Ruff and mypy with the existing Python-3.14
  environment workaround. This does not repair the pre-existing project-wide
  numpy-stub issue.
- Original sprint-7 benchmark reproduces its unchanged 72-run digest.
- No runtime or prior benchmark diff; no dependency added.

```sh
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/session_replay.py --check
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/replay.py --check
python3 -m pytest tests/test_msi_replay.py tests/test_msi_session_replay.py -p no:cacheprovider -o addopts='' -q
python3 -m pytest tests/ -p no:cacheprovider -o addopts='' -q
```

Implementation evidence commit:
`437316171b0fbe751e74e96a37dbba50cf3aecad`. Acceptance evidence and privacy
grep reproduction are in `docs/msi/SPRINT_9_DONE.md`. This change is confined
to research artifacts, tests, documentation and the changelog; reverting
these commits requires no runtime migration or rollback action.
