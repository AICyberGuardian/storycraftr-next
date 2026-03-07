from __future__ import annotations

from storycraftr.agent.story.scene_planner import ScenePlan
from storycraftr.tui.context_builder import build_scoped_context_block
from storycraftr.tui.state_engine import NarrativeState


def _state() -> NarrativeState:
    return NarrativeState(
        chapters=(),
        active_chapter=4,
        active_scene="Bridge",
        active_arc="Act II",
        memory_strip="Narrative: Chapter 4 - Bridge | Arc: Act II",
        timeline_strip="Timeline: Ch3 Break-in -> Ch4 Bridge",
    )


def test_build_scoped_context_block_includes_plan_constraints_and_retrieval() -> None:
    block = build_scoped_context_block(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Escalate the standoff.",
            conflict="Trust is collapsing.",
            outcome="End with a hard choice.",
        ),
        canon_facts=["Mira is the ship navigator."],
        retrieved_context=["Bridge logs confirm sabotage."],
    )

    assert "[Scene Plan]" in block
    assert "Goal: Escalate the standoff." in block
    assert "[Active Constraints]" in block
    assert "Mira is the ship navigator." in block
    assert "[Relevant Context]" in block
    assert "Bridge logs confirm sabotage." in block


def test_build_scoped_context_block_dedupes_and_caps_inputs() -> None:
    long_value = "A" * 260
    block = build_scoped_context_block(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Escalate.",
            conflict="Collapse.",
            outcome="Shift.",
        ),
        canon_facts=["Fact one.", "Fact one.", long_value],
        retrieved_context=[
            "Chunk one.",
            "Chunk one.",
            "Chunk two.",
            "Chunk three.",
            "Chunk four.",
        ],
        max_facts=2,
        max_retrieval_chunks=3,
    )

    assert block.count("Fact one.") == 1
    assert "Chunk four." not in block
    assert ("A" * 180) in block
    assert "..." in block
