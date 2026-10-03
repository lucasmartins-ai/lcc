# Sprint 9 integration: local replay and separate regression probes

CURRENT evidence, captured/replayed 2026-10-03. Implementation baseline:
`de2ff0d` (sprint 8). The harness revision is the commit returned by
`git log -1 --format=%H -- benchmarks/msi-replay`; the exact validated
revision and commands are recorded in `docs/msi/SPRINT_9_DONE.md`.

**REPLAYED: 10 windows from 7 local sessions, 20 paired runs, 0/20 failures.**
**CURATED: 10 authored probes, 60 runs, 25/60 failures (41.7%).**
These tracks have different sampling frames and executors; their outcomes
are reported separately. Production transfer of the bench gains remains
unestablished. No tolerance or threshold was fitted to this integration data.

## Sources, selection and anonymization

The local testbed at `/Users/Master/LOOKAORCHESTRATOR` contains a desktop
checkout (`src/desktop-store.js`) without a versioned trace-export interface.
No private code is imported and no private business data is published.
The allowed fallback uses local LCC sessions.

REPLAYED source: every top-level JSONL in the local Claude Code LCC project
session directory, 10 files scanned, 7 containing matching observations.
All tool-result blocks with a pytest outcome/duration summary are included;
repeated observations remain in the denominator. Original observation window:
2026-06-18T23:51:53.626Z through 2026-06-19T22:55:16.176Z. Capture date:
2026-10-03. These are historical tool outputs re-executed against the current
frozen API, not new production traffic. An authored objective asks for the
pytest count and duration; quality checks preservation of the recorded
summary, not whether the historical agent solved its original user task.

`session_replay.py --collect <local-project-session-directory>` exports only
pytest summaries and progress markers using a positive grammar. Failure
counts are preserved when present. Paths, original session ids, commands,
user prompts, names and all other output are omitted. Each window retains
an anonymous session alias, original source SHA-256, record number,
observation timestamp and excerpt SHA-256. `sessions.json` freezes the
anonymous excerpts; replay needs neither the original files nor a private
service. This heavy redaction and outcome-summary sampling frame limit
external validity; the 10 windows are correlated within 7 sessions.

CURATED source: the 10 authored scenarios already present at session start,
now correctly labeled as regression probes rather than recordings. Scenario
mechanisms deliberately overlap sprint-7 tasks, so disjoint ids are not a
claim of independent holdout data. Authorship has not been independently
verified. Every unit and outcome is public in `traces.py` and `results.json`.
Four permanent cases are in `fixtures/`, each explicitly labeled CURATED.
No secret incident occurred during capture.

## Versioned execution and paired metrics

The REPLAYED track calls actual `lcc.msi.compile` (`msi-api-1.0`, mechanical)
and compares its output with unchanged full context under the same
`verify-1.0` standard required-fact rubric. MSI must also pass its structural
sufficiency check. Dataset: `msi-session-replay-9-2026-10-03`, N=10;
`heuristic-v1` counts on the frozen excerpts. The full and compiled receipts
both carry this dataset and actual retained-token accounting.

| Arm | Retention quality | Estimated retained tokens | Reduction vs full | External API cost | Wall p50 ms | Verifications / failures | Restores / retries / escalations | Frontier calls / avoided |
|---|---|---|---|---|---|---|---|---|
| Full context | 10/10 | 174 | 0/174 | $0 | 0.0227 | 10 / 0 | 0 / 0 / 0 | 0 / 0 |
| Public MSI API | 10/10 | 122 | 52/174 (29.9%) | $0 | 1.2580 | 10 / 0 | 0 / 0 / 0 | 0 / 0 |

No inference calls are made in either arm. Zero API spend excludes CPU and
energy; cost per successful model task and inference latency are unmeasured.
Wall times are a single run's measured local overhead, not stable goldens.
The descriptive Pareto set on retention quality, external API spend and
retained tokens is `msi_api`; baseline has less local overhead. There are no
REPLAYED regressions under this narrow rubric. No agent-success claim or
statistical equivalence claim follows from 10/10 summary preservation.

The CURATED track reuses frozen sprint-7 selection and the versioned
planner/execution/verifier interfaces (`planner-1.0`, `verify-1.0`, standard,
receipt `inference-receipt/0.1`). Dataset:
`msi-replay-9-curated-2026-10-03`, N=10, seed=7, tokenizer `heuristic-v1`.
The `msi` arm uses required-fact carrier labels as an oracle. It exercises
protection behavior; it is not the public compiler or a deployable selector.

| Arm | Quality | CI95 | Modeled chain cost | Success / modeled $ | Retained tokens | Frontier attempts | Verification calls / failures | Restores / retries / escalations | Wall p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| full | 7/10 | [0.4, 1.0] | $16.032 | 0.44 | 469 | 10 | 10 / 3 | 0 / 0 / 3 | 0.0359 |
| lcc | 4/10 | [0.1, 0.7] | $0 | N/A | 214 | 0 | 10 / 6 | 0 / 0 / 6 | 0.0371 |
| routing | 7/10 | [0.4, 1.0] | $3.352 | 2.09 | 469 | 2 | 10 / 3 | 0 / 0 / 3 | 0.0344 |
| lcc_routing | 4/10 | [0.1, 0.7] | $1.112 | 3.60 | 214 | 2 | 10 / 6 | 0 / 0 / 6 | 0.0361 |
| lcc_routing_verify | 5/10 | [0.2, 0.8] | $3.144 | 1.59 | 228 | 4 | 17 / 12 | 1 / 6 / 5 | 0.0369 |
| msi (oracle probe) | 8/10 | [0.5, 1.0] | $3.992 | 2.00 | 302 | 4 | 14 / 6 | 0 / 4 / 2 | 0.0266 |

