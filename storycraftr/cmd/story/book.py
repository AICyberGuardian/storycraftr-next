from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

import click
from rich.console import Console

from storycraftr.agent.agents import create_or_get_assistant
from storycraftr.agent.book_engine import (
    BookEngine,
    BookEngineError,
    BookEngineStage,
    ChapterRunArtifact,
)
from storycraftr.agent.generation_pipeline import SceneGenerationPipeline
from storycraftr.agent.memory_manager import NarrativeMemoryManager
from storycraftr.agent.narrative_state import NarrativeStateStore, SceneDirective
from storycraftr.agent.state_extractor import extract_state_patch
from storycraftr.prompts.craft_rules import load_craft_rule_set
from storycraftr.tui.canon import load_canon, save_canon
from storycraftr.utils.core import load_book_config

console = Console()


@dataclass(frozen=True)
class BookRunSummary:
    """Execution summary returned by the `book` command pipeline."""

    chapters_generated: int
    coherence_reviews_run: int
    patch_operations_applied: int


def _normalize_model_output(value: Any) -> str:
    """Normalize model response payloads into plain text."""

    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
            else:
                text = str(item).strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content).strip()


def _invoke_model_text(
    assistant: Any,
    *,
    system_rules: str,
    prompt: str,
) -> str:
    """Invoke the configured model and return normalized text output."""

    composed = f"{system_rules.strip()}\n\n{prompt.strip()}" if system_rules else prompt
    try:
        response = assistant.llm.invoke(composed)
    except Exception as exc:
        raise BookEngineError(f"Model invocation failed: {exc}") from exc

    text = _normalize_model_output(response)
    if not text:
        raise BookEngineError("Model invocation returned empty text")
    return text


def _extract_json_object(text: str) -> str:
    """Extract the most likely JSON object payload from model output text."""

    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        return stripped[first : last + 1]
    raise ValueError("No JSON object found in model output")


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _serialize_plot_threads(snapshot: Any) -> str:
    """Serialize plot thread state into a stable JSON payload for canon facts."""

    rows: list[dict[str, Any]] = []
    for item in getattr(snapshot, "plot_threads", []):
        if hasattr(item, "model_dump"):
            payload = dict(item.model_dump())
        elif isinstance(item, dict):
            payload = dict(item)
        else:
            continue
        rows.append(
            {
                "id": str(payload.get("id", "")).strip(),
                "status": str(payload.get("status", "")).strip(),
                "introduced_chapter": payload.get("introduced_chapter"),
                "must_resolve_by_chapter": payload.get("must_resolve_by_chapter"),
                "resolved_chapter": payload.get("resolved_chapter"),
            }
        )

    rows.sort(key=lambda row: row.get("id", ""))
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _persist_canon_ledger(
    *,
    book_path: str,
    chapter_number: int,
    snapshot: Any,
) -> None:
    """Persist/update outline/canon.yml for a committed chapter."""

    data = load_canon(book_path)
    chapters = data.setdefault("chapters", {})
    if not isinstance(chapters, dict):
        raise RuntimeError("Invalid canon ledger: 'chapters' must be a mapping")

    chapter_key = str(chapter_number)
    chapter_payload = chapters.setdefault(chapter_key, {"facts": []})
    if not isinstance(chapter_payload, dict):
        chapter_payload = {"facts": []}
        chapters[chapter_key] = chapter_payload

    facts = chapter_payload.setdefault("facts", [])
    if not isinstance(facts, list):
        facts = []
        chapter_payload["facts"] = facts

    fact_id = f"book-plot-threads-{chapter_number:03d}"
    replacement = {
        "id": fact_id,
        "text": f"plot_threads: {_serialize_plot_threads(snapshot)}",
        "type": "plot_threads",
        "source": "accepted",
    }

    updated = False
    for index, row in enumerate(facts):
        if isinstance(row, dict) and str(row.get("id", "")).strip() == fact_id:
            facts[index] = replacement
            updated = True
            break
    if not updated:
        facts.append(replacement)

    save_canon(book_path, data)


