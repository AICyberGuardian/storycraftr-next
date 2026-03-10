from __future__ import annotations

from types import SimpleNamespace

import pytest

from storycraftr.agent.chapter_validator import (
    guarded_generation,
    has_meaningful_state_signal,
)


def test_has_meaningful_state_signal_reads_nested_patch_operations() -> None:
    assert (
        has_meaningful_state_signal({"patch": SimpleNamespace(operations=[{"op": 1}])})
        is True
    )
    assert (
        has_meaningful_state_signal({"patch": SimpleNamespace(operations=[])}) is False
    )


def test_guarded_generation_transient_model_failure_does_not_consume_retry_budget(
    monkeypatch,
) -> None:
    calls = {"count": 0}

    def _generate() -> str:
        calls["count"] += 1
        if calls["count"] <= 2:
            raise RuntimeError(
                "Model invocation failed: Error code: 429 - temporarily rate-limited"
            )
        return " ".join("word" for _ in range(900))

    monkeypatch.setattr(
        "storycraftr.agent.chapter_validator.time.sleep", lambda _: None
    )

    text = guarded_generation(_generate, max_retries=1, min_words=800)

    assert len(text.split()) == 900
    assert calls["count"] == 3


def test_guarded_generation_raises_non_transient_generation_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "storycraftr.agent.chapter_validator.time.sleep", lambda _: None
    )

    def _generate() -> str:
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        guarded_generation(_generate, max_retries=3, min_words=800)


def test_guarded_generation_passes_failure_reason_to_next_attempt() -> None:
    seen_feedback: list[str | None] = []

    def _generate(*, feedback: str | None = None) -> str:
        seen_feedback.append(feedback)
        if feedback is None:
            return "short"
        return " ".join("word" for _ in range(900))

    text = guarded_generation(_generate, max_retries=2, min_words=800)

    assert len(text.split()) == 900
    assert seen_feedback == [None, "too_short:1"]
