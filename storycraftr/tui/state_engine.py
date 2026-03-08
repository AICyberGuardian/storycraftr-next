from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml import YAMLError

from storycraftr.agent.narrative_state import NarrativeStateStore
from storycraftr.agent.memory_manager import NarrativeMemoryManager
from storycraftr.agent.story.scene_planner import plan_next_scene
from storycraftr.tui.canon import list_facts
from storycraftr.tui.context_builder import (
    build_scoped_context_block,
    compose_budgeted_prompt_with_diagnostics,
    PromptBudget,
    PromptDiagnostics,
)

_CHAPTER_FILE_PATTERN = re.compile(r"^chapter-(\d+)\.md$", re.IGNORECASE)
_FRONTMATTER_DELIMITER = "---"


@dataclass(frozen=True)
class ChapterState:
    """Normalized chapter-level state extracted from project files."""

    number: int
    title: str
    scene: str
    arc: str


@dataclass(frozen=True)
class NarrativeState:
    """Read-only narrative snapshot used by the TUI strips and prompt context."""

    chapters: tuple[ChapterState, ...]
    active_chapter: int | None
    active_scene: str
    active_arc: str
    memory_strip: str
    timeline_strip: str


class NarrativeStateEngine:
    """Read-only narrative-state builder with lightweight caching for TUI use."""

    def __init__(self, *, book_path: str, cache_ttl_seconds: int = 5) -> None:
        self.book_path = Path(book_path)
        self.cache_ttl_seconds = max(1, cache_ttl_seconds)
        self._cache: NarrativeState | None = None
        self._cached_at = 0.0
        self._active_chapter_override: int | None = None
        self._active_scene_override: str | None = None
        self.last_budget_metadata: PromptBudget | None = None
        self.last_prompt_diagnostics: PromptDiagnostics | None = None
        self.narrative_state_store = NarrativeStateStore(str(self.book_path))
        self._runtime_config: Any | None = None
        self.memory_manager = NarrativeMemoryManager(book_path=str(self.book_path))

    def configure(self, config: Any | None) -> None:
        """Apply runtime config updates for path-aware collaborators."""

        self._runtime_config = config
        self.memory_manager.configure(config)

    def refresh_memory_runtime(self) -> dict[str, Any]:
        """Reinitialize memory runtime and return refreshed diagnostics."""

        self.memory_manager.configure(self._runtime_config)
        return self.memory_manager.get_runtime_diagnostics()

    def set_active_chapter(self, chapter_number: int) -> None:
        """Update in-memory active chapter focus for strips and prompt context."""

        self._active_chapter_override = max(1, chapter_number)
        self._cache = None
        self._cached_at = 0.0

    def set_active_scene(self, scene_label: str) -> None:
        """Update in-memory active scene focus for strips and prompt context."""

        text = scene_label.strip()
        if text:
            self._active_scene_override = text
            self._cache = None
            self._cached_at = 0.0

    def get_state(self, *, force_refresh: bool = False) -> NarrativeState:
        """Return the current state snapshot, refreshing cached reads when needed."""

        now = time.time()
        if (
            not force_refresh
            and self._cache is not None
            and (now - self._cached_at) < self.cache_ttl_seconds
        ):
            return self._cache

        state = self._build_state()
        self._cache = state
        self._cached_at = now
        return state

    def build_prompt_block(self, *, state: NarrativeState) -> str:
        """Build a compact state block for prompt-prefix injection."""

        chapter_value = (
            str(state.active_chapter) if state.active_chapter is not None else "unknown"
        )
        return "\n".join(
            [
                "[Narrative State]",
                f"Active Chapter: {chapter_value}",
                f"Active Scene: {state.active_scene}",
                f"Current Arc: {state.active_arc}",
                f"Narrative Memory: {state.memory_strip}",
                f"Scene Timeline: {state.timeline_strip}",
                "[/Narrative State]",
            ]
        )

    def compose_prompt(
        self,
        user_prompt: str,
        *,
        provider: str = "openrouter",
        model_id: str = "openrouter/free",
        output_reserve_tokens: int | None = None,
        retrieved_context: list[str] | None = None,
        recent_turns: list[str] | None = None,
    ) -> str:
        """Compose a model-budgeted prompt with deterministic context pruning."""

        prompt, _budget, _diagnostics = self.compose_prompt_with_diagnostics(
            user_prompt,
            provider=provider,
            model_id=model_id,
            output_reserve_tokens=output_reserve_tokens,
            retrieved_context=retrieved_context,
            recent_turns=recent_turns,
        )
        return prompt

    def compose_prompt_with_diagnostics(
        self,
        user_prompt: str,
        *,
        provider: str = "openrouter",
        model_id: str = "openrouter/free",
        output_reserve_tokens: int | None = None,
        retrieved_context: list[str] | None = None,
        recent_turns: list[str] | None = None,
    ) -> tuple[str, PromptBudget, PromptDiagnostics]:
        """Compose prompt and return diagnostics for TUI observability commands."""

        state = self.get_state()
        canon_facts = self.get_active_canon_facts(state=state)
        memory_context = self.get_memory_context(
            state=state, user_query=user_prompt, provider=provider, model_id=model_id
        )
        merged_retrieved_context = list(memory_context)
        if retrieved_context:
            merged_retrieved_context.extend(retrieved_context)
        scene_plan = plan_next_scene(
            active_scene=state.active_scene,
            active_arc=state.active_arc,
            user_prompt=user_prompt,
        )
        prompt, budget, diagnostics = compose_budgeted_prompt_with_diagnostics(
            state=state,
            scene_plan=scene_plan,
            canon_facts=canon_facts,
            user_prompt=user_prompt,
            provider=provider,
            model_id=model_id,
            output_reserve_tokens=output_reserve_tokens,
            retrieved_context=merged_retrieved_context,
            recent_turns=recent_turns,
            narrative_state_json=self.narrative_state_store.render_prompt_block(),
        )
        self.last_budget_metadata = budget
        self.last_prompt_diagnostics = diagnostics
        return prompt, budget, diagnostics

    def build_scoped_context(
        self,
        user_prompt: str,
        *,
        retrieved_context: list[str] | None = None,
    ) -> str:
        """Build token-scoped context block with scene plan and constraints."""

        state = self.get_state()
        canon_facts = self.get_active_canon_facts(state=state)
        # Use default budget when provider/model_id unavailable (e.g., diagnostics)
        memory_context = self.get_memory_context(state=state, user_query=user_prompt)
        merged_retrieved_context = list(memory_context)
        if retrieved_context:
            merged_retrieved_context.extend(retrieved_context)
        scene_plan = plan_next_scene(
            active_scene=state.active_scene,
            active_arc=state.active_arc,
            user_prompt=user_prompt,
        )
        return build_scoped_context_block(
            state=state,
            scene_plan=scene_plan,
            canon_facts=canon_facts,
            retrieved_context=merged_retrieved_context,
            narrative_state_json=self.narrative_state_store.render_prompt_block(),
        )

    def record_turn_memory(self, *, user_prompt: str, assistant_response: str) -> bool:
        """Persist one turn to optional long-term memory storage."""

        state = self.get_state()
        return self.memory_manager.remember_turn(
            user_prompt=user_prompt,
            assistant_response=assistant_response,
            chapter=state.active_chapter,
            scene=state.active_scene,
        )

    def get_memory_context(
        self,
        *,
        state: NarrativeState,
        user_query: str | None = None,
        provider: str | None = None,
        model_id: str | None = None,
        max_items: int = 4,
        max_tokens: int | None = None,
    ) -> list[str]:
        """Return prompt-ready memory context bullets when available.

        A local memory token ceiling keeps long recalled snippets from consuming
        most of the budget before downstream prompt pruning runs.

        When user_query is provided, memory retrieval becomes semantically aware
        of the current prompt for improved relevance ranking.

        When provider/model_id are provided and max_tokens is None, the budget
        is scaled dynamically based on the model's context window (larger models
        receive larger memory budgets, capped at reasonable bounds).
        """

        if max_tokens is None:
            max_tokens = self._compute_memory_budget(
                provider=provider, model_id=model_id
            )

        items = self.memory_manager.get_context_items(
            chapter=state.active_chapter,
            max_items=max_items,
            query=user_query,
        )
        lines: list[str] = []
        consumed_tokens = 0
        token_limit = max(16, max_tokens)
        for item in items:
            label = "Intent" if item.source == "intent" else "Memory"
            line = f"{label}: {item.text}"
            estimated = _estimate_tokens(line)
            if consumed_tokens + estimated > token_limit:
                break
            lines.append(line)
            consumed_tokens += estimated
        return lines

    def _compute_memory_budget(
        self, *, provider: str | None, model_id: str | None
    ) -> int:
        """Compute memory recall token budget based on model context window.

        Larger models (e.g., 128k context) receive larger memory budgets to take
        advantage of available capacity. Smaller models (e.g., 8k context) use
        conservative budgets to preserve space for critical prompt sections.

        Returns a value between 160 and 1280 tokens, scaled as a percentage of
        the model's effective context window.
        """

        from storycraftr.llm.model_context import resolve_model_context

        spec = resolve_model_context(provider, model_id)
        context_window = spec.context_window_tokens

        # Memory budget as ~2% of context window, clamped to reasonable bounds
        budget = int(context_window * 0.02)
        budget = max(160, min(budget, 1280))
        return budget

    def memory_diagnostics(self) -> dict[str, Any]:
        """Return current long-term memory diagnostics for observability views."""

        return self.memory_manager.get_runtime_diagnostics()

    def get_active_canon_facts(
        self, *, state: NarrativeState, max_facts: int = 8
    ) -> list[str]:
        """Return chapter-scoped canon fact text for prompt constraint injection."""

        chapter = state.active_chapter
        if chapter is None:
            return []

        facts = list_facts(str(self.book_path), chapter=chapter)
        cleaned = [fact.text.strip() for fact in facts if fact.text.strip()]
        return cleaned[: max(1, max_facts)]

    def _build_state(self) -> NarrativeState:
        chapters = self._load_chapter_states()
        active_chapter = self._resolve_active_chapter(chapters)
        active_scene = self._resolve_active_scene(chapters, active_chapter)
        active_arc = self._resolve_active_arc(chapters, active_chapter)
        memory_strip = self._build_memory_strip(chapters, active_chapter, active_arc)
        timeline_strip = self._build_timeline_strip(chapters)

        return NarrativeState(
            chapters=tuple(chapters),
            active_chapter=active_chapter,
            active_scene=active_scene,
            active_arc=active_arc,
            memory_strip=memory_strip,
            timeline_strip=timeline_strip,
        )

    def _load_chapter_states(self) -> list[ChapterState]:
        """Load chapter metadata from chapter markdown frontmatter and outline YAML."""

        chapters_dir = self.book_path / "chapters"
        arc_lookup = self._load_outline_arc_map()
        chapter_states: list[ChapterState] = []

        if not chapters_dir.exists():
            return chapter_states

        for chapter_file in chapters_dir.glob("chapter-*.md"):
            chapter = self._parse_chapter_file(chapter_file)
            if chapter is None:
                continue

            if chapter.arc == "Unknown" and chapter.number in arc_lookup:
                chapter = ChapterState(
                    number=chapter.number,
                    title=chapter.title,
                    scene=chapter.scene,
                    arc=arc_lookup[chapter.number],
                )
            chapter_states.append(chapter)

        chapter_states.sort(key=lambda chapter: chapter.number)

        return chapter_states

    def _parse_chapter_file(self, chapter_file: Path) -> ChapterState | None:
        """Parse one chapter markdown file into a normalized chapter state object."""

        match = _CHAPTER_FILE_PATTERN.match(chapter_file.name)
        if match is None:
            return None

        number = int(match.group(1))
        try:
            raw_text = chapter_file.read_text(encoding="utf-8")
        except OSError:
            return None

        frontmatter, body = _split_frontmatter(raw_text)

        title = _first_non_empty(
            _coerce_text(frontmatter.get("title") if frontmatter else None),
            _extract_heading(body),
            f"Chapter {number}",
        )
        scene = _first_non_empty(
            _coerce_text(frontmatter.get("scene") if frontmatter else None),
            _coerce_text(frontmatter.get("beat") if frontmatter else None),
            "Unknown",
        )
        arc = _first_non_empty(
            _coerce_text(frontmatter.get("arc") if frontmatter else None),
            _coerce_text(frontmatter.get("act") if frontmatter else None),
            "Unknown",
        )

        return ChapterState(number=number, title=title, scene=scene, arc=arc)

    def _load_outline_arc_map(self) -> dict[int, str]:
        """Load optional chapter-to-arc mapping from outline YAML files."""

        outline_dir = self.book_path / "outline"
        if not outline_dir.exists():
            return {}

        chapter_arcs: dict[int, str] = {}
        for yaml_file in sorted(outline_dir.glob("*.yml")) + sorted(
            outline_dir.glob("*.yaml")
        ):
            try:
                content = yaml_file.read_text(encoding="utf-8")
                parsed = yaml.safe_load(content)
            except (OSError, YAMLError):
                continue
            if not isinstance(parsed, dict):
                continue

            for row in _iter_chapter_like_rows(parsed):
                chapter_number = _extract_chapter_number(row)
                arc_name = _extract_arc_name(row)
                if chapter_number is None or not arc_name:
                    continue
                chapter_arcs.setdefault(chapter_number, arc_name)

        return chapter_arcs

    def _resolve_active_chapter(self, chapters: list[ChapterState]) -> int | None:
        """Resolve active chapter from in-memory override or chapter list fallback."""

        if not chapters:
            return self._active_chapter_override

        chapter_numbers = {chapter.number for chapter in chapters}
        if (
            self._active_chapter_override is not None
            and self._active_chapter_override in chapter_numbers
        ):
            return self._active_chapter_override

        return max(chapter_numbers)

    def _resolve_active_scene(
        self, chapters: list[ChapterState], active_chapter: int | None
    ) -> str:
        """Resolve active scene from override or selected chapter metadata."""

        if self._active_scene_override:
            return self._active_scene_override

        chapter = _find_chapter(chapters, active_chapter)
        if chapter is None:
            return "Unknown"
        return chapter.scene

    def _resolve_active_arc(
        self, chapters: list[ChapterState], active_chapter: int | None
    ) -> str:
        """Resolve active arc from selected chapter metadata."""

        chapter = _find_chapter(chapters, active_chapter)
        if chapter is None:
            return "Unknown"
        return chapter.arc

    def _build_memory_strip(
        self,
        chapters: list[ChapterState],
        active_chapter: int | None,
        active_arc: str,
    ) -> str:
        """Build short narrative-memory strip text for the TUI."""

        chapter = _find_chapter(chapters, active_chapter)
        if chapter is None:
            return "Narrative: Chapter context unavailable"

        base = f"Narrative: Chapter {chapter.number} - {chapter.title}"
        if active_arc == "Unknown":
            return f"{base} | Arc unknown"
        return f"{base} | Arc: {active_arc}"

    def _build_timeline_strip(self, chapters: list[ChapterState]) -> str:
        """Build condensed scene timeline strip from most recent chapters."""

        if not chapters:
            return "Timeline: No scene map yet"

        tail = chapters[-3:]
        events = [
            f"Ch{item.number} {item.scene}"
            for item in tail
            if item.scene and item.scene != "Unknown"
        ]
        if not events:
            return "Timeline: Chapter metadata incomplete"
        return "Timeline: " + " -> ".join(events)


