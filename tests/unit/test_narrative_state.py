from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from storycraftr.agent.narrative_state import (
    CharacterState,
    NarrativeStateStore,
    SceneDirective,
    StateValidationError,
)


def test_narrative_state_store_upsert_and_load(tmp_path) -> None:
    store = NarrativeStateStore(str(tmp_path))

    store.upsert_character(
        "Mira",
        {
            "status": "injured",
            "location": "Bridge",
            "inventory": ["key", "medkit"],
        },
    )
    store.upsert_world("Bridge", {"integrity": "critical"})

    snapshot = store.load()

    # Characters are now Pydantic models, access via dot notation
    assert "Mira" in snapshot.characters
    assert snapshot.characters["Mira"].status == "injured"
    assert snapshot.characters["Mira"].location == "Bridge"
    assert snapshot.characters["Mira"].inventory == ["key", "medkit"]
    # World is still a legacy dict
    assert snapshot.world["Bridge"]["integrity"] == "critical"


def test_narrative_state_store_render_prompt_block(tmp_path) -> None:
    store = NarrativeStateStore(str(tmp_path))
    path = tmp_path / "outline" / "narrative_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "characters": {
                    "Mira": {
                        "name": "Mira",  # Required field
                        "status": "alive",  # Use valid status
                    }
                },
                "world": {"Hangar": {"status": "sealed"}},
            }
        ),
        encoding="utf-8",
    )

    block = store.render_prompt_block()

    assert '"characters"' in block
    assert '"Mira"' in block
    assert '"Hangar"' in block
    assert '"alive"' in block  # Verify it loaded the character status


def test_narrative_state_store_handles_invalid_json(tmp_path) -> None:
    store = NarrativeStateStore(str(tmp_path))
    path = tmp_path / "outline" / "narrative_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")

    with pytest.raises(StateValidationError, match="Failed to load narrative state"):
        store.load()


def test_character_state_supports_story_engine_fields() -> None:
    character = CharacterState(
        name="Mira",
        ghost="Abandoned during the first evacuation.",
        character_lie="Trust always ends in betrayal.",
        external_want="Secure command of the bridge.",
        internal_need="Accept shared leadership.",
    )

    assert character.ghost is not None
    assert "evacuation" in character.ghost.lower()
    assert "trust" in (character.character_lie or "").lower()


def test_scene_directive_requires_core_fields() -> None:
    directive = SceneDirective(
        goal="Expose the sabotage before dawn.",
        conflict="The quartermaster blocks records access.",
        stakes="If delayed, the fleet launches compromised.",
        outcome="No-and: access denied and evidence is erased.",
    )

    assert "sabotage" in directive.goal.lower()

    with pytest.raises(ValidationError):
        SceneDirective(
            goal="",
            conflict="Active resistance.",
            stakes="High cost.",
            outcome="Failure.",
        )


# ============================================================================
# PROMPT VERSION HEADER TESTS (DSVL Phase 2C)
# ============================================================================


def test_render_prompt_block_includes_version_header(tmp_path) -> None:
    """Test that render_prompt_block() includes version and timestamp header."""
    from storycraftr.agent.narrative_state import (
        NarrativeStateSnapshot,
        CharacterState,
    )

    store = NarrativeStateStore(str(tmp_path))

    # Create a snapshot with known version and data
    snapshot = NarrativeStateSnapshot(
        version=5,
        characters={"alice": CharacterState(name="Alice", status="alive")},
    )
    store.save(snapshot)

    result = store.render_prompt_block()

    # Should contain version header
    assert "[Narrative State v5 as of " in result
    # Should contain JSON data after header
    assert '"characters"' in result
    assert '"alice"' in result


def test_render_prompt_block_header_format(tmp_path) -> None:
    """Test the exact format of the version header."""
    from storycraftr.agent.narrative_state import (
        NarrativeStateSnapshot,
        LocationState,
    )

    store = NarrativeStateStore(str(tmp_path))

    # Create minimal snapshot
    snapshot = NarrativeStateSnapshot(
        version=1,
        locations={"castle": LocationState(name="Castle")},
    )
    store.save(snapshot)

    result = store.render_prompt_block()

    # Header should be on first line
    lines = result.split("\n")
    assert lines[0].startswith("[Narrative State v1 as of ")
    assert lines[0].endswith("]")
    # JSON should start on second line
    assert lines[1] == "{"


def test_render_prompt_block_empty_returns_empty_string(tmp_path) -> None:
    """Test that empty state returns empty string (no header for empty data)."""
    from storycraftr.agent.narrative_state import NarrativeStateSnapshot

    store = NarrativeStateStore(str(tmp_path))

    # Save empty snapshot
    snapshot = NarrativeStateSnapshot()
    store.save(snapshot)

    result = store.render_prompt_block()

    # Empty state should return empty string
    assert result == ""


def test_render_prompt_block_truncation_preserves_header(tmp_path) -> None:
    """Test that truncation applies to JSON payload, not header."""
    from storycraftr.agent.narrative_state import (
        NarrativeStateSnapshot,
        CharacterState,
    )

    store = NarrativeStateStore(str(tmp_path))

    # Create snapshot with large data
    snapshot = NarrativeStateSnapshot(
        version=42,
        characters={
            f"char{i}": CharacterState(
                name=f"Character {i}",
                status="alive",
                location="castle",
                notes="Very long notes " * 20,
            )
            for i in range(10)
        },
    )
    store.save(snapshot)

    # Render with small max_chars
    result = store.render_prompt_block(max_chars=100)

    # Header should be present
    assert "[Narrative State v42 as of " in result
    # JSON should be truncated (ends with ...)
    assert result.endswith("...")
    # Full JSON won't fit
    assert '"char9"' not in result  # Last character won't fit


def test_render_prompt_block_version_increments(tmp_path) -> None:
    """Test that version header reflects state version after patches."""
    from storycraftr.agent.narrative_state import (
        NarrativeStateSnapshot,
        CharacterState,
        StatePatch,
        PatchOperation,
    )

    store = NarrativeStateStore(str(tmp_path), enable_audit=False)

    # Create initial snapshot
    snapshot = NarrativeStateSnapshot(
        version=1, characters={"alice": CharacterState(name="Alice", status="alive")}
    )
    store.save(snapshot)

    # Apply a patch (should increment version)
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="bob",
                data={"name": "Bob", "status": "alive"},
            )
        ]
    )
    store.apply_patch(patch, actor="test")

    result = store.render_prompt_block()

    # Version should be incremented to 2
    assert "[Narrative State v2 as of " in result
    # Should contain both characters
    assert '"alice"' in result
    assert '"bob"' in result


def test_begin_state_transaction_rolls_back_on_error(tmp_path) -> None:
    """State file should be restored when a transactional block raises."""
    from storycraftr.agent.narrative_state import (
        NarrativeStateSnapshot,
    )

    store = NarrativeStateStore(str(tmp_path))
    initial = NarrativeStateSnapshot(
        characters={"alice": CharacterState(name="Alice", status="alive")}
    )
    store.save(initial)
    original_text = store._file_path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError, match="forced_error"):
        with store.begin_state_transaction():
            modified = NarrativeStateSnapshot(
                characters={"bob": CharacterState(name="Bob", status="alive")}
            )
            store.save(modified)
            assert '"bob"' in store._file_path.read_text(encoding="utf-8")
            raise RuntimeError("forced_error")

    restored_text = store._file_path.read_text(encoding="utf-8")
    assert restored_text == original_text
    assert '"alice"' in restored_text
    assert '"bob"' not in restored_text
