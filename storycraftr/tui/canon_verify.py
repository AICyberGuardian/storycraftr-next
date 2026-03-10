from __future__ import annotations

from dataclasses import dataclass

from storycraftr.tui.canon import list_facts

_NEGATION_TOKENS = {"not", "no", "never", "cannot", "can't", "won't", "without"}


@dataclass(frozen=True)
class CanonVerificationResult:
    """Verification outcome for a candidate canon fact."""

    allowed: bool
    reason: str
    conflicting_fact: str | None = None


def verify_candidate_against_canon(
    *,
    book_path: str,
    chapter: int,
    candidate_text: str,
) -> CanonVerificationResult:
    """Fail-closed verification of one candidate against accepted chapter canon."""

    candidate = _normalize(candidate_text)
    if not candidate:
        return CanonVerificationResult(allowed=False, reason="empty-candidate")

    try:
        existing = list_facts(book_path, chapter=chapter)
    except RuntimeError:
        return CanonVerificationResult(allowed=False, reason="verification-error")

    existing_texts = [fact.text for fact in existing if fact.text.strip()]
    if candidate in {_normalize(text) for text in existing_texts}:
        return CanonVerificationResult(allowed=False, reason="duplicate")

    candidate_tokens = _tokenize(candidate)
    candidate_has_neg = _has_negation(candidate_tokens)

    for fact in existing_texts:
        normalized_fact = _normalize(fact)
        fact_tokens = _tokenize(normalized_fact)

        if _core_tokens(candidate_tokens) == _core_tokens(fact_tokens):
            fact_has_neg = _has_negation(fact_tokens)
            if fact_has_neg != candidate_has_neg:
                return CanonVerificationResult(
                    allowed=False,
                    reason="negation-conflict",
                    conflicting_fact=fact,
                )

    return CanonVerificationResult(allowed=True, reason="ok")


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _tokenize(text: str) -> list[str]:
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return [tok for tok in cleaned.split() if tok]


def _has_negation(tokens: list[str]) -> bool:
    return any(tok in _NEGATION_TOKENS for tok in tokens)


def _core_tokens(tokens: list[str]) -> tuple[str, ...]:
    return tuple(tok for tok in tokens if tok not in _NEGATION_TOKENS)
