from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from storycraftr.agent.narrative_state import (
    NarrativeStateSnapshot,
    PatchOperation,
    StatePatch,
)


@dataclass(frozen=True)
class ExtractionEvent:
    """One deterministic extraction event derived from prose."""

    kind: str
    character_id: str
    details: str


@dataclass(frozen=True)
class StateExtractionResult:
    """Extractor output containing patch proposal and traceable events."""

    patch: StatePatch
    events: list[ExtractionEvent]


_ENTER_PATTERNS = (
    re.compile(
        r"\b(?P<name>[A-Z][A-Za-z]+)\s+entered\s+(?:the\s+)?(?P<location>[A-Za-z][A-Za-z\- ]+)"
    ),
    re.compile(
        r"\b(?P<name>[A-Z][A-Za-z]+)\s+(?:went|moved|walked|arrived)\s+(?:to|into|at)\s+(?:the\s+)?(?P<location>[A-Za-z][A-Za-z\- ]+)"
    ),
)
_DROP_PATTERN = re.compile(
    r"\b(?P<name>[A-Z][A-Za-z]+)\s+(?:dropped|discarded|set down)\s+(?:(?:his|her|their)\s+)?(?P<item>[A-Za-z][A-Za-z\- ]+)"
)
_MAX_STRUCTURED_ATTEMPTS = 3
_MIN_VALIDATED_CHAPTER_WORDS = 800


def _to_entity_id(raw: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower())
    return normalized.strip("_")


def _to_display_name(raw: str) -> str:
    words = [part for part in raw.strip().split() if part]
    return " ".join(word.capitalize() for word in words)


def _clean_tail(raw: str) -> str:
    return raw.strip().rstrip(".,;:!?")


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        return stripped[first : last + 1]
    raise ValueError("No JSON object found in extraction payload")


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _merge_inventory(
    *,
    base_inventory: list[str],
    add_items: list[str],
    remove_items: list[str],
) -> list[str]:
    merged = [item for item in base_inventory if item not in remove_items]
    for item in add_items:
        if item not in merged:
            merged.append(item)
    return merged


