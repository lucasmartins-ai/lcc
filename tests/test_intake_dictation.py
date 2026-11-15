"""Dictation intake v2: disfluency rules, aside cuts, the Jev role judgment, the extractive brief.

Protocol and benchmark: benchmarks/research/intake-dictation-v1/.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from lcc.intake import LccIntake, parse_intake
from lcc.intake.speech import clean_dictation, detect_dictation, rebuild_input


def _check_receipt(text: str) -> str:
    cleaned = clean_dictation(text)
    assert rebuild_input(cleaned.text, cleaned.removals) == text
    for r in cleaned.removals:
        assert text[r.start : r.end] == r.text
        assert "?" not in r.text
    return cleaned.text


# --- Layer 1: deterministic -------------------------------------------------------------------


def test_aside_sentence_is_cut_detected_and_listed():
    text = "O resultado ficou bom? Me explica a camada paga. Te amo."
    detection = detect_dictation(text)
    assert detection.detected and "aside_phrase" in detection.reasons
    cleaned = clean_dictation(text)
    assert cleaned.text == "O resultado ficou bom? Me explica a camada paga."
    assert [(r.text, r.kind) for r in cleaned.removals] == [(" Te amo.", "aside_phrase")]


@pytest.mark.parametrize(
    "aside", ["Já vou, amor!", "Amor, já vou.", "Também te amo!", "Coming, honey!", "Love you too."]
)
def test_aside_lexicon_mid_message(aside):
    text = f"Fix the login test. {aside} It fails once in ten runs."
    assert _check_receipt(text) == "Fix the login test. It fails once in ten runs."


@pytest.mark.parametrize(
    "text",
    [
        'O botão "Te amo" do app sumiu.',
        "Coming soon banner is broken.",
        "The love you message in the app is cut off.",
        "Oi, mãe, te ligo depois.",  # an aside, but outside the lexicon: Layer 2's job
        "```\nTe amo.\n```",
        "Translate the following text into English:\nTe amo.",  # content the ask introduces
        "Traduza isto para o inglês:\n\nLove you too.",
    ],
)
def test_aside_lookalikes_and_code_are_kept(text):
    assert _check_receipt(text) == text
    assert "aside_phrase" not in detect_dictation(text).reasons


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Rode a migração na sexta, não, quer dizer, na segunda de manhã.",
            "Rode a migração na segunda de manhã.",
        ),
        ("A página demora dez, não, quer dizer, oito segundos.", "A página demora oito segundos."),
        ("O arquivo é o src/a.py, ou melhor, o src/b.py.", "O arquivo é o src/b.py."),
        ("Run it on Friday, no, I mean, on Monday.", "Run it on Monday."),
        ("It fails once in twenty, no wait, ten runs.", "It fails once in ten runs."),
        ("Roda o teste, não, roda o build.", "roda o build."),
    ],
)
def test_self_correction_keeps_only_the_repair(text, expected):
    assert _check_receipt(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Roda o teste, não o deploy.",  # contrast, no editing term
        "Usa Redis, não, Memcached.",  # weak term, nothing parallel: ambiguous, kept
        "Azul, ou melhor, verde.",  # strong term, but the only candidate opens the sentence
        "Isso, quer dizer, o cache inteiro está lento.",
    ],
)
def test_ambiguous_corrections_cut_nothing(text):
    assert _check_receipt(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Preciso, preciso que você corrija o teste.", "preciso que você corrija o teste."),
        ("Fix the fix the flaky test.", "fix the flaky test."),
        ("Eu queria eu queria um resumo.", "eu queria um resumo."),
        ("Can you, can you check it?", "can you check it?"),
        ("Pre- Preciso que você rode.", "Preciso que você rode."),
        ("Ple- please run the suite.", "please run the suite."),
    ],
)
def test_repetition_and_false_start_cut_the_first_copy(text, expected):
    assert _check_receipt(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "I know that that is wrong.",
        "Ficou muito, muito rápido.",
        "Run pre- and post-processing.",
        "Use the the `foo foo` helper.",  # one word, no comma: typo territory, left alone
        "Vamos passo a passo, dia a dia.",
        'Set the label to "go, go".',  # quoted text is literal
        "Name the song “to be to be” in the list.",
        'Use "`print("go, go")`" as the example.',  # code inside quotes stays whole
    ],
)
def test_repetition_lookalikes_are_kept(text):
    assert _check_receipt(text) == text
    assert "disfluency" not in detect_dictation(text).reasons


def test_disfluency_counts_as_dictation():
    assert "disfluency" in detect_dictation("Fix the fix the login test.").reasons
    assert not detect_dictation("Fix the login test.").detected


def test_receipt_rebuilds_mixed_input_byte_for_byte():
    text = (
        "Cara, pre- preciso que você, né, rode a migração na sexta, não, quer dizer, na segunda.\n"
        "Já vou, amor!\nDepois me mande o log, tipo, completo. Te amo."
    )
    cleaned = _check_receipt(text)
    assert "Te amo" not in cleaned and "Já vou" not in cleaned and "sexta" not in cleaned
    assert "na segunda" in cleaned and "me mande o log" in cleaned


# --- Layer 3: extractive brief ----------------------------------------------------------------


def test_brief_lists_asks_verbatim_and_drops_the_aside():
    text = "A pergunta é simples. O resultado ficou bom? Me explica a camada paga. Te amo."
    result = LccIntake(optimize_context=False).process(text)
    brief = result.parsed.brief
    assert brief.asks == ["O resultado ficou bom?", "Me explica a camada paga."]
    assert brief.objective == "O resultado ficou bom?"
    assert brief.context == "A pergunta é simples."
    assert result.parsed.lang == "pt"
    assert all("Te amo" not in item.text for item in result.extract)
    for item in result.extract:
        assert "".join(text[s:e] for s, e in item.spans) == item.text
    assert [r.text for r in result.speech_cleaning.removals] == [" Te amo."]


def test_brief_spans_skip_cut_text_inside_a_sentence():
    # The repetition makes this dictation; fillers are only cut from detected dictation.
    text = "Preciso, preciso que você, né, rode a migração. Não mexa no schema."
    result = LccIntake(optimize_context=False).process(text)
    ask = next(i for i in result.extract if i.role == "ask")
    assert ask.text == "preciso que você rode a migração."
    assert len(ask.spans) == 2
    assert "".join(text[s:e] for s, e in ask.spans) == ask.text
    assert result.parsed.brief.constraints == ["Não mexa no schema."]


@pytest.mark.parametrize(
    ("text", "role"),
    [
        ("Depois me mande o log completo.", "ask"),
        ("Then tell me which images we can compress.", "ask"),
        ("Não mexa no schema das tabelas.", "constraint"),
        ("Do not change the session timeout.", "constraint"),
        ("Não consigo rodar os testes, pode olhar?", "ask"),
        ("O deploy de ontem derrubou o worker.", "context"),
        ("Create the login endpoint; it must be authenticated.", "ask"),
        ("Crie o endpoint de login; ele tem que ser autenticado.", "ask"),
        ("The output must be JSON.", "constraint"),
        ("Build must be reproducible on every supported platform.", "constraint"),  # a subject
        ("A resposta tem que ser em JSON.", "constraint"),
    ],
)
def test_deterministic_roles(text, role):
    assert [i.role for i in parse_intake(text).extract] == [role]


def test_an_ask_with_a_rule_inside_still_counts_as_an_ask():
    text = (
        "Create the login endpoint; it must be authenticated. "
        "Add a logout route; it should be idempotent. "
        "Write the migration; it has to be reversible."
    )
    parsed = parse_intake(text)
    assert len(parsed.brief.asks) == 3
    assert parsed.ask_count == 3


def test_readiness_questions_follow_the_input_language():
    pt = parse_intake("Renomeia a coluna, sei lá, alguma coisa assim.")
    en = parse_intake("Rename the column or something, not sure.")
    assert pt.lang == "pt" and en.lang == "en"
    assert pt.questions and all("?" in q for q in pt.questions)
    assert not set(pt.questions) & set(en.questions)
    assert any("entrega" in q for q in pt.questions)


def test_dictated_hedge_is_not_ambiguity():
    dictated = "então, tipo, talvez você possa, né, olhar o cache do prompt, sabe, que tá lento"
    assert detect_dictation(dictated).detected
    assert "vague_marker" not in LccIntake(optimize_context=False).process(dictated).parsed.reasons
    assert "vague_marker" in parse_intake("Talvez renomear a coluna.").reasons  # typed: still vague
    sei_la = dictated + ", sei lá"
    assert "vague_marker" in LccIntake(optimize_context=False).process(sei_la).parsed.reasons


# --- Layer 2: Jev role judgment ---------------------------------------------------------------


class FakeJev:
    """Answers each sentence question from a fixed table keyed by the sentence text."""

    def __init__(self, table: dict[str, dict[str, Any] | None]) -> None:
        self.table = table
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.last_resolved_model = "jev-latest"  # the alias, until a call resolves it

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((state, questions))
        self.last_resolved_model = "jev-test"
        answers = {}
        for qid, i in zip(questions, range(len(questions)), strict=True):
            answer = self.table.get(state["sentences"][i])
            if answer is not None:
                answers[qid] = answer
        return {"answers": answers}


def _choice(role: str, p_aside: float) -> dict[str, Any]:
    rest = (1 - p_aside) if role != "aside" else 0.0
    probs = {"ask": 0.0, "context": 0.0, "constraint": 0.0, "aside": p_aside, "thinking_aloud": 0.0}
    if role != "aside":
        probs[role] = rest
    return {"type": "choice", "choice": role, "confidence": 0.9, "probabilities": probs}


TEXT = "Fix the login test. Bella, drop it! Max, sit. Do not touch the API. It broke today."


def test_jev_cuts_only_confident_asides_and_keeps_the_rest():
    fake = FakeJev(
        {
            "Fix the login test.": _choice("ask", 0.0),
            "Bella, drop it!": _choice("aside", 0.97),
            "Max, sit.": _choice("aside", 0.85),  # under the threshold: kept
            "Do not touch the API.": _choice("constraint", 0.01),
            "It broke today.": _choice("context", 0.02),
        }
    )
    result = LccIntake(optimize_context=False, judge_roles=True, roles_client=fake).process(TEXT)
    assert len(fake.calls) == 1
    state, questions = fake.calls[0]
    assert state["sentences"][1] == "Bella, drop it!"
    assert all(q["type"] == "choice" and "aside" in q["criteria"] for q in questions.values())
    cleaned = result.speech_cleaning
    assert [(r.text, r.kind) for r in cleaned.removals] == [(" Bella, drop it!", "aside_jev")]
    assert rebuild_input(cleaned.text, cleaned.removals) == TEXT
    assert result.roles.provider == "jev" and not result.roles.degraded
    assert result.roles.model == "jev-test"  # the resolved model, not the alias
    assert result.parsed.brief.asks == ["Fix the login test."]
    assert result.parsed.brief.constraints == ["Do not touch the API."]


@pytest.mark.parametrize(
    "answer",
    [
        None,
        {"type": "choice", "choice": "aside"},  # no probabilities: not enough to cut
        {"type": "choice", "choice": "aside", "probabilities": {"aside": 1.7}},
        {"type": "choice", "choice": "aside", "probabilities": {"aside": True}},
        {"probabilities": {"aside": 0.99}},  # no choice
        {"type": "choice", "choice": [], "probabilities": {"aside": 0.99}},
        {"type": "choice", "choice": "shouting", "probabilities": {"aside": 0.99}},
        "not an object",
    ],
)
def test_jev_bad_answers_cut_nothing(answer):
    table = {s: _choice("context", 0.0) for s in ("Fix the login test.", "Max, sit.")}
    table |= {"Do not touch the API.": _choice("constraint", 0.0)}
    table |= {"It broke today.": _choice("context", 0.0), "Bella, drop it!": answer}
    fake = FakeJev(table)
    result = LccIntake(optimize_context=False, judge_roles=True, roles_client=fake).process(TEXT)
    assert result.speech_cleaning is None or not result.speech_cleaning.removals
    assert result.roles.degraded and result.roles.warnings


def test_jev_never_cuts_a_line_inside_a_code_block():
    text = "Fix the login test.\n```\nMax, sit.\n```"
    fake = FakeJev({"Max, sit.": _choice("aside", 0.99)})
    result = LccIntake(optimize_context=False, judge_roles=True, roles_client=fake).process(text)
    assert result.speech_cleaning is None or not result.speech_cleaning.removals


def test_jev_failure_in_a_later_batch_drops_earlier_cuts():
    from lcc.intake.roles import BATCH

    class FailsSecond(FakeJev):
        def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
            if self.calls:
                self.calls.append((state, questions))
                raise TimeoutError("second batch")
            return super().evaluate(state, questions)

    text = "Bella, drop it! " + " ".join(f"Step {k} is done." for k in range(BATCH))
    fake = FailsSecond({"Bella, drop it!": _choice("aside", 0.99)})
    result = LccIntake(optimize_context=False, judge_roles=True, roles_client=fake).process(text)
    assert len(fake.calls) == 2
    assert result.roles.degraded and not result.roles.asides
    assert result.speech_cleaning is None or not result.speech_cleaning.removals


def test_cli_shows_a_degraded_judgment_without_a_report(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from lcc.cli import app

    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    src = tmp_path / "talk.txt"
    src.write_text(TEXT, encoding="utf-8")
    result = CliRunner().invoke(app, ["intake", str(src), "--judge-roles"])
    assert result.exit_code == 0
    assert "Jev unavailable" in result.output


def test_jev_failure_keeps_everything():
    from lcc.relevance.jev import JevRequestError

    class Down:
        last_resolved_model = "jev-test"

        def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
            raise JevRequestError("503")

    result = LccIntake(optimize_context=False, judge_roles=True, roles_client=Down()).process(TEXT)
    assert result.speech_cleaning is None or not result.speech_cleaning.removals
    assert result.roles.degraded and result.roles.warnings


def test_jev_unavailable_offline_keeps_everything(monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    result = LccIntake(optimize_context=False, judge_roles=True).process(TEXT)
    assert result.roles.provider == "none" and result.roles.degraded
    assert result.speech_cleaning is None or not result.speech_cleaning.removals


def test_default_intake_never_builds_a_judge(monkeypatch):
    import lcc.intake.roles as roles

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("default intake must stay offline")

    monkeypatch.setattr(roles, "judge_roles", boom)
    LccIntake(optimize_context=False).process(TEXT)


# --- one cue scan serves the roles and the ask count ---------------------------------------

_ONE_SCAN_EDGES = [
    "Do it.\nadd the test",
    "please\nfix the bug",
    "Check it and\nfix it",
    "1. fix X\n2. add Y\n3) run the suite",
    "Não faça merge sem os testes. Corrige o login. Depois adiciona um teste, e roda.",
    "Fix the login; it must be fast. Build must be reproducible. Also update the docs?",
    "Hmm… fix the bug. Never touch the cart. Then, just add a test and deploy.",
    "",
    # A per-sentence scan counted these differently: the join glues "!\n" to "make".
    "crie … cart ! \t make sure",
    "Fix deve ser 2) keep \n 1. i need não 2) then você pode    ! make sure , talvez . Run ADD … Fix",
    "then i need talvez bug never \n\n without ADD add the Do só login make sure without and ! "
    "make sure , deve ser maybe tem que add without fix touch crie then",
]


def test_one_cue_scan_matches_the_joined_count_and_the_roles():
    from pathlib import Path

    from lcc.intake.parser import count_asks, sentence_role

    root = Path(__file__).resolve().parents[1]
    bench = json.loads(
        (root / "benchmarks/research/intake-dictation-v1/cases.json").read_text("utf-8")
    )
    corpus = json.loads((root / "tests/corpus/intake/v1.json").read_text("utf-8"))
    texts = [c["text"] for c in bench["cases"] + corpus["cases"]] + _ONE_SCAN_EDGES
    assert len(texts) > len(_ONE_SCAN_EDGES)
    for text in texts:
        parsed = parse_intake(text)
        if not text.strip():
            continue
        joined = "\n".join(i.text for i in parsed.extract if i.role != "constraint")
        assert parsed.ask_count == count_asks(joined), text
        assert [i.role for i in parsed.extract] == [sentence_role(i.text) for i in parsed.extract]
