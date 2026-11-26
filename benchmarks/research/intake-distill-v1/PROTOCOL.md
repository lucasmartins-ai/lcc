# Intake distill v1: can a deterministic pattern model split a long dictation into a structured brief?

Status: frozen by Amendment 1 (2026-11-26, owner approved). Only the exploratory dev pilot and the voice-memo
transcription and screening ran before the freeze; no arm has seen T. Later changes go in new amendments.

## Why

The owner dictates long, one-paragraph prompts that mix the request with context, delivery details, rules,
repetition and thinking aloud. The intake goal is a structured brief the agent reads instead:

```xml
<pedido>…</pedido><contexto>…</contexto><entrega>…</entrega><regras>…</regras><a_confirmar>…</a_confirmar>
```

The brief is built from the owner's own sentences, copied verbatim. What the brief leaves out (noise,
repetition) goes to the stash, recoverable with `recall`, so the guarantee is "recoverable", not "byte for byte".
The tags cost a few tokens; any saving comes from what moves to the stash.

What intake-objective-v1 established (`../intake-objective-v1/RESULTS.md`):

- Fixed hand-written rules (arm D) beat the baseline on synthetic dictations and did not on real ones (Part R 11
  against A0's 12 of 22). The lesson recorded there: tune on real data, not more hand rules.
- Jev over D's top five blocks (DJ) reached 14 of 22 on Part R, the best measured arm, on a small n.
- A fresh Opus agent labelling the main ask blind matched the owner on 7 of 22.
- Only Part R carries owner sentence labels (22 dictations). Part R2 and R3 judged arm outputs, not sentences.

## Questions

- **Q1.** Does P's brief keep everything the owner needs (main ask, side asks, delivery, rules) while moving
  noise and repetition to the stash, and how many tokens does that save?
- **Q1b.** Does a deterministic pattern model whose weights are learned from teacher labels (arm P) find the
  owner's main ask more often than A0 on fresh real dictations?
- **Q2.** How well do P and the tuned teacher assign the six categories, against the owner?
- **Q4 (phase 2, only by a later amendment).** Does a small encoder student (ModernBERT family), with or without
  in-domain JEPA pretraining, beat P? Does the XML brief help a downstream agent?

## Categories (one per sentence)

| Category | The sentence… |
|---|---|
| `pedido_principal` | holds the request the speaker most needs done (several sentences if it is repeated), as in Part R |
| `pedido_lateral` | asks for something else as well |
| `contexto` | gives background the task needs |
| `entrega` | says what should come out: format, file, place, audience |
| `regra` | constrains how: must, never, only, without, before |
| `ruido` | thinking aloud, filler, or a repeat of an earlier sentence with nothing new |

The page defaults every sentence to `contexto`; the labeller clicks only the others.

## Data

All splits use the pinned sentence split of intake-objective-v1 (`lcc.intake.parser`, sha `91ed1cc2…`).

### Training pool (teacher-labelled only)

The owner's own typed or dictated prompts from Claude Code, Codex and Grok transcripts, with Part R's text rule
(app reminders stripped at either end, any other markup drops the message), at least 20 words, deduplicated by
sha256, minus dev and T. The rest of the intake-objective-v1 pools (Part R2's candidates that are not in T, Part
R's skipped ones) join the training pool: they are the only long texts left, and no owner label of theirs is
used. Messages matching a
secret pattern (API keys, tokens, private keys, JWTs) are dropped before anything leaves the machine.

Census of 2026-11-25, counts only (one paragraph / several lines):

| Source | 20–99 words | 100–199 | 200–299 | 300+ |
|---|---|---|---|---|
| Claude Code | 1,085 / 66 | 156 / 33 | 4 / 0 | 2 / 0 |
| Codex | 1 / 11 | 11 / 38 | 8 / 13 | 0 / 97 |
| Grok | 0 / 0 | 0 / 0 | 0 / 1 | 0 / 0 |

Long one-paragraph dictations are nearly used up by the earlier pools. The training unit is therefore the
**sentence**, not the message. That is a named distribution shift: most training sentences come from short
prompts. Multi-line messages stay in the training pool (Amendment 9 of v1 found that they are mostly typed,
pasted or generated), flagged so the analysis can drop them.

### Dev: Part R (22 dictations)

Part R has owner gold for the main ask only. Before any teacher runs, the owner labels the other five categories
on the same 22 with T's page (the main ask shown as the owner marked it in Part R). This is the pilot of the
categories and the only dev gold for them. It is already exposed to Jev (DJ) and to an Opus labeller, so it is
dev only and never a test. Used to choose the teacher, tune the Jev question, and fix τ.

### Test: T (fresh, owner-labelled, all six categories)

Candidates, drawn once and shuffled with a fixed seed:

1. the 24 Part R3 dictations (judged as arm outputs, never sentence-labelled);
2. the 14 long one-paragraph messages of the census (Claude Code 6, Codex 8);
3. long voice recordings the owner names, transcribed locally with a speech-to-text model named and pinned in
   Amendment 1 (`lcc.intake.speech` only cleans text afterwards; it does not transcribe).

#### Voice memos (rule written 2026-11-26, before any transcript was screened)

- Source: the owner's folder of 56 Voice Memos (407 min). The owner said some are not prompts.
- Speech-to-text, pinned by `transcribe_voice.py`: whisper.cpp `whisper-cli` 1.9.5, `ggml-large-v3-turbo`
  (sha256 `1fc70f77…e2bc69`) with silero v5.1.2 VAD (`29940d98…ea2cf`), language pt, temperature 0, no
  previous-text context. Transcripts stay in the private folder; scripts print counts only.
- Unit: one memo is one T candidate, whole. No memo is split or trimmed by the agent.
- Prompt means: the owner speaking a request meant for an AI assistant (a task, a question to act on, a brief).
  Not prompts: notes to self, conversations with other people, calls, ambient recordings.
- Screening: **the owner decides** from a private local list (file name, date, duration, word count, first
  ~30 words). Jev does not screen, because Jev is a teacher candidate and would tilt T toward texts it handles;
  memos the owner marks as not prompts are never sent to any model.
- Bounds, fixed now: 100 to 1,500 words (upper bound raised to 3,000 below). Longer prompts are counted and reported, not split.
- Quality flags, fixed now: words per minute outside 60–220 or the top 4-gram above 5% of all 4-grams → the
  memo is listed as a likely transcription failure and the owner decides on it with that flag shown.
- Leakage: a memo whose transcript matches a dev, R3 or training-pool message at difflib ratio ≥0.6 is dropped
  (counts only), since a memo may also have been dictated into an app.
- Screening result (owner, 2026-11-26): 32 of 56 memos marked as prompts. Of these, 21 are within 100–1,500
  words with no quality flag and become T candidates; 9 are over 1,500 words and 2 under 100, both reported and
  left out. Unmarked rows (`[ ]` or `[]`) count as not prompts. T candidates so far: 24 + 14 + 21 = 59, before
  leakage and the owner's labelling skips.
- Change after screening, before freeze and before any arm saw T (2026-11-26): the owner reported that the long
  memos are book context dictated to an AI as prompts, so they are long by nature. The upper bound becomes 3,000
  words. The 9 long memos (1,520–2,516 words, all without a quality flag) join T as a declared stratum `longo`
  (over 1,500 words). H1–H4 run on all of T; each is also reported for `longo` and for the rest separately,
  descriptive only. On the labelling page the owner clicks only sentences that are not `contexto`, so book
  context costs no clicks. The lower bound stays: the 2 marked memos under 100 words stay out.
  T candidates: 24 + 14 + 30 = 68.

The owner labels top down on a new page (same layout as Part R): click each sentence's category, or skip the
message with a listed reason ("não foi ditado", "sensível", "não tem um pedido principal"). Target 30 to 45 kept;
**fewer than 30 kept means the primary test does not run.** No model, teacher or arm output is shown on the page.

## Teachers and the teacher gate (dev only)

- **Jev.** One request per message: the message as `state` with numbered sentences, one Choice question per
  sentence over the six categories (definitions as above). Probabilities are kept as soft labels.
- **Opus.** A fresh agent per batch with the same definitions, writing one category per sentence.

Gate on Part R, two measures:

- main-ask hit@1 (the `pedido_principal` sentence with the highest probability, or the first one for Opus)
  against the owner's Part R gold;
- macro-F1 over all six categories against the owner's dev labels, and the dev loss rate (defined under Metrics).

Up to 5 Jev question variants may be tried on dev; the best is frozen. The teacher for P is the one with the
higher macro-F1; ties go to Jev. **The study stops if neither teacher reaches A0's hit@1 or neither has a dev loss
rate at or under 10%**, and records why.

## Arms

| Arm | What it is | Role |
|---|---|---|
| A0 | intake-objective-v1 baseline, frozen | study baseline (not the shipped default; that is intake v3) |
| D | intake-objective-v1 arm D, frozen | study arm |
| P | deterministic features, per-category weights learned from the teacher's labels | candidate for the product |
| J | the frozen tuned Jev question, run directly | reference only (network call) |
| S | phase 2 encoder student | only after a later amendment |

**P's features**, all computed by code:

- fuzzy hits on fixed pt-BR and English cue lists per category (e.g. `pedido_*`: preciso, quero, faz, cria, corrige,
  verifica; `regra`: não, nunca, sempre, sem, só, antes de; `entrega`: arquivo, PR, formato, relatório, me manda;
  `contexto`: eu tô, tenho, ontem, porque, já fiz). The lists are frozen in Amendment 1. Fuzzy matching uses
  stdlib `difflib` with a fixed ratio, so speech-to-text misspellings still count;
- imperative and question markers from the pinned parser's roles;
- relative position in the message, sentence length, and overlap with any earlier sentence (repetition);
- the same features of the previous and next sentence.

Model: multinomial logistic regression in numpy, fitted on the training pool's sentences, with the teacher's
probabilities as soft targets. The class prior is fitted, the L2 strength is chosen on a 10% held-out slice of
the training pool, and nothing is fitted on T. Inference is a dot product. The weights ship as a small JSON file
with no new runtime dependency.

**Brief assembly** (code, no model): sentences grouped by predicted category in input order, verbatim. A sentence
whose top probability is under τ goes under `<a_confirmar>`. `ruido` and the repeats go to the stash. τ is fixed
on dev.

## Metrics

- **Loss rate**: share of T's messages where P sent to the stash any sentence the owner marked
  `pedido_principal`, `pedido_lateral`, `entrega` or `regra`. A brief that drops the request is worse than no
  brief, whatever it saves.
- **Saving**: brief tokens / original tokens per message (lcc's token counter), median and p90. It is always
  reported next to the loss rate.
- **Main-ask hit@1**, as in v1: the arm's chosen sentence is one the owner marked `pedido_principal`. Side
  requests never count as a hit.
- Descriptive: per-category precision, recall and macro-F1 against the owner (P, J, teacher); P's latency and RSS
  on the M1; class balance of the teacher labels by message-length band.

## Exploratory pilot on dev (2026-11-26, not pre-registered)

The owner asked for a downstream check before the freeze, run outside Claude: Part R's 22 dictations (dev only;
T untouched). Jev labelled every sentence (in requests of 10 questions, since one request per message exceeded
System One's 32K context). Code built the verbatim XML brief. Antigravity (`agy`, plan mode, empty folder)
answered each dictation twice, raw and as the brief, without executing anything. Codex (`codex exec`, read-only,
reasoning effort medium) judged each pair blind, in seeded random order, against the raw message and the owner's
gold for the main ask. Script: `pilot_downstream.py`; aggregates: `pilot_downstream_stats.json`.

| Measure (n = 22) | Raw | Brief |
|---|---|---|
| Main ask fully captured (judge 2/2) | 16 | 19 (discordant 5 to 2, exact p = 0.45) |
| Answer invents a requirement | 18 | 12 (discordant 2 to 8, exact p = 0.11) |
| Judge prefers | 12 | 10 (sign p = 0.83) |
| Tokens, brief / raw (median, max) | — | 1.044, 1.094 |

- Jev labelled 1,129 sentences: 6% `ruido` (68 dropped), 22% under τ = 0.5 (sent to `<a_confirmar>`).
- Loss: 2 of 22 messages dropped a gold main-ask sentence as `ruido`.
- Jev's main-ask hit@1: 12 of 22, the same as A0 on Part R.

Reading, with one answerer, one judge and n = 22: **the verbatim brief saves no tokens; it costs 4%.** These
dictations hold little droppable noise, and the tags add tokens. The only hints of value are in clarity, fewer
invented requirements and more main asks captured, and neither is significant. A dictation is also about 600
tokens against a median of about 88K tokens of context per prompt (lcc-judge census, 2026-11-05), so even a 15%
cut would save about 90 tokens per prompt. Token saving belongs to compaction and the stash, not to intake.

**Decision (by the agent, as the owner delegated):** the token-saving bar is dropped. The brief's purpose becomes
clarity, and the hypotheses below replace the earlier H1 and H2.

## Hypotheses and pass criteria

- **H1 (primary).** On T, an answerer given P's brief invents a requirement less often than when given the raw
  message: exact two-sided McNemar on the discordant pairs, α = 0.05. Same answerer, judge and prompts as the
  pilot, frozen in Amendment 1. The pilot's split (2 to 8) is the planning figure.
- **H2 (guard, must hold for H1 to count).** P's loss rate on T is at most 10%, with the Wilson 95% upper bound
  reported.
- **H3 (secondary).** Main ask fully captured, brief against raw, McNemar. Main-ask hit@1, P against A0, is
  reported descriptively: the best arm measured so far would not reach significance at this n.
- **H4 (descriptive).** P's macro-F1 against the owner is at least 0.8 of the teacher's. Brief/raw tokens are
  reported, with no bar.

## Leakage controls

- T is drawn once. Its labels are read only by the final run. No weight, threshold, cue list or Jev variant is
  chosen with T.
- Every training message is sha-checked against the v1 pools and T before teacher labelling.
- Frozen files are pinned by sha256 in Amendment 1. v1's frozen files are imported, never edited.
- The run refuses to overwrite its results file.

## Privacy

- Message texts live only in `~/.lcc-private/intake-distill-v1/` (0700/0600). The repository gets code, counts,
  hashes and aggregate statistics.
- Only user-typed text is sent anywhere (no tool output), after the secret filter.
- The owner authorised on 2026-11-25: Jev and Colab for labelling and training; reading other agents'
  transcripts; Opus as a labeller; voice recordings as a source. The record is private.
- Claude Code does not read T's texts; only the owner labels them.

## Budget

- Jev: at most 2,500 requests in total (dev variants plus the training pool), one HTTP attempt each, logged to a
  private resumable ledger as in v1's `part_r_dj.py`. A smoke batch of 20 measures throughput and rate limits
  first.
- Opus: dev (22 messages) plus a 200-message training sample for the teacher comparison, batched.
- Colab: none in phase 1. P fits on the M1 in seconds.

## Run order

1. Owner approves this draft and picks the primary → Amendment 1 freezes cue lists, seeds, filters, the
   speech-to-text model and file hashes.
2. `collect`: training pool and T candidates (counts printed, no text).
3. Owner labels the five other categories on Part R's 22 (dev pilot), then T (T can run in parallel with 4–6).
4. Teachers on dev → teacher gate → Jev variant frozen (Amendment 2 records the result).
5. Teacher labels on the training pool; class balance by length band printed before fitting. A category with
   under 200 training sentences is reported, and its features are not tuned further.
6. Fit P; τ on dev; freeze P (Amendment 3, weights hash).
7. Run all arms on T once → `stats.json` → RESULTS.md with gateClaim.
8. Phase 2 (S, JEPA ablation, downstream XML test) only by a new amendment, after 7.

## What needs the owner

- Approved on 2026-11-26: the 10% loss bar. The saving bar and the choice of primary were delegated to the agent;
  see the pilot section.
- Done on 2026-11-26: voice memos marked; freeze approved.
- Done on 2026-11-26: Part R's 22 labelled for the five other categories. Nothing else: T is judged blind
  (Amendment 2).

## Amendments

### Amendment 1 (2026-11-26): freeze

Approved by the owner on 2026-11-26. Everything below is fixed for phase 1; `collect` and every later script
refuse to run if a pinned file's sha256 differs.

| File | sha256 |
| :--- | :--- |
| `src/lcc/intake/parser.py` (sentence split, roles) | `91ed1cc255e4bd35bb3e9de5216f2f6461ef6af634977008ccb6339908834346` |
| `src/lcc/handoff.py` (secret filter: a message is dropped when `mask(text) != text`) | `9a5d5873eac33cff52f1409c02e14939b4cc27ee2adb0e61c6e73a91637c07b3` |
| `cues.json` (P's cue lists and fuzzy rule) | `f9e3f574057af27c193b4bfde28b7a7bf8993eafe7e4d259eb6af8f583a9f9de` |
| `pilot_downstream.py` (H1/H3 answerer and judge prompts, `agy` and `codex` settings) | `eac48532b9233a35a53f20a45b7d021234d15610cb789bfea580c315dcce9dda` |
| `transcribe_voice.py` (speech-to-text, pinned model hashes inside) | `a2aa4adafa2154d5a06769ea19c5afaba4df5c87b0603e14fc7899e970569529` |
| `voice_screen.py` (screening bounds and flags) | `c73e59cfa3e5ab4bddb325072ad433aa8cb4c4f19b50adc16aa7d09da43df5bf` |
| `ggml-large-v3-turbo.bin` | `1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69` |
| `ggml-silero-v5.1.2.bin` | `29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf` |

- **Voice memos in T:** 30, identified by the audio files' sha256; the sorted list hashes to
  `762f8ba36301296924c917338cd87727a4058b697bc5d26df2a6dfa3c034a52a` (list kept privately).
- **Seeds:** T order `20261126`; P's 10% held-out slice for L2 `20261127`; the downstream X/Y order keeps the
  pilot's `20261125`.
- **Filters:** the training pool's text rule, 20-word floor and sha dedup as in Data; the secret filter above;
  leakage by sha and by difflib ratio ≥0.6 against dev, R3 and T.
- **Cue lists:** written from general pt-BR and English usage, without reading T and without tuning on dev. They
  may be wrong in places; P's learned weights decide how much each one counts.
- **Not frozen yet, by design:** the Jev question variant and τ (Amendment 2, chosen on dev), P's weights
  (Amendment 3).

**`collect` result (2026-11-26, counts only).** T: 68 candidates (R3 24, census 14, voice 30 of which 9 in
`longo`), shuffled with seed `20261126`; no memo dropped by leakage, none caught by the secret filter. Training
pool: 1,581 messages (303 multi-line), 15,020 sentences. Left out on the way: 1,241 with markup, 133 duplicates,
130 already in an earlier pool, 84 typed messages and 57 earlier-pool leftovers by the secret filter (the Codex
review found the leftovers had skipped it; the draw was redone and T came out byte-identical). One deviation: the leakage ratio is computed on lowercased words, not
characters; character-level difflib on 15,000-character memos ran for over ten minutes without finishing, and the
written rule does not name the unit.

### Amendment 2 (2026-11-26): dev result, no owner labels on T

Written after the teacher comparison on dev and before any Jev variant, P fit or run on T.

**Dev result** (`teacher_dev.py`, `stats_teacher_dev.json`). The owner labelled the five non-context categories
on Part R's 22 (1,129 sentences): 112 `pedido_principal`, 22 `pedido_lateral`, 13 `regra`, 5 `entrega`, **0
`ruido`**; 86.5% `contexto`. The owner confirmed he read every sentence, that some parser sentences were too long
to mark one part of them, and that several dev texts are typed, not spoken. Against these labels:

| Teacher | main-ask hit@1 | dev loss | κ vs owner | macro-F1 (6) |
|---|---|---|---|---|
| Jev (pilot question) | 12 | 2 / 22 (9.1%) | 0.11 | 0.198 |
| Opus (4 fresh agents) | 13 | 6 / 22 (27.3%) | 0.13 | 0.227 |

Jev and Opus agree with each other (κ 0.44) far more than with the owner: both call 40–58% of sentences
something other than context. The owner's concept of context is wider than any teacher's.

**Changes.**

1. **No sentence goes to the stash.** The owner marked nothing as `ruido`, and the pilot's two lost main asks
   came from Jev's `ruido`. A `ruido` prediction joins `<contexto>`; the brief keeps every sentence, verbatim. Loss
   by dropping can no longer happen; what can go wrong is filing (a request filed under context).
2. **Teacher eligibility.** Only a teacher with dev loss ≤10% can be chosen (the same bar as H2); this is a
   clarification made after seeing the numbers. Jev is the teacher.
3. **Jev variants** (up to 4 more, on dev only), chosen in this order: dev loss ≤10%; then main-ask hit@1; then
   κ against the owner. One variant adds the owner's concept: most sentences are context; `entrega` and `regra`
   only when explicit. The ledger and budget rules are unchanged.
4. **The owner does not label T.** The owner asked not to be given labelling tasks. T's 68 candidates all run;
   the minimum of 30 is met. Gold on T comes from a blind judge instead: Codex, with the pilot's settings
   (`codex exec`, read-only, reasoning medium), seeing only the raw message and the two outputs, never an arm's
   name.
   - **H1** (primary, unchanged in form): answer from the brief vs answer from the raw message, "invents a
     requirement", exact McNemar, α 0.05.
   - **H2** (guard): per message, the judge reads the raw message and P's brief and says whether any request,
     delivery detail or rule of the raw message is filed only under `<contexto>`. At most 10% of T, Wilson upper
     bound reported.
   - **H3**: main ask fully captured, brief vs raw answers, judged against the raw message (no gold).
   - Main-ask hit@1 of P against A0, and P's macro-F1 against the owner, are reported on dev only.
   The judge prompt changes only by dropping the owner's gold; it is frozen in Amendment 3 with P.
5. `label_t.html` is not used.

### Amendment 3 (2026-11-26): Jev variant freeze, pool labelling, arm P freeze, and blind judge freeze

Written after dev tuning, training-pool labelling, and P fitting, and before any arm reads T.

1. **Frozen Jev variant (`jev_tune.py`, `stats_jev_variants.json`).** Four new variants (v2–v5) ran on Part R's 22
   against `v1_pilot` (185 Jev requests total including 1 synthetic smoke call, resolved `jev-1.14.0`):

   | Variant | dev loss | main-ask hit@1 | κ vs owner | macro-F1 (5) | all gold main in `<contexto>` |
   |---|---|---|---|---|---|
   | `v1_pilot` (frozen) | 2 / 22 (9.1%) | **12 / 22** | 0.110 | 0.237 | 1 / 22 |
   | `v2_owner_prior_en` | 0 / 22 (0.0%) | 10 / 22 | 0.208 | 0.322 | 5 / 22 |
   | `v3_owner_prior_pt` | 0 / 22 (0.0%) | 10 / 22 | 0.148 | 0.303 | 5 / 22 |
   | `v4_five_class_en` | 0 / 22 (0.0%) | 11 / 22 | 0.224 | 0.282 | 5 / 22 |
   | `v5_five_class_pt_strict` | 0 / 22 (0.0%) | 9 / 22 | 0.271 | 0.305 | 4 / 22 |

   Under Amendment 2's selection order (dev loss ≤10%, then main-ask hit@1, then κ), **`v1_pilot` wins and is
   frozen**. Adding the "most sentences are context" prior improved κ and macro-F1 at the cost of filing real
   requests under `<contexto>` (4–5 of 22 messages) and dropping main-ask hit@1.

2. **Training-pool labelling (`label_pool.py`, `stats_pool_labels.json`).** Smoke batch of 20 passed with 0 errors
   (4.71 req/s). All 1,581 pool messages (15,020 sentences) were labelled with `v1_pilot` (`jev-1.14.0`, 1,821
   requests; 2,006 total against the 2,500 budget, 0 errors, leakage-checked against dev/R3/T). In the full pool all
   six categories exceed 1,200 sentences; however, the 303 multi-line messages contribute 10,912 of 15,020
   sentences (72.6%), heavily skewed toward `entrega` (2,008) and `regra` (2,947).

3. **Arm P freeze (`arm_p.py`, `p_weights.json`, `stats_p_dev.json`).** As flagged in Data (multi-line messages are
   mostly typed, pasted or generated), P is fitted on the **1,278 single-line training messages (4,108 sentences)**
   using Jev's 6-class soft probabilities (`L2 = 0.01`, selected on the 10% message-level held-out slice, seed
   `20261127`). One category has under 200 single-line training sentences (`entrega`: 117) and is reported as
   required without further feature tuning.
   - Dev result on Part R's 22: P reaches **14 / 22** main-ask hit@1 (vs A0 12, D 11, Jev 12, Opus 13; full-pool
     ablation 12 / 22), macro-F1 (6) **0.202** (1.02× teacher), macro-F1 (5, no `ruido`) **0.243** (1.025× teacher),
     κ **0.0744**, median latency **26.6 ms** (max 176.5 ms), max RSS 309.6 MB.
   - Threshold **τ = 0.40** (lowest value on the dev grid `[0.20..0.50]` where messages with all gold main-ask
     sentences filed in `<contexto>` are ≤10%: 1 / 22 = 4.5%, with 40.3% of sentences routed to `<a_confirmar>` and
     median brief/raw token ratio 1.042). Under Amendment 2, `ruido` joins `<contexto>` and zero sentences are
     dropped.

4. **Frozen files for the final test run on T (`run_test.py`).** `run_test.py` verifies Amendment 1 pins plus these
   hashes before reading `t.json`, freezes the H1/H3 judge prompt (pilot prompt minus `<GOLD>`) and H2 filing-audit
   prompt, keeps `SEED_XY = 20261125`, and refuses to overwrite `stats.json`.

   | File | sha256 |
   | :--- | :--- |
   | `arm_p.py` | `a53c4869a16319347ed89728089b4be85016bcb81cb8e2802358887e4167acad` |
   | `p_weights.json` | `c145a96274b70dcd053287294febb7091e4cd9b2cdde8cc92d444f5065839540` |
   | `run_test.py` | `02caf707aefb539d7d01aab0443e62d51e923d90f819b8477648efe79effe3f1` |
   | `jev_common.py` | `6463af95c7c7194ab97c9c4668b2471803820976830373fbbc314aafbf43fd3c` |
