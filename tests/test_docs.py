from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _words(path: str) -> str:
    return " ".join(_read(path).split())


def test_phase_1_7_model_assistance_boundary_is_documented() -> None:
    adr = _read("docs/adr/0010-deterministic-first-preparation-model-assistance.md")
    adr_words = " ".join(adr.lower().split())

    required_phrases = [
        "optional future model assistance is not implemented",
        "outside the deterministic core",
        "outside the inspection boundary",
        "diagnostic, not transformative",
        "no llm, embedding model, network client, runtime download, local-model call, "
        "or remote model call may enter",
        "cleaning",
        "token_budget",
        "prompt_builder",
        "reporting",
        "pipeline",
        "inspection",
        "benchmarking",
        "mechanical behavior only",
        "not LLM answer quality",
        "exact-vs-approximate",
        "never summarizes, rewrites, or paraphrases source content",
    ]

    for phrase in required_phrases:
        assert phrase.lower() in adr_words

    expected_link = "0010-deterministic-first-preparation-model-assistance.md"
    adr_index = _words("docs/adr/README.md")
    adr_index_words = adr_index.lower()
    assert expected_link in adr_index
    assert "deterministic phase 1.7 prepare boundary" in adr_index_words
    assert "optional model assistance is not implemented" in adr_index_words
    assert expected_link in _read("README.md")
    assert "ADR 0010" in _read("docs/roadmap.md")
    assert "ADR 0010" in _read("CHANGELOG.md")


def test_phase_1_7_boundary_is_referenced_by_core_docs() -> None:
    expected_link = "0010-deterministic-first-preparation-model-assistance.md"
    docs = [
        "docs/architecture.md",
        "docs/evaluation.md",
        "docs/release.md",
        "benchmarks/README.md",
    ]

    for path in docs:
        text = _read(path)
        assert expected_link in text, path
        assert "ADR 0010" in text, path

    architecture = _words("docs/architecture.md")
    assert "question-aware lexical chunk selection" in architecture
    assert (
        "no semantic selection, embeddings, network access, local model call, or remote LLM call"
        in architecture
    )

    evaluation = _words("docs/evaluation.md")
    assert "deterministic prepare" in evaluation
    assert "mechanical metrics" in evaluation
    assert "not LLM answer quality" in evaluation

    release = _words("docs/release.md")
    assert "deterministic Phase 1.7 prepare boundary" in release
    assert "ADRs 0001-0011" in release

    benchmarks = _words("benchmarks/README.md")
    assert "lexical/mechanical signals" in benchmarks
    assert "does not summarize, rewrite, or paraphrase source content" in benchmarks


def test_phase_2_first_slice_boundary_stub_is_documented() -> None:
    adr_path = "docs/adr/0011-phase-2-opt-in-semantic-retrieval-boundary.md"
    adr = _read(adr_path)
    adr_words = " ".join(adr.lower().split())

    required_phrases = [
        "**status:** accepted",
        "phase 2",
        "optional local semantic retrieval",
        "disabled-by-default opt-in scaffold",
        "semantic_retrieval",
        "lcc semantic-retrieval",
        "semantic_retrieval.enabled",
        "semantic_retrieval.index_manifest",
        "semantic_retrieval.embedding_assets",
        "opt-in",
        "outside the deterministic core",
        "outside the inspection boundary",
        "outside the deterministic benchmark harness",
        "must not enter",
        "cleaning",
        "token_budget",
        "prompt_builder",
        "reporting",
        "pipeline",
        "inspection",
        "benchmarking",
        "exact-vs-approximate token-count honesty",
        "command and configuration surface",
        "disabled by default",
        "module boundary",
        "dependency and asset contract",
        "index and provenance contract",
        "report schema impact",
        "failure modes",
        "test boundary",
        "fail closed",
        "does not retrieve, rank, select, embed, summarize, rewrite, paraphrase, call a model, "
        "touch the network, or build a prompt",
    ]

    for phrase in required_phrases:
        assert phrase in adr_words

    assert adr_path.split("/")[-1] in _read("docs/adr/README.md")

    roadmap = _read("docs/roadmap.md")
    assert "ADR 0011" in roadmap
    assert "Phase 2 remains planned for retrieval itself" in roadmap
    assert "disabled-by-default opt-in scaffold" in roadmap
    assert "semantic-index-1.0" in roadmap
    assert "local vector file references" in roadmap
    assert "validation does not read vector contents" in roadmap
    assert "no retrieval adapter is implemented" in roadmap
