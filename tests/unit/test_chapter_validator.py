from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from storycraftr.agent.chapter_validator import (
    MechanicalSieve,
    guarded_generation,
    has_meaningful_state_signal,
    validate_chapter,
)
from storycraftr.agent.deterministic_guards import (
    check_draft_expansion,
    check_hard_truncation,
    check_outcome_overlap,
    check_pov,
    check_pov_presence,
    check_terminal_truncation,
)


def test_terminal_truncation_guard_rejects_missing_terminal_punctuation() -> None:
    assert (
        check_terminal_truncation("A complete sentence without an ending")[0] is False
    )


def test_validate_chapter_detects_sentence_boundary_truncation(monkeypatch) -> None:
    mock_logger = mock.Mock()
    monkeypatch.setattr("storycraftr.agent.chapter_validator.logger", mock_logger)

    valid, reason = validate_chapter(
        (
            "This chapter contains enough words to pass the gate. "
            "But the final sentence ends without punctuation"
        ),
        min_words=5,
    )

    assert valid is False
    assert reason == "sentence_boundary_truncation"
    mock_logger.error.assert_called_once()


def test_validate_chapter_skips_sentence_boundary_guard_for_token_stream() -> None:
    token_stream = " ".join(f"stitched{idx}" for idx in range(900))

    valid, reason = validate_chapter(token_stream, min_words=800)

    assert valid is True
    assert reason == "ok"


def test_draft_expansion_guard_rejects_underexpanded_output() -> None:
    ok, reason = check_draft_expansion("short draft", "directive words go here")

    assert ok is False
    assert reason.startswith("insufficient_expansion:")


def test_pov_presence_guard_requires_two_mentions() -> None:
    ok, reason = check_pov_presence("Lyra hesitated once.", "Lyra")

    assert ok is False
    assert reason == "missing_pov:Lyra"


def test_check_pov_accepts_single_direct_mention() -> None:
    assert check_pov("Lyra steps into the vault.", "Lyra") is True


def test_check_hard_truncation_uses_expected_word_threshold() -> None:
    truncated = " ".join("word" for _ in range(50)) + ","
    assert check_hard_truncation(truncated, expected_words=100) is True


def test_check_outcome_overlap_requires_thirty_percent() -> None:
    outcome = "Lyra discovers ledger decides confront Mara before dawn"
    draft = "Lyra discovers the ledger and decides to confront Mara before dawn."
    assert check_outcome_overlap(draft, outcome) is True


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
        return " ".join("word" for _ in range(900)) + "."

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
        return " ".join("word" for _ in range(900)) + "."

    text = guarded_generation(_generate, max_retries=2, min_words=800)

    assert len(text.split()) == 900
    assert seen_feedback == [None, "too_short:1"]


def test_guarded_generation_short_circuits_semantic_review_on_deterministic_failure() -> (
    None
):
    seen_feedback: list[str | None] = []
    validator_calls = {"count": 0}
    semantic_calls = {"count": 0}

    def _generate(*, feedback: str | None = None) -> str:
        seen_feedback.append(feedback)
        return " ".join("word" for _ in range(900)) + "."

    def _deterministic_validator(text: str) -> tuple[bool, str]:
        del text
        validator_calls["count"] += 1
        if validator_calls["count"] == 1:
            return False, "missing_pov:Lyra"
        return True, "ok"

    def _semantic_validator(text: str) -> tuple[bool, str]:
        del text
        semantic_calls["count"] += 1
        return True, "ok"

    text = guarded_generation(
        _generate,
        max_retries=2,
        min_words=800,
        deterministic_validator=_deterministic_validator,
        semantic_validator=_semantic_validator,
    )

    assert len(text.split()) == 900
    assert seen_feedback == [None, "missing_pov:Lyra"]
    assert semantic_calls["count"] == 1


def test_guarded_generation_retries_semantic_transport_without_new_generation(
    monkeypatch,
) -> None:
    generate_calls = {"count": 0}
    semantic_calls = {"count": 0}
    mock_logger = mock.Mock()
    monkeypatch.setattr("storycraftr.agent.chapter_validator.logger", mock_logger)

    def _generate(*, feedback: str | None = None) -> str:
        del feedback
        generate_calls["count"] += 1
        return " ".join("word" for _ in range(900)) + "."

    def _semantic_validator(text: str) -> tuple[bool, str]:
        del text
        semantic_calls["count"] += 1
        if semantic_calls["count"] < 3:
            return (
                False,
                "reviewer_invalid_response:OpenRouter request failed without an explicit exception.",
            )
        return True, "ok"

    monkeypatch.setattr(
        "storycraftr.agent.chapter_validator.time.sleep", lambda _: None
    )

    text = guarded_generation(
        _generate,
        max_retries=1,
        min_words=800,
        semantic_validator=_semantic_validator,
    )

    assert len(text.split()) == 900
    assert generate_calls["count"] == 1
    assert semantic_calls["count"] == 3
    assert any(
        call.args and call.args[0] == "guarded_generation_semantic_transport_retry"
        for call in mock_logger.warning.call_args_list
    )


def test_mechanical_sieve_flags_plot_omission_when_overlap_is_too_low() -> None:
    sieve = MechanicalSieve(
        pov_name="Lyra",
        planned_outcome="Lyra discovers the hidden ledger and decides to confront Mara",
    )

    ok, reason = sieve(
        "Lyra waits in silence while the crowd disperses and thinks about the rain. "
        "Lyra returns home without acting on any discovery or confrontation."
    )

    assert ok is False
    assert reason.startswith("PLOT_OMISSION:")


def test_mechanical_sieve_allows_scene_with_outcome_overlap() -> None:
    sieve = MechanicalSieve(
        pov_name="Lyra",
        planned_outcome="Lyra discovers the hidden ledger and decides to confront Mara",
    )

    ok, reason = sieve(
        "Lyra discovers the hidden ledger beneath the floorboards. "
        "Lyra decides to confront Mara before dawn and prepares the evidence."
    )

    assert ok is True
    assert reason == "ok"


def test_guarded_generation_rejects_narrative_stasis_before_semantic_review() -> None:
    calls = {"count": 0}

    def _generate(*, feedback: str | None = None) -> str:
        calls["count"] += 1
        if feedback is None:
            return "short"
        if calls["count"] == 2:
            return " ".join("word" for _ in range(900)) + "."
        return " ".join("new" for _ in range(900)) + "."

    semantic_calls = {"count": 0}

    def _semantic_validator(text: str) -> tuple[bool, str]:
        del text
        semantic_calls["count"] += 1
        return True, "ok"

    text = guarded_generation(
        _generate,
        max_retries=3,
        min_words=800,
        semantic_validator=_semantic_validator,
    )

    assert len(text.split()) == 900
    assert semantic_calls["count"] == 1
