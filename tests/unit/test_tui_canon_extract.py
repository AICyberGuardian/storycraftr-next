from __future__ import annotations

from storycraftr.tui.canon_extract import extract_canon_candidates


def test_extract_canon_candidates_returns_fact_like_sentences() -> None:
    response = (
        "Mira is the ship navigator. "
        "The engine room was sealed after dusk. "
        "Try adding more sensory language in the next scene."
    )

    candidates = extract_canon_candidates(response, chapter=2, max_candidates=5)

    assert len(candidates) == 2
    assert candidates[0].chapter == 2
    assert candidates[0].text == "Mira is the ship navigator."
    assert candidates[1].text == "The engine room was sealed after dusk."


def test_extract_canon_candidates_deduplicates_and_caps() -> None:
    response = (
        "Alex is the active POV. "
        "Alex is the active POV. "
        "The control room is dark. "
        "The radio tower is unstable."
    )

    candidates = extract_canon_candidates(response, chapter=1, max_candidates=2)

    assert len(candidates) == 2
    assert candidates[0].text == "Alex is the active POV."
    assert candidates[1].text == "The control room is dark."
