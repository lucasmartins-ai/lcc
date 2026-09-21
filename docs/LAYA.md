# Laya local semantic provider (`--provider laya`)

Laya is an optional, fully local semantic decision backend for `lcc compact`
(developed by NandhaKishorM / Convai Innovations, Apache 2.0 —
<https://github.com/NandhaKishorM/laya>).
LCC is independent and not affiliated with the Laya author.
It answers the same typed `noul` questions Jev answers, on-device, with zero
network calls and zero remote tokens. See also `README.md` (§ providers) and
`docs/adr/0013-instant-relevance-compaction-boundary.md` for the opt-in boundary.

## 1. Real context limits (not marketing numbers)

| Checkpoint | Context limit | Reserved heads | State budget (`available_state_tokens`) |
| :--- | ---: | ---: | ---: |
| `convaiinnovations/laya` | 512 | 192 | **319** |
| `convaiinnovations/laya-multilingual` (default) | 1024 | 192 | **831** |
| `convaiinnovations/laya-typed-decisions` | 1024 | 192 | **831** |

Rules LCC enforces (see `src/lcc/relevance/laya.py`, `compactor.py`):

- `available_state_tokens = max(16, context_limit - head_reservation - 1)`.
- The objective plus one batch must fit. Blocks are packed greedily
  (`_batch_blocks_for_laya`); a block that alone exceeds the room is **never
  sliced** — it is kept whole with warning `laya_context_limit_exceeded` and
  audit reason `laya_context_limit_exceeded` (`status: insufficient_context`).
- Override only when you know the checkpoint: `--laya-context-limit N`
  (`LayaClient(context_limit=…)`). Values below 64 are rejected by the CLI.
- The report proves compliance: `laya_context_limit` (budget) vs
  `context_budget_used` (largest objective + one-batch state actually sent).
  If `context_budget_used > laya_context_limit`, the pass is misconfigured —
  lower `--batch-size` or raise the limit.

## 2. Latency: what to expect and how to measure

There are **no committed CPU-vs-GPU numbers in this repo**: latency depends on
device, checkpoint, batch size, and block length. Every run reports its own
cost — trust the report, not a table:

- `latency_ms`: sum of Laya `evaluate()` batch times (model inference only).
- `compilation_ms`: wall clock of the whole pass (splitting + scoring +
  graph + sufficiency).
- `calls`: number of Laya batches actually executed.

What moves the number:

- Device (`--laya-device cpu|mps|cuda|auto`): CPU is fine for small dossiers;
  CUDA/MPS cuts per-batch time on large ones.
- Batch size (`--batch-size`, default 8): fewer, fuller batches mean fewer
  calls but larger states — stay inside the budget above.
- Cache (`--decisions-cache`): warm runs skip scoring entirely (`calls: 0`).

Measure your own hardware:

```bash
lcc compact dossier.md -q "<objective>" --provider laya \
  --laya-model convaiinnovations/laya-multilingual --laya-device cpu \
  -o out.md -r report.json
python3 -c "import json; d=json.load(open('report.json')); print(d['calls'], d['latency_ms'], d['compilation_ms'], d['context_budget_used'], d['laya_context_limit'])"
```

Compare with `run_laya_comparison.py` in `benchmarks/research/` for the
recall/reduction side. Since 2026-09-21 that script runs the REAL backend by
default (`--mock` opts into the labelled offline harness); live rows and
provenance: `benchmarks/research/RESEARCH_STATUS.md`.

## 3. When to use which provider

| You want… | Use | Why |
| :--- | :--- | :--- |
| Offline, CI, huge dossier, max reduction, no new deps | `--provider mechanical` | Lexical baseline, unbounded context, drops only zero-overlap (+ safety net). `semantic_guarantee: none`. |
| Offline **with** a real semantic pass, no API key | `--provider laya` | Local System 1 judgment inside a 512/1024 budget. More conservative than mechanical (keeps more), `semantic_guarantee: judged`, $0. |
| Strongest judgment on subtle/paraphrased evidence, key available | `--provider jev` | Remote 32K System 1, best on nuance. Costs ~$0.001/call, needs `TYPESAFE_API_KEY`. |
| Don't care, just work | `--provider auto` | Prefers Jev, falls back to mechanical with `degraded:true`. Explicit is better for audits. |

Decision shortcut:

- No key and no `pip install …[laya]` → `mechanical`.
- No key but `[laya]` installed → `laya`.
- Key available and evidence is subtle → `jev` (or compare `laya` vs `jev`
  on your dossier and keep the one with 100% category recall).

## 4. Trade-off, stated plainly (measured 2026-09-21, real weights)

Laya is **more conservative than mechanical**: it keeps semantically related
content that shares no words with the objective, so reduction is lower and
preservation is higher. Measured on the research corpora with the real default
checkpoint (`laya-multilingual`): it currently keeps **essentially every block**
— 0.0% reduction at small/medium/large and −0.5% at XL — against mechanical
−70% and remote Jev −52% on XL, all at 100% category recall. That is the
intended trade pushed to its limit: a semantic pass that never drops cannot lose
content, and it cannot save tokens either. If you need maximum bytes removed and
accept heuristic judgment, use mechanical. If you need a semantic pass without a
key and can accept the ~0% local reduction, use Laya. A checkpoint that drops
confidently remains the open requirement for real local reduction — see §7 and
`benchmarks/research/RESEARCH_STATUS.md`.

Additional safety nets apply equally to all providers: type-aware trim,
deterministic protection (quoted speech, cross-language evidence,
distinctive-term links), graph + sufficiency restoration (`--max-restorations`),
and confidence degradation (`--confidence-threshold`). Laya does not bypass
any of them.

## 5. Install, run, fallback

```bash
pip install "local-context-compiler[laya]"   # torch + transformers + laya
# or
pip install laya torch transformers

lcc compact dossier.md -q "reduce mobile booking friction" --provider laya \
  -o compacted.md -r report.json

# Explicit checkpoint + device + calibration:
lcc compact dossier.md -q "…" --provider laya \
  --laya-model convaiinnovations/laya-multilingual --laya-device cpu \
  --laya-temperature 2.0 -r report.json
```

Env vars: `LCC_LAYA_MODEL`, `LCC_LAYA_DEVICE`, `LCC_LAYA_TEMPERATURE`.
`LCC_DISABLE_NETWORK=1` forces Hugging Face offline mode (`HF_HUB_OFFLINE=1`).

**Fallback (never silent):** Laya missing or a batch failing never drops
content via the failed path. Missing extra → mechanical scoring as
`provider_used: laya+mechanical_fallback`, `degraded: true`,
`degradation_reason: laya_unavailable_mechanical_fallback`,
`semantic_guarantee: none` + `laya_unavailable…` warning.
Failed batch → remaining blocks scored mechanically,
`provider_used: laya+mechanical_fallback`, `semantic_guarantee: partial`.
Oversized block → kept whole (`laya_context_limit_exceeded`).

## 6. Report fields (schema `relevance-compaction-1.2`)

- `provider_requested`, `provider_used` (`laya`, `laya+mechanical_fallback`,
  `mechanical`, `cache`, …), `degraded`, `degradation_reason`,
  `semantic_guarantee` (`judged`/`partial`/`none`).
- `laya_model_requested`, `laya_model_resolved`, `laya_context_limit`,
  `context_budget_used`, `laya_temperature`.
- `calls`, `latency_ms` (model only), `compilation_ms` (whole pass).
- Standard: `threshold`, decisions with `score`/`confidence`/`reason`/
  `relationships`/`content_type`, sufficiency, cache accounting, warnings.

`lcc explain report.json --source dossier.md` audits any Laya pass offline.

## 7. Validation status (2026-09-21)

Live validation ran against the real checkpoints on macOS/CPU, offline
(`LCC_DISABLE_NETWORK=1`, HF hub offline, no API key), through
`lcc compact --provider laya` and the scripts in `benchmarks/research/`:

| Check | Result |
| :--- | :--- |
| Real inference | `provider_used: laya`, `degraded: false`, `semantic_guarantee: judged`, resolved `laya-rl-agent` |
| Context budget | every state ≤ 1024 tokens (max `context_budget_used` observed: 520); oversized blocks kept whole with `laya_context_limit_exceeded`, tail byte-identical — no slicing |
| Offline, no fallback | no network and no key present; the pass never fell back to mechanical |
| Default checkpoint (`laya-multilingual`) | keeps essentially every block: 0.0% reduction at small/medium/large, −0.5% at XL; 6/6 noise blocks kept on the ablation corpus |
| Cache path | cold 43.2 s → warm 0.5 s (83.6×), 391 decisions reused, byte-identical output |

Repro (all real by default; `--mock` opts into the labelled harness):
`run_laya_comparison.py`, `run_judge_ablation.py --judge laya`,
`run_laya_context_cases.py`, `run_comparative_stress_test.py`; gated integration
test `LCC_LAYA_INTEGRATION=1 pytest tests/test_laya_integration.py`.
Checkpoint comparison (`--laya-model convaiinnovations/laya-typed-decisions`),
sample sizes, limitations and labelled mock archives:
`benchmarks/research/RESEARCH_STATUS.md`.

Note: selecting a checkpoint requires the request field (`--laya-model` /
`RelevanceCompactionRequest(laya_model=...)`). `LCC_LAYA_MODEL` alone sets a
standalone `LayaClient()` but is stamped over by the request default inside
`compact_context` — flagged as a follow-up in RESEARCH_STATUS.
