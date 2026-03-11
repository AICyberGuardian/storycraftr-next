from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal


HealingPass = Literal["PASS"]


@dataclass(frozen=True)
class HealingTicket:
    """Deterministic healing artifact describing a single failed output check."""

    stage: str
    failure_class: str
    raw_output: str
    remediation_instruction: str


class NarrativeHealer:
    """Centralized orchestration for deterministic healing classification.

    This class converts validator failures into normalized ``HealingTicket`` records
    so runtime callers can apply one consistent remediation flow.
    """

    _DEFAULT_REMEDIATIONS = {
        "EMPTY_OUTPUT": "CRITICAL: Your previous response was empty. Rewrite the full content.",
        "TOO_SHORT": "CRITICAL: Expand the draft with concrete actions, conflict, and consequences.",
        "DUPLICATE_PARAGRAPHS": "CRITICAL: Remove repetitive loops and rewrite with forward narrative movement.",
        "TERMINAL_TRUNCATION": (
            "CRITICAL: Your response was cut off. End with complete sentences and closed dialogue."
        ),
        "MISSING_POV": (
            "CRITICAL: You omitted the required POV character. Include the POV as an active participant."
        ),
        "INSUFFICIENT_EXPANSION": (
            "CRITICAL: Expand directive beats into full scene prose; do not return compressed summaries."
        ),
        "PLOT_OMISSION": (
            "CRITICAL: Your draft does not mention the planned outcome. Ensure it happens on-page."
        ),
        "SEMANTIC_REVIEW": (
            "CRITICAL: Semantic review failed. Rewrite while preserving the approved scene plan."
        ),
        "COHERENCE_GATE": (
            "CRITICAL: Coherence gate failed. Resolve continuity contradictions and canon drift."
        ),
    }

    def evaluate(
        self,
        *,
        stage: str,
        raw_output: str,
        validator: Callable[[str], tuple[bool, str]],
    ) -> HealingPass | HealingTicket:
        """Run a deterministic validator and return PASS or a healing ticket."""

        ok, reason = validator(raw_output)
        if ok:
            return "PASS"
        return self.ticket(stage=stage, failure_class=reason, raw_output=raw_output)

    def ticket(
        self, *, stage: str, failure_class: str, raw_output: str
    ) -> HealingTicket:
        """Create a normalized healing ticket from a raw failure reason."""

        raw_failure = str(failure_class).strip() or "UNKNOWN"
        normalized = self.normalize_failure_class(raw_failure)
        remediation = self.remediation_for(normalized, raw_output=raw_output)
        return HealingTicket(
            stage=str(stage).strip() or "unknown",
            failure_class=raw_failure,
            raw_output=str(raw_output),
            remediation_instruction=remediation,
        )

    def remediation_for(self, failure_class: str, *, raw_output: str) -> str:
        """Map normalized failure class to deterministic remediation guidance."""

        del raw_output
        return self._DEFAULT_REMEDIATIONS.get(
            failure_class,
            f"CRITICAL: Previous output failed with {failure_class}. Rewrite to fix it.",
        )

    @staticmethod
    def normalize_failure_class(reason: str) -> str:
        """Normalize rich failure reasons to stable class identifiers."""

        raw = str(reason or "unknown").strip()
        prefix = raw.split(":", 1)[0].strip()
        if not prefix:
            return "UNKNOWN"
        return prefix.upper()
