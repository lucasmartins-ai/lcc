# Offline workflow usability benchmark

BENCHMARK evidence; CURATED workflows with SYNTHETIC text. Captured on
2026-10-03, Python 3.12.14, macOS-26.6.2-arm64-arm-64bit. N=12 scenarios, three
repetitions each (36 checks), one fresh installation. **No human participants.**
This measures command execution and observable error handling, not learning
speed, satisfaction, task discovery or production task success.

## Provenance and reproduction

Code commit: `310ab9e21121c46c254d643ffb738d8cb8d41eb4` (audit fixes and runner).
Runner SHA-256: `8d47e6ed10e1065f4b3e7c9a85e08b6f6f93d6f72df8f2c11f65cb1519a6652a`.
Wheel SHA-256: `8dbf98023284535b31106e86abece58f07abd3a1be852aac78a2bb9d600a2645`.
Input SHA-256: `d80bcf24ff8b7d9b6c7653687c82c4e71ed730147829d8e7e9732a9fa6aab563`.
All commands, full stdout/stderr, expected-error outcomes, times and installed
package versions are frozen in [results.json](results.json).

From the repository root:

```sh
python -m pip install -e '.[dev]'
python -m build --outdir /tmp/lcc-dist
python benchmarks/usability/run.py \
  --wheel /tmp/lcc-dist/local_context_compiler-1.0.0-py3-none-any.whl \
  --output /tmp/lcc-usability.json --repeats 3
```

Rebuilt wheels may have different ZIP timestamps/hashes. The recorded wheel
hash identifies the measured artifact; times are observations, not golden
assertions. The harness fails on a wrong exit code or failed content check.
It installs base dependencies only and rejects accidentally present Laya or
tiktoken. Each workflow runs outside the checkout with no `PYTHONPATH`.
`LCC_DISABLE_NETWORK=1` is set; dependency installation may use the network.

## Results

Fresh-venv creation, wheel install, dependency inventory and first Python
compile took **3.14 s** end to end (N=1, existing pip cache).
The first compile passed. This time excludes reading documentation and
writing a user's input. Process startup is included in every row below.

| Workflow | Checks passed | Median wall ms (N=3) |
| --- | --- | --- |
| `help` | 3/3 | 213.8 |
| `optimize` | 3/3 | 188.2 |
| `inspect` | 3/3 | 182.7 |
| `compact` | 3/3 | 188.6 |
| `explain` | 3/3 | 179.6 |
| `diff` | 3/3 | 183.1 |
| `python_api` | 3/3 | 131.2 |
| `missing_file` | 3/3 | 178.9 |
| `invalid_report` | 3/3 | 183.4 |
| `invalid_api` | 3/3 | 135.5 |
| `retrieval_status` | 3/3 | 184.3 |
| `mcp` | 3/3 | 178.4 |

The valid-input checks cover help discovery, cleaning output, a read-only
inspection report, mechanical compaction with retained evidence and honest
provider/count labels, report explanation, text comparison, Python receipt
shape, retrieval status and framed MCP initialization/list/compaction.
Invalid-input checks require an actionable missing-file message, a malformed
report diagnostic and an explicit empty-task API error. Sources remain unchanged.
This is not exhaustive invalid-input coverage.

The short text's three blocks are protected. Compaction preserves all 154
characters: **0% reduction is the correct result here**, with no semantic
judgment. The benchmark makes no quality-per-dollar or compression claim.
Token counts are estimates; no model, judge or plugin host is invoked.

## Corrections and actual feedback

The initial packaged run found `mechanical` falsely labeled `judged` when
all blocks were protected. A dedicated regression test failed on that exact
condition before the fix; the corrected run passes. See the
[audit](../../research/msi-audit-2026-10-03.md).
The initial harness also expected the diff summary on stdout with the word
`heuristic`; the CLI correctly prints its human summary on stderr and calls
the count `approximate`. The harness was corrected to the documented contract.
No thresholds, fixture text or workflow acceptance goals were tuned for timing.

External feedback is separate from this benchmark: one reporter opened
[issue #19](https://github.com/lucasmartins-ai/lcc/issues/19) about repeated Laya
weight loads and [issue #18](https://github.com/lucasmartins-ai/lcc/issues/18)
about cross-thread network interception. Both are closed and their offline
regression tests pass. No new live Laya/Jev measurement is claimed.

## What this cannot conclude

One machine, three repetitions, one synthetic document and scripted command
selection cannot establish human usability. Base-only installation excludes
model setup, cold tokenizer assets, Windows, plugin transport, actual model
answers and concurrent production workloads. A next usability study should
ask unfamiliar users to complete a predefined task from the README, record
completion/errors/time, and preserve unsuccessful attempts in the denominator.
