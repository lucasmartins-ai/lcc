from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_claims", ROOT / "scripts" / "check_claims.py")
assert _spec and _spec.loader
claims = importlib.util.module_from_spec(_spec)
sys.modules["check_claims"] = claims  # dataclasses look their module up there
_spec.loader.exec_module(claims)


def test_published_numbers_match_their_result_files() -> None:
    assert claims.check() == []


def _copy(tmp_path: Path, claim: object) -> None:
    for name in (claim.doc, claim.source):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)


def test_a_planted_mismatch_fails(tmp_path: Path) -> None:
    claim = next(c for c in claims.CLAIMS if c.doc == "docs/CACHE_ALIGNMENT.md")
    _copy(tmp_path, claim)
    doc = tmp_path / claim.doc
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("**−7.9 %**", "**−8.9 %**"), encoding="utf-8"
    )
    failures = claims.check(tmp_path, [claim], [])
    assert len(failures) == 1 and "−7.9 %" in failures[0]


def test_a_correct_row_in_a_comment_does_not_count(tmp_path: Path) -> None:
    claim = next(c for c in claims.CLAIMS if c.doc == "docs/CACHE_ALIGNMENT.md")
    _copy(tmp_path, claim)
    doc = tmp_path / claim.doc
    text = doc.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "**−7.9 %**" in line)
    doc.write_text(
        text.replace(row, f"<!-- {row} -->\n" + row.replace("−7.9", "−8.9")), encoding="utf-8"
    )
    assert len(claims.check(tmp_path, [claim], [])) == 1


def test_every_number_of_the_default_replay_row_is_checked(tmp_path: Path) -> None:
    claim = next(c for c in claims.CLAIMS if "at default" in c.template)
    _copy(tmp_path, claim)
    doc = tmp_path / claim.doc
    text = doc.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "cut 25 %, at default" in line)
    doc.write_text(text.replace(row, row.replace("| 5 |", "| 99 |")), encoding="utf-8")
    assert len(claims.check(tmp_path, [claim], [])) == 1


def test_an_edited_attested_number_fails(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    readme.write_text(text.replace("15% to 31%", "15% to 91%"), encoding="utf-8")
    failures = claims.check(tmp_path, [], claims.ATTESTED)
    assert len(failures) == 1 and "owner-attested" in failures[0]


def test_a_changed_result_fails(tmp_path: Path) -> None:
    claim = claims.CLAIMS[0]
    _copy(tmp_path, claim)
    source = tmp_path / claim.source
    data = json.loads(source.read_text(encoding="utf-8"))
    data["thresholds"]["summary@30%"]["corpus_vs_builtin_default"] -= 0.1
    source.write_text(json.dumps(data), encoding="utf-8")
    assert len(claims.check(tmp_path, [claim], [])) == 1


def test_a_missing_key_or_attested_phrase_is_reported(tmp_path: Path) -> None:
    claim = claims.CLAIMS[0]
    _copy(tmp_path, claim)
    (tmp_path / claim.source).write_text("{}", encoding="utf-8")
    shutil.copy(ROOT / "README.md", tmp_path / "README.md")
    failures = claims.check(tmp_path, [claim], [("README.md", "a phrase that is not there", "")])
    assert "cannot render" in failures[0] and "owner-attested" in failures[1]


def test_formatting_matches_the_docs() -> None:
    assert claims.delta(0.7012) == "−30 %"
    assert claims.delta(1.0473) == "+5 %"
    assert claims.delta(0.5788, "") == "−42"
    assert claims.delta(0.9211, digits=1) == "−7.9 %"
    assert claims.share(0.117) == "11.7 %"
    assert claims.share(0.0) == "0 %"
    assert claims.num(3406.9) == "3,407"
