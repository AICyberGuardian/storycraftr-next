from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from rich.markup import render


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


def test_toggle_tree_hides_sidebar_container(tmp_path, monkeypatch) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    class _Sidebar:
        def __init__(self) -> None:
            self.display = True

    sidebar = _Sidebar()

    def _query_one(selector, _type=None):
        assert selector == "#sidebar"
        return sidebar

    monkeypatch.setattr(app, "query_one", _query_one)

    hidden_message = app._toggle_tree_visibility()
    shown_message = app._toggle_tree_visibility()

    assert hidden_message == "Project tree hidden."
    assert shown_message == "Project tree shown."


def test_toggle_tree_returns_unavailable_when_sidebar_missing(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    def _query_one(_selector, _type=None):
        raise RuntimeError("no sidebar")

    monkeypatch.setattr(app, "query_one", _query_one)

    assert (
        app._toggle_tree_visibility()
        == "Project tree is not available in the current view."
    )


def test_change_model_skips_openrouter_validation_for_non_openrouter_provider(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.config = SimpleNamespace(llm_provider="openai", llm_model="gpt-4o")
    app.assistant = object()

    called: list[str] = []

    def _fake_create_or_get(book_path, model_id=None):
        called.append(model_id)
        return object()

    monkeypatch.setattr(
        "storycraftr.tui.app.create_or_get_assistant", _fake_create_or_get
    )

    result = asyncio.run(app._change_model("gpt-4o"))

    assert called == ["gpt-4o"]
    assert "Model changed" in result
    assert "Validation skipped: current provider is not openrouter" in result


def test_change_model_failure_does_not_raise_attribute_error(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.config = SimpleNamespace(llm_provider="openai", llm_model="gpt-4o")
    previous_assistant = object()
    app.assistant = previous_assistant
    app.model_override = "old-model"

    def _raise_create_error(book_path, model_id=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "storycraftr.tui.app.create_or_get_assistant", _raise_create_error
    )

    result = asyncio.run(app._change_model("gpt-4o"))

    assert "Failed to change model" in result
    assert "connection refused" in result
    assert app.assistant is previous_assistant
    assert app.model_override == "old-model"


def test_change_model_rejects_coroutine_result_from_factory(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.config = SimpleNamespace(llm_provider="openai", llm_model="gpt-4o")
    app.assistant = object()
    app.model_override = "old-model"

    async def _bad_factory(book_path, model_id=None):
        return object()

    monkeypatch.setattr("storycraftr.tui.app.create_or_get_assistant", _bad_factory)

    result = asyncio.run(app._change_model("some-model"))

    assert "Failed to change model" in result
    assert "returned a coroutine" in result
    assert app.model_override == "old-model"


def test_state_output_is_markup_safe_and_preserved(tmp_path, monkeypatch) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    class _FakeInput:
        def __init__(self, value: str) -> None:
            self.value = value
            self.disabled = False

        def focus(self) -> None:
            return

    class _MarkupCheckingLog:
        def __init__(self) -> None:
            self.rendered_plain: list[str] = []

        def write(self, value) -> None:
            if isinstance(value, str):
                self.rendered_plain.append(render(value).plain)
            else:
                self.rendered_plain.append(str(value))

    fake_log = _MarkupCheckingLog()

    async def _fake_dispatch(_raw: str) -> str:
        return "[Narrative State]\nActive Chapter: 1\n[/Narrative State]"

    monkeypatch.setattr(app, "_dispatch_slash_command", _fake_dispatch)
    monkeypatch.setattr(app, "query_one", lambda *_args, **_kwargs: fake_log)

    event = SimpleNamespace(input=_FakeInput("/state"), value="/state")
    asyncio.run(app.on_input_submitted(event))

    combined = "\n".join(fake_log.rendered_plain)
    assert "CLI:" in combined
    assert "[Narrative State]" in combined
    assert "[/Narrative State]" in combined


def test_error_output_is_markup_safe_when_exception_contains_brackets(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    class _FakeInput:
        def __init__(self, value: str) -> None:
            self.value = value
            self.disabled = False

        def focus(self) -> None:
            return

    class _MarkupCheckingLog:
        def __init__(self) -> None:
            self.rendered_plain: list[str] = []

        def write(self, value) -> None:
            if isinstance(value, str):
                self.rendered_plain.append(render(value).plain)
            else:
                self.rendered_plain.append(str(value))

    fake_log = _MarkupCheckingLog()

    async def _raising_dispatch(_raw: str) -> str:
        raise RuntimeError("bad [/Narrative State] [not-a-style]")

    monkeypatch.setattr(app, "_dispatch_slash_command", _raising_dispatch)
    monkeypatch.setattr(app, "query_one", lambda *_args, **_kwargs: fake_log)

    event = SimpleNamespace(input=_FakeInput("/state"), value="/state")
    asyncio.run(app.on_input_submitted(event))

    combined = "\n".join(fake_log.rendered_plain)
    assert "Error:" in combined
    assert "bad [/Narrative State] [not-a-style]" in combined
