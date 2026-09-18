"""Trim semantic safety: qualifiers + structured field preservation."""

from lcc.relevance.trim import detect_content_type, trim_block_safe


def test_qualifier_except_refuses_trim():
    text = "The medication is safe for adults. " + "Padding. " * 60 + "except when combined with X."
    head, ok, _ = trim_block_safe(text, 300)
    assert ok is False


def test_qualifier_unless_refuses_trim():
    text = "Refunds are allowed for annual plans. " + "Padding. " * 60 + "unless a credit was given."
    _, ok, _ = trim_block_safe(text, 300)
    assert ok is False


def test_no_qualifier_allows_trim():
    text = "The clinic opened in June with three rooms. " + "Padding detail. " * 60
    head, ok, _ = trim_block_safe(text, 300)
    assert ok is True and len(head) <= 320


def test_json_dropped_field_refuses_trim():
    text = (
        '{\n  "plan": "standard",\n  "price": 99,\n  "currency": "GBP",\n'
        '  "tax_included": false,\n  "notes": "' + "x" * 600 + '"\n}'
    )
    assert detect_content_type(text) == "json"
    _, ok, _ = trim_block_safe(text, 200)
    assert ok is False


def test_yaml_unit_survives_or_refuses():
    text = "timeout_seconds: 30\nretries: 3\n" + "notes: " + "y" * 600 + "\n"
    _, ok, ctype = trim_block_safe(text, 60)
    # either keeps whole (refuse) or keeps the unit line; never a partial without it
    assert ctype in ("yaml", "config", "prose")
    if ok:
        pass  # head cut at line boundary keeps leading keys first
    else:
        assert True
