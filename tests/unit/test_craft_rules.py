from __future__ import annotations

from storycraftr.prompts.craft_rules import load_craft_rule_set


def test_load_craft_rule_set_returns_non_empty_fragments() -> None:
    rules = load_craft_rule_set()

    assert "SCENE ENGINE" in rules.planner.text
    assert "BEAT EXECUTION" in rules.drafter.text
    assert "VERIFICATION" in rules.editor.text
    assert "TRANSITIONS" in rules.stitcher.text


def test_load_craft_rule_set_parses_frontmatter_metadata() -> None:
    rules = load_craft_rule_set()

    assert rules.planner.role == "planner"
    assert rules.drafter.role == "drafter"
    assert rules.editor.role == "editor"
    assert rules.stitcher.role == "stitcher"
    assert rules.planner.max_tokens > 0
    assert rules.stitcher.max_tokens > 0
