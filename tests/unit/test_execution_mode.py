from __future__ import annotations

from storycraftr.agent.execution_mode import (
    ExecutionMode,
    ModeConfig,
    parse_execution_mode,
)
from storycraftr.tui.session import TuiSessionState


def test_execution_mode_enum_values() -> None:
    assert ExecutionMode.MANUAL.value == "manual"
    assert ExecutionMode.HYBRID.value == "hybrid"
    assert ExecutionMode.AUTOPILOT.value == "autopilot"


def test_parse_execution_mode_accepts_case_insensitive_values() -> None:
    assert parse_execution_mode("MANUAL") is ExecutionMode.MANUAL
    assert parse_execution_mode("Hybrid") is ExecutionMode.HYBRID
    assert parse_execution_mode("autopilot") is ExecutionMode.AUTOPILOT
    assert parse_execution_mode("unknown") is None


def test_mode_config_policy_gates() -> None:
    manual = ModeConfig(mode=ExecutionMode.MANUAL)
    hybrid = ModeConfig(mode=ExecutionMode.HYBRID)
    autopilot = ModeConfig(mode=ExecutionMode.AUTOPILOT)

    assert manual.allows_background_agents() is False
    assert manual.allows_autopilot_loop() is False
    assert manual.should_auto_regenerate_on_conflict() is False

    assert hybrid.allows_background_agents() is True
    assert hybrid.allows_autopilot_loop() is False
    assert hybrid.should_auto_regenerate_on_conflict() is True

    assert autopilot.allows_background_agents() is True
    assert autopilot.allows_autopilot_loop() is True
    assert autopilot.should_auto_regenerate_on_conflict() is False


def test_mode_config_autopilot_limit_is_clamped() -> None:
    cfg = ModeConfig(mode=ExecutionMode.AUTOPILOT)

    assert cfg.with_autopilot_limit(0).max_autopilot_turns == 1
    assert cfg.with_autopilot_limit(6).max_autopilot_turns == 6
    assert cfg.with_autopilot_limit(99).max_autopilot_turns == 10


def test_tui_session_state_serialization_round_trip() -> None:
    state = TuiSessionState(
        mode_config=ModeConfig(
            mode=ExecutionMode.AUTOPILOT,
            max_autopilot_turns=4,
            auto_regenerate_on_conflict=False,
        ),
        autopilot_turns_remaining=2,
    )

    payload = state.to_dict()
    restored = TuiSessionState.from_dict(payload)

    assert restored.mode_config.mode is ExecutionMode.AUTOPILOT
    assert restored.mode_config.max_autopilot_turns == 4
    assert restored.mode_config.auto_regenerate_on_conflict is False
    assert restored.autopilot_turns_remaining == 2


def test_tui_session_state_supports_legacy_execution_mode_key() -> None:
    restored = TuiSessionState.from_dict(
        {
            "execution_mode": "hybrid",
            "max_autopilot_turns": 3,
            "autopilot_turns_remaining": 1,
        }
    )

    assert restored.mode_config.mode is ExecutionMode.HYBRID
    assert restored.mode_config.max_autopilot_turns == 3
    assert restored.autopilot_turns_remaining == 1
