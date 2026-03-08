from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from storycraftr.agent.execution_mode import ExecutionMode, parse_execution_mode
from storycraftr.agent.narrative_state import NarrativeStateStore
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

    if not apply_patch or not extracted.patch.operations:
        return StateExtractResult(
            extracted=extracted,
            applied=False,
            applied_version=None,
        )

    updated = None
    # Apply one operation at a time so strict validators can resolve
    # dependencies (e.g., add location before assigning character location).
    for operation in extracted.patch.operations:
        updated = store.apply_patch(
            type(extracted.patch)(
                operations=[operation],
                description=extracted.patch.description,
            ),
            actor=actor,
        )

    if updated is None:
        return StateExtractResult(
            extracted=extracted,
            applied=False,
            applied_version=None,
        )

    return StateExtractResult(
        extracted=extracted,
        applied=True,
        applied_version=updated.version,
    )
