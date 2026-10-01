---
name: trim-long-context
description: Cut a long document, transcript, meeting recording, support thread, or server log down to only the parts that matter for a stated goal. Use when the user pastes a lot of text and asks to shorten it, find the relevant part, cut the noise, or answer a question from a long transcript. Returns the kept text verbatim rather than a summary, so quotes stay exact.
---

Use this skill when the user has more text than fits comfortably in a conversation and
wants only the part that matters for a specific goal.

## What the user gives you

- **A goal**, in their words: "find the refund issue", "what decided the launch date",
  "why did it 500".
- **A body of text**: a transcript, document, log, or thread.

If the goal is missing or vague, ask what they are trying to find out. Do not guess the
goal — a wrong goal silently returns the wrong blocks.

## Workflow

1. Identify the goal and the text. If the text is enormous, work on the portion the user
   pointed at.
2. Call `compact` with the text and the goal. The default `mechanical` provider is fully
   offline and needs no API key; use it unless the user asks for deeper semantic judging.
3. Read the report. It names every block that was kept, trimmed, or dropped, with the
   score and reason for each.
4. Answer from the kept text, quoting it exactly. Cite where in the source each fact came
   from when the user needs to check it.

## Output

- The relevant passages, verbatim, with the dropped material accounted for.
- A one-line note on what was cut and how much, so the user knows the scope of the filter.
- The block report when the user wants to audit the decision (`explain` renders it in
  plain language).

## Do not

- Do not paraphrase or summarize the kept text. The point of this plugin is that it is
  verbatim and quotable.
- Do not invent facts that were dropped. If the answer is not in the kept blocks, say the
  source does not contain it — or re-run with a different goal.
- Do not claim a block was irrelevant without a reason from the report.

## Escalate when the mechanical pass is not enough

If the kept text still contains a lot that looks unrelated, that usually means the goal
was phrased too broadly. Offer to re-run with a narrower goal ("just the refund part")
rather than silently loosening the threshold.

`compact` never drops content it could not judge: if a call fails, the output comes back
with `degraded: true` and the text intact. Report that honestly instead of pretending the
filter was clean.