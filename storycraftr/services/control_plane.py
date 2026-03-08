from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from storycraftr.agent.execution_mode import ExecutionMode, parse_execution_mode
from storycraftr.agent.narrative_state import (
    NarrativeStateSnapshot,
    NarrativeStateStore,
    PatchOperation,
    StatePatch,
)
from storycraftr.agent.state_extractor import StateExtractionResult, extract_state_patch
from storycraftr.chat.session import SessionManager
from storycraftr.tui.canon_extract import extract_canon_candidates
from storycraftr.tui.canon_verify import verify_candidate_against_canon
from storycraftr.tui.session import TuiSessionState


@dataclass(frozen=True)
class CanonCheckRow:
    """Normalized canon-check result for one candidate statement."""

    candidate: str
    allowed: bool
    reason: str
    conflicting_fact: str | None


@dataclass(frozen=True)
class CanonCheckResult:
    """Aggregated canon verification output for a payload."""

    chapter: int
    checked_candidates: int
    failures: int
    rows: list[CanonCheckRow]


@dataclass(frozen=True)
class StateAuditResult:
    """Result envelope for state audit queries."""

    enabled: bool
    entries: list


@dataclass(frozen=True)
class StateExtractResult:
    """Shared state extraction result for CLI and TUI surfaces."""

    extracted: StateExtractionResult
    applied: bool
    applied_version: int | None
    verification_passed: bool
    verification_issues: list[str]
    retry_performed: bool
    dropped_operations: int


def _operation_priority(operation: PatchOperation) -> int:
    """Return deterministic operation priority for dependency-aware retries."""

    if operation.entity_type == "location" and operation.operation == "add":
        return 0
    if operation.entity_type == "character" and operation.operation == "add":
        return 1
    if operation.entity_type == "character" and operation.operation == "update":
        return 2
    return 3


def _reorder_patch_operations(
    operations: list[PatchOperation],
) -> list[PatchOperation]:
    """Return deterministic dependency-first ordering for verification retries."""

    indexed = list(enumerate(operations))
    indexed.sort(key=lambda pair: (_operation_priority(pair[1]), pair[0]))
    return [operation for _idx, operation in indexed]


