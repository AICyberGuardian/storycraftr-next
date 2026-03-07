from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from storycraftr.utils.project_lock import project_write_lock

logger = logging.getLogger(__name__)

# Import audit and diff modules (forward declarations for type hints)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storycraftr.agent.state_audit import StateAuditLog
    from storycraftr.agent.state_diff import StateChangeset


# ============================================================================
# PYDANTIC VALIDATION MODELS (DSVL Phase 1A)
# ============================================================================


class CharacterState(BaseModel):
    """Validated character state with invariant enforcement."""

    name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="", max_length=200)
    location: str | None = None
    status: Literal["alive", "injured", "dead", "unknown"] = "alive"
    inventory: list[str] = Field(default_factory=list, max_length=50)
    first_appearance_chapter: int | None = Field(None, ge=1)
    notes: str = Field(default="", max_length=1000)

    @field_validator("location")
    @classmethod
    def validate_location_not_empty(cls, v: str | None) -> str | None:
        """Reject empty location strings."""
        if v is not None and v.strip() == "":
            raise ValueError("Location cannot be empty string")
        return v

    @model_validator(mode="after")
    def validate_dead_character_constraints(self) -> CharacterState:
        """Dead characters cannot change location or gain inventory."""
        # This will be enforced during patch application
        return self


class LocationState(BaseModel):
    """Validated location state."""

    name: str = Field(min_length=1, max_length=100)
    status: Literal["normal", "damaged", "destroyed", "sealed"] = "normal"
    description: str = Field(default="", max_length=2000)
    visited_chapters: list[int] = Field(default_factory=list)

    @field_validator("visited_chapters")
    @classmethod
    def validate_chapters_ascending(cls, v: list[int]) -> list[int]:
        """Chapters should be in ascending order."""
        if v != sorted(v):
            raise ValueError("Visited chapters must be in ascending order")
        return v


class PlotThreadState(BaseModel):
    """Validated plot thread."""

    id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(min_length=1, max_length=500)
    status: Literal["open", "resolved"] = "open"
    introduced_chapter: int | None = Field(None, ge=1)
    resolved_chapter: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_resolution_logic(self) -> PlotThreadState:
        """Resolved threads must have resolved_chapter."""
        if self.status == "resolved" and self.resolved_chapter is None:
            raise ValueError("Resolved threads must have resolved_chapter")
        if self.status == "open" and self.resolved_chapter is not None:
            raise ValueError("Open threads cannot have resolved_chapter")
        return self


class NarrativeStateSnapshot(BaseModel):
    """Root narrative state with cross-entity validation."""

    characters: dict[str, CharacterState] = Field(default_factory=dict)
    locations: dict[str, LocationState] = Field(default_factory=dict)
    plot_threads: dict[str, PlotThreadState] = Field(default_factory=dict)
    world: dict[str, dict[str, Any]] = Field(default_factory=dict)  # Legacy support
    version: int = Field(default=1, ge=1)
    last_modified: str = Field(default_factory=lambda: datetime.now().isoformat())

    @model_validator(mode="after")
    def validate_cross_references(self) -> NarrativeStateSnapshot:
        """Validate character locations reference existing locations."""
        valid_locations = set(self.locations.keys())
        for char_name, char in self.characters.items():
            if char.location and char.location not in valid_locations:
                # Warning only - don't fail, but flag for review
                logger.warning(
                    f"Character {char_name} references unknown location: {char.location}"
                )
        return self


# ============================================================================
# PATCH VALIDATION & APPLICATION (DSVL Phase 1C)
# ============================================================================


class StateValidationError(Exception):
    """Raised when a state patch violates business rules."""

    pass


class PatchOperation(BaseModel):
    """Single patch operation on an entity."""

    operation: Literal["add", "update", "remove"]
    entity_type: Literal["character", "location", "plot_thread"]
    entity_id: str
    data: dict[str, Any] | None = None  # None for remove operations


class StatePatch(BaseModel):
    """Collection of operations to apply to narrative state."""

    operations: list[PatchOperation] = Field(default_factory=list)
    description: str = ""  # Human-readable description of the patch


