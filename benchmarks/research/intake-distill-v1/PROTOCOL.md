# Intake distill v1: can a deterministic pattern model split a long dictation into a structured brief? (DRAFT, not frozen)

Status: draft for the owner's approval. Nothing below has run. No Jev call, no Claude labelling and no Colab
runtime happen before the owner approves this file and its hashes are recorded in Amendment 1.

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
- **Q2.** How well do P and the tuned teacher assign the five categories, against the owner?
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

The page defaults every sentence to `contexto`; the labeller clicks only the others. "Five categories" below means the five besides `contexto`'s default, i.e. all six are labelled.

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

### Test: T (fresh, owner-labelled, all five categories)

Candidates, drawn once and shuffled with a fixed seed:

1. the 24 Part R3 dictations (judged as arm outputs, never sentence-labelled);
2. the 14 long one-paragraph messages of the census (Claude Code 6, Codex 8);
3. long voice recordings the owner names, transcribed locally with a speech-to-text model named and pinned in
   Amendment 1 (`lcc.intake.speech` only cleans text afterwards; it does not transcribe).

The owner labels top down on a new page (same layout as Part R): click each sentence's category, or skip the
message with a listed reason ("não foi ditado", "sensível", "não tem um pedido principal"). Target 30 to 45 kept;
**fewer than 30 kept means the primary test does not run.** No model, teacher or arm output is shown on the page.

## Teachers and the teacher gate (dev only)

- **Jev.** One request per message: the message as `state` with numbered sentences, one Choice question per
  sentence over the five categories (definitions as above). Probabilities are kept as soft labels.
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

## Hypotheses and pass criteria (the primary is the owner's choice before the freeze)

- **H1 (proposed primary).** On T, P's loss rate is at most 10% (Wilson 95% upper bound reported) **and** its
  median saving is at least 15% of the tokens. This is what the brief is for.
- **H2.** P's main-ask hit@1 on T beats A0's: exact two-sided McNemar on the discordant pairs, α = 0.05.
  - Power line: at n = 30 to 40 this needs a lopsided split such as 8 to 1 or 10 to 2. The best measured arm
    so far (DJ, 14 against A0's 12 of 22) would not reach that, and P sits at or below its teacher. **The likely
    reading of H2 is "not shown"**, which is why it is not proposed as the primary.
- **H3.** P's macro-F1 against the owner is at least 0.8 of the teacher's on T (descriptive bar, no test).

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

- Approve or change this draft: categories, test size, the 10% loss bar and the 15% saving bar.
- Pick the primary: H1 (loss and saving, proposed) or H2 (main-ask hit@1 against A0).
- Name the folder with the voice recordings.
- Label Part R's 22 for the five other categories (dev pilot) and then T: about 30–45 dictations, clicking only
  the sentences that are not `contexto`.
