from __future__ import annotations

from storycraftr.services.control_plane import (
    canon_check_impl,
    mode_set_impl,
    mode_show_impl,
    state_audit_impl,
    state_extract_impl,
)
from storycraftr.tui.canon import add_fact


def test_mode_show_set_round_trip(tmp_path) -> None:
    state_before = mode_show_impl(tmp_path)
    assert state_before.mode_config.mode.value == "manual"

    updated = mode_set_impl(tmp_path, "autopilot", turns=4)
    assert updated.mode_config.mode.value == "autopilot"
    assert updated.autopilot_turns_remaining == 4

    state_after = mode_show_impl(tmp_path)
    assert state_after.mode_config.mode.value == "autopilot"
    assert state_after.autopilot_turns_remaining == 4


def test_state_audit_impl_returns_entries(tmp_path) -> None:
    from storycraftr.agent.narrative_state import (
        NarrativeStateSnapshot,
        PatchOperation,
        StatePatch,
        NarrativeStateStore,
    )

    store = NarrativeStateStore(str(tmp_path))
    store.save(NarrativeStateSnapshot())
    store.apply_patch(
        StatePatch(
            operations=[
                PatchOperation(
                    operation="add",
                    entity_type="character",
                    entity_id="elias",
                    data={"name": "Elias"},
                )
            ]
        ),
        actor="service-test",
    )

    result = state_audit_impl(
        tmp_path,
        entity_type="character",
        entity_id="elias",
        limit=10,
    )

    assert result.enabled is True
    assert len(result.entries) >= 1
    assert result.entries[0].actor == "service-test"


def test_canon_check_impl_flags_conflict(tmp_path) -> None:
    add_fact(
        str(tmp_path),
        chapter=1,
        text="Mira is the pilot.",
        fact_type="character",
        source="accepted",
    )

    result = canon_check_impl(
        tmp_path,
        chapter=1,
        text="Mira is not the pilot.",
        max_candidates=3,
    )

    assert result.checked_candidates >= 1
    assert result.failures >= 1
    assert any(row.reason == "negation-conflict" for row in result.rows)


def test_state_extract_impl_can_apply_patch(tmp_path) -> None:
    result = state_extract_impl(
        tmp_path,
        text="Elias entered the bridge.",
        apply_patch=True,
        actor="service-extractor-test",
    )

    assert result.applied is True
    assert result.applied_version is not None
    assert len(result.extracted.patch.operations) >= 1

    from storycraftr.agent.narrative_state import NarrativeStateStore

    store = NarrativeStateStore(str(tmp_path))
    snapshot = store.load()
    assert "elias" in snapshot.characters
    assert snapshot.characters["elias"].location == "bridge"
