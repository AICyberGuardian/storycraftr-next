from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from typing import Callable

import pysbd
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from storycraftr.agent.deterministic_guards import (
    check_draft_expansion,
    check_narrative_stasis,
    check_pov_presence,
    check_terminal_truncation,
)

MIN_WORDS = 800
MAX_RETRIES = 9
DUPLICATE_THRESHOLD = 0.92
_TRANSIENT_MODEL_ERROR_TOKENS = (
    "model invocation failed",
    "rate-limited",
    "error code: 429",
    "error code: 500",
    "error code: 502",
    "error code: 503",
    "error code: 504",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "empty response",
)
_SEMANTIC_TRANSPORT_ERROR_TOKENS = (
    "reviewer_invalid_response",
    "reviewer_empty_output",
    "reviewer_transport_error",
    "openrouter request failed without an explicit exception",
    "semantic_review_error:model invocation failed",
)
_OUTCOME_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "their",
    "they",
    "them",
    "will",
    "would",
    "could",
    "should",
    "scene",
    "outcome",
    "chapter",
}
_SENTENCE_ENDINGS = (".", "!", "?", '"', "'", ")", "]")
_SEGMENTER = pysbd.Segmenter(language="en", clean=False)
logger = structlog.get_logger("storycraftr.chapter_validator")


class _TransientGenerationRetry(RuntimeError):
    """Retryable transient generation transport failure."""


class _SemanticTransportRetry(RuntimeError):
    """Retryable semantic-review transport failure."""


def _sleep(seconds: float) -> None:
    """Wrapper so tests can monkeypatch module-local sleep deterministically."""

    time.sleep(seconds)


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def detect_duplicate_paragraphs(paragraphs: list[str]) -> bool:
    """Detect repeated narrative loops produced by unstable generations."""

    for i in range(len(paragraphs)):
        for j in range(i + 1, len(paragraphs)):
            similarity = SequenceMatcher(None, paragraphs[i], paragraphs[j]).ratio()
            if similarity > DUPLICATE_THRESHOLD:
                return True
    return False


def _has_sentence_boundary_truncation(text: str) -> bool:
    raw_text = str(text)
    # Skip pySBD boundary checks for punctuation-free token streams used in
    # deterministic scaffolding; truncation is handled by other guards there.
    if not any(mark in raw_text for mark in (".", "!", "?")):
        return False
    sentences = _SEGMENTER.segment(raw_text)
    if not sentences:
        return False
    last_sentence = str(sentences[-1]).rstrip()
    if not last_sentence:
        return False
    return not last_sentence.endswith(_SENTENCE_ENDINGS)


def validate_chapter(text: str, min_words: int = MIN_WORDS) -> tuple[bool, str]:
    """Validate chapter completeness and return `(is_valid, reason)` contract."""

    if not text or not text.strip():
        return False, "empty_output"

    words = word_count(text)
    if words < min_words:
        return False, f"too_short:{words}"

    paragraphs = split_paragraphs(text)
    if detect_duplicate_paragraphs(paragraphs):
        return False, "duplicate_paragraphs"

    if _has_sentence_boundary_truncation(text):
        logger.error(
            "sentence_boundary_truncation",
            last_sentence=_SEGMENTER.segment(str(text))[-1],
        )
        return False, "sentence_boundary_truncation"

    return True, "ok"


def _is_transient_model_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in _TRANSIENT_MODEL_ERROR_TOKENS)


def is_semantic_transport_error(reason: str) -> bool:
    """Classify reviewer transport failures that should not burn creative retries."""

    lowered = str(reason).strip().lower()
    return any(token in lowered for token in _SEMANTIC_TRANSPORT_ERROR_TOKENS)


def _log_transient_generation_retry(retry_state: object) -> None:
    outcome = getattr(retry_state, "outcome", None)
    exc = (
        outcome.exception()
        if outcome is not None and hasattr(outcome, "exception")
        else None
    )
    logger.warning(
        "guarded_generation_transient_model_error",
        attempt=getattr(retry_state, "attempt_number", 0),
        error=str(exc) if exc is not None else "",
        action="retry_without_budget_consumption",
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type(_TransientGenerationRetry),
    before_sleep=_log_transient_generation_retry,
    sleep=_sleep,
    reraise=True,
)
def _invoke_generation_with_transient_retry(
    generate_fn: Callable[..., str],
    feedback: str | None,
) -> str:
    try:
        if feedback is None:
            return generate_fn()
        try:
            return generate_fn(feedback=feedback)
        except TypeError:
            # Backward compatibility for generators that do not accept
            # feedback keyword arguments.
            return generate_fn()
    except Exception as exc:
        if _is_transient_model_error(exc):
            raise _TransientGenerationRetry(str(exc)) from exc
        raise


