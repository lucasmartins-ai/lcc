<div align="center">

# lcc — Local Context Compiler

**Shrink what you send to the model. Keep every byte you didn't cut. Get a receipt.**

[![PyPI](https://img.shields.io/pypi/v/local-context-compiler.svg)](https://pypi.org/project/local-context-compiler/)
[![Python](https://img.shields.io/pypi/pyversions/local-context-compiler.svg)](https://pypi.org/project/local-context-compiler/)
[![CI](https://github.com/lucasmartins-ai/lcc/actions/workflows/ci.yml/badge.svg)](https://github.com/lucasmartins-ai/lcc/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/lucasmartins-ai/lcc?style=social)](https://github.com/lucasmartins-ai/lcc/stargazers)

<img src="https://raw.githubusercontent.com/lucasmartins-ai/lcc/main/demos/compact.gif" alt="lcc compact dropping noise from a 23-block dossier, then lcc explain showing why each block went" width="820">

</div>

`lcc` prepares text for model calls: clean duplicates and boilerplate, select
context for an explicit objective, and record what was kept, trimmed or omitted.
Selected spans stay **verbatim** (no LLM rewriting), the default path runs
**offline with no API key**, and every pass writes a JSON report you can audit.

| Measured on | Before → after | What was kept |
| --- | --- | --- |
| A real Claude Code session (192 messages, 75 tool calls) | 55,411 → 18,761 tokens (**−66.1%**) | all 42 user/assistant texts, byte for byte |
| A real 337-message agent session (187 tool calls) | 199,717 → 36,645 tokens (**−81.7%**) | all 58 user/assistant texts, byte for byte |
| The demo dossier above, offline `mechanical` provider | 642 → 393 tokens (**−39.6%**) | 13 of 23 blocks, plus a reason for every drop |
| A messy brief compiled by `lcc optimize` | 415 → 245 tokens (**−41.0%**) | deduplicated content in a structured prompt |

The session rows use tool-call mode with the Jev judge; source, commands and limits are in
[real-session measurements](benchmarks/research/REAL_SESSIONS.md). The demo rows are reproducible
with the commands in the GIFs (exact tiktoken counts). Your reduction depends on how much of
your context is actually noise; below a 25% gain, `lcc` tells you it is not worth it.

## Quick start

```sh
pip install "local-context-compiler[tiktoken]"   # the CLI is `lcc`

lcc compact notes.md -q "what is wrong with the booking flow?" \
  --provider mechanical -o compacted.md -r report.json
lcc explain report.json --source notes.md        # why every block was kept or dropped
```

Use it from any MCP client (Claude Code, Cursor, Claude Desktop…):

```json
{"mcpServers": {"lcc": {"command": "lcc", "args": ["mcp"]}}}
```

Or replace Claude Code's lossy `/compact` summary with verbatim tool-call compaction:

```sh
claude plugin marketplace add lucasmartins-ai/lcc
claude plugin install lcc@lcc
```

The plugin needs the early-access function-hooks flag and a judge (a TypeSafe key for Jev, or
`provider: laya` for fully local); without one it falls back to the built-in summary. See the
[Claude Code plugin guide](docs/CLAUDE_CODE.md).

## Where it fits in a token-saving stack

| Tool | Shrinks | How |
| --- | --- | --- |
| [RTK](https://github.com/rtk-ai/rtk) | command output (`git`, `ls`, test runners) | CLI proxy that filters what a shell prints |
| [caveman](https://github.com/JuliusBrussee/caveman) | the model's answers | prompt style that makes replies terse |
| **lcc** | the context itself (docs, logs, transcripts, tool calls) | objective-driven verbatim selection with an audit report |

They compose: RTK and caveman cut what flows in and out per turn; `lcc` cuts what accumulates.

<details>
<summary><b>More demos:</b> <code>lcc optimize</code> compiling a messy brief into a structured prompt</summary>

<img src="https://raw.githubusercontent.com/lucasmartins-ai/lcc/main/demos/compile.gif" alt="lcc optimize turning a brief dumped from three places into a structured XML prompt" width="820">

</details>

## What it does not do

A structural `PASS` does not establish that a model will answer correctly.
Cleaning and prompt templates are separate transformations; compaction may add omission markers.
The default offline workflow uses lexical scoring and structural checks. Optional semantic
providers run locally (Laya) or remotely (Jev). No RAG, embeddings or vector store is implemented.

## Project status

The checkout declares Python and Node package version **1.0.0** and Python
**3.11+**. MSI sprints **1–10 have PASS reports; the research release is complete**.
The software is classified Beta in package metadata.

The [2026-10-03 audit](research/msi-audit-2026-10-03.md) findings R1–R3 are
resolved in Sprint 10: all-attempt cost accounting, shared paired bootstrap,
and full-payload drift checks are active in `MSI-Bench`. Frozen contracts,
the [architecture paper](research/paper.md), [prior-art review](research/prior-art.md),
[limitations and research agenda](research/limitations.md), [version manifest](research/versions.json),
and [master results](research/results-master.md) are published.



## Install from source

From a local checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
lcc --version
```

Runtime dependencies are Typer, Rich and PyYAML. This path requires no model
or API key. Installation may download Python dependencies; the workflows
below run offline. To install the registry package, use
`pip install local-context-compiler`; its contents may differ from this checkout.
The executable is `lcc`. The unrelated PyPI package named `lcc` is not this project.

Optional extras:

```sh
python -m pip install '.[tiktoken]'  # exact counts when encoding assets are available
python -m pip install '.[laya]'      # local semantic provider; stages model dependencies
```

Tiktoken installed without cached encoding assets can still yield estimates.
Read `token_count_method`, `tokenizer_id` and `is_estimate` in the report;
use `--require-exact-tokens` on supported commands to reject estimated counts.
See [tokenizer boundaries](docs/adr/0008-tokenizer-network-boundary.md).

## Copyable offline workflow

Create the input before invoking the CLI:

```sh
cat > dossier.md <<'EOF'
The mobile booking form erased patient input at step two.

The mobile booking form erased patient input at step two.

LOG: worker heartbeat ok in 554ms.
EOF

lcc optimize dossier.md -o prompt.md -r clean.json
lcc inspect dossier.md -r inspect.json
lcc compact dossier.md -q 'reduce mobile booking friction' \
  --provider mechanical -o compacted.md -r report.json
lcc explain report.json --source dossier.md
lcc diff dossier.md compacted.md
```

`optimize` removes boilerplate/duplicates and formats a prompt. `inspect`
reads without modifying the source. `compact` selects context for the objective;
short or protected inputs may remain unchanged. `explain` audits the report
without scoring again. `diff` prints a comparison and exits 0 even when files
are different. Human summaries go to stderr; requested text/JSON files carry
machine-readable output. See the [quickstart](docs/QUICKSTART.md).

## Python: compile context with an audit receipt

```python
from pathlib import Path
from lcc.msi import compile

result = compile(
    'reduce mobile booking friction',
    Path('dossier.md').read_text(encoding='utf-8'),
    task_id='booking-01',
)
print(result.context)
print(result.sufficiency)
print(result.receipt.to_spec_dict())
```

`compile()` uses `planner-1.0`, mechanical compaction and bounded structural
restoration. It makes **no inference call**. Its plan describes a route;
it does not execute that model. The wrapper fixes risk to `low`, so use the
[planner API](docs/lcc/inference-planning.md) explicitly for higher-risk tasks.
A receipt's zero API cost means no remote call, excluding CPU and energy.

Same inputs produce the same context bytes; receipt clocks may differ.
Empty tasks/context and negative restoration budgets raise `ValueError`.
The [API contract](docs/lcc/msi-api.md) documents `msi-api-1.0` and its limits.
For full execution/verification chains, use the separate
[verification](docs/msi/verification.md) and [escalation](docs/msi/escalation.md) APIs.

## Providers and failure handling

| Provider | Execution | Setup | What the report establishes |
| --- | --- | --- | --- |
| `mechanical` | Offline lexical scoring | Base install | `semantic_guarantee: none`; no semantic judgment |
| `laya` | Local semantic scoring | Extra and model assets; setup may download weights | Named model, budget and fallback state |
| `jev` | Remote typed decisions | `TYPESAFE_API_KEY` and network | Semantic judgment or explicit degradation; sends the objective and context blocks |

```sh
lcc compact dossier.md -q 'reduce mobile booking friction' --provider jev \
  -o compacted.md -r report.json
```

Jev's optional path evaluates typed relevance questions instead of generating
summaries. Its decisions do not prove downstream answer quality. See [Jev](docs/JEV.md)
and [Laya](docs/LAYA.md) for limits and fallback contracts.
`LCC_DISABLE_NETWORK=1` disables the Jev path. Explicit unavailable Jev keeps
context and reports degradation; unavailable Laya uses a named mechanical fallback.
`LCC_REQUEST_LOG=1` opts in to a local log of redacted goal strings (never the
context) in `./.lcc/request-log` (`LCC_REQUEST_LOG_DIR` to move it); it is off by
default. `lcc request-log` counts entries and `--delete ID` removes one.
Check `provider_used`, `degraded`, `degradation_reason`, sufficiency failures
and review flags before using the output.

`compact` writes a `relevance-compaction-1.2` report. Optional IR is
`context-ir/0.1`; the Python MSI receipt is `inference-receipt/0.1`.
Read the artifact's version before interpreting its fields.

The pipeline applies selection, deterministic protection, bounded restoration
and structural checks. Optional semantic verification is a separate single
pass. The [safety model](docs/adr/0014-minimum-sufficient-context.md),
[IR](docs/lcc/context-ir.md) and [restoration limits](docs/lcc/restoration.md)
explain where evidence can still be lost. Preservation is not a security verdict.

## Agents, MCP and Node

```json
{"mcpServers": {"lcc": {"command": "lcc", "args": ["mcp"]}}}
```

The stdio MCP server exposes `compact`, `compact_transcript`, `inspect`,
`prepare`, `explain` and `intake`. `compact` defaults to mechanical scoring.
Tool-call transcripts use a semantic provider; user/assistant messages remain
pinned. See [MCP](docs/MCP.md), [tool-call mode](docs/TOOL_CALLS.md) and
[Claude Code integration](docs/CLAUDE_CODE.md). Plugin transport and live model
execution were not exercised by the offline usability benchmark.

The Node API supports deterministic cleaning, prompt templates and intake;
it has no Python MSI/IR/planner parity. Node token counts are heuristic.
From this checkout:

```js
const { LccCompressor } = require('./index.js');
const result = new LccCompressor().compress('context text');
console.log(result.compressedText);
```

`agent` and `route` are separate optional execution paths requiring configured
backends. `semantic-retrieval` reports a disabled/blocked boundary: no retrieval
adapter is implemented. Command requirements are listed in the
[quickstart matrix](docs/QUICKSTART.md#offline--command-matrix-all-rows-verified-without-key-or-network).

## Evidence and usability

The [workflow benchmark](benchmarks/usability/REPORT.md) installs a wheel into
a fresh base-only venv and runs outside the source directory. On macOS ARM64,
Python 3.12.14, at code commit `310ab9e`:

| Measurement | Result | Scope |
| --- | --- | --- |
| First offline compile, including venv creation and wheel install | 3.14 s | N=1; existing pip cache, scripted execution |
| CLI/API/MCP workflows, including invalid-input diagnostics | 36/36 checks passed | 12 curated scenarios × 3 repetitions; synthetic text |

Times include process startup. This is executable workflow coverage, not a
human usability score or a guarantee for other machines. Full stdout/stderr,
package versions, input/runner/wheel hashes and commands are in
[results.json](benchmarks/usability/results.json).

Existing quality evidence is reported separately:

| Track | Paired quality | Context accounting | Limit |
| --- | --- | --- | --- |
| Sprint 9 REPLAYED: 10 pytest windows from 7 local sessions | Public API 10/10; full context 10/10 | 122 vs 174 estimated retained tokens; neither makes API calls | Summary retention only; correlated historical observations |
| Sprint 9 CURATED: 10 probes × 6 arms | Oracle-protected arm 8/10; full 7/10 | 302 vs 469 estimated retained tokens; modeled chain costs $3.992 vs $16.032 | Label-assisted selector and constructed executor; 25/60 terminal failures published |

Source, exact commits, reproduction and all failures:
[real-world integration](research/real-world-integration.md).
The oracle arm is not `lcc.msi.compile`. No result above establishes live-agent
success, inference latency, actual billing savings or production transfer.

The [sprint-7 pilot](benchmarks/msi-bench/REPORT.md) has 12 curated tasks and
72 arm runs. In Sprint 10, audit findings R1–R3 were resolved: full-chain attempt
costs are accounted for, bootstrap sampling is paired across arms, and `--check`
asserts complete payload stability. Historical semantic-provider experiments live in
[research status](benchmarks/research/RESEARCH_STATUS.md),
[transcript A/B](benchmarks/research/TRANSCRIPT_AB.md) and
[real-session measurements](benchmarks/research/REAL_SESSIONS.md).
They were not rerun with live providers in this audit.

External feedback exists: one contributor reported
[Laya weight reloads (#19)](https://github.com/lucasmartins-ai/lcc/issues/19)
and [network-guard thread interference (#18)](https://github.com/lucasmartins-ai/lcc/issues/18).
Both issues are closed and have offline regression tests. Their historical
timing/incident reports are user observations, not new benchmark measurements.

## Reproduce and validate

From the repository root, with Python 3.11 or 3.12:

```sh
python -m pip install -e '.[dev,tiktoken]'
mypy
ruff check src tests benchmarks/usability/run.py
pytest -q
npm test
python examples/msi_quickstart.py
PYTHONPATH=src:benchmarks/msi-bench python benchmarks/msi-bench/run.py --check
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay \
  python benchmarks/msi-replay/session_replay.py --check
PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay \
  python benchmarks/msi-replay/replay.py --check
```

The CI enforces Python tests, lint and configured-package mypy on Python
3.11/3.12, plus Node 20 unit and hook tests. Optional live Laya/Jev tests and
uncached exact-token tests may skip; a green suite does not validate them.
See [audit evidence](research/msi-audit-evidence.json) for commands and results.

To rerun the usability harness against a packaged artifact:

```sh
python -m build --outdir /tmp/lcc-dist
python benchmarks/usability/run.py \
  --wheel /tmp/lcc-dist/local_context_compiler-1.0.0-py3-none-any.whl \
  --output /tmp/lcc-usability.json --repeats 3
```

Benchmark reproduction needs a repository checkout, including frozen datasets;
a runtime wheel alone is not the research archive.

## Architecture and license

The deterministic core is `cleaning`, `token_budget`, `prompt_builder`,
`reporting`, `pipeline`, `inspection` and `benchmarking`. Relevance providers,
MSI composition and model execution live outside it. See
[ADR 0010](docs/adr/0010-deterministic-first-preparation-model-assistance.md),
[architecture](docs/architecture.md) and the [ADR index](docs/adr/README.md).

LCC uses the [MIT license](LICENSE). The optional Laya integration has
Apache-2.0 attribution in [NOTICE](NOTICE), included with packaged license files.
Maintained by [LookADev](https://lookadev.com).
