# Sprint 8 — DONE (PASS)

- Commit: branch `msi/sprint-8-dx` (exact sha in the PR). Working tree was clean at start
  except one pre-existing untracked foreign file (`plugins/chatgpt/assets/make_icon.py`),
  left untouched and uncommitted.
- Gate: `SPRINT_7_DONE.md` = PASS (verified before any edit); no API freeze violation —
  planner (`planner-1.0`), verifier (`verify-1.0`), receipt (`inference-receipt/0.1`),
  Context IR (`context-ir/0.1`) contracts unchanged.

## Acceptance

- [x] Fresh-venv install + quickstart verde em ≤5 min → PASS. Evidence (N=1 honest, UTC):
  `python3 -m venv /tmp/msi8-venv` + `/tmp/msi8-venv/bin/pip install -e .` →
  `2026-10-03T13:41:20Z START install` … `2026-10-03T13:41:23Z INSTALLED`
  (`lcc 1.0.0`, 4 base deps, ~3 s); quickstart `2026-10-03T13:42:08Z QUICKSTART-START`
  → `optimize` exit 0 → `inspect` exit 0 (`2026-10-03T13:42:14Z INSPECT-DONE`) →
  `compact --provider mechanical` exit 0 (`2026-10-03T13:42:14Z COMPACT-DONE`) →
  `explain` exit 0 (`2026-10-03T13:42:16Z EXPLAIN-DONE`) →
  `diff` exit 0 (`2026-10-03T13:42:16Z DIFF-DONE`) →
  `examples/msi_quickstart.py` exit 0 (`2026-10-03T13:42:27Z MSI-EXAMPLE-DONE`,
  `receipt ok: inference-receipt/0.1`). Install-to-done ≈ 67 s, quickstart
  itself ≈ 19 s — both well under 5 min.
- [x] 100% dos exemplos executáveis e verdes → PASS. Evidence:
  `python3 examples/msi_quickstart.py` exit 0 (`provider: mechanical`,
  `receipt ok: inference-receipt/0.1`); `python3 examples/compact_providers.py`
  exit 0; `python3 examples/long_session_cache.py` exit 0;
  `python3 -m pytest tests/test_examples.py -p no:cacheprovider` → 4 passed
  (3 example-runs + quickstart-flag guard, all offline, no key).
- [x] Núcleo determinístico prova offline → PASS. Evidence:
  `python3 -m pytest tests/test_deterministic_boundary.py tests/test_msi_dx.py`
  → green; `test_msi_dx.py` blocks `socket.connect`/`create_connection` +
  `LCC_DISABLE_NETWORK=1` + no key and still gets byte-identical
  `compile()` context twice, `diff` exit 0, and `msi.py` carries zero
  `socket/requests/urllib/http/httpx/torch/transformers/laya/openai/anthropic`
  imports (AST-asserted). `msi.py` is intentionally NOT in the core boundary
  list: it wraps the opt-in layers (`lcc.relevance`, `lcc.router`) by design,
  so the core invariant (core never imports opt-in layers) is preserved.
- [x] Zero comandos sem workflow real documentado → PASS. Evidence:
  `lcc --help` lists 12 commands (optimize, prepare, bench, semantic-retrieval,
  inspect, compact, explain, diff, intake, agent, route, mcp); every row has a
  workflow + offline/key requirement in `docs/QUICKSTART.md` § "Offline ×
  command matrix" (14 rows). `semantic-retrieval` (no flags) is documented as a
  boundary-status check that performs no retrieval — a real workflow, not a stub.
  New `diff` workflow: compact then diff before sending to a model.
- [x] `SPRINT_8_DONE.md` em PASS (this file, `docs/msi/`).

## Testes

- `python3 -m pytest tests/ -p no:cacheprovider` → **801 passed, 5 skipped, 0 failed**
  (baseline before sprint: 795 passed + same 5 env/opt-in skips; +6 new here:
  5 in `tests/test_msi_dx.py`, 1 in `tests/test_examples.py`; no regressions).
- `python3 -m pytest tests/test_msi_dx.py tests/test_examples.py
  tests/test_deterministic_boundary.py tests/test_cli.py tests/test_cli_compact.py`
  → all green (subset re-verified after lint fixes).
- `.venv/bin/ruff check` on `msi.py`, `cli.py`, `test_msi_dx.py`,
  `test_examples.py`, `msi_quickstart.py` → clean (5 E501 + 1 I001 fixed).
