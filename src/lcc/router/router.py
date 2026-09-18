"""Hybrid local-first router engine."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Protocol, cast

from lcc.router.cloud_client import (
    RemoteSolver,
    build_fireworks_prompt,
    create_remote_solver_from_env,
)
from lcc.router.config import PolicyConfig, load_policy
from lcc.router.context_adapter import (
    inspect_context,
    optimize_context_if_needed,
    prepare_context,
)
from lcc.router.features import extract_features
from lcc.router.final_formatter import local_final, remote_final
from lcc.router.policy import RoutePlan, choose_route
from lcc.router.prompt_builder import build_local_prompt
from lcc.router.schemas import (
    FinalAnswer,
    LCCReportSummary,
    LocalAnswer,
    PreparedContext,
    RouteDecision,
    TaskFeatures,
    TaskInput,
    VerificationDecision,
    VerificationResult,
)


class LocalSolver(Protocol):
    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        """Return a local answer with zero remote tokens used."""



class Verifier(Protocol):
    def verify(
        self,
        task: TaskInput,
        local_answer: LocalAnswer,
        lcc_report: LCCReportSummary,
        features: TaskFeatures,
    ) -> VerificationResult:
        """Return a local verification decision."""


class LCCRouter:
    """Hybrid local/cloud router that prioritizes zero-token local execution."""

    def __init__(
        self,
        policy: PolicyConfig | None = None,
        local_solver: LocalSolver | None = None,
        remote_solver: RemoteSolver | None = None,
        verifier: Verifier | None = None,
    ) -> None:
        self.policy = policy or load_policy()
        if local_solver is None:
            from lcc.agents.local_solver import create_local_solver_from_env

            self.local_solver: LocalSolver = create_local_solver_from_env()
        else:
            self.local_solver = local_solver

        self.remote_solver = remote_solver or create_remote_solver_from_env()

        if verifier is None:
            from lcc.agents.local_verifier import create_verifier

            self.verifier: Verifier = cast(
                Verifier, create_verifier(self.policy, self.local_solver)
            )
        else:
            self.verifier = verifier


    def run(self, task: TaskInput) -> FinalAnswer:
        lcc_summary = inspect_context(task)
        features = extract_features(task, lcc_summary, self.policy.risk)
        plan = choose_route(features, self.policy)
        trace = [*plan.reasons, f"initial_route:{plan.decision.value}"]
        prepared: PreparedContext | None = None

        if plan.decision in {RouteDecision.COMPRESS_THEN_LOCAL, RouteDecision.COMPRESS_THEN_REMOTE}:
            prepared = prepare_context(task)
            lcc_summary = prepared.lcc_summary
            trace.append(
                "lcc_compression_applied"
                if prepared.compression_applied
                else "lcc_original_context"
            )

        if plan.decision in {
            RouteDecision.LOCAL_ONLY,
            RouteDecision.LOCAL_THEN_VERIFY,
            RouteDecision.COMPRESS_THEN_LOCAL,
        }:
            local_task = replace(task, context=(prepared.context if prepared else task.context))
            local_answer = self._local_answer(local_task)
            if plan.decision == RouteDecision.LOCAL_ONLY:
                return local_final(
                    task_id=task.task_id,
                    answer=local_answer,
                    route=plan.decision,
                    verification=None,
                    lcc_summary=lcc_summary,
                    trace=trace,
                    compression_applied=bool(prepared and prepared.compression_applied),
                )

            verification = self._verify(local_task, local_answer, lcc_summary, features)
            if verification.decision == VerificationDecision.ACCEPT_LOCAL:
                return local_final(
                    task_id=task.task_id,
                    answer=local_answer,
                    route=plan.decision,
                    verification=verification,
                    lcc_summary=lcc_summary,
                    trace=[*trace, "local_accepted"],
                    compression_applied=bool(prepared and prepared.compression_applied),
                )
            trace.append("local_rejected_by_verifier")
            return self._remote_after_local(task, plan, verification, trace, lcc_summary)

        return self._remote_direct(task, plan, trace, lcc_summary, prepared)

    def _local_answer(self, task: TaskInput) -> LocalAnswer:
        prompt = build_local_prompt(task, task.context)
        return self.local_solver.solve(task, prompt)

    def _verify(
        self,
        task: TaskInput,
        local_answer: LocalAnswer,
        lcc_summary: LCCReportSummary,
        features: TaskFeatures,
    ) -> VerificationResult:
        return self.verifier.verify(task, local_answer, lcc_summary, features)

    def _remote_after_local(
        self,
        task: TaskInput,
        plan: RoutePlan,
        verification: VerificationResult,
        trace: list[str],
        lcc_summary: LCCReportSummary,
    ) -> FinalAnswer:
        prepared = optimize_context_if_needed(task, self.policy)
        remote_task = replace(task, context=prepared.context)
        route_taken = (
            f"{plan.decision.value}->{RouteDecision.COMPRESS_THEN_REMOTE.value}"
            if prepared.compression_applied
            else f"{plan.decision.value}->{RouteDecision.REMOTE_DIRECT.value}"
        )
        prompt = build_fireworks_prompt(remote_task, remote_task.context)
        remote = self.remote_solver.complete(remote_task, prompt)
        return remote_final(
            task_id=task.task_id,
            answer=remote,
            route_taken=route_taken,
            verification=verification,
            lcc_summary=prepared.lcc_summary,
            trace=[*trace, "remote_escalation_after_local"],
            compression_applied=prepared.compression_applied,
        )

    def _remote_direct(
        self,
        task: TaskInput,
        plan: RoutePlan,
        trace: list[str],
        lcc_summary: LCCReportSummary,
        prepared: PreparedContext | None,
    ) -> FinalAnswer:
        from lcc.cleaning import safe_clean_text

        context = prepared.context if prepared else safe_clean_text(task.context)
        remote_task = replace(task, context=context)
        prompt = build_fireworks_prompt(remote_task, context)
        remote = self.remote_solver.complete(remote_task, prompt)
        return remote_final(
            task_id=task.task_id,
            answer=remote,
            route_taken=plan.decision.value,
            verification=None,
            lcc_summary=(prepared.lcc_summary if prepared else lcc_summary),
            trace=trace,
            compression_applied=bool(prepared and prepared.compression_applied),
        )


def final_answer_to_dict(answer: FinalAnswer) -> dict[str, object]:
    return asdict(answer)
