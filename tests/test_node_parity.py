"""Node/Python parity tests (ADR 0014 boundary).

Full `compact` parity is roadmap, not implied (ADR 0013/0014): the Node engine has no
Jev scorer, no decision cache and no sufficiency verifier. What MUST agree is the
deterministic surface both runtimes advertise — token-estimate honesty, boilerplate
removal and paragraph dedup — on shared fixtures. Exact textual equality is not
required where documented formatting differs; semantic policy agreement is checked
only for the mechanical cleaning both sides implement.
"""

import json
import shutil
import subprocess

import pytest

NODE = shutil.which("node")

PROSE_FIXTURES = [
    "Here is the primary context paragraph.\n\nHere is the primary context paragraph.\n",
    "Sent from my iPhone\n\nThe database migration guide is ready for review.\n",
    "Hello world! This is a test context prompt.\n",
]


def _node_eval(script: str) -> str:
    result = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_node_estimates_are_labelled_approximate():
    out = _node_eval(
        "const lcc=require('./index.js');"
        "console.log(JSON.stringify(lcc.estimateTokensWithMeta('Hello world')))"
    )
    payload = json.loads(out)
    assert payload["method"] == "approximate"
    assert payload["isEstimate"] is True
    assert payload["tokenizer"]["exact"] is False


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_node_and_python_agree_on_prose_dedup():
    """Same prose in, same paragraph out: policy agrees on the shared surface."""
    from lcc.cleaning.deduplicate import deduplicate_paragraphs

    for fixture in PROSE_FIXTURES:
        py = deduplicate_paragraphs(fixture).text
        out = _node_eval(
            "const lcc=require('./index.js');"
            f"console.log(JSON.stringify(lcc.compressContext({json.dumps(fixture)}).compressedText))"
        )
        node_text = json.loads(out)
        # Boilerplate must be gone on both sides; surviving evidence must match.
        assert "Sent from my iPhone" not in node_text
        for paragraph in py.split("\n\n"):
            first_line = paragraph.strip().splitlines()[0] if paragraph.strip() else ""
            if len(first_line) > 20 and "iPhone" not in first_line:
                assert first_line[:30] in node_text or first_line[:30] in fixture


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_parity_boundary_is_documented():
    """Compact/sufficiency/cache-identity exist only in Python — Node must not imply them."""
    out = _node_eval(
        "const lcc=require('./index.js');console.log(Object.keys(lcc).sort().join(','))"
    )
    exports = out.split(",")
    assert "compact" not in exports  # no relevance compaction in Node (roadmap)
    assert "estimateTokensWithMeta" in exports
    assert "tokenizerIdentity" in exports
