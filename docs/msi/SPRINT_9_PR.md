## Description

Complete the outstanding local MSI work from sprints 6–9 and make its
validation reproducible on GitHub runners. Remote main contains the spec,
Context IR, planner and verification/receipt work through sprint 5.

### Resulting behavior

- **Sprint 6 — causal necessity:** bounded remove-and-replay experiments
  distinguish necessary, conditional, redundant, protected and unknown
  units. The frozen pilot, invariants, labels, ADR and digest are committed.
- **Sprint 7 — MSI-Bench:** 12 CURATED tasks, 6 categories, 6 frozen arms;
  all 72 outcomes/receipts, paired quality and modeled cost, risk/protection
  gaps, uncertainty bands and descriptive Pareto reporting are published.
- **Sprint 8 — developer workflow:** offline `lcc.msi.compile(task, context)`
  returns context, plan, receipt and structural sufficiency; `lcc diff`
  supports auditing. Actionable CLI errors, quickstart and an executable
  example cover the workflow without an API key.
- **Sprint 9 — integration:** replay ten anonymous pytest-result windows
  from seven actual local sessions through the public API, paired with full
  context. Keep ten authored probes separately labeled CURATED; publish
  all 60 cells, all 25 terminal failures, their evidence/next experiments
  and four permanent failure fixtures.
- **Local plugin tooling:** retain the already-present stdlib icon generator.
  The existing plugin image is unchanged; the generator is not executed.

### Evidence and limits

| Track / arm | N | Quality | Estimated tokens | Cost scope |
|---|---|---|---|---|
| REPLAYED full | 10 windows | 10/10 summaries | 174 | $0 external spend; no model calls |
| REPLAYED public MSI | 10 windows | 10/10 summaries | 122 | $0 external spend; no model calls |
| CURATED full | 10 probes | 7/10 probe PASS | 469 | $16.032 modeled executed-chain cost |
| CURATED MSI oracle | 10 probes | 8/10 probe PASS | 302 | $3.992 modeled executed-chain cost |

The REPLAYED observation window is 2026-06-18 through 2026-06-19;
capture/replay occurred 2026-10-03. A positive output grammar publishes
only pytest summaries/progress markers, preserving failed outcome counts
when present and repeated observations. Original paths, identifiers,
commands, prompts and names are omitted. Anonymous session aliases, source
and excerpt SHA-256, record numbers and timestamps retain provenance.
Original logs and private testbed code are not included.

Ten windows are correlated within seven sessions. Summary preservation is
not original agent task completion. Authored probes overlap prior scenario
mechanisms and use oracle fact-carrier protection. **25/60 (41.7%) terminal
probe cells fail, with 25/25 investigated**; attempt-level verification
failures total 36. Modeled prices include every executed attempt, exclude
CPU/energy and unexecuted escalation handlers, and are not vendor quotes.
Live model quality, inference latency and transfer to production remain
unmeasured. No threshold was tuned on integration data.

Receipt hashes cover audit fields, excluding clocks/measurements only.
Replay checks compare complete stable payloads, including aggregates,
provenance, shared bootstrap samples and investigations. Mutation tests
reject reason and metric drift. Full configurations, denominators, tables
and commands are in the research reports and sprint DONE artifacts.

## Integration and CI fixes

The local and fetched histories had no merge base. This branch starts at
remote main `7ac648dfdddc715d0acfdd2f4358fd4a7dfa0117` and applies the local
content delta. Its staged snapshot was verified byte-for-byte against
local source `d92501cafcf0bce80e6225c673d1c5205a8f0948` before commit
`e09d3352dac5fc1305e40d1822379dc8b97ba7da`. Existing local history is
preserved; no force push or unrelated-history merge is needed.

Fresh CI-equivalent environments exposed problems hidden by the existing
developer environment. Commit `9df8b57c70faa0399f959a0ae81f25cb6d28e73d`:

- Pins four unchanged MSI schemas as test-only fixtures with source hashes.
  Seven loaders use the checkout instead of developer-specific paths.
- Adds `jsonschema` to the **development extra only**, so contract test
  modules execute in CI. Runtime dependencies remain unchanged.
- Replaces removed Typer `CliRunner.isolated_filesystem()` with pytest
  `tmp_path`/`monkeypatch.chdir`, preserving the CLI assertions.
- Binds the correct attribute name in the network-guard defensive error
  and fixes test imports. A new regression fails before the fix and passes
  afterward; concurrent-thread network behavior is unchanged.

No schema contract, compiler threshold, routing policy, dataset or prior
frozen result changed during publication preparation.

## Related issue

Local MSI sprint prompts and acceptance reports in `docs/msi/`; no remote
issue is required.

## How has this been tested?

Local preflight, fresh macOS development installs:

- **Python 3.11.5:** 822 passed, 5 optional/environment skips.
- **Python 3.12.14:** 822 passed, 5 optional/environment skips.
- Exact CI Ruff scope passes without the workflow's advisory `|| true`;
  exact CI mypy scope passes in both environments.
- Additional changed Python scope: mypy passes on seven source files;
  research runners and icon helper pass Ruff.
- Node unit suite passes; all 11 hook-mapping tests pass (local Node 22).
- CI answer regression: 30 cases, 0 regressions; multi-agent smoke:
  20 tasks per arm, 0 E0/E1 regressions; injection smoke: 3/3 PASS.
- Pilot, 72-run bench, 60-run probes and 20-run public API replay reproduce.
  Receipt validation uses committed fixtures; privacy grep has zero hits.
- Offline quickstart passes. Wheel and sdist build and both pass
  `twine check`. No tag, package release or deployment is performed.
- `git merge-tree --write-tree origin/main HEAD` exits 0 without conflicts
  against the inspected base. Actual GitHub mergeability and Linux/Python
  3.11/3.12 plus Node 20 results are checked after creation.

```sh
pip install -e ".[dev,tiktoken]"
pytest -q
ruff check src tests benchmarks/research/run_multiagent_ab.py benchmarks/research/run_injection_e2e.py src/lcc/relevance/verifier.py
mypy src/lcc/relevance/verifier.py src/lcc/relevance/compactor.py src/lcc/relevance/trim.py
python benchmarks/research/run_answer_eval.py --provider mechanical
python benchmarks/research/run_multiagent_ab.py --tasks 20 --provider mechanical
python benchmarks/research/run_injection_e2e.py
node test/index.test.js
node test/hook-map.test.mjs
PYTHONPATH=src python benchmarks/ablation/pilot.py --check
PYTHONPATH=src:benchmarks/msi-bench python benchmarks/msi-bench/run.py --check
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python benchmarks/msi-replay/replay.py --check
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python benchmarks/msi-replay/session_replay.py --check
```

## Checklist

- [x] New/existing Python and Node tests pass locally.
- [x] Changed code passes lint and applicable type checks.
- [x] CLI quickstart, errors and offline diff exercised.
- [x] Research evidence, failures, ADR, quickstart and changelog updated.
- [x] No runtime dependency or breaking contract change.
- [x] Local history preserved; branch integrates with inspected main.

Rollback is a normal revert of the PR commits; no data migration or
deployment rollback is required.
