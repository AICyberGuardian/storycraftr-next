from __future__ import annotations

import json

from storycraftr.agent.narrative_state import NarrativeStateStore


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

    assert snapshot.characters["Mira"]["status"] == "injured"
    assert snapshot.characters["Mira"]["location"] == "Bridge"
    assert snapshot.world["Bridge"]["integrity"] == "critical"


def test_narrative_state_store_render_prompt_block(tmp_path) -> None:
    store = NarrativeStateStore(str(tmp_path))
    path = tmp_path / "outline" / "narrative_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "characters": {"Mira": {"status": "focused"}},
                "world": {"Hangar": {"status": "sealed"}},
            }
        ),
        encoding="utf-8",
    )

    block = store.render_prompt_block()

    assert '"characters"' in block
    assert '"Mira"' in block
    assert '"Hangar"' in block


def test_narrative_state_store_handles_invalid_json(tmp_path) -> None:
    store = NarrativeStateStore(str(tmp_path))
    path = tmp_path / "outline" / "narrative_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")

    snapshot = store.load()

    assert snapshot.characters == {}
    assert snapshot.world == {}
