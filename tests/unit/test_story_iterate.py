import json
from types import SimpleNamespace
from unittest import mock

import pytest
from click.testing import CliRunner

from storycraftr.agent.story import iterate as iterate_agent
from storycraftr.cli import cli


def _write_project_config(project_dir, filename):
    config = {"book_name": "Demo", "llm_provider": "openai"}
    (project_dir / filename).write_text(json.dumps(config), encoding="utf-8")


def test_iterate_chapter_command_accepts_storycraftr_config(tmp_path):
    runner = CliRunner()
    project = tmp_path / "story-book"
    project.mkdir()
    _write_project_config(project, "storycraftr.json")

    with mock.patch(
        "storycraftr.cmd.story.iterate.iterate_single_chapter"
    ) as mock_iterate:
        result = runner.invoke(
            cli,
            [
                "iterate",
                "chapter",
                "--book-path",
                str(project),
                "1",
                "Tighten the final scene pacing.",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_iterate.assert_called_once_with(
        str(project), 1, "Tighten the final scene pacing."
    )


def test_iterate_chapter_command_accepts_papercraftr_config(tmp_path):
    runner = CliRunner()
    project = tmp_path / "paper-book"
    project.mkdir()
    _write_project_config(project, "papercraftr.json")

    with mock.patch(
        "storycraftr.cmd.story.iterate.iterate_single_chapter"
    ) as mock_iterate:
        result = runner.invoke(
            cli,
            [
                "iterate",
                "chapter",
                "--book-path",
                str(project),
                "2",
                "Add stronger foreshadowing in this chapter.",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_iterate.assert_called_once_with(
        str(project), 2, "Add stronger foreshadowing in this chapter."
    )


def test_iterate_single_chapter_raises_for_missing_chapter(tmp_path):
    with pytest.raises(FileNotFoundError, match="chapter-99\\.md"):
        iterate_agent.iterate_single_chapter(
            book_path=str(tmp_path), chapter_num=99, prompt="Rewrite this chapter."
        )


def test_iterate_single_chapter_targets_only_requested_file(monkeypatch, tmp_path):
    book_path = tmp_path / "book"
    chapters_dir = book_path / "chapters"
    chapters_dir.mkdir(parents=True)
    chapter_path = chapters_dir / "chapter-1.md"
    chapter_path.write_text("# Chapter 1\n\nOriginal text.", encoding="utf-8")

    captured = {}
    assistant = SimpleNamespace()
    thread = SimpleNamespace(id="thread-123")

    class DummyProgress:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, *_args, **_kwargs):
            return 1

        def update(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(iterate_agent, "Progress", DummyProgress)
    monkeypatch.setattr(iterate_agent, "create_or_get_assistant", lambda _: assistant)
    monkeypatch.setattr(iterate_agent, "get_thread", lambda _: thread)

    def fake_create_message(
        book_path, thread_id, content, assistant, progress, task_id, file_path
    ):
        captured["book_path"] = book_path
        captured["thread_id"] = thread_id
        captured["content"] = content
        captured["file_path"] = file_path
        return "Updated chapter text."

    def fake_save_to_markdown(
        book_path, file_name, header, content, progress=None, task=None
    ):
        captured["saved_book_path"] = book_path
        captured["saved_file_name"] = file_name
        captured["saved_header"] = header
        captured["saved_content"] = content
        return str(file_name)

    monkeypatch.setattr(iterate_agent, "create_message", fake_create_message)
    monkeypatch.setattr(iterate_agent, "save_to_markdown", fake_save_to_markdown)

    iterate_agent.iterate_single_chapter(
        book_path=str(book_path),
        chapter_num=1,
        prompt="Improve dialogue realism.",
    )

    assert captured["thread_id"] == "thread-123"
    assert captured["file_path"] == str(chapter_path.resolve())
    assert "Improve dialogue realism." in captured["content"]
    assert captured["saved_file_name"] == chapter_path.resolve()
    assert captured["saved_header"] == "Chapter 1"
    assert captured["saved_content"] == "Updated chapter text."
