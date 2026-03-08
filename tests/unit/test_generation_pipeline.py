from __future__ import annotations

import pytest

from storycraftr.agent.generation_pipeline import SceneGenerationPipeline


def _pipeline() -> SceneGenerationPipeline:
    return SceneGenerationPipeline(
        planner_rules="planner",
        drafter_rules="drafter",
        editor_rules="editor",
    )


def test_parse_scene_directive_accepts_plain_json() -> None:
    pipeline = _pipeline()

    directive = pipeline.parse_scene_directive(
        '{"goal":"Reach vault","conflict":"Guard blocks path","stakes":"Lose leverage","outcome":"No-and collapse"}'
    )

    assert directive.goal == "Reach vault"
    assert "Guard" in directive.conflict


def test_parse_scene_directive_accepts_markdown_json_block() -> None:
    pipeline = _pipeline()

    directive = pipeline.parse_scene_directive(
        """```json
{"goal":"Reach vault","conflict":"Guard blocks path","stakes":"Lose leverage","outcome":"No-and collapse"}
```"""
    )

    assert directive.stakes == "Lose leverage"


def test_parse_scene_directive_rejects_missing_json() -> None:
    pipeline = _pipeline()

    with pytest.raises(ValueError):
        pipeline.parse_scene_directive("No structured output")


def test_build_drafter_user_prompt_embeds_directive() -> None:
    pipeline = _pipeline()
    directive = pipeline.parse_scene_directive(
        '{"goal":"Reach vault","conflict":"Guard blocks path","stakes":"Lose leverage","outcome":"No-and collapse"}'
    )

    prompt = pipeline.build_drafter_user_prompt(
        user_input="Write the confrontation.",
        directive=directive,
    )

    assert "Drafter stage" in prompt
    assert "Goal: Reach vault" in prompt
    assert "User request: Write the confrontation." in prompt
