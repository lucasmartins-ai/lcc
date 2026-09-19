"""Opt-in Laya local semantic decision backend for relevance compaction (ADR 0015).

Attribution & Licensing Notice:
-------------------------------
Laya is a fast, non-autoregressive System 1 decision engine developed by
NandhaKishorM / Convai Innovations and licensed under the Apache License 2.0.
Source repository: https://github.com/NandhaKishorM/laya
Models: convaiinnovations/laya, convaiinnovations/laya-multilingual,
        convaiinnovations/laya-typed-decisions (Apache 2.0)

LCC integrates Laya as an optional local semantic decision backend. LCC is an
independent project and is not endorsed by nor affiliated with the author of Laya.

Research Hypothesis:
--------------------
Can LCC's context compilation reduce a large context to a sufficiently small
decision-relevant representation that a local ~1K-context Laya model can make
useful semantic decisions without requiring a 32K-context remote decision model?
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from lcc.relevance.provider import UnsupportedOperationError
from lcc.token_budget import count_tokens

__all__ = [
    "DEFAULT_LAYA_MODEL",
    "HEAD_RESERVATION_TOKENS",
    "LayaClient",
    "LayaContextLimitExceededError",
    "LayaError",
    "LayaExecutionError",
    "LayaModelNotFoundError",
    "LayaUnavailableError",
    "get_laya_context_limit",
    "serialize_state",
]

DEFAULT_LAYA_MODEL = "convaiinnovations/laya-multilingual"
HEAD_RESERVATION_TOKENS = 192  # Default head token budget reserved for questions, rubrics, markers

KNOWN_CONTEXT_LIMITS: dict[str, int] = {
    "convaiinnovations/laya": 512,
    "convaiinnovations/laya-multilingual": 1024,
    "convaiinnovations/laya-typed-decisions": 1024,
    "laya": 512,
    "laya-multilingual": 1024,
    "laya-typed-decisions": 1024,
}


class LayaError(RuntimeError):
    """Base error for Laya provider failures."""


class LayaUnavailableError(LayaError):
    """Laya dependencies (torch, transformers, laya) are not installed."""


class LayaModelNotFoundError(LayaError):
    """Laya model checkpoint weights or configuration files were not found."""


class LayaContextLimitExceededError(LayaError):
    """Context exceeds Laya's verified context window limit without naive truncation."""

    def __init__(
        self,
        raw_tokens: int,
        compacted_tokens: int,
        limit: int,
        message: str | None = None,
    ) -> None:
        self.raw_tokens = raw_tokens
        self.compacted_tokens = compacted_tokens
        self.limit = limit
        default_msg = (
            f"context tokens ({compacted_tokens}) exceed Laya's context limit ({limit}) "
            f"even after LCC progressive compaction. Raw context was {raw_tokens} tokens. "
            f"LCC will not naively truncate semantically important content."
        )
        super().__init__(message or default_msg)


class LayaExecutionError(LayaError):
    """Error during local Laya model inference."""


def serialize_state(state: str | dict | list) -> str:
    """Serialize input state to string format for token counting and inference."""
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False)


def get_laya_context_limit(model_id_or_path: str) -> int:
    """Determine the maximum context token limit for a Laya checkpoint."""
    # 1. Direct match in known catalog
    norm = model_id_or_path.strip().rstrip("/")
    if norm in KNOWN_CONTEXT_LIMITS:
        return KNOWN_CONTEXT_LIMITS[norm]

    # 2. Check local directory config if present
    local_path = Path(model_id_or_path).expanduser()
    if local_path.is_dir():
        cfg_file = local_path / "rl_agent_config.json"
        if cfg_file.is_file():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                if "max_len" in cfg and isinstance(cfg["max_len"], int):
                    return cfg["max_len"]
            except Exception:
                pass

    # 3. Infer from checkpoint naming cues
    name_lower = norm.lower()
    if "512" in name_lower:
        return 512
    if "1024" in name_lower or "multilingual" in name_lower or "typed-decisions" in name_lower:
        return 1024
    if name_lower.endswith("laya"):
        return 512

    return 1024


