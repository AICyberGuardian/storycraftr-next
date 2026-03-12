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
        outcome=f"Decides outcome {label}",
    )


def _long_scene(label: str, words: int = 280) -> str:
    return " ".join(f"{label}{idx}" for idx in range(words)) + "."


def _scene_from_directive(
    directive: SceneDirective,
    *,
    label: str,
    filler_words: int = 240,
) -> str:
    core = " ".join(
        [
            f"{label} {directive.goal}.",
            f"{label} {directive.conflict}.",
            f"{label} because {directive.stakes}.",
            f"{label} {directive.outcome}.",
        ]
    )
    filler = " ".join(f"{label}{idx}" for idx in range(filler_words))
    return f"{core} {filler}."


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


def test_generate_draft_text_continues_truncated_output_instead_of_resetting() -> None:
    retry_prompts: list[str] = []
    truncated_seed = " ".join(f"vesper{i}" for i in range(70)) + ","

    def _retry_draft(*args):
        if len(args) >= 4 and isinstance(args[3], str):
            retry_prompts.append(args[3])
        return " ".join(f"continuation{i}" for i in range(45)) + "."

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [_directive("a")],
        draft_scene=lambda directive, chapter, scene: truncated_seed,
        edit_scene=lambda directive, draft, chapter, scene: draft,
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        min_scene_words=100,
    )

    draft = engine._generate_draft_text(_directive("a"), 1, 1)

    assert "vesper0" in draft
    assert "continuation44" in draft
    assert retry_prompts
    assert "CRITICAL: Continue exactly from this point." in retry_prompts[0]
    assert (
        "DO NOT restart, summarize, paraphrase, or reframe prior text."
        in retry_prompts[0]
    )
    assert "Last complete sentence:" in retry_prompts[0]
    assert "Unfinished fragment:" in retry_prompts[0]
    assert "scene_directive" not in retry_prompts[0].lower()


def test_generate_draft_text_falls_back_to_full_rewrite_after_two_continuations() -> (
    None
):
    retry_prompts: list[str] = []
    attempt_counter = {"count": 0}
    truncated_seed = " ".join(f"tail{i}" for i in range(90)) + ","

    def _retry_draft(*args):
        if len(args) >= 4 and isinstance(args[3], str):
            retry_prompts.append(args[3])
        attempt_counter["count"] += 1
        if attempt_counter["count"] <= 2:
            return " ".join(f"cont{i}" for i in range(70)) + ","
        return "Lyra reaches the gate and completes the handoff in full view."

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [_directive("a")],
        draft_scene=lambda directive, chapter, scene: truncated_seed,
        edit_scene=lambda directive, draft, chapter, scene: draft,
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
    )

    draft = engine._generate_draft_text(_directive("a"), 1, 1)

    assert attempt_counter["count"] == 3
    assert "Continue exactly" in retry_prompts[0]
    assert "Continue exactly" in retry_prompts[1]
    assert (
        "Continuation attempts failed; rewrite this scene from scratch."
        in retry_prompts[2]
    )
    assert "completes the handoff" in draft


def test_draft_continuation_prompt_uses_local_buffer_not_memory_context() -> None:
    retry_prompts: list[str] = []
    fetched_memory: list[tuple[int, int]] = []

    truncated = " ".join(
        [
            "Mara",
            "slips",
            "into",
            "the",
            "archive",
            "vault",
            "and",
            "reaches",
            "for",
            "the",
            "seal",
            "while",
            "the",
            "alarms",
            "begin",
            "to",
        ]
        * 7
    )

    def _fetch_context(
        chapter_number: int,
        scene_number: int,
        directive: SceneDirective,
        top_k: int,
    ) -> str:
        del directive, top_k
        fetched_memory.append((chapter_number, scene_number))
        return "RECENT CONTEXT: remote memory should never drive continuation"

    def _retry_draft(*args):
        if len(args) >= 4 and isinstance(args[3], str):
            retry_prompts.append(args[3])
        return "She forces the lock and keeps moving."

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [_directive("a")],
        draft_scene=lambda directive, chapter, scene: truncated,
        edit_scene=lambda directive, draft, chapter, scene: draft,
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        scene_memory_fetch_context=_fetch_context,
    )

    draft = engine._generate_draft_text(_directive("a"), 1, 1)

    assert fetched_memory == [(1, 1)]
    assert retry_prompts
    assert "Last 120 words:" in retry_prompts[0]
    assert "Failing guard reason:" in retry_prompts[0]
    assert "Continue exactly" in retry_prompts[0]
    assert "remote memory should never drive continuation" not in retry_prompts[0]
    assert "keeps moving" in draft


