"""
Tests for DSVL Phase 1B: State Diff Engine

Validates deterministic diff computation between narrative state snapshots.
"""

from __future__ import annotations

import pytest

from storycraftr.agent.narrative_state import (
    CharacterState,
    LocationState,
    NarrativeStateSnapshot,
    PlotThreadState,
)
from storycraftr.agent.state_diff import (
    DiffType,
    EntityDiff,
    FieldDiff,
    StateChangeset,
    compute_state_diff,
)

# ============================================================================
# EMPTY STATE DIFF TESTS
# ============================================================================


def test_empty_states_produce_no_changes():
    """Two empty states should produce no changes."""
    old_state = NarrativeStateSnapshot()
    new_state = NarrativeStateSnapshot()

    changeset = compute_state_diff(old_state, new_state)

    assert not changeset.has_changes()
    assert changeset.count_changes() == 0
    assert len(changeset.character_diffs) == 0
    assert len(changeset.location_diffs) == 0
    assert len(changeset.plot_thread_diffs) == 0


def test_identical_states_produce_unchanged_entities():
    """Identical states should mark all entities as unchanged."""
    char = CharacterState(name="Elias", status="alive")
    loc = LocationState(name="Engine Room", status="normal")

    old_state = NarrativeStateSnapshot(
        characters={"Elias": char},
        locations={"Engine Room": loc},
    )
    new_state = NarrativeStateSnapshot(
        characters={"Elias": char},
        locations={"Engine Room": loc},
    )

    changeset = compute_state_diff(old_state, new_state)

    assert not changeset.has_changes()
    assert len(changeset.character_diffs) == 1
    assert changeset.character_diffs[0].diff_type == DiffType.UNCHANGED
    assert len(changeset.location_diffs) == 1
    assert changeset.location_diffs[0].diff_type == DiffType.UNCHANGED


# ============================================================================
# CHARACTER DIFF TESTS
# ============================================================================


def test_adding_character_detected():
    """Adding a character should be detected as ADDED."""
    old_state = NarrativeStateSnapshot()
    new_char = CharacterState(name="Elias", status="alive")
    new_state = NarrativeStateSnapshot(characters={"Elias": new_char})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    assert changeset.count_changes() == 1
    assert len(changeset.character_diffs) == 1

    diff = changeset.character_diffs[0]
    assert diff.entity_type == "character"
    assert diff.entity_id == "Elias"
    assert diff.diff_type == DiffType.ADDED


def test_removing_character_detected():
    """Removing a character should be detected as REMOVED."""
    old_char = CharacterState(name="Elias", status="alive")
    old_state = NarrativeStateSnapshot(characters={"Elias": old_char})
    new_state = NarrativeStateSnapshot()

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    assert changeset.count_changes() == 1
    assert len(changeset.character_diffs) == 1

    diff = changeset.character_diffs[0]
    assert diff.entity_type == "character"
    assert diff.entity_id == "Elias"
    assert diff.diff_type == DiffType.REMOVED


def test_modifying_character_field_detected():
    """Modifying a character field should produce field-level diffs."""
    old_char = CharacterState(name="Elias", status="alive", location="Bridge")
    new_char = CharacterState(name="Elias", status="injured", location="Bridge")

    old_state = NarrativeStateSnapshot(characters={"Elias": old_char})
    new_state = NarrativeStateSnapshot(characters={"Elias": new_char})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    assert len(changeset.character_diffs) == 1

    diff = changeset.character_diffs[0]
    assert diff.diff_type == DiffType.MODIFIED
    assert len(diff.field_diffs) == 1

    field_diff = diff.field_diffs[0]
    assert field_diff.field_name == "status"
    assert field_diff.old_value == "alive"
    assert field_diff.new_value == "injured"
    assert field_diff.diff_type == DiffType.MODIFIED


