"""Opt-in Jev judgment of each dictated sentence's role (intake Layer 2).

One System One ``choice`` question per sentence: ask, context, constraint, aside (words meant
for someone or something other than the assistant) or thinking aloud. A sentence is cut only
when Jev puts ``aside`` at or above ``ASIDE_THRESHOLD``; with no client, an error or a malformed
answer nothing is cut and the judgment says ``degraded``. Never imported by the default intake
(ADR 0010: Jev stays opt-in and outside the deterministic core).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lcc.intake.speech import aside_cut_allowed, sentence_cut, sentence_spans

FEATURE = "lcc_intake_roles"
#: Fixed in benchmarks/research/intake-dictation-v1/PROTOCOL.md before the Jev arm ran.
ASIDE_THRESHOLD = 0.9
BATCH = 32
ROLES = {
    "ask": "A request or question for the assistant.",
    "context": "Background the assistant needs: facts, symptoms, history.",
    "constraint": "A rule or limit on how the assistant must do the work.",
    "aside": (
        "Words meant for someone or something other than the assistant: a person or pet in "
        "the room, a phone call, a TV or radio line the microphone caught."
    ),
    "thinking_aloud": "The speaker organising their own thoughts, addressed to no one.",
}


@dataclass
class RoleJudgment:
    provider: str  # "jev" or "none"
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)
    #: Jev's role per sentence text, for the sentences it answered.
    roles: dict[str, str] = field(default_factory=dict)
    #: Whole-sentence cuts, as spans of the judged text.
    asides: list[tuple[int, int]] = field(default_factory=list)
    model: str = ""


def _p_aside(answer: Any) -> float | None:
    probs = answer.get("probabilities") if isinstance(answer, dict) else None
    p = probs.get("aside") if isinstance(probs, dict) else None
    if isinstance(p, bool) or not isinstance(p, int | float) or not 0 <= p <= 1:
        return None
    return float(p)


def judge_roles(text: str, client: Any | None = None) -> RoleJudgment:
    """Ask Jev for each sentence's role; return the asides to cut and the roles it gave."""
    if client is None:
        from lcc.relevance.jev import JevClient, default_ledger_path

        client = JevClient.from_env(ledger_path=default_ledger_path(), feature=FEATURE)
    if client is None:
        return RoleJudgment(
            "none", degraded=True, warnings=["Jev unavailable (no key or network disabled)"]
        )
    judgment = RoleJudgment("jev")
    spans = sentence_spans(text)
    unusable = 0
    for first in range(0, len(spans), BATCH):
        batch = spans[first : first + BATCH]
        sentences = [text[s:e] for s, e in batch]
        questions = {
            f"s{k}": {
                "type": "choice",
                "instructions": (
                    f"state.sentences[{k}] is one sentence of a message someone dictated to an "
                    "AI assistant. What is that sentence?"
                ),
                "criteria": ROLES,
            }
            for k in range(len(batch))
        }
        try:
            response = client.evaluate({"sentences": sentences}, questions)
            # The model the call resolved to ("jev-latest" -> "jev-1.14.0"), known only after it.
            judgment.model = str(getattr(client, "last_resolved_model", "") or "")
            answers = response.get("answers") if isinstance(response, dict) else None
            if not isinstance(answers, dict):
                raise ValueError("answer had no 'answers' mapping")
        except Exception as exc:  # noqa: BLE001 - any failure keeps every sentence
            # A failed batch voids the cuts earlier batches made: Jev failing means nothing cut.
            judgment.asides.clear()
            judgment.degraded = True
            judgment.warnings.append(f"Jev failed, nothing cut: {type(exc).__name__}: {exc}")
            return judgment
        for k, (s, e) in enumerate(batch):
            answer = answers.get(f"s{k}")
            choice = answer.get("choice") if isinstance(answer, dict) else None
            p = _p_aside(answer)
            if not isinstance(choice, str) or choice not in ROLES or p is None:
                unusable += 1  # malformed: this sentence is kept
                continue
            judgment.roles[sentences[k]] = choice
            # Questions, code, quotes and colon-introduced content are never cut.
            if p >= ASIDE_THRESHOLD and aside_cut_allowed(text, s, e):
                judgment.asides.append(sentence_cut(text, s, e))
    if unusable:
        judgment.degraded = True
        judgment.warnings.append(f"{unusable} sentence(s) had a malformed answer, kept")
    return judgment
