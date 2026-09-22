# TypeSafe Jev provider (`--provider jev`)

Jev is TypeSafe's System One model and the strongest semantic judge `lcc compact`
can use: it answers **typed questions about context blocks** instead of writing
prose. LCC is independent and not affiliated with TypeSafe.
See `README.md` (§ providers), `docs/LAYA.md` for the fully local alternative, and
`docs/adr/0013-instant-relevance-compaction-boundary.md` for the opt-in boundary.

## 1. What LCC sends and what comes back

One HTTP request scores a whole batch of blocks (`--batch-size`, default 8; batches
are sent concurrently, `--max-workers`).

| Direction | Payload |
| :--- | :--- |
| Request | `{model, state: {question, blocks[]}, questions: {...}}` — the objective plus the block heads, nothing else |
| Response | one typed answer per block (`noul` keep-probability 0–1, `choice`, or `score`) plus `usage` |

Rules LCC enforces (`src/lcc/relevance/jev.py`, `src/lcc/relevance/compactor.py`):

- **Only typed decisions are consumed.** No text the model returns ever reaches your
  context; Jev never writes, and LCC never summarizes.
- A `noul` outside 0–1 is **rejected, not clamped** (`parse_noul_answer`): a judge
  answering 1.7 is not answering the question it was asked, so the caller falls back.
- A missing `confidence` is treated as neutral by the verifier, never as maximal doubt
  (the resolved backend version omits it; see `benchmarks/research/RESEARCH_STATUS.md`).
- The resolved model version is recorded (`jev_model_resolved`), so a moving alias such
  as `jev-latest` never appears as the only model identifier.
- Every attempt is appended to the shared ledger (`logs/typesafe/jev.jsonl` under
  `LCC_LOOKAORCHESTRATOR_DIR`, or `LCC_TS_LEDGER`), with feature tag `lcc_compact`.

## 2. Key and environment

Resolution order, first hit wins:

1. `TYPESAFE_API_KEY`
2. `~/.config/lcc/typesafe.key` (`LCC_TYPESAFE_KEY_FILE` overrides the path)
3. the orchestrator checkout's `.env` (`LCC_LOOKAORCHESTRATOR_DIR`, default `~/Downloads/LOOKAORCHESTRATOR`)
4. macOS Keychain (`security find-generic-password -s typesafe -w`)

| Variable | Effect |
| :--- | :--- |
| `TYPESAFE_ENDPOINT` | System One endpoint (default `https://api.typesafe.ai/v1/systemone`) |
| `TYPESAFE_MODEL` | model id (default `jev-latest`) |
| `LCC_DISABLE_NETWORK=1` | kill switch: no client is built and no request leaves the machine |
| `LCC_TS_LEDGER` | ledger path override; the ledger is written only when its directory exists, and write failures never break a pass |

Retries: 408/425/429/500/502/503/504/529 and network errors are retried three times
with a 1.5 s × attempt backoff; any other status fails immediately. TLS prefers
certifi's CA bundle when it is installed, so interpreters without a CA store still
verify.

## 3. Fallback (never silent)

| Situation | `provider_used` | `degraded` | `semantic_guarantee` | What happens |
| :--- | :--- | :--- | :--- | :--- |
| `--provider jev`, no key or network disabled | `degraded` | true | `none` | keeps every block (fail-safe) |
| `--provider auto`, no key | `mechanical` scoring | true | `none` | mechanical pass, `degradation_reason: jev_unavailable_mechanical_fallback` |
| a batch fails mid-run | `jev+mechanical_fallback` | true | `partial` (`none` when nothing was judged) | remaining blocks scored mechanically; already-judged blocks keep their Jev verdict |
| state over the 32,768-token window | same as a failed batch | true | `partial` (`none` when nothing was judged) | refused **before** the call (`JevStateTooLargeError`, ledger `pre_flight:`) — no round trip is spent on `400 max_tokens_exceeded` |

Warnings in the report name the reason (`jev_unavailable`, `jev_batch_failed`). A
failed pass never drops content it could not judge.

## 4. Why this is not summarization

| | Classic summarization | `lcc compact --provider jev` |
| :--- | :--- | :--- |
| What changes | a model rewrites your context into new text | blocks are re-emitted byte for byte or dropped (trim keeps a bounded head plus a note) |
| What can vanish | a path, an error string, a constraint — silently | only blocks whose keep-probability fell below the threshold, each one named in the report |
| Audit | none by default: the summary replaces the source | `lcc explain report.json --source dossier.md` states why every block was kept, trimmed or dropped |
| Repeatability | re-summarizing emits different bytes | sticky decisions plus a decisions cache make warm runs free and byte-identical |
| Failure mode | a bad summary is undetectable downstream | a failed judge keeps content and reports `degraded: true` |

## 5. Measured behaviour (2026-09-21, resolved `jev-1.13.0`)

| Check | Result | Sample |
| :--- | :--- | :--- |
| Adversarial suite E0 | 30/30 kept, mean reduction 50.2%, min survival 1.0 | 30 cases |
| Answer-level regression | 0 regressions (required-fact recall delta ≥ 0) | 30 cases |
| Multi-scale reduction | −21.2% (1.2K) / −40.0% (4.5K) / −49.8% (11.6K) / −52.1% (44K), 100% category recall | 4 scales |
| Answer preservation (Jev selector, mock downstream) | −58 tokens/task, correctness delta 0.0; verifier PASS 29–31, REVIEW 19–21, FAIL 0 | 50 tasks |
| Cost | $0.005 (1.2K) → $0.187 (44K) per pass | 4 scales |
| Token count, API vs local (pre-flight calibration, 2026-09-22) | worst fit `api = 249 + 0.98 * local` (prose-JSON); second run combined `api = 437 + 0.90 * local` — the API never counted above the local tiktoken count + a small fixed overhead, so at the refusal point it still projects under the cap (32,361 worst case). Cost: the band refused that the API would take, 1–10% of the window across the three fits | 6 API measurements + 1 live refusal, 2 runs |

Limits, stated plainly: the provider is remote, so it needs the network and a key
(everything else in LCC stays offline); the resolved backend returned no `confidence`,
so the selector's confidence gear is inert against it; on the 12-block ablation corpus
the raw judge made 2 false drops, which is exactly why the safety, graph, sufficiency
and verifier layers exist — **individual drops are not safe by construction**; blocks
are judged whole, so granularity is the block, not the sentence.

Repro (all in `benchmarks/research/`): `python3 run_comparative_stress_test.py`,
`run_adversarial.py jev`, `run_answer_eval.py --provider jev`,
`run_judge_ablation.py --judge jev`. Full rows, provenance and limitations:
`benchmarks/research/RESEARCH_STATUS.md`.

## 6. Run it

```bash
export TYPESAFE_API_KEY=...

lcc compact dossier.md -q "reduce mobile booking friction" \
  --provider jev -o compacted.md -r report.json

# Fewer, fuller calls: batches of 8, four in flight
lcc compact dossier.md -q "…" --provider jev --batch-size 8 --max-workers 4

# Cache-safe incremental pass (never rewrites the bytes already in the session)
lcc compact tool-result.md -q "…" --provider jev --append-to session.md \
  --decisions-cache ~/.cache/lcc/decisions.jsonl
```

Report fields worth reading: `provider_requested`, `provider_used`, `degraded`,
`degradation_reason`, `semantic_guarantee`, `jev_model_requested`,
`jev_model_resolved`, `calls`, `reduction_ratio`, `invalidated_tokens`,
`break_even_reuses`. Audit any pass offline with
`lcc explain report.json --source dossier.md`.
