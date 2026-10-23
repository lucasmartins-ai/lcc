# LCC in 5 minutes

Install once, then pick the one command that matches your situation.
The deterministic examples below run offline. Installing dependencies or
staging local-model assets may use the network; Jev is an explicit remote path.

```bash
pip install "local-context-compiler[tiktoken]"   # exact token counting (optional)
pip install "local-context-compiler[laya]"       # local semantic judge (optional)
```

## 1. Clean a messy draft (60 seconds)

```bash
lcc optimize messy.txt -o prompt.md -r report.json
```

Deterministic: boilerplate stripped, exact paragraphs deduped, tokens and cost
before/after in `report.json`. Same input → byte-identical output, always.

## 2. Diagnose before you transform

```bash
lcc inspect messy.txt
```

Read-only. Tells you what `optimize` *would* remove and whether a prompt is
worth building at all (`skip` / `manual_review` / `optimize_safe`).

## 3. Drop what the objective doesn't need

```bash
# No key, no network — lexical baseline:
lcc compact dossier.md -q "reduce mobile booking friction" --provider mechanical -o compacted.md -r report.json

# No key, but want a real semantic pass (needs the [laya] extra):
lcc compact dossier.md -q "reduce mobile booking friction" --provider laya -o compacted.md -r report.json

# Key available — remote semantic judgment:
lcc compact dossier.md -q "reduce mobile booking friction" --provider jev -o compacted.md -r report.json
```

**Which provider?** `mechanical` = offline lexical heuristic.
`laya` = local semantic judgment with staged assets. `jev` = remote
semantic judgment. These descriptions are not a ranking of answer quality.
Missing Laya extra falls back honestly to mechanical
(`degraded: true`). Full table: `docs/LAYA.md`. Runnable comparison:
`examples/compact_providers.py`.

### The Jev path (when a key is available)

```bash
export TYPESAFE_API_KEY=...            # or ~/.config/lcc/typesafe.key, or the macOS keychain

lcc compact dossier.md -q "reduce mobile booking friction" \
  --provider jev -o compacted.md -r report.json
lcc explain report.json --source dossier.md
```

Jev judges blocks with typed questions instead of writing prose: kept blocks come
back byte for byte, dropped ones are named in the report, and a missing key or a
failed call degrades to a labelled fallback rather than dropping what it could not
judge. No key? Use `mechanical` or `laya` above. Contract, key resolution and the
fallback table: `docs/JEV.md`.

## 4. Long session without killing the prompt cache

```bash
# Compact each tool result BEFORE appending — never rewrite the session file:
lcc compact tool-result.md -q "<objective>" --provider mechanical --append-to session.md

# Steady state: pin warm history, freeze new turns, reuse sticky decisions:
lcc compact dossier.md -q "<objective>" --provider mechanical \
  --prefix-marker "<!-- lcc:cache-break -->" --preserve-tail 6 \
  --decisions-cache ~/.cache/lcc/decisions.jsonl --append-to session.md
```

Why: a whole-session rewrite invalidates cached tokens after the first change.
Compacting a payload before appending preserves the existing prefix. Cost
depends on scorer calls, token counts and reuse; see `docs/CACHE_ALIGNMENT.md`.
Runnable demo: `examples/long_session_cache.py`.

## 5. Audit any pass after the fact (offline)

```bash
lcc explain report.json --source dossier.md
```

Prints why every block was kept, trimmed, or dropped. Never re-runs, never
touches the network.

## 6. One-call MSI path (Python API, offline)

```python
from lcc.msi import compile

result = compile("reduce mobile booking friction", open("dossier.md").read())
print(result.context)             # compacted text, ready for a downstream model
print(result.sufficiency)         # {"checks": 1, "failures": 0, "restored": 0, ...}
print(result.receipt.to_spec_dict())  # inference-receipt/0.1 audit chain
```

Deterministic planner (`planner-1.0`) + mechanical compaction + bounded
sufficiency restoration. No key, no network, no new deps. Runnable demo:
`python3 examples/msi_quickstart.py`. Full signature: `docs/lcc/msi-api.md`.

## 7. Compare two outputs (offline)

```bash
lcc compact dossier.md -q "reduce mobile booking friction" --provider mechanical -o compacted.md
lcc diff dossier.md compacted.md
```

Sizes, token deltas, and a unified diff. Exit code is 0 whether the files
match or not; the summary tells you. Never touches the network.

## 8. Voice note or rambling request to a prompt (offline)

```bash
lcc intake voice-note.txt --report intake.json > prompt.md
```

