from __future__ import annotations

from storycraftr.prompts.craft_rules import load_craft_rule_set


def test_load_craft_rule_set_returns_non_empty_fragments() -> None:
    rules = load_craft_rule_set()

    assert "System Flow" in rules.planner
    assert "Stimulus-Response" in rules.drafter
    assert "Cause and effect is absolute" in rules.editor
