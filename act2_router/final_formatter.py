"""Final answer assembly."""

from __future__ import annotations

from dataclasses import asdict

from act2_router.schemas import (
    FinalAnswer,
    LCCReportSummary,
    LocalAnswer,
    RemoteAnswer,
    RouteDecision,
    VerificationResult,
)


def local_final(
    *,
    task_id: str,
    answer: LocalAnswer,
    route: RouteDecision,
    verification: VerificationResult | None,
    lcc_summary: LCCReportSummary,
    trace: list[str],
) -> FinalAnswer:
    return FinalAnswer(
        task_id=task_id,
        answer=answer.answer,
        route_taken=route.value,
        remote_tokens_used=0,
        local_steps_used=["lcc_inspect", "local_solver"]
        + (["local_verifier"] if verification is not None else []),
        verification=verification,
        metadata={
            "local_model": answer.model_name,
            "lcc": asdict(lcc_summary),
            "trace": trace,
        },
    )


def remote_final(
    *,
    task_id: str,
    answer: RemoteAnswer,
    route_taken: str,
    verification: VerificationResult | None,
    lcc_summary: LCCReportSummary,
    trace: list[str],
    compression_applied: bool,
) -> FinalAnswer:
    return FinalAnswer(
        task_id=task_id,
        answer=answer.answer,
        route_taken=route_taken,
        remote_tokens_used=answer.total_tokens,
        local_steps_used=["lcc_inspect"] + (["lcc_prepare"] if compression_applied else []),
        verification=verification,
        metadata={
            "remote_model": answer.model_name,
            "remote_prompt_tokens": answer.prompt_tokens,
            "remote_completion_tokens": answer.completion_tokens,
            "remote_usage_estimated": answer.usage_estimated,
            "remote_error": answer.error,
            "lcc": asdict(lcc_summary),
            "compression_applied": compression_applied,
            "trace": trace,
        },
    )
