from __future__ import annotations

import asyncio
import sys

import pytest


def _load_tui_app():
    for module_name in list(sys.modules):
        if module_name == "rich" or module_name.startswith("rich."):
            sys.modules.pop(module_name, None)
        if module_name == "textual" or module_name.startswith("textual."):
            sys.modules.pop(module_name, None)
    sys.modules.pop("storycraftr.tui.app", None)

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
    assert "/state" in help_text
    assert "/toggle-tree" in help_text
    assert "/chapter <number>" in help_text
    assert "/scene <label>" in help_text
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


def test_dispatch_chapter_requires_number(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    assert (
        asyncio.run(app._dispatch_slash_command("/chapter"))
        == "Usage: /chapter <number>"
    )
    assert (
        asyncio.run(app._dispatch_slash_command("/chapter abc"))
        == "Usage: /chapter <number>"
    )


def test_dispatch_scene_requires_label(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    assert asyncio.run(app._dispatch_slash_command("/scene")) == "Usage: /scene <label>"


def test_build_state_text_contains_injected_block(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    state_text = asyncio.run(app._build_state_text())

    assert "Narrative State" in state_text
    assert "Injected Prompt Block" in state_text
    assert "[Narrative State]" in state_text


def test_dispatch_state_command_returns_state_block(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/state"))

    assert "Narrative State" in result
    assert "Injected Prompt Block" in result
