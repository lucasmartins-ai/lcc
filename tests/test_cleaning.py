"""Tests for deterministic text cleaning (normalize + boilerplate)."""

from __future__ import annotations

from lcc.cleaning.boilerplate import remove_common_boilerplate
from lcc.cleaning.normalize import normalize_text


def test_normalize_converts_line_endings():
    result = normalize_text("a\r\nb\rc")
    assert result.text == "a\nb\nc"
    assert "normalize_line_endings" in {step.name for step in result.steps}


def test_normalize_strips_trailing_whitespace():
    result = normalize_text("hello   \nworld\t\n")
    assert result.text == "hello\nworld"


def test_normalize_collapses_blank_line_runs():
    result = normalize_text("a\n\n\n\n\nb")
    assert result.text == "a\n\nb"


def test_normalize_collapses_inner_spaces_but_keeps_indentation():
    result = normalize_text("    code    here")
    assert result.text == "    code here"


def test_normalize_preserves_unicode():
    result = normalize_text("café — naïve\n\nrésumé")
    assert "café" in result.text
    assert "résumé" in result.text


def test_normalize_empty_and_whitespace_only():
    assert normalize_text("").text == ""
    assert normalize_text("   \n  \n").text == ""


def test_normalize_preserves_python_code_block_indentation_and_spaces():
    raw = """Here is some   introductory   text.

```python
def calculate_metrics(items,    factor=2):
    total = 0
    for item in items:
        # Indented 8 spaces
        val = item.get("value",    0)
        total += val * factor
    return total
```

Follow-up   remarks   here."""

    res = normalize_text(raw)

    expected_code = """```python
def calculate_metrics(items,    factor=2):
    total = 0
    for item in items:
        # Indented 8 spaces
        val = item.get("value",    0)
        total += val * factor
    return total
```"""
    assert expected_code in res.text
    assert "Here is some introductory text." in res.text
    assert "Follow-up remarks here." in res.text


def test_normalize_preserves_markdown_table():
    raw = """Summary   table   below:

| Column A    | Column B       | Status   |
|:------------|:--------------:|---------:|
| Item 1      | Description    | OK       |
| Item 2      | Long detail    | Pending  |

Closing   paragraph   with    spaces."""

    res = normalize_text(raw)

    expected_table = """| Column A    | Column B       | Status   |
|:------------|:--------------:|---------:|
| Item 1      | Description    | OK       |
| Item 2      | Long detail    | Pending  |"""
    assert expected_table in res.text
    assert "Summary table below:" in res.text
    assert "Closing paragraph with spaces." in res.text


def test_normalize_mixed_content_prose_code_table():
    raw = """### Overview   with   spaces

First paragraph with    extra   spaces.

```json
{
    "id": 1,
    "name": "test",
    "params":    [1,    2,    3]
}
```

Middle   transition   text.

| Key       | Value     |
|-----------|-----------|
| host      | localhost |
| port      | 8080      |

~~~bash
#!/usr/bin/env bash
echo "Running    script..."
~~~

Final   conclusion."""

    res = normalize_text(raw)

    assert "### Overview with spaces" in res.text
    assert "First paragraph with extra spaces." in res.text
    assert '    "params":    [1,    2,    3]' in res.text
    assert "| Key       | Value     |" in res.text
    assert 'echo "Running    script..."' in res.text
    assert "Final conclusion." in res.text


def test_normalize_nested_and_consecutive_code_blocks():
    raw = """Consecutive code blocks:

```python
x    = 1
```
```python
y    = 2
```

Nested markdown code fence:

````markdown
```python
def nested():
    pass    # 4 spaces
```
````

End   note."""

    res = normalize_text(raw)

    assert "x    = 1" in res.text
    assert "y    = 2" in res.text
    assert "pass    # 4 spaces" in res.text
    assert "End note." in res.text


def test_boilerplate_removes_signature_and_page_marker():
    text = "Real content here.\nSent from my iPhone\nPage 3 of 10\nMore content."
    result = remove_common_boilerplate(text)
    assert "Sent from my iPhone" not in result.text
    assert "Page 3 of 10" not in result.text
    assert "Real content here." in result.text
    assert "More content." in result.text
    assert result.actions


def test_boilerplate_removes_long_rule_but_keeps_markdown_hr():
    text = "Title\n====\nBody\n---\nEnd"
    result = remove_common_boilerplate(text)
    assert "====" not in result.text  # 4-char decorative rule removed
    assert "---" in result.text  # 3-char Markdown thematic break preserved
    assert "Title" in result.text
    assert "Body" in result.text


def test_boilerplate_keeps_meaningful_lines():
    text = "The unsubscribe rate fell 12% this quarter.\nThis page covers billing."
    result = remove_common_boilerplate(text)
    assert result.text == text
    assert result.actions == []


def test_boilerplate_can_be_given_empty_pattern_set():
    text = "Sent from my iPhone"
    result = remove_common_boilerplate(text, patterns={})
    assert result.text == text
    assert result.actions == []
