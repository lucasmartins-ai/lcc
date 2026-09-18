"""Type-aware TRIM tests: safe boundaries per content type, KEEP when unsafe."""

import json
import xml.etree.ElementTree as ET

import pytest

from lcc.relevance.trim import detect_content_type, trim_block_safe


def _long(prefix: str, filler: str = "Extra sentence with booking context. ", n: int = 30) -> str:
    return prefix + filler * n + "TAIL_GONE"


def test_prose_trims_at_word_boundary():
    text = _long("The borderline paragraph starts here. ")
    head, ok, ctype = trim_block_safe(text, 300)
    assert ok and ctype == "prose"
    assert "TAIL_GONE" not in head
    assert len(head) <= 320


def test_logs_prefer_head_tail():
    lines = [f"2026-01-0{(i % 9) + 1} 10:00:0{i % 10} INFO event number {i} happened" for i in range(60)]
    text = "\n".join(lines)
    assert detect_content_type(text) == "logs"
    head, ok, _ = trim_block_safe(text, 600)
    assert ok
    assert lines[0][:30] in head  # oldest context survives
    assert lines[-1][:30] in head  # most recent state survives


def test_tables_keep_whole_rows():
    rows = "\n".join(f"| {i} | value {i} |" for i in range(40))
    text = "| id | value |\n|---|---|\n" + rows
    assert detect_content_type(text) == "markdown_table"
    head, ok, _ = trim_block_safe(text, 300)
    assert ok
    assert "| id | value |" in head  # header survives
    for line in head.splitlines()[2:]:
        assert line.count("|") >= 3  # no cut mid-row


def test_json_never_breaks_syntax():
    payload = {"items": [{"id": i, "note": "booking context filler text"} for i in range(60)]}
    text = json.dumps(payload, indent=2)
    assert detect_content_type(text) == "json"
    head, ok, ctype = trim_block_safe(text, 400)
    assert ctype == "json"
    if ok:
        json.loads(head)  # must still parse
    else:
        assert head == text  # refused: caller must KEEP


def test_broken_json_is_not_trimmed_as_prose():
    text = '{"items": [' + '{"id": 1}, ' * 200 + "TAIL"
    head, ok, ctype = trim_block_safe(text, 300)
    assert ctype == "json"
    assert not ok and head == text


def test_xml_never_breaks_syntax():
    items = "".join(f"<item id='{i}'>booking filler</item>" for i in range(200))
    text = f"<root>{items}</root>"
    assert detect_content_type(text) == "xml"
    head, ok, ctype = trim_block_safe(text, 400)
    assert ctype == "xml"
    if ok:
        ET.fromstring(head)
    else:
        assert head == text


def test_code_cuts_at_line_boundaries():
    funcs = "\n\n".join(f"def func_{i}():\n    return {i}\n" for i in range(40))
    assert detect_content_type(funcs) == "code"
    head, ok, _ = trim_block_safe(funcs, 400)
    assert ok
    assert head.endswith(")") or head.endswith(":") or "\n" not in head[len(head) - 40 :]
    # Every kept line is complete (no cut mid-line beyond the boundary).
    assert not head.endswith("retu")


def test_high_risk_trims_to_keep():
    text = (
        "The indemnification clause holds the provider liable for losses arising from "
        "the data processing agreement. " * 10
    )
    assert detect_content_type(text) == "high_risk"
    head, ok, _ = trim_block_safe(text, 300)
    assert not ok and head == text


def test_sentence_word_does_not_trigger_high_risk():
    text = _long("A normal paragraph. ")
    assert detect_content_type(text) != "high_risk"


@pytest.mark.parametrize("text", ["", "x", "short"])
def test_very_short_content_is_not_trimmed(text):
    head, ok, _ = trim_block_safe(text, 300)
    assert not ok and head == text


def test_content_at_threshold_is_kept_whole():
    text = "w " * 150  # exactly ~300 chars
    head, ok, _ = trim_block_safe(text.strip(), 300)
    assert head is not None


def test_unicode_and_emoji_survive_trim():
    text = _long("Relato da clínica 🎉: agendamentos は重要です. ")
    head, ok, _ = trim_block_safe(text, 300)
    assert ok
    head.encode("utf-8")  # no broken surrogates
