from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from storycraftr.agent.execution_mode import (
    ExecutionMode,
    ModeConfig,
    parse_execution_mode,
)


@dataclass(frozen=True)
class TuiSessionState:
    """Serializable runtime session state for execution-mode controls."""

    mode_config: ModeConfig = ModeConfig()
    autopilot_turns_remaining: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TuiSessionState:
        """Build state from runtime metadata, tolerating legacy keys."""

        payload = raw or {}

        mode_raw = payload.get("mode")
        if not isinstance(mode_raw, str):
            mode_raw = payload.get("execution_mode")

        mode = parse_execution_mode(mode_raw) or ExecutionMode.MANUAL

        max_turns_raw = payload.get("max_autopilot_turns", 1)
        if not isinstance(max_turns_raw, int):
            max_turns_raw = 1

        auto_regen_raw = payload.get("auto_regenerate_on_conflict", True)
        auto_regenerate = auto_regen_raw if isinstance(auto_regen_raw, bool) else True

        remaining_raw = payload.get("autopilot_turns_remaining", 0)
        remaining = remaining_raw if isinstance(remaining_raw, int) else 0

        config = ModeConfig(
            mode=mode,
            max_autopilot_turns=max(1, min(10, max_turns_raw)),
            auto_regenerate_on_conflict=auto_regenerate,
        )

        return cls(
            mode_config=config,
            autopilot_turns_remaining=max(0, remaining),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize state into runtime metadata representation."""

        return {
            "mode": self.mode_config.mode.value,
            "execution_mode": self.mode_config.mode.value,
            "max_autopilot_turns": self.mode_config.max_autopilot_turns,
            "auto_regenerate_on_conflict": self.mode_config.auto_regenerate_on_conflict,
            "autopilot_turns_remaining": self.autopilot_turns_remaining,
        }
