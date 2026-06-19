"""Command-line interface for lcc (ADR 0003).

Thin presentation/IO layer over the pipeline. The optimized prompt goes to ``--output``
(or stdout); the human-readable summary and warnings go to stderr so stdout stays pipeable.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lcc import __version__
from lcc.benchmarking import (
    BenchmarkCaseError,
    load_suite,
    run_suite,
    suite_to_json,
    write_suite_json,
    write_suite_markdown,
)
from lcc.inspection import InspectionRequest
from lcc.inspection import inspect as run_inspection
from lcc.inspection.report import inspection_to_json, write_inspection_report
from lcc.inspection.report import summary_rows as inspect_summary_rows
from lcc.pipeline import OptimizationRequest
from lcc.pipeline import optimize as run_pipeline
from lcc.prompt_builder import available_templates
from lcc.reporting.report import summary_rows, write_report
from lcc.token_budget.pricing import load_pricing

app = typer.Typer(
    add_completion=False,
    help="Local Context Compiler (lcc): deterministic, local-first context optimization "
    "for LLM prompts.",
)
console = Console()
err_console = Console(stderr=True)


def _fail(message: str, code: int = 1) -> NoReturn:
    """Print an error to stderr and exit with a non-zero code."""
    err_console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(code=code)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"lcc {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Local Context Compiler -- clean, dedupe, and structure context before an LLM call."""


