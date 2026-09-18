"""Adversarial semantic-safety gate for `lcc compact`.

Runs the case suite in `benchmarks/research/adversarial_cases.py` through the compactor and
asserts the documented baseline. The deterministic provider is used so this runs offline and
reproducibly in CI: the mechanical scorer never touches the network, and its failures are
stable, which makes them useful regression signals.

The baseline, measured by `benchmarks/research/run_adversarial.py`:

  * the Jev provider keeps every case's evidence (20/20);
  * the mechanical provider loses evidence in exactly three places, all of them because a
    lexical scorer cannot tell a qualifier, a quotation or another language from noise.

Each of those three is marked xfail with its reason. If a change fixes one, the strict marker
turns it into a failure that says so, and if a change breaks one of the 17 working cases, the
assertion fails.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.cli import app

runner = CliRunner()

CASES_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "adversarial_cases.py"


def _load_cases():
    spec = importlib.util.spec_from_file_location("_adversarial_cases", CASES_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the dataclasses in the module resolve their own __module__.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_cases()
CASES = {case.id: case for case in MODULE.CASES}

#: Cases the deterministic scorer is known to fail, with the reason. Measured, not assumed.
MECHANICAL_GAPS = {
    "dependency_causal": "a lexical scorer cannot link a cause block to its effect block",
    "quoted_instruction": "a quoted customer request reads as noise to overlap scoring",
    "multilingual": "evidence in another language shares no tokens with an English question",
}


def _compact(case_id: str, tmp_path: Path) -> tuple[str, str]:
    case = CASES[case_id]
    corpus = tmp_path / f"{case_id}.md"
    corpus.write_text(MODULE.build_corpus(case), encoding="utf-8")
    out = tmp_path / f"{case_id}.out.md"
    result = runner.invoke(
        app,
        [
            "compact", str(corpus),
            "--question", case.question,
            "--provider", "mechanical",
            "--output", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    return out.read_text(encoding="utf-8"), corpus.read_text(encoding="utf-8")


def _evidence_kept(case, output: str) -> bool:
    """Only the blocks the case declares as required have to survive.

    A case may carry a deliberate distractor among its critical blocks, and the injection
    case carries a block that must specifically NOT survive.
    """
    required = case.must_survive or tuple(range(len(case.critical)))
    return all(case.critical[i].strip()[:60] in output for i in required)


def _checks_hold(case, output: str) -> list[str]:
    failed = []
    for name, pattern, expectation in case.checks:
        found = bool(re.search(pattern, output, re.I | re.S))
        if (expectation == "present") != found:
            failed.append(name)
    return failed


@pytest.mark.parametrize("case_id", sorted(c for c in CASES if c not in MECHANICAL_GAPS))
def test_mechanical_keeps_evidence_for_safe_cases(case_id: str, tmp_path: Path):
    """Every case outside the known gaps must keep its evidence under the deterministic scorer."""
    output, _ = _compact(case_id, tmp_path)
    case = CASES[case_id]
    assert _evidence_kept(case, output), f"{case_id}: critical block dropped"
    assert not _checks_hold(case, output), f"{case_id}: assertions failed"


@pytest.mark.xfail(strict=True, reason="documented deterministic-scorer gap")
@pytest.mark.parametrize("case_id", sorted(MECHANICAL_GAPS))
def test_mechanical_gaps_are_still_gaps(case_id: str, tmp_path: Path):
    """The three known gaps stay documented: fixing one should be a deliberate, visible act."""
    output, _ = _compact(case_id, tmp_path)
    case = CASES[case_id]
    assert _evidence_kept(case, output) and not _checks_hold(case, output), MECHANICAL_GAPS[case_id]


def test_every_case_probes_something():
    """Suite hygiene: a case with no evidence and no assertions would pass vacuously."""
    for case in MODULE.CASES:
        assert case.critical, f"{case.id} has no critical blocks"
        assert case.checks, f"{case.id} has no assertions"
        assert case.trap, f"{case.id} has no high-overlap trap block"
        for block in case.critical:
            assert len(block) >= 80 or case.hazard == "size", (
                f"{case.id}: a critical block is below the scoring floor, so nothing can drop it "
                "and the case would test nothing"
            )


def test_trap_blocks_share_vocabulary_with_the_question():
    """The trap only works if it genuinely competes with the evidence for relevance.

    Compared on word stems so singular/plural and inflection do not hide a shared term.
    """
    for case in MODULE.CASES:
        stems = lambda text: {w.lower()[:5] for w in re.findall(r"[a-z]{4,}", text)}  # noqa: E731
        shared = stems(case.question) & stems(case.trap)
        assert shared, (
            f"{case.id}: the trap shares no vocabulary with the question, so it is not a trap. "
            f"shared={sorted(shared)} question={sorted(stems(case.question))} "
            f"trap={sorted(stems(case.trap))}"
        )
