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

#: Cases the deterministic scorer still fails. Empty since the deterministic safety net landed:
#: all twenty pass. Keep the mechanism, because the next gap should be recorded here rather
#: than discovered in production. Each entry becomes a strict xfail, so fixing one is a visible
#: act and breaking a passing case fails the suite.
MECHANICAL_GAPS: dict[str, str] = {}


def _compact(case_id: str, tmp_path: Path, extra: list[str] | None = None) -> tuple[str, str]:
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
            *(extra or []),
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


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_mechanical_keeps_evidence_for_safe_cases(case_id: str, tmp_path: Path):
    """Every case must keep its evidence under the deterministic scorer."""
    output, _ = _compact(case_id, tmp_path)
    case = CASES[case_id]
    assert _evidence_kept(case, output), f"{case_id}: critical block dropped"
    assert not _checks_hold(case, output), f"{case_id}: assertions failed"


@pytest.mark.skipif(not MECHANICAL_GAPS, reason="no recorded deterministic-scorer gaps")
@pytest.mark.xfail(strict=True, reason="documented deterministic-scorer gap")
@pytest.mark.parametrize("case_id", sorted(MECHANICAL_GAPS))
def test_mechanical_gaps_are_still_gaps(case_id: str, tmp_path: Path):
    """Recorded gaps stay recorded until a fix is deliberate and visible."""
    output, _ = _compact(case_id, tmp_path)
    case = CASES[case_id]
    assert _evidence_kept(case, output) and not _checks_hold(case, output), MECHANICAL_GAPS[case_id]


@pytest.mark.parametrize(
    "case_id", ["multilingual", "quoted_instruction", "dependency_causal"]
)
def test_cases_the_safety_net_was_built_for(case_id: str, tmp_path: Path):
    """The three measured failures the deterministic safety net exists to fix.

    Disabling the net must bring them back, otherwise the test is not actually exercising it.
    """
    output, _ = _compact(case_id, tmp_path)
    case = CASES[case_id]
    assert _evidence_kept(case, output) and not _checks_hold(case, output)

    unguarded, _ = _compact(case_id, tmp_path, ["--no-deterministic-protection"])
    assert not _evidence_kept(case, unguarded) or _checks_hold(case, unguarded), (
        f"{case_id}: passes without the safety net, so the protection is not what fixes it "
        "and this case should not be counted as a fix"
    )


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


# --- the deterministic safety net itself ------------------------------------------------


def test_quoted_speech_is_recognised():
    from lcc.relevance.compactor import _deterministic_protection

    assert _deterministic_protection('A customer wrote in the review: please cancel now.', "en")
    assert _deterministic_protection('She said: "the form never loads on mobile".', "en")
    # Ordinary prose is not quoted speech and stays judgeable.
    assert _deterministic_protection("The scanner returned 41 kB of HTML with no console errors.", "en") is None


def test_language_detection_is_conservative():
    from lcc.relevance.compactor import _detect_language

    portuguese = (
        "Relato da clinica: cerca de 41 por cento dos agendamentos sao perdidos porque o "
        "paciente nao recebe confirmacao fora do horario, e isso tambem nao melhora depois."
    )
    assert _detect_language(portuguese) == "pt"
    english = (
        "The scanner returned 41 kB of HTML with no console errors and the viewport meta tag "
        "is present in every run of the audit."
    )
    assert _detect_language(english) is None
    # Too short to judge: guessing here would be worse than not guessing.
    assert _detect_language("nao pode ser") is None


def test_foreign_language_evidence_is_protected():
    from lcc.relevance.compactor import _deterministic_protection

    block = (
        "Relato da clinica: cerca de 41 por cento dos agendamentos sao perdidos porque o "
        "paciente nao recebe confirmacao fora do horario de atendimento da clinica."
    )
    reason = _deterministic_protection(block, "en")
    assert reason is not None and reason.startswith("evidence_in_pt")


def test_dependency_closure_links_a_cause_to_its_effect():
    from lcc.relevance.blocks import split_blocks
    from lcc.relevance.compactor import _dependency_closures, _lexical_terms

    cause = (
        "The checkout flow was refactored in June, replacing the multi-step form with a "
        "single page for every visitor."
    )
    effect = (
        "Conversion dropped by 12 percent in June, immediately after the checkout flow "
        "refactor shipped to production."
    )
    noise = (
        "TOOL OUTPUT: the scanner returned HTTP 200 with 41 kB of HTML and no console "
        "errors at all."
    )
    blocks = split_blocks(f"{cause}\n\n{noise}\n\n{effect}\n")
    question_terms = _lexical_terms("Why did conversion move?")
    kept = {blocks[2].id}  # the effect is kept; the cause shares nothing with the question

    closures = _dependency_closures(blocks, kept, question_terms)
    assert blocks[0].id in closures, "the cause block was not linked to its effect"
    assert blocks[1].id not in closures, "unrelated noise was pulled in"


