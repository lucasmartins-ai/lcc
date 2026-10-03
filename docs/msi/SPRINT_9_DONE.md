# Sprint 9 — DONE (PASS)

- Commit: `437316171b0fbe751e74e96a37dbba50cf3aecad` (validated implementation,
  fixtures, frozen results and research report). This DONE and the English
  PR description are added in the following documentation commit.
- Gate: `SPRINT_8_DONE.md` = PASS; protocol, repo-map, sprint-09 prompt and
  repository-boundaries document read before integration.
- Scope: user confirmed sprint 9 because sprints 1–8 already have PASS
  reports. Reference repositories stayed read-only; GitHub was not accessed.
- Existing sprint-9 work was reviewed and completed; unrelated pre-existing
  `plugins/chatgpt/assets/make_icon.py` remains untouched and uncommitted.

## Acceptance

- Source declared → PASS. `benchmarks/msi-replay/sessions.json` contains
  REPLAYED N=10 windows from 7 local LCC sessions, all matching tool-result
  summaries among 10 source files. Observation window:
  `2026-06-18T23:51:53.626Z`–`2026-06-19T22:55:16.176Z`; capture 2026-10-03.
  Positive-grammar anonymization removes paths, original ids, commands,
  names and prompts, preserving outcome counts including failed counts.
  Source SHA-256, record number, timestamp and excerpt SHA-256 survive.
  The separate authored set is CURATED N=10, never called production or
  a recorded session. `research/real-world-integration.md` documents both.
- Complete paired metrics, no omitted failures → PASS. Public API:
  10 windows × 2 arms = 20 runs in `session_results.json`; summary quality,
  tokens, external spend, overhead, verification failures, restores,
  retries, escalations and frontier calls/avoided are recorded per run.
  Probes: 10 × 6 = 60 runs in `results.json`, with all attempts priced and
  all terminal failures published. Public API task quality is explicitly
  summary retention; inference task success/cost/latency are unmeasured.
- Every regression investigated → PASS. `results.json#regressions` lists
  25/25 failing probe cells, actual receipt failure reasons, root cause and
  next experiment. Actual attempt-level verification failures: 36.
  No public-API replay failure (0/20). Regression coverage is asserted by
  `test_every_curated_failure_has_a_case_investigation` and
  `test_all_regressions_have_measured_failures_and_next_experiment`.
- At least 3 permanent failures and deterministic replay → PASS. Four
  labeled CURATED fixtures (T05/T06/T08/T10) replay to all six recorded
  outcomes. Both tracks run twice with matching hashes of whole receipts,
  except documented wall time/receipt clock fields. Mutation tests prove
  policy-reason and aggregate drift are rejected.
- DONE = PASS → this report. No sprint 10 work started.

## Tests and evidence

Commands ran from `/Users/Master/LCC`, CURRENT evidence, Python 3.14;
implementation commit is recorded above. No network/provider calls.

```text
python3 -m pytest tests/ -p no:cacheprovider -o addopts='' -q
821 passed, 5 skipped in 12.57s

python3 -m pytest tests/test_msi_replay.py tests/test_msi_session_replay.py -p no:cacheprovider -o addopts='' -q
20 passed in 0.45s

.venv/bin/ruff check benchmarks/msi-replay tests/test_msi_replay.py tests/test_msi_session_replay.py
All checks passed!

.venv/bin/mypy --python-version 3.14 --ignore-missing-imports --follow-imports=silent benchmarks/msi-replay/replay.py benchmarks/msi-replay/traces.py benchmarks/msi-replay/session_replay.py
Success: no issues found in 3 source files

PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/replay.py --check
reproducible: digest a636d2f1ff4ac1f46f20e343c6b48e80b0f99cd3475c54405ab47cc5f085f5fb (60 runs, 10 traces x 6 arms)

PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/session_replay.py --check
public API replay reproducible: 20 runs

PYTHONPATH=src:benchmarks/msi-bench python3 benchmarks/msi-bench/run.py --check
reproducible: digest d62de09e65353d3a6c3ebc3c9dffc627f6a08a6135eb888452395e09eef4e93e (72 runs, 12 tasks x 6 arms)

git diff --exit-code de2ff0d -- src/lcc benchmarks/msi-bench
(empty output; exit 0: runtime and prior benchmark unchanged)

git diff --check
(empty output; exit 0)
```

