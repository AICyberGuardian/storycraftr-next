from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from storycraftr.agent.narrative_state import SceneDirective


class BookEngineError(RuntimeError):
    """Raised when the book engine encounters an invalid or unsafe transition."""


class BookEngineStage(str, Enum):
    """Finite-state machine stages for chapter generation orchestration."""

    IDLE = "idle"
    OUTLINE_REVIEW = "outline_review"
    STATE_REVIEW = "state_review"
    COMPLETE = "complete"


@dataclass(frozen=True)
class SceneRunArtifact:
    """Artifacts produced for a single scene in the chapter loop."""

    scene_number: int
    directive: SceneDirective
    draft_text: str
    edited_text: str


@dataclass(frozen=True)
class ChapterRunArtifact:
    """Artifacts produced for one completed chapter pipeline."""

    chapter_number: int
    outline_text: str
    scene_artifacts: tuple[SceneRunArtifact, ...]
    stitched_text: str
    state_update: Any
    coherence_review: str | None = None


@dataclass(frozen=True)
class EngineStatus:
    """Read-only status snapshot for UI/CLI integration surfaces."""

    stage: BookEngineStage
    current_chapter: int
    target_chapters: int
    pending_outline: str | None
    pending_chapter: ChapterRunArtifact | None


@dataclass
class BookEngine:
    """Disciplined chapter-generation state machine with approval checkpoints.

    This engine enforces the sequential flow:
    Outline -> Scene Plan -> Draft -> Edit -> Stitch -> State Update.

    The machine fails closed: invalid transitions, malformed outputs, and
    step exceptions raise `BookEngineError` and halt progression.
    """

    build_outline: Callable[[str, int, tuple[ChapterRunArtifact, ...]], str]
    build_scene_plan: Callable[[str, int], list[SceneDirective]]
    draft_scene: Callable[[SceneDirective, int, int], str]
    edit_scene: Callable[[SceneDirective, str, int, int], str]
    stitch_chapter: Callable[[list[str], int], str]
    derive_state_update: Callable[[str, int], Any]
    commit_state_update: Callable[[Any, int], None]
    push_soft_memory: Callable[[ChapterRunArtifact], None] | None = None
    retry_draft_scene: Callable[[SceneDirective, int, int], str] | None = None
    check_severe_canon_violation: Callable[[Any], bool] | None = None
    run_coherence_review: (
        Callable[[str, tuple[ChapterRunArtifact, ...]], str] | None
    ) = None
    coherence_interval: int = 5

    stage: BookEngineStage = BookEngineStage.IDLE
    seed_markdown: str = ""
    target_chapters: int = 0
    current_chapter: int = 1
    approved_outline: str = ""
    history: list[ChapterRunArtifact] = field(default_factory=list)
    _pending_outline: str | None = None
    _pending_chapter: ChapterRunArtifact | None = None

    def start(self, *, seed_markdown: str, target_chapters: int) -> EngineStatus:
        """Initialize engine run and generate the first outline for approval."""

        cleaned_seed = seed_markdown.strip()
        if not cleaned_seed:
            raise BookEngineError("seed_markdown must be non-empty")
        if target_chapters < 1:
            raise BookEngineError("target_chapters must be >= 1")

        self.seed_markdown = cleaned_seed
        self.target_chapters = target_chapters
        self.current_chapter = 1
        self.approved_outline = ""
        self.history.clear()
        self._pending_chapter = None

        self._pending_outline = self._generate_outline(self.current_chapter)
        self.stage = BookEngineStage.OUTLINE_REVIEW
        return self.status()

    def approve_outline(self, *, approved: bool) -> EngineStatus:
        """Approve or reject the pending outline and execute chapter pipeline."""

        if (
            self.stage != BookEngineStage.OUTLINE_REVIEW
            or self._pending_outline is None
        ):
            raise BookEngineError("No outline is pending approval")
        if not approved:
            raise BookEngineError("Outline rejected; engine stopped fail-closed")

        self.approved_outline = self._pending_outline
        self._pending_outline = None
        self._pending_chapter = self._execute_chapter_pipeline()
        self.stage = BookEngineStage.STATE_REVIEW
        return self.status()

    def approve_state_commit(self, *, approved: bool) -> EngineStatus:
        """Approve or reject state commit for the pending chapter artifact."""

        if self.stage != BookEngineStage.STATE_REVIEW or self._pending_chapter is None:
            raise BookEngineError("No chapter state update is pending approval")
        if not approved:
            raise BookEngineError("State commit rejected; engine stopped fail-closed")

        chapter = self._pending_chapter
        try:
            self.commit_state_update(chapter.state_update, chapter.chapter_number)
        except Exception as exc:
            raise BookEngineError(f"State commit failed: {exc}") from exc

        if self.push_soft_memory is not None:
            try:
                self.push_soft_memory(chapter)
            except Exception as exc:
                raise BookEngineError(f"Soft memory push failed: {exc}") from exc

        self.history.append(chapter)
        self._pending_chapter = None
        self.current_chapter += 1

        if len(self.history) >= self.target_chapters:
            self.stage = BookEngineStage.COMPLETE
            return self.status()

        self._pending_outline = self._generate_outline(self.current_chapter)
        self.stage = BookEngineStage.OUTLINE_REVIEW
        return self.status()

    def status(self) -> EngineStatus:
        """Return a read-only status snapshot for external orchestration layers."""

        return EngineStatus(
            stage=self.stage,
            current_chapter=self.current_chapter,
            target_chapters=self.target_chapters,
            pending_outline=self._pending_outline,
            pending_chapter=self._pending_chapter,
        )

    def _generate_outline(self, chapter_number: int) -> str:
        """Build the rolling outline text for the next chapter."""

        try:
            outline = self.build_outline(
                self.seed_markdown,
                chapter_number,
                tuple(self.history),
            )
        except Exception as exc:
            raise BookEngineError(f"Outline generation failed: {exc}") from exc

        cleaned = outline.strip()
        if not cleaned:
            raise BookEngineError("Outline generation produced empty text")
        return cleaned

    def _execute_chapter_pipeline(self) -> ChapterRunArtifact:
        """Execute the deterministic chapter assembly line after outline approval."""

        chapter_number = self.current_chapter

        try:
            directives = self.build_scene_plan(self.approved_outline, chapter_number)
        except Exception as exc:
            raise BookEngineError(f"Scene planning failed: {exc}") from exc

        if not 3 <= len(directives) <= 5:
            raise BookEngineError(
                "Scene planning must produce between 3 and 5 directives"
            )

        scene_artifacts: list[SceneRunArtifact] = []
        edited_scenes: list[str] = []
        for index, directive in enumerate(directives, start=1):
            draft_text = self._generate_draft_text(directive, chapter_number, index)
            edited_text = self._generate_edited_text(
                directive,
                draft_text,
                chapter_number,
                index,
            )
            scene_artifacts.append(
                SceneRunArtifact(
                    scene_number=index,
                    directive=directive,
                    draft_text=draft_text,
                    edited_text=edited_text,
                )
            )
            edited_scenes.append(edited_text)

        try:
            stitched = self.stitch_chapter(edited_scenes, chapter_number)
        except Exception as exc:
            raise BookEngineError(f"Chapter stitch failed: {exc}") from exc

        stitched_text = stitched.strip()
        if not stitched_text:
            raise BookEngineError("Chapter stitch produced empty text")

        try:
            state_update = self.derive_state_update(stitched_text, chapter_number)
        except Exception as exc:
            raise BookEngineError(f"State extraction failed: {exc}") from exc

        coherence_review: str | None = None
        should_run_gate = chapter_number % max(1, self.coherence_interval) == 0
        severe_violation = False
        if self.check_severe_canon_violation is not None:
            try:
                severe_violation = bool(self.check_severe_canon_violation(state_update))
            except Exception as exc:
                raise BookEngineError(f"Canon violation check failed: {exc}") from exc

        if (
            should_run_gate or severe_violation
        ) and self.run_coherence_review is not None:
            try:
                coherence_review = self.run_coherence_review(
                    self.seed_markdown,
                    tuple(
                        [
                            *self.history,
                            ChapterRunArtifact(
                                chapter_number=chapter_number,
                                outline_text=self.approved_outline,
                                scene_artifacts=tuple(scene_artifacts),
                                stitched_text=stitched_text,
                                state_update=state_update,
                                coherence_review=None,
                            ),
                        ]
                    ),
                )
            except Exception as exc:
                raise BookEngineError(f"Coherence gate failed: {exc}") from exc

        return ChapterRunArtifact(
            chapter_number=chapter_number,
            outline_text=self.approved_outline,
            scene_artifacts=tuple(scene_artifacts),
            stitched_text=stitched_text,
            state_update=state_update,
            coherence_review=coherence_review,
        )

    def _generate_draft_text(
        self,
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        """Generate one draft scene and enforce non-empty output."""

        try:
            draft_text = self.draft_scene(directive, chapter_number, scene_number)
        except Exception as exc:
            raise BookEngineError(f"Draft generation failed: {exc}") from exc

        cleaned = draft_text.strip()
        if not cleaned:
            raise BookEngineError("Draft generation produced empty text")
        return cleaned

    def _generate_edited_text(
        self,
        directive: SceneDirective,
        draft_text: str,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        """Generate edited scene text with one fallback-redraft retry path."""

        try:
            edited_text = self.edit_scene(
                directive,
                draft_text,
                chapter_number,
                scene_number,
            )
        except Exception as exc:
            if self.retry_draft_scene is None:
                raise BookEngineError(f"Edit generation failed: {exc}") from exc

            retry_draft = self.retry_draft_scene(
                directive,
                chapter_number,
                scene_number,
            ).strip()
            if not retry_draft:
                raise BookEngineError("Fallback draft generation produced empty text")
            try:
                edited_text = self.edit_scene(
                    directive,
                    retry_draft,
                    chapter_number,
                    scene_number,
                )
            except Exception as second_exc:
                raise BookEngineError(
                    f"Edit retry failed after fallback draft: {second_exc}"
                ) from second_exc

        cleaned = edited_text.strip()
        if not cleaned:
            raise BookEngineError("Edit generation produced empty text")
        return cleaned
