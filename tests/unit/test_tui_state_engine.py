from __future__ import annotations

from pathlib import Path

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

    assert "[Narrative State]" in prompt
    assert "Active Chapter: 3" in prompt
    assert "Active Scene: Reveal" in prompt
    assert "[User Prompt]" in prompt
    assert "Draft the next scene with sharper tension." in prompt


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

    assert "[Active Constraints]" in prompt
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

    assert "[Active Constraints]" not in prompt


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
