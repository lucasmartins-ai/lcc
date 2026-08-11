"""Command-line interface for lcc (ADR 0003).

Thin presentation/IO layer over the pipeline. The optimized prompt goes to ``--output``
(or stdout); the human-readable summary and warnings go to stderr so stdout stays pipeable.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, replace
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
from lcc.inspection.report import (
    compact_summary_lines,
    inspection_to_dict,
    inspection_to_json,
    write_inspection_report,
)
from lcc.inspection.report import summary_rows as inspect_summary_rows
from lcc.lexical_selection import PREPARE_SCHEMA_VERSION, select_chunks_for_question
from lcc.pipeline import OptimizationRequest
from lcc.pipeline import optimize as run_pipeline
from lcc.prompt_builder import available_templates
from lcc.reporting.report import report_to_dict, summary_rows, write_report
from lcc.semantic_retrieval import (
    LOCAL_INDEX_V1_ADAPTER,
    SemanticRetrievalBoundaryError,
    SemanticRetrievalConfig,
    SemanticRetrievalExecutionRequest,
    semantic_retrieval_boundary_report,
    semantic_retrieval_execution_report,
)
from lcc.token_budget.pricing import load_pricing

app = typer.Typer(
    add_completion=False,
    help="Local Context Compiler (lcc): deterministic, local-first context optimization "
    "for LLM prompts.",
)
console = Console()
err_console = Console(stderr=True)
_OPTIMIZE_RECOMMENDATION_ACTIONS = {"optimize_safe", "optimize_with_flags"}
_SEMANTIC_RETRIEVAL_CONFIG_KEYS = frozenset(
    {"enabled", "index_manifest", "embedding_assets", "top_k"}
)


@dataclass(frozen=True)
class _OptimizationCliOptions:
    model: str
    task_type: str
    template_name: str
    question: str
    pricing: dict[str, Any] | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    similarity_threshold: float
    remove_boilerplate: bool
    remove_near_duplicates: bool
    allow_external_knowledge: bool
    constraints: list[str]


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
    """Clean, dedupe, and structure context before a downstream LLM call."""


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


def _validate_template(template_name: str) -> None:
    if template_name not in available_templates():
        _fail(
            f"unknown template {template_name!r}. Available: {', '.join(available_templates())}.",
            code=2,
        )


def _resolve_optimization_options(
    *,
    question: str | None,
    model: str | None,
    max_input_tokens: int | None,
    max_output_tokens: int | None,
    task_type: str | None,
    constraint: list[str] | None,
    pricing: str | None,
    config: str | None,
    template: str | None,
    no_boilerplate: bool,
    no_near_dedup: bool,
    allow_external_knowledge: bool,
    validate_template: bool = True,
) -> _OptimizationCliOptions:
    cfg = _load_config(config)

    # Config supplies defaults; explicit CLI flags override (None means "not provided").
    effective_model = str(model or cfg.get("model") or "gpt-4.1")
    effective_task = str(task_type or cfg.get("task_type") or "general")
    effective_template = str(template or cfg.get("template") or "default")
    question_value = question if question is not None else cfg.get("question", "")
    effective_question = str(question_value or "")
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

    constraints = [str(item) for item in (cfg.get("constraints") or [])]
    if constraint:
        constraints.extend(constraint)

    if validate_template:
        _validate_template(effective_template)

    pricing_doc: dict[str, Any] | None = None
    if effective_pricing:
        try:
            pricing_doc = load_pricing(str(effective_pricing))
        except (FileNotFoundError, ValueError) as exc:
            _fail(str(exc))

    return _OptimizationCliOptions(
        model=effective_model,
        task_type=effective_task,
        template_name=effective_template,
        question=effective_question,
        pricing=pricing_doc,
        max_input_tokens=effective_max_in,
        max_output_tokens=effective_max_out,
        similarity_threshold=similarity,
        remove_boilerplate=remove_boilerplate,
        remove_near_duplicates=remove_near,
        allow_external_knowledge=allow_external,
        constraints=constraints,
    )


def _optimization_request(raw: str, options: _OptimizationCliOptions) -> OptimizationRequest:
    return OptimizationRequest(
        raw_text=raw,
        question=options.question,
        model=options.model,
        task_type=options.task_type,
        constraints=options.constraints,
        max_output_tokens=options.max_output_tokens,
        max_input_tokens=options.max_input_tokens,
        allow_external_knowledge=options.allow_external_knowledge,
        remove_boilerplate=options.remove_boilerplate,
        remove_near_duplicates=options.remove_near_duplicates,
        similarity_threshold=options.similarity_threshold,
        template_name=options.template_name,
        pricing=options.pricing,
    )


def _inspection_request(
    raw: str,
    *,
    source_type: str,
    options: _OptimizationCliOptions,
) -> InspectionRequest:
    return InspectionRequest(
        raw_text=raw,
        source_type=source_type,
        model=options.model,
        pricing=options.pricing,
        remove_boilerplate=options.remove_boilerplate,
        remove_near_duplicates=options.remove_near_duplicates,
        similarity_threshold=options.similarity_threshold,
    )


def _guard_prepare_output_paths(
    input_path: str,
    *,
    output_path: Path | None,
    report_path: Path | None,
) -> None:
    if input_path == "-":
        return
    input_file = Path(input_path)
    if output_path is not None and _same_existing_or_resolved_path(input_file, output_path):
        _fail("--output must not point to the input file; prepare never overwrites its input.")
    if report_path is not None and _same_existing_or_resolved_path(input_file, report_path):
        _fail("--report must not point to the input file; prepare never overwrites its input.")


def _write_prepare_report(
    *,
    inspection_report: Any,
    selection_report: Any,
    optimization_report: Any,
    path: Path,
) -> None:
    payload = {
        "schema_version": PREPARE_SCHEMA_VERSION,
        "tool_version": __version__,
        "inspection": inspection_to_dict(inspection_report),
        "selection": asdict(selection_report),
        "optimization": report_to_dict(optimization_report),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
        help="Add prompt guidance allowing labelled downstream outside knowledge.",
    ),
) -> None:
    """Clean, deduplicate, and structure INPUT into an optimized prompt and JSON report."""
    raw = _read_input(input_path)
    options = _resolve_optimization_options(
        question=question,
        model=model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        task_type=task_type,
        constraint=constraint,
        pricing=pricing,
        config=config,
        template=template,
        no_boilerplate=no_boilerplate,
        no_near_dedup=no_near_dedup,
        allow_external_knowledge=allow_external_knowledge,
    )
    result = run_pipeline(_optimization_request(raw, options))

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


@app.command("prepare")
def prepare_command(
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
        None, "--output", "-o", help="Write the optimized prompt here when generated."
    ),
    report_path: Path | None = typer.Option(
        None,
        "--report",
        "-r",
        help="Write the inspection report on skip, or prepare report when optimized.",
    ),
    pricing: str | None = typer.Option(
        None, "--pricing", help="Path to a pricing YAML file (default: built-in examples)."
    ),
    config: str | None = typer.Option(
        None, "--config", help="Path to a YAML config file providing defaults."
    ),
    template: str | None = typer.Option(
        None, "--template", help="Prompt template name when optimization runs (default: default)."
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
        help="Add prompt guidance allowing labelled downstream outside knowledge when optimized.",
    ),
) -> None:
    """Inspect INPUT first, then generate a prompt only when safe optimization is useful.

    ``prepare`` is deterministic orchestration over ``inspect`` and ``optimize``. It runs
    question-aware lexical selection only after an optimize recommendation. It does not
    summarize, rewrite, or paraphrase source content, and adds no semantic selection,
    embeddings, network access, local model call, or remote LLM call. On ``skip`` or
    ``manual_review`` recommendations it emits an inspection report and generates no prompt.
    On ``optimize_safe`` or ``optimize_with_flags`` it runs the existing safe optimization
    pipeline over deterministic lexical selection output and writes a prepare report when
    requested.
    """
    raw = _read_input(input_path)
    _guard_prepare_output_paths(input_path, output_path=output_path, report_path=report_path)
    options = _resolve_optimization_options(
        question=question,
        model=model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        task_type=task_type,
        constraint=constraint,
        pricing=pricing,
        config=config,
        template=template,
        no_boilerplate=no_boilerplate,
        no_near_dedup=no_near_dedup,
        allow_external_knowledge=allow_external_knowledge,
        validate_template=False,
    )
    source_type = "stdin" if input_path == "-" else "file"
    inspection_report = run_inspection(
        _inspection_request(raw, source_type=source_type, options=options)
    )

    action = inspection_report.recommendation.action
    if action not in _OPTIMIZE_RECOMMENDATION_ACTIONS:
        if report_path is not None:
            try:
                write_inspection_report(inspection_report, report_path)
            except OSError as exc:
                _fail(f"could not write report to {report_path}: {exc}")
        else:
            sys.stdout.write(inspection_to_json(inspection_report) + "\n")
        _print_prepare_skip_summary(inspection_report, output_path, report_path)
        return

    _validate_template(options.template_name)
    err_console.print(f"Inspection decision: {action}")
    selection = select_chunks_for_question(
        raw_text=raw,
        question=options.question,
        chunk_inventory=inspection_report.chunk_inventory,
    )
    if selection.applied:
        err_console.print(
            "Lexical selection: "
            f"kept {selection.report.selected_chunk_count}/"
            f"{selection.report.source_chunk_count} chunks."
        )
    else:
        err_console.print(f"Lexical selection: not applied ({selection.report.reason}).")

    result = run_pipeline(_optimization_request(selection.selected_text, options))

    if output_path is not None:
        try:
            output_path.write_text(result.prompt, encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write prompt to {output_path}: {exc}")
    else:
        sys.stdout.write(result.prompt)

    if report_path is not None:
        try:
            _write_prepare_report(
                inspection_report=inspection_report,
                selection_report=selection.report,
                optimization_report=result.report,
                path=report_path,
            )
        except OSError as exc:
            _fail(f"could not write report to {report_path}: {exc}")

    _print_summary(result.report, output_path, report_path)


def _print_prepare_skip_summary(
    report: Any,
    output_path: Path | None,
    report_path: Path | None,
) -> None:
    err_console.print(
        f"No prompt generated: inspection recommended {report.recommendation.action}."
    )
    _print_inspect_summary(report, report_path, "compact")
    if output_path is not None:
        err_console.print(f"Prompt not written to: [green]{output_path}[/green]")


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
    """Report mechanical optimization and prepare-selection metrics for benchmark cases.

    Measures deterministic mechanical behavior (token savings, compression, marker
    preservation, exact-vs-approximate counting, prepare action, and selection state) -- not
    LLM answer quality. Exits non-zero if any case fails its thresholds or the path is
    invalid.
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


