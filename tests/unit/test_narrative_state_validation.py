"""
Tests for DSVL Phase 1A: Pydantic validation models for narrative state.

Validates:
- CharacterState validation rules
- LocationState validation rules
- PlotThreadState validation rules
- NarrativeStateSnapshot cross-entity validation
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from storycraftr.agent.narrative_state import (
    CharacterState,
    LocationState,
    NarrativeStateSnapshot,
    PlotThreadState,
)

# ============================================================================
# CHARACTER STATE VALIDATION TESTS
# ============================================================================


def test_character_state_rejects_empty_name():
    """Character name must be non-empty."""
    with pytest.raises(ValidationError) as exc_info:
        CharacterState(name="")

    assert "name" in str(exc_info.value)


def test_character_state_rejects_too_long_name():
    """Character name must not exceed 100 characters."""
    with pytest.raises(ValidationError) as exc_info:
        CharacterState(name="x" * 101)

    assert "name" in str(exc_info.value)


def test_character_state_rejects_empty_location_string():
    """Location cannot be empty string (must be None or non-empty)."""
    with pytest.raises(ValidationError) as exc_info:
        CharacterState(name="Elias", location="")

    assert "Location cannot be empty string" in str(exc_info.value)


def test_character_state_accepts_none_location():
    """Location can be None."""
    char = CharacterState(name="Elias", location=None)
    assert char.location is None


def test_character_state_accepts_valid_location():
    """Location can be a non-empty string."""
    char = CharacterState(name="Elias", location="Engine Room")
    assert char.location == "Engine Room"


def test_character_state_rejects_invalid_status():
    """Status must be one of the allowed literals."""
    with pytest.raises(ValidationError) as exc_info:
        CharacterState(name="Elias", status="zombie")  # type: ignore

    assert "status" in str(exc_info.value)


def test_character_state_accepts_all_valid_statuses():
    """All valid status values should be accepted."""
    for status in ["alive", "injured", "dead", "unknown"]:
        char = CharacterState(name="Test", status=status)  # type: ignore
        assert char.status == status


def test_character_state_defaults_to_alive():
    """Status defaults to 'alive' if not specified."""
    char = CharacterState(name="Elias")
    assert char.status == "alive"


def test_character_state_inventory_defaults_to_empty_list():
    """Inventory defaults to empty list."""
    char = CharacterState(name="Elias")
    assert char.inventory == []


def test_character_state_inventory_accepts_strings():
    """Inventory can contain strings."""
    char = CharacterState(name="Elias", inventory=["key", "map"])
    assert char.inventory == ["key", "map"]


def test_character_state_rejects_negative_first_appearance():
    """First appearance chapter must be >= 1."""
    with pytest.raises(ValidationError) as exc_info:
        CharacterState(name="Elias", first_appearance_chapter=0)

    assert "first_appearance_chapter" in str(exc_info.value)


def test_character_state_accepts_valid_first_appearance():
    """First appearance chapter can be positive integer."""
    char = CharacterState(name="Elias", first_appearance_chapter=3)
    assert char.first_appearance_chapter == 3


# ============================================================================
# LOCATION STATE VALIDATION TESTS
# ============================================================================


def test_location_state_rejects_empty_name():
    """Location name must be non-empty."""
    with pytest.raises(ValidationError) as exc_info:
        LocationState(name="")

    assert "name" in str(exc_info.value)


def test_location_state_rejects_invalid_status():
    """Status must be one of the allowed literals."""
    with pytest.raises(ValidationError) as exc_info:
        LocationState(name="Engine Room", status="obliterated")  # type: ignore

    assert "status" in str(exc_info.value)


def test_location_state_accepts_all_valid_statuses():
    """All valid status values should be accepted."""
    for status in ["normal", "damaged", "destroyed", "sealed"]:
        loc = LocationState(name="Test", status=status)  # type: ignore
        assert loc.status == status


def test_location_state_enforces_visited_chapters_order():
    """Visited chapters must be in ascending order."""
    with pytest.raises(ValidationError) as exc_info:
        LocationState(name="Engine Room", visited_chapters=[3, 1, 2])

    assert "ascending order" in str(exc_info.value)


def test_location_state_accepts_ordered_chapters():
    """Visited chapters in ascending order should be accepted."""
    loc = LocationState(name="Engine Room", visited_chapters=[1, 2, 3])
    assert loc.visited_chapters == [1, 2, 3]


def test_location_state_accepts_empty_visited_chapters():
    """Empty visited chapters list should be accepted."""
    loc = LocationState(name="Engine Room", visited_chapters=[])
    assert loc.visited_chapters == []


# ============================================================================
# PLOT THREAD STATE VALIDATION TESTS
# ============================================================================


def test_plot_thread_requires_resolved_chapter_when_resolved():
    """Resolved threads must have resolved_chapter."""
    with pytest.raises(ValidationError) as exc_info:
        PlotThreadState(
            id="rebellion",
            description="Resistance movement",
            status="CLOSED",
            introduced_chapter=1,
            resolved_chapter=None,
        )

    assert "must have resolved_chapter" in str(exc_info.value)


def test_plot_thread_rejects_resolved_chapter_when_open():
    """Open threads cannot have resolved_chapter."""
    with pytest.raises(ValidationError) as exc_info:
        PlotThreadState(
            id="rebellion",
            description="Resistance movement",
            status="OPEN",
            introduced_chapter=1,
            resolved_chapter=5,
        )

    assert "cannot have resolved_chapter" in str(exc_info.value)


def test_plot_thread_accepts_valid_resolved():
    """Resolved threads with resolved_chapter should be accepted."""
    thread = PlotThreadState(
        id="rebellion",
        description="Resistance movement",
        status="CLOSED",
        introduced_chapter=1,
        resolved_chapter=5,
    )
    assert thread.status == "CLOSED"
    assert thread.resolved_chapter == 5


def test_plot_thread_accepts_valid_open():
    """Open threads without resolved_chapter should be accepted."""
    thread = PlotThreadState(
        id="rebellion",
        description="Resistance movement",
        status="OPEN",
        introduced_chapter=1,
    )
    assert thread.status == "OPEN"
    assert thread.resolved_chapter is None


def test_plot_thread_rejects_invalid_id_format():
    """Thread ID must match pattern [a-z0-9_-]+."""
    with pytest.raises(ValidationError) as exc_info:
        PlotThreadState(
            id="Rebellion Thread!",
            description="Resistance movement",
            introduced_chapter=1,
        )

    assert "id" in str(exc_info.value)


def test_plot_thread_accepts_valid_id_format():
    """Thread ID with lowercase, numbers, underscores, hyphens should work."""
    thread = PlotThreadState(
        id="rebellion_001",
        description="Resistance movement",
        introduced_chapter=1,
    )
    assert thread.id == "rebellion_001"


# ============================================================================
# NARRATIVE STATE SNAPSHOT TESTS
# ============================================================================


def test_narrative_snapshot_validates_on_load():
    """NarrativeStateSnapshot should validate all entities."""
    char = CharacterState(name="Elias", status="alive")
    loc = LocationState(name="Engine Room", status="normal")

    snapshot = NarrativeStateSnapshot(
        characters={"Elias": char},
        locations={"Engine Room": loc},
    )

    assert "Elias" in snapshot.characters
    assert "Engine Room" in snapshot.locations


def test_narrative_snapshot_warns_about_unknown_location_reference(caplog):
    """Characters referencing unknown locations should log a warning."""
    char = CharacterState(name="Elias", location="Unknown Place")

    snapshot = NarrativeStateSnapshot(
        characters={"Elias": char},
        locations={},  # No locations defined
    )

    # Warning should be logged
    assert any("Unknown Place" in record.message for record in caplog.records)


def test_narrative_snapshot_accepts_valid_location_reference():
    """Characters referencing known locations should validate without warnings."""
    char = CharacterState(name="Elias", location="Engine Room")
    loc = LocationState(name="Engine Room")

    snapshot = NarrativeStateSnapshot(
        characters={"Elias": char},
        locations={"Engine Room": loc},
    )

    assert snapshot.characters["Elias"].location == "Engine Room"


def test_narrative_snapshot_has_version_field():
    """Snapshot should have a version field."""
    snapshot = NarrativeStateSnapshot()
    assert snapshot.version >= 1


def test_narrative_snapshot_has_last_modified_field():
    """Snapshot should have a last_modified field."""
    snapshot = NarrativeStateSnapshot()
    assert snapshot.last_modified is not None
    assert len(snapshot.last_modified) > 0


def test_invalid_json_raises_validation_error():
    """Invalid data types should raise ValidationError."""
    with pytest.raises(ValidationError):
        NarrativeStateSnapshot(characters={"Elias": "not a dict"})  # type: ignore
