# Intake dictation v1: results (2026-11-15)

Protocol: [PROTOCOL.md](PROTOCOL.md), pre-registered before any arm ran, with two amendments (below).
Cases: `cases.json`, 280 synthetic cases, sha256 `dd190cf2743db32a6a332909f5ada533904da8f39bbba813411aad43a8bb82d6`
(every results file records it). Test split: 140 cases from the 14 even-numbered requests.

| Arm | Code | Results file | Evidence label |
| :--- | :--- | :--- | :--- |
| A0 | `origin/main` `bf8bf02` | `results-A0.json` | measured (deterministic) |
| L1 | branch `feat/intake-v2-dictation`, code sha256 `0e0fdd3a…` | `results-L1.json` | measured (deterministic); `gateClaim` PASS |
| L12 | `judge_roles=True`, Jev `jev-1.14.0`, three runs, 280 of 280 calls answered in each; run 3 on code `50647e3f…` | `results-L12.json` (run 3) | measured on the test split, three runs; `gateClaim` PASS |

The L12 Jev calls carried only the synthetic text in `cases.json`, logged to the private ledger
`~/.lcc/bench/intake-dictation-v1/jev.jsonl` (feature `lcc_intake_roles`, 246,735 input and 48,446 output
tokens per run, 840 calls in all). The shared fleet ledger got none of them. Run 1 used the code before the
Codex review, run 2 and run 3 the code after its first pass ([Amendment 2](PROTOCOL.md#amendments)); the
tables show run 3. The final code (`0e0fdd3a…`, after the second pass) gives run 3's 280 records exactly when
run 3's recorded Jev answers are replayed through it.

## Test split

| metric | A0 | L1 | L12 (run 3) |
| :--- | ---: | ---: | ---: |
| cut precision | 1.0 | 1.0 | 1.0 |
| cut recall | 0.0348 | 0.5826 | 0.8841 |
| cut F1 | 0.0672 | 0.7363 | 0.9385 |
| false cuts / keep tokens | 0.0 | 0.0 | 0.0 |
| ask survival | 1.0 | 1.0 | 1.0 |
| brief ask recall | 0.575 | 0.9938 | 0.95 |
| brief ask precision | 0.6571 | 0.8833 | 0.9935 |
| aside leaks (cases) | 21 | 23 | 0 |
| questions in input language | 0.5 | 1.0 | 1.0 |
| false NEEDS_INTAKE | 0.0 | 0.0 | 0.0 |
| dictation detected (noisy) | 0.0306 | 0.6837 | 0.8265 |
| dictation detected (clean) | 0.0 | 0.0 | 0.0 |
| rebuilt byte for byte | 1.0 | 1.0 | 1.0 |
| brief spans verbatim | n/a | 1.0 | 1.0 |
| token reduction | 0.0033 | 0.0502 | 0.0752 |
| recall: aside_lexicon | 0.0 | 1.0 | 1.0 |
| recall: aside_open | 0.0 | 0.0 | 1.0 |
| recall: false_start | 0.0 | 1.0 | 1.0 |
| recall: filler | 0.1852 | 0.463 | 0.463 |
| recall: repetition | 0.0 | 1.0 | 1.0 |
| recall: self_correction | 0.0213 | 0.883 | 0.883 |

Across the three L12 runs every test metric above was the same except brief ask precision (0.9935, 1.0,
0.9935).

## Dev split

| metric | A0 | L1 | L12 (run 3) |
| :--- | ---: | ---: | ---: |
| cut precision | 1.0 | 1.0 | 1.0 |
| cut recall | 0.0 | 0.4719 | 0.7562 |
| ask survival | 1.0 | 1.0 | 1.0 |
| brief ask recall | 0.3222 | 1.0 | 1.0 |
| brief ask precision | 0.4143 | 0.9945 | 0.9836 |
| aside leaks (cases) | 20 | 22 | 2 |
| questions in input language | 0.5 | 1.0 | 1.0 |
| rebuilt byte for byte | 1.0 | 1.0 | 1.0 |
| brief spans verbatim | n/a | 1.0 | 1.0 |
| recall: aside_open | 0.0 | 0.0 | 0.8349 |
| recall: self_correction | 0.0 | 0.7123 | 0.7123 |

On dev the judge varied: `aside_open` recall 0.8349, 0.7523 and 0.8349, aside leaks 2, 3 and 2 (run 2 left
one long TV line under the threshold). Cut precision stayed 1.0 in all three.

Full tables for both splits: `python intake_dictation_v1.py report`.

## Hypotheses

| Id | Pass criterion | Result | Verdict |
| :--- | :--- | :--- | :--- |
| H1 | ask survival = 1.0 in L1 and L12, both splits | 1.0 in all four | pass |
| H2 | rebuilt and verbatim = 1.0 in L1 and L12 | 1.0 in all four | pass |
| H3 | L1 test precision >= 0.95, false cuts <= 0.01 | 1.0 and 0.0 | pass |
| H4 | L1 test recall > A0 on the four rule families | 1.0 > 0.0, 0.883 > 0.021, 1.0 > 0.0, 1.0 > 0.0 | pass |
| H5 | L12 test `aside_open` recall >= 0.8 at precision >= 0.95 | 1.0 at 1.0 in each of three runs | pass (`gateClaim` PASS) |
| H6 | L1 test brief ask recall >= 0.9 and above A0 | 0.9938 vs 0.575 | pass |
| H7 | L1 questions in input language = 1.0 | 1.0 | pass |

## What the numbers do and do not say

- **Leakage.** The injected phrases and the Layer 1 rules have one author, so the rule families
  (`aside_lexicon`, `self_correction`, `repetition`, `false_start`) show the rules work as specified and never
  cut an ask. They do not say how much of real speech the rules cover. `aside_open` (L12) is the only family
  whose phrases the rules never saw; on it the deterministic layer finds nothing, as designed.
- **Brief cue list.** The sentence-initial imperative list in `parser.py` (`mande`, `diga`, `send`, `tell`,
  `roll back`, `hide`, ...) was written after reading which base asks the A0 brief missed, test bases included.
  Brief ask recall on the test split is therefore an optimistic number for unseen phrasing.
- **Fillers** are cut only when the message is detected as dictation (unchanged contract); with two injected
  fillers and nothing else, a message is usually not detected, hence filler recall 0.46 on test.
- **Self-correction** recall below 1.0 is the spec: a weak editing term ("quer dizer,", "I mean,", "não,") with
  no parallel word cuts nothing.
- **L12 brief ask recall fell to 0.95** because Jev labelled one request's ask ("Rode a migração do banco na
  segunda de manhã.", base `pt02`) as something other than an ask in 8 of its 10 variants (the 8 misses out of
  160 test asks). The ask was not cut; it went to the brief's context or constraints instead.
- **Aside leaks in L1 (23)** are the `aside_open` sentences, which L1 keeps by design and the brief lists as
  sentences. With L12 none leak on test and 2 or 3 on dev (the TV line "And now the weather: …" got
  p(aside) < 0.9).
- **Dictation detected on clean cases stays 0.0**: the new signals do not fire on the clean requests.

## The owner's two messages (offline, L1; text stays out of the repository)

| | A0 (`bf8bf02`) | L1 |
| :--- | :--- | :--- |
| Message 1, 56 tokens | not detected; "Te amo." kept; objective = first 80 chars; READY 90 | detected (`aside_phrase`); **" Te amo." cut**, listed in the receipt as `aside_phrase`; brief lists its four real asks in order, the opening line as context; READY 90 |
| Message 2, 317 tokens | detected; one ", né," cut; objective = first 80 chars; NEEDS_INTAKE 40 on "talvez"; questions in English | detected; the same ", né," cut (no aside, correction or repetition in it); "talvez" no longer read as ambiguity, READY 90; brief lists four ask sentences, the rest as context; questions, when asked, in Portuguese |

Both rebuild byte for byte from the cleaned text plus the receipt, and every brief item equals its listed spans of
the raw input. Neither message was sent to Jev; that waits for the owner's yes.

Known limit: `brief.objective` is the first ask in input order. In message 2 that is a secondary sentence, not
the main request. Picking the main ask among several is not solved here and the benchmark does not measure it.

## Amendments

See [PROTOCOL.md](PROTOCOL.md#amendments). Amendment 1 changed one metric outside the hypotheses (false
`NEEDS_INTAKE`, test 0.0317 → 0.0); every other test metric was identical before and after it. Amendment 2
(the Codex review fixes: quoted text, colon-introduced content, Jev answer validation, asks holding a rule)
left every L1 metric identical on both splits.

## Not built: an output-side compiler

Out of scope here, noted for later. Ideas, none measured:

- Reuse the receipt contract on the way out: a terse rewrite of an agent's answer that lists every dropped span,
  so the full answer is recoverable, the same guarantee intake now gives.
- Gate it on content type: never touch code, commands, numbers, paths or quoted text; compress only prose.
- Measure it the same way: synthetic answers with known removable spans (pleasantries, restated questions,
  repeated summaries), precision on facts kept, and a byte-exact rebuild.
- One Jev `noul` per paragraph ("does the user need this to act?") with keep-everything on failure, like
  `--judge-roles`.
