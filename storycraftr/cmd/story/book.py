from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

import click
from rich.console import Console
import yaml

from storycraftr.agent.agents import create_or_get_assistant
from storycraftr.agent.book_engine import (
    BookEngine,
    BookEngineError,
    BookEngineStage,
    ChapterRunArtifact,
)
from storycraftr.agent.generation_pipeline import SceneGenerationPipeline
from storycraftr.agent.memory_manager import NarrativeMemoryManager
from storycraftr.agent.narrative_state import (
    NarrativeStateStore,
    SceneDirective,
    StateValidationError,
)
from storycraftr.agent.state_extractor import extract_state_patch
from storycraftr.llm.factory import (
    LLMSettings,
    build_chat_model,
    validate_openrouter_rankings_config,
)
from storycraftr.prompts.craft_rules import load_craft_rule_set
from storycraftr.tui.canon import load_canon, save_canon
from storycraftr.utils.core import load_book_config, llm_settings_from_config
from storycraftr.utils.paths import resolve_project_paths

console = Console()
_VALIDATOR_REPORT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "validator_report.schema.json"
)


@dataclass(frozen=True)
class BookRunSummary:
    """Execution summary returned by the `book` command pipeline."""

    chapters_generated: int
    coherence_reviews_run: int
    patch_operations_applied: int


_SCENE_DIRECTIVE_KEYS = ("goal", "conflict", "stakes", "outcome")


def _utc_now_iso() -> str:
    """Return stable UTC timestamp string for audit artifacts."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_strict_provider(provider_name: str) -> bool:
    """Determine whether provider should run strict fail-closed validation mode."""

    return provider_name in {"openai", "openrouter", "ollama"}


def _model_family(model_id: str) -> str:
    """Return normalized model-family prefix for consensus routing decisions."""

    cleaned = str(model_id).strip().lower()
    if not cleaned:
        return ""
    if "/" in cleaned:
        return cleaned.split("/", 1)[0]
    return cleaned.split(":", 1)[0]


def _prefer_independent_fallback(
    models: tuple[str, ...],
    *,
    reference_family: str,
) -> tuple[str, ...]:
    """Prefer fallback model from a different family when available."""

    if not models or not reference_family:
        return models

    # The first model is the role primary; fallback candidates come after it.
    for candidate in models[1:]:
        if _model_family(candidate) != reference_family:
            return (candidate, *[model for model in models if model != candidate])
    return models


def _validate_scene_directive_payload(
    payload: dict[str, Any],
    *,
    min_words: int,
) -> None:
    """Fail closed when planner JSON shape/content is not directive-contract safe."""

    required = set(_SCENE_DIRECTIVE_KEYS)
    provided = set(payload.keys())
    missing = sorted(required - provided)
    extras = sorted(provided - required)
    if missing or extras:
        raise BookEngineError(
            "Planner directive JSON shape invalid: "
            f"missing={missing or []}, extras={extras or []}"
        )

    minimum = max(1, min_words)
    for field_name in _SCENE_DIRECTIVE_KEYS:
        value = str(payload.get(field_name, "")).strip()
        if not value:
            raise BookEngineError(f"Planner directive field '{field_name}' is empty")
        if _word_count(value) < minimum:
            raise BookEngineError(
                f"Planner directive field below minimum content threshold: {field_name}"
            )


def _render_book_audit_markdown(payload: dict[str, Any]) -> str:
    """Render a concise markdown audit report from run-level JSON payload."""

    lines = [
        "# Book Run Audit",
        "",
        f"- run_id: `{payload.get('run_id', '')}`",
        f"- status: `{payload.get('status', '')}`",
        f"- provider: `{payload.get('provider', '')}`",
        f"- strict_autonomous: `{payload.get('strict_autonomous', False)}`",
        f"- started_at: `{payload.get('started_at', '')}`",
        f"- finished_at: `{payload.get('finished_at', '')}`",
        f"- chapters_target: `{payload.get('chapters_target', 0)}`",
        f"- chapters_generated: `{payload.get('chapters_generated', 0)}`",
        f"- coherence_reviews_run: `{payload.get('coherence_reviews_run', 0)}`",
        f"- patch_operations_applied: `{payload.get('patch_operations_applied', 0)}`",
    ]

    error_message = str(payload.get("error", "")).strip()
    if error_message:
        lines.extend(["", "## Failure", "", f"`{error_message}`"])

    chapters = payload.get("chapters", [])
    if isinstance(chapters, list) and chapters:
        lines.extend(["", "## Chapter Diagnostics", ""])
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            chapter_number = int(chapter.get("chapter", 0))
            lines.append(f"### Chapter {chapter_number}")
            lines.append("")
            lines.append(
                f"- packet: `{str(chapter.get('packet_dir', '')).strip() or 'n/a'}`"
            )
            lines.append(
                f"- acceptance_all_passed: `{bool(chapter.get('acceptance_all_passed', False))}`"
            )
            lines.append(
                f"- stage_contract_all_passed: `{bool(chapter.get('stage_contract_all_passed', False))}`"
            )
            lines.append(
                f"- semantic_review_passed: `{chapter.get('semantic_review_passed', None)}`"
            )
            lines.append(
                f"- coherence_gate_passed: `{chapter.get('coherence_gate_passed', None)}`"
            )
            lines.append(
                f"- severe_canon_violation: `{bool(chapter.get('severe_canon_violation', False))}`"
            )
            lines.append(
                f"- retry_reason: `{str(chapter.get('retry_reason', '')).strip() or 'none'}`"
            )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_book_audit(
    *,
    book_path: str,
    config: Any,
    payload: dict[str, Any],
) -> None:
    """Persist run-level audit summaries for deterministic post-run review."""

    path_config = config if getattr(config, "book_path", None) else None
    project_paths = resolve_project_paths(book_path, config=path_config)
    outline_dir = project_paths.root / "outline"
    outline_dir.mkdir(parents=True, exist_ok=True)

    json_path = outline_dir / "book_audit.json"
    md_path = outline_dir / "book_audit.md"
    json_path.write_text(
        json.dumps(_jsonable(payload), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_book_audit_markdown(payload), encoding="utf-8")


def _load_validator_report_schema() -> dict[str, Any]:
    """Load validator report schema for fail-closed packet validation."""

    try:
        raw = _VALIDATOR_REPORT_SCHEMA_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        raise BookEngineError(
            "Validator report schema is missing or invalid at "
            f"{_VALIDATOR_REPORT_SCHEMA_PATH}"
        ) from exc

    if not isinstance(data, dict):
        raise BookEngineError("Validator report schema must be a JSON object")
    return data


def _validate_validator_report_payload(payload: dict[str, Any]) -> None:
    """Validate validator report payload with full JSON Schema semantics."""

    schema = _load_validator_report_schema()
    try:
        import jsonschema
    except Exception as exc:  # pragma: no cover - dependency guard
        raise BookEngineError(
            "Validator report schema validation failed: jsonschema dependency is unavailable"
        ) from exc

    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        raise BookEngineError(
            f"Validator report schema validation failed: {exc.message}"
        ) from exc
    except jsonschema.SchemaError as exc:
        raise BookEngineError(
            f"Validator report schema is invalid: {exc.message}"
        ) from exc


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


def _invoke_llm_text(
    llm: Any,
    *,
    system_rules: str,
    prompt: str,
) -> str:
    """Invoke the configured model and return normalized text output."""

    composed = f"{system_rules.strip()}\n\n{prompt.strip()}" if system_rules else prompt
    try:
        response = llm.invoke(composed)
    except Exception as exc:
        raise BookEngineError(f"Model invocation failed: {exc}") from exc

    text = _normalize_model_output(response)
    if not text:
        raise BookEngineError("Model invocation returned empty text")
    return text


def _invoke_model_text(
    assistant: Any,
    *,
    system_rules: str,
    prompt: str,
) -> str:
    """Invoke the assistant model and normalize text output."""

    return _invoke_llm_text(
        assistant.llm,
        system_rules=system_rules,
        prompt=prompt,
    )


def _load_reviewer_rules() -> str:
    """Load static semantic reviewer guardrails."""

    reviewer_path = (
        Path(__file__).resolve().parents[2] / "prompts" / "reviewer_rules.md"
    )
    try:
        content = reviewer_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BookEngineError(
            f"Failed to load semantic reviewer rules: {reviewer_path}"
        ) from exc

    if not content:
        raise BookEngineError("Semantic reviewer rules are empty")
    return content


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
    events: list[Any] | None = None,
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

    # Persist extraction events as canon-facing breadcrumbs for auditability.
    for index, event in enumerate(events or [], start=1):
        event_kind = str(getattr(event, "kind", "")).strip()
        event_character = str(getattr(event, "character_id", "")).strip()
        event_details = str(getattr(event, "details", "")).strip()
        if not (event_kind and event_character and event_details):
            continue

        event_fact_id = f"book-event-{chapter_number:03d}-{index:03d}"
        event_fact = {
            "id": event_fact_id,
            "text": (
                "state_event: "
                f"kind={event_kind}; character={event_character}; {event_details}"
            ),
            "type": "state_event",
            "source": "accepted",
        }

        replaced = False
        for row_index, row in enumerate(facts):
            if (
                isinstance(row, dict)
                and str(row.get("id", "")).strip() == event_fact_id
            ):
                facts[row_index] = event_fact
                replaced = True
                break
        if not replaced:
            facts.append(event_fact)

    save_canon(book_path, data)


def _jsonable(value: Any) -> Any:
    """Convert nested runtime values into JSON/YAML-serializable data."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def _chapter_packet_dir(book_path: str, config: Any, chapter_number: int) -> Path:
    """Resolve the deterministic on-disk packet directory for one chapter."""

    path_config = config if getattr(config, "book_path", None) else None
    project_paths = resolve_project_paths(book_path, config=path_config)
    packets_root = project_paths.root / "outline" / "chapter_packets"
    return packets_root / f"chapter-{chapter_number:03d}"


