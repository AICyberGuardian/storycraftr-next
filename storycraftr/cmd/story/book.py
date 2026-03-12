from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
import sys
from typing import Any, Callable

import click
from rich.console import Console
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
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
    LLMInvocationError,
    LLMSettings,
    build_transport_error_payload,
    build_chat_model,
    validate_openrouter_rankings_config,
    validate_ranking_consensus,
)
from storycraftr.prompts.craft_rules import load_craft_rule_set
from storycraftr.tui.canon import load_canon, save_canon
from storycraftr.utils.core import load_book_config, llm_settings_from_config
from storycraftr.utils.paths import resolve_project_paths

console = Console()
_BOOK_LOGGER = structlog.get_logger("storycraftr.book_command")
_VALIDATOR_REPORT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "validator_report.schema.json"
)


@dataclass(frozen=True)
class BookRunSummary:
    """Execution summary returned by the `book` command pipeline."""

    chapters_generated: int
    coherence_reviews_run: int
    patch_operations_applied: int
    chapters_attempted: int = 0
    retries: int = 0
    escalations: int = 0
    semantic_reviews_run: int = 0
    elapsed_seconds: float = 0.0
    final_status: str = "unknown"


_SCENE_DIRECTIVE_KEYS = ("goal", "conflict", "stakes", "outcome")
_MANDATORY_SEED_CONSTRAINT_MAX_CHARS = 3200
_POV_VERB_TOKENS = frozenset(
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


def _exclude_model_family(
    models: tuple[str, ...],
    *,
    excluded_family: str,
) -> tuple[str, ...]:
    """Remove models belonging to a disallowed family, preserving order."""

    if not models or not excluded_family:
        return models
    filtered = tuple(
        model for model in models if _model_family(model) != excluded_family
    )
    return filtered


def _first_token(text: str) -> str:
    for raw_token in str(text).split():
        token = raw_token.strip(".,:;!?()[]{}\"'")
        if token:
            return token
    return ""


def _is_verb_like_pov(token: str) -> bool:
    lowered = str(token).strip().lower()
    if not lowered:
        return False
    return lowered in _POV_VERB_TOKENS


def _build_mandatory_seed_constraints(seed_markdown: str) -> str:
    """Build high-priority deterministic scene constraints from seed.md."""

    cleaned = _trim_text(
        str(seed_markdown).strip(),
        max_chars=_MANDATORY_SEED_CONSTRAINT_MAX_CHARS,
    )
    if not cleaned:
        return ""
    return "\n".join(
        [
            "MANDATORY SCENE CONSTRAINTS:",
            "These are hard constraints from seed.md and are NOT optional.",
            (
                "You MUST preserve these world rules exactly and reject any draft/edit "
                "direction that contradicts them."
            ),
            cleaned,
        ]
    )


def _compose_stage_system_rules(
    *,
    base_rules: str,
    mandatory_seed_constraints: str,
    repair_directive: str | None = None,
) -> str:
    """Compose deterministic stage rules with seed hard constraints."""

    sections: list[str] = [str(base_rules).strip()]
    if mandatory_seed_constraints.strip():
        sections.append(mandatory_seed_constraints.strip())
    if repair_directive:
        sections.append(f"CRITICAL CORRECTION:\n{repair_directive.strip()}")
    return "\n\n".join(section for section in sections if section).strip()


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
        if field_name == "goal":
            first_goal_token = _first_token(value)
            if _is_verb_like_pov(first_goal_token):
                raise BookEngineError(
                    "Planner directive goal must start with a character name, not "
                    f"a verb-like token: {first_goal_token}"
                )
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
    stage_name: str = "unknown",
) -> str:
    """Invoke the configured model and return normalized text output."""

    composed = f"{system_rules.strip()}\n\n{prompt.strip()}" if system_rules else prompt
    if hasattr(llm, "set_invocation_stage"):
        try:
            llm.set_invocation_stage(stage_name)
        except Exception as exc:
            _BOOK_LOGGER.debug(
                "Non-fatal failure setting LLM invocation stage",
                exc_info=exc,
            )
    try:
        response = llm.invoke(composed)
    except Exception as exc:
        root = exc
        if isinstance(exc, BookEngineError) and exc.__cause__ is not None:
            root = exc.__cause__
        if isinstance(root, LLMInvocationError) and root.transport_error:
            payload = root.transport_error
            raise BookEngineError(
                "Model invocation failed: "
                f"provider={payload.get('provider', 'unknown')} "
                f"effective_model={payload.get('effective_model', '<unknown>')} "
                f"http_status={payload.get('http_status')} "
                f"raw_error_body={payload.get('raw_error_body', '<no-error-body>')}"
            ) from exc
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
    stage_name: str = "unknown",
) -> str:
    """Invoke the assistant model and normalize text output."""

    return _invoke_llm_text(
        assistant.llm,
        system_rules=system_rules,
        prompt=prompt,
        stage_name=stage_name,
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
    """Extract the most likely JSON object payload from model output text.

    Priority: standard bracket extraction → json-repair library (zero-token) → raise.
    """
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidate = stripped[first : last + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Zero-token repair via library before calling the LLM repair role.
    try:
        from json_repair import repair_json  # type: ignore[import-untyped]

        repaired = str(repair_json(text, return_objects=False))
        if repaired.strip().startswith("{"):
            json.loads(repaired)
            return repaired
    except Exception:  # noqa: BLE001
        repaired = ""

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

    canon_root = data.setdefault("canon", {})
    if not isinstance(canon_root, dict):
        raise RuntimeError("Invalid canon ledger: 'canon' must be a mapping")

    previous_facts = canon_root.get("facts")
    if not isinstance(previous_facts, dict):
        previous_facts = {}

    structured_facts = extract_structured_facts(snapshot)
    conflicts = validate_fact_consistency(
        previous_facts=previous_facts,
        new_facts=structured_facts,
    )
    if conflicts:
        raise RuntimeError("canon_fact_conflict: " + " | ".join(conflicts))

    canon_root["facts"] = structured_facts
    canon_root["updated_at"] = _utc_now_iso()
    canon_root["chapter"] = chapter_number

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


def _looks_truncated(text: str) -> bool:
    """Detect likely truncation tails in generated prose."""

    stripped = str(text).rstrip()
    if not stripped:
        return True
    if stripped.endswith("..."):
        return True
    if stripped.endswith((":", ";", ",", "-", "(", "[")):
        return True
    contains_terminal = any(mark in stripped for mark in (".", "!", "?"))
    if (
        _word_count(stripped) >= 120
        and contains_terminal
        and not stripped.endswith((".", "!", "?", '"', "'", ")", "]"))
    ):
        return True
    if stripped.count('"') % 2 != 0:
        return True
    return False


def _write_text_with_fsync(path: Path, text: str) -> None:
    """Write UTF-8 text and fsync to reduce partial-write risk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _write_attempt_transport_error(
    *,
    packet_dir: Path,
    attempt: int,
    payload: dict[str, Any] | None,
) -> None:
    """Persist structured provider transport telemetry for one failed attempt."""

    if not isinstance(payload, dict) or not payload:
        return
    attempt_dir = packet_dir / "failures" / f"attempt-{max(1, attempt)}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    _write_text_with_fsync(
        attempt_dir / "transport_error.json",
        json.dumps(_jsonable(payload), indent=2, ensure_ascii=True) + "\n",
    )


def _summarize_model_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Build concise model metadata snapshot for validator artifacts."""

    invocations = diagnostics.get("model_invocations", [])
    if not isinstance(invocations, list):
        invocations = []

    latest_by_role: dict[str, dict[str, Any]] = {}
    latest_by_stage: dict[str, dict[str, Any]] = {}
    for row in invocations:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role", "")).strip().lower()
        stage = str(row.get("stage", "")).strip().lower()
        if not role:
            continue
        latest_by_role[role] = row
        if stage:
            latest_by_stage[stage] = row

    return {
        "provider": str(diagnostics.get("provider", "")).strip(),
        "drafter_model": latest_by_role.get("batch_prose", {}).get("model_id"),
        "editor_model": latest_by_role.get("batch_editing", {}).get("model_id"),
        "reviewer_model": latest_by_role.get("coherence_check", {}).get("model_id"),
        "planner_model": latest_by_role.get("batch_planning", {}).get("model_id"),
        "state_extractor_model": latest_by_role.get("repair_json", {}).get("model_id"),
        "planning_effective_model": latest_by_stage.get("scene_plan", {}).get(
            "effective_model_id"
        ),
        "drafting_effective_model": latest_by_stage.get("draft", {}).get(
            "effective_model_id"
        ),
        "editing_effective_model": latest_by_stage.get("edit", {}).get(
            "effective_model_id"
        ),
        "stitch_effective_model": latest_by_stage.get("stitch", {}).get(
            "effective_model_id"
        ),
        "semantic_review_effective_model": latest_by_stage.get(
            "semantic_review", {}
        ).get("effective_model_id"),
        "coherence_review_effective_model": latest_by_stage.get(
            "coherence_review", {}
        ).get("effective_model_id"),
        "invocations": invocations,
    }


def extract_structured_facts(snapshot: Any) -> dict[str, Any]:
    """Extract deterministic canon facts from the narrative snapshot."""

    character_facts: dict[str, dict[str, Any]] = {}
    for key, character in getattr(snapshot, "characters", {}).items():
        character_facts[str(key)] = {
            "status": str(getattr(character, "status", "")).strip().lower(),
            "location": str(getattr(character, "location", "")).strip().lower(),
            "inventory": sorted(
                [
                    str(item).strip().lower()
                    for item in list(getattr(character, "inventory", []))
                    if str(item).strip()
                ]
            ),
        }

    world_facts: dict[str, Any] = {}
    for key, value in getattr(snapshot, "world", {}).items():
        world_facts[str(key)] = _jsonable(value)

    return {
        "characters": character_facts,
        "world": world_facts,
        "plot_threads": json.loads(_serialize_plot_threads(snapshot)),
    }


def validate_fact_consistency(
    *,
    previous_facts: dict[str, Any],
    new_facts: dict[str, Any],
) -> list[str]:
    """Return canonical fact conflicts that should fail closed."""

    conflicts: list[str] = []
    previous_characters = previous_facts.get("characters", {})
    new_characters = new_facts.get("characters", {})
    if not isinstance(previous_characters, dict) or not isinstance(
        new_characters, dict
    ):
        return conflicts

    for character_id, previous_row in previous_characters.items():
        if not isinstance(previous_row, dict):
            continue
        new_row = new_characters.get(character_id)
        if not isinstance(new_row, dict):
            continue
        previous_status = str(previous_row.get("status", "")).strip().lower()
        new_status = str(new_row.get("status", "")).strip().lower()
        if previous_status == "dead" and new_status and new_status != "dead":
            conflicts.append(
                f"character={character_id}; prior_status=dead; new_status={new_status}"
            )

    return conflicts


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
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct scene-level acceptance checks for deterministic handoff validation."""

    enforce_scene_length = min_scene_words > 0
    diagnostic_payload = diagnostics or {}
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
            "edit_not_truncated": not _looks_truncated(edited_text),
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
            "model_diagnostics": _summarize_model_diagnostics(diagnostic_payload),
        }
        if failed_checks:
            failed_scenes.append(scene.scene_number)
        scene_reports.append(report)

    return {
        "chapter": chapter.chapter_number,
        "scenes": scene_reports,
        "failed_scenes": failed_scenes,
        "all_passed": not failed_scenes,
        "model_diagnostics": _summarize_model_diagnostics(diagnostic_payload),
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
            "edit_not_truncated": not _looks_truncated(edited_text),
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
        "stitched_not_truncated": not _looks_truncated(stitched_text),
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
    raw_payloads: dict[str, str] | None = None,
    transport_errors: list[dict[str, Any]] | None = None,
    quarantine_decisions: list[dict[str, Any]] | None = None,
) -> Path:
    """Persist a deterministic chapter packet for validator handoff before commit."""

    packet_dir = _chapter_packet_dir(book_path, config, chapter.chapter_number)
    packet_dir.mkdir(parents=True, exist_ok=True)

    _write_text_with_fsync(
        packet_dir / "outline_context.md",
        chapter.outline_text.strip() + "\n",
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
    _write_text_with_fsync(
        packet_dir / "scene_plan.json",
        json.dumps(scene_plan, indent=2, ensure_ascii=True) + "\n",
    )

    for scene in chapter.scene_artifacts:
        _write_text_with_fsync(
            packet_dir / f"scene_{scene.scene_number}_draft.md",
            scene.draft_text.strip() + "\n",
        )
        _write_text_with_fsync(
            packet_dir / f"scene_{scene.scene_number}_edit.md",
            scene.edited_text.strip() + "\n",
        )

    for scene_report in scene_acceptance.get("scenes", []):
        scene_number = int(scene_report.get("scene_number", 0))
        if scene_number <= 0:
            continue
        _write_text_with_fsync(
            packet_dir / f"scene_{scene_number}_validator_report.json",
            json.dumps(_jsonable(scene_report), indent=2, ensure_ascii=True) + "\n",
        )

    _write_text_with_fsync(
        packet_dir / "stitched_chapter.md",
        chapter.stitched_text.strip() + "\n",
    )

    update = chapter.state_update if isinstance(chapter.state_update, dict) else {}
    patch = update.get("patch")
    patch_payload = _jsonable(getattr(patch, "operations", []))
    _write_text_with_fsync(
        packet_dir / "state_patch.json",
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
    )

    precommit_canon = load_canon(book_path)
    _write_text_with_fsync(
        packet_dir / "canon_delta.yml",
        yaml.safe_dump(
            {
                "chapter": chapter.chapter_number,
                "status": "precommit",
                "canon_snapshot": _jsonable(precommit_canon),
            },
            sort_keys=False,
            allow_unicode=False,
        ),
    )

    diagnostics_payload = dict(_jsonable(diagnostics))
    diagnostics_payload["model_diagnostics"] = _summarize_model_diagnostics(diagnostics)
    _write_text_with_fsync(
        packet_dir / "diagnostics.json",
        json.dumps(diagnostics_payload, indent=2, ensure_ascii=True) + "\n",
    )

    normalized_raw_payloads: dict[str, str] = {}
    for stage, payload in (raw_payloads or {}).items():
        stage_name = str(stage).strip()
        if not stage_name:
            continue
        text_payload = str(payload).strip()
        if not text_payload:
            continue
        normalized_raw_payloads[stage_name] = text_payload
    _write_text_with_fsync(
        packet_dir / "raw_payloads.json",
        json.dumps(normalized_raw_payloads, indent=2, ensure_ascii=True) + "\n",
    )

    _write_text_with_fsync(
        packet_dir / "transport_errors.json",
        json.dumps(_jsonable(transport_errors or []), indent=2, ensure_ascii=True)
        + "\n",
    )
    _write_text_with_fsync(
        packet_dir / "quarantine_decisions.json",
        json.dumps(_jsonable(quarantine_decisions or []), indent=2, ensure_ascii=True)
        + "\n",
    )

    validator_report_payload = {
        "phase": "precommit",
        "chapter": chapter.chapter_number,
        "acceptance": acceptance,
        "scene_acceptance": scene_acceptance,
        "stage_contract": stage_contract,
        "semantic_reason": diagnostics.get("semantic_review_last_reason"),
        "retry_reason": diagnostics.get("chapter_validation_last_retry_reason"),
        "model_diagnostics": _summarize_model_diagnostics(diagnostics),
    }
    _validate_validator_report_payload(validator_report_payload)
    _write_text_with_fsync(
        packet_dir / "validator_report.json",
        json.dumps(validator_report_payload, indent=2, ensure_ascii=True) + "\n",
    )

    return packet_dir


def _assert_packet_integrity(packet_dir: Path) -> None:
    """Fail closed when required packet forensics artifacts are missing/empty."""

    required = [
        packet_dir / "diagnostics.json",
        packet_dir / "validator_report.json",
        packet_dir / "raw_payloads.json",
    ]
    missing = [str(path.name) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            "packet_integrity_failed: missing artifacts " + ", ".join(sorted(missing))
        )

    empty = [str(path.name) for path in required if path.stat().st_size <= 0]
    if empty:
        raise RuntimeError(
            "packet_integrity_failed: empty artifacts " + ", ".join(sorted(empty))
        )


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
            "audit_entry_appended": True,
        },
    }
    report["commit_status"]["all_persisted"] = all(report["commit_status"].values())
    _validate_validator_report_payload(report)

    _write_text_with_fsync(
        packet_dir / "validator_report.json",
        json.dumps(report, indent=2, ensure_ascii=True) + "\n",
    )

    committed_canon = load_canon(book_path)
    _write_text_with_fsync(
        packet_dir / "canon_delta.yml",
        yaml.safe_dump(
            {
                "chapter": chapter_number,
                "status": "committed",
                "canon_snapshot": _jsonable(committed_canon),
            },
            sort_keys=False,
            allow_unicode=False,
        ),
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

    min_scene_words = 225 if enforce_completeness_guard else 0
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
    role_escalation_counts: dict[str, int] = {}
    base_settings: LLMSettings | None = None
    configured_model = (
        str(getattr(runtime_config, "llm_model", "")).strip() or "<unset>"
    )
    run_started = time.monotonic()
    run_id = f"book-run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    telemetry: dict[str, int] = {
        "retries": 0,
        "escalations": 0,
        "semantic_reviews_run": 0,
    }
    model_invocations_by_chapter: dict[int, list[dict[str, Any]]] = {}
    raw_stage_outputs_by_chapter: dict[int, dict[str, str]] = {}
    canonical_conflicts_by_chapter: dict[int, str] = {}
    transport_errors_by_chapter: dict[int, list[dict[str, Any]]] = {}
    quarantine_events_by_chapter: dict[int, list[dict[str, Any]]] = {}
    latest_transport_error_by_chapter: dict[int, dict[str, Any]] = {}
    attempt_transport_errors: dict[tuple[int, int], dict[str, Any]] = {}

    def _record_raw_output(chapter_number: int, stage_name: str, text: str) -> None:
        chapter_bucket = raw_stage_outputs_by_chapter.setdefault(chapter_number, {})
        chapter_bucket[stage_name] = str(text).strip()

    def _record_model_invocation(
        *,
        chapter_number: int,
        stage_name: str,
        role: str,
        model_id: str,
        source: str,
        attempt: int,
        configured_model_id: str,
        effective_model_id: str,
        status: str,
        transport_error: dict[str, Any] | None = None,
    ) -> None:
        chapter_rows = model_invocations_by_chapter.setdefault(chapter_number, [])
        chapter_rows.append(
            {
                "timestamp": _utc_now_iso(),
                "provider": provider_name,
                "stage": stage_name,
                "role": role,
                "model_id": model_id,
                "configured_model_id": configured_model_id,
                "effective_model_id": effective_model_id,
                "source": source,
                "attempt": max(1, int(attempt)),
                "status": str(status).strip() or "unknown",
                "transport_error": _jsonable(transport_error or {}),
            }
        )

    def _record_transport_error(
        *,
        chapter_number: int,
        stage_name: str,
        role: str,
        configured_model_id: str,
        effective_model_id: str,
        exc: Exception,
    ) -> dict[str, Any]:
        root: Exception = exc.__cause__ if getattr(exc, "__cause__", None) else exc
        payload: dict[str, Any]
        if isinstance(root, LLMInvocationError) and root.transport_error:
            payload = dict(root.transport_error)
            if isinstance(root.quarantine_events, list) and root.quarantine_events:
                rows = quarantine_events_by_chapter.setdefault(chapter_number, [])
                rows.extend(
                    [
                        {
                            **_jsonable(event),
                            "chapter": chapter_number,
                            "stage": stage_name,
                            "role": role,
                        }
                        for event in root.quarantine_events
                        if isinstance(event, dict)
                    ]
                )
        else:
            payload = build_transport_error_payload(
                root,
                provider=provider_name or "unknown",
                configured_model=configured_model_id,
                effective_model=effective_model_id,
            )

        payload.update(
            {
                "timestamp": _utc_now_iso(),
                "chapter": chapter_number,
                "stage": stage_name,
                "role": role,
            }
        )
        rows = transport_errors_by_chapter.setdefault(chapter_number, [])
        rows.append(payload)
        latest_transport_error_by_chapter[chapter_number] = payload
        return payload

    def _persist_retry_stage_artifacts(
        *,
        chapter_number: int,
        attempt: int,
        reason: str,
    ) -> None:
        """Persist raw stage outputs for each retry attempt."""

        packet_dir = _chapter_packet_dir(book_path, runtime_config, chapter_number)
        attempt_dir = packet_dir / "failures" / f"attempt-{max(1, attempt)}"
        attempt_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "chapter": chapter_number,
            "attempt": max(1, attempt),
            "reason": str(reason).strip(),
            "captured_at": _utc_now_iso(),
        }
        _write_text_with_fsync(
            attempt_dir / "metadata.json",
            json.dumps(metadata, indent=2, ensure_ascii=True) + "\n",
        )

        transport_payload = attempt_transport_errors.get(
            (chapter_number, max(1, attempt))
        )
        _write_attempt_transport_error(
            packet_dir=packet_dir,
            attempt=attempt,
            payload=transport_payload,
        )

        stage_rows = raw_stage_outputs_by_chapter.get(chapter_number, {})
        stage_to_file = {
            "scene_plan": "planner_output.txt",
            "scene_plan_repair": "planner_output.txt",
            "draft": "drafter_output.txt",
            "draft_retry": "drafter_output.txt",
            "edit": "editor_output.txt",
            "stitch": "editor_output.txt",
            "coherence_review": "reviewer_output.txt",
            "semantic_review": "reviewer_output.txt",
            "state_extract": "state_extractor_output.txt",
        }
        persisted: set[str] = set()
        for stage, file_name in stage_to_file.items():
            payload = str(stage_rows.get(stage, "")).strip()
            if not payload:
                continue
            if file_name in persisted:
                continue
            _write_text_with_fsync(attempt_dir / file_name, payload + "\n")
            persisted.add(file_name)

    def _persist_chapter_failure_blackbox(
        chapter_number: int,
        attempt: int,
        prompt_context: str,
        raw_response: str,
        error_reason: str,
    ) -> None:
        """Write forensic black-box JSON for every failed generation attempt.

        File: outline/chapter_packets/chapter-<N>/failures/attempt-<N>_blackbox.json
        Contains the prompt context, raw (possibly broken) response, and the
        Python-native error reason — enough to diagnose any failure offline.
        """
        packet_dir = _chapter_packet_dir(book_path, runtime_config, chapter_number)
        failures_dir = packet_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        blackbox_file = failures_dir / f"attempt-{max(1, attempt)}_blackbox.json"
        payload = {
            "chapter": chapter_number,
            "attempt": max(1, attempt),
            "prompt_context": str(prompt_context).strip(),
            "raw_response": str(raw_response).strip(),
            "error_reason": str(error_reason).strip(),
            "captured_at": _utc_now_iso(),
        }
        _write_text_with_fsync(
            blackbox_file,
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        )

    def _provider_display_name(name: str) -> str:
        normalized = str(name).strip().lower()
        if normalized == "openrouter":
            return "OpenRouter"
        if normalized == "openai":
            return "OpenAI"
        if normalized == "ollama":
            return "Ollama"
        return normalized or "provider"

    def _emit_chapter_progress(chapter_number: int, message: str) -> None:
        _BOOK_LOGGER.info(
            "chapter_progress",
            run_id=run_id,
            chapter=chapter_number,
            message=message,
        )

    def _resolve_effective_model(llm: Any, *, fallback_model: str) -> str:
        resolved_name = getattr(llm, "last_resolved_model", None)
        if isinstance(resolved_name, str) and resolved_name.strip():
            return resolved_name.strip()

        idx = getattr(llm, "last_resolved_model_index", None)
        sequence = getattr(llm, "model_sequence", None)
        if isinstance(idx, int) and isinstance(sequence, list):
            if 0 <= idx < len(sequence):
                return str(sequence[idx]).strip() or fallback_model

        model_name = getattr(llm, "model_name", None)
        if isinstance(model_name, str) and model_name.strip():
            return model_name.strip()
        model = getattr(llm, "model", None)
        if isinstance(model, str) and model.strip():
            return model.strip()
        return fallback_model

    def _model_source(
        *,
        role: str,
        requested_index: int,
        effective_model: str,
        using_rankings: bool,
    ) -> str:
        if provider_name != "openrouter" or not using_rankings:
            return "explicit_config"
        if effective_model == "openrouter/free":
            return "openrouter_free_router"
        if requested_index > 0 and role_escalation_counts.get(role, 0) > 0:
            return "escalation_ladder"
        if requested_index == 0:
            return "rankings_primary"
        return "fallback"

    def _print_stage_model_line(
        *,
        chapter_number: int,
        stage_name: str,
        role: str,
        effective_model: str,
        source: str,
    ) -> None:
        _emit_chapter_progress(
            chapter_number,
            (
                f"Stage={stage_name} role={role} "
                f"configured={configured_model} effective={effective_model} "
                f"source={source}"
            ),
        )

    def _invoke_with_heartbeat(
        *,
        chapter_number: int,
        invoker: Callable[[], str],
    ) -> str:
        stop_event = threading.Event()
        provider_label = _provider_display_name(provider_name)
        heartbeat_seconds = 15.0
        heartbeat_raw = os.getenv("STORYCRAFTR_BOOK_HEARTBEAT_SECONDS", "").strip()
        if heartbeat_raw:
            try:
                heartbeat_seconds = max(0.05, float(heartbeat_raw))
            except ValueError:
                heartbeat_seconds = 15.0

        def _heartbeat() -> None:
            elapsed = 0.0
            while not stop_event.wait(heartbeat_seconds):
                elapsed += heartbeat_seconds
                elapsed_label = (
                    f"{int(round(elapsed))}s"
                    if heartbeat_seconds >= 1.0
                    else f"{elapsed:.2f}s"
                )
                _emit_chapter_progress(
                    chapter_number,
                    f"Waiting on {provider_label} response... {elapsed_label} elapsed",
                )

        thread = threading.Thread(target=_heartbeat, daemon=True)
        thread.start()
        try:
            return invoker()
        finally:
            stop_event.set()
            thread.join(timeout=0.1)

    def _print_final_run_summary(final_status: str) -> None:
        elapsed = time.monotonic() - run_started
        _BOOK_LOGGER.info(
            "book_run_summary",
            run_id=run_id,
            elapsed_seconds=round(elapsed, 2),
            chapters_attempted=chapters,
            chapters_committed=len(engine.history),
            retries=telemetry["retries"],
            escalations=telemetry["escalations"],
            semantic_reviews_run=telemetry["semantic_reviews_run"],
            coherence_reviews_run=coherence_reviews_run,
            final_status=final_status,
        )

    if runtime_config is not None and hasattr(runtime_config, "llm_provider"):
        base_settings = llm_settings_from_config(runtime_config)
    if provider_name == "openrouter" and runtime_config is not None:
        # Pre-flight: verify all ranking models are free; auto-substitute paid ones.
        # This must run before any generation tokens are spent.
        if validate_openrouter_rankings_config.__module__ != "storycraftr.llm.factory":
            rankings = validate_openrouter_rankings_config()
        else:
            try:
                rankings = validate_ranking_consensus()
            except Exception:
                # Backward-compatible fallback for strict rankings validators.
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
        preferred = _prefer_independent_fallback(
            role_model_specs.get("coherence_check", tuple()),
            reference_family=drafter_family,
        )
        filtered = _exclude_model_family(
            preferred,
            excluded_family=drafter_family,
        )
        role_model_specs["coherence_check"] = (
            filtered if filtered else role_model_specs.get("coherence_check", tuple())
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

    if strict_autonomous and enable_semantic_review:
        prose_models = role_model_specs.get("batch_prose", tuple())
        reviewer_models = role_model_specs.get("coherence_check", tuple())
        prose_model = prose_models[0] if prose_models else configured_model
        reviewer_model = reviewer_models[0] if reviewer_models else configured_model
        prose_family = _model_family(prose_model)
        conflicting_reviewer_models = [
            model
            for model in reviewer_models
            if _model_family(model) and _model_family(model) == prose_family
        ]
        if _model_family(prose_model) == _model_family(reviewer_model) or (
            conflicting_reviewer_models
            and len(conflicting_reviewer_models) == len(reviewer_models)
        ):
            raise BookEngineError(
                "validator_independence_failed: reviewer must be independent "
                "from drafter model family in strict autonomous runs"
            )

    assistant = create_or_get_assistant(book_path)
    state_store = NarrativeStateStore(book_path)
    memory_manager = NarrativeMemoryManager(book_path=book_path, config=runtime_config)
    rules = load_craft_rule_set()
    mandatory_seed_constraints = _build_mandatory_seed_constraints(seed_text)
    pipeline = SceneGenerationPipeline(
        planner_rules=rules.planner.text,
        drafter_rules=rules.drafter.text,
        editor_rules=rules.editor.text,
    )

    def _invoke_role_text(
        role: str,
        *,
        chapter_number: int,
        stage_name: str,
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
            requested_model = _resolve_effective_model(
                llm,
                fallback_model=configured_model,
            )
            try:
                response_text = _invoke_with_heartbeat(
                    chapter_number=chapter_number,
                    invoker=lambda: _invoke_llm_text(
                        llm,
                        system_rules=system_rules,
                        prompt=prompt,
                        stage_name=stage_name,
                    ),
                )
            except Exception as exc:
                effective_model = _resolve_effective_model(
                    llm,
                    fallback_model=requested_model,
                )
                transport_payload = _record_transport_error(
                    chapter_number=chapter_number,
                    stage_name=stage_name,
                    role=role,
                    configured_model_id=requested_model,
                    effective_model_id=effective_model,
                    exc=exc,
                )
                _record_model_invocation(
                    chapter_number=chapter_number,
                    stage_name=stage_name,
                    role=role,
                    model_id=effective_model,
                    source="explicit_config",
                    attempt=1,
                    configured_model_id=requested_model,
                    effective_model_id=effective_model,
                    status="failed",
                    transport_error=transport_payload,
                )
                raise BookEngineError(
                    "Model invocation failed with transport error: "
                    f"{transport_payload.get('raw_error_body', str(exc))}"
                ) from exc
            effective_model = _resolve_effective_model(
                llm,
                fallback_model=requested_model,
            )
            quarantine_rows = getattr(llm, "quarantine_events", None)
            if isinstance(quarantine_rows, list) and quarantine_rows:
                rows = quarantine_events_by_chapter.setdefault(chapter_number, [])
                rows.extend(
                    [
                        {
                            **_jsonable(event),
                            "chapter": chapter_number,
                            "stage": stage_name,
                            "role": role,
                        }
                        for event in quarantine_rows
                        if isinstance(event, dict)
                    ]
                )
            _print_stage_model_line(
                chapter_number=chapter_number,
                stage_name=stage_name,
                role=role,
                effective_model=effective_model,
                source="explicit_config",
            )
            _record_model_invocation(
                chapter_number=chapter_number,
                stage_name=stage_name,
                role=role,
                model_id=effective_model,
                source="explicit_config",
                attempt=1,
                configured_model_id=requested_model,
                effective_model_id=effective_model,
                status="succeeded",
            )
            _record_raw_output(chapter_number, stage_name, response_text)
            return response_text

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
                requested_model = (
                    role_model_specs.get(role, tuple())[candidate_index]
                    if candidate_index < len(role_model_specs.get(role, tuple()))
                    else configured_model
                )
                response_text = _invoke_with_heartbeat(
                    chapter_number=chapter_number,
                    invoker=lambda: _invoke_llm_text(
                        llm,
                        system_rules=system_rules,
                        prompt=prompt,
                        stage_name=stage_name,
                    ),
                )
                effective_model = _resolve_effective_model(
                    llm,
                    fallback_model=requested_model,
                )
                quarantine_rows = getattr(llm, "quarantine_events", None)
                if isinstance(quarantine_rows, list) and quarantine_rows:
                    rows = quarantine_events_by_chapter.setdefault(chapter_number, [])
                    rows.extend(
                        [
                            {
                                **_jsonable(event),
                                "chapter": chapter_number,
                                "stage": stage_name,
                                "role": role,
                            }
                            for event in quarantine_rows
                            if isinstance(event, dict)
                        ]
                    )
                source = _model_source(
                    role=role,
                    requested_index=candidate_index,
                    effective_model=effective_model,
                    using_rankings=bool(role_model_specs.get(role, tuple())),
                )
                _print_stage_model_line(
                    chapter_number=chapter_number,
                    stage_name=stage_name,
                    role=role,
                    effective_model=effective_model,
                    source=source,
                )
                _record_model_invocation(
                    chapter_number=chapter_number,
                    stage_name=stage_name,
                    role=role,
                    model_id=effective_model,
                    source=source,
                    attempt=candidate_index + 1,
                    configured_model_id=requested_model,
                    effective_model_id=effective_model,
                    status="succeeded",
                )
                _record_raw_output(chapter_number, stage_name, response_text)
                return response_text
            except Exception as exc:
                effective_model = _resolve_effective_model(
                    llm,
                    fallback_model=requested_model,
                )
                transport_payload = _record_transport_error(
                    chapter_number=chapter_number,
                    stage_name=stage_name,
                    role=role,
                    configured_model_id=requested_model,
                    effective_model_id=effective_model,
                    exc=exc,
                )
                _record_model_invocation(
                    chapter_number=chapter_number,
                    stage_name=stage_name,
                    role=role,
                    model_id=effective_model,
                    source=_model_source(
                        role=role,
                        requested_index=candidate_index,
                        effective_model=effective_model,
                        using_rankings=bool(role_model_specs.get(role, tuple())),
                    ),
                    attempt=candidate_index + 1,
                    configured_model_id=requested_model,
                    effective_model_id=effective_model,
                    status="failed",
                    transport_error=transport_payload,
                )
                errors.append(
                    str(transport_payload.get("raw_error_body", "")).strip() or str(exc)
                )

        raise BookEngineError(
            f"All ranked models failed for role '{role}': {errors[-1] if errors else 'unknown error'}"
        )

    def _rotate_role_model(
        role: str,
        *,
        reason: str,
        chapter_number: int,
        attempt: int,
    ) -> bool:
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
        telemetry["escalations"] += 1
        role_escalation_counts[role] = role_escalation_counts.get(role, 0) + 1
        model_ids = role_model_specs.get(role, tuple())
        next_model = (
            model_ids[next_index] if next_index < len(model_ids) else "<unknown>"
        )
        _emit_chapter_progress(
            chapter_number,
            f"Escalating {role} model to {next_model} (attempt {attempt}) reason={reason}",
        )
        return True

    def _on_scene_generation_retry(
        chapter_number: int,
        scene_number: int,
        attempt: int,
        reason: str,
    ) -> None:
        """Escalate prose/editing models when scene retries indicate quality stasis."""

        telemetry["retries"] += 1
        latest_transport = latest_transport_error_by_chapter.get(chapter_number)
        if latest_transport is not None:
            attempt_transport_errors[
                (chapter_number, max(1, attempt))
            ] = latest_transport
        _emit_chapter_progress(
            chapter_number,
            f"Scene {scene_number} failed validation: {reason}",
        )
        _persist_retry_stage_artifacts(
            chapter_number=chapter_number,
            attempt=attempt,
            reason=reason,
        )
        if provider_name != "openrouter":
            return
        if attempt < 2:
            return

        reason_lower = reason.lower()
        if "scene_structure_missing" in reason_lower:
            _rotate_role_model(
                "batch_prose",
                reason=reason,
                chapter_number=chapter_number,
                attempt=attempt,
            )
            _rotate_role_model(
                "batch_editing",
                reason=reason,
                chapter_number=chapter_number,
                attempt=attempt,
            )
            _rotate_role_model(
                "batch_planning",
                reason=f"scene_repair:{reason}",
                chapter_number=chapter_number,
                attempt=attempt,
            )
            return

        if any(
            token in reason_lower
            for token in (
                "too_short",
                "validation",
                "terminal_truncation",
                "insufficient_expansion",
                "missing_pov",
            )
        ):
            _rotate_role_model(
                "batch_prose",
                reason=reason,
                chapter_number=chapter_number,
                attempt=attempt,
            )
            _rotate_role_model(
                "batch_editing",
                reason=reason,
                chapter_number=chapter_number,
                attempt=attempt,
            )

    def _on_chapter_validation_retry(attempt: int, total: int, reason: str) -> None:
        """Escalate ranked models after repeated chapter-level quality failures."""

        telemetry["retries"] += 1
        chapter_number = max(1, engine.current_chapter)
        latest_transport = latest_transport_error_by_chapter.get(chapter_number)
        if latest_transport is not None:
            attempt_transport_errors[
                (chapter_number, max(1, attempt))
            ] = latest_transport
        _emit_chapter_progress(
            chapter_number,
            f"Chapter validation retry {attempt}/{total}: {reason}",
        )
        _persist_retry_stage_artifacts(
            chapter_number=chapter_number,
            attempt=attempt,
            reason=reason,
        )
        if provider_name != "openrouter":
            return
        if attempt < 2:
            return

        reason_lower = reason.lower()
        rotated = False
        if any(
            token in reason_lower
            for token in (
                "too_short",
                "duplicate",
                "truncated",
                "empty_output",
                "terminal_truncation",
                "insufficient_expansion",
                "missing_pov",
            )
        ):
            rotated = (
                _rotate_role_model(
                    "batch_prose",
                    reason=reason,
                    chapter_number=chapter_number,
                    attempt=attempt,
                )
                or rotated
            )
            rotated = (
                _rotate_role_model(
                    "batch_editing",
                    reason=reason,
                    chapter_number=chapter_number,
                    attempt=attempt,
                )
                or rotated
            )
        if "semantic_review" in reason_lower:
            rotated = (
                _rotate_role_model(
                    "batch_prose",
                    reason=reason,
                    chapter_number=chapter_number,
                    attempt=attempt,
                )
                or rotated
            )
            rotated = (
                _rotate_role_model(
                    "batch_editing",
                    reason=reason,
                    chapter_number=chapter_number,
                    attempt=attempt,
                )
                or rotated
            )
            # Keep reviewer rotation as a tertiary fallback when generation
            # ladders are exhausted or unavailable.
            if not rotated:
                rotated = (
                    _rotate_role_model(
                        "coherence_check",
                        reason=reason,
                        chapter_number=chapter_number,
                        attempt=attempt,
                    )
                    or rotated
                )

        if not rotated:
            _rotate_role_model(
                "batch_prose",
                reason=reason,
                chapter_number=chapter_number,
                attempt=attempt,
            )

    def _on_coherence_repair_retry(attempt: int, total: int, reason: str) -> None:
        """Force escalation before coherence repair regeneration attempts."""

        telemetry["retries"] += 1
        chapter_number = max(1, engine.current_chapter)
        latest_transport = latest_transport_error_by_chapter.get(chapter_number)
        if latest_transport is not None:
            attempt_transport_errors[
                (chapter_number, max(1, attempt))
            ] = latest_transport
        _emit_chapter_progress(
            chapter_number,
            f"Coherence repair retry {attempt}/{total}: {reason}",
        )
        _persist_retry_stage_artifacts(
            chapter_number=chapter_number,
            attempt=attempt,
            reason=reason,
        )
        if provider_name != "openrouter":
            return
        _rotate_role_model(
            "batch_prose",
            reason=f"coherence_repair:{reason}",
            chapter_number=chapter_number,
            attempt=attempt,
        )
        _rotate_role_model(
            "batch_editing",
            reason=f"coherence_repair:{reason}",
            chapter_number=chapter_number,
            attempt=attempt,
        )
        _rotate_role_model(
            "coherence_check",
            reason=f"coherence_repair:{reason}",
            chapter_number=chapter_number,
            attempt=attempt,
        )

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

    def _resolve_character_ledger_names() -> tuple[str, ...]:
        """Return deterministic character ledger names from narrative state."""

        try:
            snapshot = state_store.load()
        except Exception:
            return ()

        names: list[str] = []
        seen: set[str] = set()
        for character_id, character in snapshot.characters.items():
            candidate = (
                str(getattr(character, "name", "")).strip() or str(character_id).strip()
            )
            if len(candidate) < 2:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(candidate)
        return tuple(names)

    def _build_outline(
        seed: str,
        chapter_number: int,
        history: tuple[ChapterRunArtifact, ...],
    ) -> str:
        _emit_chapter_progress(chapter_number, "Outline generation started...")
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
        output = _invoke_role_text(
            "batch_planning",
            chapter_number=chapter_number,
            stage_name="outline",
            system_rules=rules.planner.text,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )
        _emit_chapter_progress(chapter_number, "Outline generation complete")
        return output

    def _plan_scene_directive(
        *,
        outline: str,
        chapter_number: int,
        scene_number: int,
        extra_feedback: str | None = None,
        stage_name: str = "scene_plan",
    ) -> SceneDirective:
        grounding = _build_grounding_context(
            chapter_number=chapter_number,
            history=engine.history,
        )
        ledger_names = _resolve_character_ledger_names()
        ledger_text = ", ".join(ledger_names)
        prompt_sections = [
            f"Chapter {chapter_number}, scene {scene_number} of 3.",
            "Use this approved chapter outline:",
            outline,
            grounding,
            (
                "POV ENTITY CONSTRAINT: The first token in `goal` must be a POV "
                "character name, not a verb."
            ),
            (
                "POV ENTITY CONSTRAINT: Never start `goal` with verb-like tokens "
                "such as Gather, Reach, Seek, or Investigate."
            ),
            (
                "Directive requirement: outcome must include at least one "
                "movement marker word such as decides, changes, discovers, "
                "or fails."
            ),
            (
                "Directive requirement: outcome must describe the exact on-page turn "
                "the final paragraphs will land on. Do not use vague endings or "
                "generic placeholder wording."
            ),
        ]
        if ledger_text:
            prompt_sections.extend(
                [
                    f"Known character ledger names: {ledger_text}",
                    (
                        "POV ENTITY CONSTRAINT: `goal` must begin with one of these "
                        "ledger names exactly."
                    ),
                ]
            )
        if len(ledger_names) == 1:
            prompt_sections.append(f"If uncertain, default POV to: {ledger_names[0]}")
        if extra_feedback:
            prompt_sections.extend(
                [
                    "Previous scene drift feedback:",
                    extra_feedback.strip(),
                ]
            )
        base_prompt = "\n".join(prompt_sections)

        parsed_directive: SceneDirective | None = None
        last_error: Exception | None = None
        planner_input = base_prompt
        for attempt_index in range(3):
            planner_prompt = pipeline.build_planner_user_prompt(planner_input)
            planner_role = "batch_planning" if attempt_index == 0 else "repair_json"
            planner_response = _invoke_role_text(
                planner_role,
                chapter_number=chapter_number,
                stage_name=stage_name,
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
                        f"Exact validation error: {exc}",
                        (
                            "The first token in `goal` must be a real character name "
                            "from the ledger, never a verb-like token."
                        ),
                        (
                            "Outcome must contain at least one movement marker: "
                            "decides, changes, discovers, or fails."
                        ),
                        (
                            "Outcome must be concrete enough that the drafter can "
                            "realize it directly in the final scene beat."
                        ),
                        "Return JSON only with double-quoted keys/values.",
                        planner_response,
                    ]
                )

        if parsed_directive is None:
            raise BookEngineError(
                "Scene planner failed strict directive schema validation"
            ) from last_error
        return parsed_directive

    def _build_scene_plan(outline: str, chapter_number: int) -> list[SceneDirective]:
        _emit_chapter_progress(chapter_number, "Scene planning started...")

        def _plan_with_python_validation_retry(
            *,
            scene_number: int,
            stage_name: str,
            base_feedback: str | None = None,
            prior_directive: SceneDirective | None = None,
            repaired: bool = False,
        ) -> SceneDirective:
            max_attempts = 3
            extra_feedback = str(base_feedback or "").strip() or None
            last_error: Exception | None = None
            current_directive = prior_directive

            for attempt in range(1, max_attempts + 1):
                if attempt > 1 and last_error is not None:
                    directive_context = current_directive or SceneDirective(
                        goal="",
                        conflict="",
                        stakes="",
                        outcome="",
                    )
                    correction_lines = [
                        (
                            f"CRITICAL CORRECTION (Attempt {attempt}): Your previous "
                            f"{'repaired scene directive' if repaired else 'scene directive'} was rejected."
                        ),
                        f"Exact validation error: {last_error}",
                        "You MUST fix this exact error.",
                        (
                            "The outcome field MUST contain a valid decision-beat "
                            "movement marker and the repaired scene must remain aligned "
                            "to the existing chapter plan."
                        ),
                        f"Failing scene number: {scene_number}",
                        f"Current scene goal: {directive_context.goal}",
                        f"Current scene conflict: {directive_context.conflict}",
                        f"Current scene outcome: {directive_context.outcome}",
                        (
                            "Preserve chapter-plan alignment and do not invent new "
                            "locations, factions, or events not implied by the outline."
                        ),
                    ]
                    extra_feedback = "\n".join(
                        [
                            *(
                                [extra_feedback]
                                if extra_feedback
                                and "CRITICAL CORRECTION" not in extra_feedback
                                else []
                            ),
                            *correction_lines,
                        ]
                    )

                candidate = _plan_scene_directive(
                    outline=outline,
                    chapter_number=chapter_number,
                    scene_number=scene_number,
                    extra_feedback=extra_feedback,
                    stage_name=stage_name,
                )

                try:
                    engine._validate_scene_directive(
                        candidate,
                        scene_number=scene_number,
                    )
                    return candidate
                except BookEngineError as exc:
                    last_error = exc
                    current_directive = candidate

            raise BookEngineError(
                "Scene planner directive validation failed after bounded retries"
            ) from last_error

        directives: list[SceneDirective] = []
        for scene_number in range(1, 4):
            directives.append(
                _plan_with_python_validation_retry(
                    scene_number=scene_number,
                    stage_name="scene_plan",
                )
            )
        _emit_chapter_progress(
            chapter_number,
            f"Scene planning complete ({len(directives)} scenes)",
        )
        return directives

    def _repair_scene_directive(
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        failure_reason: str,
    ) -> SceneDirective:
        _emit_chapter_progress(
            chapter_number,
            f"Repairing scene {scene_number} plan after structure drift...",
        )
        base_feedback = "\n".join(
            [
                f"Failure reason: {failure_reason}",
                "Keep the chapter outline intent, but make the scene outcome more "
                "concrete and easier to execute literally on-page.",
                f"Prior goal: {directive.goal}",
                f"Prior conflict: {directive.conflict}",
                f"Prior stakes: {directive.stakes}",
                f"Prior outcome: {directive.outcome}",
                "Avoid generic placeholder subjects such as 'POV character' when a "
                "more concrete phrasing is possible.",
            ]
        )

        max_attempts = 3
        last_error: Exception | None = None
        current_directive = directive
        extra_feedback = base_feedback

        for attempt in range(1, max_attempts + 1):
            if attempt > 1 and last_error is not None:
                correction_lines = [
                    (
                        f"CRITICAL CORRECTION (Attempt {attempt}): Your previous "
                        "repaired scene directive was rejected."
                    ),
                    f"Exact validation error: {last_error}",
                    "You MUST fix this exact error.",
                    (
                        "The outcome field MUST contain a valid decision-beat "
                        "movement marker and the repaired scene must remain aligned "
                        "to the existing chapter plan."
                    ),
                    f"Failing scene number: {scene_number}",
                    f"Current scene goal: {current_directive.goal}",
                    f"Current scene conflict: {current_directive.conflict}",
                    f"Current scene outcome: {current_directive.outcome}",
                    (
                        "Preserve chapter-plan alignment and do not invent new "
                        "locations, factions, or events not implied by the outline."
                    ),
                ]
                extra_feedback = "\n".join([base_feedback, *correction_lines])

            candidate = _plan_scene_directive(
                outline=engine.approved_outline,
                chapter_number=chapter_number,
                scene_number=scene_number,
                extra_feedback=extra_feedback,
                stage_name="scene_plan_repair",
            )

            try:
                engine._validate_scene_directive(candidate, scene_number=scene_number)
                return candidate
            except BookEngineError as exc:
                last_error = exc
                current_directive = candidate

        raise BookEngineError(
            f"Scene plan repair exhausted deterministic retries for scene {scene_number}"
        ) from last_error

    def _draft_scene(
        directive: SceneDirective,
        chapter_number: int,
        scene_number: int,
        repair_directive: str | None = None,
        repair_in_system_prompt: bool = False,
    ) -> str:
        _emit_chapter_progress(
            chapter_number,
            f"Drafting scene {scene_number}/3...",
        )
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
        drafter_rules = _compose_stage_system_rules(
            base_rules=rules.drafter.text,
            mandatory_seed_constraints=mandatory_seed_constraints,
            repair_directive=(
                repair_directive
                if repair_directive and repair_in_system_prompt
                else None
            ),
        )
        output = _invoke_role_text(
            "batch_prose",
            chapter_number=chapter_number,
            stage_name="draft",
            system_rules=drafter_rules,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )
        _emit_chapter_progress(
            chapter_number,
            f"Drafting scene {scene_number}/3 complete ({_word_count(output)} words)",
        )
        return output

    def _edit_scene(
        directive: SceneDirective,
        draft: str,
        chapter_number: int,
        scene_number: int,
    ) -> str:
        _emit_chapter_progress(
            chapter_number,
            f"Editing scene {scene_number}/3...",
        )
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
        editor_rules = _compose_stage_system_rules(
            base_rules=rules.editor.text,
            mandatory_seed_constraints=mandatory_seed_constraints,
        )
        output = _invoke_role_text(
            "batch_editing",
            chapter_number=chapter_number,
            stage_name="edit",
            system_rules=editor_rules,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )
        _emit_chapter_progress(
            chapter_number,
            f"Editing scene {scene_number}/3 complete ({_word_count(output)} words)",
        )
        return output

    def _retry_draft(
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
        repair_block = ""
        if repair_directive:
            repair_block = f"\n{repair_directive.strip()}"
        retry_prompt = pipeline.build_drafter_user_prompt(
            user_input=(
                f"Retry draft for chapter {chapter_number} scene {scene_number}. "
                "Address prior coherence issues and preserve directive fidelity. "
                "The final beat must land the approved outcome exactly."
                f"{repair_block}\n"
                f"{grounding}"
            ),
            directive=directive,
        )
        drafter_rules = _compose_stage_system_rules(
            base_rules=rules.drafter.text,
            mandatory_seed_constraints=mandatory_seed_constraints,
            repair_directive=(
                repair_directive
                if repair_directive and repair_in_system_prompt
                else None
            ),
        )
        return _invoke_role_text(
            "batch_prose",
            chapter_number=chapter_number,
            stage_name="draft_retry",
            system_rules=drafter_rules,
            prompt=retry_prompt,
            fallback_llm=assistant.llm,
        )

    def _stitch_chapter(edited_scenes: list[str], chapter_number: int) -> str:
        _emit_chapter_progress(chapter_number, "Stitching started...")
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
        stitch_rules = _compose_stage_system_rules(
            base_rules=rules.stitcher.text,
            mandatory_seed_constraints=mandatory_seed_constraints,
        )
        output = _invoke_role_text(
            "batch_editing",
            chapter_number=chapter_number,
            stage_name="stitch",
            system_rules=stitch_rules,
            prompt=prompt,
            fallback_llm=assistant.llm,
        )
        _emit_chapter_progress(
            chapter_number,
            f"Stitching complete ({_word_count(output)} words)",
        )
        return output

    def _derive_state_update(chapter_text: str, chapter_number: int) -> dict[str, Any]:
        _emit_chapter_progress(chapter_number, "State extraction started...")
        try:
            snapshot = state_store.load()
        except StateValidationError as exc:
            raise BookEngineError(f"Narrative state load failed: {exc}") from exc

        def _invoke_extraction_role(prompt: str) -> str:
            return _invoke_role_text(
                "repair_json",
                chapter_number=chapter_number,
                stage_name="state_extract",
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
        state_update = {
            "chapter_text": chapter_text,
            "chapter_number": chapter_number,
            "patch": extraction.patch,
            "events": extraction.events,
            "snapshot": snapshot,
        }
        patch_operations = len(getattr(extraction.patch, "operations", []))
        _emit_chapter_progress(
            chapter_number,
            f"State extraction complete ({patch_operations} patch ops)",
        )
        return state_update

    def _commit_state_update(update: dict[str, Any], chapter_number: int) -> None:
        path_config = (
            runtime_config if getattr(runtime_config, "book_path", None) else None
        )
        project_paths = resolve_project_paths(book_path, config=path_config)

        state_file = project_paths.root / "outline" / "narrative_state.json"
        canon_file = project_paths.root / "outline" / "canon.yml"
        audit_file = project_paths.root / "outline" / "narrative_audit.jsonl"
        chapter_file = project_paths.root / "chapters" / f"chapter-{chapter_number}.md"

        state_before_exists = state_file.exists()
        canon_before_exists = canon_file.exists()
        audit_before_exists = audit_file.exists()
        chapter_before_exists = chapter_file.exists()
        state_before = (
            state_file.read_text(encoding="utf-8") if state_before_exists else None
        )
        canon_before = (
            canon_file.read_text(encoding="utf-8") if canon_before_exists else None
        )
        audit_before = (
            audit_file.read_text(encoding="utf-8") if audit_before_exists else None
        )
        chapter_before = (
            chapter_file.read_text(encoding="utf-8") if chapter_before_exists else None
        )
        wrote_state = False
        wrote_canon = False
        wrote_audit = False
        wrote_chapter = False
        audit_requested = False

        def _restore_file(path: Path, content: str | None, existed: bool) -> None:
            if existed:
                _write_text_with_fsync(path, content or "")
                return
            if path.exists():
                path.unlink()

        patch = update["patch"]
        try:
            chapter_file.parent.mkdir(parents=True, exist_ok=True)
            _write_text_with_fsync(
                chapter_file,
                str(update["chapter_text"]).strip() + "\n",
            )
            wrote_chapter = True

            try:
                snapshot = state_store.apply_patch(
                    patch,
                    actor="book-engine",
                    write_audit=True,
                )
                audit_requested = True
            except TypeError:
                snapshot = state_store.apply_patch(patch, actor="book-engine")
            if snapshot is None and hasattr(state_store, "load"):
                snapshot = state_store.load()
            if not state_file.exists() and snapshot is not None:
                _write_text_with_fsync(
                    state_file,
                    json.dumps(_jsonable(snapshot), ensure_ascii=True, indent=2) + "\n",
                )
            wrote_state = True
            wrote_audit = audit_file.exists()
            _persist_canon_ledger(
                book_path=book_path,
                chapter_number=chapter_number,
                snapshot=snapshot,
                events=list(update.get("events", [])),
            )
            wrote_canon = True

            if not state_file.exists():
                raise RuntimeError("state_persist_missing:narrative_state.json")
            if not canon_file.exists():
                raise RuntimeError("canon_persist_missing:canon.yml")
            if audit_requested and not audit_file.exists():
                raise RuntimeError("audit_persist_missing:narrative_audit.jsonl")
        except Exception as exc:
            # Roll back all touched commit artifacts to avoid partial persistence.
            try:
                if wrote_chapter or chapter_file.exists():
                    _restore_file(chapter_file, chapter_before, chapter_before_exists)
                if wrote_canon or canon_file.exists():
                    _restore_file(canon_file, canon_before, canon_before_exists)
                if wrote_audit or audit_file.exists():
                    _restore_file(audit_file, audit_before, audit_before_exists)
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
        if chapter_number in canonical_conflicts_by_chapter:
            return (
                False,
                "canon_fact_conflict: "
                + canonical_conflicts_by_chapter[chapter_number],
            )
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
                "CRITICAL: You are a Continuity Guard, NOT a literary critic. DO NOT fail the chapter for subjective stylistic reasons like 'pacing', 'show don't tell', or 'feeling like a setup'. ONLY mark FAIL if there is a HARD logical impossibility, a resurrected character, or a direct contradiction of the Canon Facts.",
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
            _emit_chapter_progress(chapter_number, "Coherence review started...")
            raw = _invoke_role_text(
                "coherence_check",
                chapter_number=chapter_number,
                stage_name="coherence_review",
                system_rules=rules.editor.text,
                prompt=prompt,
                fallback_llm=semantic_reviewer_llm,
            )
            payload = json.loads(_extract_json_object(raw))
            status = str(payload.get("status", "")).strip().upper()
            if status == "PASS":
                _emit_chapter_progress(chapter_number, "Coherence review PASS")
                return True, str(payload.get("reason", "pass")).strip() or "pass"
            if status == "FAIL":
                reason = str(payload.get("reason", "unspecified_violation")).strip()
                _emit_chapter_progress(chapter_number, "Coherence review FAIL")
                return False, reason or "unspecified_violation"
            _emit_chapter_progress(chapter_number, "Coherence review FAIL")
            return False, f"coherence_invalid_status:{status or 'missing'}"
        except Exception as exc:
            _emit_chapter_progress(chapter_number, "Coherence review FAIL")
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
        chapter_number = int(update.get("chapter_number", 0) or 0)
        if not chapter_text or snapshot is None:
            return False

        try:
            canon_data = load_canon(book_path)
            canon_root = (
                canon_data.get("canon", {}) if isinstance(canon_data, dict) else {}
            )
            previous_facts = (
                canon_root.get("facts", {}) if isinstance(canon_root, dict) else {}
            )
            current_facts = extract_structured_facts(snapshot)
            conflicts = validate_fact_consistency(
                previous_facts=(
                    previous_facts if isinstance(previous_facts, dict) else {}
                ),
                new_facts=current_facts,
            )
            if conflicts:
                reason = " | ".join(conflicts)
                canonical_conflicts_by_chapter[chapter_number] = reason
                _emit_chapter_progress(
                    chapter_number,
                    f"canon_fact_conflict: {reason}",
                )
                return True
        except Exception:
            if strict_coherence_guard:
                return True

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
                chapter_number=update.get("chapter_number", 0) or 0,
                stage_name="canon_violation_check",
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

        def _is_reviewer_transport_error(reason: str) -> bool:
            lowered = str(reason).strip().lower()
            return any(
                token in lowered
                for token in (
                    "reviewer_invalid_response",
                    "reviewer_empty_output",
                    "reviewer_transport_error",
                    "openrouter request failed without an explicit exception",
                    "model invocation failed",
                    "rate-limited",
                    "error code: 429",
                    "error code: 500",
                    "error code: 502",
                    "error code: 503",
                    "error code: 504",
                    "bad gateway",
                    "service unavailable",
                    "gateway timeout",
                    "empty response",
                )
            )

        if semantic_reviewer_llm is None:
            return True, None
        _emit_chapter_progress(chapter_number, "Semantic review started...")

        canon_data = load_canon(book_path)
        canon_payload = json.dumps(canon_data, ensure_ascii=True)
        try:
            state_payload = json.dumps(_jsonable(state_store.load()), ensure_ascii=True)
        except Exception:
            state_payload = "{}"
        prompt = "\n".join(
            [
                f"Chapter: {chapter_number}",
                "Seed:",
                seed_text.strip(),
                "Approved Scene Plan:",
                outline_text.strip(),
                "Canon Facts JSON:",
                canon_payload,
                "Narrative State JSON:",
                state_payload,
                "Generated Chapter:",
                chapter_text.strip(),
                "Return JSON only.",
            ]
        )

        class _SemanticReviewTransportRetry(RuntimeError):
            """Retryable transport-level semantic reviewer failure."""

        class _SemanticReviewFatal(RuntimeError):
            """Non-retryable semantic reviewer failure."""

        def _log_semantic_retry(retry_state: Any) -> None:
            reason = ""
            outcome = getattr(retry_state, "outcome", None)
            if outcome is not None and hasattr(outcome, "exception"):
                exc = outcome.exception()
                if exc is not None:
                    reason = str(exc)
            _emit_chapter_progress(
                chapter_number,
                "Semantic review transport retry "
                f"{getattr(retry_state, 'attempt_number', 0)}/3: {reason or 'unknown'}",
            )

        attempt_counter = {"count": 0}

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=8),
            retry=retry_if_exception_type(_SemanticReviewTransportRetry),
            before_sleep=_log_semantic_retry,
            reraise=True,
        )
        def _invoke_semantic_payload() -> dict[str, Any]:
            attempt_counter["count"] += 1
            telemetry["semantic_reviews_run"] += 1
            try:
                raw = _invoke_role_text(
                    "coherence_check",
                    chapter_number=chapter_number,
                    stage_name="semantic_review",
                    system_rules=reviewer_rules,
                    prompt=prompt,
                    fallback_llm=semantic_reviewer_llm,
                )
                if not str(raw).strip():
                    raise RuntimeError("reviewer_empty_output")
                parsed = json.loads(_extract_json_object(raw))
                if not isinstance(parsed, dict):
                    raise RuntimeError("reviewer_invalid_response:payload_not_object")
                return parsed
            except Exception as exc:
                reason = f"reviewer_invalid_response:{exc}"
                if not _is_reviewer_transport_error(reason):
                    raise _SemanticReviewFatal(reason) from exc

                if provider_name == "openrouter":
                    _rotate_role_model(
                        "coherence_check",
                        reason=reason,
                        chapter_number=chapter_number,
                        attempt=attempt_counter["count"],
                    )
                raise _SemanticReviewTransportRetry(reason) from exc

        try:
            payload = _invoke_semantic_payload()
        except _SemanticReviewFatal as exc:
            _emit_chapter_progress(chapter_number, "Semantic review FAIL")
            return False, str(exc)
        except _SemanticReviewTransportRetry as exc:
            _emit_chapter_progress(chapter_number, "Semantic review FAIL")
            return False, str(exc)

        if payload is None:
            _emit_chapter_progress(chapter_number, "Semantic review FAIL")
            return False, "reviewer_transport_error:review payload missing"

        status = str(payload.get("status", "")).strip().upper()
        if status == "PASS":
            _emit_chapter_progress(chapter_number, "Semantic review PASS")
            return True, None
        if status == "FAIL":
            reason = str(payload.get("reason", "unspecified_violation")).strip()
            _emit_chapter_progress(chapter_number, "Semantic review FAIL")
            return False, reason or "unspecified_violation"
        _emit_chapter_progress(chapter_number, "Semantic review FAIL")
        return False, f"reviewer_invalid_status:{status or 'missing'}"

    def _persist_generation_failure(
        chapter_number: int,
        attempt: int,
        reason: str,
        text: str,
    ) -> None:
        """Persist rejected chapter attempts for post-mortem debugging."""

        _record_raw_output(chapter_number, "stitch", text)
        latest_transport = latest_transport_error_by_chapter.get(chapter_number)
        if latest_transport is not None:
            attempt_transport_errors[
                (chapter_number, max(1, attempt))
            ] = latest_transport
        _persist_retry_stage_artifacts(
            chapter_number=chapter_number,
            attempt=attempt,
            reason=reason,
        )

        packet_dir = _chapter_packet_dir(book_path, runtime_config, chapter_number)
        failures_dir = packet_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        failure_file = failures_dir / f"attempt-{max(1, attempt)}.txt"
        _write_text_with_fsync(
            failure_file,
            (
                f"chapter={chapter_number}\n"
                f"attempt={attempt}\n"
                f"reason={reason}\n\n"
                f"{str(text).strip()}\n"
            ),
        )

    def _persist_coherence_failure(
        chapter_number: int,
        gate_reason: str,
        stitched_text: str,
    ) -> None:
        """Persist last stitched chapter on coherence-gate hard failures."""

        packet_dir = _chapter_packet_dir(book_path, runtime_config, chapter_number)
        failures_dir = packet_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        failure_file = failures_dir / "coherence_fail_last_attempt.txt"
        _record_raw_output(chapter_number, "coherence_review", stitched_text)
        _persist_retry_stage_artifacts(
            chapter_number=chapter_number,
            attempt=1,
            reason=f"coherence_gate:{gate_reason}",
        )
        _write_text_with_fsync(
            failure_file,
            (
                f"Coherence gate failed: {str(gate_reason).strip() or 'unspecified'}\n\n"
                f"{str(stitched_text).strip()}\n"
            ),
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
        persist_coherence_failure=_persist_coherence_failure,
        persist_blackbox=_persist_chapter_failure_blackbox,
        on_scene_generation_retry=_on_scene_generation_retry,
        on_chapter_validation_retry=_on_chapter_validation_retry,
        on_coherence_repair_retry=_on_coherence_repair_retry,
        repair_scene_directive=_repair_scene_directive,
        resolve_character_ledger_names=_resolve_character_ledger_names,
        max_scene_generation_attempts=3,
        # Enforce meaningful state updates for all real-provider runs.
        enforce_state_signal_guard=strict_provider,
        enforce_coherence_each_chapter=strict_autonomous,
        require_severe_canon_check=strict_autonomous,
        enforce_scene_structure_contract=strict_provider,
        enforce_plot_omission_guard=strict_autonomous,
        coherence_interval=1 if strict_autonomous else 5,
    )

    status = engine.start(seed_markdown=seed_text, target_chapters=chapters)
    coherence_reviews_run = 0
    patch_operations_applied = 0
    chapter_packet_dirs: dict[int, Path] = {}
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
                "terminal_truncation",
                "insufficient_expansion",
                "missing_pov",
                "acceptance contract",
                "stage validator contract",
            )
        ):
            return "Completeness"
        return "unknown"

    def _persist_halt_artifacts() -> None:
        """Best-effort persistence of baseline state/canon/audit on fail-closed halts."""

        path_config = (
            runtime_config if getattr(runtime_config, "book_path", None) else None
        )
        project_paths = resolve_project_paths(book_path, config=path_config)
        outline_dir = project_paths.root / "outline"
        outline_dir.mkdir(parents=True, exist_ok=True)

        state_file = outline_dir / "narrative_state.json"
        canon_file = outline_dir / "canon.yml"
        audit_file = outline_dir / "narrative_audit.jsonl"
        halt_outline_file = outline_dir / "halt_outline.md"
        halt_diagnostics_file = outline_dir / "halt_diagnostics.json"

        if not state_file.exists():
            try:
                fallback_snapshot = _jsonable(state_store.load())
            except Exception:
                fallback_snapshot = {
                    "characters": {},
                    "relationships": [],
                    "locations": {},
                    "world_facts": [],
                    "plot_threads": [],
                    "world": {},
                    "version": 1,
                }
            _write_text_with_fsync(
                state_file,
                json.dumps(fallback_snapshot, ensure_ascii=True, indent=2) + "\n",
            )

        if not canon_file.exists():
            save_canon(
                book_path,
                {
                    "canon": {
                        "facts": {},
                        "updated_at": _utc_now_iso(),
                        "chapter": max(0, len(engine.history)),
                    },
                    "chapters": {},
                },
            )

        if not audit_file.exists():
            _write_text_with_fsync(
                audit_file,
                json.dumps(
                    {
                        "timestamp": _utc_now_iso(),
                        "actor": "book-engine-fallback",
                        "event": "pipeline_halt",
                        "chapter": max(1, engine.current_chapter),
                        "error": run_error or "<unknown>",
                    },
                    ensure_ascii=True,
                )
                + "\n",
            )

        if status.pending_outline:
            _write_text_with_fsync(
                halt_outline_file,
                str(status.pending_outline).strip() + "\n",
            )

        _write_text_with_fsync(
            halt_diagnostics_file,
            json.dumps(
                {
                    "run_id": run_id,
                    "status": run_status,
                    "failed_guard": failed_guard,
                    "error": run_error or "<unknown>",
                    "chapter": max(1, engine.current_chapter),
                    "provider": provider_name or "unknown",
                    "generated_chapters": len(engine.history),
                },
                ensure_ascii=True,
                indent=2,
            )
            + "\n",
        )

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
                _emit_chapter_progress(
                    pending.chapter_number,
                    "Chapter validation started...",
                )
                update = pending.state_update
                patch = update.get("patch")
                operation_count = len(getattr(patch, "operations", []))
                patch_operations_applied += operation_count

                console.print(
                    f"[bold cyan]Chapter {pending.chapter_number} Draft Ready (pending state commit)[/bold cyan]"
                )
                console.print(f"Patch operations: {operation_count}")
                diagnostics = pending.generation_diagnostics or {}
                diagnostics["provider"] = provider_name
                diagnostics["chapter"] = pending.chapter_number
                diagnostics["model_invocations"] = model_invocations_by_chapter.get(
                    pending.chapter_number,
                    [],
                )
                diagnostics["raw_stage_outputs_present"] = sorted(
                    list(
                        raw_stage_outputs_by_chapter.get(
                            pending.chapter_number,
                            {},
                        ).keys()
                    )
                )
                diagnostics["transport_errors"] = transport_errors_by_chapter.get(
                    pending.chapter_number,
                    [],
                )
                diagnostics["quarantine_decisions"] = quarantine_events_by_chapter.get(
                    pending.chapter_number, []
                )
                if pending.chapter_number in canonical_conflicts_by_chapter:
                    diagnostics["canon_fact_conflict"] = canonical_conflicts_by_chapter[
                        pending.chapter_number
                    ]
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
                    diagnostics=diagnostics,
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
                _emit_chapter_progress(
                    pending.chapter_number,
                    "Chapter validation complete (PASS)",
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
                        raw_payloads=raw_stage_outputs_by_chapter.get(
                            pending.chapter_number,
                            {},
                        ),
                        transport_errors=transport_errors_by_chapter.get(
                            pending.chapter_number,
                            [],
                        ),
                        quarantine_decisions=quarantine_events_by_chapter.get(
                            pending.chapter_number,
                            [],
                        ),
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
                _emit_chapter_progress(
                    pending.chapter_number,
                    "Canon/state/chapter commit started...",
                )
                status = engine.approve_state_commit(approved=approved)
                _emit_chapter_progress(
                    pending.chapter_number,
                    "Canon/state/chapter commit complete",
                )

                packet_dir = chapter_packet_dirs.get(pending.chapter_number)
                if packet_dir is not None:
                    try:
                        _finalize_packet_after_commit(
                            book_path=book_path,
                            config=runtime_config,
                            chapter_number=pending.chapter_number,
                            packet_dir=packet_dir,
                        )
                        _assert_packet_integrity(packet_dir)
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
                        "transport_errors": diagnostics.get("transport_errors", []),
                        "quarantine_decisions": diagnostics.get(
                            "quarantine_decisions", []
                        ),
                        "model_diagnostics": _summarize_model_diagnostics(diagnostics),
                    }
                )
                continue

            raise BookEngineError(f"Unexpected engine stage: {status.stage}")

        run_status = "succeeded"
        _print_final_run_summary("succeeded")
        elapsed = time.monotonic() - run_started
        return BookRunSummary(
            chapters_generated=len(engine.history),
            coherence_reviews_run=coherence_reviews_run,
            patch_operations_applied=patch_operations_applied,
            chapters_attempted=chapters,
            retries=telemetry["retries"],
            escalations=telemetry["escalations"],
            semantic_reviews_run=telemetry["semantic_reviews_run"],
            elapsed_seconds=elapsed,
            final_status="succeeded",
        )
    except Exception as exc:
        run_error = str(exc)
        failed_guard = _classify_failed_guard(run_error)
        raise
    finally:
        if run_status != "succeeded":
            _BOOK_LOGGER.error(
                "final_guard_trip",
                run_id=run_id,
                guard=failed_guard,
                error=run_error or "<none>",
            )
            try:
                _persist_halt_artifacts()
            except Exception as exc:
                _BOOK_LOGGER.error(
                    "halt_artifact_persist_failed",
                    run_id=run_id,
                    error=str(exc),
                )
            _print_final_run_summary("failed")
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
    console.print(f"Retries: {summary.retries}")
    console.print(f"Escalations: {summary.escalations}")
    console.print(f"Semantic reviews run: {summary.semantic_reviews_run}")
    console.print(f"Elapsed seconds: {summary.elapsed_seconds:.1f}")