Modeled prices are inherited illustrative USD/1k-token values, not current
vendor quotes: local=0, hosted=0.5/1.5 input/output, frontier=8/24. Every
executed attempt is priced using its routed model and context; terminal
escalation records a request and does not invent another execution. These
costs exclude CPU, energy and any unexecuted escalation handler. Pairing
uses the same task sample across arms for every one of 2,000 bootstrap
resamples (seed=7). Wide intervals do not establish equivalence.

MSI's probe quality is 8/10 vs full's 7/10 at 3.992/16.032 modeled cost
and 302/469 retained tokens. The corrected Pareto set is `lcc`, `routing`,
`lcc_routing_verify`, `msi`: retry accounting makes routing non-dominated.
This replaces the pending report's incorrect final-attempt-only cost
($2.200 for MSI) and its corresponding Pareto/transfer claims.

Matched-success denominators and risk gaps are also published in JSON:

| Arm | Matched N | Mean tokens at matched success | Frontier avoided fraction at matched success | False de-escalations | Unsafe optimization proxy | Protected units dropped |
|---|---|---|---|---|---|---|
| full | 7 | 48.0 | 0 | 0 | 0 | 0 |
| lcc | 3 | 28.3 | 1.000 | 2 | 0 | 1 |
| routing | 7 | 48.0 | 0.857 | 0 | 0 | 0 |
| lcc_routing | 3 | 28.3 | 1.000 | 0 | 0 | 1 |
| lcc_routing_verify | 4 | 28.5 | 1.000 | 0 | 0 | 1 |
| msi | 7 | 32.7 | 0.857 | 0 | 0 | 0 |

## Every failure investigated

`results.json#regressions` contains 25/25 terminal failure cells, their
actual failed-check reasons, mechanism and next experiment. Verification
failures across attempts total 36; this differs from 25 terminal failures.

- A: 14 cells. T02 (3), T03 (2), T04 (3), T05 lexical arms (3), T10 (3).
  Exact lexical selection drops fact or citation carriers. T02 and T05
  lexical output is empty and schema failure selects ABORT, not retry.
  T04/T10 retries reuse incomplete context; T03 verification restores its
  citation and passes, whereas the plain arms have no restoration budget.
- B: 3 cells, T05 full/routing/msi. A fact and instruction share a unit;
  preservation forwards the instruction and fails the forbidden-claim check.
- C: 6 cells, T08 every arm. Query vocabulary retains the injected unit.
- D: 2 cells, T06 full/routing. All-units execution forwards the ambient
  instruction; filtering arms omit it under the fixed lexical rule.

The previous pending prose incorrectly reported 26 failures and described
T02 as retrying. Receipt events establish the counts and ABORT distinction.
T07 additionally drops a protected safety note in three unprotected arms
while all still PASS the fact rubric. This gap remains visible in the
protected-drop column; preservation success is not a general safety verdict.

Permanent fixtures: F1 co-located injection (T05), F2 ambient injection
(T06), F3 query-overlap injection (T08), F4 dependency loss (T10). Each
pins input hash, all six recorded outcomes, root cause, next experiment,
and replay command. These reproduce constructed regressions; none is
misrepresented as a production incident. The 25-cell investigation includes
next experiments for the remaining traces, so no regression is omitted.

## Reproduction and hash contract

From the LCC root, no network:

```sh
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/session_replay.py --check
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/replay.py --check
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/replay.py --fixture msi-replay-9-t05
python3 -m pytest tests/test_msi_replay.py tests/test_msi_session_replay.py -p no:cacheprovider -o addopts='' -q
```

CURATED outcome digest:
`a636d2f1ff4ac1f46f20e343c6b48e80b0f99cd3475c54405ab47cc5f085f5fb`.
Every run also hashes its complete receipt, excluding receipt timestamps,
event clocks and measured latency. Versions, rationales, budgets, selection,
restoration, tokens, costs and outcomes remain hashed. `--check` compares
all stable payload fields, including aggregates, source hashes, fixture
investigations and bootstrap results; an outcome-only digest cannot hide
metric drift. Tests mutate an audit reason and an aggregate to prove this.

## Limits and next experiment

The real replay is a heavily redacted, narrow summary-retention task; the
constructed track has oracle protection and overlapping scenario mechanisms.
Neither measures live model quality or production inference costs. Therefore
the hypothesis that bench gains transfer to production is unresolved.
The next experiment is a consented, versioned testbed export with an
independent task evaluator and measured inference cost/latency, frozen
before any selection-policy changes. No thresholds were tuned this sprint.
