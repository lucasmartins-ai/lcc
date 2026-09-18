# Use cases, evidence-backed

Which uses LCC's own measurements support, which they contradict, and the configuration each one
needs. Every verdict links to a numbered finding in `README.md`; nothing here is asserted without
a run behind it, and every run is re-runnable from this directory.

Start with use case 1. It is the one that changes the economics, and everything else is a
qualification of it.

---

## 1. Prune a tool result before it enters the session — the recommended pattern

**Supported, and it is the biggest win measured anywhere in this study.**

Compaction has two placements and they are not close:

| placement | measured context cost |
|---|---|
| whole session, one pass | −7.9 % |
| whole session, three passes | −22.6 % |
| **each payload before it is appended** | **−42.4 %** |

Per-payload compaction saves **5.4 times more** than a whole-session pass, and it also spends
fewer scorer tokens (33 154 against 57 567 over the same session). The reason is arithmetic: a
whole-session drop pays to rewrite everything it invalidates, handing back most of what it
removed, while a per-payload drop pays fresh-input price on smaller content and invalidates
nothing at all. (Finding 13)

```bash
# Compact the tool result while it is still standalone, then append the result.
lcc compact fetched-page.md -q "<what you are trying to find out>" \
  -o clean.md -r report.json

# Then append clean.md to the session. The session prefix never changes, so its cache survives.
```

**Why the prefix matters that much.** Prompt caches are keyed on byte-stable prefixes. A cache
read costs roughly 0.10x the input price and a cache write roughly 1.25x, so dropping 400 tokens
by mutating a 40 000-token warm prefix invalidates far more than it saves. (Finding 5)

**Check afterwards:** `token_count_method: exact`, and `first_mutation_offset` should be `null`
or far past anything you already sent.

---

## 2. Compact a whole dossier, cold, before the first call

**Supported.** This is the case where whole-session compaction is right: nothing is cached yet,
so there is no prefix to invalidate and no epoch to break.

Measured on the categorized benchmark: `compact --provider jev` keeps **every item of every
information category** — critical facts, constraints, negative constraints, exceptions, dated
revisions and contradictions — on all four corpus scales, up to 44 128 tokens. Reduction is
44.0 % at 4.5k tokens and 49.0 % at 44k. (Finding 10, Finding 12)

```bash
lcc compact dossier.md -q "<objective>" --provider jev -o compacted.md -r report.json
lcc explain report.json --source dossier.md      # audit what it decided, and why
```

**Use `--provider jev` explicitly, never `auto`.** `auto` silently falls back to lexical scoring
when the model is unreachable, and while it now reports `degraded: true` with
`semantic_guarantee: none`, an explicit provider makes the guarantee a decision rather than a
fallback. (Finding 3)

---

## 3. Long sessions that must compact in place

**Supported, with three conditions.**

```bash
lcc compact session.md -q "<objective>" \
  --provider jev \
  --prefix-marker "<!-- lcc:cache-break -->" \
  --preserve-tail 6 \
  --decisions-cache ~/.cache/lcc/decisions.jsonl
```

The conditions, each measured:

- **Protect the prefix.** `--prefix-marker` placed after your stable material makes mid-prefix
  mutation impossible, and the report proves it with `prefix_untouched: true`. On the large
  corpus it moved the first mutation from offset 13 418 to 13 592, which is the protection
  actually doing something rather than being cosmetic. (Finding 5)
- **Reuse the pruned context 12 times or more, or do not keep the pass.** Measured break-even
  across three corpus sizes: 11.8, 12.6 and 20.3 reuses. The report states the number for your
  own pass in `break_even_reuses` and warns with a `cache_epoch_risk` message when the pass
  cannot pay for itself. (Finding 5)
- **Keep the decisions cache.** A warm run then costs zero scoring calls, and the emitted bytes
  stay identical. Measured on the 1 492-block stress corpus: cold 32 196 ms, warm 458 ms, bytes
  identical, `reused_decisions: 1 491`. (Finding 11)

---

