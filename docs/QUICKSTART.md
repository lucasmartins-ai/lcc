# LCC in 5 minutes

Install once, then pick the one command that matches your situation.
Everything below runs **100% offline** unless marked otherwise.

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
# No key, no network, no new deps — lexical baseline, biggest reduction:
lcc compact dossier.md -q "reduce mobile booking friction" --provider mechanical -o compacted.md -r report.json

# No key, but want a real semantic pass (needs the [laya] extra):
lcc compact dossier.md -q "reduce mobile booking friction" --provider laya -o compacted.md -r report.json

# Key available, strongest judgment on subtle evidence (only online command here):
lcc compact dossier.md -q "reduce mobile booking friction" --provider jev -o compacted.md -r report.json
```

**Which provider?** `mechanical` = offline heuristic, max reduction.
`laya` = offline semantic, more conservative (keeps more). `jev` = remote
semantic, best on nuance. Missing Laya extra falls back honestly to mechanical
(`degraded: true`). Full table: `docs/LAYA.md`. Runnable comparison:
`examples/compact_providers.py`.

## 4. Long session without killing the prompt cache

```bash
# Compact each tool result BEFORE appending — never rewrite the session file:
lcc compact tool-result.md -q "<objective>" --provider mechanical --append-to session.md

# Steady state: pin warm history, freeze new turns, reuse sticky decisions:
lcc compact dossier.md -q "<objective>" --provider mechanical \
  --prefix-marker "<!-- lcc:cache-break -->" --preserve-tail 6 \
  --decisions-cache ~/.cache/lcc/decisions.jsonl --append-to session.md
```

Why: a whole-session rewrite invalidates every cached token right of the first
drop (~12–20 reuses to pay off). Per-payload compaction measured **42.4%**
saved vs **7.9%** for whole-session passes. Details: `docs/CACHE_ALIGNMENT.md`.
Runnable demo: `examples/long_session_cache.py`.

## 5. Audit any pass after the fact (offline)

```bash
lcc explain report.json --source dossier.md
```

Prints why every block was kept, trimmed, or dropped. Never re-runs, never
touches the network.

## Where next

| Question | Answer |
| :--- | :--- |
| Laya limits, latency, fallback? | `docs/LAYA.md` |
| Cache math and epoch discipline? | `docs/CACHE_ALIGNMENT.md` |
| What is guaranteed deterministic? | `README.md` § Architectural Boundaries & ADRs 0001–0016 |
| Full command reference? | `lcc --help`, `lcc compact --help` |