def _semantic_path_from_config(section: dict[str, Any], key: str) -> Path | None:
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, str) or not value.strip():
        _fail(f"config key semantic_retrieval.{key} must be a path string", code=2)
    return Path(str(value))


def _semantic_top_k_from_config(section: dict[str, Any]) -> int:
    value = section.get("top_k", 8)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail("config key semantic_retrieval.top_k must be a positive integer", code=2)
    return value


def _validate_semantic_config_keys(section: dict[str, Any]) -> None:
    for key in section:
        if key not in _SEMANTIC_RETRIEVAL_CONFIG_KEYS:
            _fail(f"unsupported config key semantic_retrieval.{key}", code=2)


def _semantic_enabled_from_config(section: dict[str, Any]) -> bool:
    if "enabled" not in section:
        return False
    value = section["enabled"]
    if not isinstance(value, bool):
        _fail("config key semantic_retrieval.enabled must be a boolean", code=2)
    return value


@app.command("semantic-retrieval")
def semantic_retrieval_command(
    enable_semantic_retrieval: bool = typer.Option(
        False,
        "--enable-semantic-retrieval",
        help="Opt in to the Phase 2 semantic retrieval boundary scaffold.",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Explicitly request the future semantic retrieval execution boundary.",
    ),
    source_path: str | None = typer.Option(
        None,
        "--source",
        help="Source text path required with --execute, or '-' for stdin.",
    ),
    question: str | None = typer.Option(
        None,
        "--question",
        help="Question required with --execute.",
    ),
    adapter_name: str = typer.Option(
        LOCAL_INDEX_V1_ADAPTER,
        "--adapter",
        help="Future execution adapter name. Only local_index_v1 is recognized.",
    ),
    index_manifest_path: Path | None = typer.Option(
        None,
        "--index-manifest",
        help="Local semantic index manifest required when semantic retrieval is enabled.",
    ),
    embedding_assets_dir: Path | None = typer.Option(
        None,
        "--embedding-assets",
        help="Local embedding asset directory required when semantic retrieval is enabled.",
    ),
    top_k: int | None = typer.Option(
        None,
        "--top-k",
        help="Future retrieval result limit; must be greater than 0.",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        help="Path to a YAML config file with a semantic_retrieval mapping.",
    ),
    report_path: Path | None = typer.Option(
        None,
        "--report",
        "-r",
        help="Write the boundary status report here (otherwise stdout).",
    ),
) -> None:
    """Report the Phase 2 semantic retrieval boundary status; no retrieval is performed.

    This command is a disabled-by-default opt-in scaffold (ADR 0011). It does not retrieve,
    rank, select, embed, summarize, rewrite, paraphrase, call a model, touch the network, or
    build a prompt. When explicitly enabled, it validates local artifact presence and then
    exits non-zero because retrieval execution is intentionally not implemented yet.
    """

    cfg = _load_config(config)
    semantic_cfg = cfg.get("semantic_retrieval", {})
    if semantic_cfg is None:
        semantic_cfg = {}
    if not isinstance(semantic_cfg, dict):
        _fail("config key semantic_retrieval must be a mapping", code=2)
    _validate_semantic_config_keys(semantic_cfg)

    effective_enabled = enable_semantic_retrieval or _semantic_enabled_from_config(semantic_cfg)
    effective_index_manifest = index_manifest_path or _semantic_path_from_config(
        semantic_cfg, "index_manifest"
    )
    effective_embedding_assets = embedding_assets_dir or _semantic_path_from_config(
        semantic_cfg, "embedding_assets"
    )
    effective_top_k = top_k if top_k is not None else _semantic_top_k_from_config(semantic_cfg)

    if execute:
        source_text = _read_input(source_path) if source_path is not None else None
        execution_report = semantic_retrieval_execution_report(
            SemanticRetrievalExecutionRequest(
                enabled=effective_enabled,
                adapter_name=adapter_name,
                source_text=source_text,
                question=question,
                index_manifest_path=effective_index_manifest,
                embedding_assets_dir=effective_embedding_assets,
                top_k=effective_top_k,
            )
        )
        payload = json.dumps(asdict(execution_report), indent=2, ensure_ascii=False) + "\n"
        if report_path is not None:
            try:
                report_path.write_text(payload, encoding="utf-8")
            except OSError as exc:
                _fail(f"could not write report to {report_path}: {exc}")
        else:
            sys.stdout.write(payload)
        err_console.print(f"[red]Error:[/red] {execution_report.message}")
        raise typer.Exit(code=1)

    try:
        boundary_report = semantic_retrieval_boundary_report(
            SemanticRetrievalConfig(
                enabled=effective_enabled,
                index_manifest_path=effective_index_manifest,
                embedding_assets_dir=effective_embedding_assets,
                top_k=effective_top_k,
            )
        )
    except SemanticRetrievalBoundaryError as exc:
        _fail(str(exc))

    payload = json.dumps(asdict(boundary_report), indent=2, ensure_ascii=False) + "\n"
    if report_path is not None:
        try:
            report_path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write report to {report_path}: {exc}")
    else:
        sys.stdout.write(payload)

    if boundary_report.status == "blocked":
        err_console.print(f"[red]Error:[/red] {boundary_report.message}")
        raise typer.Exit(code=1)


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
    summary: str = typer.Option(
        "table",
        "--summary",
        help="Human summary style: 'table' or 'compact'. JSON output is unchanged.",
    ),
) -> None:
    """Analyze INPUT and emit a deterministic diagnostic report -- no prompt is generated.

    Reports the token, structure, duplication, cleanup, and cost profile of INPUT and projects
    what ``lcc optimize``'s safe cleaning would remove, to help you decide whether to optimize.
    It is diagnostic only (ADR 0009): it never builds or writes an optimized prompt, makes no
    network, LLM, embedding, local model, or remote model call, and never modifies the input
    file. The JSON report goes to ``--report`` (or stdout); the human-readable summary and
    warnings go to stderr.
    """
    source_type = "stdin" if input_path == "-" else "file"
    if summary not in {"table", "compact"}:
        _fail("unknown --summary value. Use 'table' or 'compact'.", code=2)
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

    _print_inspect_summary(report, report_path, summary)


