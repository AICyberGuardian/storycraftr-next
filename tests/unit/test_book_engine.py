from __future__ import annotations

import pytest

from storycraftr.agent.book_engine import (
    BookEngine,
    BookEngineError,
    BookEngineStage,
)
from storycraftr.agent.narrative_state import SceneDirective


def _directive(label: str) -> SceneDirective:
    return SceneDirective(
        goal=f"Goal {label}",
        conflict=f"Conflict {label}",
        stakes=f"Stakes {label}",
        outcome=f"Outcome {label}",
    )


def test_book_engine_runs_single_chapter_with_approvals() -> None:
    committed: list[tuple[dict[str, str], int]] = []

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: f"outline-{chapter}",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: f"draft-{chapter}-{scene}",
        edit_scene=lambda directive, draft, chapter, scene: f"edited-{chapter}-{scene}",
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: committed.append((update, chapter)),
    )

    status = engine.start(seed_markdown="# seed", target_chapters=1)
    assert status.stage == BookEngineStage.OUTLINE_REVIEW
    assert status.pending_outline == "outline-1"

    status = engine.approve_outline(approved=True)
    assert status.stage == BookEngineStage.STATE_REVIEW
    assert status.pending_chapter is not None
    assert status.pending_chapter.chapter_number == 1
    assert len(status.pending_chapter.scene_artifacts) == 3

    status = engine.approve_state_commit(approved=True)
    assert status.stage == BookEngineStage.COMPLETE
    assert len(committed) == 1
    assert committed[0][1] == 1


def test_book_engine_fails_closed_when_scene_count_is_out_of_bounds() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: f"outline-{chapter}",
        build_scene_plan=lambda outline, chapter: [_directive("only")],
        draft_scene=lambda directive, chapter, scene: "draft",
        edit_scene=lambda directive, draft, chapter, scene: "edited",
        stitch_chapter=lambda scenes, chapter: "stitched",
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="between 3 and 5"):
        engine.approve_outline(approved=True)


def test_book_engine_retries_edit_with_fallback_draft_once() -> None:
    calls = {"edit": 0, "retry": 0}

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        calls["edit"] += 1
        if calls["edit"] == 1:
            raise RuntimeError("primary editor failed")
        return f"edited-{scene}"

    def _retry_draft(directive: SceneDirective, chapter: int, scene: int) -> str:
        calls["retry"] += 1
        return f"fallback-draft-{scene}"

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: f"draft-{scene}",
        edit_scene=_edit_scene,
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert calls["retry"] == 1
    assert calls["edit"] >= 2


def test_book_engine_triggers_coherence_gate_every_interval() -> None:
    coherence_calls: list[int] = []

    def _coherence(seed: str, history: tuple[object, ...]) -> str:
        coherence_calls.append(len(history))
        return "coherence-ok"

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: f"outline-{chapter}",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: f"draft-{chapter}-{scene}",
        edit_scene=lambda directive, draft, chapter, scene: f"edited-{chapter}-{scene}",
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        run_coherence_review=_coherence,
        coherence_interval=2,
    )

    engine.start(seed_markdown="# seed", target_chapters=2)
    engine.approve_outline(approved=True)
    engine.approve_state_commit(approved=True)
    engine.approve_outline(approved=True)
    status = engine.approve_state_commit(approved=True)

    assert status.stage == BookEngineStage.COMPLETE
    assert coherence_calls == [2]


def test_book_engine_pauses_before_state_commit_side_effects() -> None:
    committed: list[int] = []

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: "draft",
        edit_scene=lambda directive, draft, chapter, scene: "edited",
        stitch_chapter=lambda scenes, chapter: "stitched",
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: committed.append(chapter),
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert committed == []

    status = engine.approve_state_commit(approved=True)
    assert status.stage == BookEngineStage.COMPLETE
    assert committed == [1]


def test_book_engine_pushes_soft_memory_after_state_commit() -> None:
    committed: list[int] = []
    pushed: list[int] = []

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: "draft",
        edit_scene=lambda directive, draft, chapter, scene: "edited",
        stitch_chapter=lambda scenes, chapter: "stitched",
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: committed.append(chapter),
        push_soft_memory=lambda chapter: pushed.append(chapter.chapter_number),
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    engine.approve_outline(approved=True)
    status = engine.approve_state_commit(approved=True)

    assert status.stage == BookEngineStage.COMPLETE
    assert committed == [1]
    assert pushed == [1]


def test_book_engine_coherence_violation_fails_closed_without_chapter_write(
    tmp_path,
) -> None:
    chapter_file = tmp_path / "chapters" / "chapter-1.md"

    def _mock_violation_checker(_update: object) -> bool:
        raise RuntimeError("mock llm high-severity coherence violation")

    def _commit_state_update(_update: dict[str, str], _chapter: int) -> None:
        chapter_file.parent.mkdir(parents=True, exist_ok=True)
        chapter_file.write_text("should-not-exist\n", encoding="utf-8")

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: "draft",
        edit_scene=lambda directive, draft, chapter, scene: "edited",
        stitch_chapter=lambda scenes, chapter: "stitched",
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=_commit_state_update,
        check_severe_canon_violation=_mock_violation_checker,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="Canon violation check failed"):
        engine.approve_outline(approved=True)

    assert not chapter_file.exists()
