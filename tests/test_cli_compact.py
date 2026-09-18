"""CLI tests for `lcc compact` and intake relevance wiring (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lcc.cli import app

runner = CliRunner()

SAMPLE = (
    "Mission: reduce mobile booking friction.\n\n"
    "Funnel metric block: 38% of mobile users abandon at the date picker step today.\n\n"
    "Office noise block: the coffee machine repair needs a part and the plants need water.\n"
)


def test_compact_mechanical_writes_output_and_report(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "out.md"
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "--question",
            "reduce mobile booking friction funnel",
            "--provider",
            "mechanical",
            "--output",
            str(out),
            "--report",
            str(report),
        ],
    )
    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["schema_version"] == "relevance-compaction-1.1"
    assert data["provider_used"] == "mechanical"
    assert "first_mutation_offset" in data
    assert "prefix_sha256" in data
    assert data["reduction_ratio"] >= 0.0
    assert "worth_it" in data
    assert data["trim_head_chars"] == 300
    assert data["blocks_trimmed"] == 0


def test_compact_accepts_trim_tail_and_worker_flags(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    report = tmp_path / "r.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "--question",
            "reduce mobile booking friction funnel",
            "--provider",
            "mechanical",
            "--trim-head-chars",
            "0",
            "--trim-threshold",
            "0.2",
            "--preserve-tail",
            "1",
            "--max-workers",
            "2",
            "--min-reduction",
            "0.1",
            "--report",
            str(report),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["trim_head_chars"] == 0
    assert data["trim_threshold"] is None
    assert data["blocks_trimmed"] == 0
    assert data["min_reduction"] == 0.1


def test_compact_rejects_bad_worker_count(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(
        app, ["compact", str(src), "--question", "x", "--max-workers", "99"]
    )
    assert result.exit_code == 2


def test_compact_requires_question(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(app, ["compact", str(src), "--provider", "mechanical"])
    assert result.exit_code != 0


def test_compact_rejects_unknown_provider(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(
        app, ["compact", str(src), "--question", "x", "--provider", "wat"]
    )
    assert result.exit_code == 2


def test_intake_with_mechanical_relevance(tmp_path: Path):
    src = tmp_path / "intake.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "intake",
            str(src),
            "--enable-relevance",
            "--relevance-provider",
            "mechanical",
        ],
    )
    assert result.exit_code == 0
    assert "lcc-intake:readiness" in result.stdout


def test_intake_without_relevance_unchanged(tmp_path: Path):
    src = tmp_path / "intake.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(app, ["intake", str(src)])
    assert result.exit_code == 0


def test_require_exact_tokens_fails_when_counting_degrades(tmp_path: Path, monkeypatch):
    """A token budget must not be built on an estimate the CLI silently accepted."""
    from lcc import schemas
    from lcc.relevance import compactor as compactor_module

    real_count = compactor_module.count_tokens

    def forced_approximate(text, model=None, **kwargs):
        counted = real_count(text, model, **kwargs)
        return schemas.TokenCount(
            counted.value, schemas.TokenCountMethod.APPROXIMATE, "heuristic", None, "forced"
        )

    monkeypatch.setattr(compactor_module, "count_tokens", forced_approximate)
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "--question",
            "reduce mobile booking friction funnel",
            "--provider",
            "mechanical",
            "--require-exact-tokens",
        ],
    )
    assert result.exit_code == 3
    assert "approximate" in result.output.lower() or "estimate" in result.output.lower()


def test_marker_scores_flag_is_opt_in(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")

    plain = tmp_path / "plain.md"
    runner.invoke(
        app,
        [
            "compact", str(src), "--question", "office noise plants coffee",
            "--provider", "mechanical", "--output", str(plain),
        ],
    )
    plain_text = plain.read_text(encoding="utf-8")
    assert "lcc-compact: dropped" in plain_text, "expected a drop marker to exist"
    assert "score" not in plain_text

    scored = tmp_path / "scored.md"
    runner.invoke(
        app,
        [
            "compact", str(src), "--question", "office noise plants coffee",
            "--provider", "mechanical", "--marker-scores", "--output", str(scored),
        ],
    )
    scored_text = scored.read_text(encoding="utf-8")
    assert "lcc-compact: dropped" in scored_text
    assert "score" in scored_text


# --- per-payload append: the placement the cache measurements favour ----------------------


PAYLOAD = (
    "TOOL OUTPUT: the scanner returned HTTP 200 with 41 kB of HTML and no console errors.\n\n"
    "The clinic booking widget loses 63 percent of mobile visitors before the second step.\n\n"
    "A line about lunch and weather that carries nothing at all for the objective here.\n"
)


def _invoke_append(session: Path, payload: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "compact", str(payload),
            "--question", "what is wrong with the booking operation",
            "--provider", "mechanical",
            "--append-to", str(session),
            *extra,
        ],
    )


def test_append_leaves_the_existing_bytes_untouched(tmp_path: Path):
    """The whole point of the flag: adding to a session must not rewrite it."""
    session = tmp_path / "session.md"
    original = "STABLE SYSTEM CONTRACT\nNever invent figures.\n\n"
    session.write_text(original, encoding="utf-8")
    payload = tmp_path / "payload.md"
    payload.write_text(PAYLOAD, encoding="utf-8")

    result = _invoke_append(session, payload)
    assert result.exit_code == 0, result.output
    after = session.read_text(encoding="utf-8")
    assert after.startswith(original), "the existing bytes were modified"
    assert after != original, "nothing was appended"
    assert "appended" in result.output.lower()


def test_append_keeps_the_prefix_stable_across_repeated_appends(tmp_path: Path):
    """A session built this way stays byte-stable at the front, which is what a cache keys on."""
    session = tmp_path / "session.md"
    seed = "STABLE SYSTEM CONTRACT\n\n"
    session.write_text(seed, encoding="utf-8")
    payload = tmp_path / "payload.md"
    payload.write_text(PAYLOAD, encoding="utf-8")

    prefix = seed
    for _ in range(3):
        assert _invoke_append(session, payload).exit_code == 0
        current = session.read_text(encoding="utf-8")
        assert current.startswith(prefix), "a repeated append changed bytes already written"
        prefix = current


def test_append_creates_the_file_when_it_does_not_exist(tmp_path: Path):
    session = tmp_path / "new-session.md"
    payload = tmp_path / "payload.md"
    payload.write_text(PAYLOAD, encoding="utf-8")
    assert _invoke_append(session, payload).exit_code == 0
    assert session.exists() and session.read_text(encoding="utf-8").strip()


def test_append_still_compacts_the_payload(tmp_path: Path):
    """Appending must not become a way to skip the work."""
    session = tmp_path / "session.md"
    payload = tmp_path / "payload.md"
    payload.write_text(PAYLOAD, encoding="utf-8")
    assert _invoke_append(session, payload).exit_code == 0
    appended = session.read_text(encoding="utf-8")
    assert "63 percent" in appended, "evidence was lost"
    assert "41 kB" not in appended and "lunch" not in appended, "noise survived"


def test_append_and_output_are_mutually_exclusive(tmp_path: Path):
    session = tmp_path / "session.md"
    payload = tmp_path / "payload.md"
    payload.write_text(PAYLOAD, encoding="utf-8")
    result = _invoke_append(session, payload, "--output", str(tmp_path / "out.md"))
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output
    assert not session.exists(), "the rejected invocation still wrote something"


def test_append_respects_dry_run(tmp_path: Path):
    session = tmp_path / "session.md"
    payload = tmp_path / "payload.md"
    payload.write_text(PAYLOAD, encoding="utf-8")
    result = _invoke_append(session, payload, "--dry-run")
    assert result.exit_code == 0, result.output
    assert not session.exists(), "--dry-run must not append anything"
