from pathlib import Path

import pytest

from storycraftr.utils.markdown import (
    append_to_markdown,
    read_from_markdown,
    save_to_markdown,
)


def test_save_to_markdown_creates_backup_when_file_exists(tmp_path):
    book_path = tmp_path
    file_name = "test.md"
    target = book_path / file_name
    target.write_text("# Old\n\nOld content", encoding="utf-8")

    saved = save_to_markdown(str(book_path), file_name, "Test Header", "Test content")

    assert saved == str(target)
    assert target.read_text(encoding="utf-8") == "# Test Header\n\nTest content"
    backup = target.with_suffix(".md.back")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "# Old\n\nOld content"


def test_save_to_markdown_no_backup_for_new_file(tmp_path):
    book_path = tmp_path
    file_name = "new.md"
    target = book_path / file_name

    save_to_markdown(str(book_path), file_name, "Test Header", "Test content")

    assert target.read_text(encoding="utf-8") == "# Test Header\n\nTest content"
    assert not target.with_suffix(".md.back").exists()


def test_append_to_markdown_success(tmp_path):
    book_path = tmp_path
    folder_name = "test_folder"
    file_name = "test.md"
    target = book_path / folder_name / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("start", encoding="utf-8")

    append_to_markdown(str(book_path), folder_name, file_name, "Appended content")

    assert target.read_text(encoding="utf-8") == "start\n\nAppended content"


def test_append_to_markdown_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        append_to_markdown(str(tmp_path), "test_folder", "test.md", "Appended content")


def test_read_from_markdown_success(tmp_path):
    target = tmp_path / "test_folder" / "test.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("File content", encoding="utf-8")

    content = read_from_markdown(str(tmp_path), "test_folder", "test.md")

    assert content == "File content"


def test_read_from_markdown_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_from_markdown(str(tmp_path), "test_folder", "test.md")
