from __future__ import annotations

from act2_router.router import LCCRouter
from act2_router.schemas import TaskInput


def test_end_to_end_mock_accepts_simple_local_answer(monkeypatch) -> None:
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    task = TaskInput(
        task_id="simple",
        instruction="What is the deployment status?",
        context="The deployment is complete. Smoke tests passed.",
    )

    final = LCCRouter().run(task)

    assert final.remote_tokens_used == 0
    assert "deployment is complete" in final.answer.lower()
    assert "LOCAL" in final.route_taken


def test_end_to_end_mock_escalates_external_knowledge(monkeypatch) -> None:
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    task = TaskInput(
        task_id="external",
        instruction="What is the latest public status?",
        context="The local context has no current public status.",
    )

    final = LCCRouter().run(task)

    assert final.remote_tokens_used > 0
    assert final.route_taken == "REMOTE_DIRECT"


def test_end_to_end_mock_reports_local_compression(monkeypatch) -> None:
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    repeated = "Runbook decision: keep the stable cache header. Current page remains live."
    task = TaskInput(
        task_id="compressed",
        instruction="What should the runbook keep?",
        context="\n\n".join([repeated, repeated, repeated, "Ignore billing notes.", repeated]),
    )

    final = LCCRouter().run(task)

    assert final.route_taken == "COMPRESS_THEN_LOCAL"
    assert final.remote_tokens_used == 0
    assert final.metadata["compression_applied"] is True
    assert "lcc_prepare" in final.local_steps_used


def test_remote_direct_applies_safe_cleaning_without_leak(monkeypatch) -> None:
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    from lcc.router.cloud_client import RemoteSolver
    from lcc.router.schemas import RemoteAnswer

    class RecordingRemoteSolver(RemoteSolver):
        def __init__(self) -> None:
            self.last_task: TaskInput | None = None
            self.last_prompt: str | None = None

        def complete(self, task: TaskInput, prompt: str) -> RemoteAnswer:
            self.last_task = task
            self.last_prompt = prompt
            return RemoteAnswer(
                answer="Processed successfully",
                model_name="mock-recorder",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                latency_ms=1,
                usage_estimated=True,
            )

    from lcc.router.config import PolicyConfig, RouterPolicyConfig

    rec_solver = RecordingRemoteSolver()
    policy = PolicyConfig(router=RouterPolicyConfig(compress_before_remote=False))
    router = LCCRouter(policy=policy, remote_solver=rec_solver)

    context_with_noise = (
        "Sent from my iPhone\n"
        "Page 1 of 4\n\n"
        "First valid paragraph of information.\n\n"
        "First valid paragraph of information.\n\n"
        "```python\n"
        "def code_sample():\n"
        "    x    = 10\n"
        "    return x\n"
        "```"
    )

    task = TaskInput(
        task_id="remote_direct_clean_check",
        instruction="What is the latest public status?",
        context=context_with_noise,
    )

    final = router.run(task)

    assert final.route_taken == "REMOTE_DIRECT"
    assert rec_solver.last_task is not None
    cleaned_context = rec_solver.last_task.context

    # Assert boilerplate was removed
    assert "Sent from my iPhone" not in cleaned_context
    assert "Page 1 of 4" not in cleaned_context

    # Assert exact duplicate paragraph was deduplicated
    assert cleaned_context.count("First valid paragraph of information.") == 1

    # Assert code block formatting and indentation was preserved
    assert "x    = 10" in cleaned_context
    assert "def code_sample():" in cleaned_context

