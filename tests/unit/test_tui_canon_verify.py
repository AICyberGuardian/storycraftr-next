from __future__ import annotations

from storycraftr.tui.canon import add_fact
from storycraftr.tui.canon_verify import verify_candidate_against_canon


def test_verify_candidate_rejects_duplicate(tmp_path) -> None:
    add_fact(str(tmp_path), chapter=1, text="Mira is the ship navigator.")

    result = verify_candidate_against_canon(
        book_path=str(tmp_path),
        chapter=1,
        candidate_text="Mira is the ship navigator.",
    )

    assert result.allowed is False
    assert result.reason == "duplicate"


def test_verify_candidate_rejects_negation_conflict(tmp_path) -> None:
    add_fact(str(tmp_path), chapter=1, text="Mira is the ship navigator.")

    result = verify_candidate_against_canon(
        book_path=str(tmp_path),
        chapter=1,
        candidate_text="Mira is not the ship navigator.",
    )

    assert result.allowed is False
    assert result.reason == "negation-conflict"


def test_verify_candidate_allows_new_fact(tmp_path) -> None:
    add_fact(str(tmp_path), chapter=1, text="Mira is the ship navigator.")

    result = verify_candidate_against_canon(
        book_path=str(tmp_path),
        chapter=1,
        candidate_text="The lower deck is flooded.",
    )

    assert result.allowed is True
    assert result.reason == "ok"
