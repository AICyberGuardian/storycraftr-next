from __future__ import annotations

from pathlib import Path

import pytest

from storycraftr.tui.canon import (
    add_fact,
    canon_file_path,
    clear_chapter_facts,
    list_facts,
    load_canon,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_canon_returns_empty_schema_when_file_missing(tmp_path) -> None:
    data = load_canon(str(tmp_path))

    assert data["version"] == 1
    assert data["chapters"] == {}


def test_add_fact_creates_canon_file_when_missing(tmp_path) -> None:
    fact = add_fact(str(tmp_path), chapter=1, text="Alex is the active POV.")

    assert fact.id == "fact-001"
    assert canon_file_path(str(tmp_path)).exists()


def test_add_and_list_facts_by_chapter(tmp_path) -> None:
    add_fact(str(tmp_path), chapter=1, text="The control room is dark.")
    add_fact(str(tmp_path), chapter=2, text="Mira has the access key.")

    chapter_one = list_facts(str(tmp_path), chapter=1)
    all_facts = list_facts(str(tmp_path))

    assert len(chapter_one) == 1
    assert chapter_one[0].text == "The control room is dark."
    assert len(all_facts) == 2


def test_clear_chapter_facts_removes_only_one_chapter(tmp_path) -> None:
    add_fact(str(tmp_path), chapter=1, text="Fact A")
    add_fact(str(tmp_path), chapter=1, text="Fact B")
    add_fact(str(tmp_path), chapter=2, text="Fact C")

    removed = clear_chapter_facts(str(tmp_path), chapter=1)

    assert removed == 2
    assert list_facts(str(tmp_path), chapter=1) == []
    assert len(list_facts(str(tmp_path), chapter=2)) == 1


def test_load_canon_malformed_yaml_raises_actionable_error(tmp_path) -> None:
    _write(tmp_path / "outline" / "canon.yml", "version: [")

    with pytest.raises(RuntimeError) as exc_info:
        load_canon(str(tmp_path))

    assert "Malformed canon YAML" in str(exc_info.value)