The existing environment workaround is used for mypy, as in sprint 8;
this does not claim the project-wide numpy-stub problem is repaired. The
same 5 optional/environment tests remain skipped. Suite delta from sprint
8: +20 integration tests. New behavior/repairs were tested RED before
implementation, then GREEN; lint/type errors were corrected before commit.

Schema verification (existing `jsonschema`, no dependency added):

```sh
python3 - <<'PY'
from pathlib import Path
import json, jsonschema
schema = json.loads(Path('/Users/Master/msi-repos/minimum-sufficient-inference/spec/inference-receipt.schema.json').read_text())
n = 0
for name in ('results.json', 'session_results.json'):
    for run in json.loads(Path('benchmarks/msi-replay', name).read_text())['runs']:
        jsonschema.validate(run['receipt'], schema)
        n += 1
print(f'{n}/{n} receipts schema-valid; inference-receipt/0.1')
PY
```

Output: `80/80 receipts schema-valid; inference-receipt/0.1`.

Privacy grep (published content only):

```sh
rg -in 'sk-(live|test)-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}\b|ghp_[A-Za-z0-9]{8,}|xox[bap]-|-----BEGIN [A-Z ]*PRIVATE KEY-----' benchmarks/msi-replay/traces.py benchmarks/msi-replay/*.json benchmarks/msi-replay/fixtures/*.json
```

Output: empty, exit 1 (zero matches). Positive-grammar tests independently
reject private names/paths/arbitrary fields; grep is not the anonymizer.

## Benchmark

CURRENT, REPLAYED dataset `msi-session-replay-9-2026-10-03`, N=10 windows,
7 correlated sessions; `msi-api-1.0`, mechanical, `verify-1.0` standard,
`heuristic-v1`; implementation commit and reproduction commands above:

| Arm | Summary quality | Estimated tokens | External API spend | Verifications / failures | Restores / retries / escalations | Frontier calls / avoided |
|---|---|---|---|---|---|---|
| Full context | 10/10 | 174 | $0 | 10 / 0 | 0 / 0 / 0 | 0 / 0 |
| Public MSI API | 10/10 | 122 | $0 | 10 / 0 | 0 / 0 / 0 | 0 / 0 |

Reduction is 52/174 (29.9%) at matched summary quality; model-task success,
production savings and inference latency remain unmeasured. CPU/energy are
not priced. Single-run overhead is recorded in the JSON/research table.

CURRENT, CURATED dataset `msi-replay-9-curated-2026-10-03`, N=10 probes,
6 arms; seed=7, frozen planner/verifier, standard, heuristic-v1:

| Arm | Probe quality | Modeled full-chain cost | Estimated tokens | Verification failures |
|---|---|---|---|---|
| full | 7/10 | $16.032 | 469 | 3 |
| lcc | 4/10 | $0 | 214 | 6 |
| routing | 7/10 | $3.352 | 469 | 3 |
| lcc_routing | 4/10 | $1.112 | 214 | 6 |
| lcc_routing_verify | 5/10 | $3.144 | 228 | 12 |
| msi (oracle) | 8/10 | $3.992 | 302 | 6 |

Full paired metric/risk/latency tables, denominators and uncertainty are in
the research report. Corrected Pareto: lcc, routing, lcc_routing_verify,
msi. Failure rate: 25/60 (41.7%), all investigated. Oracle protection and
scenario overlap preclude a production-transfer conclusion.

## Docs/ADRs

- `research/real-world-integration.md`: source, collection, anonymization,
  method, both paired tables, every failure class, Pareto, reproduction
  and limits.
- `docs/msi/SPRINT_9_PR.md`: detailed English PR description, ready locally.
- `CHANGELOG.md`: accurate integration entry without production claims.
- `benchmarks/msi-replay/`: source/provenance freeze, public API replay,
  constructed probes, stable results and four permanent failure fixtures.
