from __future__ import annotations

from lcc.router.context_adapter import prepare_context
from lcc.router.schemas import TaskInput


def test_prepare_context_preserves_original_when_lcc_optimize_fails(monkeypatch) -> None:
    import lcc.pipeline

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(lcc.pipeline, "optimize", fail)
    task = TaskInput("t", "Summarize", "Original context stays.")

    prepared = prepare_context(task)

    assert prepared.context == "Original context stays."
    assert prepared.compression_applied is False
    assert any("original context preserved" in warning for warning in prepared.warnings)
