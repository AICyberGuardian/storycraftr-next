from __future__ import annotations

from storycraftr.agent.self_healer import HealingTicket, NarrativeHealer


def test_narrative_healer_returns_ticket_for_short_output() -> None:
    healer = NarrativeHealer()

    def _validator(text: str) -> tuple[bool, str]:
        del text
        return False, "too_short:42"

    result = healer.evaluate(
        stage="chapter_validation",
        raw_output="short",
        validator=_validator,
    )

    assert isinstance(result, HealingTicket)
    assert result.stage == "chapter_validation"
    assert result.failure_class == "too_short:42"
    assert "Expand the draft" in result.remediation_instruction


def test_narrative_healer_returns_pass_for_valid_output() -> None:
    healer = NarrativeHealer()

    result = healer.evaluate(
        stage="chapter_validation",
        raw_output="valid prose",
        validator=lambda _: (True, "ok"),
    )

    assert result == "PASS"
