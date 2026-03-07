from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from storycraftr.agent.story.scene_planner import ScenePlan

if TYPE_CHECKING:
    from storycraftr.tui.state_engine import NarrativeState


@dataclass(frozen=True)
class ScopedContext:
    """Prompt-ready scoped context built for token-efficient generation."""

    scene_plan: ScenePlan
    state: "NarrativeState"
    canon_facts: tuple[str, ...]
    retrieved_context: tuple[str, ...]


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
