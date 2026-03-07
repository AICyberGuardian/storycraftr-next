"""Tests for state audit trail (DSVL Phase 2A)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from storycraftr.agent.narrative_state import PatchOperation, StatePatch
from storycraftr.agent.state_audit import AuditEntry, StateAuditLog
from storycraftr.agent.state_diff import (
    DiffType,
    EntityDiff,
    FieldDiff,
    StateChangeset,
)


def test_audit_entry_serialization():
    """Test AuditEntry serialization to dict."""
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="alice",
                data={"location": "castle"},
            )
        ],
        description="Alice enters the castle",
    )

    changeset = StateChangeset(
        character_diffs=(
            EntityDiff(
                entity_type="character",
                entity_id="alice",
                diff_type=DiffType.MODIFIED,
                field_diffs=(
                    FieldDiff(
                        field_name="location",
                        old_value="village",
                        new_value="castle",
                        diff_type=DiffType.MODIFIED,
                    ),
                ),
            ),
        ),
        location_diffs=(),
        plot_thread_diffs=(),
        world_changed=False,
    )

    entry = AuditEntry(
        timestamp="2026-03-07T12:00:00Z",
        operation_type="patch",
        actor="test_user",
        patch=patch,
        changeset=changeset,
        metadata={"chapter": 3},
    )

    # Serialize and verify structure
    data = entry.to_dict()
    assert data["timestamp"] == "2026-03-07T12:00:00Z"
    assert data["operation_type"] == "patch"
    assert data["actor"] == "test_user"
    assert "patch" in data
    assert "changeset" in data
    assert data["metadata"]["chapter"] == 3

    # Verify patch serialization
    assert data["patch"]["operations"][0]["entity_type"] == "character"
    assert data["patch"]["operations"][0]["entity_id"] == "alice"

    # Verify changeset serialization
    assert len(data["changeset"]["character_diffs"]) == 1
    assert data["changeset"]["character_diffs"][0]["entity_id"] == "alice"
    assert (
        data["changeset"]["character_diffs"][0]["field_diffs"][0]["field_name"]
        == "location"
    )


def test_audit_entry_deserialization():
    """Test AuditEntry deserialization from dict."""
    data = {
        "timestamp": "2026-03-07T12:00:00Z",
        "operation_type": "patch",
        "actor": "test_user",
        "patch": {
            "operations": [
                {
                    "operation": "update",
                    "entity_type": "character",
                    "entity_id": "alice",
                    "data": {"location": "castle"},
                }
            ],
            "description": "Alice enters the castle",
        },
        "changeset": {
            "character_diffs": [
                {
                    "entity_type": "character",
                    "entity_id": "alice",
                    "diff_type": "modified",
                    "field_diffs": [
                        {
                            "field_name": "location",
                            "old_value": "village",
                            "new_value": "castle",
                            "diff_type": "modified",
                        }
                    ],
                }
            ],
            "location_diffs": [],
            "plot_thread_diffs": [],
            "world_changed": False,
        },
        "metadata": {"chapter": 3},
    }

    entry = AuditEntry.from_dict(data)
    assert entry.timestamp == "2026-03-07T12:00:00Z"
    assert entry.operation_type == "patch"
    assert entry.actor == "test_user"
    assert entry.patch is not None
    assert len(entry.patch.operations) == 1
    assert entry.changeset is not None
    assert len(entry.changeset.character_diffs) == 1
    assert entry.metadata["chapter"] == 3


def test_audit_log_append_creates_file(tmp_path: Path):
    """Test that append creates the audit file if missing."""
    audit_path = tmp_path / "outline" / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    entry = AuditEntry(
        timestamp="2026-03-07T12:00:00Z",
        operation_type="upsert",
        actor="system",
    )

    log.append_entry(entry)

    # Verify file was created
    assert audit_path.exists()
    assert audit_path.parent.exists()

    # Verify content
    with audit_path.open("r") as f:
        lines = f.readlines()
        assert len(lines) == 1


def test_audit_log_append_multiple_entries(tmp_path: Path):
    """Test appending multiple entries to audit log."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Append three entries
    for i in range(3):
        entry = AuditEntry(
            timestamp=f"2026-03-07T12:0{i}:00Z",
            operation_type="patch",
            actor=f"user_{i}",
        )
        log.append_entry(entry)

    # Verify all entries present
    entries = log._read_all_entries()
    assert len(entries) == 3
    assert entries[0].timestamp == "2026-03-07T12:00:00Z"
    assert entries[1].timestamp == "2026-03-07T12:01:00Z"
    assert entries[2].timestamp == "2026-03-07T12:02:00Z"


