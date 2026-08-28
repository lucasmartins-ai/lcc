"""Configuration loading for the LCC hybrid router and local agents."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RouterPolicyConfig:
    local_first_max_tokens: int = 3500
    compress_if_projected_savings_above: float = 0.12
    remote_direct_if_input_tokens_above: int = 16000
    escalate_if_manual_review: bool = True
    local_accept_confidence: float = 0.82
    strict_format_requires_verification: bool = True
    compress_before_remote: bool = True


@dataclass(frozen=True)
class RiskConfig:
    calculation_keywords: list[str] = field(default_factory=list)
    code_keywords: list[str] = field(default_factory=list)
    strict_format_markers: list[str] = field(default_factory=list)
    external_knowledge_keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyConfig:
    router: RouterPolicyConfig = field(default_factory=RouterPolicyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelConfig:
    local_backend: str = "mock"
    local_model_name: str = "gemma-4-e4b"
    local_endpoint: str = "http://127.0.0.1:11434"
    local_family: str = "auto"
    local_quantization: str = "e4b"
    local_temperature: float = 0.0
    local_max_tokens: int = 2048
    verifier_backend: str = "rule"
    cloud_base_url: str = "https://api.fireworks.ai/inference/v1"
    cloud_model_id: str = "mock-fireworks"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return data


def load_policy(path: str | Path = "configs/router_policy.yaml") -> PolicyConfig:
    data = _read_yaml(Path(path))
    router_data = dict(data.get("router") or {})
    risk_data = dict(data.get("risk") or {})
    return PolicyConfig(
        router=RouterPolicyConfig(
            local_first_max_tokens=int(
                router_data.get("local_first_max_tokens", RouterPolicyConfig.local_first_max_tokens)
            ),
            compress_if_projected_savings_above=float(
                router_data.get(
                    "compress_if_projected_savings_above",
                    RouterPolicyConfig.compress_if_projected_savings_above,
                )
            ),
            remote_direct_if_input_tokens_above=int(
                router_data.get(
                    "remote_direct_if_input_tokens_above",
                    RouterPolicyConfig.remote_direct_if_input_tokens_above,
                )
            ),
            escalate_if_manual_review=bool(
                router_data.get(
                    "escalate_if_manual_review", RouterPolicyConfig.escalate_if_manual_review
                )
            ),
            local_accept_confidence=float(
                router_data.get(
                    "local_accept_confidence", RouterPolicyConfig.local_accept_confidence
                )
            ),
            strict_format_requires_verification=bool(
                router_data.get(
                    "strict_format_requires_verification",
                    RouterPolicyConfig.strict_format_requires_verification,
                )
            ),
            compress_before_remote=bool(
                router_data.get("compress_before_remote", RouterPolicyConfig.compress_before_remote)
            ),
        ),
        risk=RiskConfig(
            calculation_keywords=[str(item) for item in risk_data.get("calculation_keywords", [])],
            code_keywords=[str(item) for item in risk_data.get("code_keywords", [])],
            strict_format_markers=[
                str(item) for item in risk_data.get("strict_format_markers", [])
            ],
            external_knowledge_keywords=[
                str(item) for item in risk_data.get("external_knowledge_keywords", [])
            ],
        ),
    )


def load_model_config(path: str | Path = "configs/models.yaml") -> ModelConfig:
    data = _read_yaml(Path(path))
    local = dict(data.get("local") or {})
    verifier = dict(data.get("verifier") or {})
    cloud = dict(data.get("fireworks") or data.get("cloud") or {})
    return ModelConfig(
        local_backend=os.getenv("LOCAL_MODEL_BACKEND", str(local.get("backend", "mock"))),
        local_model_name=os.getenv(
            "LOCAL_MODEL_NAME", str(local.get("model_name", "gemma-4-e4b"))
        ),
        local_endpoint=os.getenv(
            "LOCAL_MODEL_ENDPOINT", str(local.get("endpoint", "http://127.0.0.1:11434"))
        ),
        local_family=os.getenv("LOCAL_MODEL_FAMILY", str(local.get("family", "auto"))),
        local_quantization=os.getenv(
            "LOCAL_MODEL_QUANTIZATION", str(local.get("quantization", "e4b"))
        ),
        local_temperature=float(
            os.getenv("LOCAL_MODEL_TEMPERATURE", str(local.get("temperature", 0.0)))
        ),
        local_max_tokens=int(
            os.getenv("LOCAL_MODEL_MAX_TOKENS", str(local.get("max_tokens", 2048)))
        ),
        verifier_backend=os.getenv("LOCAL_VERIFIER_BACKEND", str(verifier.get("backend", "rule"))),
        cloud_base_url=os.getenv(
            "CLOUD_BASE_URL",
            os.getenv("FIREWORKS_BASE_URL", str(cloud.get("base_url", "https://api.fireworks.ai/inference/v1"))),
        ),
        cloud_model_id=os.getenv(
            "CLOUD_MODEL_ID",
            os.getenv("FIREWORKS_MODEL_ID", str(cloud.get("model_id", "mock-fireworks"))),
        ),
    )
