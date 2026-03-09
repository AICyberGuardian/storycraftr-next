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


def _long_scene(label: str, words: int = 280) -> str:
    return " ".join(f"{label}{idx}" for idx in range(words)) + "."


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

    def _coherence(seed: str, history: tuple[object, ...]) -> tuple[bool, str]:
        coherence_calls.append(len(history))
        return True, "coherence-ok"

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


def test_book_engine_forces_coherence_gate_on_severe_violation_even_off_interval() -> (
    None
):
    coherence_calls: list[int] = []

    def _coherence(seed: str, history: tuple[object, ...]) -> tuple[bool, str]:
        coherence_calls.append(len(history))
        return True, "coherence-ok"

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}"),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}"
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        run_coherence_review=_coherence,
        check_severe_canon_violation=lambda _update: True,
        coherence_interval=99,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert coherence_calls == [1]


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


def test_book_engine_fails_closed_on_short_chapter_output() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: "small draft.",
        edit_scene=lambda directive, draft, chapter, scene: "small edit.",
        stitch_chapter=lambda scenes, chapter: "too short",
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        min_chapter_words=750,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="below minimum word count"):
        engine.approve_outline(approved=True)


def test_book_engine_uses_unstitched_fallback_when_stitch_is_truncated() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "This chapter restarts and cuts off...",
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        min_scene_words=250,
        min_chapter_words=750,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert status.pending_chapter is not None
    assert "cuts off" not in status.pending_chapter.stitched_text
    assert status.pending_chapter.stitched_text.count("scene") > 700


def test_book_engine_retries_scene_when_edit_output_is_incomplete() -> None:
    calls = {"edit": 0, "retry": 0}

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        calls["edit"] += 1
        if calls["edit"] == 1:
            return "truncated output..."
        return _long_scene(f"scene{scene}", 280)

    def _retry_draft(directive: SceneDirective, chapter: int, scene: int) -> str:
        calls["retry"] += 1
        return _long_scene(f"retry{scene}", 280)

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=_edit_scene,
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        min_scene_words=250,
        min_chapter_words=750,
        max_scene_generation_attempts=3,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert calls["retry"] == 1
    assert calls["edit"] >= 2


def test_book_engine_fails_closed_on_duplicate_chapter_paragraph_loops() -> None:
    repeated_paragraph = " ".join(f"loop{idx}" for idx in range(170))
    duplicated = f"{repeated_paragraph}\n\n{repeated_paragraph}\n\n{repeated_paragraph}\n\n{repeated_paragraph}\n\n{repeated_paragraph}"

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: duplicated,
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"ok": True}]
        },
        commit_state_update=lambda update, chapter: None,
        min_scene_words=250,
        min_chapter_words=800,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="duplicate_paragraphs"):
        engine.approve_outline(approved=True)


def test_book_engine_fails_closed_on_empty_state_signal_when_guard_enabled() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"operations": []},
        commit_state_update=lambda update, chapter: None,
        min_scene_words=250,
        min_chapter_words=800,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="no meaningful update"):
        engine.approve_outline(approved=True)


def test_book_engine_fails_closed_on_empty_directive_field() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            SceneDirective(
                goal="goal", conflict="conflict", stakes="stakes", outcome=""
            ),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="Scene planning failed"):
        engine.approve_outline(approved=True)


def test_book_engine_fails_closed_on_weak_directive_field() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            SceneDirective(
                goal="steady goal",
                conflict="x",
                stakes="high stakes",
                outcome="clear outcome",
            ),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        min_directive_words=2,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="weak directive 'conflict'"):
        engine.approve_outline(approved=True)


def test_book_engine_records_generation_diagnostics_for_chapter_retries() -> None:
    stitch_calls = {"count": 0}
    repeated_paragraph = " ".join(f"loop{idx}" for idx in range(170))
    duplicated = (
        f"{repeated_paragraph}\n\n{repeated_paragraph}\n\n{repeated_paragraph}\n\n"
        f"{repeated_paragraph}\n\n{repeated_paragraph}"
    )

    def _stitch_with_retry(scenes: list[str], chapter: int) -> str:
        stitch_calls["count"] += 1
        if stitch_calls["count"] == 1:
            return duplicated
        return "\n\n".join(scenes)

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=_stitch_with_retry,
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        min_scene_words=250,
        min_chapter_words=800,
        max_chapter_validation_attempts=3,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.pending_chapter is not None
    diagnostics = status.pending_chapter.generation_diagnostics
    assert diagnostics["directive_quality_passed"] is True
    assert diagnostics["chapter_validation_attempts"] == 2
    assert diagnostics["chapter_validation_last_retry_reason"] == "duplicate_paragraphs"
    assert diagnostics["state_signal_meaningful"] is True
    assert diagnostics["state_signal_enforced"] is True