def _verify_patch_operations(
    snapshot: NarrativeStateSnapshot,
    operations: list[PatchOperation],
) -> tuple[list[PatchOperation], list[str]]:
    """Verify patch operations against current state and keep only safe operations."""

    known_locations = set(snapshot.locations.keys())
    known_characters = set(snapshot.characters.keys())
    known_plot_threads = set(snapshot.plot_threads.keys())
    character_locations = {
        key: character.location for key, character in snapshot.characters.items()
    }
    dead_characters = {
        key
        for key, character in snapshot.characters.items()
        if character.status == "dead"
    }

    verified: list[PatchOperation] = []
    issues: list[str] = []

    for operation in operations:
        if operation.entity_type == "location":
            if operation.operation == "add":
                if operation.entity_id in known_locations:
                    issues.append(
                        f"drop location add '{operation.entity_id}': already exists"
                    )
                    continue
                known_locations.add(operation.entity_id)
            elif operation.operation == "update":
                if operation.entity_id not in known_locations:
                    issues.append(
                        f"drop location update '{operation.entity_id}': location missing"
                    )
                    continue
            elif operation.operation == "remove":
                if operation.entity_id not in known_locations:
                    issues.append(
                        f"drop location remove '{operation.entity_id}': location missing"
                    )
                    continue
                occupied = [
                    char_id
                    for char_id, location in character_locations.items()
                    if location == operation.entity_id
                ]
                if occupied:
                    issues.append(
                        "drop location remove "
                        f"'{operation.entity_id}': occupied by {', '.join(sorted(occupied))}"
                    )
                    continue
                known_locations.discard(operation.entity_id)
            verified.append(operation)
            continue

        if operation.entity_type == "character":
            location = None
            if operation.data is not None:
                location = operation.data.get("location")

            if operation.operation == "add":
                if operation.entity_id in known_characters:
                    issues.append(
                        f"drop character add '{operation.entity_id}': already exists"
                    )
                    continue
                if location and location not in known_locations:
                    issues.append(
                        "drop character add "
                        f"'{operation.entity_id}': unknown location '{location}'"
                    )
                    continue
                known_characters.add(operation.entity_id)
                character_locations[operation.entity_id] = location
                status = (operation.data or {}).get("status")
                if status == "dead":
                    dead_characters.add(operation.entity_id)
            elif operation.operation == "update":
                if operation.entity_id not in known_characters:
                    issues.append(
                        f"drop character update '{operation.entity_id}': character missing"
                    )
                    continue
                if location and location not in known_locations:
                    issues.append(
                        "drop character update "
                        f"'{operation.entity_id}': unknown location '{location}'"
                    )
                    continue
                current_location = character_locations.get(operation.entity_id)
                if (
                    operation.entity_id in dead_characters
                    and location is not None
                    and location != current_location
                ):
                    issues.append(
                        "drop character update "
                        f"'{operation.entity_id}': dead character cannot move"
                    )
                    continue
                if location is not None:
                    character_locations[operation.entity_id] = location
                status = (operation.data or {}).get("status")
                if status == "dead":
                    dead_characters.add(operation.entity_id)
                elif status in {"alive", "injured", "unknown"}:
                    dead_characters.discard(operation.entity_id)
            elif operation.operation == "remove":
                if operation.entity_id not in known_characters:
                    issues.append(
                        f"drop character remove '{operation.entity_id}': character missing"
                    )
                    continue
                known_characters.discard(operation.entity_id)
                character_locations.pop(operation.entity_id, None)
                dead_characters.discard(operation.entity_id)
            verified.append(operation)
            continue

        if operation.entity_type == "plot_thread":
            if operation.operation == "add":
                if operation.entity_id in known_plot_threads:
                    issues.append(
                        f"drop plot-thread add '{operation.entity_id}': already exists"
                    )
                    continue
                known_plot_threads.add(operation.entity_id)
            elif operation.operation in {"update", "remove"}:
                if operation.entity_id not in known_plot_threads:
                    issues.append(
                        "drop plot-thread "
                        f"{operation.operation} '{operation.entity_id}': thread missing"
                    )
                    continue
                if operation.operation == "remove":
                    known_plot_threads.discard(operation.entity_id)
            verified.append(operation)

    return verified, issues


def _resolve_book_path(book_path: str | Path | None) -> str:
    """Resolve and normalize the project path used by control-plane services."""

    raw = Path(book_path) if book_path is not None else Path(os.getcwd())
    return str(raw.resolve())


def _load_mode_state(
    book_path: str | Path | None,
) -> tuple[SessionManager, TuiSessionState]:
    """Load runtime mode state for a project."""

    manager = SessionManager(_resolve_book_path(book_path))
    runtime_state = manager.load_runtime_state()
    return manager, TuiSessionState.from_dict(runtime_state)


def mode_show_impl(book_path: str | Path | None) -> TuiSessionState:
    """Return persisted execution-mode runtime state."""

    _manager, state = _load_mode_state(book_path)
    return state


def mode_set_impl(
    book_path: str | Path | None,
    mode_name: str,
    *,
    turns: int | None = None,
) -> TuiSessionState:
    """Persist execution mode updates and return the new runtime state."""

    requested = parse_execution_mode(mode_name)
    if requested is None:
        raise ValueError("Unsupported execution mode.")

    manager, state = _load_mode_state(book_path)
    config = state.mode_config.with_mode(requested)
    if requested is ExecutionMode.AUTOPILOT:
        if turns is not None:
            config = config.with_autopilot_limit(turns)
        remaining = config.max_autopilot_turns
    else:
        remaining = 0

    updated = TuiSessionState(
        mode_config=config,
        autopilot_turns_remaining=remaining,
    )

    # Merge mode updates into existing runtime metadata to avoid dropping
    # sibling keys such as rolling session summaries.
    runtime_state = manager.load_runtime_state()
    runtime_state.update(updated.to_dict())
    manager.save_runtime_state(runtime_state)
    return updated


def state_audit_impl(
    book_path: str | Path | None,
    *,
    entity_type: str | None,
    entity_id: str | None,
    limit: int,
    store: NarrativeStateStore | None = None,
) -> StateAuditResult:
    """Query narrative-state audit entries with optional filters."""

    resolved_store = store or NarrativeStateStore(_resolve_book_path(book_path))
    audit_log = resolved_store._get_audit_log()
    if audit_log is None:
        return StateAuditResult(enabled=False, entries=[])

    entries = audit_log.query_entries(
        entity_type=entity_type,
        entity_id=entity_id,
        limit=max(1, limit),
    )
    return StateAuditResult(enabled=True, entries=entries)


