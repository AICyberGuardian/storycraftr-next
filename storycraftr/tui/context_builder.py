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


@dataclass(frozen=True)
class PromptDiagnostics:
    """Inspection metadata for prompt composition and pruning decisions."""

    included_sections: tuple[str, ...]
    pruned_sections: tuple[str, ...]
    truncated_sections: tuple[str, ...]
    estimated_tokens: dict[str, int]


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
    narrative_state_json: str | None = None,
    planner_rules: str | None = None,
    drafter_rules: str | None = None,
    editor_rules: str | None = None,
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
        f"Stakes: {scoped.scene_plan.stakes}",
        f"Outcome: {scoped.scene_plan.outcome}",
        f"Ending Beat: {scoped.scene_plan.ending_beat}",
        "[/Scene Plan]",
    ]

    if planner_rules and planner_rules.strip():
        lines.extend(["", "[Planner Rules]", planner_rules.strip(), "[/Planner Rules]"])

    if drafter_rules and drafter_rules.strip():
        lines.extend(["", "[Drafter Rules]", drafter_rules.strip(), "[/Drafter Rules]"])

    if editor_rules and editor_rules.strip():
        lines.extend(["", "[Editor Rules]", editor_rules.strip(), "[/Editor Rules]"])

    lines.extend(
        [
            "",
            "[Scoped Context]",
            f"Active Chapter: {chapter_value}",
            f"Active Scene: {scoped.state.active_scene}",
            f"Current Arc: {scoped.state.active_arc}",
            f"Narrative Memory: {scoped.state.memory_strip}",
            f"Scene Timeline: {scoped.state.timeline_strip}",
        ]
    )

    if scoped.canon_facts:
        lines.append("[Canon Constraints]")
        lines.extend(f"- {fact}" for fact in scoped.canon_facts)

    if scoped.retrieved_context:
        lines.append("[Relevant Context]")
        lines.extend(f"- {item}" for item in scoped.retrieved_context)

    if narrative_state_json:
        lines.append("[Structured Narrative State]")
        lines.append(narrative_state_json)
        lines.append("[/Structured Narrative State]")

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
    narrative_state_json: str | None = None,
    planner_rules: str | None = None,
    drafter_rules: str | None = None,
    editor_rules: str | None = None,
    max_facts: int = 5,
    max_retrieval_chunks: int = 3,
    max_recent_turns: int = 3,
) -> tuple[str, PromptBudget]:
    """Compose a model-budgeted prompt with deterministic priority pruning."""

    prompt, budget, _ = compose_budgeted_prompt_with_diagnostics(
        state=state,
        scene_plan=scene_plan,
        canon_facts=canon_facts,
        user_prompt=user_prompt,
        provider=provider,
        model_id=model_id,
        output_reserve_tokens=output_reserve_tokens,
        retrieved_context=retrieved_context,
        recent_turns=recent_turns,
        narrative_state_json=narrative_state_json,
        planner_rules=planner_rules,
        drafter_rules=drafter_rules,
        editor_rules=editor_rules,
        max_facts=max_facts,
        max_retrieval_chunks=max_retrieval_chunks,
        max_recent_turns=max_recent_turns,
    )
    return prompt, budget


