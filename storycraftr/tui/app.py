from __future__ import annotations

import asyncio
import io
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DirectoryTree, Footer, Header, Input, Label, RichLog, Static

from storycraftr.agent.agents import (
    LangChainAssistant,
    create_message,
    create_or_get_assistant,
    get_thread,
)
from storycraftr.chat.commands import CommandContext, handle_command
from storycraftr.chat.module_runner import ModuleCommandError, run_module_command
from storycraftr.chat.session import SessionManager
from storycraftr.utils.core import BookConfig, load_book_config
from storycraftr.tui.openrouter_models import (
    OpenRouterModel,
    fetch_free_openrouter_models,
)


def _resolve_book_path(book_path: str | None) -> Path:
    return Path(
        book_path or os.getenv("STORYCRAFTR_BOOK_PATH") or os.getcwd()
    ).resolve()


def _parse_book_path_from_argv(argv: list[str]) -> str | None:
    if len(argv) >= 3 and argv[1] in {"--book-path", "-b"}:
        return argv[2]
    if len(argv) == 2 and not argv[1].startswith("-"):
        return argv[1]
    return None


class TuiApp(App[None]):
    """Minimal Textual shell that reuses StoryCraftr assistant and CLI dispatch."""

    TITLE = "StoryCraftr TUI"
    SUB_TITLE = "v0.1"
    CSS = """
    #title { padding: 0 1; text-style: bold; }
    #model-status { padding: 0 1; color: $accent; }
    #body { height: 1fr; }
    .sidebar { width: 25%; border: round $surface; padding: 0 1; }
    .main { width: 75%; border: round $surface; padding: 0 1; }
    .pane-title { padding: 0 0 1 0; text-style: bold; }
    #project-tree, #output { height: 1fr; }
    #command-input { dock: bottom; margin: 1 0 0 0; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+p", "command_palette", "Command Palette"),
    ]

    _FREE_MODEL_CACHE_TTL_SECONDS = 300

    def __init__(self, *, book_path: str | None = None) -> None:
        super().__init__()
        self.book_path = _resolve_book_path(book_path)
        self.config: BookConfig | None = None
        self.assistant: LangChainAssistant | None = None
        self.thread_id: str | None = None
        self.model_override: str | None = None
        self._cached_free_models: list[OpenRouterModel] = []
        self._cached_free_models_at: float = 0.0
        self.transcript: list[dict[str, Any]] = []
        self.session_manager = SessionManager(str(self.book_path))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("StoryCraftr TUI", id="title")
        yield Static("", id="model-status")
        with Horizontal(id="body"):
            with Vertical(classes="sidebar"):
                yield Label("Project", classes="pane-title")
                yield DirectoryTree(str(self.book_path), id="project-tree")
            with Vertical(classes="main"):
                yield Label("Chat / Output", classes="pane-title")
                yield RichLog(id="output", wrap=True, markup=True)
        yield Input(
            placeholder="Ask StoryCraftr or run /outline ...", id="command-input"
        )
        yield Footer()

    async def on_mount(self) -> None:
        output = self.query_one(RichLog)
        user_input = self.query_one(Input)
        user_input.focus()
        self.config = load_book_config(str(self.book_path))
        if self.config is None:
            output.write(
                "[red]No project config found. Use a StoryCraftr/PaperCraftr project or --book-path.[/red]"
            )
            user_input.disabled = True
            return

        self.model_override = self.config.llm_model
        self._update_model_status_widget()
        output.write(f"[cyan]Loading assistant for {self.book_path}...[/cyan]")
        try:
            self.assistant = await asyncio.to_thread(
                create_or_get_assistant, str(self.book_path)
            )
            self.thread_id = get_thread(str(self.book_path)).id
        except Exception as exc:  # pragma: no cover
            output.write(f"[red]Assistant initialization failed: {exc}[/red]")
            user_input.disabled = True
            return
        output.write(
            "[green]Ready. Enter prompts or slash commands (e.g. /agents, /outline ...).[/green]"
        )

    @on(Input.Submitted)
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        log = self.query_one(RichLog)
        log.write(f"[bold cyan]You:[/bold cyan] {text}")
        event.input.disabled = True
        try:
            if text.startswith("/"):
                log.write(
                    f"[bold magenta]CLI:[/bold magenta] {await self._dispatch_slash_command(text)}"
                )
            else:
                response, streamed = await self._run_assistant_turn(text)
                if not streamed:
                    log.write(f"[bold green]Assistant:[/bold green] {response}")
                self.transcript.append({"user": text, "answer": response})
        except Exception as exc:  # pragma: no cover
            log.write(f"[red]Error: {exc}[/red]")
        finally:
            event.input.disabled = False
            event.input.focus()

    async def _run_assistant_turn(self, prompt: str) -> tuple[str, bool]:
        if not self.assistant or not self.thread_id:
            return "Assistant is not initialized.", False
        stream_fn = getattr(self.assistant, "astream", None)
        if callable(stream_fn):
            parts: list[str] = []
            self.query_one(RichLog).write("[bold green]Assistant:[/bold green]")
            async for token in stream_fn(prompt):
                text = str(token)
                if text:
                    parts.append(text)
                    self.query_one(RichLog).write(text)
            return "".join(parts).strip(), True
        response = await asyncio.to_thread(self._invoke_assistant_sync, prompt)
        return response, False

    def _invoke_assistant_sync(self, prompt: str) -> str:
        if self.assistant is None or self.thread_id is None:
            return "Assistant is not initialized."
        return create_message(
            book_path=str(self.book_path),
            thread_id=self.thread_id,
            content=prompt,
            assistant=self.assistant,
            force_single_answer=True,
        )

    async def _dispatch_slash_command(self, raw: str) -> str:
        payload = raw[1:].strip()
        if not payload:
            return "Empty slash command."
        try:
            parts = shlex.split(payload)
        except ValueError as exc:
            return f"Command parse error: {exc}"
        command = parts[0].lower()
        args = parts[1:]

        if command == "help":
            return self._build_help_text()

        if command == "status":
            return await self._build_status_text()

        if command == "chat":
            return "Already in chat mode."

        if command == "model-list":
            return await asyncio.to_thread(self._render_model_list)

        if command == "model-change":
            if not args:
                return "Usage: /model-change <model_id>"
            return await self._change_model(args[0])

        if command == "session":
            return await asyncio.to_thread(
                self._run_chat_command_capture,
                f":{payload}",
            )

        if command in {"agents", "subagents", "sub-agent"}:
            if command == "agents":
                return await asyncio.to_thread(
                    self._run_chat_command_capture, ":sub-agent !list"
                )
            if not args:
                return "Usage: /sub-agent !list | !status | !<command> [args]"
            return await asyncio.to_thread(
                self._run_chat_command_capture, f":sub-agent {' '.join(args)}"
            )

        return await asyncio.to_thread(self._run_module_command_capture, payload)

    def _active_model(self) -> str:
        if self.model_override:
            return self.model_override
        if self.config and self.config.llm_model:
            return self.config.llm_model
        return "<unknown>"

    def _active_provider(self) -> str:
        if self.config and self.config.llm_provider:
            return self.config.llm_provider
        return "<unknown>"

    def _update_model_status_widget(self) -> None:
        self.query_one("#model-status", Static).update(
            f"Provider: {self._active_provider()} | Model: {self._active_model()}"
        )

    def _build_help_text(self) -> str:
        lines = [
            "TUI Slash Commands",
            "- /help - show this command reference",
            "- /status - show project/assistant/runtime status",
            "- /session list",
            "- /session save <name>",
            "- /session load <name>",
            "- /sub-agent !list",
            "- /sub-agent !status",
            "- /sub-agent !<command>",
            "- /agents - alias for /sub-agent !list",
            "- /model-list - list free OpenRouter models",
            "- /model-change <model_id> - switch active model for this TUI session",
            "- /outline ... /chapters ... /worldbuilding ... - routed to existing CLI module commands",
        ]
        return "\n".join(lines)

    async def _build_status_text(self) -> str:
        lines = [
            "TUI Status",
            f"- Project: {self.book_path}",
            f"- Provider: {self._active_provider()}",
            f"- Model: {self._active_model()}",
            f"- Thread: {self.thread_id or '<none>'}",
            f"- Transcript turns: {len(self.transcript)}",
        ]
        chat_status = await asyncio.to_thread(self._run_chat_command_capture, ":status")
        if chat_status:
            lines.extend(["", "Assistant Retrieval Status", chat_status])
        return "\n".join(lines)

    def _openrouter_api_key(self) -> str | None:
        if self.config and self.config.llm_api_key_env:
            candidate = os.getenv(self.config.llm_api_key_env)
            if candidate:
                return candidate
        return os.getenv("OPENROUTER_API_KEY")

    def _get_free_models(self, *, force_refresh: bool = False) -> list[OpenRouterModel]:
        now = time.time()
        if (
            not force_refresh
            and self._cached_free_models
            and (now - self._cached_free_models_at) < self._FREE_MODEL_CACHE_TTL_SECONDS
        ):
            return self._cached_free_models

        models = fetch_free_openrouter_models(api_key=self._openrouter_api_key())
        self._cached_free_models = models
        self._cached_free_models_at = now
        return models

    def _render_model_list(self) -> str:
        try:
            models = self._get_free_models(force_refresh=True)
        except Exception as exc:
            if self._cached_free_models:
                lines = [
                    f"Failed to refresh OpenRouter models: {exc}",
                    "Using cached free model list:",
                ]
                lines.extend(
                    f"- {model.model_id} - {model.label}"
                    for model in self._cached_free_models
                )
                return "\n".join(lines)
            return f"Failed to fetch OpenRouter models: {exc}"

        if not models:
            return "No free OpenRouter models were found in the current API response."

        lines = ["Free OpenRouter Models"]
        lines.extend(f"- {model.model_id} - {model.label}" for model in models)
        return "\n".join(lines)

    async def _change_model(self, model_id: str) -> str:
        requested = model_id.strip()
        if not requested:
            return "Usage: /model-change <model_id>"

        validated = False
        validation_note = ""
        try:
            free_models = await asyncio.to_thread(self._get_free_models)
            if free_models:
                free_ids = {model.model_id for model in free_models}
                validated = requested in free_ids
                if not validated:
                    return (
                        "Model is not in the current free OpenRouter model list. "
                        "Use /model-list to inspect valid IDs."
                    )
                validation_note = "Validated against current free OpenRouter list."
        except Exception as exc:
            validation_note = (
                f"Validation skipped due to model-list fetch failure: {exc}"
            )

        previous_model = self._active_model()
        previous_assistant = self.assistant
        previous_override = self.model_override

        try:
            new_assistant = await asyncio.to_thread(
                create_or_get_assistant,
                str(self.book_path),
                requested,
            )
        except Exception as exc:
            self.assistant = previous_assistant
            self.model_override = previous_override
            self._update_model_status_widget()
            return f"Failed to change model to '{requested}': {exc}"

        self.assistant = new_assistant
        self.model_override = requested
        if self.thread_id is None:
            self.thread_id = get_thread(str(self.book_path)).id
        self._update_model_status_widget()

        continuity = f"Retained thread id {self.thread_id} and {len(self.transcript)} transcript turns."
        provider_note = ""
        if self._active_provider() != "openrouter":
            provider_note = (
                " Current provider is not openrouter; this override still applies "
                "for the active TUI assistant session."
            )

        return (
            f"Model changed: {previous_model} -> {requested}. "
            f"{validation_note} {continuity}{provider_note}"
        ).strip()

    def _run_chat_command_capture(self, command_text: str) -> str:
        stream = io.StringIO()
        command_console = Console(file=stream, force_terminal=False, no_color=True)
        ctx = CommandContext(
            console=command_console,
            session_manager=self.session_manager,
            transcript=self.transcript,
            assistant=self.assistant,
            book_path=str(self.book_path),
        )
        result = handle_command(command_text, ctx)
        if isinstance(result, list):
            self.transcript = list(result)
        return stream.getvalue().strip() or "Command completed."

    def _run_module_command_capture(self, payload: str) -> str:
        stream = io.StringIO()
        command_console = Console(file=stream, force_terminal=False, no_color=True)
        try:
            run_module_command(
                payload, console=command_console, book_path=str(self.book_path)
            )
        except ModuleCommandError as exc:
            return str(exc)
        return stream.getvalue().strip() or "Command completed."


if __name__ == "__main__":
    TuiApp(book_path=_parse_book_path_from_argv(sys.argv)).run()
