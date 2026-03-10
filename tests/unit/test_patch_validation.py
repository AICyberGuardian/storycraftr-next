"""
Tests for DSVL Phase 1C: Patch Validation & Application

Validates rule-governed state transitions and business logic enforcement.
"""

from __future__ import annotations

import pytest

from storycraftr.agent.narrative_state import (
    CharacterState,
    LocationState,
    NarrativeStateSnapshot,
    NarrativeStateStore,
    PatchOperation,
    PlotThreadState,
    StatePatch,
    StateValidationError,
)

# ============================================================================
# DEAD CHARACTER MOVEMENT TESTS
# ============================================================================


def test_dead_character_cannot_move(tmp_path):
    """Dead characters cannot change location."""
    store = NarrativeStateStore(str(tmp_path))

    # Setup: create a dead character at Bridge
    initial = NarrativeStateSnapshot(
        characters={
            "Elias": CharacterState(name="Elias", status="dead", location="Bridge")
        },
        locations={
            "Bridge": LocationState(name="Bridge"),
            "Engine Room": LocationState(name="Engine Room"),
        },
    )
    store.save(initial)

    # Attempt to move dead character
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Elias",
                data={"location": "Engine Room"},
            )
        ]
    )

    with pytest.raises(StateValidationError) as exc_info:
        store.validate_patch(patch)

    assert "Dead character" in str(exc_info.value)
    assert "cannot change location" in str(exc_info.value)


def test_dead_character_can_update_non_location_fields(tmp_path):
    """Dead characters can update fields other than location."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(
        characters={
            "Elias": CharacterState(
                name="Elias", status="dead", location="Bridge", notes=""
            )
        }
    )
    store.save(initial)

    # Update notes field (not location)
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Elias",
                data={"notes": "Heroic sacrifice"},
            )
        ]
    )

    # Should not raise
    store.validate_patch(patch)
    updated = store.apply_patch(patch)

    assert updated.characters["Elias"].notes == "Heroic sacrifice"
    assert updated.characters["Elias"].status == "dead"


def test_reviving_character_with_explicit_status_allowed(tmp_path):
    """Characters can be revived if status is explicitly changed."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(
        characters={
            "Elias": CharacterState(name="Elias", status="dead", location="Bridge")
        }
    )
    store.save(initial)

    # Revive by changing status
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Elias",
                data={"status": "alive"},
            )
        ]
    )

    # Should not raise
    store.validate_patch(patch)
    updated = store.apply_patch(patch)

    assert updated.characters["Elias"].status == "alive"


# ============================================================================
# LOCATION REFERENCE VALIDATION TESTS
# ============================================================================


def test_character_location_must_exist(tmp_path):
    """Characters cannot reference non-existent locations."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(
        characters={"Elias": CharacterState(name="Elias", location="Bridge")},
        locations={"Bridge": LocationState(name="Bridge")},
    )
    store.save(initial)

    # Attempt to move to non-existent location
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Elias",
                data={"location": "Unknown Place"},
            )
        ]
    )

    with pytest.raises(StateValidationError) as exc_info:
        store.validate_patch(patch)

    assert "unknown location" in str(exc_info.value)


def test_new_character_location_must_exist(tmp_path):
    """New characters cannot reference non-existent locations."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot()
    store.save(initial)

    # Add character with non-existent location
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="Elias",
                data={"name": "Elias", "location": "Unknown Place"},
            )
        ]
    )

    with pytest.raises(StateValidationError) as exc_info:
        store.validate_patch(patch)

    assert "unknown location" in str(exc_info.value)