def test_dependency_closure_never_pulls_in_corpus_wide_boilerplate():
    from lcc.relevance.blocks import split_blocks
    from lcc.relevance.compactor import _dependency_closures, _lexical_terms

    boiler = "TOOL OUTPUT: the scanner returned HTTP 200 with 41 kB of HTML and no errors."
    repeated = "\n\n".join(boiler for _ in range(8))
    blocks = split_blocks(f"{repeated}\n")
    kept = {blocks[0].id}
    closures = _dependency_closures(blocks, kept, _lexical_terms("anything at all here"))
    assert not closures, f"boilerplate was treated as a dependency: {closures}"


def test_protection_can_be_disabled(tmp_path: Path):
    output, _ = _compact("multilingual", tmp_path, ["--no-deterministic-protection"])
    case = CASES["multilingual"]
    assert not _evidence_kept(case, output), (
        "with the net off the foreign-language block should be dropped, which is what makes "
        "the protected run meaningful"
    )


# --- the supersession rule ----------------------------------------------------------------


def _closure_for(text: str, kept_index: int, question: str = "what changed"):
    """Closures for a corpus where the objective deliberately avoids the link terms.

    A term that appears in the objective is not a link between two blocks, so a test that wants
    the supersession pass to fire must keep the objective out of the shared vocabulary.
    """
    from lcc.relevance.blocks import split_blocks
    from lcc.relevance.compactor import _dependency_closures, _lexical_terms

    blocks = split_blocks(text)
    closures = _dependency_closures(
        blocks, {blocks[kept_index].id}, _lexical_terms(question)
    )
    return blocks, closures


SUPERSESSION_SAMPLE = (
    "The measured p95 response time for the endpoint is 4.2 seconds under the standard load.\n\n"
    "TOOL OUTPUT: the scanner returned HTTP 200 with 41 kB of HTML and no console errors.\n\n"
    "REVISION: the earlier figure for the endpoint was superseded by a lower value entirely.\n\n"
    "REVISION: the annual pricing schedule was updated for every plan in the coming year.\n"
)


def test_supersession_links_a_revision_to_the_value_it_replaces():
    """A restatement that shares exactly one distinctive term still reaches the value it corrects.

    The general closure needs two shared terms, so this case only passes through the
    supersession pass; that is what makes it a test of that pass rather than of the closure.
    """
    blocks, closures = _closure_for(SUPERSESSION_SAMPLE, 0)
    revision = blocks[2]
    assert revision.id in closures, "the revision was not linked to the value it replaces"
    assert closures[revision.id].startswith("supersedes_value"), (
        f"linked by the general closure instead of the supersession pass: {closures[revision.id]}"
    )


def test_supersession_needs_a_cue_and_a_shared_term():
    """Only restatements qualify: a revision cue alone, or a shared term alone, is not enough."""
    blocks, closures = _closure_for(SUPERSESSION_SAMPLE, 0)
    # `unrelated` mentions no term the kept block uses, so the cue alone must not rescue it.
    assert blocks[3].id not in closures


def test_supersession_does_not_seed_further_links():
    """The pass reaches one level deeper without becoming transitive.

    Making the general closure transitive cost 27 points of reduction on the medium corpus, so
    the extra reach is confined to restatements. A block that shares terms only with a pulled
    revision, and carries no revision cue of its own, must stay out.
    """
    from lcc.relevance.blocks import split_blocks
    from lcc.relevance.compactor import _dependency_closures, _lexical_terms

    text = (
        "The measured p95 response time for the endpoint is 4.2 seconds under the standard load.\n\n"
        "REVISION: the earlier figure for the endpoint was superseded by a lower value entirely.\n\n"
        "The paragraph discusses the earlier figure in broad terms and adds nothing kept.\n"
    )
    blocks = split_blocks(text)
    closures = _dependency_closures(blocks, {blocks[0].id}, _lexical_terms("what changed"))
    assert blocks[1].id in closures, "the revision itself must still be pulled in"
    assert blocks[2].id not in closures, (
        "a block linking only to a pulled revision, with no cue of its own, must not follow"
    )
