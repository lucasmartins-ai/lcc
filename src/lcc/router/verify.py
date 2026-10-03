"""MSI Sprint 5: layered verification runner (deterministic-first, fail-closed).

Protocol ported from agenttrace-studio (read-only reference, no dependency):

- check shape ``{id, passed, detail}`` + reason-code taxonomy from
  ``services/agent-api/agent_api/evals/checks.py`` (9 deterministic checks);
- gate semantics from ``evals/ci_gate.py`` (thresholds, 100%-or-block on
  citations, zero-regression spirit: any hard-layer FAIL blocks PASS);
- tri-state + single-shot from ``lcc.relevance.verifier`` (REVIEW is doubt,
  never conflated with FAIL; verifier problems degrade to REVIEW).

Six layers (sprint IN scope): schema assertions, task assertions, citation
checks, test results, semantic (opt-in, single-shot, inherits
``verify_semantic_contract``), policy checks. No provider calls here unless
the caller supplies a semantic client; every other layer is pure stdlib.

Correction rule (sprint prompt): a layer that yields REVIEW in >50% of runs
without a matching FAIL is recalibrated to advisory with written evidence.
The semantic layer satisfies this by construction: it is advisory unless it
holds confident evidence of insufficiency (inherits the verifier bands).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

EVALUATOR_VERSION = "verify-1.0"
SCHEMA_VERSION = "verification-result/0.1"

VALID_STATUSES = ("PASS", "REVIEW", "FAIL")
VALID_ACTIONS = (
    "PASS",
    "RESTORE_CONTEXT",
    "RETRY",
    "INCREASE_REASONING",
    "SWITCH_MODEL",
    "ADD_TOOL",
    "ESCALATE",
    "ABORT",
)
VALID_PROFILES = ("strict", "standard", "light")

# Reasons that carry doubt, not concrete evidence of insufficiency: they can
# only force REVIEW, never FAIL (inherits verifier.py bands; sprint-3 crash
# guarantee). Everything else is hard evidence -> FAIL.
_ADVISORY_REASONS = ("semantic_uncertain", "semantic_unavailable", "layer_crashed")

# Layer -> recommended action on FAIL (documented in docs/msi/verification.md).
_ACTION_BY_LAYER = {
    "schema": "ABORT",
    "task": "RETRY",
    "citation": "RESTORE_CONTEXT",
    "test": "RETRY",
    "semantic_fail": "RESTORE_CONTEXT",
    "semantic_review": "ESCALATE",
    "policy_budget": "ESCALATE",
    "policy_tool": "ABORT",
    "policy_missing_tool": "ADD_TOOL",
}


@dataclass(frozen=True)
class LayerCheck:
    """One check result: AgentTrace ``{name, status}`` shape, LCC-local."""

    id: str
    passed: bool
    detail: str = ""
    reason_code: str | None = None  # taxonomy port, audit only (not in spec)


@dataclass(frozen=True)
class UnitResult:
    name: str
    passed: bool


@dataclass(frozen=True)
class VerificationSubject:
    """Everything the layers inspect. Built by the executor; all stdlib types."""

    output: dict[str, Any] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    required_facts: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    citation_ids: list[str] = field(default_factory=list)
    valid_citation_ids: frozenset[str] = frozenset()
    require_citations: bool = False
    tests: list[UnitResult] = field(default_factory=list)
    latency_ms: int | None = None
    max_latency_ms: int | None = None
    cost_usd: float | None = None
    max_cost_usd: float | None = None
    tools_used: list[str] = field(default_factory=list)
    allowed_tools: list[str] | None = None  # None = no tool policy configured
    required_tools: list[str] = field(default_factory=list)
    objective: str = ""
    candidate_context: str = ""
    semantic_client: Any = None  # opt-in; None = semantic layer advisory-skips


@dataclass(frozen=True)
class VerificationOutcome:
    """Tri-state result. ``to_spec_dict`` strips audit for schema validation."""

    status: str  # PASS | REVIEW | FAIL
    checks: list[LayerCheck] = field(default_factory=list)
    confidence: float = 1.0
    failures: list[str] = field(default_factory=list)
    recommended_action: str = "PASS"
    evaluator_version: str = EVALUATOR_VERSION

    def to_spec_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "checks": [
                {"id": c.id, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
            "confidence": self.confidence,
            "failures": list(self.failures),
            "recommended_action": self.recommended_action,
        }


def _fail(check_id: str, reason: str, detail: str = "") -> LayerCheck:
    return LayerCheck(id=check_id, passed=False, detail=detail or reason, reason_code=reason)


def _pass(check_id: str, detail: str = "passed") -> LayerCheck:
    return LayerCheck(id=check_id, passed=True, detail=detail)


def layer_schema(subject: VerificationSubject) -> list[LayerCheck]:
    """Port of ``output_schema_valid``: required fields present and non-empty."""
    if not isinstance(subject.output, dict):
        return [_fail("schema_valid", "output_schema_invalid", "output is not an object")]
    missing = [f for f in subject.required_fields if f not in subject.output]
    empty = [
        f
        for f in subject.required_fields
        if f in subject.output and subject.output[f] in ("", None, [], {})
    ]
    if missing or empty:
        return [
            _fail(
                "schema_valid",
                "output_schema_invalid",
                f"missing={missing} empty={empty}",
            )
        ]
    return [_pass("schema_valid", f"{len(subject.required_fields)} required fields present")]


def _search_texts(output: dict[str, Any]) -> tuple[str, str]:
    """Two haystacks: JSON dump (structure) + raw strings (no escaping).

    The dump alone misses facts containing quotes/newlines (escaped) and
    non-ASCII (escaped by default); the raw concatenation alone misses
    non-string values. Searching both closes the gap in one place.
    """
    import json

    dump = json.dumps(output, sort_keys=True, ensure_ascii=False).lower()
    strings: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                collect(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                collect(v)

    collect(output)
    return dump, " ".join(strings).lower()


def layer_task(subject: VerificationSubject) -> list[LayerCheck]:
    """Port of ``required_facts_present`` + ``forbidden_claims_absent``."""
    dump, raw = _search_texts(subject.output)
    facts = [f for f in subject.required_facts if f.strip()]  # empty carries no signal
    missing = [f for f in facts if f.lower() not in dump and f.lower() not in raw]
    out: list[LayerCheck] = []
    out.append(
        _fail("required_facts_present", "required_fact_missing", f"missing={missing}")
        if missing
        else _pass("required_facts_present", f"{len(facts)} facts present")
    )
    present = [
        c
        for c in subject.forbidden_claims
        if c.strip() and (c.lower() in dump or c.lower() in raw)
    ]
    out.append(
        _fail("forbidden_claims_absent", "forbidden_claim_present", f"present={present}")
        if present
        else _pass("forbidden_claims_absent", "no forbidden claims")
    )
    return out


def layer_citation(subject: VerificationSubject) -> list[LayerCheck]:
    """Port of ``citations_resolve`` (local id-set, no DB; snapshot match skipped)."""
    if not subject.citation_ids and not subject.require_citations:
        return [_pass("citations_resolve", "no citations required or supplied (not_configured)")]
    if not subject.citation_ids:
        return [_fail("citations_resolve", "citation_missing", "output carries no citations")]
    unresolved = [c for c in subject.citation_ids if c not in subject.valid_citation_ids]
    if unresolved:
        return [
            _fail(
                "citations_resolve",
                "citation_unresolved",
                f"unresolved={unresolved}",
            )
        ]
    return [_pass("citations_resolve", f"{len(subject.citation_ids)} citations resolve")]


def layer_tests(subject: VerificationSubject) -> list[LayerCheck]:
    """Port of ``tool_errors_absent`` shape: supplied test outcomes all green."""
    if not subject.tests:
        return [_pass("tests_green", "no tests configured (not_configured)")]
    failed = [t.name for t in subject.tests if not t.passed]
    if failed:
        return [_fail("tests_green", "test_failed", f"failed={failed}")]
    return [_pass("tests_green", f"{len(subject.tests)} tests green")]


def layer_semantic(subject: VerificationSubject) -> list[LayerCheck]:
    """Opt-in single-shot semantic layer; inherits ``verifier.py`` bands.

    No client -> advisory skip (passed, never FAIL). Client crash ->
    REVIEW (fail-closed, mirrors ``verifier_unavailable_fail_closed``).
    """
    from lcc.relevance.verifier import verify_semantic_contract

    if subject.semantic_client is None:
        return [_pass("semantic_sufficient", "no semantic client: advisory skip, not evidence")]
    try:
        contract = verify_semantic_contract(
            objective=subject.objective,
            candidate_context=subject.candidate_context,
            client=subject.semantic_client,
        )
    except Exception as exc:  # fail-closed: transport/code problems -> REVIEW
        return [
            LayerCheck(
                id="semantic_sufficient",
                passed=False,
                detail=f"verifier crashed: {exc}",
                reason_code="semantic_unavailable",
            )
        ]
    if contract.decision == "PASS":
        return [_pass("semantic_sufficient", f"judged sufficient ({contract.reason})")]
    # REVIEW and FAIL both read as check-failed; the runner maps REVIEW->REVIEW
    # and FAIL->FAIL via the reason code below.
    code = (
        "semantic_insufficient"
        if contract.decision == "FAIL"
        else "semantic_uncertain"
    )
    return [
        LayerCheck(
            id="semantic_sufficient",
            passed=False,
            detail=f"{contract.decision}: {contract.reason}",
            reason_code=code,
        )
    ]


def layer_policy(subject: VerificationSubject) -> list[LayerCheck]:
    """Port of ``latency_under_budget`` + ``cost_under_budget`` + tool policy."""
    out: list[LayerCheck] = []
    if subject.max_latency_ms is None:
        out.append(_pass("latency_under_budget", "no budget configured (not_configured)"))
    elif subject.latency_ms is None or subject.latency_ms > subject.max_latency_ms:
        out.append(
            _fail(
                "latency_under_budget",
                "latency_budget_exceeded",
                f"actual={subject.latency_ms} max={subject.max_latency_ms}",
            )
        )
    else:
        out.append(
            _pass("latency_under_budget", f"{subject.latency_ms}<={subject.max_latency_ms}ms")
        )
    if subject.max_cost_usd is None:
        out.append(_pass("cost_under_budget", "no budget configured (not_configured)"))
    elif subject.cost_usd is None or subject.cost_usd > subject.max_cost_usd:
        out.append(
            _fail(
                "cost_under_budget",
                "cost_budget_exceeded",
                f"actual={subject.cost_usd} max={subject.max_cost_usd}",
            )
        )
    else:
        out.append(_pass("cost_under_budget", f"{subject.cost_usd}<={subject.max_cost_usd}"))
    if subject.allowed_tools is None:
        out.append(_pass("tool_policy", "no tool policy configured (not_configured)"))
    else:
        disallowed = [t for t in subject.tools_used if t not in subject.allowed_tools]
        if disallowed:
            out.append(
                _fail("tool_policy", "tool_not_allowed", f"disallowed={disallowed}")
            )
        else:
            out.append(_pass("tool_policy", f"{len(subject.tools_used)} tools within policy"))
    missing = [t for t in subject.required_tools if t not in subject.tools_used]
    if missing:
        out.append(
            _fail("required_tools_used", "required_tool_missing", f"missing={missing}")
        )
    else:
        out.append(_pass("required_tools_used", "all required tools used"))
    return out


_LAYERS: dict[str, Callable[[VerificationSubject], list[LayerCheck]]] = {
    "schema": layer_schema,
    "task": layer_task,
    "citation": layer_citation,
    "test": layer_tests,
    "semantic": layer_semantic,
    "policy": layer_policy,
}

_LAYERS_BY_PROFILE = {
    "light": ("schema", "task"),
    "standard": ("schema", "task", "citation", "test", "policy"),
    "strict": ("schema", "task", "citation", "test", "semantic", "policy"),
}


def _action_for(failed: LayerCheck) -> str:
    if failed.id == "semantic_sufficient":
        if failed.reason_code == "semantic_insufficient":
            return _ACTION_BY_LAYER["semantic_fail"]
        return _ACTION_BY_LAYER["semantic_review"]
    if failed.id in ("latency_under_budget", "cost_under_budget"):
        return _ACTION_BY_LAYER["policy_budget"]
    if failed.id == "tool_policy":
        return _ACTION_BY_LAYER["policy_tool"]
    if failed.id == "required_tools_used":
        return _ACTION_BY_LAYER["policy_missing_tool"]
    for layer, action in (
        ("schema", "schema_valid"),
        ("task", "required_facts_present"),
        ("task", "forbidden_claims_absent"),
        ("citation", "citations_resolve"),
        ("test", "tests_green"),
    ):
        if failed.id == action:
            return _ACTION_BY_LAYER[layer]
    return "ESCALATE"  # fail-closed default for unmapped failures


def run_verification(
    subject: VerificationSubject, profile: str = "strict"
) -> VerificationOutcome:
    """Run the layered checks; aggregate to tri-state + one recommended action.

    Unknown profile -> REVIEW fail-closed (mirrors checks.py unknown-check).
    A crashing layer -> REVIEW entry (fail-closed, mirrors sprint-3 guarantee).
    REVIEW/FAIL are never silent: every failure lands in ``failures``.
    """
    if profile not in VALID_PROFILES:
        return VerificationOutcome(
            status="REVIEW",
            checks=[],
            confidence=0.0,
            failures=[f"unknown_verification_profile:{profile}"],
            recommended_action="ESCALATE",
        )
    checks: list[LayerCheck] = []
    for layer in _LAYERS_BY_PROFILE[profile]:
        try:
            checks.extend(_LAYERS[layer](subject))
        except Exception as exc:  # fail-closed, never silent
            checks.append(
                LayerCheck(
                    id=f"{layer}_layer",
                    passed=False,
                    detail=f"layer crashed fail-closed: {exc}",
                    reason_code="layer_crashed",
                )
            )
    failed = [c for c in checks if not c.passed]
    if not failed:
        return VerificationOutcome(
            status="PASS", checks=checks, confidence=1.0, recommended_action="PASS"
        )
    if any(c.reason_code not in _ADVISORY_REASONS for c in failed):
        status = "FAIL"
        action = _action_for(failed[0])
    else:
        status = "REVIEW"
        action = "ESCALATE"  # doubt escalates, never passes silently
    confidence = round(sum(1 for c in checks if c.passed) / len(checks), 3) if checks else 0.0
    return VerificationOutcome(
        status=status,
        checks=checks,
        confidence=confidence,
        failures=[f"{c.id}:{c.reason_code or 'failed'}:{c.detail}" for c in failed],
        recommended_action=action,
    )
