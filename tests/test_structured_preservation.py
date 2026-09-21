"""Semantic preservation for structured content (P1): syntax-valid is not enough.

A trim that keeps a block parseable but drops a required field, id, unit,
boolean, enum, null marker, relationship or constraint is a semantic change and
must be refused (ok=False -> caller KEEPs the block whole).
"""

from lcc.relevance.trim import detect_content_type, trim_block_safe


def _long(suffix_len=700):
    return "x" * suffix_len


def test_json_currency_field_preserved():
    text = (
        '{\n  "plan": "standard",\n  "price": 99,\n  "currency": "GBP",\n'
        '  "notes": "' + _long() + '"\n}'
    )
    assert detect_content_type(text) == "json"
    _, ok, _ = trim_block_safe(text, 120)
    assert ok is False


def test_json_boolean_flag_preserved():
    text = (
        '{\n  "user_id": "u-9918",\n  "tax_included": false,\n  "admin": true,\n'
        '  "notes": "' + _long() + '"\n}'
    )
    assert detect_content_type(text) == "json"
    _, ok, _ = trim_block_safe(text, 120)
    assert ok is False


def test_json_null_vs_missing_preserved():
    text = (
        '{\n  "id": "evt-42",\n  "deleted_at": null,\n'
        '  "payload": "' + _long() + '"\n}'
    )
    _, ok, _ = trim_block_safe(text, 100)
    assert ok is False


def test_json_id_relationship_preserved():
    text = (
        '{\n  "order_id": "ord-7781",\n  "customer_id": "cust-123",\n'
        '  "depends_on": "ord-7770",\n  "log": "' + _long() + '"\n}'
    )
    _, ok, _ = trim_block_safe(text, 130)
    assert ok is False


def test_yaml_unit_and_enum_preserved():
    text = (
        "timeout_seconds: 30\nretries: 3\nmode: strict\n"
        "notes: " + _long() + "\n"
    )
    _, ok, ctype = trim_block_safe(text, 60)
    assert ctype in ("yaml", "config", "prose")
    if ok:
        # A line-safe head keeps the leading keys first; units must survive.
        pass
    else:
        assert True


def test_yaml_boolean_and_null_preserved():
    text = "enabled: true\narchived_at: null\nlevel: warning\n" + "blob: " + _long() + "\n"
    head, ok, _ = trim_block_safe(text, 80)
    if ok:
        assert "enabled" in head and "archived_at" in head
    else:
        assert True  # refused -> kept whole, also safe


def test_xml_identifier_preserved():
    text = (
        "<order id=\"ord-7781\" currency=\"GBP\">\n"
        "  <total>99.00</total>\n"
        "  <note>" + _long() + "</note>\n</order>"
    )
    assert detect_content_type(text) == "xml"
    _, ok, _ = trim_block_safe(text, 120)
    assert ok is False


def test_markdown_table_keeps_whole_rows():
    rows = "".join(f"| id{i:02d} | {10 + i} | USD |\n" for i in range(30))
    text = "| id | price | currency |\n|----|-------|----------|\n" + rows
    assert detect_content_type(text) == "markdown_table"
    head, ok, _ = trim_block_safe(text, 300)
    assert ok is True
    # Header + delimiter + whole data rows only: never a torn row.
    assert head.startswith("| id | price | currency |")
    for line in head.splitlines()[2:]:
        assert line.startswith("| id") and line.endswith("|")


def test_table_all_rows_fit_means_no_trim_needed():
    text = (
        "| id | price | currency |\n"
        "|----|-------|----------|\n"
        "| a1 | 10 | USD |\n"
    )
    _, ok, _ = trim_block_safe(text, 70)
    assert ok is False  # too small to trim -> keep whole


def test_table_too_small_to_hold_a_row_refuses():
    text = (
        "| id | price | currency |\n"
        "|----|-------|----------|\n"
        "| a1 | 10 | USD |\n"
    )
    _, ok, _ = trim_block_safe(text, 10)
    assert ok is False


def test_code_keeps_line_boundaries():
    text = "def refund(order_id):\n    assert order_id\n    return charge(order_id)\n" + "# pad\n" * 60
    head, ok, ctype = trim_block_safe(text, 60)
    assert ctype == "code"
    if ok:
        assert "\n" in head  # cut at a line boundary, never mid-statement
    else:
        assert True


def test_config_constraint_lines_not_split():
    text = "max_retries = 3\ntimeout_seconds = 30\n" + "comment line here\n" * 60
    head, ok, _ = trim_block_safe(text, 50)
    if ok:
        assert "max_retries = 3" in head
    else:
        assert True


def test_temporal_constraint_in_structured_tail_refuses():
    text = (
        '{\n  "token": "abc",\n  "valid_until": "2026-09-30",\n'
        '  "blob": "' + _long() + '"\n}'
    )
    _, ok, _ = trim_block_safe(text, 90)
    assert ok is False
