from __future__ import annotations

import re

_WORD_RE = re.compile(r"\w+")
_DOUBLE_QUOTE_RE = re.compile(r'"')
_TERMINAL_PUNCTUATION = (".", "?", "!", '"')


def _word_count(text: str) -> int:
    """Count word-like tokens with a stable regex across guard checks."""

    return len(_WORD_RE.findall(text))


def check_terminal_truncation(text: str) -> tuple[bool, str]:
    """Reject prose that appears to stop mid-thought or with broken dialogue."""

    stripped = str(text).strip()
    if not stripped:
        return False, "terminal_truncation:empty_output"

    if stripped.endswith(","):
        return False, "terminal_truncation:comma_tail"

    if len(_DOUBLE_QUOTE_RE.findall(stripped)) % 2 != 0:
        return False, "terminal_truncation:unbalanced_quote"

    has_terminal_mark = any(mark in stripped for mark in (".", "!", "?"))
    if not has_terminal_mark and _word_count(stripped) < 50:
        return False, "terminal_truncation:missing_terminal_punctuation"
    if has_terminal_mark and not stripped.endswith(_TERMINAL_PUNCTUATION):
        return False, "terminal_truncation:missing_terminal_punctuation"

    return True, "ok"


def check_pov_presence(text: str, expected_pov: str) -> tuple[bool, str]:
    """Require the expected POV name to appear at least twice in the prose."""

    pov_name = str(expected_pov).strip()
    if not pov_name:
        return True, "ok"

    pattern = re.compile(rf"\b{re.escape(pov_name)}\b", re.IGNORECASE)
    if len(pattern.findall(str(text))) >= 2:
        return True, "ok"
    return False, f"missing_pov:{pov_name}"


def check_draft_expansion(draft_text: str, directive_text: str) -> tuple[bool, str]:
    """Ensure generated prose materially expands the directive source text."""

    draft_words = _word_count(str(draft_text))
    directive_words = max(1, _word_count(str(directive_text)))
    required_words = directive_words * 3
    if draft_words < required_words:
        return False, f"insufficient_expansion:{draft_words}<{required_words}"
    return True, "ok"
