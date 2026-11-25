"""The site's in-browser intake demo (site/src/lib/intake.ts) is a port of lcc.intake.category.

site/test/intake-parity.json holds prompts and what Python returns for each; this test keeps the
expectations true for Python, and site/test/intake-parity.test.ts checks the TypeScript port
against the same file. After a model change: ``python tests/test_site_intake_fixture.py --write``.
"""

import json
import sys
from pathlib import Path

from lcc.intake import category as cat

FIXTURE = Path(__file__).resolve().parents[1] / "site" / "test" / "intake-parity.json"


def expected(prompt: str) -> dict:
    model = cat._load()
    assert model is not None
    p = model.proba(prompt)
    i = max(range(len(p)), key=p.__getitem__)
    hit = cat.classify(prompt)
    return {
        "top": model.labels[i],
        "probability": p[i],
        "category": hit.id if hit else None,
        "probabilities": p,
    }


def test_fixture_matches_python():
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(items) >= 30
    for item in items:
        got = expected(item["prompt"]) if (item["prompt"] or "").strip() else None
        want = item["expected"]
        assert (got is None) == (want is None), item["prompt"][:60]
        if got is not None:
            assert got["top"] == want["top"] and got["category"] == want["category"]
            assert abs(got["probability"] - want["probability"]) < 1e-12


if __name__ == "__main__" and sys.argv[1:] == ["--write"]:
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for item in items:
        item["expected"] = expected(item["prompt"]) if (item["prompt"] or "").strip() else None
    FIXTURE.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