- No ADR or runtime/schema/policy change; existing versioned interfaces
  remain the boundary. No reference repository was changed.

## Deliberately skipped

- Private testbed adapter/exporter: no versioned trace interface available;
  local replay is the prompt's permitted fallback. No business-code copy.
- Live models, pricing lookups, threshold tuning, semantic judges and
  production-success claims: absent evidence/budget; no fabricated metrics.
- New runtime CLI, dependency, orchestration layer: runner is research-only
  and uses existing public compiler/planner/verifier interfaces.
- Repo archive, deployment and publication: outside scope.
- GitHub push/PR at initial sprint completion: not performed under the user's explicit "não use GitHub"
  constraint; the only configured remote is GitHub. Local commit is the
  explicit override to the protocol's working-tree-only rule. Opening the
  requested PR needs a narrow exception to that user constraint.

## Known limitations

- The hypothesis of bench gains transferring to production remains open;
  passing the artifact/evidence gates does not resolve that hypothesis.
- Replay uses redacted pytest summaries, not complete original agent tasks;
  correlated observations and selection on summary availability limit scope.
- Authored probes use oracle carrier protection and overlap prior scenarios;
  they are regression fixtures, not an independent evaluation holdout.
- Costs for probes are illustrative, all executed attempts only. Escalation
  handlers are not run; CPU/energy and model inference latency are absent.
- Initial validation used the local spec checkout. Publication preparation
  replaces machine-specific test paths with pinned in-repo schema fixtures
  and includes jsonschema in the development extra, so CI validates contracts.

## Next

Sprint 10 may use these PASS artifacts for release gates while retaining the explicit limits on summary quality, oracle probes and production-transfer evidence.

## Publication preparation — 2026-10-03

The user subsequently authorized committing and opening a PR for all local
work, including GitHub access. This supersedes the initial publication
restriction above. PR branch: `codex/msi-local-work`, based on remote main
`7ac648dfdddc715d0acfdd2f4358fd4a7dfa0117`.

The original local and fetched histories had no merge base. Instead of
forcing a history merge or rewriting either branch, publication commit
`e09d3352dac5fc1305e40d1822379dc8b97ba7da` applies the exact local tracked
content delta (sprints 6–9 and the icon helper) to remote main. The index
was compared against local source `d92501cafcf0bce80e6225c673d1c5205a8f0948`
before committing: byte-identical tracked files. Original local commits
remain preserved; their historical SHAs above are local evidence references.

CI preparation commit `9df8b57c70faa0399f959a0ae81f25cb6d28e73d` pins four
unchanged schemas as test fixtures, adds only a dev validator dependency,
replaces a removed Typer test-runner helper with pytest fixtures, and binds
the correct attribute name in the network-guard fallback diagnostic. The
new diagnostic regression failed before the fix and passed afterward.

Reproduction with fresh environments and `pip install -e ".[dev,tiktoken]"`:

- Python 3.11.5: `python -m pytest tests/ -p no:cacheprovider -o addopts='' -q`
  → **822 passed, 5 skipped in 11.39s**.
- Python 3.12.14: same command → **822 passed, 5 skipped in 12.45s**.
- Exact CI Ruff scope → `All checks passed!`; exact CI mypy scope →
  `Success: no issues found in 3 source files` in both environments.
- Additional changed Python scope: mypy → success in 7 source files;
  research/icon Ruff → all checks passed.
- Node unit suite → all passed; hook mapping suite → 11 passed (local Node 22).
- CI answer regression → 30 cases, 0 regressions; multi-agent smoke →
  20 tasks per arm, 0 E0/E1 regressions; injection smoke → 3/3 PASS.
- Pilot, 72-run bench, 60-run probes and 20-run API replay all reproduce;
  original frozen result JSONs were not rewritten by publication preparation.
- `python -m build` → wheel and sdist built; `python -m twine check` → both PASS.
- `git merge-tree --write-tree origin/main HEAD` → exit 0, no conflicts.

These are local macOS checks. Actual Linux/Python 3.11/3.12 and Node 20
GitHub checks are reported on the PR after opening; local results alone do
not claim that a remote job has already completed.