def test_character_can_move_to_existing_location(tmp_path):
    """Characters can move to existing locations."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(
        characters={"Elias": CharacterState(name="Elias", location="Bridge")},
        locations={
            "Bridge": LocationState(name="Bridge"),
            "Engine Room": LocationState(name="Engine Room"),
        },
    )
    store.save(initial)

    # Move to existing location
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Elias",
                data={"location": "Engine Room"},
            )
        ]
    )

    # Should not raise
    store.validate_patch(patch)
    updated = store.apply_patch(patch)

    assert updated.characters["Elias"].location == "Engine Room"


# ============================================================================
# LOCATION REMOVAL VALIDATION TESTS
# ============================================================================


def test_cannot_remove_location_with_characters(tmp_path):
    """Cannot remove locations that still have characters in them."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(
        characters={"Elias": CharacterState(name="Elias", location="Bridge")},
        locations={"Bridge": LocationState(name="Bridge")},
    )
    store.save(initial)

    # Attempt to remove location with character
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="remove",
                entity_type="location",
                entity_id="Bridge",
            )
        ]
    )

    with pytest.raises(StateValidationError) as exc_info:
        store.validate_patch(patch)

    assert "Cannot remove location" in str(exc_info.value)
    assert "character" in str(exc_info.value)


def test_can_remove_empty_location(tmp_path):
    """Can remove locations with no characters."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(locations={"Bridge": LocationState(name="Bridge")})
    store.save(initial)

    # Remove empty location
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="remove",
                entity_type="location",
                entity_id="Bridge",
            )
        ]
    )

    # Should not raise
    store.validate_patch(patch)
    updated = store.apply_patch(patch)

    assert "Bridge" not in updated.locations


# ============================================================================
# ENTITY EXISTENCE VALIDATION TESTS
# ============================================================================


def test_cannot_update_nonexistent_character(tmp_path):
    """Cannot update characters that don't exist."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot()
    store.save(initial)

    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Ghost",
                data={"status": "alive"},
            )
        ]
    )

    with pytest.raises(StateValidationError) as exc_info:
        store.validate_patch(patch)

    assert "non-existent character" in str(exc_info.value)


def test_cannot_add_duplicate_character(tmp_path):
    """Cannot add characters that already exist."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(characters={"Elias": CharacterState(name="Elias")})
    store.save(initial)

    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="Elias",
                data={"name": "Elias"},
            )
        ]
    )

    with pytest.raises(StateValidationError) as exc_info:
        store.validate_patch(patch)

    assert "existing character" in str(exc_info.value)


# ============================================================================
# PATCH APPLICATION TESTS
# ============================================================================


def test_patch_application_updates_version(tmp_path):
    """Applying a patch increments the version number."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(version=1)
    store.save(initial)

    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="Elias",
                data={"name": "Elias"},
            )
        ]
    )

    updated = store.apply_patch(patch)

    assert updated.version == 2


def test_patch_application_updates_timestamp(tmp_path):
    """Applying a patch updates the last_modified timestamp."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot()
    initial_timestamp = initial.last_modified
    store.save(initial)

    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="Elias",
                data={"name": "Elias"},
            )
        ]
    )

    updated = store.apply_patch(patch)

    assert updated.last_modified != initial_timestamp


def test_multi_operation_patch(tmp_path):
    """Multiple operations in one patch are applied atomically."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(
        characters={"Alice": CharacterState(name="Alice", status="alive")},
        locations={"Bridge": LocationState(name="Bridge")},
    )
    store.save(initial)

    # Add character, update existing, add location
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="Bob",
                data={"name": "Bob"},
            ),
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Alice",
                data={"status": "injured"},
            ),
            PatchOperation(
                operation="add",
                entity_type="location",
                entity_id="Engine Room",
                data={"name": "Engine Room"},
            ),
        ]
    )

    updated = store.apply_patch(patch)

    assert "Bob" in updated.characters
    assert updated.characters["Alice"].status == "injured"
    assert "Engine Room" in updated.locations


def test_failed_validation_leaves_state_unchanged(tmp_path):
    """If validation fails, the state is not modified."""
    store = NarrativeStateStore(str(tmp_path))

    initial = NarrativeStateSnapshot(
        characters={"Elias": CharacterState(name="Elias", status="dead")},
        version=1,
    )
    store.save(initial)

    # Invalid patch (dead character moving)
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="Elias",
                data={"location": "Bridge"},
            )
        ]
    )

    with pytest.raises(StateValidationError):
        store.apply_patch(patch)

    # State should be unchanged
    current = store.load()
    assert current.version == 1
    assert current.characters["Elias"].status == "dead"
