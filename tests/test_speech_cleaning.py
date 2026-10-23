"""Unit tests for deterministic speech transcript, disfluency, and Whisper hallucination cleaning."""

from __future__ import annotations

from lcc.cleaning.speech import clean_speech_transcript, is_speech_transcript


def test_is_speech_transcript_detection() -> None:
    # SRT timestamps
    assert is_speech_transcript("00:00:01,000 --> 00:00:04,000\nHello world") is True

    # Audio tags
    assert is_speech_transcript("[Music]\nThis is a presentation.") is True
    assert is_speech_transcript("The speaker started talking. (applause)") is True

    # Multiple speaker turns
    assert is_speech_transcript("Speaker 1: Hello.\nSpeaker 2: Hi there.") is True

    # High filler density
    assert (
        is_speech_transcript("Tipo assim, o banco caiu, né? Então assim, precisamos reiniciar.")
        is True
    )
    assert is_speech_transcript("Basically, you know, we should fix the bug.") is True

    # Normal code or prose is not a transcript
    assert is_speech_transcript("def add(a: int, b: int) -> int:\n    return a + b") is False
    assert (
        is_speech_transcript("The quarterly revenue increased by 15% due to enterprise growth.")
        is False
    )


def test_clean_speech_english_whisper_transcript() -> None:
    raw = """WEBVTT

1
00:00:01.000 --> 00:00:04.500
[Music]
Speaker 1: Um, okay so, we need to basically refactor the authentication middleware.

2
00:00:04.600 --> 00:00:08.000
Speaker 1: You know, the token expiration is currently, uh, sort of set to 24 hours.

3
00:00:08.100 --> 00:00:11.000
Speaker 2: Right, I mean, literally it should be reduced to 1 hour, right?

4
00:00:11.100 --> 00:00:13.500
[Applause]
Thank you for watching!
Please subscribe to the channel.
Subtitles by the Amara.org community"""

    cleaned = clean_speech_transcript(raw)

    # Hallucinations and audio tags removed
    assert "[Music]" not in cleaned
    assert "[Applause]" not in cleaned
    assert "Thank you for watching" not in cleaned
    assert "Please subscribe" not in cleaned
    assert "Subtitles by" not in cleaned
    assert "-->" not in cleaned
    assert "WEBVTT" not in cleaned

    # Sequential Speaker 1 turns merged; pure fillers go, words that can carry meaning
    # ("basically", "sort of" without commas) stay.
    assert (
        "Speaker 1: we need to basically refactor the authentication middleware. "
        "the token expiration is currently sort of set to 24 hours."
    ) in cleaned

    # The tag question stays a question.
    assert "Speaker 2: literally it should be reduced to 1 hour, right?" in cleaned


def test_clean_speech_portuguese_transcript() -> None:
    raw = """Speaker 1: Então assim, tipo assim, o deploy falhou no Kubernetes, né?
Speaker 1: Peraí, quer dizer, o pod deu OOMKilled por causa de limite de memória.
Speaker 2: É... precisamos aumentar o limite para 2GB em um container."""

    cleaned = clean_speech_transcript(raw)

    # Fillers removed and speaker 1 turns combined
    assert (
        "Speaker 1: o deploy falhou no Kubernetes, né? "
        "o pod deu OOMKilled por causa de limite de memória."
    ) in cleaned

    # Portuguese 'um' (a/one) is preserved; 'É...' filler stripped
    assert "Speaker 2: precisamos aumentar o limite para 2GB em um container." in cleaned


def test_clean_speech_preserves_code_and_technical_vocabulary() -> None:
    raw = """Speaker 1: Um, let's look at the database query, you know:

```sql
SELECT * FROM users WHERE status LIKE '%active%'
```

Speaker 1: Tipo assim, precisamos criar um índice no PostgreSQL."""

    cleaned = clean_speech_transcript(raw)

    # Code block is preserved exactly
    expected_code = "```sql\nSELECT * FROM users WHERE status LIKE '%active%'\n```"
    assert expected_code in cleaned

    # Technical terms preserved
    assert "PostgreSQL" in cleaned
    assert "índice no PostgreSQL" in cleaned


def test_clean_speech_empty_and_noop() -> None:
    assert clean_speech_transcript("") == ""
    assert clean_speech_transcript("   \n\n  ") == "   \n\n  "

    clean_prose = "The system architecture is based on microservices."
    assert clean_speech_transcript(clean_prose) == clean_prose


def test_prose_with_times_is_not_a_transcript() -> None:
    """A document that merely contains clock times must not be read as a conversation.

    Regression: the speaker-label pattern used to accept any run of alphanumerics before a
    colon, so "The deployment finished at 09:00 UTC" was parsed as a speaker called "The
    deployment finished at 09". Two such lines declared the file a transcript, the speech
    cleaner then joined every paragraph into one line, and whole-line boilerplate removal
    could no longer see the signatures it exists to remove.
    """
    deployment_log = (
        "The deployment completed successfully at 09:00 UTC across all three regions.\n\n"
        "The rollback procedure requires admin approval before execution.\n\n"
        "Sent from my iPhone\n\n"
        "The deployment completed successfully at 09:00 UTC across all three regions.\n"
    )
    assert is_speech_transcript(deployment_log) is False


