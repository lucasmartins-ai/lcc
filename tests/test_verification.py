"""MSI Sprint 5: layered verification + escalation machine (offline only).

One injection test per layer (schema, task, citation, test, semantic,
policy) + crash fail-closed + retry-limit + 3 frozen golden receipts.
No provider calls: the semantic client is a stub shaped like
``client.evaluate``; ``parse_noul_answer`` consumes ``{"noul", "confidence"}``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lcc.router.escalate import ReceiptVersions, run_execution
from lcc.router.plan import DeterministicPlanner, EscalationPolicy, PlannerInput
from lcc.router.verify import UnitResult, VerificationSubject, run_verification

jsonschema = pytest.importorskip("jsonschema", reason="spec validation needs jsonschema")

SPEC_DIR = Path(__file__).parent / "fixtures" / "msi"
VERIFY_SCHEMA = json.loads((SPEC_DIR / "verification-result.schema.json").read_text())
RECEIPT_SCHEMA = json.loads((SPEC_DIR / "inference-receipt.schema.json").read_text())
DET = DeterministicPlanner()
FIXED_AT = "2026-10-03T00:00:00+00:00"


def _good() -> VerificationSubject:
    return VerificationSubject(
        output={"summary": "fixed null deref", "labels": ["bug"]},
        required_fields=["summary"],
        required_facts=["null deref"],
        citation_ids=["c1"],
        valid_citation_ids=frozenset({"c1"}),
        require_citations=True,
        tests=[UnitResult("unit", True)],
        latency_ms=10,
        max_latency_ms=100,
        cost_usd=0.001,
        max_cost_usd=0.01,
        tools_used=["retrieval.search"],
        allowed_tools=["retrieval.search"],
        required_tools=["retrieval.search"],
        objective="fix the crash",
        candidate_context="the crash is a null deref",
    )


class _StubClient:
    """Fake semantic judge: fixed (sufficiency, confidence) + optional crash."""

    def __init__(self, suff=0.9, conf=0.9, contra=0.1, crash=False):
        self._suff, self._conf, self._contra, self._crash = suff, conf, contra, crash
        self.model = "stub"
        self.last_resolved_model = "stub-1"

    def evaluate(self, state, questions):
        if self._crash:
            raise RuntimeError("transport down")
        return {
            "answers": {
                "sufficient_to_answer": {"noul": self._suff, "confidence": self._conf},
                "contradiction_risk": {"noul": self._contra, "confidence": 0.9},
            }
        }


def _plan(**kw):
    inp = PlannerInput(task_id="t", risk_level=kw.pop("risk", "low"))
    plan = DET.plan(inp)
    esc = EscalationPolicy(
        max_retries=kw.get("max_retries", plan.escalation_policy.max_retries),
        max_restorations=kw.get(
            "max_restorations", plan.escalation_policy.max_restorations
        ),
        escalate_to=kw.get("escalate_to", plan.escalation_policy.escalate_to),
    )
    from dataclasses import replace

    return replace(plan, escalation_policy=esc)


# --- injection: one per layer ---


def test_schema_missing_field_fails_abort():
    s = _good()
    from dataclasses import replace

    s = replace(s, output={"labels": []})
    o = run_verification(s)
    assert o.status == "FAIL" and o.recommended_action == "ABORT"
    assert any("output_schema_invalid" in f for f in o.failures)
    jsonschema.validate(o.to_spec_dict(), VERIFY_SCHEMA)


def test_task_missing_fact_fails_retry():
    from dataclasses import replace

    o = run_verification(replace(_good(), required_facts=["quantum hamster"]))
    assert o.status == "FAIL" and o.recommended_action == "RETRY"
    jsonschema.validate(o.to_spec_dict(), VERIFY_SCHEMA)


def test_task_forbidden_claim_fails_retry():
    from dataclasses import replace

    o = run_verification(replace(_good(), forbidden_claims=["null deref"]))
    assert o.status == "FAIL" and o.recommended_action == "RETRY"


def test_citation_unresolved_fails_restore():
    from dataclasses import replace

    o = run_verification(replace(_good(), citation_ids=["ghost"]))
    assert o.status == "FAIL" and o.recommended_action == "RESTORE_CONTEXT"


def test_failing_test_fails_retry():
    from dataclasses import replace

    o = run_verification(replace(_good(), tests=[UnitResult("unit", False)]))
    assert o.status == "FAIL" and o.recommended_action == "RETRY"


def test_semantic_confident_insufficiency_fails_restore():
    from dataclasses import replace

    client = _StubClient(suff=0.1, conf=0.9)
    o = run_verification(replace(_good(), semantic_client=client))
    assert o.status == "FAIL" and o.recommended_action == "RESTORE_CONTEXT"


def test_semantic_unavailable_reviews_never_silent():
    from dataclasses import replace

    client = _StubClient(crash=True)
    o = run_verification(replace(_good(), semantic_client=client))
    assert o.status == "REVIEW" and o.recommended_action == "ESCALATE"
    assert o.failures  # doubt is recorded, never silent


def test_semantic_absent_is_advisory_skip():
    o = run_verification(_good())  # strict profile, no client
    assert o.status == "PASS"  # skip cannot fail the run


def test_policy_latency_over_budget_fails_escalate():
    from dataclasses import replace

    o = run_verification(replace(_good(), latency_ms=999))
    assert o.status == "FAIL" and o.recommended_action == "ESCALATE"


def test_policy_disallowed_tool_fails_abort():
    from dataclasses import replace

    o = run_verification(replace(_good(), tools_used=["evil.exec"]))
    assert o.status == "FAIL" and o.recommended_action == "ABORT"


def test_policy_missing_required_tool_fails_add_tool():
    from dataclasses import replace

    o = run_verification(replace(_good(), tools_used=[]))
    assert o.status == "FAIL" and o.recommended_action == "ADD_TOOL"


def test_unknown_profile_reviews_fail_closed():
    o = run_verification(_good(), profile="nope")
    assert o.status == "REVIEW" and o.recommended_action == "ESCALATE"


def test_task_layer_matches_quoted_unicode_and_skips_empty_facts():
    from dataclasses import replace

    s = replace(
        _good(),
        output={"answer": 'Clínica odontológica set "--retries 3" and "backoff: exponential" done'},
        required_fields=["answer"],
        required_facts=[
            "clínica odontológica",
            '"--retries 3"',
            "backoff: exponential",
            "   ",  # empty carries no signal, ignored
        ],
    )
    o = run_verification(s, profile="light")
    assert o.status == "PASS", o.failures


def test_no_provider_fields_in_spec_dicts():
    blob = json.dumps(run_verification(_good()).to_spec_dict()).lower()
    for token in ("jev", "openai", "anthropic", "gpt", "claude"):
        assert token not in blob


# --- machine: limits, transitions, goldens ---


def test_retry_beyond_max_escalates_with_reason():
    from dataclasses import replace

    bad = replace(_good(), required_facts=["quantum hamster"])  # RETRY forever
    run = run_execution(
        task_id="t",
        plan=_plan(max_retries=1),
        execute=lambda i: bad,
        clock=lambda: FIXED_AT,
        versions=ReceiptVersions(compiler="lcc-test", model="local_small"),
    )
    r = run.receipt
    assert r.retries == 1 and r.escalations == ["frontier"]
    assert r.evaluation == "FAIL" and run.attempts == 2
    assert any(e.event == "escalated" and e.reason for e in r.decision_events)
    jsonschema.validate(r.to_spec_dict(), RECEIPT_SCHEMA)


def test_restore_budget_zero_skips_restore_stage():
    from dataclasses import replace

    bad = replace(_good(), citation_ids=["ghost"])  # RESTORE_CONTEXT
    run = run_execution(
        task_id="t",
        plan=_plan(max_restorations=0),
        execute=lambda i: bad,
        clock=lambda: FIXED_AT,
    )
    assert run.receipt.restored == [] and run.attempts == 1
    assert run.receipt.escalations == ["frontier"]


def _golden_versions():
    return ReceiptVersions(
        compiler="lcc-test-1.0",
        policy="planner-1.0",
        model="local_small",
        dataset="n/a",
        evaluator="verify-1.0",
    )


def test_golden_direct_pass_receipt_frozen():
    run = run_execution(
        task_id="task-pass",
        plan=_plan(),
        execute=lambda i: _good(),
        receipt_id="r-pass",
        selected_units=["blk_a"],
        omitted_units=[{"id": "blk_b", "rationale": "duplicate of blk_a"}],
        result_text="fixed",
        clock=lambda: FIXED_AT,
        versions=_golden_versions(),
    )
    d = run.receipt.to_spec_dict()
    jsonschema.validate(d, RECEIPT_SCHEMA)
    assert d == {
        "schema_version": "inference-receipt/0.1",
        "receipt_id": "r-pass",
        "task_id": "task-pass",
        "selected_units": ["blk_a"],
        "omitted_units": [{"id": "blk_b", "rationale": "duplicate of blk_a"}],
        "model": {"class": "local_small", "reasoning_budget": "low"},
        "tools_used": ["retrieval.search"],
        "verification": {"profile": "standard", "result": "PASS"},
        "restorations": {"restored": [], "retries": 0, "escalations": []},
        "cost": {"latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0},
        "versions": {
            "compiler": "lcc-test-1.0",
            "policy": "planner-1.0",
            "model": "local_small",
            "schema": "inference-receipt/0.1",
            "dataset": "n/a",
            "evaluator": "verify-1.0",
        },
        "timestamps": {"started_at": FIXED_AT, "finished_at": FIXED_AT},
        "decision_events": [
            {
                "event": "routed",
                "reason": d["decision_events"][0]["reason"],
                "at": FIXED_AT,
            }
        ],
        "outcome": {"result": "fixed", "evaluation": "PASS"},
    }
    assert d["decision_events"][0]["reason"].startswith("engine=deterministic")


def test_golden_pass_via_restore_receipt_frozen():
    from dataclasses import replace

    first = replace(_good(), citation_ids=["ghost"])
    calls = {"n": 0}

    def execute(i):
        calls["n"] += 1
        return first if i == 0 else _good()

    run = run_execution(
        task_id="task-restore",
        plan=_plan(),
        execute=execute,
        restore=lambda fails: ["blk_ghost"],
        receipt_id="r-restore",
        clock=lambda: FIXED_AT,
        versions=_golden_versions(),
    )
    d = run.receipt.to_spec_dict()
    jsonschema.validate(d, RECEIPT_SCHEMA)
    assert d["verification"] == {"profile": "standard", "result": "PASS"}
    assert d["restorations"]["restored"] == ["blk_ghost"]
    assert d["restorations"]["retries"] == 0
    assert [e["event"] for e in d["decision_events"]] == [
        "routed",
        "failed",
        "restored",
    ]
    assert all(e["reason"] and e["at"] == FIXED_AT for e in d["decision_events"])
    assert d["outcome"] == {"result": "PASS", "evaluation": "PASS"}


def test_golden_escalate_receipt_frozen():
    from dataclasses import replace

    bad = replace(_good(), required_facts=["quantum hamster"])
    run = run_execution(
        task_id="task-escalate",
        plan=_plan(max_retries=1, escalate_to="human"),
        execute=lambda i: bad,
        receipt_id="r-escalate",
        clock=lambda: FIXED_AT,
        versions=_golden_versions(),
    )
    d = run.receipt.to_spec_dict()
    jsonschema.validate(d, RECEIPT_SCHEMA)
    assert d["verification"]["result"] == "FAIL"
    assert d["restorations"] == {"restored": [], "retries": 1, "escalations": ["human"]}
    assert [e["event"] for e in d["decision_events"]] == [
        "routed",
        "failed",
        "routed",
        "failed",
        "escalated",
    ]
    assert all(e["reason"] for e in d["decision_events"])
    assert d["outcome"]["evaluation"] == "FAIL"
