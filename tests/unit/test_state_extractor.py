from __future__ import annotations

from storycraftr.agent.narrative_state import CharacterState, NarrativeStateSnapshot
from storycraftr.agent.state_extractor import extract_state_patch


def test_extract_state_patch_adds_character_and_location() -> None:
    result = extract_state_patch(
        "Elias entered the bridge.",
        snapshot=NarrativeStateSnapshot(),
    )

    ops = result.patch.operations
    assert any(op.entity_type == "location" and op.operation == "add" for op in ops)
    assert any(op.entity_type == "character" and op.operation == "add" for op in ops)
    assert any(event.kind == "character_location" for event in result.events)


def test_extract_state_patch_updates_existing_character_location() -> None:
    snapshot = NarrativeStateSnapshot(
        characters={
            "elias": CharacterState(name="Elias", location="dock", inventory=[])
        },
        locations={
            "dock": {"name": "Dock"},
            "bridge": {"name": "Bridge"},
        },
    )

    result = extract_state_patch(
        "Elias entered the bridge.",
        snapshot=snapshot,
    )

    update_ops = [op for op in result.patch.operations if op.operation == "update"]
    assert len(update_ops) == 1
    assert update_ops[0].entity_id == "elias"
    assert update_ops[0].data == {"location": "bridge"}


def test_extract_state_patch_removes_dropped_item_from_inventory() -> None:
    snapshot = NarrativeStateSnapshot(
        characters={
            "elias": CharacterState(
                name="Elias",
                location="bridge",
                inventory=["pistol", "key"],
            )
        },
        locations={"bridge": {"name": "Bridge"}},
    )

    result = extract_state_patch(
        "Elias dropped his pistol.",
        snapshot=snapshot,
    )

    update_ops = [op for op in result.patch.operations if op.operation == "update"]
    assert len(update_ops) == 1
    assert update_ops[0].data == {"inventory": ["key"]}
