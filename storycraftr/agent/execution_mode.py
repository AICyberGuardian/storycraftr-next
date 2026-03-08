from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExecutionMode(StrEnum):
    """Execution mode values used by runtime policy gates."""

    MANUAL = "manual"
    HYBRID = "hybrid"
    AUTOPILOT = "autopilot"


@dataclass(frozen=True)
class ModeConfig:
    """Policy configuration for execution-mode controlled runtime behavior."""

    mode: ExecutionMode = ExecutionMode.MANUAL
    max_autopilot_turns: int = 1
    auto_regenerate_on_conflict: bool = True

    def with_mode(self, mode: ExecutionMode) -> ModeConfig:
        """Return a config copy with a different mode."""

        return ModeConfig(
            mode=mode,
            max_autopilot_turns=self.max_autopilot_turns,
            auto_regenerate_on_conflict=self.auto_regenerate_on_conflict,
        )

    def with_autopilot_limit(self, limit: int) -> ModeConfig:
        """Return a config copy with a validated autopilot turn limit."""

        normalized = max(1, min(10, int(limit)))
        return ModeConfig(
            mode=self.mode,
            max_autopilot_turns=normalized,
            auto_regenerate_on_conflict=self.auto_regenerate_on_conflict,
        )

    def allows_background_agents(self) -> bool:
        """Return True when background extraction workers are allowed."""

        return self.mode in {ExecutionMode.HYBRID, ExecutionMode.AUTOPILOT}

    def allows_autopilot_loop(self) -> bool:
        """Return True when bounded autopilot loop execution is allowed."""

        return self.mode is ExecutionMode.AUTOPILOT

    def should_auto_regenerate_on_conflict(self) -> bool:
        """Return True when a one-time conflict-driven regeneration is allowed."""

        return self.mode is ExecutionMode.HYBRID and self.auto_regenerate_on_conflict


def parse_execution_mode(raw: str | None) -> ExecutionMode | None:
    """Parse a user-provided mode label into an ExecutionMode value."""

    if raw is None:
        return None
    try:
        return ExecutionMode(raw.strip().lower())
    except ValueError:
        return None