def _word_count(text: str) -> int:
    """Count words in plain text using whitespace tokenization."""

    return len(str(text).split())


def _trim_text(text: str, *, max_chars: int) -> str:
    """Trim long text payloads deterministically for prompt sections."""

    cleaned = str(text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 3:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 3].rstrip() + "..."


def _chapter_history_summary(
    history: tuple[ChapterRunArtifact, ...], *, max_items: int = 4
) -> str:
    """Build compact chapter-history summary for continuity-aware prompts."""

    if not history:
        return "(none)"

    lines: list[str] = []
    for item in history[-max_items:]:
        excerpt = _trim_text(item.stitched_text, max_chars=450)
        lines.append(f"- Chapter {item.chapter_number}: {excerpt}")
    return "\n".join(lines)


def _full_chapter_history_block(history: tuple[ChapterRunArtifact, ...]) -> str:
    """Render full stitched chapter history in chapter order."""

    if not history:
        return "(none)"

    blocks: list[str] = []
    for chapter in history:
        blocks.append(
            "\n".join(
                [
                    f"[Chapter {chapter.chapter_number}]",
                    chapter.stitched_text.strip(),
                ]
            )
        )
    return "\n\n".join(blocks)


def _build_scene_acceptance_contract(
    *,
    chapter: ChapterRunArtifact,
    min_scene_words: int,
) -> dict[str, Any]:
    """Construct scene-level acceptance checks for deterministic handoff validation."""

    enforce_scene_length = min_scene_words > 0
    scene_reports: list[dict[str, Any]] = []
    failed_scenes: list[int] = []

    for scene in chapter.scene_artifacts:
        draft_text = scene.draft_text.strip()
        edited_text = scene.edited_text.strip()
        directive = scene.directive

        checks = {
            "directive_fields_present": all(
                bool(str(getattr(directive, field_name, "")).strip())
                for field_name in ("goal", "conflict", "stakes", "outcome")
            ),
            "draft_non_empty": bool(draft_text),
            "edit_non_empty": bool(edited_text),
            "edit_not_truncated": not edited_text.endswith("..."),
            "edit_min_words": (
                _word_count(edited_text) >= min_scene_words
                if enforce_scene_length
                else True
            ),
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        report = {
            "chapter": chapter.chapter_number,
            "scene_number": scene.scene_number,
            "checks": checks,
            "failed_checks": failed_checks,
            "all_passed": not failed_checks,
        }
        if failed_checks:
            failed_scenes.append(scene.scene_number)
        scene_reports.append(report)

    return {
        "chapter": chapter.chapter_number,
        "scenes": scene_reports,
        "failed_scenes": failed_scenes,
        "all_passed": not failed_scenes,
    }


def _build_stage_validator_contract(
    *,
    chapter: ChapterRunArtifact,
    diagnostics: dict[str, Any],
    patch_operation_count: int,
    min_scene_words: int,
    min_chapter_words: int,
    scene_acceptance: dict[str, Any],
) -> dict[str, Any]:
    """Build explicit stage-by-stage validation metadata for packet handoff."""

    enforce_scene_words = min_scene_words > 0
    enforce_chapter_words = min_chapter_words > 0
    state_enforced = bool(diagnostics.get("state_signal_enforced", False))
    semantic_enabled = bool(diagnostics.get("semantic_review_enabled", False))

    outline_checks = {
        "outline_non_empty": bool(chapter.outline_text.strip()),
    }

    scene_plan_reports = scene_acceptance.get("scenes", [])
    scene_plan_checks = {
        "scene_count_valid": 3 <= len(chapter.scene_artifacts) <= 5,
        "directive_fields_present": all(
            bool(report.get("checks", {}).get("directive_fields_present", False))
            for report in scene_plan_reports
        ),
    }

    draft_reports: list[dict[str, Any]] = []
    edit_reports: list[dict[str, Any]] = []
    for scene in chapter.scene_artifacts:
        draft_text = scene.draft_text.strip()
        edited_text = scene.edited_text.strip()
        draft_checks = {
            "draft_non_empty": bool(draft_text),
            "draft_min_words": (
                _word_count(draft_text) >= min_scene_words
                if enforce_scene_words
                else True
            ),
        }
        edit_checks = {
            "edit_non_empty": bool(edited_text),
            "edit_not_truncated": not edited_text.endswith("..."),
            "edit_min_words": (
                _word_count(edited_text) >= min_scene_words
                if enforce_scene_words
                else True
            ),
        }
        draft_reports.append(
            {
                "scene_number": scene.scene_number,
                "checks": draft_checks,
                "all_passed": all(draft_checks.values()),
            }
        )
        edit_reports.append(
            {
                "scene_number": scene.scene_number,
                "checks": edit_checks,
                "all_passed": all(edit_checks.values()),
            }
        )

    stitched_text = chapter.stitched_text.strip()
    stitch_checks = {
        "stitched_non_empty": bool(stitched_text),
        "stitched_not_truncated": not stitched_text.endswith("..."),
        "stitched_min_words": (
            _word_count(stitched_text) >= min_chapter_words
            if enforce_chapter_words
            else True
        ),
    }

    state_checks = {
        "state_update_present": chapter.state_update is not None,
        "state_signal": (
            bool(diagnostics.get("state_signal_meaningful", False))
            if state_enforced
            else True
        ),
        "state_patch_non_empty": (
            patch_operation_count > 0 if state_enforced else True
        ),
    }

    semantic_checks = {
        "semantic_enabled": semantic_enabled,
        "semantic_passed": (
            bool(diagnostics.get("semantic_review_passed", False))
            if semantic_enabled
            else True
        ),
    }

    stages = {
        "outline": {
            "checks": outline_checks,
            "all_passed": all(outline_checks.values()),
        },
        "scene_plan": {
            "checks": scene_plan_checks,
            "all_passed": all(scene_plan_checks.values()),
        },
        "scene_draft": {
            "scenes": draft_reports,
            "all_passed": all(report["all_passed"] for report in draft_reports),
        },
        "scene_edit": {
            "scenes": edit_reports,
            "all_passed": all(report["all_passed"] for report in edit_reports),
        },
        "stitch": {
            "checks": stitch_checks,
            "all_passed": all(stitch_checks.values()),
        },
        "state_extract": {
            "checks": state_checks,
            "all_passed": all(state_checks.values()),
        },
        "semantic_review": {
            "checks": semantic_checks,
            "all_passed": (
                bool(semantic_checks["semantic_passed"]) if semantic_enabled else True
            ),
        },
    }

    return {
        "chapter": chapter.chapter_number,
        "stages": stages,
        "all_passed": all(stage["all_passed"] for stage in stages.values()),
    }


def _build_acceptance_contract(
    *,
    chapter_number: int,
    diagnostics: dict[str, Any],
    patch_operation_count: int,
    scene_acceptance_ok: bool,
) -> dict[str, Any]:
    """Construct strict pre-commit acceptance requirements for chapter advancement."""

    directive_ok = bool(diagnostics.get("directive_quality_passed", False))
    semantic_enabled = bool(diagnostics.get("semantic_review_enabled", False))
    semantic_ok = (
        bool(diagnostics.get("semantic_review_passed", False))
        if semantic_enabled
        else True
    )

    state_enforced = bool(diagnostics.get("state_signal_enforced", False))
    state_meaningful = bool(diagnostics.get("state_signal_meaningful", False))
    state_ok = state_meaningful if state_enforced else True

    chapter_validation_attempts = int(diagnostics.get("chapter_validation_attempts", 1))
    retries_ok = chapter_validation_attempts >= 1
    patch_ok = patch_operation_count > 0 if state_enforced else True

    checks = {
        "scene_contract": scene_acceptance_ok,
        "planner_quality": directive_ok,
        "chapter_completeness": retries_ok,
        "semantic_review": semantic_ok,
        "state_signal": state_ok,
        "state_patch_non_empty": patch_ok,
    }

    failed = [name for name, passed in checks.items() if not passed]
    return {
        "chapter": chapter_number,
        "checks": checks,
        "failed_checks": failed,
        "all_passed": not failed,
    }


def _write_precommit_packet(
    *,
    book_path: str,
    config: Any,
    chapter: ChapterRunArtifact,
    diagnostics: dict[str, Any],
    acceptance: dict[str, Any],
    scene_acceptance: dict[str, Any],
    stage_contract: dict[str, Any],
) -> Path:
    """Persist a deterministic chapter packet for validator handoff before commit."""

    packet_dir = _chapter_packet_dir(book_path, config, chapter.chapter_number)
    packet_dir.mkdir(parents=True, exist_ok=True)

    (packet_dir / "outline_context.md").write_text(
        chapter.outline_text.strip() + "\n",
        encoding="utf-8",
    )

    scene_plan = [
        {
            "scene_number": scene.scene_number,
            "directive": {
                "goal": scene.directive.goal,
                "conflict": scene.directive.conflict,
                "stakes": scene.directive.stakes,
                "outcome": scene.directive.outcome,
            },
        }
        for scene in chapter.scene_artifacts
    ]
    (packet_dir / "scene_plan.json").write_text(
        json.dumps(scene_plan, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    for scene in chapter.scene_artifacts:
        (packet_dir / f"scene_{scene.scene_number}_draft.md").write_text(
            scene.draft_text.strip() + "\n",
            encoding="utf-8",
        )
        (packet_dir / f"scene_{scene.scene_number}_edit.md").write_text(
            scene.edited_text.strip() + "\n",
            encoding="utf-8",
        )

    for scene_report in scene_acceptance.get("scenes", []):
        scene_number = int(scene_report.get("scene_number", 0))
        if scene_number <= 0:
            continue
        (packet_dir / f"scene_{scene_number}_validator_report.json").write_text(
            json.dumps(_jsonable(scene_report), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    (packet_dir / "stitched_chapter.md").write_text(
        chapter.stitched_text.strip() + "\n",
        encoding="utf-8",
    )

    update = chapter.state_update if isinstance(chapter.state_update, dict) else {}
    patch = update.get("patch")
    patch_payload = _jsonable(getattr(patch, "operations", []))
    (packet_dir / "state_patch.json").write_text(
        json.dumps(
            {
                "chapter": chapter.chapter_number,
                "operations": patch_payload,
                "events": _jsonable(update.get("events", [])),
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    precommit_canon = load_canon(book_path)
    (packet_dir / "canon_delta.yml").write_text(
        yaml.safe_dump(
            {
                "chapter": chapter.chapter_number,
                "status": "precommit",
                "canon_snapshot": _jsonable(precommit_canon),
            },
            sort_keys=False,
            allow_unicode=False,
        ),
        encoding="utf-8",
    )

    (packet_dir / "diagnostics.json").write_text(
        json.dumps(_jsonable(diagnostics), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    validator_report_payload = {
        "phase": "precommit",
        "chapter": chapter.chapter_number,
        "acceptance": acceptance,
        "scene_acceptance": scene_acceptance,
        "stage_contract": stage_contract,
        "semantic_reason": diagnostics.get("semantic_review_last_reason"),
        "retry_reason": diagnostics.get("chapter_validation_last_retry_reason"),
    }
    _validate_validator_report_payload(validator_report_payload)
    (packet_dir / "validator_report.json").write_text(
        json.dumps(validator_report_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    return packet_dir


def _finalize_packet_after_commit(
    *,
    book_path: str,
    config: Any,
    chapter_number: int,
    packet_dir: Path,
) -> None:
    """Persist commit-time validator status after successful chapter commit."""

    path_config = config if getattr(config, "book_path", None) else None
    project_paths = resolve_project_paths(book_path, config=path_config)
    chapter_file = project_paths.root / "chapters" / f"chapter-{chapter_number}.md"
    state_file = project_paths.root / "outline" / "narrative_state.json"
    canon_file = project_paths.root / "outline" / "canon.yml"

    precommit_report: dict[str, Any] = {}
    precommit_path = packet_dir / "validator_report.json"
    if precommit_path.exists():
        try:
            precommit_report = json.loads(precommit_path.read_text(encoding="utf-8"))
        except Exception:
            precommit_report = {}

    report = {
        "phase": "postcommit",
        "chapter": chapter_number,
        "precommit": precommit_report,
        "commit_status": {
            "chapter_file_written": chapter_file.exists(),
            "state_file_written": state_file.exists(),
            "canon_file_written": canon_file.exists(),
        },
    }
    report["commit_status"]["all_persisted"] = all(report["commit_status"].values())
    _validate_validator_report_payload(report)

    (packet_dir / "validator_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    committed_canon = load_canon(book_path)
    (packet_dir / "canon_delta.yml").write_text(
        yaml.safe_dump(
            {
                "chapter": chapter_number,
                "status": "committed",
                "canon_snapshot": _jsonable(committed_canon),
            },
            sort_keys=False,
            allow_unicode=False,
        ),
        encoding="utf-8",
    )


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

    provider_name = ""
    if runtime_config is not None and hasattr(runtime_config, "llm_provider"):
        provider_name = str(runtime_config.llm_provider).strip().lower()
    strict_provider = _is_strict_provider(provider_name)
    strict_autonomous = bool(auto_approve and strict_provider)
    strict_coherence_guard = strict_provider
    enforce_completeness_guard = strict_provider

    if strict_autonomous and runtime_config is None:
        raise BookEngineError(
            "Autonomous strict mode requires a valid project configuration"
        )

    min_scene_words = 250 if enforce_completeness_guard else 0
    min_chapter_words = 750 if enforce_completeness_guard else 0
    min_directive_words = 2 if enforce_completeness_guard else 1
    configured_semantic_review = bool(
        getattr(runtime_config, "enable_semantic_review", False)
    )
    if strict_provider and not configured_semantic_review:
        raise BookEngineError(
            "Real-provider book runs require semantic review enabled in project config"
        )
    # Keep runtime semantic gate enabled for all real-provider runs.
    enable_semantic_review = configured_semantic_review or strict_provider

    rankings: dict[str, Any] = {}
    role_model_specs: dict[str, tuple[str, ...]] = {}
    role_models: dict[str, tuple[Any, ...]] = {}
    role_model_indices: dict[str, int] = {}
    base_settings: LLMSettings | None = None
    if runtime_config is not None and hasattr(runtime_config, "llm_provider"):
        base_settings = llm_settings_from_config(runtime_config)
    if provider_name == "openrouter" and runtime_config is not None:
        rankings = validate_openrouter_rankings_config()

        def _build_role_model_spec(role: str) -> tuple[str, ...]:
            role_cfg = rankings.get(role)
            if not isinstance(role_cfg, dict):
                return tuple()
            model_ids: list[str] = []
            primary = str(role_cfg.get("primary", "")).strip()
            if primary:
                model_ids.append(primary)
            for fallback in role_cfg.get("fallbacks", []):
                candidate = str(fallback).strip()
                if candidate and candidate not in model_ids:
                    model_ids.append(candidate)
            return tuple(model_ids)

        role_model_specs["batch_planning"] = _build_role_model_spec("batch_planning")
        role_model_specs["batch_prose"] = _build_role_model_spec("batch_prose")
        role_model_specs["batch_editing"] = _build_role_model_spec("batch_editing")
        role_model_specs["repair_json"] = _build_role_model_spec("repair_json")
        role_model_specs["coherence_check"] = _build_role_model_spec("coherence_check")

        drafter_models = role_model_specs.get("batch_prose", tuple())
        drafter_family = _model_family(drafter_models[0]) if drafter_models else ""
        role_model_specs["coherence_check"] = _prefer_independent_fallback(
            role_model_specs.get("coherence_check", tuple()),
            reference_family=drafter_family,
        )

    semantic_reviewer_llm: Any | None = None
    reviewer_rules = ""
    if enable_semantic_review:
        reviewer_rules = _load_reviewer_rules()
        if runtime_config is None:
            raise BookEngineError(
                "Semantic review requires a loaded project configuration"
            )

        reviewer_models = role_model_specs.get("coherence_check", tuple())
        if reviewer_models and base_settings is not None:
            try:
                reviewer_settings = LLMSettings(
                    provider=base_settings.provider,
                    model=reviewer_models[0],
                    endpoint=base_settings.endpoint,
                    api_key_env=base_settings.api_key_env,
                    temperature=0.0,
                    request_timeout=base_settings.request_timeout,
                    max_tokens=base_settings.max_tokens,
                )
                semantic_reviewer_llm = build_chat_model(reviewer_settings)
            except Exception:
                semantic_reviewer_llm = None
        if semantic_reviewer_llm is None:
            reviewer_settings = llm_settings_from_config(runtime_config)
            semantic_reviewer_llm = build_chat_model(reviewer_settings)

    assistant = create_or_get_assistant(book_path)
    state_store = NarrativeStateStore(book_path)
    memory_manager = NarrativeMemoryManager(book_path=book_path, config=runtime_config)
    rules = load_craft_rule_set()
    pipeline = SceneGenerationPipeline(
        planner_rules=rules.planner.text,
        drafter_rules=rules.drafter.text,
        editor_rules=rules.editor.text,
    )

    def _invoke_role_text(
        role: str,
        *,
        system_rules: str,
        prompt: str,
        fallback_llm: Any | None = None,
    ) -> str:
        if role not in role_models:
            model_ids = role_model_specs.get(role, tuple())
            clients: list[Any] = []
            if model_ids and base_settings is not None:
                role_temperature = {
                    "batch_planning": 0.0,
                    "batch_prose": 0.7,
                    "batch_editing": 0.3,
                    "repair_json": 0.0,
                    "coherence_check": 0.0,
                }.get(role, base_settings.temperature)
                for model_id in model_ids:
                    try:
                        role_settings = LLMSettings(
                            provider=base_settings.provider,
                            model=model_id,
                            endpoint=base_settings.endpoint,
                            api_key_env=base_settings.api_key_env,
                            temperature=role_temperature,
                            request_timeout=base_settings.request_timeout,
                            max_tokens=base_settings.max_tokens,
                        )
                        clients.append(build_chat_model(role_settings))
                    except (
                        Exception
                    ):  # nosec B112 - ranked fallback intentionally skips invalid model configs
                        continue
            role_models[role] = tuple(clients)

        candidates = role_models.get(role, tuple())
        if not candidates:
            llm = fallback_llm if fallback_llm is not None else assistant.llm
            return _invoke_llm_text(llm, system_rules=system_rules, prompt=prompt)

        start_index = role_model_indices.get(role, 0)
        if start_index < 0 or start_index >= len(candidates):
            start_index = 0
            role_model_indices[role] = 0

        ordered_candidates = list(enumerate(candidates))
        if start_index > 0:
            ordered_candidates = (
                ordered_candidates[start_index:] + ordered_candidates[:start_index]
            )

        errors: list[str] = []
        for candidate_index, llm in ordered_candidates:
            try:
                role_model_indices[role] = candidate_index
                return _invoke_llm_text(llm, system_rules=system_rules, prompt=prompt)
            except Exception as exc:
                errors.append(str(exc))

        raise BookEngineError(
            f"All ranked models failed for role '{role}': {errors[-1] if errors else 'unknown error'}"
        )

    def _rotate_role_model(role: str, *, reason: str) -> bool:
        """Rotate active role model to the next ranked candidate."""

        candidates = role_models.get(role, tuple())
        if len(candidates) <= 1:
            return False

        current_index = role_model_indices.get(role, 0)
        if current_index < 0 or current_index >= len(candidates):
            current_index = 0
        next_index = (current_index + 1) % len(candidates)
        if next_index == current_index:
            return False

        role_model_indices[role] = next_index
        model_ids = role_model_specs.get(role, tuple())
        current_model = (
            model_ids[current_index] if current_index < len(model_ids) else "<unknown>"
        )
        next_model = (
            model_ids[next_index] if next_index < len(model_ids) else "<unknown>"
        )
        console.print(
            "[yellow]Model escalation:[/yellow] "
            f"role={role} reason={reason} "
            f"{current_model} -> {next_model}"
        )
        return True

    def _on_scene_generation_retry(
        chapter_number: int,
        scene_number: int,
        attempt: int,
        reason: str,
    ) -> None:
        """Escalate prose/editing models when scene retries indicate quality stasis."""

        del chapter_number, scene_number
        if provider_name != "openrouter":
            return
        if attempt < 2:
            return

        reason_lower = reason.lower()
        if "too_short" in reason_lower or "validation" in reason_lower:
            _rotate_role_model("batch_prose", reason=reason)
            _rotate_role_model("batch_editing", reason=reason)

    def _on_chapter_validation_retry(attempt: int, total: int, reason: str) -> None:
        """Escalate ranked models after repeated chapter-level quality failures."""

        del total
        if provider_name != "openrouter":
            return
        if attempt < 2:
            return

        reason_lower = reason.lower()
        rotated = False
        if any(
            token in reason_lower
            for token in ("too_short", "duplicate", "truncated", "empty_output")
        ):
            rotated = _rotate_role_model("batch_prose", reason=reason) or rotated
            rotated = _rotate_role_model("batch_editing", reason=reason) or rotated
        if "semantic_review" in reason_lower:
            rotated = _rotate_role_model("coherence_check", reason=reason) or rotated

        if not rotated:
            _rotate_role_model("batch_prose", reason=reason)

    def _on_coherence_repair_retry(attempt: int, total: int, reason: str) -> None:
        """Force escalation before coherence repair regeneration attempts."""

        del attempt, total
        if provider_name != "openrouter":
            return
        _rotate_role_model("batch_prose", reason=f"coherence_repair:{reason}")
        _rotate_role_model("batch_editing", reason=f"coherence_repair:{reason}")
        _rotate_role_model("coherence_check", reason=f"coherence_repair:{reason}")

    def _build_grounding_context(
        *,
        chapter_number: int,
        history: tuple[ChapterRunArtifact, ...],
    ) -> str:
        state_block = ""
        if hasattr(state_store, "render_prompt_block"):
            try:
                state_block = state_store.render_prompt_block(max_chars=2400)
            except StateValidationError as exc:
                raise BookEngineError(f"Narrative state load failed: {exc}") from exc
        elif hasattr(state_store, "load"):
            # Compatibility path for lightweight test doubles without render helper.
            try:
                state_snapshot = state_store.load()
                state_block = _trim_text(
                    json.dumps(_jsonable(state_snapshot), ensure_ascii=True),
                    max_chars=1200,
                )
            except Exception:
                state_block = ""

        canon_payload = json.dumps(
            load_canon(book_path), ensure_ascii=True, sort_keys=True
        )
        canon_payload = _trim_text(canon_payload, max_chars=2000)
        history_block = _chapter_history_summary(history)
        state_text = state_block or "[Narrative State]\n(none)"

        return "\n".join(
            [
                f"[Continuity Grounding for Chapter {chapter_number}]",
                state_text,
                "[Canon Facts JSON]",
                canon_payload,
                "[Recent Chapter History]",
                history_block,
            ]
        )

    def _build_outline(
        seed: str,
        chapter_number: int,
        history: tuple[ChapterRunArtifact, ...],
    ) -> str:
        grounding = _build_grounding_context(
            chapter_number=chapter_number,
            history=history,
        )
        prompt = "\n".join(
            [
                "Create a concise rolling outline for the next chapter.",
                f"Target chapter: {chapter_number}",
                "Pinned seed:",
                seed,
                grounding,
                "Return markdown bullets only.",
            ]
        )
        return _invoke_role_text(
            "batch_planning",
            system_rules=rules.planner.text,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )

    def _build_scene_plan(outline: str, chapter_number: int) -> list[SceneDirective]:
        directives: list[SceneDirective] = []
        grounding = _build_grounding_context(
            chapter_number=chapter_number,
            history=engine.history,
        )
        for scene_number in range(1, 4):
            base_prompt = "\n".join(
                [
                    f"Chapter {chapter_number}, scene {scene_number} of 3.",
                    "Use this approved chapter outline:",
                    outline,
                    grounding,
                ]
            )

            parsed_directive: SceneDirective | None = None
            last_error: Exception | None = None
            planner_input = base_prompt
            for attempt_index in range(3):
                planner_prompt = pipeline.build_planner_user_prompt(planner_input)
                planner_role = "batch_planning" if attempt_index == 0 else "repair_json"
                planner_response = _invoke_role_text(
                    planner_role,
                    system_rules=rules.planner.text,
                    prompt=planner_prompt,
                    fallback_llm=assistant.llm,
                )
                try:
                    payload = json.loads(_extract_json_object(planner_response))
                    if not isinstance(payload, dict):
                        raise BookEngineError(
                            "Planner directive payload must be a JSON object"
                        )
                    _validate_scene_directive_payload(
                        payload,
                        min_words=min_directive_words,
                    )
                    parsed_directive = SceneDirective(**payload)
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
                    "Scene planner failed strict directive schema validation"
                ) from last_error

            directives.append(parsed_directive)
        return directives

    def _draft_scene(
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        grounding = _build_grounding_context(
            chapter_number=chapter_number,
            history=engine.history,
        )
        prompt = pipeline.build_drafter_user_prompt(
            user_input=(
                f"Chapter {chapter_number} scene {scene_number}. "
                "Write 800-1200 words and keep continuity tight.\n"
                f"{grounding}"
            ),
            directive=directive,
        )
        drafter_rules = rules.drafter.text
        if repair_directive and repair_in_system_prompt:
            drafter_rules = "\n\n".join(
                [
                    rules.drafter.text,
                    f"CRITICAL CORRECTION:\n{repair_directive.strip()}",
                ]
            )
        return _invoke_role_text(
            "batch_prose",
            system_rules=drafter_rules,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        grounding = _build_grounding_context(
            chapter_number=chapter_number,
            history=engine.history,
        )
        prompt = pipeline.build_editor_user_prompt(
            user_input=(
                f"Revise chapter {chapter_number} scene {scene_number} for craft and canon.\n"
                f"{grounding}"
            ),
            directive=directive,
            draft=draft,
        )
        return _invoke_role_text(
            "batch_editing",
            system_rules=rules.editor.text,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )

    def _retry_draft(
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        repair_directive: str | None = None,
    ) -> str:
        grounding = _build_grounding_context(
            chapter_number=chapter_number,
            history=engine.history,
        )
        repair_block = ""
        if repair_directive:
            repair_block = f"\n{repair_directive.strip()}"
        retry_prompt = pipeline.build_drafter_user_prompt(
            user_input=(
                f"Retry draft for chapter {chapter_number} scene {scene_number}. "
                "Address prior coherence issues and preserve directive fidelity."
                f"{repair_block}\n"
                f"{grounding}"
            ),
            directive=directive,
        )
        return _invoke_role_text(
            "batch_prose",
            system_rules=rules.drafter.text,
            prompt=retry_prompt,
            fallback_llm=assistant.llm,
        )

    def _stitch_chapter(edited_scenes: list[str], chapter_number: int) -> str:
        grounding = _build_grounding_context(
            chapter_number=chapter_number,
            history=engine.history,
        )
        prompt = "\n\n".join(
            [
                (
                    f"Stitch chapter {chapter_number} scene transitions. "
                    "Return a single cohesive chapter preserving all major beats."
                ),
                grounding,
                *[
                    f"[Scene {index}]\n{scene_text}"
                    for index, scene_text in enumerate(edited_scenes, start=1)
                ],
            ]
        )
        return _invoke_role_text(
            "batch_editing",
            system_rules=rules.stitcher.text,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )

    def _derive_state_update(chapter_text: str, chapter_number: int) -> dict[str, Any]:
        try:
            snapshot = state_store.load()
        except StateValidationError as exc:
            raise BookEngineError(f"Narrative state load failed: {exc}") from exc

        def _invoke_extraction_role(prompt: str) -> str:
            return _invoke_role_text(
                "repair_json",
                system_rules=rules.editor.text,
                prompt=prompt,
                fallback_llm=assistant.llm,
            )

        extraction = extract_state_patch(
            chapter_text,
            snapshot=snapshot,
            chapter_number=chapter_number,
            invoke_json_role=_invoke_extraction_role,
        )
        return {
            "chapter_text": chapter_text,
            "chapter_number": chapter_number,
            "patch": extraction.patch,
            "events": extraction.events,
            "snapshot": snapshot,
        }

    def _commit_state_update(update: dict[str, Any], chapter_number: int) -> None:
        path_config = (
            runtime_config if getattr(runtime_config, "book_path", None) else None
        )
        project_paths = resolve_project_paths(book_path, config=path_config)

        state_file = project_paths.root / "outline" / "narrative_state.json"
        canon_file = project_paths.root / "outline" / "canon.yml"
        chapter_file = project_paths.root / "chapters" / f"chapter-{chapter_number}.md"

        state_before_exists = state_file.exists()
        canon_before_exists = canon_file.exists()
        chapter_before_exists = chapter_file.exists()
        state_before = (
            state_file.read_text(encoding="utf-8") if state_before_exists else None
        )
        canon_before = (
            canon_file.read_text(encoding="utf-8") if canon_before_exists else None
        )
        chapter_before = (
            chapter_file.read_text(encoding="utf-8") if chapter_before_exists else None
        )
        wrote_state = False
        wrote_canon = False
        wrote_chapter = False

        def _restore_file(path: Path, content: str | None, existed: bool) -> None:
            if existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content or "", encoding="utf-8")
                return
            if path.exists():
                path.unlink()

        patch = update["patch"]
        try:
            snapshot = state_store.apply_patch(patch, actor="book-engine")
            wrote_state = True
            _persist_canon_ledger(
                book_path=book_path,
                chapter_number=chapter_number,
                snapshot=snapshot,
                events=list(update.get("events", [])),
            )
            wrote_canon = True

            chapter_file.parent.mkdir(parents=True, exist_ok=True)
            chapter_file.write_text(
                str(update["chapter_text"]).strip() + "\n", encoding="utf-8"
            )
            wrote_chapter = True
        except Exception as exc:
            # Roll back all touched commit artifacts to avoid partial persistence.
            try:
                if wrote_chapter or chapter_file.exists():
                    _restore_file(chapter_file, chapter_before, chapter_before_exists)
                if wrote_canon or canon_file.exists():
                    _restore_file(canon_file, canon_before, canon_before_exists)
                if wrote_state or state_file.exists():
                    _restore_file(state_file, state_before, state_before_exists)
            except Exception as rollback_exc:
                raise RuntimeError(
                    "Atomic commit rollback failed after commit error: "
                    f"{rollback_exc}; original error: {exc}"
                ) from rollback_exc
            raise RuntimeError(
                f"Atomic commit failed and was rolled back: {exc}"
            ) from exc

    def _coherence_review(
        seed: str,
        history: tuple[ChapterRunArtifact, ...],
    ) -> tuple[bool, str | None]:
        chapter_number = history[-1].chapter_number if history else 0
        full_history = _full_chapter_history_block(history)
        canon_payload = json.dumps(
            load_canon(book_path), ensure_ascii=True, sort_keys=True
        )
        if hasattr(state_store, "render_prompt_block"):
            try:
                state_block = state_store.render_prompt_block(max_chars=2200)
            except StateValidationError as exc:
                return False, f"coherence_state_load_failed:{exc}"
        elif hasattr(state_store, "load"):
            try:
                snapshot = state_store.load()
                state_block = _trim_text(
                    json.dumps(_jsonable(snapshot), ensure_ascii=True),
                    max_chars=1200,
                )
            except Exception:
                state_block = ""
        else:
            state_block = ""

        prompt = "\n".join(
            [
                "Run a global coherence audit over chapter progression.",
                "Run a coherence audit over the latest chapter against the seed.",
                'Return strict JSON only: {"status":"PASS"} or {"status":"FAIL","reason":"..."}.',
                "Mark FAIL only for severe canon contradictions, impossible timeline shifts,",
                "or continuity regressions that should block commit.",
                f"Target chapter: {chapter_number}",
                "Seed:",
                seed,
                "Narrative State:",
                state_block or "(none)",
                "Canon Facts JSON:",
                canon_payload,
                "All chapter history (full text in order):",
                full_history,
            ]
        )
        try:
            raw = _invoke_role_text(
                "coherence_check",
                system_rules=rules.editor.text,
                prompt=prompt,
                fallback_llm=semantic_reviewer_llm,
            )
            payload = json.loads(_extract_json_object(raw))
            status = str(payload.get("status", "")).strip().upper()
            if status == "PASS":
                return True, str(payload.get("reason", "pass")).strip() or "pass"
            if status == "FAIL":
                reason = str(payload.get("reason", "unspecified_violation")).strip()
                return False, reason or "unspecified_violation"
            return False, f"coherence_invalid_status:{status or 'missing'}"
        except Exception as exc:
            return False, f"coherence_invalid_response:{exc}"

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
        has_dead_character = False
        for character in getattr(snapshot, "characters", {}).values():
            if character.status == "dead":
                has_dead_character = True
            if (
                character.status == "dead"
                and character.name.lower() in chapter_text.lower()
            ):
                return True

        if not has_dead_character and not getattr(snapshot, "plot_threads", []):
            return False

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
                "Seed:",
                seed_text.strip(),
                "Canon facts:",
                canon_summary,
                "Scene text:",
                chapter_text,
            ]
        )

        try:
            raw = _invoke_role_text(
                "coherence_check",
                system_rules=rules.editor.text,
                prompt=prompt,
                fallback_llm=assistant.llm,
            )
            payload = json.loads(_extract_json_object(raw))
            return _safe_bool(payload.get("violation", False))
        except Exception:
            # Fail closed only for real-provider runs; keep fake/offline tests deterministic.
            return strict_coherence_guard

    def _run_semantic_review(
        chapter_text: str,
        chapter_number: int,
        outline_text: str,
    ) -> tuple[bool, str | None]:
        """Run semantic reviewer pass against seed + canon + outline constraints."""

        if semantic_reviewer_llm is None:
            return True, None

        canon_data = load_canon(book_path)
        canon_payload = json.dumps(canon_data, ensure_ascii=True)
        prompt = "\n".join(
            [
                f"Chapter: {chapter_number}",
                "Seed:",
                seed_text.strip(),
                "Approved Scene Plan:",
                outline_text.strip(),
                "Canon Facts JSON:",
                canon_payload,
                "Generated Chapter:",
                chapter_text.strip(),
                "Return JSON only.",
            ]
        )

        try:
            raw = _invoke_llm_text(
                semantic_reviewer_llm,
                system_rules=reviewer_rules,
                prompt=prompt,
            )
            payload = json.loads(_extract_json_object(raw))
        except Exception as exc:
            return False, f"reviewer_invalid_response:{exc}"

        status = str(payload.get("status", "")).strip().upper()
        if status == "PASS":
            return True, None
        if status == "FAIL":
            reason = str(payload.get("reason", "unspecified_violation")).strip()
            return False, reason or "unspecified_violation"
        return False, f"reviewer_invalid_status:{status or 'missing'}"

    def _persist_generation_failure(
        chapter_number: int,
        attempt: int,
        reason: str,
        text: str,
    ) -> None:
        """Persist rejected chapter attempts for post-mortem debugging."""

        packet_dir = _chapter_packet_dir(book_path, runtime_config, chapter_number)
        failures_dir = packet_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        failure_file = failures_dir / f"attempt-{max(1, attempt)}.txt"
        failure_file.write_text(
            (
                f"chapter={chapter_number}\n"
                f"attempt={attempt}\n"
                f"reason={reason}\n\n"
                f"{str(text).strip()}\n"
            ),
            encoding="utf-8",
        )

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
        min_scene_words=min_scene_words,
        min_chapter_words=min_chapter_words,
        min_directive_words=min_directive_words,
        enable_semantic_review=enable_semantic_review,
        run_semantic_review=_run_semantic_review,
        persist_validation_failure=_persist_generation_failure,
        on_scene_generation_retry=_on_scene_generation_retry,
        on_chapter_validation_retry=_on_chapter_validation_retry,
        on_coherence_repair_retry=_on_coherence_repair_retry,
        max_scene_generation_attempts=3,
        # Enforce meaningful state updates for all real-provider runs.
        enforce_state_signal_guard=strict_provider,
        enforce_coherence_each_chapter=strict_autonomous,
        require_severe_canon_check=strict_autonomous,
        coherence_interval=1 if strict_autonomous else 5,
    )

    status = engine.start(seed_markdown=seed_text, target_chapters=chapters)
    coherence_reviews_run = 0
    patch_operations_applied = 0
    chapter_packet_dirs: dict[int, Path] = {}
    run_id = f"book-run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    started_at = _utc_now_iso()
    chapter_audits: list[dict[str, Any]] = []

    run_status = "failed"
    run_error = ""
    failed_guard = "none"

    def _classify_failed_guard(error_text: str) -> str:
        lowered = error_text.lower()
        if "coherence" in lowered:
            return "Coherence"
        if "semantic" in lowered or "reviewer_" in lowered:
            return "Semantic"
        if any(
            token in lowered
            for token in (
                "too_short",
                "below minimum word count",
                "duplicate",
                "truncated",
                "empty_output",
                "acceptance contract",
                "stage validator contract",
            )
        ):
            return "Completeness"
        return "unknown"

    try:
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
                diagnostics = pending.generation_diagnostics or {}
                directive_ok = bool(diagnostics.get("directive_quality_passed", False))
                attempts = int(diagnostics.get("chapter_validation_attempts", 1))
                last_reason = diagnostics.get("chapter_validation_last_retry_reason")
                state_signal = diagnostics.get("state_signal_meaningful")
                state_enforced = bool(diagnostics.get("state_signal_enforced", False))
                semantic_enabled = bool(
                    diagnostics.get("semantic_review_enabled", False)
                )
                semantic_passed = diagnostics.get("semantic_review_passed")
                semantic_reason = diagnostics.get("semantic_review_last_reason")
                state_label = "pass" if state_signal else "fail"
                if not state_enforced:
                    state_label += " (not_enforced)"
                semantic_label = "skip"
                if semantic_enabled:
                    semantic_label = "pass" if semantic_passed else "fail"
                    if semantic_reason:
                        semantic_label += f" ({semantic_reason})"
                retry_label = str(last_reason) if last_reason else "none"
                console.print(
                    "Guard diagnostics: "
                    f"directive_quality={'pass' if directive_ok else 'fail'}, "
                    f"chapter_validation_attempts={attempts}, "
                    f"chapter_validation_last_retry={retry_label}, "
                    f"semantic_review={semantic_label}, "
                    f"state_signal={state_label}"
                )
                if pending.coherence_review:
                    coherence_reviews_run += 1
                    console.print("[yellow]Coherence gate report:[/yellow]")
                    console.print(pending.coherence_review)

                scene_acceptance = _build_scene_acceptance_contract(
                    chapter=pending,
                    min_scene_words=min_scene_words,
                )
                if not scene_acceptance["all_passed"]:
                    failed_scene_numbers = ", ".join(
                        str(number) for number in scene_acceptance["failed_scenes"]
                    )
                    raise BookEngineError(
                        "Scene acceptance contract failed before commit: "
                        f"scenes [{failed_scene_numbers}]"
                    )

                acceptance = _build_acceptance_contract(
                    chapter_number=pending.chapter_number,
                    diagnostics=diagnostics,
                    patch_operation_count=operation_count,
                    scene_acceptance_ok=scene_acceptance["all_passed"],
                )

                if not acceptance["all_passed"]:
                    failed = ", ".join(acceptance["failed_checks"])
                    raise BookEngineError(
                        f"Chapter acceptance contract failed before commit: {failed}"
                    )

                stage_contract = _build_stage_validator_contract(
                    chapter=pending,
                    diagnostics=diagnostics,
                    patch_operation_count=operation_count,
                    min_scene_words=min_scene_words,
                    min_chapter_words=min_chapter_words,
                    scene_acceptance=scene_acceptance,
                )
                if not stage_contract["all_passed"]:
                    raise BookEngineError(
                        "Stage validator contract failed before commit"
                    )

                try:
                    packet_dir = _write_precommit_packet(
                        book_path=book_path,
                        config=runtime_config,
                        chapter=pending,
                        diagnostics=diagnostics,
                        acceptance=acceptance,
                        scene_acceptance=scene_acceptance,
                        stage_contract=stage_contract,
                    )
                except Exception as exc:
                    raise BookEngineError(
                        f"Failed to persist chapter packet before commit: {exc}"
                    ) from exc
                chapter_packet_dirs[pending.chapter_number] = packet_dir
                console.print(f"Stage packet: {packet_dir}")

                approved = auto_approve or click.confirm(
                    "Approve state commit and persist chapter?",
                    default=True,
                )
                status = engine.approve_state_commit(approved=approved)

                packet_dir = chapter_packet_dirs.get(pending.chapter_number)
                if packet_dir is not None:
                    try:
                        _finalize_packet_after_commit(
                            book_path=book_path,
                            config=runtime_config,
                            chapter_number=pending.chapter_number,
                            packet_dir=packet_dir,
                        )
                    except Exception as exc:
                        raise BookEngineError(
                            f"Commit succeeded but packet finalization failed: {exc}"
                        ) from exc

                chapter_audits.append(
                    {
                        "chapter": pending.chapter_number,
                        "packet_dir": str(packet_dir) if packet_dir is not None else "",
                        "acceptance_all_passed": bool(
                            acceptance.get("all_passed", False)
                        ),
                        "stage_contract_all_passed": bool(
                            stage_contract.get("all_passed", False)
                        ),
                        "semantic_review_passed": diagnostics.get(
                            "semantic_review_passed"
                        ),
                        "coherence_gate_required": diagnostics.get(
                            "coherence_gate_required"
                        ),
                        "coherence_gate_passed": diagnostics.get(
                            "coherence_gate_passed"
                        ),
                        "severe_canon_violation": diagnostics.get(
                            "severe_canon_violation"
                        ),
                        "retry_reason": diagnostics.get(
                            "chapter_validation_last_retry_reason"
                        ),
                    }
                )
                continue

            raise BookEngineError(f"Unexpected engine stage: {status.stage}")

        run_status = "succeeded"
        return BookRunSummary(
            chapters_generated=len(engine.history),
            coherence_reviews_run=coherence_reviews_run,
            patch_operations_applied=patch_operations_applied,
        )
    except Exception as exc:
        run_error = str(exc)
        failed_guard = _classify_failed_guard(run_error)
        raise
    finally:
        if run_status != "succeeded":
            console.print(
                "[red]Final guard trip summary:[/red] "
                f"guard={failed_guard}, error={run_error or '<none>'}"
            )
        _write_book_audit(
            book_path=book_path,
            config=runtime_config,
            payload={
                "run_id": run_id,
                "status": run_status,
                "error": run_error,
                "failed_guard": failed_guard,
                "provider": provider_name or "unknown",
                "strict_autonomous": strict_autonomous,
                "started_at": started_at,
                "finished_at": _utc_now_iso(),
                "chapters_target": chapters,
                "chapters_generated": len(engine.history),
                "coherence_reviews_run": coherence_reviews_run,
                "patch_operations_applied": patch_operations_applied,
                "chapters": chapter_audits,
            },
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
    runtime_config = load_book_config(resolved_book_path)
    if not runtime_config:
        return

    provider = str(getattr(runtime_config, "llm_provider", "")).strip().lower()
    semantic_enabled = bool(getattr(runtime_config, "enable_semantic_review", False))
    if provider in {"openai", "openrouter", "ollama"} and not semantic_enabled:
        raise click.ClickException(
            "Real-provider book runs require semantic validation. "
            "Set 'enable_semantic_review' to true in storycraftr.json/papercraftr.json."
        )

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
