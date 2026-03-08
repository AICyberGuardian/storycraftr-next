"""
DSVL Phase 1B: State Diff Engine

Computes deterministic diffs between NarrativeStateSnapshot instances.
Tracks field-level changes across characters, locations, and plot threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from storycraftr.agent.narrative_state import NarrativeStateSnapshot


class DiffType(Enum):
    """Type of change detected in a diff."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class FieldDiff:
    """Represents a single field-level change."""

    field_name: str
    old_value: Any
    new_value: Any
    diff_type: DiffType


@dataclass(frozen=True)
class EntityDiff:
    """Represents changes to a single entity (character, location, or plot thread)."""

    entity_type: str  # "character", "location", "plot_thread"
    entity_id: str
    diff_type: DiffType
    field_diffs: tuple[FieldDiff, ...] = field(default_factory=tuple)

    def has_changes(self) -> bool:
        """Return True if this entity has any field-level changes."""
        return self.diff_type != DiffType.UNCHANGED


@dataclass(frozen=True)
class StateChangeset:
    """Collection of all changes between two states."""

    character_diffs: tuple[EntityDiff, ...]
    location_diffs: tuple[EntityDiff, ...]
    plot_thread_diffs: tuple[EntityDiff, ...]
    world_changed: bool

    def has_changes(self) -> bool:
        """Return True if any entities changed."""
        return (
            any(d.has_changes() for d in self.character_diffs)
            or any(d.has_changes() for d in self.location_diffs)
            or any(d.has_changes() for d in self.plot_thread_diffs)
            or self.world_changed
        )

    def count_changes(self) -> int:
        """Return total number of entity changes."""
        return sum(
            1
            for diff_list in [
                self.character_diffs,
                self.location_diffs,
                self.plot_thread_diffs,
            ]
            for d in diff_list
            if d.has_changes()
        )


def _compute_field_diffs(
    old_entity: dict[str, Any], new_entity: dict[str, Any]
) -> tuple[FieldDiff, ...]:
    """Compute field-level diffs between two entity dicts."""
    all_fields = set(old_entity.keys()) | set(new_entity.keys())
    field_diffs = []

    for field_name in sorted(all_fields):  # Sort for deterministic ordering
        old_value = old_entity.get(field_name)
        new_value = new_entity.get(field_name)

        if old_value != new_value:
            # Determine diff type
            if field_name not in old_entity:
                diff_type = DiffType.ADDED
            elif field_name not in new_entity:
                diff_type = DiffType.REMOVED
            else:
                diff_type = DiffType.MODIFIED

            field_diffs.append(
                FieldDiff(
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                    diff_type=diff_type,
                )
            )

    return tuple(field_diffs)


def _compute_entity_diffs(
    entity_type: str,
    old_entities: dict[str, Any],
    new_entities: dict[str, Any],
) -> tuple[EntityDiff, ...]:
    """Compute diffs for a single entity type (characters, locations, or plot_threads)."""
    all_ids = set(old_entities.keys()) | set(new_entities.keys())
    entity_diffs = []

    for entity_id in sorted(all_ids):  # Sort for deterministic ordering
        old_entity = old_entities.get(entity_id)
        new_entity = new_entities.get(entity_id)

        if old_entity is None and new_entity is not None:
            # Entity was added
            entity_diffs.append(
                EntityDiff(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    diff_type=DiffType.ADDED,
                    field_diffs=tuple(),
                )
            )
        elif old_entity is not None and new_entity is None:
            # Entity was removed
            entity_diffs.append(
                EntityDiff(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    diff_type=DiffType.REMOVED,
                    field_diffs=tuple(),
                )
            )
        elif old_entity is not None and new_entity is not None:
            # Entity exists in both - check for field changes
            old_dict = (
                old_entity.model_dump()
                if hasattr(old_entity, "model_dump")
                else old_entity
            )
            new_dict = (
                new_entity.model_dump()
                if hasattr(new_entity, "model_dump")
                else new_entity
            )

            field_diffs = _compute_field_diffs(old_dict, new_dict)

            if field_diffs:
                entity_diffs.append(
                    EntityDiff(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        diff_type=DiffType.MODIFIED,
                        field_diffs=field_diffs,
                    )
                )
            else:
                entity_diffs.append(
                    EntityDiff(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        diff_type=DiffType.UNCHANGED,
                        field_diffs=tuple(),
                    )
                )

    return tuple(entity_diffs)


def compute_state_diff(
    old_state: NarrativeStateSnapshot,
    new_state: NarrativeStateSnapshot,
) -> StateChangeset:
    """
    Compute deterministic diff between two narrative state snapshots.

    Returns a StateChangeset containing all detected changes at the entity and field level.
    The diff is deterministic: given the same inputs, it will always produce the same output.

    Args:
        old_state: Previous state snapshot
        new_state: Current state snapshot

    Returns:
        StateChangeset with all detected changes
    """
    # Compute entity-level diffs
    character_diffs = _compute_entity_diffs(
        "character", old_state.characters, new_state.characters
    )
    location_diffs = _compute_entity_diffs(
        "location", old_state.locations, new_state.locations
    )
    plot_thread_diffs = _compute_entity_diffs(
        "plot_thread", old_state.plot_threads, new_state.plot_threads
    )

    # Check if world dict changed
    world_changed = old_state.world != new_state.world

    return StateChangeset(
        character_diffs=character_diffs,
        location_diffs=location_diffs,
        plot_thread_diffs=plot_thread_diffs,
        world_changed=world_changed,
    )
