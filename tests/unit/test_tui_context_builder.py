from __future__ import annotations

from storycraftr.agent.story.scene_planner import ScenePlan
from storycraftr.llm.model_context import ModelContextSpec
from storycraftr.tui.context_builder import (
    build_scoped_context_block,
    compose_budgeted_prompt,
)
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
            stakes="A failed negotiation fractures the alliance.",
            outcome="End with a hard choice.",
            ending_beat="Close on a vote that splits the bridge crew.",
        ),
        canon_facts=["Mira is the ship navigator."],
        retrieved_context=["Bridge logs confirm sabotage."],
    )

    assert "[Scene Plan]" in block
    assert "Goal: Escalate the standoff." in block
    assert "Stakes: A failed negotiation fractures the alliance." in block
    assert "Ending Beat: Close on a vote that splits the bridge crew." in block
    assert "[Canon Constraints]" in block
    assert "Mira is the ship navigator." in block
    assert "[Relevant Context]" in block
    assert "Bridge logs confirm sabotage." in block


def test_build_scoped_context_block_includes_role_rules_when_provided() -> None:
    block = build_scoped_context_block(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Escalate the standoff.",
            conflict="Trust is collapsing.",
            stakes="A failed negotiation fractures the alliance.",
            outcome="End with a hard choice.",
            ending_beat="Close on a vote that splits the bridge crew.",
        ),
        canon_facts=[],
        planner_rules="Macro beats must progress.",
        drafter_rules="Every paragraph keeps tension.",
        editor_rules="Reject luck-based resolution.",
    )

    assert "[Planner Rules]" in block
    assert "Macro beats must progress." in block
    assert "[Drafter Rules]" in block
    assert "Every paragraph keeps tension." in block
    assert "[Editor Rules]" in block
    assert "Reject luck-based resolution." in block


def test_build_scoped_context_block_includes_global_story_anchor() -> None:
    block = build_scoped_context_block(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Escalate the standoff.",
            conflict="Trust is collapsing.",
            stakes="A failed negotiation fractures the alliance.",
            outcome="End with a hard choice.",
            ending_beat="Close on a vote that splits the bridge crew.",
        ),
        canon_facts=[],
        global_story_anchor="Chapter 1 Anchor: Arrival at the station.",
    )

    assert "[Global Story Anchor]" in block
    assert "Chapter 1 Anchor: Arrival at the station." in block


def test_build_scoped_context_block_dedupes_and_caps_inputs() -> None:
    long_value = "A" * 260
    block = build_scoped_context_block(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Escalate.",
            conflict="Collapse.",
            stakes="Break trust.",
            outcome="Shift.",
            ending_beat="Force a hard pivot.",
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


def test_compose_budgeted_prompt_uses_model_aware_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        "storycraftr.tui.context_builder.resolve_model_context",
        lambda provider, model_id: ModelContextSpec(
            provider="openrouter",
            model_id=model_id,
            context_window_tokens=32768,
            default_output_reserve_tokens=4096,
            max_completion_tokens=4096,
            source="openrouter-live-discovery",
        ),
    )
    prompt, budget = compose_budgeted_prompt(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Escalate.",
            conflict="Collapse.",
            stakes="Break trust.",
            outcome="Shift.",
            ending_beat="Force a hard pivot.",
        ),
        canon_facts=["Mira is the ship navigator."],
        user_prompt="Continue the scene with pressure.",
        provider="openrouter",
        model_id="openrouter/free",
        output_reserve_tokens=4096,
        retrieved_context=["Bridge logs confirm sabotage."],
        recent_turns=["User: tighten pacing", "Assistant: pacing tightened"],
    )

    assert budget.context_window_tokens == 32768
    assert budget.output_reserve_tokens == 4096
    assert budget.input_budget_tokens == 28672
    assert "[Scene Plan]" in prompt
    assert "[User Instruction]" in prompt


def test_compose_budgeted_prompt_prunes_in_priority_order() -> None:
    huge = "X" * 15000
    prompt, _ = compose_budgeted_prompt(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Keep chapter continuity.",
            conflict="Pacing pressure rises.",
            stakes="Losing this scene breaks canon intent.",
            outcome="Land on a sharp pivot.",
            ending_beat="End with a decision that reorients chapter momentum.",
        ),
        canon_facts=[
            f"Canon fact one {huge}",
            f"Canon fact two {huge}",
        ],
        user_prompt="Continue the chapter.",
        provider="unknown",
        model_id="unknown",
        output_reserve_tokens=7900,
        retrieved_context=[
            huge,
            huge,
            huge,
            huge,
            huge,
            huge,
            huge,
            huge,
        ],
        recent_turns=[
            f"User: {huge}",
            f"Assistant: {huge}",
            f"User: {huge}",
            f"Assistant: {huge}",
            f"User: {huge}",
            f"Assistant: {huge}",
            f"User: {huge}",
            f"Assistant: {huge}",
        ],
        max_retrieval_chunks=8,
        max_recent_turns=8,
    )

    # Lower-priority sections should disappear before high-priority constraints.
    if "[Recent Dialogue]" not in prompt:
        assert "[Relevant Context]" not in prompt
    assert "[Canon Constraints]" in prompt
    assert "Canon fact one" in prompt


def test_compose_budgeted_prompt_clamps_reserve_to_model_max_completion(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "storycraftr.tui.context_builder.resolve_model_context",
        lambda provider, model_id: ModelContextSpec(
            provider="openrouter",
            model_id=model_id,
            context_window_tokens=20000,
            default_output_reserve_tokens=4096,
            max_completion_tokens=1024,
            source="test",
        ),
    )

    _prompt, budget = compose_budgeted_prompt(
        state=_state(),
        scene_plan=ScenePlan(
            goal="Escalate.",
            conflict="Collapse.",
            stakes="Break trust.",
            outcome="Shift.",
            ending_beat="Force a hard pivot.",
        ),
        canon_facts=["Mira is the ship navigator."],
        user_prompt="Continue the scene with pressure.",
        provider="openrouter",
        model_id="openrouter/free",
        output_reserve_tokens=5000,
    )

    assert budget.context_window_tokens == 20000
    assert budget.output_reserve_tokens == 1024
    assert budget.input_budget_tokens == 18976
