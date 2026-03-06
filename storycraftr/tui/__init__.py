from __future__ import annotations

from typing import Any

__all__ = ["TuiApp"]


def __getattr__(name: str) -> Any:
    if name == "TuiApp":
        from .app import TuiApp

        return TuiApp
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