def test_book_engine_retries_when_semantic_review_rejects_chapter() -> None:
    stitch_calls = {"count": 0}
    review_calls = {"count": 0}

    def _stitch_with_retry(scenes: list[str], chapter: int) -> str:
        stitch_calls["count"] += 1
        if stitch_calls["count"] == 1:
            return _long_scene("draft-semantic", 820)
        return "\n\n".join(scenes)

    def _semantic_review(
        chapter_text: str,
        chapter_number: int,
        outline_text: str,
    ) -> tuple[bool, str | None]:
        review_calls["count"] += 1
        if review_calls["count"] == 1:
            return False, "canon drift"
        return True, None

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=_stitch_with_retry,
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        min_scene_words=250,
        min_chapter_words=800,
        max_chapter_validation_attempts=3,
        enable_semantic_review=True,
        run_semantic_review=_semantic_review,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.pending_chapter is not None
    diagnostics = status.pending_chapter.generation_diagnostics
    assert diagnostics["chapter_validation_attempts"] == 2
    assert (
        diagnostics["chapter_validation_last_retry_reason"]
        == "semantic_review:canon drift"
    )
    assert diagnostics["semantic_review_enabled"] is True
    assert diagnostics["semantic_review_passed"] is True
    assert diagnostics["semantic_review_last_reason"] is None


def test_book_engine_passes_scene_density_directive_on_short_scene_retry() -> None:
    retry_directives: list[str | None] = []
    edit_calls = {"count": 0}

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        del directive, chapter
        edit_calls["count"] += 1
        if edit_calls["count"] == 1:
            return "too short scene"
        return _long_scene(f"repaired-scene-{scene}", 280)

    def _retry_draft(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        repair_directive: str | None = None,
    ) -> str:
        del directive, chapter
        retry_directives.append(repair_directive)
        return _long_scene(f"retry-draft-{scene}", 280)

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=_edit_scene,
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        min_scene_words=250,
        min_chapter_words=800,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert retry_directives
    assert retry_directives[0] is not None
    assert "too short" in str(retry_directives[0]).lower()


def test_book_engine_invokes_retry_escalation_callbacks() -> None:
    scene_retry_events: list[tuple[int, int, int, str]] = []
    chapter_retry_events: list[tuple[int, int, str]] = []
    stitch_calls = {"count": 0}
    edit_calls = {"count": 0}

    repeated_paragraph = " ".join(f"loop{idx}" for idx in range(170))
    duplicated = (
        f"{repeated_paragraph}\n\n{repeated_paragraph}\n\n{repeated_paragraph}\n\n"
        f"{repeated_paragraph}\n\n{repeated_paragraph}"
    )

    def _stitch_with_retry(scenes: list[str], chapter: int) -> str:
        del scenes, chapter
        stitch_calls["count"] += 1
        if stitch_calls["count"] == 1:
            return duplicated
        return _long_scene("stitched", 820)

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        del directive, draft, chapter, scene
        edit_calls["count"] += 1
        if edit_calls["count"] == 1:
            return "short scene"
        return _long_scene("edited", 280)

    def _retry_draft(directive: SceneDirective, chapter: int, scene: int) -> str:
        del directive, chapter, scene
        return _long_scene("retry-scene", 280)

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=_edit_scene,
        stitch_chapter=_stitch_with_retry,
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        min_scene_words=250,
        min_chapter_words=800,
        max_chapter_validation_attempts=3,
        on_scene_generation_retry=(
            lambda chapter, scene, attempt, reason: scene_retry_events.append(
                (chapter, scene, attempt, reason)
            )
        ),
        on_chapter_validation_retry=(
            lambda attempt, total, reason: chapter_retry_events.append(
                (attempt, total, reason)
            )
        ),
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert scene_retry_events
    assert any(event[3] == "scene_too_short" for event in scene_retry_events)
    assert chapter_retry_events
    assert chapter_retry_events[0][0] == 1


def test_book_engine_runs_single_coherence_repair_attempt() -> None:
    coherence_calls = {"count": 0}
    repair_events: list[tuple[int, int, str]] = []
    draft_rules: list[str] = []

    def _draft_scene(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        del directive, chapter, scene, repair_in_system_prompt
        draft_rules.append(repair_directive or "")
        return _long_scene("draft", 280)

    def _coherence(seed: str, history: tuple[object, ...]) -> tuple[bool, str]:
        del seed, history
        coherence_calls["count"] += 1
        if coherence_calls["count"] == 1:
            return False, "hallucinated timeline jump"
        return True, "coherence-ok"

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=_draft_scene,
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        run_coherence_review=_coherence,
        on_coherence_repair_retry=lambda attempt, total, reason: repair_events.append(
            (attempt, total, reason)
        ),
        min_scene_words=250,
        min_chapter_words=800,
        enforce_coherence_each_chapter=True,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert status.pending_chapter is not None
    diagnostics = status.pending_chapter.generation_diagnostics
    assert diagnostics["coherence_gate_passed"] is True
    assert diagnostics["coherence_repair_attempts"] == 1
    assert "hallucinated timeline jump" in diagnostics["coherence_repair_reason"]
    assert repair_events == [(1, 2, "hallucinated timeline jump")]
    assert any("hallucinated timeline jump" in value for value in draft_rules)


def test_book_engine_fails_closed_when_coherence_repair_is_exhausted() -> None:
    def _coherence(seed: str, history: tuple[object, ...]) -> tuple[bool, str]:
        del seed, history
        return False, "severe canon contradiction"

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        run_coherence_review=_coherence,
        min_scene_words=250,
        min_chapter_words=800,
        enforce_coherence_each_chapter=True,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="Coherence gate rejected chapter"):
        engine.approve_outline(approved=True)
