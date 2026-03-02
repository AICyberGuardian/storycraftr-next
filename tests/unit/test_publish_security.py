import sys
from unittest.mock import MagicMock, patch

# Mock dependencies before they are imported by storycraftr
sys.modules["click"] = MagicMock()
sys.modules["rich"] = MagicMock()
sys.modules["rich.console"] = MagicMock()
sys.modules["rich.progress"] = MagicMock()
sys.modules["storycraftr.utils.core"] = MagicMock()
sys.modules["storycraftr.utils.markdown"] = MagicMock()
sys.modules["storycraftr.agent.agents"] = MagicMock()
sys.modules["storycraftr.agent.paper.references"] = MagicMock()

import pytest
from pathlib import Path

# Now import the function to test
from storycraftr.cmd.paper.publish import generate_pdf


def test_generate_pdf_security_separator(tmp_path):
    # Create a dummy book path and some markdown files, including one with a leading hyphen
    book_path = tmp_path / "my_book"
    book_path.mkdir()

    # Create markdown files
    (book_path / "chapter1.md").write_text("# Chapter 1")
    (book_path / "-evil-option.md").write_text("# Evil")

    pandoc_path = "/usr/bin/pandoc"
    xelatex_path = "/usr/bin/xelatex"

    with patch("storycraftr.cmd.paper.publish.subprocess.run") as mock_run, patch(
        "storycraftr.cmd.paper.publish.load_book_config"
    ) as mock_load_config:
        mock_load_config.return_value = {"title": "Test Book"}

        # Configure mock_run to return a success result
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        generate_pdf(str(book_path), pandoc_path, xelatex_path)

        # Verify the call to subprocess.run
        assert mock_run.called
        args, kwargs = mock_run.call_args
        cmd = args[0]

        # Check that "--" is in the command
        assert "--" in cmd

        # Find index of "--"
        separator_index = cmd.index("--")

        # Ensure filenames are AFTER the separator
        filenames = [str(f) for f in Path(book_path).glob("**/*.md")]
        for filename in filenames:
            filename_str = str(filename)
            assert filename_str in cmd
            assert cmd.index(filename_str) > separator_index

        # Specifically check for the file starting with a hyphen
        evil_file = str(book_path / "-evil-option.md")
        assert evil_file in cmd
        assert cmd.index(evil_file) > separator_index
