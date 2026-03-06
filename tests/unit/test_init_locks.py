from __future__ import annotations

from contextlib import contextmanager

from storycraftr.init import init_structure_paper, init_structure_story


def test_init_structure_story_uses_project_write_lock(monkeypatch, tmp_path):
    calls: list[str] = []

    @contextmanager
    def fake_lock(book_path: str, **_kwargs):
        calls.append(book_path)
        yield tmp_path / ".storycraftr" / "project.lock"

    monkeypatch.setattr("storycraftr.init.project_write_lock", fake_lock)
    monkeypatch.setattr(
        "storycraftr.init.folder_story.files_to_create",
        [{"folder": "chapters", "filename": "chapter_1.md", "content": "Hello"}],
    )
    monkeypatch.setattr(
        "storycraftr.init.ensure_local_docs", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "storycraftr.init.seed_default_roles", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "storycraftr.init.create_or_get_assistant", lambda *_args, **_kwargs: None
    )

    init_structure_story(
        book_path=str(tmp_path),
        license="CC BY",
        primary_language="en",
        alternate_languages=[],
        default_author="Author",
        genre="fantasy",
        behavior_content="behavior",
        reference_author="",
        cli_name="storycraftr",
        llm_provider="fake",
        llm_model="offline",
        llm_endpoint="",
        llm_api_key_env="",
        temperature=0.0,
        request_timeout=30,
        embed_model="fake",
        embed_device="cpu",
        embed_cache_dir="",
    )

    assert calls == [str(tmp_path)]


def test_init_structure_paper_uses_project_write_lock(monkeypatch, tmp_path):
    calls: list[str] = []

    @contextmanager
    def fake_lock(book_path: str, **_kwargs):
        calls.append(book_path)
        yield tmp_path / ".storycraftr" / "project.lock"

    monkeypatch.setattr("storycraftr.init.project_write_lock", fake_lock)
    monkeypatch.setattr(
        "storycraftr.init.folder_paper.files_to_create",
        [{"folder": "sections", "filename": "abstract.md", "content": "Abstract"}],
    )
    monkeypatch.setattr(
        "storycraftr.init.create_or_get_assistant", lambda *_args, **_kwargs: None
    )

    init_structure_paper(
        paper_path=str(tmp_path),
        primary_language="en",
        author="Author",
        keywords="test",
        behavior_content="behavior",
        cli_name="papercraftr",
        llm_provider="fake",
        llm_model="offline",
        llm_endpoint="",
        llm_api_key_env="",
        temperature=0.0,
        request_timeout=30,
        embed_model="fake",
        embed_device="cpu",
        embed_cache_dir="",
    )

    assert calls == [str(tmp_path)]