def test_modifying_multiple_character_fields():
    """Multiple field changes should all be captured."""
    old_char = CharacterState(
        name="Elias", status="alive", location="Bridge", inventory=["key"]
    )
    new_char = CharacterState(
        name="Elias",
        status="injured",
        location="Engine Room",
        inventory=["key", "medkit"],
    )

    old_state = NarrativeStateSnapshot(characters={"Elias": old_char})
    new_state = NarrativeStateSnapshot(characters={"Elias": new_char})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    diff = changeset.character_diffs[0]
    assert diff.diff_type == DiffType.MODIFIED
    assert len(diff.field_diffs) == 3  # status, location, inventory

    field_names = {fd.field_name for fd in diff.field_diffs}
    assert field_names == {"status", "location", "inventory"}


# ============================================================================
# LOCATION DIFF TESTS
# ============================================================================


def test_adding_location_detected():
    """Adding a location should be detected as ADDED."""
    old_state = NarrativeStateSnapshot()
    new_loc = LocationState(name="Engine Room", status="normal")
    new_state = NarrativeStateSnapshot(locations={"Engine Room": new_loc})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    assert len(changeset.location_diffs) == 1

    diff = changeset.location_diffs[0]
    assert diff.entity_type == "location"
    assert diff.entity_id == "Engine Room"
    assert diff.diff_type == DiffType.ADDED


def test_modifying_location_status():
    """Changing location status should be detected."""
    old_loc = LocationState(name="Engine Room", status="normal")
    new_loc = LocationState(name="Engine Room", status="damaged")

    old_state = NarrativeStateSnapshot(locations={"Engine Room": old_loc})
    new_state = NarrativeStateSnapshot(locations={"Engine Room": new_loc})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    diff = changeset.location_diffs[0]
    assert diff.diff_type == DiffType.MODIFIED
    assert len(diff.field_diffs) == 1

    field_diff = diff.field_diffs[0]
    assert field_diff.field_name == "status"
    assert field_diff.old_value == "normal"
    assert field_diff.new_value == "damaged"


# ============================================================================
# PLOT THREAD DIFF TESTS
# ============================================================================


def test_adding_plot_thread_detected():
    """Adding a plot thread should be detected as ADDED."""
    old_state = NarrativeStateSnapshot()
    new_thread = PlotThreadState(
        id="rebellion",
        description="Resistance movement",
        status="OPEN",
        introduced_chapter=1,
    )
    new_state = NarrativeStateSnapshot(plot_threads={"rebellion": new_thread})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    assert len(changeset.plot_thread_diffs) == 1

    diff = changeset.plot_thread_diffs[0]
    assert diff.entity_type == "plot_thread"
    assert diff.entity_id == "rebellion"
    assert diff.diff_type == DiffType.ADDED


def test_resolving_plot_thread_detected():
    """Resolving a plot thread should show status and resolved_chapter changes."""
    old_thread = PlotThreadState(
        id="rebellion",
        description="Resistance movement",
        status="OPEN",
        introduced_chapter=1,
    )
    new_thread = PlotThreadState(
        id="rebellion",
        description="Resistance movement",
        status="CLOSED",
        introduced_chapter=1,
        resolved_chapter=5,
    )

    old_state = NarrativeStateSnapshot(plot_threads={"rebellion": old_thread})
    new_state = NarrativeStateSnapshot(plot_threads={"rebellion": new_thread})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    diff = changeset.plot_thread_diffs[0]
    assert diff.diff_type == DiffType.MODIFIED
    assert len(diff.field_diffs) == 2  # status and resolved_chapter

    field_names = {fd.field_name for fd in diff.field_diffs}
    assert field_names == {"status", "resolved_chapter"}


# ============================================================================
# WORLD DICT CHANGE TESTS
# ============================================================================


def test_world_dict_change_detected():
    """Changes to the world dict should be flagged."""
    old_state = NarrativeStateSnapshot(world={"Bridge": {"integrity": "normal"}})
    new_state = NarrativeStateSnapshot(world={"Bridge": {"integrity": "critical"}})

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.world_changed


def test_world_dict_no_change():
    """Identical world dicts should not be flagged as changed."""
    world = {"Bridge": {"integrity": "normal"}}
    old_state = NarrativeStateSnapshot(world=world)
    new_state = NarrativeStateSnapshot(world=world)

    changeset = compute_state_diff(old_state, new_state)

    assert not changeset.world_changed


# ============================================================================
# DETERMINISTIC ORDERING TESTS
# ============================================================================