## 4. Offline and air-gapped context cleaning

**Supported for cleaning; not supported for relevance dropping.**

`--provider mechanical` never touches the network and is byte-stable. As of the supersession rule
it keeps every item of every information category on every corpus scale, at 44.8 % to 70.7 %
reduction depending on size. (Finding 9, Finding 12)

Two caveats, both measured:

- It reaches that by keeping more. Three broad protections were tried and two were removed: a
  rule that kept every block containing a negation cue or a literal took mean reduction from
  62 % to **0.0 %**, because log lines are full of "not" and of numbers. (Finding 9)
- `--trim-head-chars 0` is the unsafe setting, not the strict one. It is the only model-scored
  arm with a category gap left (`temporal`, 0.50), because the trim band is what keeps
  near-miss evidence. (Finding 10)

---

## 5. Normalising a vague brief or a transcript — supported, and not a saving

`optimize` and `intake` grew the context at every scale tested: −13.2 % to −1.5 % for `optimize`,
−25.6 % to −2.6 % for `intake`. They clean and structure, deterministically and byte-stably, and
they are a good fit before a cache-sensitive step. They must never be budgeted as token
reductions. (Finding 2)

---

## 6. Compacting a small context — not supported

Below roughly a couple of thousand tokens the pass costs more attention than it removes, and the
scorer is called to judge a handful of blocks. Compaction needs volume to pay for itself.

---

## 7. Relying on `--provider auto` — contradicted

The default falls back to lexical scoring when the model is unreachable. It now reports that
honestly (`degraded: true`, `semantic_guarantee: none`), but the earlier measurement is the
reason to pass the provider explicitly: the fallback kept 3 of 5 ground-truth facts where the
model kept 5 of 5. (Finding 3)

---

## 8. Relying on a flat token-savings number — contradicted

A single recall or savings figure cannot tell you which kind of information a transform drops.
Measured here, a flat count read 1.00 while the categorized view showed an item missing, and the
investigation that followed found the benchmark's objective was at fault rather than the scorer.
Judge a pass per information category, and name the item that went. (Finding 10, Finding 11)

---

## 9. Asking several typed questions about the same block — contradicted

A second scored question ("does this carry a fact the objective needs, even without its
vocabulary?") correlated with the relevance question at 0.975 to 0.989 over 391 blocks, and the
rescue case it exists for fired 0 times out of 391, under two different objectives. It also cost
+77.9 % input tokens per call. Several questions about the same block in the same state yield
collinear answers; dependency or contradiction signals need a different *state* — pairs or
clusters of blocks — not another question. (Finding 11)

---

## Configuration the measurements support

```bash
export TIKTOKEN_CACHE_DIR="$HOME/.cache/tiktoken"   # otherwise counts are approximate (F1)

# Preferred: compact the payload, then append it
lcc compact tool-result.md -q "<objective>" --provider jev -o clean.md -r report.json

# Cold whole-dossier pass, before anything is cached
lcc compact dossier.md -q "<objective>" --provider jev -o compacted.md -r report.json

# Inside a warm epoch, if you must: tail only, prefix protected, decisions pinned
lcc compact session.md -q "<objective>" \
  --provider jev --prefix-marker "<!-- lcc:cache-break -->" --preserve-tail 6 \
  --decisions-cache ~/.cache/lcc/decisions.jsonl
```

Then read the report before trusting the pass, in this order:

| field | what it must say |
|---|---|
| `token_count_method` | `exact`. `approximate` means every token figure is an estimate |
| `degraded` / `semantic_guarantee` | `false` / `judged` for evidence you care about |
| `worth_it` | `true`, or the pass removed too little to justify an epoch |
| `prefix_untouched` | `true` when you asked for protection |
| `break_even_reuses` | below the number of times you expect to reuse the pruned context |
| `invalidated_tokens` | small, or you are paying to rewrite more than you removed |

And when a pass looks wrong, `lcc explain report.json --source input.md` prints why every block
was kept, trimmed or dropped, with the text behind it.
