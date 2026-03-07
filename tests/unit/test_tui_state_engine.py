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
    assert "Chapter=2: Chapter 2" in state.memory_strip
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


def test_state_engine_sorts_double_digit_chapters_numerically(tmp_path) -> None:
    """chapter-10.md must come after chapter-9.md, not between chapter-1.md and chapter-2.md."""

    for n in [1, 2, 9, 10, 11]:
        _write(
            tmp_path / "chapters" / f"chapter-{n}.md",
            f"""---
title: Chapter {n} Title
scene: Scene {n}
arc: Act I
---
# Chapter {n}
Body
""",
        )

    engine = NarrativeStateEngine(book_path=str(tmp_path), cache_ttl_seconds=60)
    state = engine.get_state(force_refresh=True)

    chapter_numbers = [c.number for c in state.chapters]
    assert chapter_numbers == sorted(chapter_numbers), (
        f"Chapters must be in numeric order, got: {chapter_numbers}"
    )
    # Last chapter should be 11, not 9 (which lexicographic sort would give after 1)
    assert state.active_chapter == 11
    assert "Ch11" in state.timeline_strip