def test_audit_log_query_empty_log(tmp_path: Path):
    """Test querying an empty (non-existent) audit log."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    entries = log.query_entries()
    assert entries == []


def test_audit_log_query_all_entries(tmp_path: Path):
    """Test querying all entries without filters."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add three entries
    for i in range(3):
        entry = AuditEntry(
            timestamp=f"2026-03-07T12:0{i}:00Z",
            operation_type="patch",
            actor="user",
        )
        log.append_entry(entry)

    # Query all
    entries = log.query_entries()
    assert len(entries) == 3

    # Verify descending timestamp order
    assert entries[0].timestamp == "2026-03-07T12:02:00Z"
    assert entries[1].timestamp == "2026-03-07T12:01:00Z"
    assert entries[2].timestamp == "2026-03-07T12:00:00Z"


def test_audit_log_query_by_operation_type(tmp_path: Path):
    """Test filtering by operation type."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add mixed operation types
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z", operation_type="patch", actor="user"
        )
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:01:00Z", operation_type="upsert", actor="user"
        )
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:02:00Z", operation_type="patch", actor="user"
        )
    )

    # Query patches only
    patches = log.query_entries(operation_type="patch")
    assert len(patches) == 2
    assert all(e.operation_type == "patch" for e in patches)

    # Query upserts only
    upserts = log.query_entries(operation_type="upsert")
    assert len(upserts) == 1
    assert upserts[0].operation_type == "upsert"


def test_audit_log_query_by_time_range(tmp_path: Path):
    """Test filtering by time range (after/before)."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add entries with different timestamps
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T10:00:00Z", operation_type="patch", actor="user"
        )
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z", operation_type="patch", actor="user"
        )
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T14:00:00Z", operation_type="patch", actor="user"
        )
    )

    # Query after 12:00 (inclusive)
    after_entries = log.query_entries(after="2026-03-07T12:00:00Z")
    assert len(after_entries) == 2
    assert all(e.timestamp >= "2026-03-07T12:00:00Z" for e in after_entries)

    # Query before 12:00 (inclusive)
    before_entries = log.query_entries(before="2026-03-07T12:00:00Z")
    assert len(before_entries) == 2
    assert all(e.timestamp <= "2026-03-07T12:00:00Z" for e in before_entries)

    # Query between 11:00 and 13:00
    range_entries = log.query_entries(
        after="2026-03-07T11:00:00Z", before="2026-03-07T13:00:00Z"
    )
    assert len(range_entries) == 1
    assert range_entries[0].timestamp == "2026-03-07T12:00:00Z"


def test_audit_log_query_with_limit(tmp_path: Path):
    """Test limiting number of returned entries."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add five entries
    for i in range(5):
        log.append_entry(
            AuditEntry(
                timestamp=f"2026-03-07T12:0{i}:00Z",
                operation_type="patch",
                actor="user",
            )
        )

    # Query with limit=2 (should get most recent)
    entries = log.query_entries(limit=2)
    assert len(entries) == 2
    assert entries[0].timestamp == "2026-03-07T12:04:00Z"
    assert entries[1].timestamp == "2026-03-07T12:03:00Z"


def test_audit_log_query_by_entity_id_in_patch(tmp_path: Path):
    """Test filtering by entity ID present in patch."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add entry affecting alice
    alice_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="alice",
                data={"location": "castle"},
            )
        ],
        description="Alice moves",
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z",
            operation_type="patch",
            actor="user",
            patch=alice_patch,
        )
    )

    # Add entry affecting bob
    bob_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="bob",
                data={"location": "forest"},
            )
        ],
        description="Bob moves",
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:01:00Z",
            operation_type="patch",
            actor="user",
            patch=bob_patch,
        )
    )

    # Query for alice only
    alice_entries = log.query_entries(entity_id="alice")
    assert len(alice_entries) == 1
    assert alice_entries[0].patch.operations[0].entity_id == "alice"

    # Query for bob only
    bob_entries = log.query_entries(entity_id="bob")
    assert len(bob_entries) == 1
    assert bob_entries[0].patch.operations[0].entity_id == "bob"


