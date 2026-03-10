from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Callable

from storycraftr.agent.chapter_validator import (
    MAX_RETRIES,
    guarded_generation,
    has_meaningful_state_signal,
)
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
    generation_diagnostics: dict[str, Any] = field(default_factory=dict)


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
    retry_draft_scene: Callable[..., str] | None = None
    check_severe_canon_violation: Callable[[Any], bool] | None = None
    on_scene_generation_retry: Callable[[int, int, int, str], None] | None = None
    on_chapter_validation_retry: Callable[[int, int, str], None] | None = None
    on_coherence_repair_retry: Callable[[int, int, str], None] | None = None
    run_coherence_review: (
        Callable[[str, tuple[ChapterRunArtifact, ...]], tuple[bool, str | None]] | None
    ) = None
    run_semantic_review: Callable[
        [str, int, str], tuple[bool, str | None]
    ] | None = None
    persist_validation_failure: Callable[[int, int, str, str], None] | None = None
    persist_coherence_failure: Callable[[int, str, str], None] | None = None
    enable_semantic_review: bool = False
    coherence_interval: int = 5
    min_scene_words: int = 0
    min_chapter_words: int = 0
    max_scene_generation_attempts: int = 3
    max_chapter_validation_attempts: int = MAX_RETRIES
    min_directive_words: int = 2
    enforce_state_signal_guard: bool = False
    enforce_coherence_each_chapter: bool = False
    require_severe_canon_check: bool = False

    stage: BookEngineStage = BookEngineStage.IDLE
    seed_markdown: str = ""
    target_chapters: int = 0
    current_chapter: int = 1
    approved_outline: str = ""
    history: list[ChapterRunArtifact] = field(default_factory=list)
    _pending_outline: str | None = None
    _pending_chapter: ChapterRunArtifact | None = None

    _SCENE_DENSITY_REPAIR_DIRECTIVE = (
        "Correction: Your previous scene was too short. Do NOT add filler. "
        "Expand the scene by deepening the GOAL, escalating the CONFLICT, "
        "clarifying the DISASTER, or expanding the character's internal "
        "reaction in the SEQUEL, as required by the Master Story Engineering rules."
    )
    _OUTCOME_MOVEMENT_MARKERS = (
        "decides",
        "decision",
        "chooses",
        "changes",
        "discovers",
        "fails",
        "reveals",
        "forces",
        "cost",
        "consequence",
        "dilemma",
        "turn",
        "escalates",
        "confrontation",
        "abandons",
        "joins",
    )

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

        for index, directive in enumerate(directives, start=1):
            self._validate_scene_directive(directive, scene_number=index)

        generation_diagnostics: dict[str, Any] = {
            "directive_quality_passed": True,
            "chapter_validation_attempts": 1,
            "chapter_validation_last_retry_reason": None,
            "state_signal_meaningful": None,
            "state_signal_enforced": False,
            "semantic_review_enabled": False,
            "semantic_review_passed": None,
            "semantic_review_last_reason": None,
            "coherence_gate_required": False,
            "coherence_gate_passed": None,
            "severe_canon_violation": False,
            "retry_feedback_last": None,
        }

        scene_artifacts: list[SceneRunArtifact] = []
        edited_scenes: list[str] = []

        def _regenerate_scene_pipeline(
            *,
            repair_directive: str | None = None,
            repair_in_system_prompt: bool = False,
        ) -> None:
            """Rebuild draft/edit scene artifacts for retry attempts."""

            nonlocal scene_artifacts, edited_scenes
            refreshed_artifacts: list[SceneRunArtifact] = []
            refreshed_scenes: list[str] = []
            for index, directive in enumerate(directives, start=1):
                draft_text = self._generate_draft_text(
                    directive,
                    chapter_number,
                    index,
                    repair_directive=repair_directive,
                    repair_in_system_prompt=repair_in_system_prompt,
                )
                edited_text = self._generate_edited_text(
                    directive,
                    draft_text,
                    chapter_number,
                    index,
                )
                refreshed_artifacts.append(
                    SceneRunArtifact(
                        scene_number=index,
                        directive=directive,
                        draft_text=draft_text,
                        edited_text=edited_text,
                    )
                )
                refreshed_scenes.append(edited_text)

            scene_artifacts = refreshed_artifacts
            edited_scenes = refreshed_scenes

        _regenerate_scene_pipeline()

        min_chapter_words = max(0, self.min_chapter_words)
        enforce_chapter_guard = min_chapter_words > 0
        enforce_state_signal = enforce_chapter_guard or self.enforce_state_signal_guard
        semantic_review_enabled = bool(
            self.enable_semantic_review and self.run_semantic_review is not None
        )
        should_use_guarded_generation = enforce_chapter_guard or semantic_review_enabled
        generation_diagnostics["state_signal_enforced"] = enforce_state_signal
        generation_diagnostics["semantic_review_enabled"] = semantic_review_enabled

        def _semantic_validator(text: str) -> tuple[bool, str]:
            parity_ok, parity_reason = self._validate_stitch_parity(
                text,
                edited_scenes,
            )
            if not parity_ok:
                generation_diagnostics["stitch_parity_passed"] = False
                generation_diagnostics["stitch_parity_last_reason"] = parity_reason
                return False, parity_reason

            generation_diagnostics["stitch_parity_passed"] = True
            generation_diagnostics["stitch_parity_last_reason"] = None

            if not semantic_review_enabled or self.run_semantic_review is None:
                return True, "ok"

            ok, reason = self.run_semantic_review(
                text,
                chapter_number,
                self.approved_outline,
            )
            if ok:
                generation_diagnostics["semantic_review_passed"] = True
                generation_diagnostics["semantic_review_last_reason"] = None
                return True, "ok"

            cleaned_reason = str(reason or "unspecified_violation").strip()
            generation_diagnostics["semantic_review_passed"] = False
            generation_diagnostics["semantic_review_last_reason"] = cleaned_reason
            return False, f"semantic_review:{cleaned_reason}"

        def _generate_validated_chapter(*, feedback: str | None = None) -> str:
            if feedback is not None:
                cleaned_feedback = str(feedback).strip()
                generation_diagnostics["retry_feedback_last"] = cleaned_feedback
                if cleaned_feedback.startswith(("semantic_review:", "coherence_gate:")):
                    correction = (
                        "CRITICAL CORRECTION: The previous chapter attempt failed "
                        "validation. You must delete non-compliant text and rewrite "
                        "to follow the approved Scene Plan exactly. "
                        f"Failure reason: {cleaned_feedback}."
                    )
                    _regenerate_scene_pipeline(
                        repair_directive=correction,
                        repair_in_system_prompt=True,
                    )
                else:
                    _regenerate_scene_pipeline()

            try:
                stitched = self.stitch_chapter(edited_scenes, chapter_number)
            except Exception as exc:
                raise BookEngineError(f"Chapter stitch failed: {exc}") from exc

            stitched_text = stitched.strip()
            if not stitched_text:
                raise RuntimeError("empty_output")

            try:
                self._validate_prose(
                    stitched_text,
                    min_words=min_chapter_words,
                    artifact_name="chapter",
                )
                return stitched_text
            except BookEngineError:
                # If stitch output is truncated or malformed, fall back to deterministic
                # scene append output when it satisfies chapter completeness checks.
                fallback_text = "\n\n".join(edited_scenes).strip()
                self._validate_prose(
                    fallback_text,
                    min_words=min_chapter_words,
                    artifact_name="chapter",
                )
                return fallback_text

        if should_use_guarded_generation:
            # `guarded_generation` calls `on_retry` after failed attempts only.
            # Track retry counts/reason for runtime diagnostics.
            retry_state: dict[str, Any] = {
                "attempts": 1,
                "last_reason": None,
            }

            def _on_failure(attempt: int, total: int, reason: str, text: str) -> None:
                del total
                if self.persist_validation_failure is None:
                    return
                try:
                    self.persist_validation_failure(
                        chapter_number,
                        attempt,
                        reason,
                        text,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to persist validation failure artifact: {exc}"
                    ) from exc

            def _on_retry(attempt: int, total: int, reason: str) -> None:
                retry_state["attempts"] = min(total, attempt + 1)
                retry_state["last_reason"] = reason
                print(
                    "[CompletenessGuard] "
                    f"Chapter invalid ({reason}) -- retry {attempt}/{total}"
                )
                if attempt < total:
                    if self.on_chapter_validation_retry is not None:
                        try:
                            self.on_chapter_validation_retry(attempt, total, reason)
                        except Exception as exc:
                            raise RuntimeError(
                                f"Chapter retry escalation callback failed: {exc}"
                            ) from exc

            try:
                stitched_text = guarded_generation(
                    _generate_validated_chapter,
                    max_retries=max(1, self.max_chapter_validation_attempts),
                    min_words=max(1, min_chapter_words),
                    semantic_validator=_semantic_validator,
                    on_failure=_on_failure,
                    on_retry=_on_retry,
                )
            except RuntimeError as exc:
                raise BookEngineError(str(exc)) from exc

            generation_diagnostics["chapter_validation_attempts"] = int(
                retry_state["attempts"]
            )
            generation_diagnostics[
                "chapter_validation_last_retry_reason"
            ] = retry_state["last_reason"]
        else:
            stitched_text = _generate_validated_chapter()

        if (
            semantic_review_enabled
            and generation_diagnostics["semantic_review_passed"] is None
        ):
            # When retries are disabled, still run semantic validation once.
            semantic_ok, semantic_reason = _semantic_validator(stitched_text)
            if not semantic_ok:
                raise BookEngineError(
                    f"Semantic review rejected chapter: {semantic_reason}"
                )

        try:
            state_update = self.derive_state_update(stitched_text, chapter_number)
        except Exception as exc:
            raise BookEngineError(f"State extraction failed: {exc}") from exc

        has_signal = has_meaningful_state_signal(state_update)
        generation_diagnostics["state_signal_meaningful"] = has_signal
        if enforce_state_signal and not has_signal:
            raise BookEngineError(
                "State extraction produced no meaningful update; halting fail-closed"
            )

        coherence_review: str | None = None
        should_run_gate = self.enforce_coherence_each_chapter or (
            chapter_number % max(1, self.coherence_interval) == 0
        )
        severe_violation = False
        if (
            self.require_severe_canon_check
            and self.check_severe_canon_violation is None
        ):
            raise BookEngineError(
                "Severe canon check is required but checker callback is not configured"
            )

        if self.check_severe_canon_violation is not None:
            try:
                severe_violation = bool(self.check_severe_canon_violation(state_update))
            except Exception as exc:
                raise BookEngineError(f"Canon violation check failed: {exc}") from exc
        generation_diagnostics["severe_canon_violation"] = severe_violation
        should_run_gate = should_run_gate or severe_violation
        generation_diagnostics["coherence_gate_required"] = should_run_gate

        if should_run_gate and self.run_coherence_review is None:
            raise BookEngineError(
                "Coherence gate is required but review callback is not configured"
            )

        if should_run_gate and self.run_coherence_review is not None:
            max_repair_attempts = 1
            repair_attempt = 0
            while True:
                try:
                    gate_ok, gate_reason = self.run_coherence_review(
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
                                    generation_diagnostics=dict(generation_diagnostics),
                                ),
                            ]
                        ),
                    )
                except Exception as exc:
                    raise BookEngineError(f"Coherence gate failed: {exc}") from exc

                coherence_review = str(gate_reason or "ok")
                generation_diagnostics["coherence_gate_passed"] = bool(gate_ok)
                generation_diagnostics["coherence_repair_attempts"] = repair_attempt

                if gate_ok:
                    break

                if repair_attempt >= max_repair_attempts:
                    if self.persist_coherence_failure is not None:
                        try:
                            self.persist_coherence_failure(
                                chapter_number,
                                coherence_review,
                                stitched_text,
                            )
                        except Exception as exc:
                            raise BookEngineError(
                                f"Failed to persist coherence failure artifact: {exc}"
                            ) from exc
                    raise BookEngineError(
                        f"Coherence gate rejected chapter: {coherence_review}"
                    )

                repair_attempt += 1
                generation_diagnostics["coherence_repair_attempts"] = repair_attempt
                generation_diagnostics["coherence_repair_reason"] = coherence_review

                repair_directive = (
                    "CRITICAL CORRECTION: Inquisitor coherence review found a severe "
                    "continuity or canon issue. Resolve this exact issue in the rewrite: "
                    f"{coherence_review}. Preserve approved scene directives while fixing "
                    "hallucinations and continuity contradictions."
                )

                if self.on_coherence_repair_retry is not None:
                    try:
                        self.on_coherence_repair_retry(
                            repair_attempt,
                            max_repair_attempts + 1,
                            coherence_review,
                        )
                    except Exception as exc:
                        raise BookEngineError(
                            f"Coherence repair escalation callback failed: {exc}"
                        ) from exc

                _regenerate_scene_pipeline(
                    repair_directive=repair_directive,
                    repair_in_system_prompt=True,
                )
                stitched_text = _generate_validated_chapter()
                try:
                    state_update = self.derive_state_update(
                        stitched_text, chapter_number
                    )
                except Exception as exc:
                    raise BookEngineError(f"State extraction failed: {exc}") from exc

                has_signal = has_meaningful_state_signal(state_update)
                generation_diagnostics["state_signal_meaningful"] = has_signal
                if enforce_state_signal and not has_signal:
                    raise BookEngineError(
                        "State extraction produced no meaningful update; halting fail-closed"
                    )

        return ChapterRunArtifact(
            chapter_number=chapter_number,
            outline_text=self.approved_outline,
            scene_artifacts=tuple(scene_artifacts),
            stitched_text=stitched_text,
            state_update=state_update,
            coherence_review=coherence_review,
            generation_diagnostics=dict(generation_diagnostics),
        )

    def _generate_draft_text(
        self,
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        *,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        """Generate one draft scene and enforce non-empty output."""

        try:
            draft_text = self._call_draft_scene(
                directive,
                chapter_number,
                scene_number,
                repair_directive=repair_directive,
                repair_in_system_prompt=repair_in_system_prompt,
            )
        except Exception as exc:
            raise BookEngineError(f"Draft generation failed: {exc}") from exc

        cleaned = draft_text.strip()
        if not cleaned:
            raise BookEngineError("Draft generation produced empty text")

        self._validate_prose(
            cleaned,
            min_words=self.min_scene_words,
            artifact_name="scene",
        )
        return cleaned

    def _generate_edited_text(
        self,
        directive: SceneDirective,
        draft_text: str,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        """Generate edited scene text with one fallback-redraft retry path."""

        current_draft = draft_text
        attempts = max(1, self.max_scene_generation_attempts)

        for attempt_index in range(attempts):
            try:
                edited_text = self.edit_scene(
                    directive,
                    current_draft,
                    chapter_number,
                    scene_number,
                )
            except Exception as exc:
                if self.retry_draft_scene is None or attempt_index == attempts - 1:
                    raise BookEngineError(f"Edit generation failed: {exc}") from exc
                self._notify_scene_retry(
                    chapter_number,
                    scene_number,
                    attempt=attempt_index + 1,
                    reason=f"edit_exception:{exc}",
                )
                current_draft = self._call_retry_draft_scene(
                    directive,
                    chapter_number,
                    scene_number,
                    repair_directive=None,
                ).strip()
                if not current_draft:
                    raise BookEngineError(
                        "Fallback draft generation produced empty text"
                    )
                continue

            cleaned = edited_text.strip()
            if not cleaned:
                if self.retry_draft_scene is None or attempt_index == attempts - 1:
                    raise BookEngineError("Edit generation produced empty text")
                self._notify_scene_retry(
                    chapter_number,
                    scene_number,
                    attempt=attempt_index + 1,
                    reason="edit_empty_output",
                )
                current_draft = self._call_retry_draft_scene(
                    directive,
                    chapter_number,
                    scene_number,
                    repair_directive=None,
                ).strip()
                if not current_draft:
                    raise BookEngineError(
                        "Fallback draft generation produced empty text"
                    )
                continue

            try:
                self._validate_prose(
                    cleaned,
                    min_words=self.min_scene_words,
                    artifact_name="scene",
                )
                return cleaned
            except BookEngineError:
                if self.retry_draft_scene is None or attempt_index == attempts - 1:
                    raise
                repair_directive: str | None = None
                reason = "scene_validation_failed"
                if self.min_scene_words > 0:
                    produced_words = self._word_count(cleaned)
                    if produced_words < self.min_scene_words:
                        reason = "scene_too_short"
                        repair_directive = self._SCENE_DENSITY_REPAIR_DIRECTIVE

                self._notify_scene_retry(
                    chapter_number,
                    scene_number,
                    attempt=attempt_index + 1,
                    reason=reason,
                )
                current_draft = self._call_retry_draft_scene(
                    directive,
                    chapter_number,
                    scene_number,
                    repair_directive=repair_directive,
                ).strip()
                if not current_draft:
                    raise BookEngineError(
                        "Fallback draft generation produced empty text"
                    )

        raise BookEngineError("Scene editing exhausted all retry attempts")

    def _validate_prose(
        self,
        text: str,
        *,
        min_words: int,
        artifact_name: str,
    ) -> None:
        """Fail closed for short or clearly truncated prose artifacts."""

        word_count = self._word_count(text)
        if min_words > 0 and word_count < min_words:
            raise BookEngineError(
                f"{artifact_name.title()} output below minimum word count: "
                f"{word_count} < {min_words}"
            )

        if text.rstrip().endswith("..."):
            raise BookEngineError(
                f"{artifact_name.title()} output appears truncated or incomplete"
            )

    def _validate_stitch_parity(
        self,
        stitched_text: str,
        edited_scenes: list[str],
    ) -> tuple[bool, str]:
        """Detect stitch-stage summarization that drops too much drafted prose."""

        total_scene_words = sum(
            self._word_count(scene_text)
            for scene_text in edited_scenes
            if scene_text.strip()
        )
        if total_scene_words <= 0:
            return True, "ok"

        stitched_words = self._word_count(stitched_text)
        minimum_allowed_words = max(1, int(total_scene_words * 0.75))
        if stitched_words < minimum_allowed_words:
            return (
                False,
                "stitcher_summarization_detected - excessive content loss "
                f"({stitched_words} < {minimum_allowed_words})",
            )

        return True, "ok"

    def _validate_scene_directive(
        self,
        directive: SceneDirective,
        *,
        scene_number: int,
    ) -> None:
        """Fail closed when planner returns structurally weak directives."""

        min_words = max(1, self.min_directive_words)
        for field_name in ("goal", "conflict", "stakes", "outcome"):
            value = str(getattr(directive, field_name, "")).strip()
            if not value:
                raise BookEngineError(
                    f"Scene planning produced empty '{field_name}' in scene {scene_number}"
                )
            if self._word_count(value) < min_words:
                raise BookEngineError(
                    "Scene planning produced weak directive "
                    f"'{field_name}' in scene {scene_number}"
                )

        outcome = str(getattr(directive, "outcome", "")).strip().lower()
        marker_pattern = r"\b(" + "|".join(self._OUTCOME_MOVEMENT_MARKERS) + r")\b"
        if not re.search(marker_pattern, outcome):
            markers = ", ".join(self._OUTCOME_MOVEMENT_MARKERS)
            raise BookEngineError(
                "Scene planning outcome must include a decision-beat movement marker "
                f"({markers}) in scene {scene_number}"
            )

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.split())

    def _notify_scene_retry(
        self,
        chapter_number: int,
        scene_number: int,
        *,
        attempt: int,
        reason: str,
    ) -> None:
        """Emit scene retry events for runtime model-escalation hooks."""

        if self.on_scene_generation_retry is None:
            return
        self.on_scene_generation_retry(
            chapter_number,
            scene_number,
            attempt,
            reason,
        )

    def _call_retry_draft_scene(
        self,
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        *,
        repair_directive: str | None,
    ) -> str:
        """Call retry draft callback with backward-compatible signature support."""

        if self.retry_draft_scene is None:
            raise BookEngineError(
                "Fallback draft generation callback is not configured"
            )

        retry_fn = self.retry_draft_scene
        if repair_directive is not None:
            try:
                return retry_fn(
                    directive,
                    chapter_number,
                    scene_number,
                    repair_directive,
                )
            except TypeError:
                # Backward compatibility for 3-argument callbacks.
                pass
        return retry_fn(directive, chapter_number, scene_number)

    def _call_draft_scene(
        self,
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        *,
        repair_directive: str | None,
        repair_in_system_prompt: bool,
    ) -> str:
        """Call draft callback with optional coherence-repair guidance."""

        if repair_directive is not None:
            try:
                return self.draft_scene(
                    directive,
                    chapter_number,
                    scene_number,
                    repair_directive,
                    repair_in_system_prompt,
                )
            except TypeError:
                # Backward compatibility for 3-arg draft callbacks.
                pass
        return self.draft_scene(directive, chapter_number, scene_number)
