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
