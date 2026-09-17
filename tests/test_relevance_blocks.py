"""Unit tests for deterministic block segmentation (ADR 0013)."""

from __future__ import annotations

from lcc.relevance import BLOCK_ID_RE, gaps_between, reconstruct, split_blocks


def test_segmentation_is_byte_exact():
    text = "First paragraph.\n\nSecond paragraph with more text.\n\n\nThird.\n"
    blocks = split_blocks(text)
    assert reconstruct(text, blocks, gaps_between(text, blocks)) == text


def test_block_ids_are_content_addressed_and_deterministic():
    text = "alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha\n\nbeta beta beta beta beta beta beta beta beta beta beta beta\n"
    blocks = split_blocks(text)
    assert [b.index for b in blocks] == [1, 2]
    assert all(BLOCK_ID_RE.match(b.id) for b in blocks)
    assert blocks[0].id != blocks[1].id
    assert [b.id for b in split_blocks(text)] == [b.id for b in blocks]


def test_fenced_code_stays_whole():
    text = (
        "Intro paragraph that is long enough to stand as its own atomic block here.\n\n"
        "```\ncode line\n\nstill code after a blank line inside the fence\n```\n\n"
        "Outro paragraph that is long enough to be its own atomic block too, yes.\n"
    )
    blocks = split_blocks(text)
    code_blocks = [b for b in blocks if "code line" in b.text]
    assert len(code_blocks) == 1
    assert "still code after a blank line" in code_blocks[0].text
    assert reconstruct(text, blocks, gaps_between(text, blocks)) == text


def test_short_blocks_are_protected():
    text = "# Heading\n\n" + ("Long paragraph sentence. " * 6) + "\n"
    blocks = split_blocks(text)
    assert blocks[0].protected
    assert blocks[0].protected_reason == "short_block"
    assert not blocks[1].protected


def test_oversize_blocks_split_at_line_boundaries():
    line = "0123456789" * 12 + "\n"
    text = line * 120
    blocks = split_blocks(text, max_block_chars=6000)
    assert len(blocks) >= 2
    assert all(len(b.text) <= 6100 for b in blocks)
    assert reconstruct(text, blocks, gaps_between(text, blocks)) == text