def _print_inspect_summary(report: Any, report_path: Path | None, summary: str) -> None:
    if summary == "compact":
        for line in compact_summary_lines(report):
            err_console.print(line)
        if report_path is not None:
            err_console.print(f"Report written to: [green]{report_path}[/green]")
        if report.warnings:
            body = "\n".join(f"- {warning}" for warning in report.warnings)
            err_console.print(Panel(body, title="Warnings", border_style="yellow", expand=False))
        return

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


@app.command(name="intake")
def intake_cmd(
    input_source: str = typer.Argument(
        ...,
        help="Input text, file path, or '-' for stdin.",
        show_default=False,
    ),
    question: str = typer.Option(
        "",
        "--question",
        "-q",
        help="Specific question or objective (optional; inferred if omitted).",
    ),
    model: str = typer.Option(
        "claude-sonnet-5",
        "--model",
        "-m",
        help="Target model for token budgeting and cost calculation.",
    ),
    template: str = typer.Option(
        "claude_xml",
        "--template",
        "-t",
        help="Prompt template to apply (claude_xml, code_agent, structured_markdown, default).",
    ),
    output_format: str = typer.Option(
        "markdown",
        "--format",
        "-f",
        help="Output format: markdown, json, or toon.",
    ),
    output_path: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the structured/compiled prompt to this file instead of stdout.",
    ),
    report_path: Path | None = typer.Option(
        None,
        "--report",
        "-r",
        help="Write the complete intake report JSON to this file.",
    ),
) -> None:
    """Analyze raw, unstructured, or voice prompt input, structure intent, and compile with LCC."""
    from lcc.intake import LccIntake, ReadinessState

    # Determine if input_source is a file or direct string
    if input_source == "-":
        raw_text = sys.stdin.read()
    elif Path(input_source).exists() and not Path(input_source).is_dir():
        raw_text = Path(input_source).read_text(encoding="utf-8")
    else:
        raw_text = input_source

    pipeline = LccIntake(
        model=model,
        template_name=template,
        optimize_context=True,
    )
    result = pipeline.process(
        raw_input=raw_text,
        question=question,
        output_format=output_format,
    )

    # Output formatted prompt
    if output_path is not None:
        try:
            output_path.write_text(result.formatted_prompt, encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write prompt to {output_path}: {exc}")
    else:
        sys.stdout.write(result.formatted_prompt + "\n")

    # Output JSON report if requested
    if report_path is not None:
        report_data = {
            "readiness": result.parsed.readiness.value,
            "readiness_score": result.parsed.readiness_score,
            "ambiguity_score": result.parsed.ambiguity_score,
            "intent": result.parsed.intent,
            "questions": result.parsed.questions,
            "assumptions": result.parsed.assumptions,
            "brief": asdict(result.parsed.brief),
            "compression": asdict(result.compression) if result.compression else None,
        }
        try:
            report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write report to {report_path}: {exc}")

    # Rich summary display on stderr
    readiness = result.parsed.readiness
    badge_style = "green" if readiness == ReadinessState.READY_TO_EXECUTE else "yellow" if readiness == ReadinessState.NEEDS_LIGHT_REFINEMENT else "magenta" if readiness == ReadinessState.NEEDS_INTAKE else "red"

    table = Table(title="lcc -- prompt intake & context compilation", show_header=False, box=None, pad_edge=False)
    table.add_column("field", style="bold cyan", no_wrap=True)
    table.add_column("value")

    table.add_row("Readiness Status", f"[{badge_style}]{readiness.value}[/{badge_style}]")
    table.add_row("Readiness Score", f"{result.parsed.readiness_score}/100")
    table.add_row("Ambiguity Score", f"{result.parsed.ambiguity_score}/100")
    table.add_row("Target Model", model)
    table.add_row("Template", template)

    if result.compression:
        table.add_row("Original Tokens", str(result.compression.original_tokens))
        table.add_row("Compiled Tokens", str(result.compression.compressed_tokens))
        table.add_row("Token Savings", f"[green]{result.compression.savings_percentage}%[/green]")

    err_console.print(table)

    if result.parsed.assumptions:
        assump_text = "\n".join(f"- {a}" for a in result.parsed.assumptions)
        err_console.print(Panel(assump_text, title="Assumptions", border_style="yellow", expand=False))

    if result.parsed.questions:
        q_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(result.parsed.questions))
        err_console.print(Panel(q_text, title="Clarifying Questions Needed", border_style="magenta", expand=False))

    if output_path is not None:
        err_console.print(f"Compiled prompt written to: [green]{output_path}[/green]")
    if report_path is not None:
        err_console.print(f"Intake report written to: [green]{report_path}[/green]")



def cli_main() -> None:
    """Console-script entry point (``lcc``)."""
    app()


if __name__ == "__main__":
    cli_main()