def _extract_with_structured_role(
    text: str,
    *,
    snapshot: NarrativeStateSnapshot,
    chapter_number: int,
    invoke_json_role: Callable[[str], str],
) -> StateExtractionResult:
    existing_characters = {
        key.lower(): character for key, character in snapshot.characters.items()
    }
    existing_locations = {
        key.lower(): location for key, location in snapshot.locations.items()
    }
    existing_threads = {thread.id: thread for thread in snapshot.plot_threads}

    snapshot_payload = {
        "characters": {
            key: {
                "name": value.name,
                "location": value.location,
                "status": value.status,
                "inventory": list(value.inventory),
            }
            for key, value in snapshot.characters.items()
        },
        "locations": {
            key: {
                "name": value.name,
                "status": value.status,
                "description": value.description,
            }
            for key, value in snapshot.locations.items()
        },
        "plot_threads": [thread.model_dump() for thread in snapshot.plot_threads],
    }

    prompt = "\n".join(
        [
            "Extract narrative state deltas from chapter prose.",
            "Return strict JSON object only with keys:",
            "character_deltas, relationship_changes, world_facts, thread_changes.",
            "Use arrays for all keys; use empty arrays when nothing is found.",
            "character_deltas item fields:",
            "id, name, location, status, role, notes, inventory_add, inventory_remove.",
            "relationship_changes item fields: character_id, details.",
            "world_facts item fields: location_id, location_name, description.",
            "thread_changes item fields: id, action(open|close), description, resolved_chapter.",
            "Existing state JSON:",
            json.dumps(snapshot_payload, ensure_ascii=True),
            "Chapter text:",
            text,
        ]
    )

    last_error: str | None = None
    payload: dict[str, Any] | None = None
    for attempt in range(1, _MAX_STRUCTURED_ATTEMPTS + 1):
        raw = invoke_json_role(prompt)
        try:
            candidate = json.loads(_extract_json_object(raw))
            if not isinstance(candidate, dict):
                raise ValueError("Extraction payload must be a JSON object")
            required = {
                "character_deltas",
                "relationship_changes",
                "world_facts",
                "thread_changes",
            }
            missing = sorted(required - set(candidate.keys()))
            if missing:
                raise ValueError(f"Extraction payload missing keys: {missing}")
            payload = candidate
            break
        except Exception as exc:
            last_error = str(exc)
            if attempt == _MAX_STRUCTURED_ATTEMPTS:
                break
            prompt = "\n".join(
                [
                    "Repair the previous extraction into valid strict JSON.",
                    "Do not add prose or markdown.",
                    "Required top-level keys:",
                    "character_deltas, relationship_changes, world_facts, thread_changes.",
                    f"Previous error: {last_error}",
                    "Previous output:",
                    raw,
                ]
            )

    if payload is None:
        raise RuntimeError(
            "Structured state extraction failed after repair attempts: "
            f"{last_error or 'unknown_error'}"
        )

    added_locations: dict[str, dict[str, Any]] = {}
    added_characters: dict[str, dict[str, Any]] = {}
    updated_characters: dict[str, dict[str, Any]] = {}
    added_threads: dict[str, dict[str, Any]] = {}
    updated_threads: dict[str, dict[str, Any]] = {}
    events: list[ExtractionEvent] = []

    for item in _coerce_list(payload.get("character_deltas")):
        if not isinstance(item, dict):
            continue
        raw_name = _clean_tail(str(item.get("name", "")))
        raw_id = _clean_tail(str(item.get("id", "")))
        character_id = _to_entity_id(raw_id or raw_name)
        if not character_id:
            continue

        location_id = _to_entity_id(str(item.get("location", "")))
        status = str(item.get("status", "")).strip().lower()
        role = str(item.get("role", "")).strip()
        notes = str(item.get("notes", "")).strip()
        inventory_add = [
            str(value).strip().lower()
            for value in _coerce_list(item.get("inventory_add"))
            if str(value).strip()
        ]
        inventory_remove = [
            str(value).strip().lower()
            for value in _coerce_list(item.get("inventory_remove"))
            if str(value).strip()
        ]

        location_exists_now = bool(location_id and location_id in existing_locations)
        if location_id and (
            location_id not in existing_locations and location_id not in added_locations
        ):
            added_locations[location_id] = {"name": _to_display_name(location_id)}

        if character_id in existing_characters:
            base = existing_characters[character_id]
            merged: dict[str, Any] = dict(updated_characters.get(character_id, {}))
            if location_exists_now:
                merged["location"] = location_id
            if status in {"alive", "injured", "dead", "unknown"}:
                merged["status"] = status
            if role:
                merged["role"] = role
            if notes:
                existing_notes = str(merged.get("notes", base.notes or "")).strip()
                merged["notes"] = (
                    f"{existing_notes}; {notes}" if existing_notes else notes
                )
            if inventory_add or inventory_remove:
                base_inventory = list(merged.get("inventory", list(base.inventory)))
                merged["inventory"] = _merge_inventory(
                    base_inventory=base_inventory,
                    add_items=inventory_add,
                    remove_items=inventory_remove,
                )
            if merged:
                updated_characters[character_id] = merged
        else:
            added_data: dict[str, Any] = {
                "name": _to_display_name(raw_name or character_id),
            }
            if location_exists_now:
                added_data["location"] = location_id
            if status in {"alive", "injured", "dead", "unknown"}:
                added_data["status"] = status
            if role:
                added_data["role"] = role
            if notes:
                added_data["notes"] = notes
            if inventory_add:
                added_data["inventory"] = inventory_add
            added_characters[character_id] = added_data

        events.append(
            ExtractionEvent(
                kind="character_delta",
                character_id=character_id,
                details=(
                    "location="
                    f"{location_id or '-'}; status={status or '-'}; role={role or '-'}"
                ),
            )
        )

    for item in _coerce_list(payload.get("relationship_changes")):
        if not isinstance(item, dict):
            continue
        character_id = _to_entity_id(str(item.get("character_id", "")))
        details = str(item.get("details", "")).strip()
        if not character_id or not details:
            continue

        relationship_note = f"relationship: {details}"
        if character_id in added_characters:
            existing_notes = str(
                added_characters[character_id].get("notes", "")
            ).strip()
            added_characters[character_id]["notes"] = (
                f"{existing_notes}; {relationship_note}"
                if existing_notes
                else relationship_note
            )
        elif character_id in existing_characters:
            target = dict(updated_characters.get(character_id, {}))
            existing_notes = str(target.get("notes", "")).strip()
            target["notes"] = (
                f"{existing_notes}; {relationship_note}"
                if existing_notes
                else relationship_note
            )
            updated_characters[character_id] = target
        else:
            continue
        events.append(
            ExtractionEvent(
                kind="relationship_change",
                character_id=character_id,
                details=details,
            )
        )

    for item in _coerce_list(payload.get("world_facts")):
        if not isinstance(item, dict):
            continue
        location_id = _to_entity_id(str(item.get("location_id", "")))
        description = str(item.get("description", "")).strip()
        if not location_id or not description:
            continue

        location_name = str(item.get("location_name", "")).strip()
        if location_id in existing_locations:
            existing_description = existing_locations[location_id].description
            merged_description = (
                f"{existing_description}; {description}"
                if existing_description
                else description
            )
            added_locations.setdefault(
                location_id, {"name": existing_locations[location_id].name}
            )
            added_locations[location_id]["description"] = merged_description
        else:
            added_locations[location_id] = {
                "name": location_name or _to_display_name(location_id),
                "description": description,
            }

        events.append(
            ExtractionEvent(
                kind="world_fact",
                character_id=location_id,
                details=description,
            )
        )

    for item in _coerce_list(payload.get("thread_changes")):
        if not isinstance(item, dict):
            continue
        thread_id = _to_entity_id(str(item.get("id", "")))
        action = str(item.get("action", "")).strip().lower()
        description = str(item.get("description", "")).strip()
        if not thread_id or action not in {"open", "close"}:
            continue

        if action == "open":
            thread_data = {
                "id": thread_id,
                "description": description or f"Thread {thread_id}",
                "status": "OPEN",
                "introduced_chapter": max(1, chapter_number),
                "resolved_chapter": None,
            }
            if thread_id in existing_threads:
                updated_threads[thread_id] = {
                    "description": thread_data["description"],
                    "status": "OPEN",
                    "resolved_chapter": None,
                }
            else:
                added_threads[thread_id] = thread_data
        else:
            resolved = item.get("resolved_chapter")
            resolved_chapter = (
                int(resolved)
                if isinstance(resolved, int) and resolved > 0
                else chapter_number
            )
            if thread_id in existing_threads:
                updated_threads[thread_id] = {
                    "status": "CLOSED",
                    "resolved_chapter": resolved_chapter,
                }
            else:
                added_threads[thread_id] = {
                    "id": thread_id,
                    "description": description or f"Thread {thread_id}",
                    "status": "CLOSED",
                    "introduced_chapter": max(1, chapter_number),
                    "resolved_chapter": resolved_chapter,
                }

        events.append(
            ExtractionEvent(
                kind="plot_thread",
                character_id=thread_id,
                details=f"action={action}",
            )
        )

    operations: list[PatchOperation] = []
    for location_id, data in sorted(added_locations.items()):
        op = "update" if location_id in existing_locations else "add"
        operations.append(
            PatchOperation(
                operation=op,
                entity_type="location",
                entity_id=location_id,
                data=data,
            )
        )

    for character_id, data in sorted(added_characters.items()):
        operations.append(
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id=character_id,
                data=data,
            )
        )

    for character_id, data in sorted(updated_characters.items()):
        operations.append(
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id=character_id,
                data=data,
            )
        )

    for thread_id, data in sorted(added_threads.items()):
        operations.append(
            PatchOperation(
                operation="add",
                entity_type="plot_thread",
                entity_id=thread_id,
                data=data,
            )
        )

    for thread_id, data in sorted(updated_threads.items()):
        operations.append(
            PatchOperation(
                operation="update",
                entity_type="plot_thread",
                entity_id=thread_id,
                data=data,
            )
        )

    return StateExtractionResult(
        patch=StatePatch(
            operations=operations,
            description="Structured extraction from generated prose.",
        ),
        events=events,
    )