def test_audit_log_query_by_entity_type_in_patch(tmp_path: Path):
    """Test filtering by entity type present in patch."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add character patch
    char_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="alice",
                data={"name": "Alice"},
            )
        ],
        description="Add Alice",
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z",
            operation_type="patch",
            actor="user",
            patch=char_patch,
        )
    )

    # Add location patch
    loc_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="location",
                entity_id="castle",
                data={"name": "Castle"},
            )
        ],
        description="Add castle",
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:01:00Z",
            operation_type="patch",
            actor="user",
            patch=loc_patch,
        )
    )

    # Query for characters only
    char_entries = log.query_entries(entity_type="character")
    assert len(char_entries) == 1
    assert char_entries[0].patch.operations[0].entity_type == "character"

    # Query for locations only
    loc_entries = log.query_entries(entity_type="location")
    assert len(loc_entries) == 1
    assert loc_entries[0].patch.operations[0].entity_type == "location"


def test_audit_log_query_by_entity_id_in_changeset(tmp_path: Path):
    """Test filtering by entity ID present in changeset."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add entry with alice changeset
    alice_changeset = StateChangeset(
        character_diffs=(
            EntityDiff(
                entity_type="character",
                entity_id="alice",
                diff_type=DiffType.MODIFIED,
                field_diffs=(
                    FieldDiff(
                        field_name="location",
                        old_value="village",
                        new_value="castle",
                        diff_type=DiffType.MODIFIED,
                    ),
                ),
            ),
        ),
        location_diffs=(),
        plot_thread_diffs=(),
        world_changed=False,
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z",
            operation_type="patch",
            actor="user",
            changeset=alice_changeset,
        )
    )

    # Add entry with bob changeset
    bob_changeset = StateChangeset(
        character_diffs=(
            EntityDiff(
                entity_type="character",
                entity_id="bob",
                diff_type=DiffType.ADDED,
                field_diffs=(),
            ),
        ),
        location_diffs=(),
        plot_thread_diffs=(),
        world_changed=False,
    )
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:01:00Z",
            operation_type="upsert",
            actor="user",
            changeset=bob_changeset,
        )
    )

    # Query for alice only
    alice_entries = log.query_entries(entity_id="alice")
    assert len(alice_entries) == 1
    assert alice_entries[0].changeset.character_diffs[0].entity_id == "alice"

    # Query for bob only
    bob_entries = log.query_entries(entity_id="bob")
    assert len(bob_entries) == 1
    assert bob_entries[0].changeset.character_diffs[0].entity_id == "bob"