def test_one_repeated_label_is_not_a_conversation() -> None:
    """Prose that repeats a label-like word is still prose; a conversation alternates."""
    assert is_speech_transcript("Note: check the logs.\nNote: then retry.\n") is False
    assert is_speech_transcript("Alice: check the logs.\nBob: then retry.\n") is True


def test_real_transcript_labels_still_detected() -> None:
    assert is_speech_transcript("Speaker 1: hello.\nSpeaker 2: hi.\n") is True
    assert is_speech_transcript("Dr. Smith: we should retry.\nHost: agreed.\n") is True


def test_srt_starting_with_a_sequence_number_is_detected():
    assert is_speech_transcript("1\n00:00:01,000 --> 00:00:04,000\nOlá.\n") is True


def test_question_tags_stay_questions() -> None:
    for kept in ["O deploy falhou, né?", "O deploy falhou né?", "It failed, right?"]:
        assert kept in clean_speech_transcript(f"Speaker 1: {kept}\nSpeaker 2: Sim.")


def test_content_phrases_that_look_like_fillers_survive() -> None:
    raw = (
        "Speaker 1: What kind of index fits this query?\n"
        "Speaker 2: Do you know the schema? What I mean is the tenant column.\n"
        "Speaker 1: Turn right, then sort of by date: it literally doubles the rows.\n"
    )
    cleaned = clean_speech_transcript(raw)
    for kept in [
        "What kind of index",
        "Do you know the schema?",
        "What I mean is the tenant column.",
        "Turn right, then",
        "literally doubles",
    ]:
        assert kept in cleaned


def test_optimize_reports_speech_cleaning() -> None:
    from lcc.pipeline import OptimizationRequest, optimize

    raw = "1\n00:00:01,000 --> 00:00:02,000\n[Music]\nSpeaker 1: Um, the cache, uh, is cold.\n"
    result = optimize(OptimizationRequest(raw_text=raw, question="why?"))
    steps = [s for s in result.report.cleaning_steps if s.name == "speech_transcript_cleaning"]
    assert steps and steps[0].metrics["removed_chars"] > 0


def test_cleaning_never_changes_letter_case() -> None:
    raw = "Speaker 1: Um, okay so, we need iOS builds.\nSpeaker 2: sim, e o npm também.\n"
    cleaned = clean_speech_transcript(raw)
    assert "Speaker 1: we need iOS builds." in cleaned
    assert "Speaker 2: sim, e o npm também." in cleaned


def _apply(raw: str, spans: list[dict]) -> str:
    out, cursor = [], 0
    for span in spans:
        assert raw[span["start"] : span["end"]] == span["removed"]
        out += [raw[cursor : span["start"]], span["inserted"]]
        cursor = span["end"]
    return "".join(out) + raw[cursor:]


def test_optimize_report_lists_every_speech_edit_with_positions() -> None:
    from lcc.pipeline import OptimizationRequest, optimize
    from lcc.reporting.report import report_to_dict

    raw = (
        "1\n00:00:01,000 --> 00:00:02,000\n[Music]\nSpeaker 1: Um, the cache, you know, is cold.\n"
        "Speaker 1: o deploy falhou, né?\n"
    )
    result = optimize(OptimizationRequest(raw_text=raw, question="why?"))
    step = next(s for s in result.report.cleaning_steps if s.name == "speech_transcript_cleaning")
    from lcc.cleaning.speech import clean_speech_transcript

    assert _apply(raw, step.spans) == clean_speech_transcript(raw)
    assert any("[Music]" in s["removed"] for s in step.spans)
    assert step.metrics["spans"] == len(step.spans)
    as_json = report_to_dict(result.report)
    assert any(s["spans"] for s in as_json["cleaning_steps"])


def test_speech_edits_stay_exact_on_multi_line_merges() -> None:
    from lcc.cleaning.speech import speech_edits

    raw = "Speaker 1: a, you know, b\nSpeaker 1: c\r\nSpeaker 2: Uh, d\n" * 50
    cleaned = clean_speech_transcript(raw)
    assert _apply(raw, speech_edits(raw, cleaned)) == cleaned


def test_speech_edits_reconstruct_any_pair() -> None:
    import random

    from lcc.cleaning.speech import speech_edits

    rng = random.Random(7)
    for _ in range(200):
        a = "".join(rng.choice("ab \n,.") for _ in range(rng.randint(0, 3000)))
        b = "".join(
            ch if rng.random() > 0.05 else rng.choice("x ") for ch in a if rng.random() > 0.2
        )
        assert _apply(a, speech_edits(a, b)) == b
