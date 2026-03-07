from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenePlan:
    """Lightweight plan scaffold for the next scene generation step."""

    goal: str
    conflict: str
    outcome: str


def plan_next_scene(
    *,
    active_scene: str,
    active_arc: str,
    user_prompt: str,
) -> ScenePlan:
    """Build a deterministic scene plan from state and current user intent."""

    prompt = " ".join(user_prompt.split()).strip()
    goal = _truncate(prompt, 180) if prompt else "Advance the current scene clearly."

    if active_arc and active_arc.lower() != "unknown":
        conflict = f"Preserve tension consistent with {active_arc}."
    else:
        conflict = "Preserve narrative tension and continuity with prior beats."

    if active_scene and active_scene.lower() != "unknown":
        outcome = f"Resolve this turn with a concrete shift in scene '{active_scene}'."
    else:
        outcome = "Resolve this turn with a concrete shift and clear next beat."

    return ScenePlan(goal=goal, conflict=conflict, outcome=outcome)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
