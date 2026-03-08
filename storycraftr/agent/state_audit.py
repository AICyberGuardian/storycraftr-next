"""Audit trail for narrative state changes (DSVL Phase 2A).

Provides append-only JSONL logging of all state mutations with queryable history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from storycraftr.agent.narrative_state import StatePatch
from storycraftr.agent.state_diff import StateChangeset


@dataclass(frozen=True)
class AuditEntry:
    """Single audit log entry for a state change.

    Attributes:
        timestamp: ISO 8601 timestamp of the change
        operation_type: Type of operation (patch, upsert, delete)
        actor: Who/what initiated the change (user, agent name, or "system")
        patch: The patch that was applied (if applicable)
        changeset: The resulting diff from the operation (if applicable)
        metadata: Arbitrary key-value pairs for context (chapter, version, etc.)
    """

    timestamp: str
    operation_type: Literal["patch", "upsert", "delete"]
    actor: str
    patch: StatePatch | None = None
    changeset: StateChangeset | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize entry to dict for JSONL storage."""
        result: dict[str, Any] = {
            "timestamp": self.timestamp,
            "operation_type": self.operation_type,
            "actor": self.actor,
            "metadata": self.metadata,
        }
        if self.patch:
            # Serialize Pydantic model to dict
            result["patch"] = self.patch.model_dump(mode="json")
        if self.changeset:
            # Serialize frozen dataclass to dict
            result["changeset"] = _serialize_changeset(self.changeset)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEntry:
        """Deserialize entry from dict loaded from JSONL."""
        patch = None
        if "patch" in data and data["patch"] is not None:
            patch = StatePatch.model_validate(data["patch"])

        changeset = None
        if "changeset" in data and data["changeset"] is not None:
            changeset = _deserialize_changeset(data["changeset"])

        return cls(
            timestamp=data["timestamp"],
            operation_type=data["operation_type"],
            actor=data["actor"],
            patch=patch,
            changeset=changeset,
            metadata=data.get("metadata", {}),
        )


def _serialize_changeset(changeset: StateChangeset) -> dict[str, Any]:
    """Convert StateChangeset to JSON-serializable dict."""
    return {
        "character_diffs": [
            {
                "entity_type": diff.entity_type,
                "entity_id": diff.entity_id,
                "diff_type": diff.diff_type.value,
                "field_diffs": [
                    {
                        "field_name": fd.field_name,
                        "old_value": fd.old_value,
                        "new_value": fd.new_value,
                        "diff_type": fd.diff_type.value,
                    }
                    for fd in diff.field_diffs
                ],
            }
            for diff in changeset.character_diffs
        ],
        "location_diffs": [
            {
                "entity_type": diff.entity_type,
                "entity_id": diff.entity_id,
                "diff_type": diff.diff_type.value,
                "field_diffs": [
                    {
                        "field_name": fd.field_name,
                        "old_value": fd.old_value,
                        "new_value": fd.new_value,
                        "diff_type": fd.diff_type.value,
                    }
                    for fd in diff.field_diffs
                ],
            }
            for diff in changeset.location_diffs
        ],
        "plot_thread_diffs": [
            {
                "entity_type": diff.entity_type,
                "entity_id": diff.entity_id,
                "diff_type": diff.diff_type.value,
                "field_diffs": [
                    {
                        "field_name": fd.field_name,
                        "old_value": fd.old_value,
                        "new_value": fd.new_value,
                        "diff_type": fd.diff_type.value,
                    }
                    for fd in diff.field_diffs
                ],
            }
            for diff in changeset.plot_thread_diffs
        ],
        "world_changed": changeset.world_changed,
    }


