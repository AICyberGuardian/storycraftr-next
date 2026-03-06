from __future__ import annotations

import json
from contextlib import contextmanager

from storycraftr.utils.cleanup import cleanup_vector_stores


def _write_config(tmp_path) -> None:
    config = {
        "book_name": "Test",
        "primary_language": "en",
        "llm_provider": "fake",
        "llm_model": "offline-model",
    }
    (tmp_path / "storycraftr.json").write_text(json.dumps(config), encoding="utf-8")


def test_cleanup_vector_stores_uses_project_write_lock(monkeypatch, tmp_path):
    _write_config(tmp_path)
    vector_dir = tmp_path / "vector_store"
    vector_dir.mkdir(parents=True)
    (vector_dir / "marker.txt").write_text("x", encoding="utf-8")

    calls: list[str] = []

    @contextmanager
    def fake_lock(book_path: str, *, config=None, **_kwargs):
        calls.append(book_path)
        yield tmp_path / ".storycraftr" / "project.lock"

    monkeypatch.setattr("storycraftr.utils.cleanup.project_write_lock", fake_lock)

    cleanup_vector_stores(str(tmp_path))

    assert calls == [str(tmp_path)]
    assert not vector_dir.exists()