def _read_input(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    if not path.exists():
        _fail(f"input file not found: {source}")
    if path.is_dir():
        _fail(f"input path is a directory: {source}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _fail(f"could not read {source}: {exc}")


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    import yaml

    cfg_path = Path(path)
    if not cfg_path.exists():
        _fail(f"config file not found: {path}")
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        _fail(f"could not parse config {path}: {exc}")
    if not isinstance(data, dict):
        _fail(f"config file must be a mapping: {path}")
    return data


def _same_existing_or_resolved_path(left: Path, right: Path) -> bool:
    """Return True when two paths refer to the same target without creating either path."""
    try:
        if left.exists() and right.exists() and left.samefile(right):
            return True
    except OSError:
        pass
    try:
        return left.expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return False


@app.command("optimize")
def optimize_command(
    input_path: str = typer.Argument(
        ..., metavar="INPUT", help="Path to a UTF-8 text file, or '-' to read from stdin."
    ),
    question: str | None = typer.Option(
        None, "--question", "-q", help="The question the downstream LLM must answer."
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model for token counting and pricing (default: gpt-4.1)."
    ),
    max_input_tokens: int | None = typer.Option(
        None, "--max-input-tokens", help="Warn if the optimized context exceeds this count."
    ),
    max_output_tokens: int | None = typer.Option(
        None, "--max-output-tokens", help="Length guidance added to the prompt."
    ),
    task_type: str | None = typer.Option(
        None, "--task-type", help="Task type recorded in the prompt and report."
    ),
    constraint: list[str] | None = typer.Option(
        None, "--constraint", help="Extra constraint line for the prompt (repeatable)."
    ),
    output_path: Path | None = typer.Option(
        None, "--output", "-o", help="Write the optimized prompt here (otherwise stdout)."
    ),
    report_path: Path | None = typer.Option(
        None, "--report", "-r", help="Write the JSON report to this file."
    ),
    pricing: str | None = typer.Option(
        None, "--pricing", help="Path to a pricing YAML file (default: built-in examples)."
    ),
    config: str | None = typer.Option(
        None, "--config", help="Path to a YAML config file providing defaults."
    ),
    template: str | None = typer.Option(
        None, "--template", help="Prompt template name (default: default)."
    ),
    no_boilerplate: bool = typer.Option(
        False, "--no-boilerplate", help="Disable boilerplate line removal."
    ),
    no_near_dedup: bool = typer.Option(
        False, "--no-near-dedup", help="Disable conservative near-duplicate removal."
    ),
    allow_external_knowledge: bool = typer.Option(
        False,
        "--allow-external-knowledge",
        help="Allow the LLM to use outside knowledge (it must be labeled).",
    ),
) -> None:
    """Clean, deduplicate, and structure INPUT into an optimized prompt and JSON report."""
    raw = _read_input(input_path)
    cfg = _load_config(config)

    # Config supplies defaults; explicit CLI flags override (None means "not provided").
    effective_model = model or cfg.get("model") or "gpt-4.1"
    effective_task = task_type or cfg.get("task_type") or "general"
    effective_template = template or cfg.get("template") or "default"
    effective_question = question if question is not None else cfg.get("question", "")
    effective_pricing = pricing or cfg.get("pricing")
    effective_max_in = (
        max_input_tokens if max_input_tokens is not None else cfg.get("max_input_tokens")
    )
    effective_max_out = (
        max_output_tokens if max_output_tokens is not None else cfg.get("max_output_tokens")
    )
    similarity = float(cfg.get("similarity_threshold", 0.95))

    remove_boilerplate = (not no_boilerplate) and bool(cfg.get("remove_boilerplate", True))
    remove_near = (not no_near_dedup) and bool(cfg.get("remove_near_duplicates", True))
    allow_external = allow_external_knowledge or bool(cfg.get("allow_external_knowledge", False))

    constraints = list(cfg.get("constraints") or [])
    if constraint:
        constraints.extend(constraint)

    if effective_template not in available_templates():
        _fail(
            f"unknown template {effective_template!r}. "
            f"Available: {', '.join(available_templates())}.",
            code=2,
        )

    pricing_doc: dict[str, Any] | None = None
    if effective_pricing:
        try:
            pricing_doc = load_pricing(effective_pricing)
        except (FileNotFoundError, ValueError) as exc:
            _fail(str(exc))

    request = OptimizationRequest(
        raw_text=raw,
        question=effective_question or "",
        model=effective_model,
        task_type=effective_task,
        constraints=constraints,
        max_output_tokens=effective_max_out,
        max_input_tokens=effective_max_in,
        allow_external_knowledge=allow_external,
        remove_boilerplate=remove_boilerplate,
        remove_near_duplicates=remove_near,
        similarity_threshold=similarity,
        template_name=effective_template,
        pricing=pricing_doc,
    )
    result = run_pipeline(request)

    if output_path is not None:
        try:
            output_path.write_text(result.prompt, encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write prompt to {output_path}: {exc}")
    else:
        sys.stdout.write(result.prompt)

    if report_path is not None:
        try:
            write_report(result.report, report_path)
        except OSError as exc:
            _fail(f"could not write report to {report_path}: {exc}")

    _print_summary(result.report, output_path, report_path)


def _print_summary(report: Any, output_path: Path | None, report_path: Path | None) -> None:
    table = Table(title="lcc -- optimization summary", show_header=False, box=None, pad_edge=False)
    table.add_column("metric", style="bold cyan", no_wrap=True)
    table.add_column("value")
    for label, value in summary_rows(report):
        table.add_row(label, value)
    err_console.print(table)
    if output_path is not None:
        err_console.print(f"Prompt written to: [green]{output_path}[/green]")
    if report_path is not None:
        err_console.print(f"Report written to: [green]{report_path}[/green]")
    if report.warnings:
        body = "\n".join(f"- {warning}" for warning in report.warnings)
        err_console.print(Panel(body, title="Warnings", border_style="yellow", expand=False))


@app.command("bench")
def bench_command(
    cases_path: str = typer.Argument(
        ...,
        metavar="CASES_DIR",
        help="Directory of benchmark case folders (each with case.yaml + input.txt).",
    ),
    output_path: Path | None = typer.Option(
        None, "--output", "-o", help="Write the JSON suite report here (otherwise stdout)."
    ),
    markdown_path: Path | None = typer.Option(
        None, "--markdown", help="Also write a human-readable Markdown report to this file."
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Override the model for every case (default: each case's own)."
    ),
) -> None:
    """Run the deterministic benchmark suite in CASES_DIR and report optimization metrics.

    Measures mechanical optimization behavior (token savings, compression, marker
    preservation, exact/approximate counting) -- not LLM answer quality. Exits non-zero if
    any case fails its thresholds or the path is invalid.
    """
    try:
        cases = load_suite(cases_path)
    except BenchmarkCaseError as exc:
        _fail(str(exc))

    if model:
        cases = [replace(case, model=model) for case in cases]

    suite = run_suite(cases)

    if output_path is not None:
        try:
            write_suite_json(suite, output_path)
        except OSError as exc:
            _fail(f"could not write report to {output_path}: {exc}")
    else:
        sys.stdout.write(suite_to_json(suite) + "\n")

    if markdown_path is not None:
        try:
            write_suite_markdown(suite, markdown_path)
        except OSError as exc:
            _fail(f"could not write markdown to {markdown_path}: {exc}")

    _print_bench_summary(suite, output_path, markdown_path)
    if suite.failed_cases:
        raise typer.Exit(code=1)


def _print_bench_summary(suite: Any, output_path: Path | None, markdown_path: Path | None) -> None:
    table = Table(title="lcc -- benchmark summary", show_header=False, box=None, pad_edge=False)
    table.add_column("metric", style="bold cyan", no_wrap=True)
    table.add_column("value")
    table.add_row("Total cases", str(suite.total_cases))
    table.add_row("Passed", str(suite.passed_cases))
    table.add_row("Failed", str(suite.failed_cases))
    table.add_row("Avg token savings", f"{suite.average_token_savings_percent:.1f}%")
    table.add_row("Avg compression ratio", f"{suite.average_compression_ratio:.3f}")
    err_console.print(table)
    if output_path is not None:
        err_console.print(f"Report written to: [green]{output_path}[/green]")
    if markdown_path is not None:
        err_console.print(f"Markdown written to: [green]{markdown_path}[/green]")
    failed = [case for case in suite.cases if not case.passed]
    if failed:
        body = "\n".join(
            f"- [bold]{case.id}[/bold]: " + "; ".join(case.failure_reasons) for case in failed
        )
        err_console.print(Panel(body, title="Failed cases", border_style="red", expand=False))


@app.command("inspect")
def inspect_command(
    input_path: str = typer.Argument(
        ..., metavar="INPUT", help="Path to a UTF-8 text file, or '-' to read from stdin."
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model for token counting and pricing (default: gpt-4.1)."
    ),
    report_path: Path | None = typer.Option(
        None, "--report", "-r", help="Write the JSON diagnostic report here (otherwise stdout)."
    ),
) -> None:
    """Analyze INPUT and emit a deterministic diagnostic report -- no prompt is generated.

    Reports the token, structure, duplication, cleanup, and cost profile of INPUT and projects
    what ``lcc optimize``'s safe cleaning would remove, to help you decide whether to optimize.
    It is diagnostic only (ADR 0009): it never builds or writes an optimized prompt, makes no
    network or model call, and never modifies the input file. The JSON report goes to
    ``--report`` (or stdout); the human-readable summary and warnings go to stderr.
    """
    source_type = "stdin" if input_path == "-" else "file"
    raw = _read_input(input_path)
    effective_model = model or "gpt-4.1"

    if input_path != "-" and report_path is not None:
        input_file = Path(input_path)
        if _same_existing_or_resolved_path(input_file, report_path):
            _fail("--report must not point to the input file; inspect never modifies its input.")

    report = run_inspection(
        InspectionRequest(raw_text=raw, source_type=source_type, model=effective_model)
    )

    if report_path is not None:
        try:
            write_inspection_report(report, report_path)
        except OSError as exc:
            _fail(f"could not write report to {report_path}: {exc}")
    else:
        sys.stdout.write(inspection_to_json(report) + "\n")

    _print_inspect_summary(report, report_path)


def _print_inspect_summary(report: Any, report_path: Path | None) -> None:
    table = Table(title="lcc -- inspection summary", show_header=False, box=None, pad_edge=False)
    table.add_column("metric", style="bold cyan", no_wrap=True)
    table.add_column("value")
    for label, value in inspect_summary_rows(report):
        table.add_row(label, value)
    err_console.print(table)
    if report_path is not None:
        err_console.print(f"Report written to: [green]{report_path}[/green]")
    if report.warnings:
        body = "\n".join(f"- {warning}" for warning in report.warnings)
        err_console.print(Panel(body, title="Warnings", border_style="yellow", expand=False))


def cli_main() -> None:
    """Console-script entry point (``lcc``)."""
    app()


if __name__ == "__main__":
    cli_main()
