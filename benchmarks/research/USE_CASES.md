# Use cases, evidence-backed

Which uses LCC's own measurements support, which they contradict, and the configuration each
one needs. Every verdict links to a numbered finding in `README.md`; nothing here is asserted
without a run behind it.

## 1. Prune a large dossier before an expensive model call — supported

**Where it wins:** the context is large relative to the harness floor and mostly noise.
On the 4.4k-token medium dossier, `compact --provider jev` cut the context 61.2 % and the total
prompt tokens 9.1 % per agent sample, with all five ground-truth facts intact in 3 of 3 agents
and a second independent run reproducing the same figures (Finding 6).

**The ceiling is the floor, not the ratio.** The saving is bounded by the context's share of what
the model actually processes: with a ~14k-per-call harness floor against a 5.5k context, removing
61 % of the context delivered 9 % off the prompt. Push the same transform into a 40k context and
the floor stops mattering. Extrapolating the measured 68.8 % reduction at the 11.5k scale against
the same floor gives a much larger saving, but that is **arithmetic, not a measurement**.

**Config:** `--provider jev` explicitly (Finding 3), default trim gear (Finding 2).

## 2. Long agent sessions with a warm prefix — supported, but only with the right flags

This is the case where the default behaviour actively loses money.

- Without `--decisions-cache`, the Jev arm was never byte-stable across five identical runs
  (5 distinct outputs). Every run is a fresh cache epoch whether you wanted one or not.
  (Finding 4)
- With `--no-marker --decisions-cache` the same five runs collapsed to one distinct output,
  `calls: 0`, full decision reuse — and a mid-prefix pass still does not pay below 12–20
  reuses. (Findings 4, 5)

**Config:** `--prefix-marker "<your break>" --preserve-tail N --no-marker --decisions-cache
<path>`, and warm the decisions cache once before the call you intend to cache against.

## 3. Offline / air-gapped context cleaning — supported

`--provider mechanical` and `optimize` never touch the network and were byte-stable at 1/5
distinct outputs each. Token counting stays honest as long as the encoding assets are cached;
otherwise the report says `approximate` and the number is 5.8 % low. (Findings 1, 4)

**Caveat:** mechanical scoring cut 75 % of the large corpus and took two of five facts with
it. Offline mode is safe for *cleaning* (dedup, boilerplate, structure) and unsafe for
*relevance dropping* when the evidence is topically unrelated to the objective. (Finding 2)

## 4. Normalising a vague brief or transcript into a structured prompt — supported, not a saving

`optimize` and `intake` grew the context at every scale tested (−13.2 % to −1.5 %, and −25.6 %
to −2.6 %). They are deterministically stable (1/5 distinct), so they are a good fit for a
cache-friendly rewrite step, but they must not be budgeted as token reductions. (Findings 2, 4)

## 5. Compacting a small context (a few blocks) — not supported

The compactor needs volume to pay for itself, and on a 1 092-token corpus the Jev pass still
cost 5 model calls to save 373 tokens it then partly invalidated. Below roughly a couple of
thousand tokens the pass costs more attention than it removes context.

## 6. Budgeting on `optimize` or mechanical scoring as if they preserve evidence — contradicted

`optimize` keeps everything. `prepare` and `compact --provider mechanical` drop 67–82 % of the
bytes and 40 % of the ground truth, every scale, every run. `--trim-head-chars 0` does the
same by removing the middle gear. These are not safe defaults to build a pipeline on.
(Finding 2)

## 7. Relying on `--provider auto` when a key may be missing — contradicted

The default falls back to mechanical scoring while reporting `degraded: false`, which is the
configuration Finding 2 shows destroying evidence. `--provider jev` fails safe instead.
(Finding 3)

---

## Configuration that the measurements support

```bash
export TIKTOKEN_CACHE_DIR="$HOME/.cache/tiktoken"     # else counts are approximate (F1)

# One epoch boundary: full pass, no protection, fresh decisions file
lcc compact dossier.md -q "<objective>" \
  --provider jev -o compacted.md -r report.json

# Inside a warm epoch: tail only, byte-stable, warm runs cost 0 scoring calls
lcc compact dossier.md -q "<objective>" \
  --provider jev \
  --prefix-marker "<!-- lcc:cache-break -->" \
  --preserve-tail 6 \
  --decisions-cache ~/.cache/lcc/decisions.jsonl
```

The drop marker no longer carries scorer values, so repeated runs are byte-stable without extra
flags (Finding 7). `--decisions-cache` still earns its place inside an epoch: it makes warm runs
free (`calls: 0`) and pins threshold-straddling blocks that would otherwise flip on a live
rescoring. `--no-marker` remains available when you would rather emit no marker at all.

Then check the report before trusting the pass: `token_count_method: exact`, `degraded:
false`, `worth_it: true`, `prefix_untouched: true` when protection was requested, and
`break_even_reuses` below the number of times you expect to reuse the pruned context.
