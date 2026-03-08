from __future__ import annotations

from storycraftr.agent.story.scene_planner import plan_next_scene


def test_plan_next_scene_uses_prompt_as_goal() -> None:
    plan = plan_next_scene(
        active_scene="Revelation",
        active_arc="Act II",
        user_prompt="Push the confrontation to a decisive emotional beat.",
    )

    assert plan.goal == "Push the confrontation to a decisive emotional beat."
    assert "Act II" in plan.conflict
    assert "Act II" in plan.stakes
    assert "Revelation" in plan.outcome
    assert "Revelation" in plan.ending_beat


def test_plan_next_scene_has_safe_fallbacks() -> None:
    plan = plan_next_scene(
        active_scene="Unknown",
        active_arc="Unknown",
        user_prompt="",
    )

    assert plan.goal == "Advance the current scene clearly."
    assert "continuity" in plan.conflict.lower()
    assert "cost" in plan.stakes.lower()
    assert "clear next beat" in plan.outcome.lower()
    assert "next scene" in plan.ending_beat.lower()
