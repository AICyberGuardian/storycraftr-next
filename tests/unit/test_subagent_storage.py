import pytest
from pathlib import Path

from storycraftr.subagents.storage import (
    subagent_root,
    ensure_storage_dirs,
    role_file_path,
    SUBAGENT_ROOT,
    LOGS_DIRNAME,
)


def test_subagent_root_basic():
    """Verify that subagent_root correctly appends SUBAGENT_ROOT to the given path."""
    book_path = "/home/user/mybook"
    expected = Path(book_path) / SUBAGENT_ROOT
    result = subagent_root(book_path)
    assert result == expected


def test_subagent_root_empty_string():
    """Verify that subagent_root handles empty strings correctly."""
    book_path = ""
    expected = Path(book_path) / SUBAGENT_ROOT
    result = subagent_root(book_path)
    assert result == expected


def test_ensure_storage_dirs_creates_directories(tmp_path: Path):
    """Verify ensure_storage_dirs creates the root and logs directories."""
    book_path = str(tmp_path)

    # Run the function
    result_root = ensure_storage_dirs(book_path)

    # Assertions
    expected_root = tmp_path / SUBAGENT_ROOT
    expected_logs = expected_root / LOGS_DIRNAME

    assert result_root == expected_root
    assert expected_root.exists()
    assert expected_root.is_dir()
    assert expected_logs.exists()
    assert expected_logs.is_dir()


def test_ensure_storage_dirs_idempotent(tmp_path: Path):
    """Verify calling ensure_storage_dirs multiple times does not raise errors (exist_ok=True)."""
    book_path = str(tmp_path)

    # Call once
    ensure_storage_dirs(book_path)

    # Call twice
    # If exist_ok=False was used, this would raise FileExistsError
    result_root = ensure_storage_dirs(book_path)

    expected_root = tmp_path / SUBAGENT_ROOT
    expected_logs = expected_root / LOGS_DIRNAME

    assert result_root == expected_root
    assert expected_root.exists()
    assert expected_logs.exists()


def test_role_file_path():
    """Verify role_file_path joins root and slug with .yaml extension."""
    root = Path("/some/path")
    slug = "editor"

    expected = Path("/some/path/editor.yaml")
    result = role_file_path(root, slug)

    assert result == expected
