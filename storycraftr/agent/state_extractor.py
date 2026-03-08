from __future__ import annotations

import re
from dataclasses import dataclass

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


def _to_entity_id(raw: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower())
    return normalized.strip("_")


def _to_display_name(raw: str) -> str:
    words = [part for part in raw.strip().split() if part]
    return " ".join(word.capitalize() for word in words)


def _clean_tail(raw: str) -> str:
    return raw.strip().rstrip(".,;:!?")


def extract_state_patch(
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