def _extract_with_deterministic_regex(
    text: str,
    *,
    snapshot: NarrativeStateSnapshot,
) -> StateExtractionResult:
    """Extract deterministic, validation-friendly state updates from prose."""

    content = text.strip()
    if not content:
        return StateExtractionResult(patch=StatePatch(), events=[])

    existing_characters = {
        key.lower(): character for key, character in snapshot.characters.items()
    }
    existing_locations = {
        key.lower(): location for key, location in snapshot.locations.items()
    }

    added_locations: dict[str, dict[str, str]] = {}
    added_characters: dict[str, dict[str, object]] = {}
    updated_characters: dict[str, dict[str, object]] = {}
    events: list[ExtractionEvent] = []

    for sentence in re.split(r"(?<=[.!?])\s+", content):
        chunk = _clean_tail(sentence)
        if not chunk:
            continue

        for pattern in _ENTER_PATTERNS:
            match = pattern.search(chunk)
            if match is None:
                continue

            raw_name = _clean_tail(match.group("name"))
            raw_location = _clean_tail(match.group("location"))
            if not raw_name or not raw_location:
                continue

            character_id = _to_entity_id(raw_name)
            location_id = _to_entity_id(raw_location)
            if not character_id or not location_id:
                continue

            if (
                location_id not in existing_locations
                and location_id not in added_locations
            ):
                added_locations[location_id] = {"name": _to_display_name(raw_location)}

            if (
                character_id not in existing_characters
                and character_id not in added_characters
            ):
                added_characters[character_id] = {
                    "name": _to_display_name(raw_name),
                    "location": location_id,
                }
            elif character_id in existing_characters:
                existing = existing_characters[character_id]
                if existing.location != location_id:
                    update = dict(updated_characters.get(character_id, {}))
                    update["location"] = location_id
                    updated_characters[character_id] = update

            events.append(
                ExtractionEvent(
                    kind="character_location",
                    character_id=character_id,
                    details=f"location={location_id}",
                )
            )
            break

        match_drop = _DROP_PATTERN.search(chunk)
        if match_drop is None:
            continue

        raw_name = _clean_tail(match_drop.group("name"))
        raw_item = _clean_tail(match_drop.group("item"))
        character_id = _to_entity_id(raw_name)
        item = raw_item.lower()
        if not character_id or not item:
            continue

        if character_id in existing_characters:
            existing_inventory = list(existing_characters[character_id].inventory)
            merged = dict(updated_characters.get(character_id, {}))
            inventory = list(merged.get("inventory", existing_inventory))
            if item in inventory:
                inventory = [entry for entry in inventory if entry != item]
                merged["inventory"] = inventory
                updated_characters[character_id] = merged
                events.append(
                    ExtractionEvent(
                        kind="character_inventory_remove",
                        character_id=character_id,
                        details=f"item={item}",
                    )
                )

    operations: list[PatchOperation] = []

    for location_id, data in sorted(added_locations.items()):
        operations.append(
            PatchOperation(
                operation="add",
                entity_type="location",
                entity_id=location_id,
                data=data,
            )
        )

    for character_id, data in sorted(added_characters.items()):
        operations.append(
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id=character_id,
                data=data,
            )
        )

    for character_id, data in sorted(updated_characters.items()):
        operations.append(
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id=character_id,
                data=data,
            )
        )

    return StateExtractionResult(
        patch=StatePatch(
            operations=operations,
            description="Deterministic extraction from generated prose.",
        ),
        events=events,
    )


def extract_state_patch(
    text: str,
    *,
    snapshot: NarrativeStateSnapshot,
    chapter_number: int = 1,
    invoke_json_role: Callable[[str], str] | None = None,
) -> StateExtractionResult:
    """Extract structured state updates from prose with fail-closed safeguards."""

    content = text.strip()
    if not content:
        return StateExtractionResult(patch=StatePatch(), events=[])

    if invoke_json_role is not None:
        extracted = _extract_with_structured_role(
            content,
            snapshot=snapshot,
            chapter_number=chapter_number,
            invoke_json_role=invoke_json_role,
        )
    else:
        extracted = _extract_with_deterministic_regex(content, snapshot=snapshot)

    if (
        _word_count(content) >= _MIN_VALIDATED_CHAPTER_WORDS
        and not extracted.patch.operations
    ):
        raise RuntimeError(
            "State extraction returned empty patch for validated chapter text"
        )

    return extracted
