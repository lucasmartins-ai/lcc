"""Unit tests for lcc.toon module."""

from lcc.toon import encode_toon


def test_encode_toon_tabular_array() -> None:
    data = [
        {"id": "doc1", "title": "Setup Guide", "score": 0.95},
        {"id": "doc2", "title": "API Reference", "score": 0.88},
    ]
    encoded = encode_toon(data, root_name="documents")
    expected = "documents[2]{id,title,score}:\ndoc1,Setup Guide,0.95\ndoc2,API Reference,0.88"
    assert encoded == expected


def test_encode_toon_nested_dict() -> None:
    data = {
        "status": "active",
        "count": 2,
        "items": ["alpha", "beta"],
    }
    encoded = encode_toon(data, root_name="config")
    assert "status: active" in encoded
    assert "count: 2" in encoded
    assert "items[2]:" in encoded
    assert "  - alpha" in encoded
    assert "  - beta" in encoded


def test_encode_toon_escaping() -> None:
    data = [
        {"name": "Hello, World", "note": "Line 1\nLine 2"},
    ]
    encoded = encode_toon(data, root_name="items")
    assert '"Hello, World"' in encoded
    assert '"Line 1\\nLine 2"' in encoded
