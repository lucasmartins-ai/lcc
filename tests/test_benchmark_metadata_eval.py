"""Reproducible benchmark metadata + answer-level evaluation tests (offline)."""

from lcc.benchmarking import build_metadata, metadata_to_dict


def test_metadata_records_full_identity():
    meta = build_metadata(
        corpus="some corpus",
        objective="some question",
        requested_model="jev-latest",
        resolved_model="jev-2026-09-01",
        provider="jev",
        configuration={"threshold": 0.4},
        thresholds={"keep": 0.4},
        seed=7,
        tokenizer_id="o200k_base",
        tokenizer_version="9.0",
        token_count_method="exact",
    )
    payload = metadata_to_dict(meta)
    assert payload["corpus_sha256"] and payload["objective_sha256"]
    assert payload["requested_model"] == "jev-latest"
    assert payload["resolved_model"] == "jev-2026-09-01"  # alias never stands alone
    assert payload["policy_version"] == "relevance-compaction-1.1"
    assert payload["schema_version"] == "relevance-compaction-1.1"
    assert payload["tokenizer_id"] == "o200k_base"
    assert payload["seed"] == 7
    assert payload["timestamp"]


def test_metadata_resolved_defaults_to_requested():
    meta = build_metadata(corpus="c", objective="q", requested_model="mechanical")
    assert metadata_to_dict(meta)["resolved_model"] == "mechanical"


def test_answer_level_no_regressions_on_subset():
    """Tokens may drop; required-fact recall must not. A drop in recall is a failure."""
    import importlib.util
    import sys
    from pathlib import Path

    cases_path = (
        Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "adversarial_cases.py"
    )
    spec = importlib.util.spec_from_file_location("_adv_cases_eval", cases_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "research"))
    import run_answer_eval

    subset = ["negation_consent", "multiblock_vat_set", "scope_quantifiers",
              "injection_html", "coreference_resolution", "contradiction_same_metric"]
    by_id = {c.id: c for c in module.CASES}
    for case_id in subset:
        row = run_answer_eval.evaluate_case(by_id[case_id], pressure=1, provider="mechanical")
        assert row["tokens_after"] <= row["tokens_before"]
        assert not row["regression"], f"{case_id}: {row['compacted_missing']}"
        assert row["compacted_recall"] == 1.0
