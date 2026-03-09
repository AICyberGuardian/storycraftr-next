from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable


MIN_WORDS = 800
MAX_RETRIES = 3
DUPLICATE_THRESHOLD = 0.92


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


def guarded_generation(
    generate_fn: Callable[[], str],
    *,
    max_retries: int = MAX_RETRIES,
    min_words: int = MIN_WORDS,
    semantic_validator: Callable[[str], tuple[bool, str]] | None = None,
    on_failure: Callable[[int, int, str, str], None] | None = None,
    on_retry: Callable[[int, int, str], None] | None = None,
) -> str:
    """Retry generation until chapter content validates or retries are exhausted."""

    last_reason = "unknown"
    for attempt in range(1, max_retries + 1):
        text = generate_fn()
        valid, reason = validate_chapter(text, min_words=min_words)
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

    raise RuntimeError(
        "Chapter generation failed completeness validation after retries: "
        f"{last_reason}"
    )


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