def _log_semantic_transport_retry(retry_state: object) -> None:
    outcome = getattr(retry_state, "outcome", None)
    exc = (
        outcome.exception()
        if outcome is not None and hasattr(outcome, "exception")
        else None
    )
    logger.warning(
        "guarded_generation_semantic_transport_retry",
        attempt=getattr(retry_state, "attempt_number", 0),
        reason=str(exc) if exc is not None else "unknown",
        action="retry_without_chapter_budget_consumption",
    )


@retry(
    stop=stop_after_attempt(max(3, MAX_RETRIES * 2)),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type(_SemanticTransportRetry),
    before_sleep=_log_semantic_transport_retry,
    sleep=_sleep,
    reraise=True,
)
def _run_semantic_validator_with_transport_retry(
    semantic_validator: Callable[[str], tuple[bool, str]],
    text: str,
) -> tuple[bool, str]:
    valid, reason = semantic_validator(text)
    if not valid and is_semantic_transport_error(reason):
        raise _SemanticTransportRetry(str(reason))
    return valid, reason


def guarded_generation(
    generate_fn: Callable[..., str],
    *,
    max_retries: int = MAX_RETRIES,
    min_words: int = MIN_WORDS,
    deterministic_validator: Callable[[str], tuple[bool, str]] | None = None,
    semantic_validator: Callable[[str], tuple[bool, str]] | None = None,
    on_failure: Callable[[int, int, str, str], None] | None = None,
    on_retry: Callable[[int, int, str], None] | None = None,
) -> str:
    """Retry generation until chapter content validates or retries are exhausted."""

    last_reason = "unknown"
    next_feedback: str | None = None
    previous_attempt_text: str | None = None
    stasis_repeat_count = 0

    for attempt in range(1, max_retries + 1):
        logger.info(
            "guarded_generation_attempt",
            attempt=attempt,
            last_reason=last_reason,
        )
        try:
            text = _invoke_generation_with_transient_retry(generate_fn, next_feedback)
        except _TransientGenerationRetry as exc:
            raise RuntimeError(str(exc)) from exc

        valid, reason = validate_chapter(text, min_words=min_words)
        if valid and deterministic_validator is not None:
            try:
                valid, reason = deterministic_validator(text)
            except Exception as exc:  # pragma: no cover - defensive fail-closed path
                valid = False
                reason = f"deterministic_guard_error:{exc}"
        if valid and previous_attempt_text is not None:
            retry_context = str(next_feedback or "").strip().lower()
            should_check_stasis = any(
                token in retry_context
                for token in (
                    "too_short",
                    "duplicate",
                    "terminal_truncation",
                    "insufficient_expansion",
                    "missing_pov",
                    "required_outline_thread",
                    "narrative_stasis",
                )
            )
            if should_check_stasis:
                stasis_ok, stasis_reason = check_narrative_stasis(
                    previous_attempt_text,
                    text,
                )
                if not stasis_ok:
                    stasis_repeat_count += 1
                    if stasis_repeat_count >= 2:
                        valid, reason = stasis_ok, stasis_reason
                    else:
                        valid, reason = True, "ok"
                else:
                    stasis_repeat_count = 0
            else:
                stasis_repeat_count = 0
        if valid and semantic_validator is not None:
            try:
                valid, reason = _run_semantic_validator_with_transport_retry(
                    semantic_validator,
                    text,
                )
            except _SemanticTransportRetry as exc:
                raise RuntimeError(
                    f"Semantic reviewer transport exhausted retries: {exc}"
                ) from exc
            except Exception as exc:  # pragma: no cover - defensive fail-closed path
                valid = False
                reason = f"semantic_review_error:{exc}"
        if valid:
            logger.info("guarded_generation_success", attempt=attempt)
            return text

        previous_attempt_text = text
        last_reason = reason
        logger.error("guarded_generation_failure", attempt=attempt, reason=reason)
        if on_failure is not None:
            on_failure(attempt, max_retries, reason, text)
        if on_retry is not None:
            on_retry(attempt, max_retries, reason)
        next_feedback = reason

    raise RuntimeError(
        "Chapter generation failed completeness validation after retries: "
        f"{last_reason}"
    )