def test_audit_log_handles_malformed_lines(tmp_path: Path):
    """Test that malformed JSONL lines are skipped gracefully."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add valid entry
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z", operation_type="patch", actor="user"
        )
    )

    # Manually append malformed lines
    with audit_path.open("a") as f:
        f.write("not valid json\n")
        f.write("{}\n")  # Missing required fields

    # Add another valid entry
    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:01:00Z", operation_type="patch", actor="user"
        )
    )

    # Query should skip malformed lines and return valid entries
    entries = log.query_entries()
    assert len(entries) == 2
    assert entries[0].timestamp == "2026-03-07T12:01:00Z"
    assert entries[1].timestamp == "2026-03-07T12:00:00Z"


def test_audit_log_combined_filters(tmp_path: Path):
    """Test combining multiple filters."""
    audit_path = tmp_path / "narrative_audit.jsonl"
    log = StateAuditLog(audit_path)

    # Add mixed entries
    alice_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="update",
                entity_type="character",
                entity_id="alice",
                data={"location": "castle"},
            )
        ],
        description="Alice moves",
    )

    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T10:00:00Z",
            operation_type="patch",
            actor="user",
            patch=alice_patch,
        )
    )

    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z",
            operation_type="patch",
            actor="user",
            patch=alice_patch,
        )
    )

    bob_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="bob",
                data={"name": "Bob"},
            )
        ],
        description="Add Bob",
    )

    log.append_entry(
        AuditEntry(
            timestamp="2026-03-07T12:00:00Z",
            operation_type="upsert",
            actor="user",
            patch=bob_patch,
        )
    )

    # Query: alice patches after 11:00 with limit 1
    entries = log.query_entries(
        entity_id="alice",
        operation_type="patch",
        after="2026-03-07T11:00:00Z",
        limit=1,
    )

    assert len(entries) == 1
    assert entries[0].timestamp == "2026-03-07T12:00:00Z"
    assert entries[0].patch.operations[0].entity_id == "alice"


def test_audit_integration_with_apply_patch(tmp_path: Path):
    """Test that apply_patch creates audit entries correctly."""
    from storycraftr.agent.narrative_state import (
        CharacterState,
        LocationState,
        NarrativeStateSnapshot,
        NarrativeStateStore,
        PatchOperation,
        StatePatch,
    )

    # Create a state store with audit enabled
    book_path = tmp_path / "test_book"
    book_path.mkdir()
    store = NarrativeStateStore(str(book_path), enable_audit=True)

    # Initialize with a location
    initial = NarrativeStateSnapshot(
        locations={"village": LocationState(name="Village", status="normal")}
    )
    store.save(initial)

    # Apply a patch to add a character
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="alice",
                data={"name": "Alice", "location": "village"},
            )
        ],
        description="Add Alice to village",
    )

    result = store.apply_patch(patch, actor="test_user")

    # Verify patch was applied
    assert "alice" in result.characters
    assert result.characters["alice"].name == "Alice"
    # Version starts at 0, save() increments to 1, apply_patch increments to 2
    assert result.version == 2

    # Verify audit entry was created
    audit_path = book_path / "outline" / "narrative_audit.jsonl"
    assert audit_path.exists()

    from storycraftr.agent.state_audit import StateAuditLog

    audit_log = StateAuditLog(audit_path)
    entries = audit_log.query_entries()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.operation_type == "patch"
    assert entry.actor == "test_user"
    assert entry.patch is not None
    assert entry.patch.description == "Add Alice to village"
    assert entry.changeset is not None
    assert len(entry.changeset.character_diffs) == 1
    assert entry.changeset.character_diffs[0].entity_id == "alice"
    assert entry.metadata["version"] == 2


def test_audit_disabled_no_log_created(tmp_path: Path):
    """Test that disabling audit prevents log creation."""
    from storycraftr.agent.narrative_state import (
        LocationState,
        NarrativeStateSnapshot,
        NarrativeStateStore,
        PatchOperation,
        StatePatch,
    )

    # Create a state store with audit disabled
    book_path = tmp_path / "test_book"
    book_path.mkdir()
    store = NarrativeStateStore(str(book_path), enable_audit=False)

    # Initialize with a location
    initial = NarrativeStateSnapshot(
        locations={"village": LocationState(name="Village", status="normal")}
    )
    store.save(initial)

    # Apply a patch
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="alice",
                data={"name": "Alice", "location": "village"},
            )
        ],
        description="Add Alice",
    )

    result = store.apply_patch(patch, actor="test_user")

    # Verify patch was applied
    assert "alice" in result.characters

    # Verify audit log was NOT created
    audit_path = book_path / "outline" / "narrative_audit.jsonl"
    assert not audit_path.exists()
