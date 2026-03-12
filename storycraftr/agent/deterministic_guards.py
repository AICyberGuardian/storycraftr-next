from __future__ import annotations

from difflib import SequenceMatcher
import re

_WORD_RE = re.compile(r"\w+")
_DOUBLE_QUOTE_RE = re.compile(r'"')
_TERMINAL_PUNCTUATION = (".", "?", "!", '"')
_KEYWORD_RE = re.compile(r"\b[a-zA-Z]{3,}\b")
_THREAD_STOPWORDS = frozenset(
    {
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
        "decides",
        "decision",
        "chooses",
        "changes",
        "discovers",
        "fails",
        "reveals",
        "forces",
        "cost",
        "consequence",
        "dilemma",
        "turn",
        "escalates",
        "confrontation",
        "abandons",
        "joins",
    }
)


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

    if stripped.count("(") != stripped.count(")"):
        return False, "terminal_truncation:unbalanced_parenthesis"

    if stripped.endswith((":", ";", ",", "-", "(", "[")):
        return False, "terminal_truncation:abrupt_terminal_fragment"

    has_terminal_mark = any(mark in stripped for mark in (".", "!", "?"))
    if not has_terminal_mark and _word_count(stripped) < 50:
        return False, "terminal_truncation:missing_terminal_punctuation"
    if has_terminal_mark and not stripped.endswith(_TERMINAL_PUNCTUATION):
        return False, "terminal_truncation:missing_terminal_punctuation"

    return True, "ok"


def check_narrative_stasis(
    previous_text: str,
    current_text: str,
    *,
    similarity_threshold: float = 0.94,
) -> tuple[bool, str]:
    """Reject near-identical retries that indicate deterministic stasis."""

    previous = str(previous_text).strip()
    current = str(current_text).strip()
    if not previous or not current:
        return True, "ok"

    similarity = SequenceMatcher(None, previous, current).ratio()
    if similarity >= similarity_threshold:
        return False, f"narrative_stasis:{similarity:.2f}"
    return True, "ok"


def check_hard_truncation(
    draft_text: str,
    *,
    expected_words: int | None = None,
) -> bool:
    """Return True when prose likely ends mid-sentence and under expected length."""

    stripped = str(draft_text).strip()
    if not stripped:
        return True

    ends_with_terminal = stripped.endswith((".", "?", "!", '"', "'", ")", "]"))
    if ends_with_terminal:
        return False

    if expected_words is None or expected_words <= 0:
        return False

    threshold = max(1, int(expected_words * 0.8))
    return _word_count(stripped) < threshold


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


def check_single_pov_enforcement(
    text: str,
    expected_pov: str,
    *,
    candidate_names: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Reject stitched prose when non-POV named entities dominate narration."""

    pov_name = str(expected_pov).strip()
    if not pov_name:
        return True, "ok"

    lowered_text = str(text)
    rival_names: list[str] = []
    for name in candidate_names:
        candidate = str(name).strip()
        if not candidate or candidate.lower() == pov_name.lower():
            continue
        pattern = re.compile(rf"\b{re.escape(candidate)}\b", re.IGNORECASE)
        if len(pattern.findall(lowered_text)) >= 2:
            rival_names.append(candidate)

    if rival_names:
        return False, f"multi_pov_detected:{','.join(sorted(set(rival_names)))}"
    return True, "ok"


def check_required_outcome_realization(
    chapter_text: str,
    planned_outcome: str,
    *,
    minimum_overlap: float = 0.18,
) -> tuple[bool, str]:
    """Require outcome keywords from the plan to appear in chapter prose."""

    outcome_tokens = {
        token
        for token in _KEYWORD_RE.findall(str(planned_outcome).lower())
        if token not in _THREAD_STOPWORDS
    }
    if not outcome_tokens:
        return True, "ok"

    prose_tokens = {
        token
        for token in _KEYWORD_RE.findall(str(chapter_text).lower())
        if token not in _THREAD_STOPWORDS
    }
    overlap = len(outcome_tokens & prose_tokens) / max(1, len(outcome_tokens))
    if overlap < minimum_overlap:
        return False, f"required_outcome_missing:{overlap:.2f}"
    return True, "ok"


def check_plot_overlap(
    draft_text: str,
    planner_outcome: str,
    *,
    minimum_overlap: float = 0.30,
) -> bool:
    """Return True when draft prose keeps minimum lexical overlap with outcome."""

    ok, _reason = check_required_outcome_realization(
        draft_text,
        planner_outcome,
        minimum_overlap=minimum_overlap,
    )
    return ok


def check_pov(draft: str, expected_pov: str) -> bool:
    """Return True when POV character appears at least once in prose."""

    pov_name = str(expected_pov).strip()
    if not pov_name:
        return True
    pattern = re.compile(r"\b{}\b".format(re.escape(pov_name)), re.IGNORECASE)
    return bool(pattern.search(str(draft)))


def check_outcome_overlap(draft: str, directive_outcome: str) -> bool:
    """Return True when outcome lexical overlap meets the deterministic threshold."""

    return check_plot_overlap(
        draft,
        directive_outcome,
        minimum_overlap=0.30,
    )


def check_required_outline_threads(
    chapter_text: str,
    required_threads: tuple[str, ...],
) -> tuple[bool, str]:
    """Require explicitly demanded outline threads to be present in prose."""

    normalized_chapter = str(chapter_text).lower()
    missing = [
        token
        for token in required_threads
        if token and token.lower() not in normalized_chapter
    ]
    if missing:
        return False, f"required_outline_thread_missing:{','.join(missing)}"
    return True, "ok"


def extract_missing_required_outline_threads(reason: str) -> tuple[str, ...]:
    """Parse missing required-thread names from deterministic guard reason text."""

    prefix, separator, suffix = str(reason).partition(":")
    if prefix.strip() != "required_outline_thread_missing" or not separator:
        return ()
    return tuple(token.strip().lower() for token in suffix.split(",") if token.strip())


def check_scene_order_and_count_preservation(
    stitched_text: str,
    edited_scenes: tuple[str, ...],
    *,
    expected_scene_count: int,
) -> tuple[bool, str]:
    """Best-effort check that stitch preserves scene count and sequence."""

    if expected_scene_count > 0 and len(edited_scenes) != expected_scene_count:
        return (
            False,
            f"scene_count_mismatch:{len(edited_scenes)}!={expected_scene_count}",
        )

    normalized = str(stitched_text)
    last_index = -1
    anchors_found = 0
    for scene_text in edited_scenes:
        words = [word for word in str(scene_text).split() if len(word) > 4]
        anchor = " ".join(words[:10]).strip()
        if len(anchor) < 20:
            continue
        idx = normalized.find(anchor)
        if idx < 0:
            continue
        anchors_found += 1
        if idx < last_index:
            return False, "scene_order_regression"
        last_index = idx

    # Do not fail-closed when we cannot derive robust anchors.
    if anchors_found < 2:
        return True, "ok"
    return True, "ok"