def test_generate_edited_text_repairs_when_python_pre_guard_fails() -> None:
    retry_prompts: list[str] = []
    edit_calls = {"count": 0}
    directive = SceneDirective(
        goal="Mara infiltrates the archive",
        conflict="Captain Rho blocks the vault",
        stakes="The rebellion loses leverage if the ledger disappears",
        outcome="Mara seizes the ledger and confronts Captain Rho",
    )

    def _edit(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        del directive, draft, chapter, scene
        edit_calls["count"] += 1
        if edit_calls["count"] == 1:
            return (
                "The bells ring over the river while crowds flee the plaza. "
                "No one claims the ledger and no decision is made."
            )
        return (
            "Mara grabs the ledger and confronts the captain at dawn. "
            "She forces a decision before the gates close."
        )

    def _retry_draft(*args):
        if len(args) >= 4 and isinstance(args[3], str):
            retry_prompts.append(args[3])
        return "Mara steadies herself and prepares to act."

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [_directive("a")],
        draft_scene=lambda directive, chapter, scene: "Mara enters the square.",
        edit_scene=_edit,
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
    )

    final_directive, edited = engine._generate_edited_text(
        directive,
        "Mara enters the square.",
        1,
        1,
    )

    assert final_directive.outcome == directive.outcome
    assert "forces a decision" in edited
    assert retry_prompts
    assert "CRITICAL CORRECTION" in retry_prompts[0]


def test_scene_structure_repair_uses_local_attempts_before_planner_repair() -> None:
    retry_prompts: list[str] = []
    planner_calls = {"count": 0}
    edit_calls = {"count": 0}

    directive = SceneDirective(
        goal="Lyra reaches the sealed gate",
        conflict="City guards block the route",
        stakes="The rebellion message is lost if Lyra fails",
        outcome="Lyra decides to cross through the guard cordon",
    )

    def _edit(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        del directive, draft, chapter, scene
        edit_calls["count"] += 1
        if edit_calls["count"] < 3:
            return " ".join(f"flat{i}" for i in range(170)) + "."
        return _scene_from_directive(
            SceneDirective(
                goal="Lyra reaches the sealed gate",
                conflict="City guards block the route",
                stakes="The rebellion message is lost if Lyra fails",
                outcome="Lyra decides to cross through the guard cordon",
            ),
            label="repair",
            filler_words=210,
        )

    def _retry_draft(*args):
        if len(args) >= 4 and isinstance(args[3], str):
            retry_prompts.append(args[3])
        return _scene_from_directive(directive, label="retry", filler_words=180)

    def _repair_directive(
        current: SceneDirective,
        chapter: int,
        scene: int,
        reason: str,
    ) -> SceneDirective:
        del chapter, scene, reason
        planner_calls["count"] += 1
        return current

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [_directive("a")],
        draft_scene=lambda directive, chapter, scene: _scene_from_directive(
            directive,
            label="draft",
            filler_words=180,
        ),
        edit_scene=_edit,
        stitch_chapter=lambda scenes, chapter: "\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        repair_scene_directive=_repair_directive,
        enforce_scene_structure_contract=True,
        min_scene_words=120,
        max_scene_generation_attempts=3,
    )

    final_directive, edited = engine._generate_edited_text(
        directive,
        _scene_from_directive(directive, label="seed", filler_words=180),
        1,
        1,
    )

    assert planner_calls["count"] == 1
    assert len(retry_prompts) >= 2
    assert "Exact validation error:" in retry_prompts[0]
    assert "Current goal:" in retry_prompts[0]
    assert "Do not invent new locations, factions, or events" in retry_prompts[0]
    assert "guard cordon" in edited
    assert final_directive.outcome == directive.outcome