class LayaClient:
    """Local System 1 decision client using Laya with strict context budgeting."""

    def __init__(
        self,
        model: str | None = None,
        *,
        device: str | None = None,
        context_limit: int | None = None,
        head_reservation: int = HEAD_RESERVATION_TOKENS,
        offline: bool = False,
        agent: Any | None = None,  # test seam / dependency injection
    ) -> None:
        self.model = model or os.environ.get("LCC_LAYA_MODEL", DEFAULT_LAYA_MODEL)
        self.device = device or os.environ.get("LCC_LAYA_DEVICE")
        self.context_limit = context_limit or get_laya_context_limit(self.model)
        self.head_reservation = head_reservation
        self.offline = offline or (os.environ.get("LCC_DISABLE_NETWORK") == "1")
        if self.offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        self.last_resolved_model: str = self.model
        self._agent = agent
        self._initialized = False

    @property
    def available_state_tokens(self) -> int:
        """Remaining tokens available for state content after reserving head tokens."""
        return max(16, self.context_limit - self.head_reservation - 1)

    def _ensure_agent(self) -> None:
        """Lazily load the Laya agent if not provided via injection."""
        if self._agent is not None:
            return

        # Check offline / network kill-switch
        if self.offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

        try:
            import laya
        except ImportError as exc:
            raise LayaUnavailableError(
                "Laya or PyTorch dependencies are not installed. "
                "Install them with: pip install 'local-context-compiler[laya]' "
                "or: pip install laya torch transformers"
            ) from exc

        # Check local path existence if a path was passed
        is_path = (
            self.model.startswith(("/", "./", "../", "~"))
            or Path(self.model).expanduser().exists()
        )
        if is_path:
            expanded = str(Path(self.model).expanduser())
            if not os.path.isdir(expanded):
                raise LayaModelNotFoundError(
                    f"Local Laya model directory not found: {self.model!r}. "
                    "Ensure the directory exists and contains model.safetensors "
                    "and rl_agent_config.json."
                )
            load_target = expanded
        else:
            load_target = self.model

        try:
            self._agent = laya.load(load_target, device=self.device)
            self._initialized = True
        except FileNotFoundError as exc:
            raise LayaModelNotFoundError(
                f"Laya model weights not found for {self.model!r}: {exc}. "
                f"Download weights using 'laya' or set LCC_LAYA_MODEL to a valid checkpoint."
            ) from exc
        except Exception as exc:
            raise LayaExecutionError(
                f"Failed to initialize Laya agent for {self.model!r}: {exc}"
            ) from exc

    def estimate_state_tokens(self, state: str | dict | list) -> int:
        """Estimate token count for a state payload using LCC's token budget tools."""
        serialized = serialize_state(state)
        return count_tokens(serialized, "gpt-4.1").value

    def validate_context_budget(
        self,
        state: str | dict | list,
        raw_tokens: int | None = None,
    ) -> int:
        """Verify that state tokens fit within Laya's context window.

        Raises LayaContextLimitExceededError if state exceeds the available budget.
        Returns the counted state tokens.
        """
        state_tokens = self.estimate_state_tokens(state)
        available = self.available_state_tokens
        if state_tokens > available:
            raw = raw_tokens if raw_tokens is not None else state_tokens
            raise LayaContextLimitExceededError(
                raw_tokens=raw,
                compacted_tokens=state_tokens,
                limit=self.context_limit,
            )
        return state_tokens

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        """Evaluate typed questions over state using local Laya inference.

        Checks operation support, enforces context limit without naive truncation,
        executes the forward pass, and preserves calibrated probabilities and confidence.
        """
        # 1. Validate question operations
        for qid, qdef in questions.items():
            if not isinstance(qdef, dict) or "type" not in qdef:
                raise UnsupportedOperationError(f"Question {qid!r} is missing 'type' specification")
            qtype = qdef["type"]
            if qtype not in ("noul", "choice", "score"):
                raise UnsupportedOperationError(
                    f"Laya does not support question type {qtype!r} for question {qid!r}. "
                    "Supported operations: 'noul' (binary probability), "
                    "'choice' (categorical), 'score' (ordinal)."
                )

        # 2. Enforce context window without naive truncation
        self.validate_context_budget(state)

        # 3. Ensure agent is initialized
        self._ensure_agent()
        assert self._agent is not None, "Agent initialization failed"

        # 4. Run local inference
        started = time.perf_counter()
        try:
            raw_result = self._agent.predict(state, questions)
        except Exception as exc:
            raise LayaExecutionError(f"Laya inference failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        # 5. Extract and normalize answers
        raw_answers: dict[str, Any] = {}
        usage: dict[str, Any] = {}
        if isinstance(raw_result, dict):
            extracted_answers = raw_result.get("answers")
            if isinstance(extracted_answers, dict):
                raw_answers = dict(extracted_answers)
            extracted_usage = raw_result.get("usage")
            if isinstance(extracted_usage, dict):
                usage = dict(extracted_usage)

        resolved = raw_result.get("model") if isinstance(raw_result, dict) else self.model
        resolved = resolved or self.model
        if isinstance(resolved, str) and resolved:
            self.last_resolved_model = resolved

        # Ensure every question has normalized output format expected by LCC
        answers: dict[str, Any] = {}
        for qid, qdef in questions.items():
            ans = raw_answers.get(qid)
            if not isinstance(ans, dict):
                ans = {}
            qtype = qdef["type"]
            if qtype == "noul":
                noul_val = ans.get("noul")
                conf_val = ans.get("confidence")
                answers[qid] = {
                    "type": "noul",
                    "noul": float(noul_val) if noul_val is not None else 0.5,
                    "confidence": float(conf_val) if conf_val is not None else 0.5,
                    "action": ans.get("action"),
                }
            elif qtype == "choice":
                answers[qid] = {
                    "type": "choice",
                    "choice": ans.get("choice"),
                    "confidence": ans.get("confidence"),
                    "probabilities": ans.get("probabilities", {}),
                    "action": ans.get("action"),
                }
            elif qtype == "score":
                answers[qid] = {
                    "type": "score",
                    "score": ans.get("score"),
                    "confidence": ans.get("confidence"),
                    "legend": ans.get("legend", {}),
                    "probabilities": ans.get("probabilities", {}),
                    "action": ans.get("action"),
                }

        return {
            "model": self.model,
            "resolved_model": self.last_resolved_model,
            "answers": answers,
            "usage": usage or {"input_tokens": 0, "output_tokens": 0},
            "latency_ms": latency_ms,
            "context_limit": self.context_limit,
        }

    def supports_operation(self, operation: str) -> bool:
        return operation in ("noul", "choice", "score")
