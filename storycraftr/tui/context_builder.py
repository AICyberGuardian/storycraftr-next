from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

from storycraftr.agent.story.scene_planner import ScenePlan
from storycraftr.llm.model_context import (
    compute_input_budget_tokens,
    resolve_model_context,
)

if TYPE_CHECKING:
    from storycraftr.tui.state_engine import NarrativeState


@dataclass(frozen=True)
class ScopedContext:
    """Prompt-ready scoped context built for token-efficient generation."""

    scene_plan: ScenePlan
    state: "NarrativeState"
    canon_facts: tuple[str, ...]
    retrieved_context: tuple[str, ...]


@dataclass(frozen=True)
class PromptBudget:
    """Resolved prompt budget for one turn."""

    context_window_tokens: int
    output_reserve_tokens: int
    input_budget_tokens: int
    model_source: str


_CHARS_PER_TOKEN_ESTIMATE = 4


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN_ESTIMATE))


def _trim_to_budget(text: str, budget_tokens: int) -> str:
    if budget_tokens <= 0:
        return ""

    max_chars = budget_tokens * _CHARS_PER_TOKEN_ESTIMATE
    if len(text) <= max_chars:
        return text

    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def build_scoped_context_block(
    *,
    state: "NarrativeState",
    scene_plan: ScenePlan,
    canon_facts: list[str],
    retrieved_context: list[str] | None = None,
    max_facts: int = 5,
    max_retrieval_chunks: int = 3,
) -> str:
    """Build a compact context block with explicit scene plan and constraints."""

    scoped = ScopedContext(
        scene_plan=scene_plan,
        state=state,
        canon_facts=tuple(_clean_items(canon_facts, limit=max_facts)),
        retrieved_context=tuple(
            _clean_items(retrieved_context or [], limit=max_retrieval_chunks)
        ),
    )

    chapter_value = (
        str(scoped.state.active_chapter)
        if scoped.state.active_chapter is not None
        else "unknown"
    )

    lines = [
        "[Scene Plan]",
        f"Goal: {scoped.scene_plan.goal}",
        f"Conflict: {scoped.scene_plan.conflict}",
        f"Outcome: {scoped.scene_plan.outcome}",
        "[/Scene Plan]",
        "",
        "[Scoped Context]",
        f"Active Chapter: {chapter_value}",
        f"Active Scene: {scoped.state.active_scene}",
        f"Current Arc: {scoped.state.active_arc}",
        f"Narrative Memory: {scoped.state.memory_strip}",
        f"Scene Timeline: {scoped.state.timeline_strip}",
    ]

    if scoped.canon_facts:
        lines.append("[Active Constraints]")
        lines.extend(f"- {fact}" for fact in scoped.canon_facts)

    if scoped.retrieved_context:
        lines.append("[Relevant Context]")
        lines.extend(f"- {item}" for item in scoped.retrieved_context)

    lines.append("[/Scoped Context]")
    return "\n".join(lines)


def compose_budgeted_prompt(
    *,
    state: "NarrativeState",
    scene_plan: ScenePlan,
    canon_facts: list[str],
    user_prompt: str,
    provider: str,
    model_id: str,
    output_reserve_tokens: int | None,
    retrieved_context: list[str] | None = None,
    recent_turns: list[str] | None = None,
    max_facts: int = 5,
    max_retrieval_chunks: int = 3,
    max_recent_turns: int = 3,
) -> tuple[str, PromptBudget]:
    """Compose a model-budgeted prompt with deterministic priority pruning."""

    model_spec = resolve_model_context(provider, model_id)
    input_budget_tokens = compute_input_budget_tokens(
        model_spec,
        requested_output_tokens=output_reserve_tokens,
    )
    reserve_tokens = model_spec.context_window_tokens - input_budget_tokens
    budget = PromptBudget(
        context_window_tokens=model_spec.context_window_tokens,
        output_reserve_tokens=reserve_tokens,
        input_budget_tokens=input_budget_tokens,
        model_source=model_spec.source,
    )

    canon_items = _clean_items(canon_facts, limit=max_facts)
    rag_items = _clean_items(retrieved_context or [], limit=max_retrieval_chunks)
    recent_items = _clean_items(recent_turns or [], limit=max_recent_turns)

    # Priority-5 (lowest): extra state strips.
    include_memory_strip = True
    include_timeline_strip = True
    # Priority-4: retrieval chunks.
    active_rag = list(rag_items)
    # Priority-3: minimal recent turns.
    active_recent = list(recent_items)
    # Priority-2: scene/scoped context details.
    include_arc_line = True
    include_scene_conflict = True
    include_scene_outcome = True
    # Priority-1 (highest): canon constraints.
    active_canon = list(canon_items)

    cleaned_user_prompt = user_prompt.strip()

    def _render_prompt() -> str:
        chapter_value = (
            str(state.active_chapter) if state.active_chapter is not None else "unknown"
        )

        lines = ["[Scene Plan]", f"Goal: {scene_plan.goal}"]
        if include_scene_conflict:
            lines.append(f"Conflict: {scene_plan.conflict}")
        if include_scene_outcome:
            lines.append(f"Outcome: {scene_plan.outcome}")
        lines.extend(["[/Scene Plan]", "", "[Scoped Context]"])
        lines.append(f"Active Chapter: {chapter_value}")
        lines.append(f"Active Scene: {state.active_scene}")
        if include_arc_line:
            lines.append(f"Current Arc: {state.active_arc}")
        if include_memory_strip:
            lines.append(f"Narrative Memory: {state.memory_strip}")
        if include_timeline_strip:
            lines.append(f"Scene Timeline: {state.timeline_strip}")

        if active_canon:
            lines.append("[Active Constraints]")
            lines.extend(f"- {fact}" for fact in active_canon)

        if active_rag:
            lines.append("[Relevant Context]")
            lines.extend(f"- {item}" for item in active_rag)

        lines.append("[/Scoped Context]")

        if active_recent:
            lines.append("")
            lines.append("[Recent Turns]")
            lines.extend(f"- {turn}" for turn in active_recent)
            lines.append("[/Recent Turns]")

        lines.extend(["", "[User Prompt]", cleaned_user_prompt])
        return "\n".join(lines)

    prompt = _render_prompt()
    while _estimate_tokens(prompt) > input_budget_tokens:
        if include_timeline_strip:
            include_timeline_strip = False
        elif include_memory_strip:
            include_memory_strip = False
        elif active_rag:
            active_rag.pop()
        elif active_recent:
            active_recent.pop()
        elif include_arc_line:
            include_arc_line = False
        elif include_scene_outcome:
            include_scene_outcome = False
        elif include_scene_conflict:
            include_scene_conflict = False
        elif active_canon:
            active_canon.pop()
        else:
            # Last-resort overflow guard: keep a bounded user prompt instead of hard-failing.
            scoped_without_user = _render_prompt().rsplit(
                "\n[User Prompt]\n", maxsplit=1
            )
            non_user = scoped_without_user[0] if scoped_without_user else ""
            used_tokens = _estimate_tokens(non_user + "\n[User Prompt]\n")
            remaining = max(16, input_budget_tokens - used_tokens)
            cleaned_user_prompt = _trim_to_budget(cleaned_user_prompt, remaining)
            break

        prompt = _render_prompt()

    return prompt, budget


def _clean_items(values: list[str], *, limit: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()

    for raw in values:
        text = " ".join(raw.split()).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(_truncate(text, limit=220))
        if len(cleaned) >= max(1, limit):
            break

    return cleaned


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