def test_required_outline_thread_missing_triggers_scene_local_repair_first() -> None:
    retry_prompts: list[str] = []
    used_repair = {"count": 0}

    directives = [
        SceneDirective(
            goal="Lyra meets the courier",
            conflict="City guards patrol the quay",
            stakes="The rebellion network is exposed if she fails",
            outcome="Lyra decides to protect the tunnel route at dawn",
        ),
        SceneDirective(
            goal="Lyra crosses the market",
            conflict="Guards tighten the checkpoint",
            stakes="Her rebel contact will be captured",
            outcome="Lyra decides to reroute the rebellion courier path",
        ),
        SceneDirective(
            goal="Lyra reaches the archive",
            conflict="The guard captain challenges her papers",
            stakes="The courier records vanish if she delays",
            outcome="Lyra decides to expose the rebellion informant",
        ),
    ]

    def _draft(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        *extra,
    ) -> str:
        del chapter, scene, extra
        return _scene_from_directive(directive, label="draft", filler_words=210)

    def _edit(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        del draft, chapter
        if scene == 1:
            # Intentionally omit "city seal" to trigger localized repair.
            text = _scene_from_directive(directive, label="edit", filler_words=210)
            return text.replace("city seal", "harbor lock")
        return _scene_from_directive(directive, label=f"edit{scene}", filler_words=210)

    def _retry_draft(*args):
        directive = args[0]
        if len(args) >= 4 and isinstance(args[3], str):
            retry_prompts.append(args[3])
        used_repair["count"] += 1
        return (
            _scene_from_directive(directive, label="repair", filler_words=180)
            + " The city seal remains central to the rebellion stakes."
        )

    committed: list[tuple[dict[str, str], int]] = []
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: (
            "Outline requires rebellion continuity with city seal and guards"
        ),
        build_scene_plan=lambda outline, chapter: directives,
        draft_scene=_draft,
        edit_scene=_edit,
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: committed.append((update, chapter)),
        retry_draft_scene=_retry_draft,
        min_scene_words=100,
        min_chapter_words=300,
        enforce_scene_structure_contract=True,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)
    assert status.stage == BookEngineStage.STATE_REVIEW
    status = engine.approve_state_commit(approved=True)

    assert status.stage == BookEngineStage.COMPLETE
    assert committed
    assert used_repair["count"] >= 1
    assert any(
        "CRITICAL: The scene must explicitly realize this required thread: city seal."
        in prompt
        for prompt in retry_prompts
    )


def test_book_engine_uses_scene_memory_and_purges_after_commit() -> None:
    stored: list[tuple[int, int, str, str]] = []
    fetched: list[tuple[int, int]] = []
    purged: list[int] = []

    def _fetch_context(
        chapter_number: int,
        scene_number: int,
        directive: SceneDirective,
        top_k: int,
    ) -> str:
        del directive, top_k
        fetched.append((chapter_number, scene_number))
        return "[chapter 1 scene 1 edited] Prior beat context."

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            _directive("a"),
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene, *extra: _scene_from_directive(
            directive,
            label=f"draft{scene}",
            filler_words=220,
        ),
        edit_scene=lambda directive, draft, chapter, scene: _scene_from_directive(
            directive,
            label=f"edit{scene}",
            filler_words=220,
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        scene_memory_store=lambda c, s, stage, text: stored.append((c, s, stage, text)),
        scene_memory_fetch_context=_fetch_context,
        scene_memory_purge=lambda chapter: purged.append(chapter),
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    engine.approve_outline(approved=True)
    status = engine.approve_state_commit(approved=True)

    assert status.stage == BookEngineStage.COMPLETE
    assert fetched
    assert any(stage == "draft" for _, _, stage, _ in stored)
    assert any(stage == "edited" for _, _, stage, _ in stored)
    assert purged == [1]


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


def test_book_engine_retries_scene_with_targeted_structure_correction() -> None:
    repair_payloads: list[tuple[str | None, bool]] = []
    scene_one_edits = {"count": 0}
    scene_one_directive = SceneDirective(
        goal="Lyra seeks proof of the hidden rebellion",
        conflict="City guards crowd the alley and block her contact",
        stakes="If caught Lyra will be executed as a rebel courier",
        outcome="Lyra discovers the coded message and decides to find the scribe",
    )

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        del directive, chapter
        if scene == 1:
            scene_one_edits["count"] += 1
            if scene_one_edits["count"] == 1:
                return (
                    "Lyra stalked the alley for proof while the guards pressed closer. "
                    "The contact never appeared, and she slipped away because the risk "
                    "of capture was rising around her. "
                    + " ".join(f"drift{idx}" for idx in range(260))
                    + "."
                )
        return draft

    def _retry_draft(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        del chapter
        if scene == 1:
            repair_payloads.append((repair_directive, repair_in_system_prompt))
        return _scene_from_directive(directive, label=f"retry{scene}")

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            scene_one_directive,
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _scene_from_directive(
            directive,
            label=f"draft{scene}",
        ),
        edit_scene=_edit_scene,
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        min_scene_words=250,
        min_chapter_words=750,
        enforce_scene_structure_contract=True,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert repair_payloads
    repair_text, used_system_prompt = repair_payloads[0]
    assert used_system_prompt is True
    assert repair_text is not None
    assert "approved outcome" in repair_text.lower()
    assert scene_one_directive.outcome in repair_text


def test_book_engine_injects_pov_correction_on_chapter_retry() -> None:
    repair_payloads: list[tuple[str | None, bool]] = []
    directive = SceneDirective(
        goal="Lyra infiltrates the archive to recover the ledger",
        conflict="Lyra must avoid the guard captain and a locked inner vault",
        stakes="If Lyra fails the rebellion loses its only proof of corruption",
        outcome="Lyra decides to steal the guard ring and return before dawn",
    )

    def _draft_scene(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        del chapter
        if repair_directive is not None:
            repair_payloads.append((repair_directive, repair_in_system_prompt))
            return _scene_from_directive(directive, label=f"retry{scene}")
        return " ".join(f"generic{scene}_{idx}" for idx in range(280)) + "."

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [directive, directive, directive],
        draft_scene=_draft_scene,
        edit_scene=lambda directive, draft, chapter, scene: draft,
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"ok": True}]
        },
        commit_state_update=lambda update, chapter: None,
        min_scene_words=250,
        min_chapter_words=750,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert repair_payloads
    repair_text, used_system_prompt = repair_payloads[0]
    assert used_system_prompt is True
    assert repair_text is not None
    assert (
        "[CRITICAL SYSTEM CORRECTION: Your previous attempt was rejected because "
        "you completely omitted the required POV character: Lyra. You MUST write "
        "from their perspective.]" == repair_text
    )
    assert (
        status.pending_chapter.generation_diagnostics[
            "chapter_validation_last_retry_reason"
        ]
        == "missing_pov:Lyra"
    )


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


