"""Final answer assembly for local and remote routes."""

from __future__ import annotations

from dataclasses import asdict

from lcc.router.schemas import (
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
    compression_applied: bool = False,
) -> FinalAnswer:
    """Construct unified FinalAnswer for local execution."""
    return FinalAnswer(
        task_id=task_id,
        answer=answer.answer,
        route_taken=route.value,
        remote_tokens_used=0,
        local_steps_used=["lcc_inspect"]
        + (["lcc_prepare"] if compression_applied else [])
        + ["local_solver"]
        + (["local_verifier"] if verification is not None else []),
        verification=verification,
        metadata={
            "local_model": answer.model_name,
            "lcc": asdict(lcc_summary),
            "compression_applied": compression_applied,
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
    """Construct unified FinalAnswer for cloud/remote execution."""
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
