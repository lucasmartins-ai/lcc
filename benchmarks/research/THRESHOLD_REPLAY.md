# Compaction threshold replay

Does compacting earlier cost less input? This replays 196 real Claude Code sessions (at least 100
requests each, 64,179 requests in all, 139 real compactions; the maintainer's own, read
2026-11-07). **Every result below is a model estimate, not a measurement.** It comes from one
corpus and one run, and no session was re-run at another threshold. Each session is replayed at a compaction threshold of 30 %, 40 % and 60 % of its
window and at Claude Code's own threshold. Script:
[`threshold_replay.py`](threshold_replay.py). Results:
`results/threshold_replay_2026-11-07_r{0.25,0.40,0.55}.json`.

## Result

**Modelled input cost**, in uncached-token units: cache reads at 0.1×, cache writes at each
session's own price (see [Model](#model)). This is a cost, not a token count.

**Corpus vs built-in default** is the main column: the modelled input cost of all 196 sessions
at that threshold, divided by what Claude Code does today (its summary, at its own threshold).
Every row covers the same sessions, so rows compare directly.

**Sessions affected** are the ones the threshold makes compact at least once. The next two
columns cover only those:

- **Compactions (median)** per affected session.
- **vs own default** compares with the same kind of compaction at Claude Code's threshold. It is
  a median, with the middle half in brackets.

**Over after a compaction** is a share of all 196 sessions, like the first column: the sessions
in which at least one compaction left the context at or over the threshold, so the next request
compacts again.

| Compaction, threshold | Corpus vs built-in default | Sessions affected | Compactions (median) | vs own default | Over after a compaction |
| :--- | ---: | ---: | ---: | :--- | ---: |
| built-in summary at 30 % | −13 % | 84 % | 2 | −25 % (−38 to −8) | 12.2 % |
| built-in summary at 40 % | **−29 %** | 59 % | 2 | −25 % (−38 to −14) | 1.5 % |
| built-in summary at 60 % | −19 % | 38 % | 3 | −21 % (−28 to −17) | 0 % |
| lcc verbatim, cut 25 %, at 30 % | −19 % | 84 % | 5 | −7 % (−36 to +3) | 15.3 % |
| lcc verbatim, cut 25 %, at 40 % | −9 % | 59 % | 7 | −20 % (−32 to +2) | 5.1 % |
| lcc verbatim, cut 25 %, at 60 % | +6 % | 38 % | 8.5 | −14 % (−20 to −7) | 1 % |
| lcc verbatim, cut 25 %, at default | +25 % | 27 % | 5 | 0 | 0 % |

The lcc rows are estimates. lcc's pass is not run on these sessions. Instead, each verbatim
compaction is assumed to remove a fixed cut of the context above `F`.

- **25 %** is the plugin's `minReductionRatio`: a pass that removes less of the transcript's
  characters falls back to the built-in summary. For scale, lcc's measured median cut is 21.8 %
  of tokens on 299 long sessions, with the middle half from 15 % to 31 % (the
  [README](../../README.md), owner-attested). Tokens and characters are different measures, so
  that median does not say which sessions would fall back.
- **40 % and 55 %** are optimistic sensitivity cases, not measurements.

Corpus vs built-in default, for each cut:

| lcc cut | at 30 % | at 40 % | at 60 % | at default |
| :--- | ---: | ---: | ---: | ---: |
| 25 % | −19 % | −9 % | +6 % | +25 % |
| 40 % | −29 % | −19 % | −3 % | +17 % |
| 55 % | −35 % | −25 % | −8 % | +12 % |

What this supports:

- **For the built-in summary, 40 % is estimated to be the cheapest of the three.** It cuts the
  corpus' modelled input cost by 29 %. At 30 %, the context after a summary is still over the threshold
  in 12 % of all sessions, so they compact again and again. Each extra summary also costs output
  tokens, which are not counted here.
- **For lcc's verbatim pass, earlier is cheaper (estimated):** 30 % < 40 % < 60 %. Its context
  after a pass shrinks with the context before it. But at 30 %, one pass leaves the context
  over the threshold in 9–15 % of all sessions.
- **At 40 % and above, verbatim compaction costs more input than a summary at the same
  threshold.** It keeps more of the context. At 30 % it can cost less: with a 25 % cut, −19 %
  against the summary's −13 %. What verbatim compaction buys is the exact text the agent keeps.
  This replay does not score that; the answer-preservation and agent evals do.
- **40 % is a threshold where both kinds save** and repeated compactions stay uncommon: 1.5 %
  of all sessions with the summary, and 1.5–5.1 % with the verbatim pass. That is why the
  plugin's docs suggest it.

## Model

Billed input is exact. It comes from the provider's usage records, one per request, priced
by their own split of 5-minute (1.25×) and 1-hour (2×) cache writes. The `<synthetic>`
zero-usage records are skipped. The replay is a model. At Claude Code's threshold it comes to a
median 0.89 of the real bill, with the middle half from 0.77 to 0.99.

- **Growth:** each request adds its size minus the previous request's. The request right after
  a real compaction adds nothing, and negative steps count as zero.
- **Window:** for a session with an automatic compaction, the median `preTokens` of those
  compactions plus 33k, since Claude Code compacts about 33k under the window. A manual
  `/compact` says nothing about the window. Otherwise the window is 200k when the session fits
  under 167k, and 1M when it does not.
- **Threshold:** each request is checked with its new content included. When it is over the
  threshold, the context is compacted and the request is sent compacted.
- **Fixed overhead `F`:** the first request's size.
- **After a built-in summary:** `F + E`. `E` is the corpus median of the first request after a
  real compaction minus `F`, which is 20,350 tokens: the summary plus what Claude Code
  re-attaches.
- **After lcc's verbatim pass:** `F + (1 − cut)(s − F)`.
- **Request cost:**
  - A request costs `0.1 × prefix + W × new`. `W` is the session's own cache-write price.
    These sessions wrote to the 1-hour cache, so `W` has a median of 2.0.
  - After a compaction, it costs `0.1 × F + W × (the rest)`.
  - The built-in summary also sends the whole context once to write itself.
  - lcc's pass runs locally and sends nothing.

**Not modelled:**

- Output tokens. Each summary is written at the output price, which counts against compacting
  often with the built-in summary.
- How compaction changes what the agent does next.
- Sessions on the 5-minute cache, and sessions from other agent tools.

So the numbers rank thresholds. They are not a bill.

```bash
python benchmarks/research/threshold_replay.py --json out.json                  # cut 25 %
python benchmarks/research/threshold_replay.py --reduction 0.40 --json out.json
```
