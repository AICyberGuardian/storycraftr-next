from __future__ import annotations

import asyncio
import inspect
import io
import os
import shlex
import sys
import time
import re
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.console import Console
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
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
from storycraftr.tui.openrouter_models import (
    OpenRouterModel,
    fetch_free_openrouter_models,
)
from storycraftr.tui.state_engine import NarrativeState, NarrativeStateEngine
from storycraftr.utils.core import BookConfig, load_book_config


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
    #state-strips { height: auto; padding: 0 1; }
    #narrative-strip, #timeline-strip {
        width: 1fr;
        padding: 0 1;
        border: round $surface;
        color: $text-muted;
    }
    #body { height: 1fr; }
    #sidebar { width: 25%; border: round $surface; padding: 0 1; }
    #main-pane { width: 1fr; border: round $surface; padding: 0 1; }
    .pane-title { padding: 0 0 1 0; text-style: bold; }
    #project-tree, #output { height: 1fr; }
    #command-input { dock: bottom; margin: 1 0 0 0; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+p", "command_palette", "Command Palette"),
        Binding("ctrl+t", "toggle_tree", "Toggle Tree"),
        Binding("ctrl+l", "toggle_focus_mode", "Focus Mode"),
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
        self.state_engine = NarrativeStateEngine(book_path=str(self.book_path))
        self.session_manager = SessionManager(str(self.book_path))
        self._focus_mode_enabled = False
        self._sidebar_visible_before_focus = False
        self._state_strips_visible_before_focus = True
        self._input_history: list[str] = []
        self._history_cursor: int | None = None
        self._wizard_profile: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("StoryCraftr TUI", id="title")
        with Horizontal(id="state-strips"):
            yield Static("Narrative: loading...", id="narrative-strip")
            yield Static("Timeline: loading...", id="timeline-strip")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Label("Project", classes="pane-title")
                yield DirectoryTree(str(self.book_path), id="project-tree")
            with Vertical(id="main-pane"):
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
        output.write(
            f"[cyan]Loading assistant for {escape(str(self.book_path))}...[/cyan]"
        )
        try:
            self.assistant = await asyncio.to_thread(
                create_or_get_assistant, str(self.book_path)
            )
            self.thread_id = get_thread(str(self.book_path)).id
        except Exception as exc:  # pragma: no cover
            output.write(
                f"[red]Assistant initialization failed: {escape(str(exc))}[/red]"
            )
            user_input.disabled = True
            return
        output.write(
            "[green]Ready. Enter prompts or slash commands (e.g. /help, /outline ...).[/green]"
        )
        self.query_one("#sidebar", Vertical).display = False
        await self._refresh_state_strips(force_refresh=True)

    @on(Input.Submitted)
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self._record_input_history(text)
        log = self.query_one(RichLog)
        log.write(f"[bold cyan]You:[/bold cyan] {escape(text)}")
        event.input.disabled = True
        try:
            if text.startswith("/"):
                log.write(f"[yellow][Running][/yellow] {escape(text)}")
                command_result = await self._dispatch_slash_command(text)
                log.write(f"[green][Done][/green] {escape(text)}")
                log.write(f"[bold magenta]CLI:[/bold magenta] {escape(command_result)}")
            else:
                prompt = await asyncio.to_thread(self.state_engine.compose_prompt, text)
                response, streamed = await self._run_assistant_turn(prompt)
                if not streamed:
                    log.write(f"[bold green]Assistant:[/bold green] {escape(response)}")
                self.transcript.append({"user": text, "answer": response})
        except Exception as exc:  # pragma: no cover
            if text.startswith("/"):
                log.write(f"[red][Failed][/red] {escape(text)}")
            log.write(f"[red]Error: {escape(str(exc))}[/red]")
        finally:
            event.input.disabled = False
            event.input.focus()

    @on(Key)
    def _handle_input_history_navigation(self, event: Key) -> None:
        """Support command history navigation in the active input widget."""

        if event.key not in {"up", "down"}:
            return
        try:
            user_input = self.query_one("#command-input", Input)
        except Exception:
            return
        if self.focused is not user_input:
            return

        replacement = self._navigate_input_history(
            direction=-1 if event.key == "up" else 1,
            current_text=user_input.value,
        )
        if replacement is None:
            return
        user_input.value = replacement
        event.stop()

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
                    self.query_one(RichLog).write(escape(text))
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
            return self._build_help_text(args)

        if command == "status":
            return await self._build_status_text()

        if command == "state":
            return await self._build_state_text()

        if command == "progress":
            return await asyncio.to_thread(self._build_progress_text)

        if command == "wizard":
            return await asyncio.to_thread(self._build_wizard_text, args)

        if command == "pipeline":
            return await asyncio.to_thread(self._build_wizard_text, args)

        if command == "clear":
            return self._clear_output()

        if command == "toggle-tree":
            return self._toggle_tree_visibility()

        if command == "chapter":
            if not args:
                return "Usage: /chapter <number>"
            try:
                chapter_number = int(args[0])
            except ValueError:
                return "Usage: /chapter <number>"
            self.state_engine.set_active_chapter(chapter_number)
            await self._refresh_state_strips(force_refresh=True)
            return f"Active chapter focus set to {chapter_number}."

        if command == "scene":
            if not args:
                return "Usage: /scene <label>"
            self.state_engine.set_active_scene(" ".join(args))
            await self._refresh_state_strips(force_refresh=True)
            return f"Active scene focus set to: {' '.join(args)}"

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

    def action_toggle_tree(self) -> None:
        self._toggle_tree_visibility()

    def action_toggle_focus_mode(self) -> None:
        """Toggle distraction-reduced mode by hiding sidebar and state strips."""

        try:
            sidebar = self.query_one("#sidebar", Vertical)
            state_strips = self.query_one("#state-strips", Horizontal)
        except Exception:
            return

        if not self._focus_mode_enabled:
            self._sidebar_visible_before_focus = bool(sidebar.display)
            self._state_strips_visible_before_focus = bool(state_strips.display)
            sidebar.display = False
            state_strips.display = False
            self._focus_mode_enabled = True
            return

        sidebar.display = self._sidebar_visible_before_focus
        state_strips.display = self._state_strips_visible_before_focus
        self._focus_mode_enabled = False

    def _build_help_text(self, args: list[str] | None = None) -> str:
        """Render grouped command help with optional category filtering."""

        groups: dict[str, list[str]] = {
            "writing": [
                '/chapters chapter <number> "..."',
                '/chapters cover "..."',
                '/chapters back-cover "..."',
                '/iterate chapter <number> "..."',
            ],
            "planning": [
                "/wizard [next]",
                "/pipeline [next]",
                "/wizard set <field> <value>",
                "/wizard show",
                "/wizard plan",
                "/wizard reset",
                "/progress",
                '/outline general-outline "..."',
                '/outline chapter-synopsis "..."',
            ],
            "world": [
                '/worldbuilding history "..."',
                '/worldbuilding geography "..."',
                '/worldbuilding culture "..."',
                '/worldbuilding magic-system "..."',
                '/worldbuilding technology "..."',
            ],
            "project": [
                "/status",
                "/state",
                "/clear",
                "/toggle-tree",
                "/chapter <number>",
                "/scene <label>",
                "/session list",
                "/session save <name>",
                "/session load <name>",
                "/model-list",
                "/model-change <model_id>",
                "Ctrl+L (toggle focus mode)",
            ],
        }

        if args:
            category = args[0].lower()
            if category in groups:
                lines = [f"TUI Help: {category.title()}"]
                lines.extend(f"- {entry}" for entry in groups[category])
                return "\n".join(lines)
            return (
                "Unknown help topic. Available topics: writing, planning, world, project.\n"
                "Use /help to view all grouped commands."
            )

        lines = [
            "TUI Command Guide",
            "Writing",
        ]
        lines.extend(f"- {entry}" for entry in groups["writing"])
        lines.append("Planning")
        lines.extend(f"- {entry}" for entry in groups["planning"])
        lines.append("World")
        lines.extend(f"- {entry}" for entry in groups["world"])
        lines.append("Project")
        lines.extend(f"- {entry}" for entry in groups["project"])
        lines.append("Tip: /help <topic> for a focused list.")
        return "\n".join(lines)

    async def _build_status_text(self) -> str:
        state = await asyncio.to_thread(self.state_engine.get_state)
        lines = [
            "TUI Status",
            f"- Project: {self.book_path}",
            f"- Provider: {self._active_provider()}",
            f"- Model: {self._active_model()}",
            f"- Active chapter: {state.active_chapter if state.active_chapter is not None else '<none>'}",
            f"- Active scene: {state.active_scene}",
            f"- Active arc: {state.active_arc}",
            f"- Thread: {self.thread_id or '<none>'}",
            f"- Transcript turns: {len(self.transcript)}",
        ]
        chat_status = await asyncio.to_thread(self._run_chat_command_capture, ":status")
        if chat_status:
            lines.extend(["", "Assistant Retrieval Status", chat_status])
        return "\n".join(lines)

    async def _build_state_text(self) -> str:
        """Show the current state snapshot and prompt block used for injection."""

        state = await asyncio.to_thread(self.state_engine.get_state)
        block = await asyncio.to_thread(
            self.state_engine.build_prompt_block,
            state=state,
        )
        lines = [
            "Narrative State",
            f"- Active chapter: {state.active_chapter if state.active_chapter is not None else '<none>'}",
            f"- Active scene: {state.active_scene}",
            f"- Active arc: {state.active_arc}",
            f"- Memory strip: {state.memory_strip}",
            f"- Timeline strip: {state.timeline_strip}",
            "",
            "Injected Prompt Block",
            block,
        ]
        return "\n".join(lines)

    def _build_progress_text(self) -> str:
        """Render project generation checkpoints from known output files."""

        checkpoints = self._story_pipeline_checkpoints()
        lines = ["Project Progress"]
        completed = 0
        for item in checkpoints:
            done = bool(item["done"])
            status = "[x]" if done else "[ ]"
            if done:
                completed += 1
            lines.append(f"- {item['name']}: {status}")

        chapter_count = len(self._chapter_numbers())
        lines.append(f"- Chapters drafted: {chapter_count}")
        lines.append(f"- Completion: {completed}/{len(checkpoints)} checkpoints")
        return "\n".join(lines)

    def _build_wizard_text(self, args: list[str]) -> str:
        """Provide a guided pipeline view and next-step recommendation."""

        if args:
            mode = args[0].lower()
            if mode == "set":
                return self._wizard_set_field(args[1:])
            if mode == "show":
                return self._wizard_show_profile()
            if mode == "reset":
                self._wizard_profile.clear()
                return "Wizard profile reset. Use /wizard set <field> <value>."
            if mode == "plan":
                return self._wizard_build_plan()

        checkpoints = self._story_pipeline_checkpoints()
        next_item = next((item for item in checkpoints if not item["done"]), None)

        if args and args[0].lower() == "next":
            if next_item is None:
                return (
                    "Pipeline complete. Suggested next steps:\n"
                    '- /chapters chapter <n> "Draft the next chapter"\n'
                    '- /iterate check-consistency "Check continuity and style"'
                )
            return (
                f"Next recommended step: {next_item['name']}\n"
                f"Command: {next_item['command']}"
            )

        lines = ["Story Pipeline Wizard"]
        for idx, item in enumerate(checkpoints, start=1):
            marker = "[x]" if item["done"] else "[ ]"
            lines.append(f"{idx}. {item['name']} {marker}")

        if next_item is None:
            lines.extend(
                [
                    "",
                    "All core checkpoints are complete.",
                    'Try: /iterate check-consistency "Check continuity and style"',
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    f"Next: {next_item['name']}",
                    f"Run: {next_item['command']}",
                    "Tip: use /wizard next for a compact recommendation.",
                ]
            )

        return "\n".join(lines)

    def _wizard_set_field(self, args: list[str]) -> str:
        """Set a wizard profile field for guided plan generation."""

        if len(args) < 2:
            return (
                "Usage: /wizard set <field> <value>\n"
                "Fields: premise, protagonist, genre, tone, flow"
            )

        field = args[0].lower().strip()
        value = " ".join(args[1:]).strip()
        allowed_fields = {"premise", "protagonist", "genre", "tone", "flow"}
        if field not in allowed_fields:
            return (
                "Unsupported wizard field. "
                "Allowed: premise, protagonist, genre, tone, flow"
            )
        if not value:
            return "Wizard field value cannot be empty."

        if field == "flow" and value not in {"outline-first", "world-first"}:
            return "Flow must be one of: outline-first, world-first"

        self._wizard_profile[field] = value
        return f"Wizard field set: {field} = {value}"

    def _wizard_show_profile(self) -> str:
        """Show current guided wizard profile values."""

        if not self._wizard_profile:
            return (
                "Wizard profile is empty.\n"
                "Set values with /wizard set <field> <value> "
                "(premise, protagonist, genre, tone, flow)."
            )

        lines = ["Wizard Profile"]
        for field in ["premise", "protagonist", "genre", "tone", "flow"]:
            value = self._wizard_profile.get(field)
            if value:
                lines.append(f"- {field}: {value}")
        return "\n".join(lines)

    def _wizard_build_plan(self) -> str:
        """Build a command plan from wizard profile without executing commands."""

        premise = self._wizard_profile.get("premise", "the core premise")
        protagonist = self._wizard_profile.get("protagonist", "the protagonist")
        genre = self._wizard_profile.get("genre", "the target genre")
        tone = self._wizard_profile.get("tone", "the desired tone")
        flow = self._wizard_profile.get("flow", "outline-first")

        outline_cmds = [
            f'/outline general-outline "Create the high-level story arc for {genre} with a {tone} tone. Premise: {premise}."',
            f'/outline character-summary "Summarize {protagonist} and key supporting characters."',
            '/outline chapter-synopsis "Produce a chapter-by-chapter synopsis with escalating stakes."',
        ]
        world_cmds = [
            f'/worldbuilding history "Define world history that supports this premise: {premise}."',
            '/worldbuilding culture "Define social norms, factions, and conflicts."',
            '/worldbuilding magic-system "Define rules, costs, and limitations."',
        ]

        ordered = (
            world_cmds + outline_cmds
            if flow == "world-first"
            else outline_cmds + world_cmds
        )
        ordered.extend(
            [
                '/chapters chapter 1 "Draft chapter 1 using synopsis + state context."',
                "/progress",
            ]
        )

        lines = [
            "Wizard Plan Draft",
            f"- Flow: {flow}",
            "- This plan is advisory; commands are not auto-executed.",
            "",
        ]
        lines.extend(f"{idx}. {cmd}" for idx, cmd in enumerate(ordered, start=1))
        lines.append("")
        lines.append("Tip: update inputs with /wizard set ... then rerun /wizard plan.")
        return "\n".join(lines)

    def _story_pipeline_checkpoints(self) -> list[dict[str, str | bool]]:
        """Return canonical story pipeline checkpoints with completion status."""

        has_pdf = any((self.book_path / "book").glob("book-*.pdf"))
        return [
            {
                "name": "General Outline",
                "done": self._has_content("outline/general_outline.md"),
                "command": '/outline general-outline "Summarize the overall plot"',
            },
            {
                "name": "Character Summary",
                "done": self._has_content("outline/character_summary.md"),
                "command": '/outline character-summary "Summarize key characters"',
            },
            {
                "name": "Plot Points",
                "done": self._has_content("outline/plot_points.md"),
                "command": '/outline plot-points "List the major plot points"',
            },
            {
                "name": "Chapter Synopsis",
                "done": self._has_content("outline/chapter_synopsis.md"),
                "command": '/outline chapter-synopsis "Outline each chapter"',
            },
            {
                "name": "World History",
                "done": self._has_content("worldbuilding/history.md"),
                "command": '/worldbuilding history "Describe world history"',
            },
            {
                "name": "World Geography",
                "done": self._has_content("worldbuilding/geography.md"),
                "command": '/worldbuilding geography "Describe world geography"',
            },
            {
                "name": "World Culture",
                "done": self._has_content("worldbuilding/culture.md"),
                "command": '/worldbuilding culture "Describe world culture"',
            },
            {
                "name": "Magic System",
                "done": self._has_content("worldbuilding/magic_system.md"),
                "command": '/worldbuilding magic-system "Describe the magic system"',
            },
            {
                "name": "Technology",
                "done": self._has_content("worldbuilding/technology.md"),
                "command": '/worldbuilding technology "Describe world technology"',
            },
            {
                "name": "First Chapter Draft",
                "done": self._has_content("chapters/chapter-1.md"),
                "command": '/chapters chapter 1 "Write chapter 1 from synopsis"',
            },
            {
                "name": "Cover",
                "done": self._has_content("chapters/cover.md"),
                "command": '/chapters cover "Generate cover text"',
            },
            {
                "name": "Back Cover",
                "done": self._has_content("chapters/back-cover.md"),
                "command": '/chapters back-cover "Generate back-cover text"',
            },
            {
                "name": "Published PDF",
                "done": has_pdf,
                "command": "/publish pdf en",
            },
        ]

    def _has_content(self, relative_path: str) -> bool:
        """Return True when a generated markdown file exists with non-trivial content."""

        path = self.book_path / relative_path
        if not path.exists() or not path.is_file():
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return len(text.strip().splitlines()) > 3

    def _chapter_numbers(self) -> list[int]:
        """Return sorted chapter numbers from chapter markdown filenames."""

        chapters_dir = self.book_path / "chapters"
        if not chapters_dir.exists():
            return []

        numbers: list[int] = []
        for chapter_path in chapters_dir.glob("chapter-*.md"):
            match = re.match(r"chapter-(\d+)\.md$", chapter_path.name)
            if match is not None:
                numbers.append(int(match.group(1)))

        numbers.sort()
        return numbers

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

        validation_note = ""
        active_provider = self._active_provider()
        if active_provider == "openrouter":
            try:
                free_models = await asyncio.to_thread(self._get_free_models)
                if free_models:
                    free_ids = {model.model_id for model in free_models}
                    if requested not in free_ids:
                        return (
                            "Model is not in the current free OpenRouter model list. "
                            "Use /model-list to inspect valid IDs."
                        )
                    validation_note = "Validated against current free OpenRouter list."
            except Exception as exc:
                validation_note = (
                    f"Validation skipped due to model-list fetch failure: {exc}"
                )
        else:
            validation_note = (
                "Validation skipped: current provider is not openrouter; "
                "model ID was not checked against the OpenRouter free-model list."
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
            if inspect.iscoroutine(new_assistant):
                new_assistant.close()
                raise TypeError(
                    "create_or_get_assistant returned a coroutine; expected "
                    "a synchronous assistant instance"
                )
        except Exception as exc:
            self.assistant = previous_assistant
            self.model_override = previous_override
            return f"Failed to change model to '{requested}': {exc}"

        self.assistant = new_assistant
        self.model_override = requested
        if self.thread_id is None:
            self.thread_id = get_thread(str(self.book_path)).id

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

    async def _refresh_state_strips(self, *, force_refresh: bool = False) -> None:
        """Refresh strip widgets using the read-only narrative state snapshot."""

        state = await asyncio.to_thread(
            self.state_engine.get_state, force_refresh=force_refresh
        )
        self._update_strip_widgets(state)

    def _update_strip_widgets(self, state: NarrativeState) -> None:
        """Update one-line strip widgets with concise state text."""

        try:
            self.query_one("#narrative-strip", Static).update(
                self._truncate_strip(state.memory_strip)
            )
            self.query_one("#timeline-strip", Static).update(
                self._truncate_strip(state.timeline_strip)
            )
        except Exception:
            # Widget queries may fail in unit tests that do not mount the app.
            return

    def _truncate_strip(self, text: str, *, max_len: int = 110) -> str:
        """Trim long strip values so the layout remains stable in narrow terminals."""

        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    def _toggle_tree_visibility(self) -> str:
        """Toggle project tree visibility for focused writing mode."""

        try:
            sidebar = self.query_one("#sidebar", Vertical)
        except Exception:
            return "Project tree is not available in the current view."

        sidebar.display = not sidebar.display
        return "Project tree shown." if sidebar.display else "Project tree hidden."

    def _clear_output(self) -> str:
        """Clear output text while preserving session and state context."""

        try:
            self.query_one("#output", RichLog).clear()
        except Exception:
            return "Output panel is not available in the current view."
        return "Output cleared."

    def _record_input_history(self, text: str) -> None:
        """Record user input for keyboard history navigation."""

        item = text.strip()
        if not item:
            return
        self._input_history.append(item)
        self._history_cursor = None

    def _navigate_input_history(
        self, *, direction: int, current_text: str
    ) -> str | None:
        """Return previous/next command from history for Up/Down navigation."""

        if not self._input_history:
            return None

        if self._history_cursor is None:
            if direction < 0:
                self._history_cursor = len(self._input_history) - 1
                return self._input_history[self._history_cursor]
            return current_text

        next_index = self._history_cursor + direction
        if next_index < 0:
            self._history_cursor = 0
            return self._input_history[self._history_cursor]
        if next_index >= len(self._input_history):
            self._history_cursor = None
            return ""

        self._history_cursor = next_index
        return self._input_history[self._history_cursor]

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
