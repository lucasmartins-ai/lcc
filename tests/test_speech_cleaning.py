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
    assert is_speech_transcript("Tipo assim, o banco caiu, né? Então assim, precisamos reiniciar.") is True
    assert is_speech_transcript("Basically, you know, we should fix the bug.") is True

    # Normal code or prose is not a transcript
    assert is_speech_transcript("def add(a: int, b: int) -> int:\n    return a + b") is False
    assert is_speech_transcript("The quarterly revenue increased by 15% due to enterprise growth.") is False


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

    # Sequential Speaker 1 turns merged cleanly
    assert (
        "Speaker 1: We need to refactor the authentication middleware. "
        "The token expiration is currently set to 24 hours."
    ) in cleaned

    # Fillers removed and Speaker 2 text cleaned
    assert "Speaker 2: It should be reduced to 1 hour." in cleaned


def test_clean_speech_portuguese_transcript() -> None:
    raw = """Speaker 1: Então assim, tipo assim, o deploy falhou no Kubernetes, né?
Speaker 1: Peraí, quer dizer, o pod deu OOMKilled por causa de limite de memória.
Speaker 2: É... precisamos aumentar o limite para 2GB em um container."""

    cleaned = clean_speech_transcript(raw)

    # Fillers removed and speaker 1 turns combined
    assert (
        "Speaker 1: O deploy falhou no Kubernetes. "
        "O pod deu OOMKilled por causa de limite de memória."
    ) in cleaned

    # Portuguese 'um' (a/one) is preserved; 'É...' filler stripped
    assert "Speaker 2: Precisamos aumentar o limite para 2GB em um container." in cleaned


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
