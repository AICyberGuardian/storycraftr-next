from __future__ import annotations

from dataclasses import dataclass
import re


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class CanonCandidate:
    """One extracted canon candidate awaiting user approval."""

    text: str
    chapter: int
    fact_type: str = "constraint"
    source: str = "hybrid-extract"


def extract_canon_candidates(
    response_text: str,
    *,
    chapter: int,
    max_candidates: int = 3,
) -> list[CanonCandidate]:
    """Extract concise fact-like candidates from assistant output text.

    The heuristic intentionally stays conservative for free-model workflows:
    it keeps short declarative sentences and drops obviously imperative or
    speculative fragments.
    """

    chapter = max(1, int(chapter))
    max_candidates = max(1, int(max_candidates))

    text = response_text.strip()
    if not text:
        return []

    candidates: list[CanonCandidate] = []
    seen: set[str] = set()

    for raw_sentence in _SENTENCE_SPLIT.split(text):
        sentence = " ".join(raw_sentence.split()).strip()
        if not sentence:
            continue

        normalized = sentence.lower()
        if normalized in seen:
            continue
        if not _looks_like_fact(sentence):
            continue

        seen.add(normalized)
        candidates.append(CanonCandidate(text=sentence, chapter=chapter))
        if len(candidates) >= max_candidates:
            break

    return candidates


def _looks_like_fact(sentence: str) -> bool:
    """Return True when sentence resembles a stable canon fact."""

    lower = sentence.lower()
    if len(sentence) < 16 or len(sentence) > 180:
        return False
    if lower.startswith(("maybe ", "perhaps ", "consider ", "try ", "let's ")):
        return False
    if lower.endswith(":"):
        return False

    fact_markers = (
        " is ",
        " are ",
        " was ",
        " were ",
        " has ",
        " have ",
        " can ",
        " cannot ",
        " must ",
    )
    return any(marker in lower for marker in fact_markers)
