"""Local development evaluation harness for router fixtures."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from act2_router.local_verifier import _format_valid
from act2_router.router import LCCRouter, final_answer_to_dict
from act2_router.schemas import EvaluationResult, FinalAnswer, TaskInput


def load_task(path: str | Path) -> tuple[TaskInput, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"task file must contain a JSON object: {path}")
    metadata = dict(data.get("metadata") or {})
    for key in [
        "expected_answer",
        "required_markers",
        "forbidden_markers",
        "required_fields",
    ]:
        if key in data and key not in metadata:
            metadata[key] = data[key]
    normalized = {**data, "metadata": metadata}
    return TaskInput.from_mapping(normalized), data


def run_evaluation(cases_dir: str | Path, router: LCCRouter | None = None) -> dict[str, Any]:
    router = router or LCCRouter()
    case_paths = sorted(Path(cases_dir).glob("*.json"))
    finals: list[FinalAnswer] = []
    failures: list[dict[str, Any]] = []
    format_passes = 0
    proxy_scores: list[float] = []

    for path in case_paths:
        task, raw = load_task(path)
        final = router.run(task)
        finals.append(final)
        passed_format = _format_pass(task, final)
        format_passes += int(passed_format)
        score, reasons = _proxy_score(raw, final, passed_format)
        proxy_scores.append(score)
        if reasons:
            failures.append({"task_id": task.task_id, "path": str(path), "reasons": reasons})

    total = len(finals)
    remote_total = sum(item.remote_tokens_used for item in finals)
    local_accepts = sum(1 for item in finals if item.remote_tokens_used == 0)
    result = EvaluationResult(
        total_cases=total,
        remote_tokens_total=remote_total,
        remote_tokens_mean=round(remote_total / total, 2) if total else 0.0,
        local_accept_rate=round(local_accepts / total, 4) if total else 0.0,
        remote_escalation_rate=round((total - local_accepts) / total, 4) if total else 0.0,
        format_pass_rate=round(format_passes / total, 4) if total else 0.0,
        estimated_accuracy_proxy=round(sum(proxy_scores) / total, 4) if total else 0.0,
        failures=failures,
    )
    compression_rate = (
        sum(1 for item in finals if item.metadata.get("compression_applied")) / total
        if total
        else 0.0
    )
    avg_projected_savings = (
        sum(
            float(item.metadata.get("lcc", {}).get("projected_savings_ratio", 0.0))
            for item in finals
        )
        / total
        if total
        else 0.0
    )
    return {
        "note": "Local development proxy only; not official AMD Track 1 accuracy.",
        "result": asdict(result),
        "lcc_compression_applied_rate": round(compression_rate, 4),
        "average_projected_savings": round(avg_projected_savings, 4),
        "cases": [final_answer_to_dict(item) for item in finals],
    }


def write_reports(report: dict[str, Any], output: str | Path) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown = out.with_suffix(".md")
    markdown.write_text(_markdown_report(report), encoding="utf-8")
    return out


def _format_pass(task: TaskInput, final: FinalAnswer) -> bool:
    if final.verification is not None:
        return final.verification.format_valid
    if not task.expected_format:
        return True
    return _format_valid(task.expected_format, final.answer)[0]


def _proxy_score(
    raw_case: dict[str, Any], final: FinalAnswer, format_passed: bool
) -> tuple[float, list[str]]:
    metadata = dict(raw_case.get("metadata") or {})
    for key in ["expected_answer", "required_markers", "forbidden_markers", "required_fields"]:
        if key in raw_case:
            metadata[key] = raw_case[key]

    score = 1.0
    failures: list[str] = []
    expected = metadata.get("expected_answer")
    if expected is not None and final.answer.strip() != str(expected).strip():
        score -= 0.4
        failures.append("expected_answer_mismatch")
    for marker in metadata.get("required_markers", []) or []:
        if str(marker) not in final.answer:
            score -= 0.15
            failures.append(f"missing_marker:{marker}")
    for marker in metadata.get("forbidden_markers", []) or []:
        if str(marker) in final.answer:
            score -= 0.15
            failures.append(f"forbidden_marker:{marker}")
    if not format_passed:
        score -= 0.25
        failures.append("format_failed")
    if final.answer.startswith("[remote_error]"):
        score = 0.0
        failures.append("remote_error")
    return max(score, 0.0), failures


def _markdown_report(report: dict[str, Any]) -> str:
    result = report["result"]
    lines = [
        "# LCC-Router Local Evaluation",
        "",
        str(report["note"]),
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in result.items():
        if key != "failures":
            lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            f"| lcc_compression_applied_rate | {report['lcc_compression_applied_rate']} |",
            f"| average_projected_savings | {report['average_projected_savings']} |",
            "",
            "## Cases",
            "",
            "| case | route | remote_tokens_used |",
            "| --- | --- | ---: |",
        ]
    )
    for item in report.get("cases", []):
        lines.append(
            f"| {item['task_id']} | {item['route_taken']} | {item['remote_tokens_used']} |"
        )
    lines.extend(
        [
            "",
            "## Failures",
            "",
        ]
    )
    failures = result.get("failures", [])
    if not failures:
        lines.append("None.")
    else:
        for failure in failures:
            lines.append(f"- `{failure['task_id']}`: {', '.join(failure['reasons'])}")
    return "\n".join(lines) + "\n"