- mypy (`--python-version 3.14 --ignore-missing-imports --follow-imports=silent`,
  sprint-2 workaround) on `msi.py`, `cli.py` → `Success: no issues found`
  (1 missing `dict[str, Any]` annotation fixed). Project-config mypy remains
  unrunnable env-wide (pre-existing numpy-stub issue).
- 2 correction loops, both pre-commit: ruff E501/I001 (line length + import
  order) and mypy index-on-object (payload annotation) — no behavior change.

## Benchmark

DX sprint: the benchmark IS time-to-first-compile (N=1 honest, not statistics)
plus the offline×command table (CURRENT, REAL env, 2026-10-03):

| step | evidence | time |
|---|---|---|
| `pip install -e .` (fresh venv, base only) | `13:41:20Z` → `13:41:23Z INSTALLED` | ~3 s |
| `optimize` + `inspect` + `compact` + `explain` + `diff` | exits 0, above | ~8 s |
| `examples/msi_quickstart.py` | exit 0, receipt `inference-receipt/0.1` | ~11 s later run |
| install-start → quickstart-done | timestamps above | ≈ 67 s total (≤5 min) |

No quality/cost claim (sprint de DX; quality + cost together required from
sprint 5 on — unchanged). Tokenizer in fresh venv is heuristic (tiktoken not
installed); counts are labeled estimates, never implied exact.

## Docs/ADRs

- Created: `src/lcc/msi.py` (`compile(task, context)` → context/receipt/
  sufficiency, `msi-api-1.0`, zero new deps, no network), `docs/lcc/msi-api.md`
  (signature, guarantees, non-goals), `examples/msi_quickstart.py`,
  `tests/test_msi_dx.py` (5 tests).
- Altered: `src/lcc/cli.py` (new offline `lcc diff LEFT RIGHT`, actionable
  errors on missing/unreadable files, bad JSON, non-report, stdin misuse,
  task/cases paths), `docs/QUICKSTART.md` (§6 MSI Python API, §7 diff,
  offline×command matrix, logging paragraph — single quickstart location, no
  second file), `tests/test_examples.py` (+msi example, +`lcc diff`/`msi`
  quickstart-flag guard), `CHANGELOG.md` (Unreleased/Added entry).
- No ADR: no contract, threshold, budget, or policy changed (planner, verifier,
  receipt, IR schemas untouched); DX surface only, decisions recorded here.

## Deliberately skipped

- `QUICKSTART_MSI.md` as a second file: skipped — sprint allows extending the
  existing quickstart and one location beats two (test pins the single file).
- Interactive wizard, telemetry, new breaking changes: OUT scope per sprint
  prompt (no wizard, no telemetry, no breaking change, no CHANGELOG migration
  needed).
- `--verbose/--quiet` flags and `LCC_LOG` env: skipped — library configures no
  logging (DEBUG logger only, no handlers) and CLI already separates
  machine-stdout from human-stderr; flags add surface with no workflow asking
  for them.
- Live-model timing and `strict` vs `standard` latency split: OUT scope (no
  keys, no network in this env); fresh-venv timing is deterministic overhead
  only, declared.
- CLI surfacing of plan/verify/escalate/ablate beyond the library: unchanged
  (library-only since sprints 4–6; `compile()` is the first CLI-adjacent
  default because the quickstart workflow needed it).
- Commit + PR: performed (branch `msi/sprint-8-dx`, narrow override of protocol
  §anti-slop per explicit user instruction, same call as sprints 6–7). No
  existing branch touched; foreign untracked file excluded.
- `plugins/chatgpt/assets/make_icon.py` (untracked, foreign): left alone.

## Known limitations

- `compile()` fixes risk to `low` and provider to `mechanical`: the 5-minute
  default, not a routing claim; nuanced tasks still need the planner +
  Jev/Laya path explicitly.
- `compile()` receipt `restored` derives from keep-reasons containing
  "restor" (mechanical path); full restore→retry→escalate chains still live in
  `lcc.router.escalate.run_execution`, not in this wrapper — documented in
  `msi-api.md` non-goals.
- `lcc diff` token deltas use the same counter as the CLI session (heuristic
  without tiktoken); the method is printed, never implied exact.
- Fresh-venv timing is N=1 on this machine (Apple Silicon, Python 3.14,
  2026-10-03); it proves ≤5 min here, not everywhere.
- Project-config mypy unrunnable in this env (pre-existing numpy-stub issue);
  clean with the sprint-2 workaround flags.

## Next

Sprint 9 replays real-world traces through the frozen DX surface above and turns every regression into a permanent bench fixture.
