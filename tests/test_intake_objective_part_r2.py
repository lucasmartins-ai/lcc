"""Part R2 of intake-objective-v1 (Amendment 6) on synthetic text only: the pool rule, the pool,
the labelling rules, the paired test and the scoring. No real dictation is read here."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("part_r2", HERE / "part_r2.py")
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)

#: Amendment 6 pins this file; a change needs a new amendment.
PART_R2_SHA256 = "7d1ce82f2f9ecb00823671050f6c1bfa0d8c5611a6b3d24d34039d6693f4e02b"
SENTENCE = "The shop opens at nine and the van leaves at ten. "
TEXT = (
    "Please rename the photo folder from the event. The photos sit on the shared drive. "
    "Another thing, please fix the checkout that freezes when a customer pays by card. "
    "The checkout froze twice. "
)


def _long(words: int, tag: int = 0) -> str:
    return (TEXT + SENTENCE * (words // 11) + f"Ticket {tag}.").strip()


def _entry(text, **extra):
    row = {"type": "user", "turnOrigin": "human", "message": {"role": "user", "content": text}}
    return {**row, **extra}


def _old(text, version="2.1.181", **extra):
    row = {"type": "user", "entrypoint": "claude-desktop", "version": version}
    return {**row, "message": {"role": "user", "content": text}, **extra}


def test_the_file_is_the_one_amendment_6_pins():
    assert hashlib.sha256((HERE / "part_r2.py").read_bytes()).hexdigest() == PART_R2_SHA256
    assert r2._part_r_is_pinned()  # and part_r.py, which it reuses, is Amendment 4's


def test_the_page_is_part_rs_with_no_target_count():
    for old in (
        "<title>Part R: rótulos</title>",
        "Baixar labels.json",
        'a.download = "labels.json"',
        '" de " + D.goal + " | decididos: "',
    ):
        assert old in r2.part_r.PAGE and old not in r2.PAGE  # every replacement took
    assert '"Usados: " + n + " | decididos: "' in r2.PAGE


def test_the_pool_rule_takes_tagged_and_old_untagged_rows_only():
    text = _long(220)
    assert r2.candidate(_entry(text)) == (text, "ok", "tagged")
    assert r2.candidate(_old(text)) == (text, "ok", "untagged")
    assert r2.candidate(_entry(_long(150)))[1:] == ("short", "tagged")
    assert r2.candidate(_entry(text + " ```x```"))[1] == "markup"
    for row in (
        _old(text, version="2.1.187"),  # tagging exists from here: untagged means automated
        _old(text, version="garbled"),
        _old(text, entrypoint="sdk-py"),
        _old(text, turnOrigin="sdk"),
        _old(text, origin={"kind": "sdk"}),
        _old(text, isCompactSummary=True),
        _entry(text, isSidechain=True),
        _entry(text, isMeta=True),
        _entry(text, turnOrigin="host_synthetic"),
    ):
        assert r2.candidate(row) == (None, "not a typed message", None)
    assert r2.candidate(_old(text, origin={"kind": "human"}))[2] == "tagged"


def test_reminders_are_stripped_at_both_ends_however_many():
    text = _long(220)
    note = "<system-reminder>app note</system-reminder>"
    wrapped = f"{note}\n{note}\n{text}\n{note}\n{note}"
    assert r2.candidate(_entry(wrapped))[:2] == (text, "ok")
    assert r2.candidate(_entry(f"{text} {note} more words"))[1] == "markup"  # mid-text: dropped


def test_collect_writes_a_private_pool_without_part_r(tmp_path):
    transcripts = tmp_path / "projects"
    (transcripts / "p").mkdir(parents=True)
    texts = [_long(220, n) for n in range(4)] + [_long(320, 9) + " a < b </script> end"]
    rows = [_entry(t) for t in texts[:3]] + [_old(texts[3]), _old(texts[4]), _entry(texts[0])]
    rows.append(_entry(_long(220, 7) + " \ud800"))  # a lone surrogate: no stable hash
    (transcripts / "p" / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows), "utf-8")
    out = tmp_path / "private" / "r2"
    part_r_shas = {hashlib.sha256(texts[1].encode()).hexdigest()}
    counts = r2.collect(transcripts, out, part_r_shas)
    assert counts["candidates"] == 4 and counts["in Part R"] == 1 and counts["duplicate"] == 1
    assert counts["unencodable"] == 1
    pool = json.loads((out / "candidates.json").read_text("utf-8"))
    assert {c["source"] for c in pool["items"]} == {"tagged", "untagged"}
    assert sorted(c["band"] for c in pool["items"]) == ["200-299", "200-299", "200-299", "300+"]
    for c in pool["items"]:
        assert c["split"] == ("dev", "test")[int(c["sha256"], 16) % 2]
    for path in (out / "candidates.json", out / "label.html"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert stat.S_IMODE(out.parent.stat().st_mode) == 0o700
    page = (out / "label.html").read_text("utf-8")
    assert "Part R2: rótulos" in page and 'a.download = "labels_r2.json"' in page
    assert "Baixar labels_r2.json" in page and '"goal": 4' in page
    assert (
        "</script> end" not in page and "\\u003c/script> end" in page
    )  # text cannot end the block
    with pytest.raises(SystemExit, match="drawn once"):
        r2.collect(transcripts, out, part_r_shas)


def _pool(n):
    items = []
    for i in range(n):
        text = _long(220, i)
        sha = hashlib.sha256(text.encode()).hexdigest()
        sentences = [list(s) for s in r2.part_r.analyse(text).spans]
        items.append(
            {
                "id": sha[:12],
                "sha256": sha,
                "text": text,
                "sentences": sentences,
                "band": "200-299",
                "source": ("tagged", "untagged")[i % 2],
                "split": ("dev", "test")[int(sha, 16) % 2],
            }
        )
    return {"parser_sha256": r2.part_r.PARSER_SHA256, "counts": {"candidates": n}, "items": items}


def _labels(pool):
    return {
        "items": [
            {"id": c["id"], "sha256": c["sha256"], "decision": "use", "gold": [c["sentences"][2]]}
            for c in pool["items"]
        ]
    }


def test_labels_need_the_floor_and_leave_part_r_as_it_was(monkeypatch):
    pool = _pool(3)
    labels = _labels(pool)
    with pytest.raises(SystemExit, match="needs 60"):
        r2.labelled(pool, labels)
    assert r2.part_r.TARGET == (20, 30)
    with pytest.raises(SystemExit, match="another parser"):  # part_r refuses: TARGET still restored
        r2.labelled({**pool, "parser_sha256": "0" * 64}, labels)
    assert r2.part_r.TARGET == (20, 30)
    monkeypatch.setattr(r2, "MIN_KEPT", 3)
    kept, skips = r2.labelled(pool, labels)
    assert len(kept) == 3 and skips == {} and r2.part_r.TARGET == (20, 30)


def test_mcnemar_is_the_exact_binomial():
    assert r2.mcnemar(0, 0) == 1.0
    assert r2.mcnemar(4, 1) == 0.375
    assert r2.mcnemar(10, 0) == 0.001953  # 2 / 2**10, four significant figures
    assert 0 < r2.mcnemar(40, 0) < 1e-10  # a small p never reads as 0
    assert r2.mcnemar(3, 3) == 1.0


def test_summary_pairs_d_with_a0_and_splits_every_stratum():
    def row(a0, d, band, src, split):
        return {
            "A0": a0,
            "A1": False,
            "D": d,
            "D_hit3": d,
            "band": band,
            "source": src,
            "split": split,
        }

    rows = [
        row(True, False, "300+", "untagged", "dev"),
        row(False, True, "200-299", "tagged", "test"),
        row(False, True, "200-299", "tagged", "test"),
        row(True, True, "300+", "tagged", "dev"),
    ]
    s = r2.summarise(rows, {"n": 4})
    assert s["D_vs_A0"] == {"D_only": 2, "A0_only": 1, "p_exact_mcnemar": 1.0}
    assert s["by"]["band=300+"]["n"] == 2 and s["by"]["source=untagged"]["D"]["k"] == 0
    assert s["by"]["split=test"]["D"]["k"] == 2 and set(s["by"]) == {
        f"{k}={v}" for k, vs in r2.STRATA.items() for v in vs
    }
    assert r2.summarise(rows[:1], {"n": 1})["by"]["band=200-299"] == {"n": 0}
    cross = s["by_band_and_source"]
    assert len(cross) == 4 and cross["band=200-299,source=tagged"]["D"]["k"] == 2
    assert cross["band=300+,source=untagged"]["A0"]["k"] == 1
    assert cross["band=200-299,source=untagged"] == {"n": 0}


def test_run_refuses_a_second_time(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(r2, "OUT", tmp_path / "stats_r2.json")
    (tmp_path / "stats_r2.json").write_text("{}", encoding="utf-8")
    assert r2.main(["run", "--labels", str(tmp_path / "none.json")]) == 2
    assert "runs once" in capsys.readouterr().out


def test_run_refuses_when_part_r_is_not_the_pinned_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(r2, "PART_R_SHA256", "0" * 64)
    monkeypatch.setattr(r2, "OUT", tmp_path / "stats_r2.json")
    monkeypatch.setattr(r2, "PART_R_POOL", tmp_path / "absent.json")  # never read
    assert r2.main(["collect"]) == 2
    assert r2.main(["run", "--labels", str(tmp_path / "none.json")]) == 2
    assert capsys.readouterr().out.count("Amendment 4 pins") == 2
    assert not (tmp_path / "stats_r2.json").exists()


def test_run_writes_aggregates_only_to_the_repository(monkeypatch, tmp_path):
    private, out = tmp_path / "private", tmp_path / "stats_r2.json"
    private.mkdir()
    pool = _pool(4)
    (private / "candidates.json").write_text(json.dumps(pool), encoding="utf-8")
    (private / "labels_r2.json").write_text(json.dumps(_labels(pool)), encoding="utf-8")
    monkeypatch.setattr(r2, "PRIVATE", private)
    monkeypatch.setattr(r2, "OUT", out)
    monkeypatch.setattr(r2, "MIN_KEPT", 4)
    assert r2.main(["run", "--labels", str(private / "labels_r2.json")]) == 0
    stats = json.loads(out.read_text("utf-8"))
    assert stats["n"] == 4 and stats["pool"] == {"candidates": 4} and stats["skipped"] == {}
    assert stats["by"]["source=untagged"]["n"] == 2 and len(stats["by_band_and_source"]) == 4
    assert stat.S_IMODE(out.stat().st_mode) == 0o644
    assert stat.S_IMODE((private / "results_r2.json").stat().st_mode) == 0o600
    public = out.read_text("utf-8")
    assert all(c["text"] not in public and c["id"] not in public for c in pool["items"])
