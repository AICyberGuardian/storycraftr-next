from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenePlan:
    """Lightweight plan scaffold for the next scene generation step."""

    goal: str
    conflict: str
    stakes: str
    outcome: str
    ending_beat: str


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
        stakes = f"Failure should visibly damage momentum in {active_arc}."
    else:
        conflict = "Preserve narrative tension and continuity with prior beats."
        stakes = "Failure should cost the protagonist trust, leverage, or time."

    if active_scene and active_scene.lower() != "unknown":
        outcome = f"Resolve this turn with a concrete shift in scene '{active_scene}'."
        ending_beat = (
            f"Close with an actionable pivot that changes '{active_scene}' dynamics."
        )
    else:
        outcome = "Resolve this turn with a concrete shift and clear next beat."
        ending_beat = "Close with an actionable pivot that sets the next scene."

    return ScenePlan(
        goal=goal,
        conflict=conflict,
        stakes=stakes,
        outcome=outcome,
        ending_beat=ending_beat,
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