def canon_check_impl(
    book_path: str | Path | None,
    *,
    chapter: int,
    text: str,
    max_candidates: int = 12,
) -> CanonCheckResult:
    """Run canon verification for extracted candidates from raw text."""

    payload = text.strip()
    if not payload:
        raise ValueError("Text payload must not be empty.")

    normalized_chapter = max(1, chapter)
    candidates = extract_canon_candidates(
        payload,
        chapter=normalized_chapter,
        max_candidates=max(1, max_candidates),
    )
    candidate_texts = [candidate.text for candidate in candidates]
    if not candidate_texts:
        candidate_texts = [payload]

    rows: list[CanonCheckRow] = []
    failures = 0
    for candidate_text in candidate_texts:
        result = verify_candidate_against_canon(
            book_path=_resolve_book_path(book_path),
            chapter=normalized_chapter,
            candidate_text=candidate_text,
        )
        if not result.allowed:
            failures += 1
        rows.append(
            CanonCheckRow(
                candidate=candidate_text,
                allowed=result.allowed,
                reason=result.reason,
                conflicting_fact=result.conflicting_fact,
            )
        )

    return CanonCheckResult(
        chapter=normalized_chapter,
        checked_candidates=len(candidate_texts),
        failures=failures,
        rows=rows,
    )


def state_extract_impl(
    book_path: str | Path | None,
    *,
    text: str,
    apply_patch: bool,
    actor: str = "state-extractor",
) -> StateExtractResult:
    """Extract deterministic state patch proposal and optionally apply it."""

    store = NarrativeStateStore(_resolve_book_path(book_path))
    snapshot = store.load()
    extracted = extract_state_patch(text, snapshot=snapshot)
    operations = list(extracted.patch.operations)

    verified_operations: list[PatchOperation] = operations
    verification_issues: list[str] = []
    retry_performed = False
    if operations:
        first_pass_operations, first_pass_issues = _verify_patch_operations(
            snapshot,
            operations,
        )
        verified_operations = first_pass_operations
        verification_issues = first_pass_issues

        if first_pass_issues:
            retry_performed = True
            repaired = _reorder_patch_operations(operations)
            retry_operations, retry_issues = _verify_patch_operations(
                snapshot, repaired
            )
            if len(retry_operations) >= len(first_pass_operations):
                verified_operations = retry_operations
                verification_issues = retry_issues

    dropped_operations = max(0, len(operations) - len(verified_operations))
    verification_passed = dropped_operations == 0 and not verification_issues

    effective_patch = StatePatch(
        operations=verified_operations,
        description=extracted.patch.description,
    )
    extracted_effective = StateExtractionResult(
        patch=effective_patch,
        events=extracted.events,
    )

    if not apply_patch or not verified_operations:
        return StateExtractResult(
            extracted=extracted_effective,
            applied=False,
            applied_version=None,
            verification_passed=verification_passed,
            verification_issues=verification_issues,
            retry_performed=retry_performed,
            dropped_operations=dropped_operations,
        )

    updated = None
    # Apply one operation at a time so strict validators can resolve
    # dependencies (e.g., add location before assigning character location).
    for operation in verified_operations:
        try:
            updated = store.apply_patch(
                type(extracted.patch)(
                    operations=[operation],
                    description=extracted.patch.description,
                ),
                actor=actor,
            )
        except Exception as exc:
            verification_issues = [*verification_issues, str(exc)]
            verification_passed = False
            break

    if updated is None:
        return StateExtractResult(
            extracted=extracted_effective,
            applied=False,
            applied_version=None,
            verification_passed=verification_passed,
            verification_issues=verification_issues,
            retry_performed=retry_performed,
            dropped_operations=dropped_operations,
        )

    return StateExtractResult(
        extracted=extracted_effective,
        applied=True,
        applied_version=updated.version,
        verification_passed=verification_passed,
        verification_issues=verification_issues,
        retry_performed=retry_performed,
        dropped_operations=dropped_operations,
    )