- **Dictation** is detected on plain whisper or phone text too (filler density, a long line
  with no punctuation), not only SRT/VTT. Only content-free fillers go (", né,", ", you know,",
  "uh", a bare "tipo" after a connector); "né?" and "right?" stay, so a question stays a
  question. Every removed span is in `intake.json` under `speech.removals` with its position
  in the raw input; the prompt carries one line with the span and char counts.
- **Readiness** comes with named `reasons`: `vague_marker` (whole words, pt and en),
  `voice_dump` (3+ asks in one dictation → `NEEDS_INTAKE`), `multiple_asks` (3+ typed asks →
  `NEEDS_LIGHT_REFINEMENT`), `short_directive`, `too_short`. Only empty input is `BLOCKED`.
- **`category`** (advisory): one of the 13 request-taxonomy categories (`git_ship`,
  `failure_report`, `approve_or_pick`, ...) with `category_probability` and `category_context`
  (what the agent needs in context for that kind of request). A local classifier, about 0.3 ms
  per prompt, no network. It is shown only at probability >= 0.45 and never changes readiness.
  On an owner-labelled held-out set it was right on 0.51 of prompts (keyword rules 0.22, Opus
  0.86); at that threshold dev accuracy is 0.83 on 34% of prompts. Source and receipts:
  lcc-judge `research/goal-engine-2026-10-04/intake-judge-v1/RESULTS.md`.
- **`risk_flags`** note security or injection phrasing ("bypass security", "ignore all
  previous instructions") without blocking: a test about a bypass is a normal request.
- **Cache-stable layout:** the template comes first and the intake comment lines last, so two
  different requests share the whole static prefix
  (`python benchmarks/cache/run_intake_prefix.py --check`).

## Offline × command matrix (all rows verified without key or network)

| Command | Offline, no key | Needs key/network | Notes |
| :--- | :--- | :--- | :--- |
| `optimize` | yes | no | deterministic cleaning only |
| `prepare` | yes | no | inspect + lexical selection when safe |
| `inspect` | yes | no | read-only diagnostic |
| `compact --provider mechanical` | yes | no | lexical baseline; no semantic judgment |
| `compact --provider laya` | yes (extra or honest fallback) | no | offline semantic; missing extra → `laya+mechanical_fallback`, `degraded: true` |
| `compact --provider jev` / `auto` | falls back, never silent | yes for judgment | `auto` stays on mechanical unless `LCC_AUTO_REMOTE=1`; no key → `jev` keeps everything (`degraded`) |
| `explain` / `inspect --ir` | yes | no | reads reports/IR only |
| `diff` | yes | no | compares two files only |
| `share-stats` | yes | no | anonymous counts from local reports and the request log; sends nothing |
| `bench` | yes | no | mechanical metrics, not LLM quality |
| `intake` (no `--enable-relevance`) | yes | no | structuring only |
| `intake --enable-relevance --relevance-provider jev` | no | yes | needs `TYPESAFE_API_KEY` |
| `agent health` (default mock) | yes | no | mock backend |
| `agent run` (ollama/llamacpp/vllm) | depends on backend | backend endpoint | local backends stay offline |
| `route run/eval` | yes (mock/local default) | only if a remote model is configured | default path is local |
| `semantic-retrieval` (no flags) | yes | no | boundary status only, performs no retrieval |
| `mcp` (stdio) | yes by default | only `jev` tool calls need a key | compact tool defaults to mechanical |

Common errors all name the next step: missing file suggests checking the
path or passing `-` for stdin; bad JSON suggests regenerating with
`lcc compact -r report.json`; non-IR file suggests `lcc compact --emit-ir`.
Logging: the library never configures logging (only `logging.getLogger`
at DEBUG); the CLI prints human summaries to stderr so stdout stays pipeable.

## Where next

| Question | Answer |
| :--- | :--- |
| Jev key, fallbacks and measured numbers? | `docs/JEV.md` |
| Compact a session transcript's tool calls instead of a document? | `docs/TOOL_CALLS.md` |
| How does tool-call compaction compare with `fast-jev-compaction`? | `benchmarks/research/TRANSCRIPT_AB.md` |
| What does it do on a real session? | `benchmarks/research/REAL_SESSIONS.md` |
| Replace Claude Code's compaction summary with verbatim compaction? | `docs/CLAUDE_CODE.md` |
| Laya limits, latency, fallback? | `docs/LAYA.md` |
| Cache math and epoch discipline? | `docs/CACHE_ALIGNMENT.md` |
| What is guaranteed deterministic? | `README.md` § Architectural Boundaries & ADRs 0001–0016 |
| Full command reference? | `lcc --help`, `lcc compact --help` |
| Connect an agent (Claude Code, etc.)? | `lcc mcp` — stdio server, see `docs/MCP.md` |
| Beta tester sharing results? | `lcc share-stats reports/*.json`, see `docs/SHARE_STATS.md` |