def run_book_pipeline(
    *,
    book_path: str,
    seed_text: str,
    chapters: int,
    auto_approve: bool,
) -> BookRunSummary:
    """Run the disciplined book engine loop with CLI-based approvals."""

    runtime_config = None
    try:
        runtime_config = load_book_config(book_path)
    except Exception:
        runtime_config = None

    assistant = create_or_get_assistant(book_path)
    state_store = NarrativeStateStore(book_path)
    memory_manager = NarrativeMemoryManager(book_path=book_path, config=runtime_config)
    rules = load_craft_rule_set()
    pipeline = SceneGenerationPipeline(
        planner_rules=rules.planner.text,
        drafter_rules=rules.drafter.text,
        editor_rules=rules.editor.text,
    )

    def _build_outline(
        seed: str,
        chapter_number: int,
        history: tuple[ChapterRunArtifact, ...],
    ) -> str:
        history_lines = [
            f"Chapter {item.chapter_number}: {item.stitched_text[:300]}"
            for item in history[-2:]
        ]
        prompt = "\n".join(
            [
                "Create a concise rolling outline for the next chapter.",
                f"Target chapter: {chapter_number}",
                "Pinned seed:",
                seed,
                "Recent chapter context:",
                "\n".join(history_lines) or "(none)",
                "Return markdown bullets only.",
            ]
        )
        return _invoke_model_text(
            assistant,
            system_rules=rules.planner.text,
            prompt=prompt,
        )

    def _build_scene_plan(outline: str, chapter_number: int) -> list[SceneDirective]:
        directives: list[SceneDirective] = []
        for scene_number in range(1, 4):
            base_prompt = "\n".join(
                [
                    f"Chapter {chapter_number}, scene {scene_number} of 3.",
                    "Use this approved chapter outline:",
                    outline,
                ]
            )

            parsed_directive: SceneDirective | None = None
            last_error: Exception | None = None
            planner_input = base_prompt
            for _attempt in range(3):
                planner_prompt = pipeline.build_planner_user_prompt(planner_input)
                planner_response = _invoke_model_text(
                    assistant,
                    system_rules=rules.planner.text,
                    prompt=planner_prompt,
                )
                try:
                    parsed_directive = pipeline.parse_scene_directive(planner_response)
                    break
                except Exception as exc:
                    last_error = exc
                    planner_input = "\n".join(
                        [
                            "Repair this into strict JSON with keys:",
                            "goal, conflict, stakes, outcome.",
                            "Return JSON only with double-quoted keys/values.",
                            planner_response,
                        ]
                    )

            if parsed_directive is None:
                raise BookEngineError(
                    "Scene planner failed to return parseable directive"
                ) from last_error

            directives.append(parsed_directive)
        return directives

    def _draft_scene(
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        prompt = pipeline.build_drafter_user_prompt(
            user_input=(
                f"Chapter {chapter_number} scene {scene_number}. "
                "Write 800-1200 words and keep continuity tight."
            ),
            directive=directive,
        )
        return _invoke_model_text(
            assistant,
            system_rules=rules.drafter.text,
            prompt=prompt,
        )

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        prompt = pipeline.build_editor_user_prompt(
            user_input=(
                f"Revise chapter {chapter_number} scene {scene_number} for craft and canon."
            ),
            directive=directive,
            draft=draft,
        )
        return _invoke_model_text(
            assistant,
            system_rules=rules.editor.text,
            prompt=prompt,
        )

    def _retry_draft(
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        retry_prompt = pipeline.build_drafter_user_prompt(
            user_input=(
                f"Retry draft for chapter {chapter_number} scene {scene_number}. "
                "Address prior coherence issues and preserve directive fidelity."
            ),
            directive=directive,
        )
        return _invoke_model_text(
            assistant,
            system_rules=rules.drafter.text,
            prompt=retry_prompt,
        )

    def _stitch_chapter(edited_scenes: list[str], chapter_number: int) -> str:
        prompt = "\n\n".join(
            [
                (
                    f"Stitch chapter {chapter_number} scene transitions. "
                    "Return a single cohesive chapter preserving all major beats."
                ),
                *[
                    f"[Scene {index}]\n{scene_text}"
                    for index, scene_text in enumerate(edited_scenes, start=1)
                ],
            ]
        )
        return _invoke_model_text(
            assistant,
            system_rules=rules.stitcher.text,
            prompt=prompt,
        )

    def _derive_state_update(chapter_text: str, chapter_number: int) -> dict[str, Any]:
        snapshot = state_store.load()
        extraction = extract_state_patch(chapter_text, snapshot=snapshot)
        return {
            "chapter_text": chapter_text,
            "chapter_number": chapter_number,
            "patch": extraction.patch,
            "events": extraction.events,
            "snapshot": snapshot,
        }

    def _commit_state_update(update: dict[str, Any], chapter_number: int) -> None:
        patch = update["patch"]
        snapshot = state_store.apply_patch(patch, actor="book-engine")

        try:
            _persist_canon_ledger(
                book_path=book_path,
                chapter_number=chapter_number,
                snapshot=snapshot,
            )
        except Exception as exc:
            raise RuntimeError(f"Canon ledger write failed: {exc}") from exc

        chapter_dir = Path(book_path) / "chapters"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        chapter_file = chapter_dir / f"chapter-{chapter_number}.md"
        chapter_file.write_text(
            str(update["chapter_text"]).strip() + "\n", encoding="utf-8"
        )

    def _coherence_review(
        seed: str,
        history: tuple[ChapterRunArtifact, ...],
    ) -> str:
        chapter_text = history[-1].stitched_text if history else ""
        prompt = "\n".join(
            [
                "Run a coherence audit over the latest chapter against the seed.",
                "Report major canon violations and unresolved severe inconsistencies.",
                "Seed:",
                seed,
                "Latest chapter:",
                chapter_text,
            ]
        )
        return _invoke_model_text(
            assistant,
            system_rules=rules.editor.text,
            prompt=prompt,
        )

    def _push_soft_memory(chapter: ChapterRunArtifact) -> None:
        """Explicitly push chapter flavor/atmosphere into long-term memory."""

        update = chapter.state_update if isinstance(chapter.state_update, dict) else {}
        chapter_text = str(update.get("chapter_text", chapter.stitched_text)).strip()
        if not chapter_text:
            return

        memory_manager.add_memory(
            text=chapter_text,
            metadata={
                "type": "flavor",
                "chapter": chapter.chapter_number,
                "category": "narrative_turn",
            },
        )

    def _check_severe_canon_violation(update: dict[str, Any]) -> bool:
        """Run an inquisitor pass for severe canon contradictions before commit."""

        chapter_text = str(update.get("chapter_text", "")).strip()
        snapshot = update.get("snapshot")
        if not chapter_text or snapshot is None:
            return False

        # Fast deterministic guards before LLM call.
        for character in getattr(snapshot, "characters", {}).values():
            if (
                character.status == "dead"
                and character.name.lower() in chapter_text.lower()
            ):
                return True

        thread_lines: list[str] = []
        for thread in getattr(snapshot, "plot_threads", []):
            thread_lines.append(
                f"- {thread.id}: status={thread.status}, introduced={thread.introduced_chapter}, resolved={thread.resolved_chapter}"
            )
        canon_summary = "\n".join(thread_lines[:12]) or "- none"

        prompt = "\n".join(
            [
                "You are a canon safety checker.",
                'Return strict JSON only: {"violation": true|false, "reason": "..."}.',
                "Set violation=true only for severe contradictions (dead/alive, impossible thread state, timeline break).",
                "Canon facts:",
                canon_summary,
                "Scene text:",
                chapter_text,
            ]
        )

        try:
            raw = _invoke_model_text(
                assistant,
                system_rules=rules.editor.text,
                prompt=prompt,
            )
            payload = json.loads(_extract_json_object(raw))
            return _safe_bool(payload.get("violation", False))
        except Exception:
            # Fail-open for checker parse errors to avoid deadlocking chapter progression.
            return False

    engine = BookEngine(
        build_outline=_build_outline,
        build_scene_plan=_build_scene_plan,
        draft_scene=_draft_scene,
        edit_scene=_edit_scene,
        stitch_chapter=_stitch_chapter,
        derive_state_update=_derive_state_update,
        commit_state_update=_commit_state_update,
        push_soft_memory=_push_soft_memory,
        retry_draft_scene=_retry_draft,
        check_severe_canon_violation=_check_severe_canon_violation,
        run_coherence_review=_coherence_review,
    )

    status = engine.start(seed_markdown=seed_text, target_chapters=chapters)
    coherence_reviews_run = 0
    patch_operations_applied = 0

    while status.stage != BookEngineStage.COMPLETE:
        if status.stage == BookEngineStage.OUTLINE_REVIEW:
            assert status.pending_outline is not None
            console.print(
                f"[bold cyan]Chapter {status.current_chapter} Outline (pending approval)[/bold cyan]"
            )
            console.print(status.pending_outline)
            approved = auto_approve or click.confirm(
                "Approve this outline?",
                default=True,
            )
            status = engine.approve_outline(approved=approved)
            continue

        if status.stage == BookEngineStage.STATE_REVIEW:
            pending = status.pending_chapter
            assert pending is not None
            update = pending.state_update
            patch = update.get("patch")
            operation_count = len(getattr(patch, "operations", []))
            patch_operations_applied += operation_count

            console.print(
                f"[bold cyan]Chapter {pending.chapter_number} Draft Ready (pending state commit)[/bold cyan]"
            )
            console.print(f"Patch operations: {operation_count}")
            if pending.coherence_review:
                coherence_reviews_run += 1
                console.print("[yellow]Coherence gate report:[/yellow]")
                console.print(pending.coherence_review)

            approved = auto_approve or click.confirm(
                "Approve state commit and persist chapter?",
                default=True,
            )
            status = engine.approve_state_commit(approved=approved)
            continue

        raise BookEngineError(f"Unexpected engine stage: {status.stage}")

    return BookRunSummary(
        chapters_generated=len(engine.history),
        coherence_reviews_run=coherence_reviews_run,
        patch_operations_applied=patch_operations_applied,
    )


def _resolve_seed_path(book_path: str, seed_path: str) -> Path:
    """Resolve seed path relative to the project root when needed."""

    raw = Path(seed_path).expanduser()
    if raw.is_absolute():
        return raw
    return (Path(book_path) / raw).resolve()


@click.command(name="book")
@click.option(
    "--book-path",
    type=click.Path(),
    required=False,
    help="Path to the book directory.",
)
@click.option(
    "--seed",
    "seed_path",
    type=str,
    required=True,
    help="Path to seed markdown file (absolute or relative to --book-path).",
)
@click.option(
    "--chapters",
    type=click.IntRange(1, 20),
    default=3,
    show_default=True,
    help="Number of chapters to generate in this run.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Auto-approve outline and state-commit checkpoints.",
)
def book(book_path: str | None, seed_path: str, chapters: int, yes: bool) -> None:
    """Generate a multi-chapter draft from a pinned seed markdown file."""

    resolved_book_path = book_path or os.getcwd()
    if not load_book_config(resolved_book_path):
        return

    resolved_seed = _resolve_seed_path(resolved_book_path, seed_path)
    if not resolved_seed.exists() or not resolved_seed.is_file():
        raise click.ClickException(f"Seed file not found: {resolved_seed}")

    try:
        seed_text = resolved_seed.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise click.ClickException(f"Unable to read seed file: {exc}") from exc

    if not seed_text:
        raise click.ClickException(f"Seed file is empty: {resolved_seed}")

    try:
        summary = run_book_pipeline(
            book_path=str(Path(resolved_book_path).resolve()),
            seed_text=seed_text,
            chapters=chapters,
            auto_approve=yes,
        )
    except BookEngineError as exc:
        click.secho(f"Pipeline Halted: {exc}", fg="red", bold=True)
        raise SystemExit(1) from exc
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        click.secho(f"Critical System Failure: {exc}", fg="white", bg="red")
        raise SystemExit(2) from exc

    console.print("[green]Book generation run complete.[/green]")
    console.print(f"Chapters generated: {summary.chapters_generated}")
    console.print(f"Patch operations applied: {summary.patch_operations_applied}")
    console.print(f"Coherence reviews run: {summary.coherence_reviews_run}")