def compose_budgeted_prompt_with_diagnostics(
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
    narrative_state_json: str | None = None,
    planner_rules: str | None = None,
    drafter_rules: str | None = None,
    editor_rules: str | None = None,
    max_facts: int = 5,
    max_retrieval_chunks: int = 3,
    max_recent_turns: int = 3,
) -> tuple[str, PromptBudget, PromptDiagnostics]:
    """Compose a model-budgeted prompt plus diagnostics for observability views."""

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
    normalized_planner_rules = (planner_rules or "").strip()
    normalized_drafter_rules = (drafter_rules or "").strip()
    normalized_editor_rules = (editor_rules or "").strip()

    # Priority-5 (lowest): extra state strips.
    include_memory_strip = True
    include_timeline_strip = True
    # Priority-4: retrieval chunks.
    active_rag = list(rag_items)
    # Priority-3: compacted summary + recent dialogue.
    summary_text = ""
    dialogue_items: list[str] = []
    for item in recent_items:
        if item.startswith("Session Summary:") and not summary_text:
            summary_text = item.split(":", 1)[1].strip()
            continue
        dialogue_items.append(item)
    active_recent = list(dialogue_items)
    include_summary_section = bool(summary_text)
    # Priority-2: scene/scoped context details.
    include_arc_line = True
    include_scene_conflict = True
    include_scene_outcome = True
    include_narrative_state = bool((narrative_state_json or "").strip())
    include_planner_rules = bool(normalized_planner_rules)
    include_drafter_rules = bool(normalized_drafter_rules)
    include_editor_rules = bool(normalized_editor_rules)
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
        lines.append(f"Stakes: {scene_plan.stakes}")
        if include_scene_outcome:
            lines.append(f"Outcome: {scene_plan.outcome}")
        lines.append(f"Ending Beat: {scene_plan.ending_beat}")
        lines.append("[/Scene Plan]")

        if include_planner_rules and normalized_planner_rules:
            lines.extend(
                ["", "[Planner Rules]", normalized_planner_rules, "[/Planner Rules]"]
            )

        if include_drafter_rules and normalized_drafter_rules:
            lines.extend(
                ["", "[Drafter Rules]", normalized_drafter_rules, "[/Drafter Rules]"]
            )

        if include_editor_rules and normalized_editor_rules:
            lines.extend(
                ["", "[Editor Rules]", normalized_editor_rules, "[/Editor Rules]"]
            )

        lines.extend(["", "[Scoped Context]"])
        lines.append(f"Active Chapter: {chapter_value}")
        lines.append(f"Active Scene: {state.active_scene}")
        if include_arc_line:
            lines.append(f"Current Arc: {state.active_arc}")
        if include_memory_strip:
            lines.append(f"Narrative Memory: {state.memory_strip}")
        if include_timeline_strip:
            lines.append(f"Scene Timeline: {state.timeline_strip}")

        if active_canon:
            lines.append("[Canon Constraints]")
            lines.extend(f"- {fact}" for fact in active_canon)

        if active_rag:
            lines.append("[Relevant Context]")
            lines.extend(f"- {item}" for item in active_rag)

        if include_narrative_state and narrative_state_json:
            lines.append("[Structured Narrative State]")
            lines.append(narrative_state_json)
            lines.append("[/Structured Narrative State]")

        lines.append("[/Scoped Context]")

        if include_summary_section and summary_text:
            lines.append("")
            lines.append("[Session Summary]")
            lines.append(summary_text)
            lines.append("[/Session Summary]")

        if active_recent:
            lines.append("")
            lines.append("[Recent Dialogue]")
            lines.extend(f"- {turn}" for turn in active_recent)
            lines.append("[/Recent Dialogue]")

        lines.extend(["", "[User Instruction]", cleaned_user_prompt])
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
        elif include_editor_rules:
            include_editor_rules = False
        elif include_drafter_rules:
            include_drafter_rules = False
        elif include_planner_rules:
            include_planner_rules = False
        elif include_arc_line:
            include_arc_line = False
        elif include_scene_outcome:
            include_scene_outcome = False
        elif include_scene_conflict:
            include_scene_conflict = False
        elif include_narrative_state:
            include_narrative_state = False
        elif include_summary_section:
            include_summary_section = False
        elif active_canon:
            active_canon.pop()
        else:
            # Last-resort overflow guard: keep a bounded user prompt instead of hard-failing.
            scoped_without_user = _render_prompt().rsplit(
                "\n[User Instruction]\n", maxsplit=1
            )
            non_user = scoped_without_user[0] if scoped_without_user else ""
            used_tokens = _estimate_tokens(non_user + "\n[User Instruction]\n")
            remaining = max(16, input_budget_tokens - used_tokens)
            cleaned_user_prompt = _trim_to_budget(cleaned_user_prompt, remaining)
            break

        prompt = _render_prompt()

    has_canon_section = bool(canon_items)
    has_retrieval_section = bool(rag_items)
    has_recent_section = bool(dialogue_items)
    has_summary_section = bool(summary_text)
    has_narrative_state = include_narrative_state or bool(
        (narrative_state_json or "").strip()
    )
    has_planner_rules = bool(normalized_planner_rules)
    has_drafter_rules = bool(normalized_drafter_rules)
    has_editor_rules = bool(normalized_editor_rules)

    included_sections = [
        "scene_plan",
        "scoped_context",
        "user_instruction",
    ]
    pruned_sections: list[str] = []
    truncated_sections: list[str] = []

    if active_canon:
        included_sections.append("canon_constraints")
    elif has_canon_section:
        pruned_sections.append("canon_constraints")

    if active_rag:
        included_sections.append("retrieved_context")
        if len(active_rag) < len(rag_items):
            truncated_sections.append("retrieved_context")
    elif has_retrieval_section:
        pruned_sections.append("retrieved_context")

    if active_recent:
        included_sections.append("recent_dialogue")
        if len(active_recent) < len(dialogue_items):
            truncated_sections.append("recent_dialogue")
    elif has_recent_section:
        pruned_sections.append("recent_dialogue")

    if include_summary_section and has_summary_section:
        included_sections.append("summary")
    elif has_summary_section:
        pruned_sections.append("summary")

    if include_narrative_state and has_narrative_state:
        included_sections.append("narrative_state")
    elif has_narrative_state:
        pruned_sections.append("narrative_state")

    if include_planner_rules and has_planner_rules:
        included_sections.append("planner_rules")
    elif has_planner_rules:
        pruned_sections.append("planner_rules")

    if include_drafter_rules and has_drafter_rules:
        included_sections.append("drafter_rules")
    elif has_drafter_rules:
        pruned_sections.append("drafter_rules")

    if include_editor_rules and has_editor_rules:
        included_sections.append("editor_rules")
    elif has_editor_rules:
        pruned_sections.append("editor_rules")

    if not include_memory_strip:
        pruned_sections.append("memory_strip")
    else:
        included_sections.append("memory_strip")

    if not include_timeline_strip:
        pruned_sections.append("timeline_strip")
    else:
        included_sections.append("timeline_strip")

    if not include_arc_line:
        pruned_sections.append("arc_line")
    else:
        included_sections.append("arc_line")

    if not include_scene_conflict:
        pruned_sections.append("scene_conflict")
    else:
        included_sections.append("scene_conflict")

    if not include_scene_outcome:
        pruned_sections.append("scene_outcome")
    else:
        included_sections.append("scene_outcome")

    estimated_tokens = {
        "canon": _estimate_tokens("\n".join(active_canon)),
        "retrieved_context": _estimate_tokens("\n".join(active_rag)),
        "recent_dialogue": _estimate_tokens("\n".join(active_recent)),
        "scene_plan": _estimate_tokens(
            "\n".join(
                [
                    scene_plan.goal,
                    scene_plan.conflict if include_scene_conflict else "",
                    scene_plan.outcome if include_scene_outcome else "",
                ]
            )
        ),
        "scoped_context": _estimate_tokens(
            "\n".join(
                [
                    f"chapter={state.active_chapter}",
                    f"scene={state.active_scene}",
                    state.active_arc if include_arc_line else "",
                    state.memory_strip if include_memory_strip else "",
                    state.timeline_strip if include_timeline_strip else "",
                ]
            )
        ),
        "user_instruction": _estimate_tokens(cleaned_user_prompt),
        "summary": _estimate_tokens(summary_text if include_summary_section else ""),
        "narrative_state": _estimate_tokens(
            narrative_state_json
            if include_narrative_state and narrative_state_json
            else ""
        ),
        "planner_rules": _estimate_tokens(
            normalized_planner_rules if include_planner_rules else ""
        ),
        "drafter_rules": _estimate_tokens(
            normalized_drafter_rules if include_drafter_rules else ""
        ),
        "editor_rules": _estimate_tokens(
            normalized_editor_rules if include_editor_rules else ""
        ),
        "full_prompt": _estimate_tokens(prompt),
    }

    diagnostics = PromptDiagnostics(
        included_sections=tuple(included_sections),
        pruned_sections=tuple(pruned_sections),
        truncated_sections=tuple(truncated_sections),
        estimated_tokens=estimated_tokens,
    )
    return prompt, budget, diagnostics


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
