from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from typing import Callable

from storycraftr.agent.deterministic_guards import (
    check_draft_expansion,
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

    return True, "ok"


def _is_transient_model_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in _TRANSIENT_MODEL_ERROR_TOKENS)


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
    attempt = 1
    while attempt <= max_retries:
        try:
            if next_feedback is None:
                text = generate_fn()
            else:
                try:
                    text = generate_fn(feedback=next_feedback)
                except TypeError:
                    # Backward compatibility for generators that do not accept
                    # feedback keyword arguments.
                    text = generate_fn()
        except Exception as exc:
            if _is_transient_model_error(exc):
                print(
                    "[CompletenessGuard] transient model/network failure; "
                    "retrying without consuming generation budget"
                )
                time.sleep(10)
                continue
            raise

        valid, reason = validate_chapter(text, min_words=min_words)
        if valid and deterministic_validator is not None:
            try:
                valid, reason = deterministic_validator(text)
            except Exception as exc:  # pragma: no cover - defensive fail-closed path
                valid = False
                reason = f"deterministic_guard_error:{exc}"
        if valid and semantic_validator is not None:
            try:
                valid, reason = semantic_validator(text)
            except Exception as exc:  # pragma: no cover - defensive fail-closed path
                valid = False
                reason = f"semantic_review_error:{exc}"
        if valid:
            return text

        last_reason = reason

        if on_failure is not None:
            on_failure(attempt, max_retries, reason, text)

        if on_retry is not None:
            on_retry(attempt, max_retries, reason)

        next_feedback = reason
        attempt += 1

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
        if self.pov_name:
            if looks_sentence_like:
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
        """Return a targeted system correction string for the given failure token.

        The string is injected verbatim as a ``feedback`` argument into the next
        generation attempt via ``guarded_generation``.
        """
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
