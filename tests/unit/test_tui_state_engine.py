from __future__ import annotations

from pathlib import Path

from storycraftr.agent.memory_manager import MemoryContextItem
from storycraftr.tui.state_engine import NarrativeStateEngine


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_state_engine_reads_frontmatter_and_outline_yaml(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
---
# Chapter 1
Body
""",
    )
    _write(
        tmp_path / "chapters" / "chapter-2.md",
        """---
scene: Confrontation
---
# Chapter 2
Body
""",
    )
    _write(
        tmp_path / "outline" / "chapter_arcs.yaml",
        """chapters:
  - chapter: 2
    arc: Act II
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state(force_refresh=True)

    assert state.active_chapter == 2
    assert state.active_scene == "Confrontation"
    assert state.active_arc == "Act II"
    assert "Chapter 2 - Chapter 2" in state.memory_strip
    assert "Arc: Act II" in state.memory_strip
    assert "Ch1 Setup" in state.timeline_strip
    assert "Ch2 Confrontation" in state.timeline_strip


def test_state_engine_applies_runtime_focus_overrides(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: First Move
scene: Opening
arc: Act I
---
# Chapter 1
Body
""",
    )
    _write(
        tmp_path / "chapters" / "chapter-2.md",
        """---
title: Rising Stakes
scene: Pivot
arc: Act II
---
# Chapter 2
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    engine.set_active_chapter(1)
    engine.set_active_scene("Bridge Scene")

    state = engine.get_state(force_refresh=True)

    assert state.active_chapter == 1
    assert state.active_scene == "Bridge Scene"
    assert state.active_arc == "Act I"


def test_compose_prompt_injects_state_block(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Anchor Chapter
scene: Setup
arc: Act I
---
# Chapter 1
This opening chapter establishes the long-term objective.
""",
    )
    _write(
        tmp_path / "chapters" / "chapter-3.md",
        """---
title: Turning Point
scene: Reveal
arc: Act II
---
# Chapter 3
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    prompt = engine.compose_prompt("Draft the next scene with sharper tension.")

    assert "[Scene Plan]" in prompt
    assert "Goal: Draft the next scene with sharper tension." in prompt
    assert "[Scoped Context]" in prompt
    assert "[Planner Rules]" in prompt
    assert "[Drafter Rules]" in prompt
    assert "[Editor Rules]" in prompt
    assert "[Global Story Anchor]" in prompt
    assert "Chapter 1 Anchor: Anchor Chapter" in prompt
    assert "Active Chapter: 3" in prompt
    assert "Active Scene: Reveal" in prompt
    assert "[User Instruction]" in prompt
    assert "Draft the next scene with sharper tension." in prompt


def test_compose_prompt_with_editor_rule_profile_only_includes_editor_rules(
    tmp_path,
) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Turning Point
scene: Reveal
arc: Act II
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    prompt = engine.compose_prompt(
        "Revise the scene.",
        rule_profile="editor",
    )

    assert "[Editor Rules]" in prompt
    assert "[Planner Rules]" not in prompt
    assert "[Drafter Rules]" not in prompt


def test_state_engine_tolerates_malformed_frontmatter(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-4.md",
        """---
title: Broken
scene: [oops
---
# Chapter 4
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state(force_refresh=True)

    assert state.active_chapter == 4
    assert state.active_scene == "Unknown"
    assert state.active_arc == "Unknown"
    assert "Arc unknown" in state.memory_strip
    assert state.timeline_strip == "Timeline: Chapter metadata incomplete"


def test_state_engine_skips_invalid_outline_yaml(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Opening
scene: Setup
---
# Chapter 1
Body
""",
    )
    _write(
        tmp_path / "outline" / "bad.yaml",
        "chapters: [",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state(force_refresh=True)

    assert state.active_chapter == 1
    assert state.active_scene == "Setup"


def test_state_engine_uses_placeholder_when_no_chapters(tmp_path) -> None:
    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)

    state = engine.get_state(force_refresh=True)

    assert state.memory_strip == "Narrative: Chapter context unavailable"
    assert state.timeline_strip == "Timeline: No scene map yet"


def test_state_engine_sorts_chapters_numerically(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-10.md",
        """---
scene: Late
---
# Chapter 10
Body
""",
    )
    _write(
        tmp_path / "chapters" / "chapter-2.md",
        """---
scene: Early
---
# Chapter 2
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state(force_refresh=True)

    assert "Ch2 Early" in state.timeline_strip
    assert "Ch10 Late" in state.timeline_strip
    assert state.timeline_strip.index("Ch2 Early") < state.timeline_strip.index(
        "Ch10 Late"
    )


def test_compose_prompt_includes_active_constraints_when_canon_exists(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )
    _write(
        tmp_path / "outline" / "canon.yml",
        """version: 1
chapters:
    "1":
        facts:
            - id: fact-001
              text: "Alex is the POV character."
              type: pov
              source: manual
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    prompt = engine.compose_prompt("Continue the chapter.")

    assert "[Canon Constraints]" in prompt
    assert "- Alex is the POV character." in prompt


def test_compose_prompt_omits_constraints_when_no_canon_facts(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    prompt = engine.compose_prompt("Continue the chapter.")

    assert "[Canon Constraints]" not in prompt


def test_compose_prompt_uses_only_active_chapter_canon_facts(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )
    _write(
        tmp_path / "chapters" / "chapter-2.md",
        """---
title: Collision
scene: Twist
arc: Act II
---
# Chapter 2
Body
""",
    )
    _write(
        tmp_path / "outline" / "canon.yml",
        """version: 1
chapters:
    "1":
        facts:
            - id: fact-001
              text: "Chapter one fact."
              type: event
              source: manual
    "2":
        facts:
            - id: fact-002
              text: "Chapter two fact."
              type: event
              source: manual
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    engine.set_active_chapter(2)
    prompt = engine.compose_prompt("Continue the chapter.")

    assert "Chapter two fact." in prompt
    assert "Chapter one fact." not in prompt


def test_compose_prompt_includes_memory_context_when_available(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)

    engine.memory_manager.get_context_items = lambda **_kwargs: [
        MemoryContextItem(
            source="intent",
            text="Elias intends to expose Mara before dawn.",
        ),
        MemoryContextItem(
            source="events",
            text="The bridge console logs already implicate the quartermaster.",
        ),
    ]

    prompt = engine.compose_prompt("Continue the confrontation.")

    assert "[Relevant Context]" in prompt
    assert "Intent: Elias intends to expose Mara before dawn." in prompt
    assert (
        "Memory: The bridge console logs already implicate the quartermaster." in prompt
    )


def test_get_memory_context_respects_token_budget(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state()
    long_text = "A" * 1200

    engine.memory_manager.get_context_items = lambda **_kwargs: [
        MemoryContextItem(source="intent", text=long_text),
        MemoryContextItem(source="events", text="short fallback"),
    ]

    lines = engine.get_memory_context(state=state, max_items=4, max_tokens=40)

    assert lines == []


def test_get_memory_context_passes_user_query_for_relevance(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state()
    captured_query = None

    def mock_get_items(**kwargs):
        nonlocal captured_query
        captured_query = kwargs.get("query")
        return [
            MemoryContextItem(
                source="relevant",
                text="The artifact pulses when Elias approaches.",
            )
        ]

    engine.memory_manager.get_context_items = mock_get_items

    lines = engine.get_memory_context(
        state=state, user_query="Describe the mysterious artifact.", max_items=4
    )

    assert captured_query == "Describe the mysterious artifact."
    assert len(lines) == 1
    assert "Memory: The artifact pulses when Elias approaches." in lines[0]


def test_get_memory_context_scales_budget_with_model_context_window(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state()

    # Large context model (128k) should get larger memory budget
    budget_large = engine._compute_memory_budget(provider="openai", model_id="gpt-4o")
    assert budget_large > 320  # Should be > default
    assert budget_large <= 1280  # Capped at max

    # Small context model (8k default) should get conservative budget
    budget_small = engine._compute_memory_budget(
        provider="unknown", model_id="unknown-model"
    )
    assert budget_small == 163  # 8192 * 0.02 = 163.84 truncated
    assert budget_small >= 160  # Floor enforced


def test_compose_prompt_includes_recent_turns_when_budget_allows(tmp_path) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    prompt = engine.compose_prompt(
        "Continue the chapter.",
        provider="openrouter",
        model_id="openrouter/free",
        output_reserve_tokens=4096,
        recent_turns=[
            "User: tighten POV",
            "Assistant: tightened POV and sensory detail",
        ],
    )

    assert "[Recent Dialogue]" in prompt
    assert "User: tighten POV" in prompt


def test_compose_prompt_with_diagnostics_persists_last_budget_metadata(
    tmp_path,
) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    prompt, budget, diagnostics = engine.compose_prompt_with_diagnostics(
        "Continue the chapter."
    )

    assert "[User Instruction]" in prompt
    assert engine.last_budget_metadata == budget
    assert engine.last_prompt_diagnostics == diagnostics


def test_compose_prompt_includes_structured_narrative_state_when_available(
    tmp_path,
) -> None:
    _write(
        tmp_path / "chapters" / "chapter-1.md",
        """---
title: Arrival
scene: Setup
arc: Act I
---
# Chapter 1
Body
""",
    )
    _write(
        tmp_path / "outline" / "narrative_state.json",
        '{"characters": {"Mira": {"status": "injured"}}, "world": {"Bridge": {"integrity": "critical"}}}',
    )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    prompt = engine.compose_prompt("Continue the chapter.")

    assert "[Structured Narrative State]" in prompt
    assert '"Mira"' in prompt
    assert '"integrity": "critical"' in prompt