class MechanicalSieve:
    """Deterministic POV + truncation gate that short-circuits the LLM semantic reviewer.

    Checks (in order):
    1. **Truncation**: Text must end with ``.``, ``!``, ``?``, ``"``, ``'``, ``)``, or ``]``.
    2. **POV Amnesia**: The expected POV character name must appear ≥ 2 times
       (case-insensitive).

    On failure the sieve returns a targeted correction string via ``correction_for``
    that is injected as the retry ``feedback`` without calling the LLM reviewer.
    """

    def __init__(self, pov_name: str = "", planned_outcome: str = "") -> None:
        self.pov_name = pov_name.strip()
        self.planned_outcome = planned_outcome.strip()

    def __call__(self, text: str) -> tuple[bool, str]:
        ok, reason = check_terminal_truncation(text)
        if not ok:
            return False, reason
        has_narrative_punctuation = any(mark in text for mark in (".", "!", "?"))
        looks_sentence_like = has_narrative_punctuation or len(text.split()) < 50
        if self.pov_name and looks_sentence_like:
            ok, reason = check_pov_presence(text, self.pov_name)
            if not ok:
                return False, reason

        if self.planned_outcome:
            overlap = self._keyword_overlap(self.planned_outcome, text)
            if looks_sentence_like and overlap < 0.15:
                return False, f"PLOT_OMISSION:{overlap:.2f}"

        return True, "ok"

    @staticmethod
    def correction_for(
        reason: str,
        pov_name: str = "",
        planned_outcome: str = "",
    ) -> str:
        """Return a targeted system correction string for the given failure token."""

        if reason.startswith("terminal_truncation"):
            return (
                "CORRECTION: Your response was cut off mid-sentence. "
                "Rewrite the scene so it ends with a complete sentence "
                "terminated by '.', '?', '!', or '\"'."
            )
        if reason.startswith("missing_pov:"):
            name = reason.split(":", 1)[1].strip() or pov_name
            return (
                f"CORRECTION: You forgot to include {name}. "
                f"Rewrite the scene and ensure {name} appears "
                "at least twice as an active participant."
            )
        if reason.upper().startswith("PLOT_OMISSION"):
            return (
                "CRITICAL: Your draft does not mention the planned outcome: "
                f"{planned_outcome or '(missing outcome)'}"
                ". Ensure this happens on-page."
            )
        return (
            f"CORRECTION: The previous attempt failed with reason '{reason}'. "
            "Rewrite to fix this specific issue."
        )

    @staticmethod
    def _keyword_overlap(outcome: str, prose: str) -> float:
        """Return keyword-overlap ratio between planned outcome and produced prose."""

        outcome_tokens = {
            token
            for token in re.findall(r"\b[a-zA-Z]{3,}\b", outcome.lower())
            if token not in _OUTCOME_STOPWORDS
        }
        if not outcome_tokens:
            return 1.0
        prose_tokens = {
            token
            for token in re.findall(r"\b[a-zA-Z]{3,}\b", prose.lower())
            if token not in _OUTCOME_STOPWORDS
        }
        overlap = outcome_tokens & prose_tokens
        return len(overlap) / max(1, len(outcome_tokens))


def has_meaningful_state_signal(state_update: object) -> bool:
    """Reject empty/no-op state updates so weak chapters do not commit silently."""

    if state_update is None:
        return False
    if isinstance(state_update, dict):
        patch_obj = state_update.get("patch")
        if patch_obj is not None:
            patch_operations = getattr(patch_obj, "operations", None)
            if patch_operations is None and isinstance(patch_obj, dict):
                patch_operations = patch_obj.get("operations")
            if patch_operations is not None:
                return isinstance(patch_operations, list) and len(patch_operations) > 0

        operations = state_update.get("operations")
        if operations is not None:
            return isinstance(operations, list) and len(operations) > 0
        return any(bool(value) for value in state_update.values())
    if isinstance(state_update, (list, tuple, set)):
        return len(state_update) > 0
    return True
