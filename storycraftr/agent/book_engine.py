from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Callable

from flashtext2 import KeywordProcessor
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
)
import structlog

from storycraftr.agent.chapter_validator import (
    MAX_RETRIES,
    MechanicalSieve,
    guarded_generation,
    has_meaningful_state_signal,
)
from storycraftr.agent.deterministic_guards import (
    check_draft_expansion,
    extract_missing_required_outline_threads,
    check_hard_truncation,
    check_outcome_overlap,
    check_pov,
    check_required_outline_threads,
    check_required_outcome_realization,
    check_scene_order_and_count_preservation,
    check_single_pov_enforcement,
)
from storycraftr.agent.narrative_state import SceneDirective
from storycraftr.agent.self_healer import HealingTicket, NarrativeHealer

_BOOK_ENGINE_LOGGER = structlog.get_logger("storycraftr.book_engine")
_SCENE_DIRECTIVE_POV_VERB_TOKENS = frozenset(
    {
        "gather",
        "gathers",
        "reach",
        "reaches",
        "seek",
        "seeks",
        "recover",
        "recovers",
        "steal",
        "steals",
        "cross",
        "crosses",
        "infiltrate",
        "infiltrates",
        "confront",
        "confronts",
        "protect",
        "protects",
        "rescue",
        "rescues",
        "chase",
        "chases",
        "escape",
        "escapes",
        "investigate",
        "investigates",
        "search",
        "searches",
        "track",
        "tracks",
    }
)


def _first_directive_token(text: str) -> str:
    for raw_token in str(text).split():
        token = raw_token.strip(".,:;!?()[]{}\"'")
        if token:
            return token
    return ""


def _is_verb_like_pov_token(token: str) -> bool:
    lowered = str(token).strip().lower()
    if not lowered:
        return False
    return lowered in _SCENE_DIRECTIVE_POV_VERB_TOKENS


class BookEngineError(RuntimeError):
    """Raised when the book engine encounters an invalid or unsafe transition."""


