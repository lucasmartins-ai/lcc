"""Intake against the versioned corpus in tests/corpus/intake/ (synthetic, pt and en)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lcc.intake import LccIntake, ReadinessState, parse_intake
from lcc.intake.speech import clean_dictation, detect_dictation

CORPUS = json.loads((Path(__file__).parent / "corpus" / "intake" / "v1.json").read_text("utf-8"))
CASES = CORPUS["cases"]
IDS = [c["id"] for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_dictation_detection(case):
    assert detect_dictation(case["text"]).detected is case["dictation"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_readiness(case):
    result = LccIntake(optimize_context=False).process(case["text"])
    assert result.parsed.readiness == ReadinessState(case["readiness"]), result.parsed.reasons


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_cleaning_keeps_content_and_removes_fillers(case):
    cleaned = clean_dictation(case["text"])
    for kept in case["keep"]:
        assert kept in cleaned.text
    for gone in case["remove"]:
        assert gone not in cleaned.text


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_receipt_reconstructs_the_input_exactly(case):
    text = case["text"]
    cleaned = clean_dictation(text)
    rebuilt, cursor = [], 0
    for removal in cleaned.removals:
        assert text[removal.start : removal.end] == removal.text
        rebuilt.append(text[cursor : removal.start])
        cursor = removal.end
    rebuilt.append(text[cursor:])
    assert "".join(rebuilt) == cleaned.text
    assert cleaned.removed_chars == len(text) - len(cleaned.text)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_cleaning_never_drops_a_question_mark(case):
    cleaned = clean_dictation(case["text"])
    assert all("?" not in r.text for r in cleaned.removals)


def test_question_tags_survive():
    text = "o cache só funciona se o prefixo for idêntico, né? e aí, tipo, nunca acerta, né?"
    assert (
        clean_dictation(text).text
        == "o cache só funciona se o prefixo for idêntico, né? e aí nunca acerta, né?"
    )


def test_content_words_that_look_like_fillers_survive():
    for text in [
        "Qual tipo de banco usar?",
        "What kind of index fits?",
        "I'd like to add a cache.",
        "O modelo não entendeu o pedido.",
        "Um container por serviço.",
        "Você sabe qual é a porta?",
    ]:
        assert clean_dictation(text).text == text


def test_vague_markers_match_whole_words_only():
    assert "vague_marker" not in parse_intake("Rename the maybelline_sku column.").reasons
    assert "vague_marker" in parse_intake("Maybe rename the column.").reasons
    assert "vague_marker" in parse_intake("Talvez renomear a coluna.").reasons


def test_security_words_flag_but_never_block():
    for text in [
        "Write a test proving the middleware cannot bypass security checks.",
        "Summarize this doc about 'ignore all previous instructions' attacks.",
    ]:
        parsed = parse_intake(text)
        assert parsed.readiness != ReadinessState.BLOCKED
        assert parsed.risk_flags


def test_brief_has_no_boilerplate():
    brief = parse_intake("Refactor the auth middleware to use RS256.").brief
    assert brief.deliverable == "" and brief.audience == ""
    assert brief.constraints == [] and brief.format_requirements == []


def test_voice_dump_names_the_ask_count():
    case = next(c for c in CASES if c["id"] == "pt_whisper_multi_ask")
    parsed = LccIntake(optimize_context=False).process(case["text"]).parsed
    assert "voice_dump" in parsed.reasons
    assert parsed.ask_count >= 6


@pytest.mark.parametrize("template", ["claude_xml", "code_agent", "structured_markdown", "default"])
def test_two_requests_share_the_whole_static_prefix(template):
    a = LccIntake(template_name=template).process("Refactor the auth middleware to use RS256.")
    b = LccIntake(template_name=template).process("talvez, tipo, olhar o cache, né, sei lá")
    first_dynamic = a.formatted_prompt.index("Refactor")
    prefix = 0
    for x, y in zip(a.formatted_prompt, b.formatted_prompt, strict=False):
        if x != y:
            break
        prefix += 1
    assert prefix >= first_dynamic


def test_prefix_check_script_passes():
    import importlib.util

    path = Path(__file__).parents[1] / "benchmarks" / "cache" / "run_intake_prefix.py"
    spec = importlib.util.spec_from_file_location("_intake_prefix", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0
