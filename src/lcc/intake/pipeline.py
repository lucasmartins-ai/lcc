"""Unified Intake Pipeline composing Intake parsing and LCC Context Optimization."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from lcc.compressor import CompressionResult, LccCompressor
from lcc.intake.parser import ParsedIntake, ReadinessState, parse_intake
from lcc.intake.speech import DictationClean, DictationDetection, clean_dictation, detect_dictation
from lcc.prompt_builder import PromptSpec, build_prompt
from lcc.toon import encode_toon

if TYPE_CHECKING:
    from lcc.relevance import RelevanceCompactionResult


@dataclass
class IntakeResult:
    """Unified result containing intake readiness, brief, LCC compression, and rendered prompt."""

    raw_input: str
    parsed: ParsedIntake
    compression: CompressionResult | None
    formatted_prompt: str
    output_format: str
    relevance: RelevanceCompactionResult | None = None
    dictation: DictationDetection | None = None
    #: Filler/transcript removals with exact spans in ``raw_input``; ``None`` when not dictation.
    speech_cleaning: DictationClean | None = None


def speech_receipt(result: IntakeResult) -> dict[str, Any]:
    """JSON-ready receipt of the dictation detection and every removed span."""
    detection = result.dictation
    cleaning = result.speech_cleaning
    return {
        "detected": bool(detection and detection.detected),
        "reasons": list(detection.reasons) if detection else [],
        "removed_spans": len(cleaning.removals) if cleaning else 0,
        "removed_chars": cleaning.removed_chars if cleaning else 0,
        "counts": cleaning.counts() if cleaning else {},
        "removals": [asdict(r) for r in cleaning.removals] if cleaning else [],
    }


def _intake_block(parsed: ParsedIntake, cleaning: DictationClean | None) -> str:
    """Per-request intake metadata, rendered after the prompt so the template prefix is static."""
    lines = [
        "<!-- lcc-intake:readiness "
        f'status="{parsed.readiness.value}" score="{parsed.readiness_score}"'
        + (f' reasons="{",".join(parsed.reasons)}"' if parsed.reasons else "")
        + " -->"
    ]
    if parsed.risk_flags:
        lines.append(f"<!-- risk_flags: {', '.join(parsed.risk_flags)} -->")
    if cleaning is not None and cleaning.removals:
        lines.append(
            f"<!-- speech_cleaning: removed {len(cleaning.removals)} span(s), "
            f"{cleaning.removed_chars} chars; spans in the intake report -->"
        )
    if parsed.assumptions:
        lines.append(f"<!-- assumptions: {'; '.join(parsed.assumptions)} -->")
    if parsed.questions:
        lines.append(f"<!-- clarifying_questions: {'; '.join(parsed.questions)} -->")
    return "\n".join(lines)


class LccIntake:
    """High-level unified pipeline for prompt intake and context compilation."""

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        template_name: str = "claude_xml",
        optimize_context: bool = True,
        max_tokens: int | None = None,
        strategy: str = "local-first",
        enable_relevance: bool = False,
        relevance_threshold: float = 0.4,
        relevance_provider: str = "auto",
        relevance_client: Any | None = None,
    ) -> None:
        self.model = model
        self.template_name = template_name
        self.optimize_context = optimize_context
        self.max_tokens = max_tokens
        self.strategy = strategy
        self.enable_relevance = enable_relevance
        self.relevance_threshold = relevance_threshold
        self.relevance_provider = relevance_provider
        self.relevance_client = relevance_client
        self.compressor = LccCompressor(
            model=model,
            strategy=strategy,
            max_tokens=max_tokens,
            template_name=template_name,
            # Intake cleans speech itself and reports every span; the shared cleaner does not.
            clean_speech=False,
        )

    def parse(self, raw_input: str) -> ParsedIntake:
        """Parse raw input readiness and brief without compressing."""
        return parse_intake(raw_input)

    def process(
        self,
        raw_input: str,
        question: str = "",
        output_format: str = "markdown",
        extra_constraints: list[str] | None = None,
    ) -> IntakeResult:
        """Execute full intake & LCC compilation pipeline."""
        detection = detect_dictation(raw_input)
        cleaning = clean_dictation(raw_input) if detection.detected else None
        input_text = cleaning.text if cleaning else raw_input
        parsed = parse_intake(input_text, dictation=detection.detected)
        relevance_result: RelevanceCompactionResult | None = None
        if self.enable_relevance and parsed.readiness != ReadinessState.BLOCKED:
            from lcc.relevance import RelevanceCompactionRequest, compact_context

            relevance_result = compact_context(
                RelevanceCompactionRequest(
                    text=input_text,
                    question=question or parsed.brief.objective,
                    threshold=self.relevance_threshold,
                    provider=self.relevance_provider,
                    client=self.relevance_client,
                )
            )
        source_text = relevance_result.compacted_text if relevance_result else input_text
        cleaned_text = source_text
        compression_result: CompressionResult | None = None

        if self.optimize_context and parsed.readiness != ReadinessState.BLOCKED:
            compression_result = self.compressor.compress(
                raw_text=source_text,
                question=question or parsed.brief.objective,
                task_type="intake-refinement",
                constraints=extra_constraints or [],
            )
            cleaned_text = compression_result.compressed_text

        constraints = list(parsed.brief.constraints)
        if extra_constraints:
            constraints.extend(extra_constraints)

        spec = PromptSpec(
            question=question or parsed.brief.objective,
            context=cleaned_text,
            task_type="intake-refinement",
            constraints=constraints,
            format_requirements=parsed.brief.format_requirements,
        )

        if output_format == "toon":
            toon_data: dict[str, Any] = {
                "readiness": parsed.readiness.value,
                "readiness_score": parsed.readiness_score,
                "reasons": parsed.reasons,
                "risk_flags": parsed.risk_flags,
                "assumptions": parsed.assumptions,
                "questions": parsed.questions,
                "payload": cleaned_text,
            }
            formatted_prompt = encode_toon(toon_data, root_name="intake")
        elif output_format == "json":
            json_data = {
                "readiness": parsed.readiness.value,
                "readiness_score": parsed.readiness_score,
                "intent": parsed.intent,
                "reasons": parsed.reasons,
                "risk_flags": parsed.risk_flags,
                "ask_count": parsed.ask_count,
                "assumptions": parsed.assumptions,
                "questions": parsed.questions,
                "brief": asdict(parsed.brief),
                "payload": cleaned_text,
            }
            formatted_prompt = json.dumps(json_data, indent=2)
        else:
            # Static template first, per-request intake metadata last: a cache can only reuse
            # a byte-identical prefix (docs/CACHE_ALIGNMENT.md).
            rendered = build_prompt(spec, template_name=self.template_name)
            formatted_prompt = rendered + "\n" + _intake_block(parsed, cleaning)

        return IntakeResult(
            raw_input=raw_input,
            parsed=parsed,
            compression=compression_result,
            formatted_prompt=formatted_prompt,
            output_format=output_format,
            relevance=relevance_result,
            dictation=detection,
            speech_cleaning=cleaning,
        )


IntakePipeline = LccIntake


def process_intake(
    raw_input: str, model: str = "claude-sonnet-5", template: str = "claude_xml"
) -> IntakeResult:
    """Convenience helper to run unified intake in a single function call."""
    pipeline = LccIntake(model=model, template_name=template)
    return pipeline.process(raw_input)
