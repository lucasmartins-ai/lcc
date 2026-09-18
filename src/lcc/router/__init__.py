"""LCC Hybrid Routing and Quality Verification Engine."""

from lcc.router.config import (
    ModelConfig,
    PolicyConfig,
    RouterPolicyConfig,
    load_model_config,
    load_policy,
)
from lcc.router.context_adapter import inspect_context, optimize_context_if_needed, prepare_context
from lcc.router.features import extract_features
from lcc.router.policy import RoutePlan, choose_route
from lcc.router.router import LCCRouter, final_answer_to_dict
from lcc.router.schemas import (
    AgentHealth,
    EvaluationResult,
    FinalAnswer,
    LCCReportSummary,
    LocalAnswer,
    ModelFamily,
    PreparedContext,
    RemoteAnswer,
    RouteDecision,
    TaskFeatures,
    TaskInput,
    VerificationDecision,
    VerificationResult,
)

__all__ = [
    "LCCRouter",
    "final_answer_to_dict",
    "load_policy",
    "load_model_config",
    "PolicyConfig",
    "ModelConfig",
    "RouterPolicyConfig",
    "extract_features",
    "choose_route",
    "RoutePlan",
    "inspect_context",
    "prepare_context",
    "optimize_context_if_needed",
    "RouteDecision",
    "VerificationDecision",
    "ModelFamily",
    "AgentHealth",
    "TaskInput",
    "LCCReportSummary",
    "TaskFeatures",
    "LocalAnswer",
    "VerificationResult",
    "RemoteAnswer",
    "FinalAnswer",
    "EvaluationResult",
    "PreparedContext",
]