def _iter_chapter_like_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect chapter-shaped dictionaries from common outline YAML structures."""

    rows: list[dict[str, Any]] = []
    for value in payload.values():
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    rows.append(row)
        elif isinstance(value, dict):
            rows.extend(_iter_chapter_like_rows(value))
    return rows


def _extract_chapter_number(row: dict[str, Any]) -> int | None:
    """Extract a chapter number from common chapter keys in an outline row."""

    chapter_raw = row.get("chapter")
    if chapter_raw is None:
        chapter_raw = row.get("chapter_number")
    if chapter_raw is None:
        return None

    try:
        return int(str(chapter_raw).strip())
    except (TypeError, ValueError):
        return None


def _extract_arc_name(row: dict[str, Any]) -> str:
    """Extract an arc label from common keys in an outline row."""

    return _first_non_empty(
        _coerce_text(row.get("arc")),
        _coerce_text(row.get("act")),
        "",
    )


def _split_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    """Split markdown frontmatter and body, returning an empty dict on parse failures."""

    if not raw_text.startswith(f"{_FRONTMATTER_DELIMITER}\n"):
        return {}, raw_text

    separator = f"\n{_FRONTMATTER_DELIMITER}\n"
    end_idx = raw_text.find(separator, len(_FRONTMATTER_DELIMITER) + 1)
    if end_idx == -1:
        return {}, raw_text

    yaml_raw = raw_text[len(_FRONTMATTER_DELIMITER) + 1 : end_idx]
    body = raw_text[end_idx + len(separator) :]

    try:
        parsed = yaml.safe_load(yaml_raw)
    except YAMLError:
        return {}, raw_text
    if isinstance(parsed, dict):
        return parsed, body
    return {}, body


def _extract_heading(body: str) -> str:
    """Extract the first markdown heading line from a chapter body."""

    for line in body.splitlines():
        text = line.strip()
        if text.startswith("#"):
            return text.lstrip("#").strip()
    return ""


def _coerce_text(value: Any) -> str:
    """Convert scalar values to stripped text, returning empty for unsupported types."""

    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _first_non_empty(*values: str) -> str:
    """Return the first non-empty string from ordered candidates."""

    for value in values:
        if value:
            return value
    return ""


def _find_chapter(
    chapters: list[ChapterState], active_chapter: int | None
) -> ChapterState | None:
    """Find a chapter by number in normalized chapter state entries."""

    if active_chapter is None:
        return None
    for chapter in chapters:
        if chapter.number == active_chapter:
            return chapter
    return None


def _estimate_tokens(text: str) -> int:
    """Estimate tokens using the same coarse chars-per-token ratio as TUI prompts."""

    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)