# ============================================================================
# LEGACY SUPPORT & MIGRATION
# ============================================================================


_DEFAULT_STATE: dict[str, dict[str, dict[str, Any]]] = {
    "characters": {},
    "world": {},
}


class NarrativeStateStore:
    """JSON-backed state store for deterministic character/world constraints."""

    def __init__(self, book_path: str, enable_audit: bool = True) -> None:
        self.book_path = str(Path(book_path).resolve())
        self._file_path = Path(self.book_path) / "outline" / "narrative_state.json"
        self._audit_path = Path(self.book_path) / "outline" / "narrative_audit.jsonl"
        self._enable_audit = enable_audit
        self._audit_log: StateAuditLog | None = None

    def _get_audit_log(self) -> StateAuditLog | None:
        """Lazy-initialize audit log."""
        if not self._enable_audit:
            return None
        if self._audit_log is None:
            from storycraftr.agent.state_audit import StateAuditLog

            self._audit_log = StateAuditLog(self._audit_path)
        return self._audit_log

    def load(self) -> NarrativeStateSnapshot:
        """Return validated narrative state snapshot; empty snapshot on missing/invalid data."""

        if not self._file_path.exists():
            return NarrativeStateSnapshot()

        try:
            payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            logger.warning(f"Failed to load narrative state from {self._file_path}")
            return NarrativeStateSnapshot()

        if not isinstance(payload, dict):
            logger.warning(f"Invalid narrative state format in {self._file_path}")
            return NarrativeStateSnapshot()

        # Attempt to parse with validation
        try:
            # Try loading as validated snapshot first
            return NarrativeStateSnapshot(**payload)
        except Exception as e:
            # Fall back to legacy loading with partial validation
            logger.warning(f"Partial validation during load: {e}")
            return self._load_legacy(payload)

    def _load_legacy(self, payload: dict[str, Any]) -> NarrativeStateSnapshot:
        """Load legacy unvalidated state with best-effort validation."""

        # Load characters with validation
        characters_validated: dict[str, CharacterState] = {}
        characters_raw = payload.get("characters", {})
        if isinstance(characters_raw, dict):
            for char_name, char_data in characters_raw.items():
                if not isinstance(char_data, dict):
                    continue
                try:
                    # Ensure 'name' field is present
                    if "name" not in char_data:
                        char_data = dict(char_data)
                        char_data["name"] = char_name
                    characters_validated[char_name] = CharacterState(**char_data)
                except Exception as e:
                    logger.warning(f"Skipping invalid character {char_name}: {e}")

        # Load legacy world data (unvalidated for backward compatibility)
        world_raw = payload.get("world", {})
        world = _normalize_mapping(world_raw) if isinstance(world_raw, dict) else {}

        # Load validated locations if present
        locations_validated: dict[str, LocationState] = {}
        locations_raw = payload.get("locations", {})
        if isinstance(locations_raw, dict):
            for loc_name, loc_data in locations_raw.items():
                if not isinstance(loc_data, dict):
                    continue
                try:
                    if "name" not in loc_data:
                        loc_data = dict(loc_data)
                        loc_data["name"] = loc_name
                    locations_validated[loc_name] = LocationState(**loc_data)
                except Exception as e:
                    logger.warning(f"Skipping invalid location {loc_name}: {e}")

        # Load validated plot threads if present
        plot_threads_validated: dict[str, PlotThreadState] = {}
        plot_threads_raw = payload.get("plot_threads", {})
        if isinstance(plot_threads_raw, dict):
            for thread_id, thread_data in plot_threads_raw.items():
                if not isinstance(thread_data, dict):
                    continue
                try:
                    if "id" not in thread_data:
                        thread_data = dict(thread_data)
                        thread_data["id"] = thread_id
                    plot_threads_validated[thread_id] = PlotThreadState(**thread_data)
                except Exception as e:
                    logger.warning(f"Skipping invalid plot thread {thread_id}: {e}")

        return NarrativeStateSnapshot(
            characters=characters_validated,
            locations=locations_validated,
            plot_threads=plot_threads_validated,
            world=world,
            version=payload.get("version", 1),
            last_modified=payload.get("last_modified", datetime.now().isoformat()),
        )

    def save(self, snapshot: NarrativeStateSnapshot) -> None:
        """Persist one full snapshot under project write lock."""

        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize Pydantic models to dicts
        payload = {
            "characters": {k: v.model_dump() for k, v in snapshot.characters.items()},
            "locations": {k: v.model_dump() for k, v in snapshot.locations.items()},
            "plot_threads": {
                k: v.model_dump() for k, v in snapshot.plot_threads.items()
            },
            "world": snapshot.world,
            "version": snapshot.version,
            "last_modified": snapshot.last_modified,
        }

        with project_write_lock(self.book_path):
            self._file_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    def upsert_character(
        self, name: str, fields: dict[str, Any]
    ) -> NarrativeStateSnapshot:
        """Merge one character record with validation and persist updated snapshot."""

        key = " ".join(name.split()).strip()
        if not key:
            return self.load()

        snapshot = self.load()

        # Get existing character or create new one
        if key in snapshot.characters:
            existing_char = snapshot.characters[key]
            # Merge fields with existing
            char_data = existing_char.model_dump()
            char_data.update(_normalize_fields(fields))
        else:
            # Create new character
            char_data = _normalize_fields(fields)
            if "name" not in char_data:
                char_data["name"] = key

        try:
            # Validate and create CharacterState
            new_char = CharacterState(**char_data)
            characters = dict(snapshot.characters)
            characters[key] = new_char
            updated = NarrativeStateSnapshot(
                characters=characters,
                locations=snapshot.locations,
                plot_threads=snapshot.plot_threads,
                world=snapshot.world,
                version=snapshot.version,
            )
            self.save(updated)
            return updated
        except Exception as e:
            logger.error(f"Failed to validate character {key}: {e}")
            # Return unchanged snapshot on validation failure
            return snapshot

    def upsert_world(self, key: str, fields: dict[str, Any]) -> NarrativeStateSnapshot:
        """Merge one world record and persist updated snapshot."""

        item_key = " ".join(key.split()).strip()
        if not item_key:
            return self.load()

        snapshot = self.load()
        merged = dict(snapshot.world.get(item_key, {}))
        merged.update(_normalize_fields(fields))
        world = dict(snapshot.world)
        world[item_key] = merged
        updated = NarrativeStateSnapshot(
            characters=snapshot.characters,
            locations=snapshot.locations,
            plot_threads=snapshot.plot_threads,
            world=world,
            version=snapshot.version,
        )
        self.save(updated)
        return updated

    def render_prompt_block(self, *, max_chars: int = 2400) -> str:
        """Render strict JSON block for prompt injection with version header.

        Format:
            [Narrative State v{version} as of {timestamp}]
            {JSON payload}

        Args:
            max_chars: Maximum characters for JSON payload (header not counted)

        Returns:
            Empty string if no data, otherwise formatted block with header
        """

        snapshot = self.load()
        has_data = (
            snapshot.characters
            or snapshot.locations
            or snapshot.plot_threads
            or snapshot.world
        )
        if not has_data:
            return ""

        # Build version header
        header = (
            f"[Narrative State v{snapshot.version} as of {snapshot.last_modified}]\n"
        )

        # Serialize Pydantic models for prompt
        payload = {
            "characters": {k: v.model_dump() for k, v in snapshot.characters.items()},
            "locations": {k: v.model_dump() for k, v in snapshot.locations.items()},
            "plot_threads": {
                k: v.model_dump() for k, v in snapshot.plot_threads.items()
            },
            "world": snapshot.world,
        }

        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
        if len(raw) <= max_chars:
            return header + raw
        if max_chars <= 3:
            return header + raw[:max_chars]
        return header + raw[: max_chars - 3].rstrip() + "..."

    # ========================================================================
    # PATCH VALIDATION & APPLICATION (DSVL Phase 1C)
    # ========================================================================

    def validate_patch(self, patch: StatePatch) -> None:
        """
        Validate a state patch against business rules.

        Raises StateValidationError if any operation violates rules:
        - Dead characters cannot move (location changes rejected)
        - Cannot revive dead characters without explicit status change
        - Location references must exist
        - Cannot modify removed entities

        Args:
            patch: The patch to validate

        Raises:
            StateValidationError: If patch violates business rules
        """
        snapshot = self.load()

        for op in patch.operations:
            if op.entity_type == "character":
                self._validate_character_patch(snapshot, op)
            elif op.entity_type == "location":
                self._validate_location_patch(snapshot, op)
            elif op.entity_type == "plot_thread":
                self._validate_plot_thread_patch(snapshot, op)

    def _validate_character_patch(
        self, snapshot: NarrativeStateSnapshot, op: PatchOperation
    ) -> None:
        """Validate character-specific business rules."""
        if op.operation == "update":
            existing = snapshot.characters.get(op.entity_id)
            if existing is None:
                raise StateValidationError(
                    f"Cannot update non-existent character: {op.entity_id}"
                )

            # Dead characters cannot move
            if existing.status == "dead" and op.data:
                new_location = op.data.get("location")
                if new_location is not None and new_location != existing.location:
                    raise StateValidationError(
                        f"Dead character {op.entity_id} cannot change location "
                        f"from {existing.location} to {new_location}"
                    )

            # Validate location references exist
            if op.data and "location" in op.data:
                new_location = op.data["location"]
                if new_location and new_location not in snapshot.locations:
                    raise StateValidationError(
                        f"Character {op.entity_id} references unknown location: {new_location}"
                    )

        elif op.operation == "add":
            if op.entity_id in snapshot.characters:
                raise StateValidationError(
                    f"Cannot add existing character: {op.entity_id}"
                )

            # Validate location references for new characters
            if op.data and "location" in op.data:
                new_location = op.data["location"]
                if new_location and new_location not in snapshot.locations:
                    raise StateValidationError(
                        f"New character {op.entity_id} references unknown location: {new_location}"
                    )

    def _validate_location_patch(
        self, snapshot: NarrativeStateSnapshot, op: PatchOperation
    ) -> None:
        """Validate location-specific business rules."""
        if op.operation == "update":
            if op.entity_id not in snapshot.locations:
                raise StateValidationError(
                    f"Cannot update non-existent location: {op.entity_id}"
                )
        elif op.operation == "remove":
            # Check if any characters reference this location
            for char_id, char in snapshot.characters.items():
                if char.location == op.entity_id:
                    raise StateValidationError(
                        f"Cannot remove location {op.entity_id}: "
                        f"character {char_id} is still there"
                    )

    def _validate_plot_thread_patch(
        self, snapshot: NarrativeStateSnapshot, op: PatchOperation
    ) -> None:
        """Validate plot thread-specific business rules."""
        if op.operation == "update":
            if op.entity_id not in snapshot.plot_threads:
                raise StateValidationError(
                    f"Cannot update non-existent plot thread: {op.entity_id}"
                )

    def apply_patch(
        self, patch: StatePatch, actor: str = "system"
    ) -> NarrativeStateSnapshot:
        """
        Apply a validated patch to the narrative state.

        The patch is validated before application. If validation fails,
        the state is left unchanged.

        Args:
            patch: The patch to apply
            actor: Who/what is applying the patch (for audit trail)

        Returns:
            Updated snapshot after applying all operations

        Raises:
            StateValidationError: If patch validation fails
        """
        # Validate first
        self.validate_patch(patch)

        # Load current state (for diff computation)
        old_snapshot = self.load()

        # Apply operations
        snapshot = old_snapshot
        for op in patch.operations:
            if op.entity_type == "character":
                snapshot = self._apply_character_operation(snapshot, op)
            elif op.entity_type == "location":
                snapshot = self._apply_location_operation(snapshot, op)
            elif op.entity_type == "plot_thread":
                snapshot = self._apply_plot_thread_operation(snapshot, op)

        # Update version and timestamp
        new_snapshot = NarrativeStateSnapshot(
            characters=snapshot.characters,
            locations=snapshot.locations,
            plot_threads=snapshot.plot_threads,
            world=snapshot.world,
            version=snapshot.version + 1,
            last_modified=datetime.now().isoformat(),
        )

        # Compute diff for audit trail
        changeset: StateChangeset | None = None
        audit_log = self._get_audit_log()
        if audit_log is not None:
            from storycraftr.agent.state_diff import compute_state_diff
            from storycraftr.agent.state_audit import AuditEntry

            changeset = compute_state_diff(old_snapshot, new_snapshot)

            # Log the patch application
            entry = AuditEntry(
                timestamp=new_snapshot.last_modified,
                operation_type="patch",
                actor=actor,
                patch=patch,
                changeset=changeset,
                metadata={"version": new_snapshot.version},
            )
            audit_log.append_entry(entry)

        # Persist
        self.save(new_snapshot)
        return new_snapshot

    def _apply_character_operation(
        self, snapshot: NarrativeStateSnapshot, op: PatchOperation
    ) -> NarrativeStateSnapshot:
        """Apply a character operation."""
        characters = dict(snapshot.characters)

        if op.operation == "add":
            if op.data:
                characters[op.entity_id] = CharacterState(**op.data)
        elif op.operation == "update":
            existing = characters[op.entity_id]
            updated_data = existing.model_dump()
            if op.data:
                updated_data.update(op.data)
            characters[op.entity_id] = CharacterState(**updated_data)
        elif op.operation == "remove":
            characters.pop(op.entity_id, None)

        return NarrativeStateSnapshot(
            characters=characters,
            locations=snapshot.locations,
            plot_threads=snapshot.plot_threads,
            world=snapshot.world,
            version=snapshot.version,
        )

    def _apply_location_operation(
        self, snapshot: NarrativeStateSnapshot, op: PatchOperation
    ) -> NarrativeStateSnapshot:
        """Apply a location operation."""
        locations = dict(snapshot.locations)

        if op.operation == "add":
            if op.data:
                locations[op.entity_id] = LocationState(**op.data)
        elif op.operation == "update":
            existing = locations[op.entity_id]
            updated_data = existing.model_dump()
            if op.data:
                updated_data.update(op.data)
            locations[op.entity_id] = LocationState(**updated_data)
        elif op.operation == "remove":
            locations.pop(op.entity_id, None)

        return NarrativeStateSnapshot(
            characters=snapshot.characters,
            locations=locations,
            plot_threads=snapshot.plot_threads,
            world=snapshot.world,
            version=snapshot.version,
        )

    def _apply_plot_thread_operation(
        self, snapshot: NarrativeStateSnapshot, op: PatchOperation
    ) -> NarrativeStateSnapshot:
        """Apply a plot thread operation."""
        plot_threads = dict(snapshot.plot_threads)

        if op.operation == "add":
            if op.data:
                plot_threads[op.entity_id] = PlotThreadState(**op.data)
        elif op.operation == "update":
            existing = plot_threads[op.entity_id]
            updated_data = existing.model_dump()
            if op.data:
                updated_data.update(op.data)
            plot_threads[op.entity_id] = PlotThreadState(**updated_data)
        elif op.operation == "remove":
            plot_threads.pop(op.entity_id, None)

        return NarrativeStateSnapshot(
            characters=snapshot.characters,
            locations=snapshot.locations,
            plot_threads=plot_threads,
            world=snapshot.world,
            version=snapshot.version,
        )


def _normalize_mapping(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        cleaned_key = " ".join(str(key).split()).strip()
        if not cleaned_key:
            continue
        normalized[cleaned_key] = _normalize_fields(value)
    return normalized


def _normalize_fields(raw: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        clean_key = " ".join(str(key).split()).strip()
        if not clean_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[clean_key] = value
            continue
        if isinstance(value, list):
            cleaned_list = [
                item for item in value if isinstance(item, (str, int, float, bool))
            ]
            cleaned[clean_key] = cleaned_list
            continue
        cleaned[clean_key] = str(value)
    return cleaned