class _SceneDirectiveContract(BaseModel):
    """Strict deterministic contract for scene directives before generation."""

    model_config = ConfigDict(strict=True)

    goal: str
    conflict: str
    stakes: str
    outcome: str

    @field_validator("goal", "conflict", "stakes", "outcome")
    @classmethod
    def _validate_non_empty_fields(cls, value: str, info: ValidationInfo) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("directive field must be non-empty")
        if str(
            getattr(info, "field_name", "")
        ).strip() == "goal" and _is_verb_like_pov_token(
            _first_directive_token(cleaned)
        ):
            raise ValueError("goal must start with a character name, not a verb")
        return cleaned


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
    repair_scene_directive: Callable[..., SceneDirective] | None = None
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
    scene_memory_store: Callable[[int, int, str, str], None] | None = None
    scene_memory_fetch_context: (
        Callable[[int, int, SceneDirective, int], str] | None
    ) = None
    resolve_character_ledger_names: Callable[[], tuple[str, ...]] | None = None
    scene_memory_purge: Callable[[int], None] | None = None
    persist_validation_failure: Callable[[int, int, str, str], None] | None = None
    persist_coherence_failure: Callable[[int, str, str], None] | None = None
    persist_blackbox: Callable[[int, int, str, str, str], None] | None = None
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
    enforce_scene_structure_contract: bool = False
    enforce_plot_omission_guard: bool = False
    healer: NarrativeHealer = field(default_factory=NarrativeHealer)

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
    _SCENE_STRUCTURE_REPAIR_PREFIX = (
        "Correction: The previous scene drifted from the approved Scene Plan. "
        "Rewrite from scratch if needed. Do not keep substitute beats, invented "
        "discoveries, or alternate endings. The revised scene must visibly land "
        "the approved outcome on-page in the final paragraphs."
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
    _SCENE_STRUCTURE_STOPWORDS = frozenset(
        {
            "that",
            "with",
            "from",
            "into",
            "their",
            "there",
            "about",
            "after",
            "before",
            "through",
            "while",
            "because",
            "would",
            "could",
            "should",
        }
    )
    _POV_NAME_STOPWORDS = frozenset(
        {
            "goal",
            "conflict",
            "stakes",
            "outcome",
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
            "chapter",
            "scene",
            "the",
            "and",
            "but",
        }
    )
    _POV_VERB_TOKENS = frozenset(_SCENE_DIRECTIVE_POV_VERB_TOKENS)
    _OUTLINE_THREAD_KEYWORDS = (
        "rebellion",
        "city seal",
        "guards",
    )
    _REVIEWER_TRANSPORT_FAILURE_TOKENS = (
        "reviewer_invalid_response",
        "reviewer_empty_output",
        "reviewer_transport_error",
        "openrouter request failed without an explicit exception",
        "model invocation failed",
    )
    _MAX_SCENE_CONTINUATIONS = 2

    _TERMINAL_PUNCTUATION = (".", "!", "?", '"', "'", ")", "]")

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

        if self.scene_memory_purge is not None:
            try:
                self.scene_memory_purge(chapter.chapter_number)
            except Exception as exc:
                raise BookEngineError(f"Scene memory purge failed: {exc}") from exc

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

        combined_directive_text = self._build_combined_directive_text(directives)
        expected_pov = self._infer_expected_pov(directives)
        planned_outcome = " ".join(
            directive.outcome.strip()
            for directive in directives
            if directive.outcome.strip()
        )
        required_outline_threads = self._extract_required_outline_threads(
            self.approved_outline
        )
        directive_character_candidates = self._collect_directive_character_candidates(
            directives
        )

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
            "expected_pov": expected_pov,
        }

        scene_artifacts: list[SceneRunArtifact] = []
        edited_scenes: list[str] = []

        def _apply_localized_required_thread_repairs(reason: str) -> tuple[bool, str]:
            """Repair only the failing scene span for missing required outline threads."""

            missing_threads = extract_missing_required_outline_threads(reason)
            if not missing_threads:
                return False, reason
            if self.retry_draft_scene is None:
                return False, reason

            for thread in missing_threads:
                current_joined = "\n\n".join(edited_scenes)
                if thread in current_joined.lower():
                    continue

                target_index = self._select_scene_for_required_thread(
                    thread,
                    directives,
                    edited_scenes,
                )
                target_scene_number = target_index + 1
                directive = directives[target_index]
                repair_prompt = self._build_required_thread_scene_repair_directive(
                    directive,
                    thread,
                    reason,
                )
                repaired = self._call_retry_draft_scene(
                    directive,
                    chapter_number,
                    target_scene_number,
                    repair_directive=repair_prompt,
                    repair_in_system_prompt=True,
                ).strip()
                if not repaired:
                    return False, f"required_outline_thread_repair_empty:{thread}"

                self._validate_prose(
                    repaired,
                    min_words=self.min_scene_words,
                    artifact_name="scene",
                )
                if self.enforce_scene_structure_contract and self.min_scene_words > 0:
                    self._validate_scene_structure(directive, repaired)
                pre_guard_ok, pre_guard_reason = self._run_python_pre_guards(
                    directive,
                    repaired,
                )
                if not pre_guard_ok:
                    return False, pre_guard_reason

                edited_scenes[target_index] = repaired
                prior = scene_artifacts[target_index]
                scene_artifacts[target_index] = SceneRunArtifact(
                    scene_number=prior.scene_number,
                    directive=prior.directive,
                    draft_text=prior.draft_text,
                    edited_text=repaired,
                )

                recheck_ok, recheck_reason = check_required_outline_threads(
                    "\n\n".join(edited_scenes),
                    required_outline_threads,
                )
                if not recheck_ok:
                    return False, recheck_reason

            return True, "localized_thread_repair_applied"

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
                final_directive, edited_text = self._generate_edited_text(
                    directive,
                    draft_text,
                    chapter_number,
                    index,
                )
                directives[index - 1] = final_directive
                refreshed_artifacts.append(
                    SceneRunArtifact(
                        scene_number=index,
                        directive=final_directive,
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
        healing_tickets: dict[str, HealingTicket] = {}

        def _semantic_validator(text: str) -> tuple[bool, str]:
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
            if self._is_reviewer_transport_failure(cleaned_reason):
                generation_diagnostics["semantic_review_last_reason"] = cleaned_reason
                return False, cleaned_reason

            ticket = self.healer.ticket(
                stage="semantic_review",
                failure_class=f"semantic_review:{cleaned_reason}",
                raw_output=text,
            )
            healing_tickets[
                self.healer.normalize_failure_class(ticket.failure_class)
            ] = ticket
            generation_diagnostics["last_healing_ticket"] = {
                "stage": ticket.stage,
                "failure_class": ticket.failure_class,
                "remediation_instruction": ticket.remediation_instruction,
            }
            generation_diagnostics["semantic_review_passed"] = False
            generation_diagnostics["semantic_review_last_reason"] = cleaned_reason
            return False, f"semantic_review:{cleaned_reason}"

        def _deterministic_validator(text: str) -> tuple[bool, str]:
            parity_ok, parity_reason = self._validate_stitch_parity(
                text,
                edited_scenes,
            )
            if not parity_ok:
                generation_diagnostics["stitch_parity_passed"] = False
                generation_diagnostics["stitch_parity_last_reason"] = parity_reason
                return False, parity_reason

            has_narrative_marks = any(mark in text for mark in (".", "!", "?"))

            if self.enforce_scene_structure_contract and has_narrative_marks:
                entity_ok, entity_reason = self._validate_entity_ledger(
                    text,
                    directive_character_candidates,
                )
                if not entity_ok:
                    return False, entity_reason

            generation_diagnostics["stitch_parity_passed"] = True
            generation_diagnostics["stitch_parity_last_reason"] = None

            sieve = MechanicalSieve(
                pov_name=expected_pov or "",
                planned_outcome=(
                    planned_outcome if self.enforce_plot_omission_guard else ""
                ),
            )

            def _mechanical_checks(raw_text: str) -> tuple[bool, str]:
                ok, reason = sieve(raw_text)
                if not ok:
                    return False, reason
                return check_draft_expansion(raw_text, combined_directive_text)

            result = self.healer.evaluate(
                stage="chapter_validation",
                raw_output=text,
                validator=_mechanical_checks,
            )
            if result == "PASS":
                if self.enforce_scene_structure_contract:
                    single_pov_required = self._requires_single_pov(
                        directives,
                        expected_pov,
                    )
                    if single_pov_required and expected_pov:
                        ok, reason = check_single_pov_enforcement(
                            text,
                            expected_pov,
                            candidate_names=directive_character_candidates,
                        )
                        if not ok:
                            return False, reason

                    if has_narrative_marks:
                        ok, reason = check_required_outcome_realization(
                            text,
                            planned_outcome,
                        )
                        if not ok:
                            return False, reason

                        if required_outline_threads:
                            ok, reason = check_required_outline_threads(
                                text,
                                required_outline_threads,
                            )
                            if not ok:
                                (
                                    repaired,
                                    repaired_reason,
                                ) = _apply_localized_required_thread_repairs(reason)
                                if repaired:
                                    return False, repaired_reason
                                return False, reason

                    ok, reason = check_scene_order_and_count_preservation(
                        text,
                        tuple(edited_scenes),
                        expected_scene_count=len(directives),
                    )
                    if not ok:
                        return False, reason
                return True, "ok"

            healing_tickets[
                self.healer.normalize_failure_class(result.failure_class)
            ] = result
            generation_diagnostics["last_healing_ticket"] = {
                "stage": result.stage,
                "failure_class": result.failure_class,
                "remediation_instruction": result.remediation_instruction,
            }
            return False, result.failure_class

        def _generate_validated_chapter(*, feedback: str | None = None) -> str:
            if feedback is not None:
                cleaned_feedback = str(feedback).strip()
                generation_diagnostics["retry_feedback_last"] = cleaned_feedback
                ticket = healing_tickets.get(
                    self.healer.normalize_failure_class(cleaned_feedback)
                )
                if (
                    ticket is not None
                    and self.healer.normalize_failure_class(ticket.failure_class)
                    == "PLOT_OMISSION"
                ):
                    correction = ticket.remediation_instruction
                    repair_in_system_prompt = True
                else:
                    (
                        correction,
                        repair_in_system_prompt,
                    ) = self._build_chapter_retry_repair_directive(
                        cleaned_feedback,
                        expected_pov=expected_pov,
                    )
                if correction is not None:
                    _regenerate_scene_pipeline(
                        repair_directive=correction,
                        repair_in_system_prompt=repair_in_system_prompt,
                    )
                elif cleaned_feedback == "localized_thread_repair_applied":
                    # Keep scene-local repaired buffers and avoid full chapter rewrites.
                    pass
                else:
                    _regenerate_scene_pipeline()

            try:
                stitched = self._stitch_with_deterministic_fallback(
                    edited_scenes,
                    chapter_number,
                    min_chapter_words,
                    generation_diagnostics,
                )
            except Exception as exc:
                raise BookEngineError(f"Chapter stitch failed: {exc}") from exc

            stitched_text = stitched.strip()
            if not stitched_text:
                raise RuntimeError("empty_output")
            return stitched_text

        if should_use_guarded_generation:
            # `guarded_generation` calls `on_retry` after failed attempts only.
            # Track retry counts/reason for runtime diagnostics.
            retry_state: dict[str, Any] = {
                "attempts": 1,
                "last_reason": None,
            }

            def _on_failure(attempt: int, total: int, reason: str, text: str) -> None:
                del total
                if self.persist_validation_failure is not None:
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

                # Forensic black-box: raw response + Python-native error reason.
                if self.persist_blackbox is not None:
                    prompt_context = (
                        str(
                            generation_diagnostics.get("retry_feedback_last", "")
                        ).strip()
                        or "<initial_attempt>"
                    )
                    try:
                        self.persist_blackbox(
                            chapter_number,
                            attempt,
                            prompt_context,
                            text,
                            reason,
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            f"Failed to persist blackbox artifact: {exc}"
                        ) from exc

            def _on_retry(attempt: int, total: int, reason: str) -> None:
                retry_state["attempts"] = min(total, attempt + 1)
                retry_state["last_reason"] = reason
                _BOOK_ENGINE_LOGGER.warning(
                    "chapter_validation_retry",
                    reason=reason,
                    attempt=attempt,
                    total=total,
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
                    deterministic_validator=_deterministic_validator,
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

        memory_context = self._fetch_scene_memory_context(
            chapter_number,
            scene_number,
            directive,
        )
        effective_repair_directive = self._merge_repair_with_memory_context(
            repair_directive,
            memory_context,
        )

        try:
            draft_text = self._call_draft_scene(
                directive,
                chapter_number,
                scene_number,
                repair_directive=effective_repair_directive,
                repair_in_system_prompt=(
                    repair_in_system_prompt or effective_repair_directive is not None
                ),
            )
        except Exception as exc:
            raise BookEngineError(f"Draft generation failed: {exc}") from exc

        cleaned = draft_text.strip()
        if not cleaned:
            raise BookEngineError("Draft generation produced empty text")

        continuation_attempt = 0
        rewrite_attempted = False
        while True:
            truncation_reason = self._detect_truncation_reason(cleaned)
            hard_truncation = check_hard_truncation(
                cleaned,
                expected_words=self.min_scene_words,
            )
            if truncation_reason is None and not hard_truncation:
                break
            if self.retry_draft_scene is None:
                break
            if continuation_attempt >= self._MAX_SCENE_CONTINUATIONS:
                if rewrite_attempted:
                    self._notify_scene_retry(
                        chapter_number,
                        scene_number,
                        attempt=continuation_attempt,
                        reason="scene_truncation_continuation_exhausted",
                    )
                    raise BookEngineError(
                        "Scene truncation continuation exhausted local attempts"
                    )

                rewrite_attempted = True
                self._notify_scene_retry(
                    chapter_number,
                    scene_number,
                    attempt=continuation_attempt,
                    reason="scene_truncation_rewrite_fallback",
                )
                rewrite_prompt = self._build_truncation_rewrite_directive(
                    directive,
                    failing_guard_reason=(
                        truncation_reason
                        if truncation_reason is not None
                        else "terminal_truncation:hard_cut"
                    ),
                )
                rewritten = self._call_retry_draft_scene(
                    directive,
                    chapter_number,
                    scene_number,
                    repair_directive=rewrite_prompt,
                    repair_in_system_prompt=True,
                ).strip()
                if not rewritten:
                    raise BookEngineError(
                        "Fallback draft generation produced empty text"
                    )
                cleaned = rewritten
                continue

            continuation_attempt += 1
            self._notify_scene_retry(
                chapter_number,
                scene_number,
                attempt=continuation_attempt,
                reason=(
                    f"scene_truncation_continuation:{truncation_reason}"
                    if truncation_reason is not None
                    else "scene_truncation_continuation"
                ),
            )
            continuation_prompt = self._build_draft_continuation_directive(
                cleaned,
                directive,
                failing_guard_reason=(
                    truncation_reason
                    if truncation_reason is not None
                    else "terminal_truncation:hard_cut"
                ),
            )
            continued = self._call_retry_draft_scene(
                directive,
                chapter_number,
                scene_number,
                repair_directive=continuation_prompt,
                repair_in_system_prompt=True,
            ).strip()
            if not continued:
                if rewrite_attempted:
                    break
                continue
            cleaned = f"{cleaned}\n\n{continued}".strip()

        self._validate_prose(
            cleaned,
            min_words=self.min_scene_words,
            artifact_name="scene",
        )
        self._store_scene_memory(chapter_number, scene_number, "draft", cleaned)
        return cleaned

    def _build_draft_continuation_directive(
        self,
        draft_text: str,
        directive: SceneDirective,
        *,
        failing_guard_reason: str,
    ) -> str:
        """Build deterministic continuation guidance from the trailing draft context."""

        pack = self._build_continuation_pack(
            draft_text, directive, failing_guard_reason
        )
        return "\n".join(
            [
                (
                    "CRITICAL: Continue exactly from this point. "
                    "DO NOT restart, summarize, paraphrase, or reframe prior text."
                ),
                f"Failing guard reason: {pack['failing_guard_reason']}",
                "Scene directive:",
                pack["scene_directive"],
                "Last 120 words:",
                pack["tail_words"],
                "Last complete sentence:",
                pack["last_complete_sentence"],
                "Unfinished fragment:",
                pack["unfinished_fragment"],
            ]
        )

    def _build_continuation_pack(
        self,
        draft_text: str,
        directive: SceneDirective,
        failing_guard_reason: str,
    ) -> dict[str, str]:
        """Capture deterministic local context needed for safe continuation."""

        words = str(draft_text).split()
        tail_words = " ".join(words[-120:]).strip()
        sentences = re.findall(r"[^.!?]+[.!?]", str(draft_text))
        last_complete_sentence = (
            sentences[-1].strip() if sentences else str(draft_text).strip()
        )
        unfinished_fragment = str(draft_text).strip()
        if sentences:
            unfinished_fragment = (
                str(draft_text).strip()[len("".join(sentences)) :].strip()
                or str(draft_text).strip()
            )

        directive_text = " | ".join(
            [
                f"goal={directive.goal}",
                f"conflict={directive.conflict}",
                f"stakes={directive.stakes}",
                f"outcome={directive.outcome}",
            ]
        )
        return {
            "tail_words": tail_words,
            "last_complete_sentence": last_complete_sentence,
            "unfinished_fragment": unfinished_fragment,
            "scene_directive": directive_text,
            "failing_guard_reason": str(failing_guard_reason).strip(),
        }

    def _build_truncation_rewrite_directive(
        self,
        directive: SceneDirective,
        *,
        failing_guard_reason: str,
    ) -> str:
        """Construct full rewrite guidance after bounded continuation attempts fail."""

        return "\n".join(
            [
                "CRITICAL CORRECTION: Continuation attempts failed; rewrite this scene from scratch.",
                f"Exact validation error: {str(failing_guard_reason).strip()}",
                f"Current goal: {directive.goal}",
                f"Current conflict: {directive.conflict}",
                f"Current outcome: {directive.outcome}",
                "Do not summarize. Keep the scene fully realized with a complete terminal beat.",
            ]
        )

    def _generate_edited_text(
        self,
        directive: SceneDirective,
        draft_text: str,
        chapter_number: int,
        scene_number: int,
    ) -> tuple[SceneDirective, str]:
        """Generate edited scene text with one fallback-redraft retry path."""

        current_directive = directive
        current_draft = draft_text
        attempts = max(1, self.max_scene_generation_attempts)
        planner_repair_used = False
        structure_local_failures = 0

        for attempt_index in range(attempts):
            try:
                edited_text = self.edit_scene(
                    current_directive,
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
                    current_directive,
                    chapter_number,
                    scene_number,
                    repair_directive=None,
                    repair_in_system_prompt=False,
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
                    current_directive,
                    chapter_number,
                    scene_number,
                    repair_directive=None,
                    repair_in_system_prompt=False,
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
                if self.enforce_scene_structure_contract and self.min_scene_words > 0:
                    self._validate_scene_structure(current_directive, cleaned)
                pre_guard_ok, pre_guard_reason = self._run_python_pre_guards(
                    current_directive,
                    cleaned,
                )
                if not pre_guard_ok:
                    raise BookEngineError(pre_guard_reason)
                self._store_scene_memory(
                    chapter_number,
                    scene_number,
                    "edited",
                    cleaned,
                )
                return current_directive, cleaned
            except BookEngineError as exc:
                if self.retry_draft_scene is None or attempt_index == attempts - 1:
                    raise
                repair_directive: str | None = None
                repair_in_system_prompt = False
                reason = "scene_validation_failed"
                exc_message = str(exc)
                if "scene_structure_missing" in exc_message:
                    reason = "scene_structure_missing"
                    structure_local_failures += 1
                    repair_directive = self._build_scene_structure_repair_directive(
                        current_directive,
                        exc_message,
                    )
                    repair_in_system_prompt = True
                if self.min_scene_words > 0:
                    produced_words = self._word_count(cleaned)
                    if produced_words < self.min_scene_words:
                        reason = "scene_too_short"
                        repair_directive = self._SCENE_DENSITY_REPAIR_DIRECTIVE
                        repair_in_system_prompt = False
                if exc_message.startswith("preguard_"):
                    reason = exc_message
                    (
                        repair_directive,
                        repair_in_system_prompt,
                    ) = self._build_pre_guard_repair_directive(
                        current_directive,
                        exc_message,
                    )

                self._notify_scene_retry(
                    chapter_number,
                    scene_number,
                    attempt=attempt_index + 1,
                    reason=reason,
                )
                if (
                    reason == "scene_structure_missing"
                    and self.repair_scene_directive is not None
                    and not planner_repair_used
                ):
                    directive_invalid = False
                    try:
                        self._validate_scene_directive(
                            current_directive,
                            scene_number=scene_number,
                        )
                    except BookEngineError:
                        directive_invalid = True

                    if directive_invalid or structure_local_failures >= 2:
                        current_directive = self._call_repair_scene_directive(
                            current_directive,
                            chapter_number,
                            scene_number,
                            exc_message,
                        )
                        self._validate_scene_directive(
                            current_directive,
                            scene_number=scene_number,
                        )
                        repair_directive = self._build_scene_structure_repair_directive(
                            current_directive,
                            exc_message,
                        )
                        repair_in_system_prompt = True
                        planner_repair_used = True
                current_draft = self._call_retry_draft_scene(
                    current_directive,
                    chapter_number,
                    scene_number,
                    repair_directive=repair_directive,
                    repair_in_system_prompt=repair_in_system_prompt,
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

        truncation_reason = self._detect_truncation_reason(text)
        if truncation_reason is not None:
            raise BookEngineError(
                f"{artifact_name.title()} output appears truncated or incomplete: "
                f"{truncation_reason}"
            )

    def _detect_truncation_reason(self, text: str) -> str | None:
        """Return truncation reason when prose likely ends mid-thought."""

        stripped = text.rstrip()
        if not stripped:
            return "empty_output"

        if stripped.endswith("..."):
            return "ellipsis_tail"

        words = self._word_count(stripped)
        contains_terminal = any(mark in stripped for mark in (".", "!", "?"))
        if (
            words >= 120
            and contains_terminal
            and not stripped.endswith(self._TERMINAL_PUNCTUATION)
        ):
            return "missing_terminal_punctuation"

        if stripped.count('"') % 2 != 0:
            return "unbalanced_double_quote"

        if stripped.count("(") != stripped.count(")"):
            return "unbalanced_parenthesis"

        if stripped.endswith((":", ";", ",", "-", "(", "[")):
            return "open_clause_tail"

        if words >= 80 and re.search(
            r"\b(and|or|but|because|that|which|who)$", stripped.lower()
        ):
            return "mid_sentence_cut"

        if (
            words >= 80
            and re.search(r"\b\w{1,6}$", stripped)
            and not stripped.endswith(self._TERMINAL_PUNCTUATION)
        ):
            return "abrupt_terminal_fragment"

        return None

    def _validate_scene_structure(
        self,
        directive: SceneDirective,
        scene_text: str,
    ) -> None:
        """Ensure scene prose reflects directive pillars before acceptance."""

        if not any(marker in scene_text for marker in (".", "!", "?", "\n")):
            return

        normalized_scene = scene_text.lower()
        missing: list[str] = []
        for field_name in ("goal", "conflict", "outcome"):
            raw = str(getattr(directive, field_name, "")).strip().lower()
            tokens = self._extract_scene_structure_tokens(raw)
            if not tokens:
                continue
            matched = [token for token in tokens[:6] if token in normalized_scene]
            required_matches = 2 if field_name == "outcome" and len(tokens) >= 2 else 1
            if len(set(matched)) < required_matches:
                missing.append(field_name)

        stakes_tokens = [
            token
            for token in str(getattr(directive, "stakes", "")).strip().lower().split()
            if len(token) > 3
        ]
        has_stakes_signal = any(
            token in normalized_scene for token in stakes_tokens[:4]
        )
        has_motivation_signal = any(
            marker in normalized_scene
            for marker in ("because", "wanted", "needed", "afraid", "decided")
        )
        if not has_stakes_signal and not has_motivation_signal:
            missing.append("motivation")

        if missing:
            raise BookEngineError(
                "scene_structure_missing:" + ",".join(sorted(set(missing)))
            )

    def _extract_scene_structure_tokens(self, text: str) -> list[str]:
        """Select meaningful tokens for directive-to-prose structure checks."""

        cleaned_tokens: list[str] = []
        for raw_token in str(text).split():
            token = re.sub(r"[^a-z0-9']+", "", raw_token.lower()).strip("'")
            if len(token) <= 3:
                continue
            if token in self._SCENE_STRUCTURE_STOPWORDS:
                continue
            cleaned_tokens.append(token)
        return cleaned_tokens

    @staticmethod
    def _extract_missing_scene_fields(reason: str) -> tuple[str, ...]:
        """Parse missing scene-structure fields from validator error text."""

        prefix, separator, suffix = str(reason).partition(":")
        if prefix.strip() != "scene_structure_missing" or not separator:
            return ()
        return tuple(
            field.strip().lower() for field in suffix.split(",") if field.strip()
        )

    def _build_combined_directive_text(
        self,
        directives: list[SceneDirective],
    ) -> str:
        """Serialize all scene directives into one deterministic reference string."""

        return "\n".join(
            " ".join(
                [
                    directive.goal,
                    directive.conflict,
                    directive.stakes,
                    directive.outcome,
                ]
            )
            for directive in directives
        )

    def _infer_expected_pov(self, directives: list[SceneDirective]) -> str | None:
        """Infer a likely POV character name from repeated directive proper nouns."""

        counts: dict[str, int] = {}
        for directive in directives:
            combined = " ".join(
                [
                    directive.goal,
                    directive.conflict,
                    directive.stakes,
                    directive.outcome,
                ]
            )
            for match in re.findall(r"\b[A-Z][a-z]{2,}\b", combined):
                lowered = match.lower()
                if lowered in self._POV_NAME_STOPWORDS:
                    continue
                counts[match] = counts.get(match, 0) + 1

        ranked = sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0].lower()),
        )
        if not ranked or ranked[0][1] < 2:
            return None
        return ranked[0][0]

    def _collect_directive_character_candidates(
        self,
        directives: list[SceneDirective],
    ) -> tuple[str, ...]:
        """Collect deterministic proper-noun candidates from scene directives."""

        names: set[str] = set()
        for directive in directives:
            combined = " ".join(
                [
                    directive.goal,
                    directive.conflict,
                    directive.stakes,
                    directive.outcome,
                ]
            )
            for match in re.findall(r"\b[A-Z][a-z]{2,}\b", combined):
                lowered = match.lower()
                if lowered in self._POV_NAME_STOPWORDS:
                    continue
                names.add(match)
        return tuple(sorted(names))

    def _extract_required_outline_threads(self, outline_text: str) -> tuple[str, ...]:
        """Extract explicit thread keywords demanded by the approved outline."""

        lowered = str(outline_text).lower()
        required = [
            keyword for keyword in self._OUTLINE_THREAD_KEYWORDS if keyword in lowered
        ]
        return tuple(required)

    def _requires_single_pov(
        self,
        directives: list[SceneDirective],
        expected_pov: str | None,
    ) -> bool:
        """Infer whether directives require a single-POV chapter realization."""

        pov_name = str(expected_pov or "").strip()
        if not pov_name:
            return False

        candidate_names = self._collect_directive_character_candidates(directives)
        competing = [
            name for name in candidate_names if name.lower() != pov_name.lower()
        ]
        return len(competing) <= 1

    def _is_reviewer_transport_failure(self, reason: str) -> bool:
        """Classify reviewer transport faults that should not trigger regeneration."""

        lowered = str(reason).strip().lower()
        return any(
            token in lowered for token in self._REVIEWER_TRANSPORT_FAILURE_TOKENS
        )

    def _stitch_with_deterministic_fallback(
        self,
        edited_scenes: list[str],
        chapter_number: int,
        min_chapter_words: int,
        generation_diagnostics: dict[str, Any],
    ) -> str:
        """Prefer stitch output, then anti-summarization retry, then deterministic join."""

        parity_ok = False
        parity_reason = "stitcher_summarization_detected"

        stitched = self.stitch_chapter(edited_scenes, chapter_number)
        stitched_text = str(stitched).strip()
        if not stitched_text:
            stitched_text = ""

        try:
            self._validate_prose(
                stitched_text,
                min_words=min_chapter_words,
                artifact_name="chapter",
            )
            parity_ok, parity_reason = self._validate_stitch_parity(
                stitched_text,
                edited_scenes,
            )
        except BookEngineError as exc:
            parity_reason = str(exc)

        if parity_ok:
            generation_diagnostics["stitch_deterministic_fallback_used"] = False
            return stitched_text

        generation_diagnostics["stitch_retry_reason"] = parity_reason
        anti_summary_instruction = (
            "STITCH CORRECTION: Preserve scene-level detail. Do not summarize, "
            "compress, or omit scene outcomes. Keep full narrative content "
            "from each approved edited scene in order."
        )
        restitched = self.stitch_chapter(
            [anti_summary_instruction, *edited_scenes], chapter_number
        )
        restitched_text = str(restitched).strip()
        if restitched_text:
            try:
                self._validate_prose(
                    restitched_text,
                    min_words=min_chapter_words,
                    artifact_name="chapter",
                )
                parity_ok, parity_reason = self._validate_stitch_parity(
                    restitched_text,
                    edited_scenes,
                )
                if parity_ok:
                    generation_diagnostics["stitch_deterministic_fallback_used"] = False
                    return restitched_text
            except BookEngineError as exc:
                parity_reason = str(exc)

        fallback_text = "\n\n".join(edited_scenes).strip()
        self._validate_prose(
            fallback_text,
            min_words=min_chapter_words,
            artifact_name="chapter",
        )
        parity_ok, parity_reason = self._validate_stitch_parity(
            fallback_text,
            edited_scenes,
        )
        if not parity_ok:
            raise BookEngineError(parity_reason)

        generation_diagnostics["stitch_deterministic_fallback_used"] = True
        return fallback_text

    def _build_chapter_retry_repair_directive(
        self,
        failure_reason: str,
        *,
        expected_pov: str | None,
    ) -> tuple[str | None, bool]:
        """Translate chapter-level validator failures into targeted retry guidance."""

        cleaned_reason = str(failure_reason).strip()
        lowered = cleaned_reason.lower()

        if lowered.startswith("missing_pov:"):
            pov_name = cleaned_reason.split(":", 1)[1].strip() or expected_pov or ""
            if not pov_name:
                return None, False
            return (
                "[CRITICAL SYSTEM CORRECTION: Your previous attempt was rejected "
                "because you completely omitted the required POV character: "
                f"{pov_name}. You MUST write from their perspective.]",
                True,
            )

        if lowered.startswith(("semantic_review:", "coherence_gate:")):
            return (
                "CRITICAL CORRECTION: The previous chapter attempt failed "
                "validation. You must delete non-compliant text and rewrite "
                "to follow the approved Scene Plan exactly. "
                f"Failure reason: {cleaned_reason}.",
                True,
            )

        if lowered.startswith("terminal_truncation:") or "truncated" in lowered:
            return (
                "CRITICAL SYSTEM CORRECTION: Your previous attempt was rejected "
                "because the prose ended mid-thought or with broken dialogue. "
                "Rewrite the chapter so the ending lands on complete sentences, "
                "balanced quotation marks, and a fully closed final beat.",
                True,
            )

        if lowered.startswith("insufficient_expansion:"):
            return (
                "CRITICAL SYSTEM CORRECTION: Your previous attempt was rejected "
                "because the prose did not expand the approved directives into "
                "enough narrative substance. Expand action, conflict, reaction, "
                "and outcome beats without adding filler.",
                False,
            )

        if lowered.startswith("plot_omission"):
            return (
                "CRITICAL: Your draft does not mention the planned outcome. "
                "Ensure this happens on-page.",
                True,
            )

        return None, False

    def _build_scene_structure_repair_directive(
        self,
        directive: SceneDirective,
        failure_reason: str,
    ) -> str:
        """Generate a concrete rewrite note for directive-to-prose drift."""

        missing = set(self._extract_missing_scene_fields(failure_reason))
        lines = [
            self._SCENE_STRUCTURE_REPAIR_PREFIX,
            f"Exact validation error: {str(failure_reason).strip()}",
            f"Current goal: {directive.goal}",
            f"Current conflict: {directive.conflict}",
            f"Current outcome: {directive.outcome}",
            (
                "Do not invent new locations, factions, or events outside the "
                "approved scene plan."
            ),
        ]
        if "goal" in missing:
            lines.append(f"Required goal on-page: {directive.goal}")
        if "conflict" in missing:
            lines.append(f"Required conflict on-page: {directive.conflict}")
        if "motivation" in missing or "stakes" in missing:
            lines.append(f"Make the stakes or motive explicit: {directive.stakes}")
        if "outcome" in missing or not missing:
            lines.extend(
                [
                    "Required final outcome beat:",
                    directive.outcome,
                    (
                        "The ending must show that exact discovery, decision, failure, "
                        "or change directly in action, dialogue, or realization."
                    ),
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _select_scene_for_required_thread(
        thread: str,
        directives: list[SceneDirective],
        edited_scenes: list[str],
    ) -> int:
        """Pick the most relevant scene index for thread-local repair."""

        lowered_thread = str(thread).strip().lower()
        if not lowered_thread:
            return max(0, len(directives) - 1)

        for index, directive in enumerate(directives):
            combined = " ".join(
                [
                    directive.goal,
                    directive.conflict,
                    directive.stakes,
                    directive.outcome,
                ]
            ).lower()
            if lowered_thread in combined:
                return index

        for index, scene_text in enumerate(edited_scenes):
            if lowered_thread in str(scene_text).lower():
                return index

        return max(0, len(directives) - 1)

    @staticmethod
    def _build_required_thread_scene_repair_directive(
        directive: SceneDirective,
        required_thread: str,
        failure_reason: str,
    ) -> str:
        """Build a scene-local correction prompt for missing required thread failures."""

        return "\n".join(
            [
                "CRITICAL: The scene must explicitly realize this required thread: "
                f"{required_thread}.",
                f"Exact validation error: {str(failure_reason).strip()}",
                f"Current goal: {directive.goal}",
                f"Current conflict: {directive.conflict}",
                f"Current outcome: {directive.outcome}",
                (
                    "Do not invent new locations, factions, or events outside the "
                    "approved scene plan."
                ),
            ]
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

        try:
            _SceneDirectiveContract.model_validate(directive.model_dump())
        except ValidationError as exc:
            raise BookEngineError(
                f"Scene planning produced invalid directive schema in scene {scene_number}: {exc}"
            ) from exc

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

        first_goal_token = self._first_token(directive.goal)
        if first_goal_token and self._is_likely_verb_token(first_goal_token):
            raise BookEngineError(
                "Scene planning produced invalid POV candidate in scene "
                f"{scene_number}: first goal token '{first_goal_token}' is verb-like"
            )

        pov_candidate = self._extract_primary_name_token(
            directive.goal,
            allow_first_token=False,
        )
        if pov_candidate and self._is_likely_verb_token(pov_candidate):
            raise BookEngineError(
                "Scene planning produced invalid POV candidate in scene "
                f"{scene_number}: '{pov_candidate}' is verb-like"
            )

        ledger_names = self._resolve_character_ledger_names()
        if ledger_names and not self._directive_mentions_ledger_name(
            directive,
            ledger_names,
        ):
            if len(ledger_names) == 1:
                _BOOK_ENGINE_LOGGER.info(
                    "scene_directive_single_pov_normalized",
                    scene_number=scene_number,
                    normalized_pov=ledger_names[0],
                    reason="single_character_ledger",
                )
            else:
                raise BookEngineError(
                    "Scene planning produced directive POV not aligned with character "
                    f"ledger in scene {scene_number}"
                )

        if pov_candidate and ledger_names:
            ledger_lower = {name.lower() for name in ledger_names}
            if pov_candidate.lower() not in ledger_lower:
                if len(ledger_names) == 1:
                    _BOOK_ENGINE_LOGGER.info(
                        "scene_directive_single_pov_candidate_normalized",
                        scene_number=scene_number,
                        original_pov=pov_candidate,
                        normalized_pov=ledger_names[0],
                    )
                else:
                    raise BookEngineError(
                        "Scene planning produced POV candidate outside character ledger "
                        f"in scene {scene_number}: {pov_candidate}"
                    )

    def _validate_entity_ledger(
        self,
        text: str,
        candidate_names: set[str],
    ) -> tuple[bool, str]:
        """Require deterministic presence of named directive entities in chapter prose."""

        keywords = [
            name.strip()
            for name in candidate_names
            if len(name.strip()) >= 3
            and name.strip().lower() not in self._POV_NAME_STOPWORDS
        ]
        if not keywords:
            return True, "ok"

        keyword_processor = KeywordProcessor(case_sensitive=False)
        for keyword in keywords:
            keyword_processor.add_keyword(keyword)

        matches = keyword_processor.extract_keywords(text)
        if matches:
            return True, "ok"
        return False, "entity_ledger_missing"

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.split())

    def _store_scene_memory(
        self,
        chapter_number: int,
        scene_number: int,
        stage: str,
        text: str,
    ) -> None:
        """Persist scene draft/edit snippets into optional memory backend."""

        if self.scene_memory_store is None:
            return
        self.scene_memory_store(chapter_number, scene_number, stage, text)

    def _fetch_scene_memory_context(
        self,
        chapter_number: int,
        scene_number: int,
        directive: SceneDirective,
    ) -> str | None:
        """Fetch top-k recent scene context from optional memory backend."""

        if self.scene_memory_fetch_context is None:
            return None
        context = self.scene_memory_fetch_context(
            chapter_number,
            scene_number,
            directive,
            3,
        )
        cleaned = str(context or "").strip()
        return cleaned or None

    @staticmethod
    def _merge_repair_with_memory_context(
        repair_directive: str | None,
        memory_context: str | None,
    ) -> str | None:
        """Inject RECENT CONTEXT block into draft prompts without losing repairs."""

        context_block = f"RECENT CONTEXT:\n{memory_context}" if memory_context else None
        if repair_directive and context_block:
            return f"{context_block}\n\n{repair_directive}"
        if repair_directive:
            return repair_directive
        return context_block

    def _run_python_pre_guards(
        self,
        directive: SceneDirective,
        scene_text: str,
    ) -> tuple[bool, str]:
        """Run deterministic scene checks before expensive chapter semantic review."""

        if self.retry_draft_scene is None:
            return True, "ok"

        pov_hint = self._normalized_scene_pov_hint(directive)
        if pov_hint and not check_pov(scene_text, pov_hint):
            return False, f"preguard_pov_missing:{pov_hint}"

        if not check_outcome_overlap(scene_text, directive.outcome):
            return False, "preguard_outcome_overlap"

        return True, "ok"

    @staticmethod
    def _build_pre_guard_repair_directive(
        directive: SceneDirective,
        failure_reason: str,
    ) -> tuple[str, bool]:
        """Create precise correction prompts for deterministic pre-guard failures."""

        lowered = str(failure_reason).lower()
        if lowered.startswith("preguard_pov_missing:"):
            pov_name = failure_reason.split(":", 1)[1].strip()
            return (
                "\n".join(
                    [
                        "CRITICAL CORRECTION: POV omission detected.",
                        f"Exact validation error: {str(failure_reason).strip()}",
                        f"Current goal: {directive.goal}",
                        f"Current conflict: {directive.conflict}",
                        f"Current outcome: {directive.outcome}",
                        f"Include {pov_name} directly on-page and keep narration anchored to them.",
                        (
                            "Do not invent new locations, factions, or events outside "
                            "the approved scene plan."
                        ),
                    ]
                ),
                True,
            )
        if lowered.startswith("preguard_outcome_overlap"):
            return (
                "\n".join(
                    [
                        "CRITICAL CORRECTION: Outcome overlap too low.",
                        f"Exact validation error: {str(failure_reason).strip()}",
                        f"Current goal: {directive.goal}",
                        f"Current conflict: {directive.conflict}",
                        f"Current outcome: {directive.outcome}",
                        "You must realize this exact planned outcome in-scene:",
                        directive.outcome,
                        (
                            "Do not invent new locations, factions, or events outside "
                            "the approved scene plan."
                        ),
                    ]
                ),
                True,
            )
        return ("CRITICAL CORRECTION: Deterministic guard failed. Rewrite scene.", True)

    def _extract_primary_name_token(
        self,
        text: str,
        *,
        allow_first_token: bool = True,
    ) -> str | None:
        """Extract a likely character-name token from directive text."""

        tokens = [token.strip(".,:;!?()[]{}\"'") for token in str(text).split()]
        for index, token in enumerate(tokens):
            if not allow_first_token and index == 0:
                continue
            if len(token) < 3:
                continue
            if not token[0].isalpha() or not token[0].isupper():
                continue
            if token.lower() in self._POV_NAME_STOPWORDS:
                continue
            return token
        return None

    @staticmethod
    def _first_token(text: str) -> str | None:
        for raw_token in str(text).split():
            token = raw_token.strip(".,:;!?()[]{}\"'")
            if token:
                return token
        return None

    def _is_likely_verb_token(self, token: str) -> bool:
        lowered = str(token).strip().lower()
        if not lowered:
            return False
        return lowered in self._POV_VERB_TOKENS

    def _resolve_character_ledger_names(self) -> tuple[str, ...]:
        if self.resolve_character_ledger_names is None:
            return ()
        try:
            raw_names = self.resolve_character_ledger_names()
        except Exception as exc:
            _BOOK_ENGINE_LOGGER.warning(
                "character_ledger_resolve_failed", error=str(exc)
            )
            return ()
        if not isinstance(raw_names, tuple):
            return ()
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_name in raw_names:
            name = str(raw_name).strip()
            if len(name) < 2:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(name)
        return tuple(normalized)

    @staticmethod
    def _directive_text(directive: SceneDirective) -> str:
        return " ".join(
            [
                str(directive.goal),
                str(directive.conflict),
                str(directive.stakes),
                str(directive.outcome),
            ]
        )

    def _directive_mentions_ledger_name(
        self,
        directive: SceneDirective,
        ledger_names: tuple[str, ...],
    ) -> bool:
        payload = self._directive_text(directive)
        for name in ledger_names:
            if re.search(rf"\b{re.escape(name)}\b", payload, flags=re.IGNORECASE):
                return True
        return False

    def _canonical_pov_from_ledger(
        self,
        directive: SceneDirective,
        ledger_names: tuple[str, ...],
    ) -> str | None:
        if not ledger_names:
            return None
        payload = self._directive_text(directive)
        for name in ledger_names:
            if re.search(rf"\b{re.escape(name)}\b", payload, flags=re.IGNORECASE):
                return name
        if len(ledger_names) == 1:
            return ledger_names[0]
        return None

    def _normalized_scene_pov_hint(self, directive: SceneDirective) -> str | None:
        """Resolve deterministic POV hint and normalize invalid planner tokens."""

        ledger_names = self._resolve_character_ledger_names()
        first_goal_token = self._first_token(directive.goal)
        raw_goal_candidate = self._extract_primary_name_token(
            directive.goal,
            allow_first_token=True,
        )
        pov_hint = self._extract_primary_name_token(
            directive.goal,
            allow_first_token=False,
        )

        if pov_hint is None:
            pov_hint = raw_goal_candidate

        invalid_reasons: list[str] = []
        if first_goal_token and self._is_likely_verb_token(first_goal_token):
            invalid_reasons.append("goal_first_token_verb")
        if pov_hint and self._is_likely_verb_token(pov_hint):
            invalid_reasons.append("verb_like")
        if pov_hint and ledger_names:
            if pov_hint.lower() not in {name.lower() for name in ledger_names}:
                invalid_reasons.append("outside_character_ledger")

        canonical = self._canonical_pov_from_ledger(directive, ledger_names)
        if invalid_reasons and canonical:
            if not pov_hint or canonical.lower() != pov_hint.lower():
                _BOOK_ENGINE_LOGGER.info(
                    "scene_pov_normalized",
                    original_pov=str(pov_hint or ""),
                    normalized_pov=canonical,
                    reasons=invalid_reasons,
                    goal=directive.goal,
                )
            return canonical
        if invalid_reasons:
            return None
        if pov_hint:
            return pov_hint
        return canonical

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
        repair_in_system_prompt: bool,
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
                    repair_in_system_prompt,
                )
            except TypeError:
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

    def _call_repair_scene_directive(
        self,
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        failure_reason: str,
    ) -> SceneDirective:
        """Call planner-side repair callback with backward-compatible signatures."""

        if self.repair_scene_directive is None:
            raise BookEngineError("Scene directive repair callback is not configured")

        repair_fn = self.repair_scene_directive
        try:
            return repair_fn(
                directive,
                chapter_number,
                scene_number,
                failure_reason,
            )
        except TypeError:
            return repair_fn(directive, chapter_number, scene_number)

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