def test_diff_ordering_is_deterministic():
    """Diffs should be in deterministic (sorted) order."""
    char_a = CharacterState(name="Alice", status="alive")
    char_z = CharacterState(name="Zoe", status="alive")
    char_m = CharacterState(name="Mira", status="alive")

    old_state = NarrativeStateSnapshot()
    # Add in non-alphabetical order
    new_state = NarrativeStateSnapshot(
        characters={"Zoe": char_z, "Alice": char_a, "Mira": char_m}
    )

    changeset = compute_state_diff(old_state, new_state)

    # Should be sorted alphabetically
    assert len(changeset.character_diffs) == 3
    assert changeset.character_diffs[0].entity_id == "Alice"
    assert changeset.character_diffs[1].entity_id == "Mira"
    assert changeset.character_diffs[2].entity_id == "Zoe"


def test_field_diff_ordering_is_deterministic():
    """Field diffs should be in deterministic (sorted) order."""
    old_char = CharacterState(
        name="Elias",
        status="alive",
        location="Bridge",
        inventory=[],
        role="Engineer",
    )
    new_char = CharacterState(
        name="Elias",
        status="injured",
        location="Engine Room",
        inventory=["key"],
        role="Chief Engineer",
    )

    old_state = NarrativeStateSnapshot(characters={"Elias": old_char})
    new_state = NarrativeStateSnapshot(characters={"Elias": new_char})

    changeset = compute_state_diff(old_state, new_state)

    diff = changeset.character_diffs[0]
    field_names = [fd.field_name for fd in diff.field_diffs]
    # Should be alphabetically sorted
    assert field_names == sorted(field_names)


# ============================================================================
# MIXED CHANGE TESTS
# ============================================================================


def test_mixed_changes_all_detected():
    """Adding, removing, and modifying entities in one diff should all be captured."""
    # Old state: Alice (alive), Bob (injured)
    old_state = NarrativeStateSnapshot(
        characters={
            "Alice": CharacterState(name="Alice", status="alive"),
            "Bob": CharacterState(name="Bob", status="injured"),
        }
    )

    # New state: Alice (dead), Charlie (alive)
    # - Alice modified (alive -> dead)
    # - Bob removed
    # - Charlie added
    new_state = NarrativeStateSnapshot(
        characters={
            "Alice": CharacterState(name="Alice", status="dead"),
            "Charlie": CharacterState(name="Charlie", status="alive"),
        }
    )

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    assert changeset.count_changes() == 3
    assert len(changeset.character_diffs) == 3

    # Find each diff by ID
    diffs_by_id = {d.entity_id: d for d in changeset.character_diffs}

    assert diffs_by_id["Alice"].diff_type == DiffType.MODIFIED
    assert diffs_by_id["Bob"].diff_type == DiffType.REMOVED
    assert diffs_by_id["Charlie"].diff_type == DiffType.ADDED


def test_complex_multi_entity_diff():
    """Complex diff with changes across all entity types."""
    old_state = NarrativeStateSnapshot(
        characters={"Elias": CharacterState(name="Elias", status="alive")},
        locations={"Bridge": LocationState(name="Bridge", status="normal")},
        plot_threads={
            "rebellion": PlotThreadState(
                id="rebellion",
                description="Resistance",
                status="OPEN",
                introduced_chapter=1,
            )
        },
        world={"tech_level": {"value": "advanced"}},
    )

    new_state = NarrativeStateSnapshot(
        characters={"Elias": CharacterState(name="Elias", status="injured")},
        locations={"Bridge": LocationState(name="Bridge", status="damaged")},
        plot_threads={
            "rebellion": PlotThreadState(
                id="rebellion",
                description="Resistance",
                status="CLOSED",
                introduced_chapter=1,
                resolved_chapter=5,
            )
        },
        world={"tech_level": {"value": "declining"}},
    )

    changeset = compute_state_diff(old_state, new_state)

    assert changeset.has_changes()
    assert changeset.character_diffs[0].diff_type == DiffType.MODIFIED
    assert changeset.location_diffs[0].diff_type == DiffType.MODIFIED
    assert changeset.plot_thread_diffs[0].diff_type == DiffType.MODIFIED
    assert changeset.world_changed