def _deserialize_changeset(data: dict[str, Any]) -> StateChangeset:
    """Convert dict to StateChangeset."""
    from storycraftr.agent.state_diff import DiffType, EntityDiff, FieldDiff

    def deserialize_entity_diffs(diffs_data: list[dict[str, Any]]) -> tuple:
        return tuple(
            EntityDiff(
                entity_type=d["entity_type"],
                entity_id=d["entity_id"],
                diff_type=DiffType(d["diff_type"]),
                field_diffs=tuple(
                    FieldDiff(
                        field_name=fd["field_name"],
                        old_value=fd["old_value"],
                        new_value=fd["new_value"],
                        diff_type=DiffType(fd["diff_type"]),
                    )
                    for fd in d["field_diffs"]
                ),
            )
            for d in diffs_data
        )

    return StateChangeset(
        character_diffs=deserialize_entity_diffs(data["character_diffs"]),
        location_diffs=deserialize_entity_diffs(data["location_diffs"]),
        plot_thread_diffs=deserialize_entity_diffs(data["plot_thread_diffs"]),
        world_changed=data["world_changed"],
    )


class StateAuditLog:
    """Append-only JSONL audit log for narrative state changes.

    Each line in the JSONL file is a JSON-serialized AuditEntry.
    Supports querying by entity, operation type, and time range.
    """

    def __init__(self, audit_path: Path):
        """Initialize audit log at the given path.

        Args:
            audit_path: Path to JSONL audit file (will be created if missing)
        """
        self.audit_path = audit_path

    def append_entry(self, entry: AuditEntry) -> None:
        """Append an audit entry to the log.

        Args:
            entry: The audit entry to append

        Note:
            This operation is atomic (single line append) and thread-safe
            on POSIX systems due to O_APPEND flag behavior.
        """
        # Ensure parent directory exists
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

        # Append-only write (atomic line append on POSIX)
        with self.audit_path.open("a", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, ensure_ascii=False)
            f.write("\n")

    def query_entries(
        self,
        entity_id: str | None = None,
        entity_type: Literal["character", "location", "plot_thread"] | None = None,
        operation_type: Literal["patch", "upsert", "delete"] | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        """Query audit log with optional filters.

        Args:
            entity_id: Filter to entries affecting this entity ID
            entity_type: Filter to entries affecting this entity type
            operation_type: Filter to specific operation types
            after: ISO timestamp - only return entries after this time (inclusive)
            before: ISO timestamp - only return entries before this time (inclusive)
            limit: Maximum number of entries to return (most recent first)

        Returns:
            List of matching audit entries, sorted by timestamp descending
        """
        if not self.audit_path.exists():
            return []

        entries = self._read_all_entries()

        # Apply filters
        filtered = []
        for entry in entries:
            # Time range filters
            if after and entry.timestamp < after:
                continue
            if before and entry.timestamp > before:
                continue

            # Operation type filter
            if operation_type and entry.operation_type != operation_type:
                continue

            # Entity filters (check changeset and patch)
            if entity_id or entity_type:
                if not self._entry_affects_entity(entry, entity_id, entity_type):
                    continue

            filtered.append(entry)

        # Sort by timestamp descending (most recent first)
        filtered.sort(key=lambda e: e.timestamp, reverse=True)

        # Apply limit
        if limit:
            filtered = filtered[:limit]

        return filtered

    def _read_all_entries(self) -> list[AuditEntry]:
        """Read all entries from the audit log.

        Returns:
            List of all audit entries, in file order
        """
        entries = []
        with self.audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entries.append(AuditEntry.from_dict(data))
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    # Skip malformed lines (should not happen in normal operation)
                    continue
        return entries

    def _entry_affects_entity(
        self,
        entry: AuditEntry,
        entity_id: str | None,
        entity_type: str | None,
    ) -> bool:
        """Check if an audit entry affects the specified entity.

        Args:
            entry: The audit entry to check
            entity_id: Entity ID to match (if provided)
            entity_type: Entity type to match (if provided)

        Returns:
            True if the entry affects the specified entity
        """
        # Check patch operations
        if entry.patch:
            for op in entry.patch.operations:
                if entity_type and op.entity_type != entity_type:
                    continue
                if entity_id and op.entity_id != entity_id:
                    continue
                return True

        # Check changeset diffs
        if entry.changeset:
            all_diffs = (
                entry.changeset.character_diffs
                + entry.changeset.location_diffs
                + entry.changeset.plot_thread_diffs
            )
            for diff in all_diffs:
                if entity_type and diff.entity_type != entity_type:
                    continue
                if entity_id and diff.entity_id != entity_id:
                    continue
                return True

        return False
