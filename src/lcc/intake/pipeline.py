"""Unified Intake Pipeline composing Intake parsing and LCC Context Optimization."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from lcc.compressor import CompressionResult, LccCompressor
from lcc.intake.parser import ParsedIntake, ReadinessState, parse_intake
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
        from lcc.cleaning import clean_speech_transcript, is_speech_transcript

        input_text = (
            clean_speech_transcript(raw_input) if is_speech_transcript(raw_input) else raw_input
        )
        parsed = parse_intake(input_text)
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
                constraints=extra_constraints or parsed.brief.constraints,
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
                "assumptions": parsed.assumptions,
                "questions": parsed.questions,
                "brief": asdict(parsed.brief),
                "payload": cleaned_text,
            }
            formatted_prompt = json.dumps(json_data, indent=2)
        else:
            # Build using registered prompt template
            rendered = build_prompt(spec, template_name=self.template_name)
            header_comments = [
                "<!-- lcc-intake:readiness "
                f'status="{parsed.readiness.value}" score="{parsed.readiness_score}" -->'
            ]
            if parsed.assumptions:
                header_comments.append(f"<!-- assumptions: {'; '.join(parsed.assumptions)} -->")
            if parsed.questions:
                header_comments.append(
                    f"<!-- clarifying_questions: {'; '.join(parsed.questions)} -->"
                )
            formatted_prompt = "\n".join(header_comments) + "\n\n" + rendered

        return IntakeResult(
            raw_input=raw_input,
            parsed=parsed,
            compression=compression_result,
            formatted_prompt=formatted_prompt,
            output_format=output_format,
            relevance=relevance_result,
        )


IntakePipeline = LccIntake


def process_intake(
    raw_input: str, model: str = "claude-sonnet-5", template: str = "claude_xml"
) -> IntakeResult:
    """Convenience helper to run unified intake in a single function call."""
    pipeline = LccIntake(model=model, template_name=template)
    return pipeline.process(raw_input)