def test_book_engine_rejects_verb_like_goal_pov_token() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [_directive("a")],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
    )

    directive = SceneDirective(
        goal="Gather the hidden ledger before dawn",
        conflict="Captain Rho closes the vault route",
        stakes="The rebellion loses its only leverage",
        outcome="Lyra decides to force a crossing",
    )
    with pytest.raises(
        BookEngineError, match="goal must start with a character name, not a verb"
    ):
        engine._validate_scene_directive(directive, scene_number=1)


def test_book_engine_normalizes_invalid_pov_to_single_ledger_character() -> None:
    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [_directive("a")],
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}", 280),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}", 280
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {"chapter": str(chapter)},
        commit_state_update=lambda update, chapter: None,
        resolve_character_ledger_names=lambda: ("Lyra",),
    )

    directive = SceneDirective(
        goal="Gather proof before sunrise",
        conflict="Captain Rho blocks every gate",
        stakes="The courier network will be exposed",
        outcome="Lyra decides to cross through the cordon",
    )

    assert engine._normalized_scene_pov_hint(directive) == "Lyra"


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


def test_book_engine_injects_semantic_feedback_into_retry_draft_prompt() -> None:
    review_calls = {"count": 0}
    seen_repair_directives: list[str] = []
    first = True

    def _draft_scene(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        del directive, chapter, scene, repair_in_system_prompt
        seen_repair_directives.append(repair_directive or "")
        return _long_scene("draft", 280)

    def _stitch(_scenes: list[str], _chapter: int) -> str:
        nonlocal first
        if first:
            first = False
            return _long_scene("semantic-first", 820)
        return _long_scene("semantic-retry", 820)

    def _semantic_review(
        chapter_text: str,
        chapter_number: int,
        outline_text: str,
    ) -> tuple[bool, str | None]:
        del chapter_text, chapter_number, outline_text
        review_calls["count"] += 1
        if review_calls["count"] == 1:
            return False, "skipped interrogation scene"
        return True, None

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
        stitch_chapter=_stitch,
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        min_scene_words=225,
        min_chapter_words=800,
        max_chapter_validation_attempts=3,
        enable_semantic_review=True,
        run_semantic_review=_semantic_review,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.pending_chapter is not None
    diagnostics = status.pending_chapter.generation_diagnostics
    assert diagnostics["chapter_validation_last_retry_reason"] == (
        "semantic_review:skipped interrogation scene"
    )
    assert (
        diagnostics["retry_feedback_last"]
        == "semantic_review:skipped interrogation scene"
    )
    assert any(
        "skipped interrogation scene" in directive
        for directive in seen_repair_directives
        if directive
    )


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


def test_book_engine_repairs_scene_directive_after_repeated_structure_drift() -> None:
    repaired_outcome = "Lyra reveals the coded message and chooses the eastern tunnels"
    repair_calls: list[tuple[int, int, str]] = []
    retry_outcomes: list[str] = []
    scene_one_edits = {"count": 0}

    original_directive = SceneDirective(
        goal="Lyra seeks proof of the hidden rebellion",
        conflict="City guards crowd the alley and block her contact",
        stakes="If caught Lyra will be executed as a rebel courier",
        outcome="Lyra discovers the coded message and decides to find the scribe",
    )

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter: int,
        scene: int,
    ) -> str:
        del directive, chapter
        if scene == 1:
            scene_one_edits["count"] += 1
            if scene_one_edits["count"] < 3:
                return (
                    "Lyra moved through the alley under pressure from the guard patrol, "
                    "but the scene ended on a detour without the required turn. "
                    + " ".join(f"miss{idx}" for idx in range(260))
                    + "."
                )
        return draft

    def _retry_draft(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        del chapter, repair_directive, repair_in_system_prompt
        if scene == 1:
            retry_outcomes.append(directive.outcome)
        return _scene_from_directive(directive, label=f"retry{scene}")

    def _repair_scene_directive(
        directive: SceneDirective,
        chapter: int,
        scene: int,
        failure_reason: str,
    ) -> SceneDirective:
        del directive
        repair_calls.append((chapter, scene, failure_reason))
        return SceneDirective(
            goal=original_directive.goal,
            conflict=original_directive.conflict,
            stakes=original_directive.stakes,
            outcome=repaired_outcome,
        )

    engine = BookEngine(
        build_outline=lambda seed, chapter, history: "outline",
        build_scene_plan=lambda outline, chapter: [
            original_directive,
            _directive("b"),
            _directive("c"),
        ],
        draft_scene=lambda directive, chapter, scene: _scene_from_directive(
            directive,
            label=f"draft{scene}",
        ),
        edit_scene=_edit_scene,
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        retry_draft_scene=_retry_draft,
        repair_scene_directive=_repair_scene_directive,
        min_scene_words=250,
        min_chapter_words=750,
        enforce_scene_structure_contract=True,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert repair_calls == [(1, 1, "scene_structure_missing:outcome")]
    assert retry_outcomes[-1] == repaired_outcome
    assert status.pending_chapter is not None
    assert (
        status.pending_chapter.scene_artifacts[0].directive.outcome == repaired_outcome
    )


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


def test_book_engine_retries_when_stitch_summarization_detected() -> None:
    retry_reasons: list[str] = []
    stitch_calls = {"count": 0}

    def _stitch(scenes: list[str], chapter: int) -> str:
        del chapter
        stitch_calls["count"] += 1
        if stitch_calls["count"] == 1:
            # Deliberately compress output to trigger stitch parity guard.
            return " ".join("summary" for _ in range(600))
        return "\n\n".join(scenes)

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
        stitch_chapter=_stitch,
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        min_scene_words=250,
        min_chapter_words=500,
        on_chapter_validation_retry=lambda attempt, total, reason: retry_reasons.append(
            reason
        ),
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    status = engine.approve_outline(approved=True)

    assert status.stage == BookEngineStage.STATE_REVIEW
    assert status.pending_chapter is not None
    assert stitch_calls["count"] == 2
    assert retry_reasons == []
    diagnostics = status.pending_chapter.generation_diagnostics
    assert diagnostics["stitch_retry_reason"].startswith(
        "stitcher_summarization_detected"
    )


def test_book_engine_persists_coherence_failure_before_halt() -> None:
    persisted: list[tuple[int, str, str]] = []

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
        draft_scene=lambda directive, chapter, scene: _long_scene(f"draft{scene}"),
        edit_scene=lambda directive, draft, chapter, scene: _long_scene(
            f"scene{scene}"
        ),
        stitch_chapter=lambda scenes, chapter: "\n\n".join(scenes),
        derive_state_update=lambda chapter_text, chapter: {
            "operations": [{"chapter": chapter}]
        },
        commit_state_update=lambda update, chapter: None,
        run_coherence_review=_coherence,
        persist_coherence_failure=lambda chapter, reason, text: persisted.append(
            (chapter, reason, text)
        ),
        min_scene_words=250,
        min_chapter_words=800,
        enforce_coherence_each_chapter=True,
    )

    engine.start(seed_markdown="# seed", target_chapters=1)
    with pytest.raises(BookEngineError, match="Coherence gate rejected chapter"):
        engine.approve_outline(approved=True)

    assert len(persisted) == 1
    chapter_number, reason, stitched_text = persisted[0]
    assert chapter_number == 1
    assert "severe canon contradiction" in reason
    assert stitched_text.strip()
