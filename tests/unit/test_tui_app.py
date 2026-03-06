from __future__ import annotations

import asyncio

import pytest


def _load_tui_app():
    try:
        from storycraftr.tui.app import TuiApp
    except Exception as exc:  # pragma: no cover - environment-specific import edge
        pytest.skip(f"Textual TUI import unavailable in this test environment: {exc}")
    return TuiApp


def test_tui_help_includes_required_commands(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    help_text = app._build_help_text()

    assert "/help" in help_text
    assert "/status" in help_text
    assert "/session list" in help_text
    assert "/session save <name>" in help_text
    assert "/session load <name>" in help_text
    assert "/sub-agent !list" in help_text
    assert "/sub-agent !status" in help_text
    assert "/sub-agent !<command>" in help_text
    assert "/model-list" in help_text
    assert "/model-change <model_id>" in help_text


def test_dispatch_model_change_requires_model_id(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/model-change"))

    assert result == "Usage: /model-change <model_id>"
