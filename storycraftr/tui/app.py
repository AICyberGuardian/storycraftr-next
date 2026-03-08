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
from storycraftr.agent.execution_mode import (
    ExecutionMode,
    ModeConfig,
)
from storycraftr.chat.commands import CommandContext, handle_command
from storycraftr.chat.module_runner import ModuleCommandError, run_module_command
from storycraftr.chat.session import SessionManager
from storycraftr.llm.model_context import resolve_model_context
from storycraftr.llm.openrouter_discovery import get_cache_metadata
from storycraftr.subagents import SubAgentJobManager
from storycraftr.services.control_plane import (
    canon_check_impl,
    mode_set_impl,
    mode_show_impl,
    state_audit_impl,
)
from storycraftr.tui.openrouter_models import (
    OpenRouterModel,
    fetch_free_openrouter_models,
)
from storycraftr.tui.canon import add_fact, clear_chapter_facts, list_facts
from storycraftr.tui.canon_extract import CanonCandidate, extract_canon_candidates
from storycraftr.tui.canon_verify import verify_candidate_against_canon
from storycraftr.tui.state_engine import NarrativeState, NarrativeStateEngine
from storycraftr.tui.session import TuiSessionState
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
    #mode-indicator {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
        content-align: right middle;
    }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+p", "command_palette", "Command Palette"),
        Binding("ctrl+t", "toggle_tree", "Toggle Tree"),
        Binding("ctrl+l", "toggle_focus_mode", "Focus Mode"),
    ]

    _FREE_MODEL_CACHE_TTL_SECONDS = 300
    _SUMMARY_TRIGGER_TURNS = 8
    _SUMMARY_KEEP_RECENT_TURNS = 3
    _SUMMARY_KEEP_PRIORITY_TURNS = 3
    _SUMMARY_MAX_LENGTH = 1200

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
        self.pending_canon_candidates: list[CanonCandidate] = []
        self._hybrid_extract_manager: SubAgentJobManager | None = None
        self.mode_config = ModeConfig()
        self.autopilot_turns_remaining = 0
        self._session_summary = ""
        self._session_compacted_turns = 0
        self._last_prompt_budget: Any | None = None
        self._last_prompt_diagnostics: Any | None = None
        self._last_prompt_provider = "<unknown>"
        self._last_prompt_model = "<unknown>"
        self._last_assistant_response = ""
        self._last_canon_conflict_report: dict[str, Any] | None = None
        self._load_mode_session_state()
        self._load_session_summary_state()

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
        yield Static("", id="mode-indicator")
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
        self._refresh_mode_indicator()
        await self._refresh_state_strips(force_refresh=True)

    async def on_unmount(self) -> None:
        """Release background resources used by hybrid extraction."""

        manager = self._hybrid_extract_manager
        if manager is None:
            return
        self._hybrid_extract_manager = None
        await asyncio.to_thread(manager.shutdown, False)

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
                response, streamed = await self._generate_with_mode_awareness(text)
                if not streamed:
                    log.write(f"[bold green]Assistant:[/bold green] {escape(response)}")
                self._last_assistant_response = response
                self.transcript.append({"user": text, "answer": response})
                self._roll_session_summary_if_needed()
                await self._post_generation_hooks(
                    user_prompt=text,
                    response=response,
                )
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

    async def _compose_prompt_with_tracking(self, user_prompt: str) -> str:
        """Compose a scoped prompt and persist latest budget diagnostics."""

        provider = self._active_provider()
        model_id = self._active_model()
        recent_turns = self._recent_turns_for_prompt()
        prompt, budget, diagnostics = await asyncio.to_thread(
            self.state_engine.compose_prompt_with_diagnostics,
            user_prompt,
            provider=provider,
            model_id=model_id,
            output_reserve_tokens=(
                self.config.max_tokens if self.config is not None else None
            ),
            recent_turns=recent_turns,
        )
        self._last_prompt_budget = budget
        self._last_prompt_diagnostics = diagnostics
        self._last_prompt_provider = provider
        self._last_prompt_model = model_id
        return prompt

    async def _generate_with_mode_awareness(
        self,
        user_prompt: str,
    ) -> tuple[str, bool]:
        """Generate assistant output under execution-mode policy controls."""

        prompt = await self._compose_prompt_with_tracking(user_prompt)
        response, streamed = await self._run_assistant_turn(prompt)

        if self.mode_config.should_auto_regenerate_on_conflict() and not streamed:
            chapter = self._active_chapter_for_canon()
            report = await self._analyze_canon_conflicts(
                response=response,
                chapter=chapter,
            )
            self._last_canon_conflict_report = report
            if report["conflicts"]:
                revise_prompt = (
                    f"{user_prompt}\n\n"
                    "Revise once to resolve canon conflicts and contradictions "
                    "while preserving intent."
                )
                revised = await self._compose_prompt_with_tracking(revise_prompt)
                response, streamed = await self._run_assistant_turn(revised)

        return response, streamed

    async def _post_generation_hooks(self, *, user_prompt: str, response: str) -> None:
        """Run mode-gated post-generation policy hooks."""

        _ = user_prompt  # Reserved for future structured policy decisions.
        await self._warn_about_canon_conflicts(response)
        if self.mode_config.mode is ExecutionMode.HYBRID:
            await self._maybe_queue_hybrid_canon_candidates(response)

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
            return await self._handle_state_command(args)

        if command == "summary":
            return self._handle_summary_command(args)

        if command == "context":
            return await self._handle_context_command(args)

        if command == "mode":
            return self._handle_mode_command(args)

        if command == "stop":
            return self._handle_stop_command()

        if command == "canon":
            return await self._handle_canon_command(args)

        if command == "progress":
            return await asyncio.to_thread(self._build_progress_text)

        if command == "wizard":
            return await asyncio.to_thread(self._build_wizard_text, args)

        if command == "pipeline":
            return await asyncio.to_thread(self._build_wizard_text, args)

        if command == "autopilot":
            return await self._run_autopilot_command(args)

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
            force_refresh = bool(args and args[0].lower() == "refresh")
            return await asyncio.to_thread(
                self._render_model_list,
                force_refresh,
            )

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

    @property
    def execution_mode(self) -> ExecutionMode:
        """Compatibility view for call sites/tests expecting execution_mode."""

        return self.mode_config.mode

    def _active_provider(self) -> str:
        if self.config and self.config.llm_provider:
            return self.config.llm_provider
        return "<unknown>"

    def _recent_turns_for_prompt(self, max_turns: int = 3) -> list[str]:
        """Return a small transcript tail for prompt continuity under budget."""

        if max_turns <= 0:
            return []

        rendered: list[str] = []
        if self._session_summary:
            rendered.append(f"Session Summary: {self._session_summary}")

        tail = self.transcript[-max_turns:]
        for turn in tail:
            user_text = str(turn.get("user", "")).strip()
            assistant_text = str(turn.get("answer", "")).strip()
            if user_text:
                rendered.append(f"User: {user_text}")
            if assistant_text:
                rendered.append(f"Assistant: {assistant_text}")
        return rendered

    def _roll_session_summary_if_needed(self) -> None:
        """Compact older transcript turns into a bounded rolling summary."""

        if len(self.transcript) <= self._SUMMARY_TRIGGER_TURNS:
            return

        compact_until = max(0, len(self.transcript) - self._SUMMARY_KEEP_RECENT_TURNS)
        if compact_until <= self._session_compacted_turns:
            return

        fresh_slice = self.transcript[self._session_compacted_turns : compact_until]
        fresh_summary = self._summarize_turn_slice_adaptive(fresh_slice)
        if not fresh_summary:
            self._session_compacted_turns = compact_until
            return

        if self._session_summary:
            combined = f"{self._session_summary} | {fresh_summary}"
        else:
            combined = fresh_summary

        self._session_summary = self._truncate_summary(combined)
        self._session_compacted_turns = compact_until
        self._persist_runtime_state_patch({"session_summary": self._session_summary})

    def _summarize_turn_slice_adaptive(self, turns: list[dict[str, Any]]) -> str:
        """Summarize turns while preserving high-signal narrative anchors."""

        if not turns:
            return ""

        priority_indices = self._select_priority_turn_indices(turns)
        priority_lines: list[str] = []
        summarized_turns: list[dict[str, Any]] = []

        for idx, turn in enumerate(turns):
            if idx in priority_indices:
                user_text = self._compact_summary_text(str(turn.get("user", "")), 70)
                answer_text = self._compact_summary_text(
                    str(turn.get("answer", "")), 70
                )
                if user_text:
                    priority_lines.append(f"P-U:{user_text}")
                if answer_text:
                    priority_lines.append(f"P-A:{answer_text}")
            else:
                summarized_turns.append(turn)

        summary_core = self._summarize_turn_slice(summarized_turns)
        parts = [part for part in [summary_core, "; ".join(priority_lines)] if part]
        return " | ".join(parts)

    def _select_priority_turn_indices(self, turns: list[dict[str, Any]]) -> set[int]:
        """Select a bounded set of turns to preserve verbatim in summary output."""

        scored: list[tuple[int, int]] = []
        for idx, turn in enumerate(turns):
            merged = f"{turn.get('user', '')} {turn.get('answer', '')}".strip()
            score = 0
            if self._looks_scene_boundary(merged):
                score += 4
            if self._looks_canon_relevant(merged):
                score += 3
            if self._looks_major_reveal(merged):
                score += 2
            if self._looks_new_entity_intro(merged):
                score += 1
            if score > 0:
                scored.append((idx, score))

        scored.sort(key=lambda item: (-item[1], -item[0]))
        return {idx for idx, _ in scored[: self._SUMMARY_KEEP_PRIORITY_TURNS]}

    def _looks_scene_boundary(self, text: str) -> bool:
        lower = text.lower()
        markers = (
            "scene",
            "cut to",
            "meanwhile",
            "later",
            "next morning",
            "chapter",
        )
        return any(marker in lower for marker in markers)

    def _looks_canon_relevant(self, text: str) -> bool:
        lower = text.lower()
        markers = (
            "canon",
            "constraint",
            "continuity",
            "must",
            "never",
            "always",
            "fact",
        )
        return any(marker in lower for marker in markers)

    def _looks_major_reveal(self, text: str) -> bool:
        lower = text.lower()
        markers = (
            "reveals",
            "truth",
            "betray",
            "secret",
            "dies",
            "death",
            "twist",
        )
        return any(marker in lower for marker in markers)

    def _looks_new_entity_intro(self, text: str) -> bool:
        lower = text.lower()
        markers = (
            "introduces",
            "new character",
            "arrives",
            "enters",
            "location",
            "artifact",
        )
        return any(marker in lower for marker in markers)

    def _summarize_turn_slice(self, turns: list[dict[str, Any]]) -> str:
        """Build a deterministic compact summary for a transcript slice."""

        snippets: list[str] = []
        for turn in turns:
            user_text = self._compact_summary_text(str(turn.get("user", "")), 80)
            answer_text = self._compact_summary_text(str(turn.get("answer", "")), 80)
            if user_text:
                snippets.append(f"U:{user_text}")
            if answer_text:
                snippets.append(f"A:{answer_text}")
            if len(snippets) >= 12:
                break
        return "; ".join(snippets)

    def _compact_summary_text(self, text: str, max_chars: int) -> str:
        collapsed = " ".join(text.split()).strip()
        if not collapsed:
            return ""
        if len(collapsed) <= max_chars:
            return collapsed
        if max_chars <= 3:
            return collapsed[:max_chars]
        return collapsed[: max_chars - 3].rstrip() + "..."

    def _truncate_summary(self, text: str) -> str:
        if len(text) <= self._SUMMARY_MAX_LENGTH:
            return text
        return text[-self._SUMMARY_MAX_LENGTH :]

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
                "/autopilot <steps> <prompt>",
                "/progress",
                "/canon",
                "/canon show [chapter]",
                "/canon pending",
                "/canon add <fact>",
                "/canon add <chapter> :: <fact>",
                "/canon check-last",
                "/canon accept <n[,m,...]>",
                "/canon reject [n[,m,...]]",
                "/canon clear [confirm]",
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
                "/state audit [limit=<n>] [entity=<id>] [type=<type>]",
                "/summary [clear]",
                "/context [summary|budget|models|conflicts|clear-summary|refresh-models]",
                "/mode [manual|hybrid|autopilot [max_turns]]",
                "/stop",
                "/clear",
                "/toggle-tree",
                "/chapter <number>",
                "/scene <label>",
                "/session list",
                "/session save <name>",
                "/session load <name>",
                "/model-list",
                "/model-list refresh",
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
            f"- Execution mode: {self.execution_mode.value}",
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
            self.state_engine.build_scoped_context,
            "State inspection snapshot.",
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

    def _build_state_audit_text(self, args: list[str]) -> str:
        """Query and display audit trail history with optional filters."""

        # Parse optional filter arguments (limit=N, entity=ID, type=TYPE)
        limit = 10  # Default limit
        entity_id: str | None = None
        entity_type: str | None = None

        for arg in args:
            if "=" in arg:
                key, _, value = arg.partition("=")
                key = key.strip().lower()
                value = value.strip()

                if key == "limit":
                    try:
                        limit = max(1, int(value))
                    except ValueError:
                        return f"Invalid limit value: {value}"
                elif key == "entity":
                    entity_id = value
                elif key == "type":
                    if value.lower() in {"character", "location", "plot_thread"}:
                        entity_type = value.lower()
                    else:
                        return "Invalid type. Use: character, location, or plot_thread"
                else:
                    return f"Unknown filter: {key}"

        try:
            result = state_audit_impl(
                str(self.book_path),
                entity_type=entity_type,
                entity_id=entity_id,
                limit=limit,
                store=self.state_engine.narrative_state_store,
            )
            if not result.enabled:
                return "Audit logging is disabled for this project."
            entries = result.entries

            if not entries:
                return "No audit entries found matching the specified filters."

            # Format entries for display
            lines = [f"Audit Trail (showing {len(entries)} entries):", ""]

            for i, entry in enumerate(entries, 1):
                lines.append(f"[{i}] {entry.timestamp}")
                lines.append(f"    Operation: {entry.operation_type}")
                lines.append(f"    Actor: {entry.actor}")

                if entry.patch:
                    patch_desc = f"{len(entry.patch.operations)} operation(s)"
                    lines.append(f"    Patch: {patch_desc}")

                if entry.changeset:
                    change_count = (
                        len(entry.changeset.character_diffs)
                        + len(entry.changeset.location_diffs)
                        + len(entry.changeset.plot_thread_diffs)
                    )
                    if entry.changeset.world_changed:
                        change_count += 1
                    lines.append(
                        f"    Changes: {change_count} entity/field modification(s)"
                    )

                if entry.metadata:
                    version = entry.metadata.get("version")
                    if version is not None:
                        lines.append(f"    Version: {version}")

                lines.append("")

            # Add usage example
            lines.append(
                "Tip: Use filters like 'limit=20', 'entity=alice', 'type=character'"
            )

            return "\n".join(lines)

        except Exception as exc:
            return f"Failed to query audit log: {exc}"

    async def _handle_state_command(self, args: list[str]) -> str:
        """Dispatch /state diagnostics subcommands."""

        if not args:
            return await self._build_state_text()

        subcommand = args[0].lower()
        if subcommand == "audit":
            return await asyncio.to_thread(self._build_state_audit_text, args[1:])

        return "Usage: /state [audit [limit=<n>] [entity=<id>] [type=<character|location|plot_thread>]]"

    async def _handle_context_command(self, args: list[str]) -> str:
        """Dispatch /context diagnostics subcommands."""

        if not args:
            return await self._build_context_overview_text()

        subcommand = args[0].lower()
        if subcommand == "summary":
            return self._build_context_summary_text()
        if subcommand == "budget":
            return self._build_context_budget_text()
        if subcommand == "models":
            return await asyncio.to_thread(self._build_context_models_text, False)
        if subcommand == "conflicts":
            return self._build_context_conflicts_text()
        if subcommand == "clear-summary":
            return self._handle_summary_command(["clear"])
        if subcommand == "refresh-models":
            return await asyncio.to_thread(self._build_context_models_text, True)
        return "Usage: /context [summary|budget|models|conflicts|clear-summary|refresh-models]"

    async def _build_context_overview_text(self) -> str:
        """Render compact cross-system diagnostics in one dashboard view."""

        summary_status = (
            f"active ({len(self._session_summary)} chars)"
            if self._session_summary
            else "empty"
        )

        if self._last_prompt_budget is None:
            budget_status = "unavailable (no prompt composed yet)"
            pruning_status = "n/a"
        else:
            budget_status = (
                f"{self._last_prompt_budget.input_budget_tokens} input / "
                f"{self._last_prompt_budget.output_reserve_tokens} reserve"
            )
            pruned = list(self._last_prompt_diagnostics.pruned_sections)
            truncated = list(self._last_prompt_diagnostics.truncated_sections)
            details = []
            if pruned:
                details.append(f"pruned={','.join(pruned)}")
            if truncated:
                details.append(f"truncated={','.join(truncated)}")
            pruning_status = "; ".join(details) if details else "none"

        cache = get_cache_metadata()
        age = self._format_age_seconds(cache.age_seconds)
        model_cache_status = (
            f"{cache.cache_status} ({cache.free_model_count} free models, {age})"
        )

        lines = [
            "Runtime Context Snapshot",
            f"- Active Model: {self._active_model()}",
            f"- Session Summary: {summary_status}",
            f"- Prompt Budget: {budget_status}",
            f"- Pruning: {pruning_status}",
            f"- Model Cache: {model_cache_status}",
            f"- Canon Conflicts: {self._format_conflict_summary_line()}",
        ]

        if (
            self._last_prompt_budget is not None
            and self._last_prompt_diagnostics is not None
        ):
            lines.extend(
                [
                    "",
                    "Prompt Composition Breakdown",
                    *self._build_budget_section_lines(
                        self._last_prompt_diagnostics,
                        include_estimates=True,
                    ),
                ]
            )

        lines.extend(
            [
                "",
                "Current Session Summary",
                self._session_summary or "No summary generated yet.",
                "",
                "Use /context summary, /context budget, /context models, /context conflicts for details.",
            ]
        )
        return "\n".join(lines)

    def _build_context_summary_text(self) -> str:
        """Render detailed session-summary diagnostics."""

        lines = [
            "Session Summary",
            f"- Status: {'active' if self._session_summary else 'empty'}",
            f"- Compacted turns: {self._session_compacted_turns}",
            f"- Summary chars: {len(self._session_summary)}",
        ]
        if self._session_summary:
            lines.extend(["", self._session_summary])
        return "\n".join(lines)

    def _build_context_budget_text(self) -> str:
        """Render detailed prompt budget and pruning diagnostics."""

        if self._last_prompt_budget is None or self._last_prompt_diagnostics is None:
            return (
                "Prompt Budget\n"
                "- Status: unavailable\n"
                "- Compose a prompt first (send a normal message) to inspect budget and pruning details."
            )

        diagnostics = self._last_prompt_diagnostics
        budget = self._last_prompt_budget

        lines = [
            "Prompt Budget",
            f"- Provider: {self._last_prompt_provider}",
            f"- Model: {self._last_prompt_model}",
            f"- Context Window: {budget.context_window_tokens}",
            f"- Output Reserve: {budget.output_reserve_tokens}",
            f"- Input Budget: {budget.input_budget_tokens}",
            f"- Model Source: {budget.model_source}",
            "",
            "Sections",
        ]

        lines.extend(
            self._build_budget_section_lines(diagnostics, include_estimates=False)
        )

        token_map = diagnostics.estimated_tokens
        lines.extend(
            [
                "",
                "Estimated Usage",
                f"- Canon: {token_map.get('canon', 0)}",
                f"- Scene Plan: {token_map.get('scene_plan', 0)}",
                f"- Scoped Context: {token_map.get('scoped_context', 0)}",
                f"- Narrative State: {token_map.get('narrative_state', 0)}",
                f"- Recent Dialogue: {token_map.get('recent_dialogue', 0)}",
                f"- Retrieved Context: {token_map.get('retrieved_context', 0)}",
                f"- User Instruction: {token_map.get('user_instruction', 0)}",
                f"- Summary: {token_map.get('summary', 0)}",
                f"- Full Prompt: {token_map.get('full_prompt', 0)}",
            ]
        )
        return "\n".join(lines)

    def _build_budget_section_lines(
        self,
        diagnostics: Any,
        *,
        include_estimates: bool,
    ) -> list[str]:
        """Render standardized section status markers for diagnostics views."""

        included = set(diagnostics.included_sections)
        truncated = set(diagnostics.truncated_sections)
        pruned = set(diagnostics.pruned_sections)
        token_map = diagnostics.estimated_tokens

        section_order = [
            ("canon_constraints", "Canon Constraints", "canon"),
            ("scene_plan", "Scene Plan", "scene_plan"),
            ("scoped_context", "Scoped Context", "scoped_context"),
            ("narrative_state", "Structured Narrative State", "narrative_state"),
            ("recent_dialogue", "Recent Dialogue", "recent_dialogue"),
            ("retrieved_context", "Retrieved Context", "retrieved_context"),
            ("user_instruction", "User Instruction", "user_instruction"),
            ("summary", "Session Summary", "summary"),
        ]

        lines: list[str] = []
        for key, label, token_key in section_order:
            if key == "summary":
                marker = "[x]" if self._session_summary else "[ ]"
            elif key in truncated:
                marker = "[~]"
            elif key in included:
                marker = "[x]"
            elif key in pruned:
                marker = "[ ]"
            else:
                marker = "[-]"
            if include_estimates:
                lines.append(f"{marker} {label}: ~{token_map.get(token_key, 0)} tokens")
            else:
                lines.append(f"{marker} {label}")
        return lines

    def _build_context_models_text(self, force_refresh: bool) -> str:
        """Render OpenRouter discovery/cache diagnostics and current model limits."""

        refresh_note = ""
        if force_refresh:
            try:
                refreshed = self._get_free_models(force_refresh=True)
                refresh_note = (
                    f"Model catalog refresh complete ({len(refreshed)} free models)."
                )
            except Exception as exc:
                refresh_note = f"Model catalog refresh failed: {exc}"

        cache = get_cache_metadata()
        age = self._format_age_seconds(cache.age_seconds)
        lines = [
            "OpenRouter Model Cache",
            f"- Cache Status: {cache.cache_status}",
            f"- Last Refresh: {self._format_timestamp(cache.fetched_at)}",
            f"- Age: {age}",
            f"- Cached Free Models: {cache.free_model_count}",
            f"- Cache Path: {cache.cache_path}",
        ]
        if refresh_note:
            lines.extend(["", refresh_note])

        provider = self._active_provider()
        model_id = self._active_model()
        spec = resolve_model_context(provider, model_id)
        lines.extend(
            [
                "",
                "Current Model",
                f"- Provider: {provider}",
                f"- ID: {model_id}",
                f"- Context Length: {spec.context_window_tokens}",
                f"- Max Completion: {spec.max_completion_tokens or 'unknown'}",
                f"- Source: {spec.source}",
            ]
        )
        return "\n".join(lines)

    def _build_context_conflicts_text(self) -> str:
        """Render diagnostics for latest canon conflict analysis."""

        report = self._last_canon_conflict_report
        if report is None:
            return (
                "Canon Conflict Diagnostics\n"
                "- Status: unavailable\n"
                "- Generate output or run /canon check-last to populate diagnostics."
            )

        lines = [
            "Canon Conflict Diagnostics",
            f"- Chapter: {report.get('chapter', 'n/a')}",
            f"- Checked candidates: {report.get('checked_candidates', 0)}",
            f"- Conflicts: {len(report.get('conflicts', []))}",
            f"- Duplicates: {report.get('duplicate_count', 0)}",
            f"- Negation conflicts: {report.get('negation_conflict_count', 0)}",
        ]

        for entry in report.get("conflicts", []):
            reason = str(entry.get("reason", "unknown"))
            candidate = str(entry.get("candidate", "")).strip()
            conflicting = str(entry.get("conflicting_fact", "")).strip()
            detail = f"- {reason}: {candidate}" if candidate else f"- {reason}"
            if conflicting:
                detail += f" (conflicts with: {conflicting})"
            lines.append(detail)

        return "\n".join(lines)

    def _format_conflict_summary_line(self) -> str:
        report = self._last_canon_conflict_report
        if report is None:
            return "unavailable"
        return (
            f"{len(report.get('conflicts', []))} conflict(s), "
            f"dup={report.get('duplicate_count', 0)}, "
            f"neg={report.get('negation_conflict_count', 0)}"
        )

    def _format_timestamp(self, timestamp: float | None) -> str:
        if timestamp is None:
            return "n/a"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

    def _format_age_seconds(self, seconds: float | None) -> str:
        if seconds is None:
            return "n/a"
        total = max(0, int(seconds))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def _handle_summary_command(self, args: list[str]) -> str:
        """Inspect or clear the rolling session summary used for prompt continuity."""

        if args and args[0].lower() == "clear":
            self._session_summary = ""
            self._session_compacted_turns = len(self.transcript)
            try:
                self._persist_runtime_state_patch({"session_summary": ""})
            except Exception as exc:
                return f"Failed to clear session summary: {exc}"
            return "Session summary cleared."

        if args:
            return "Usage: /summary [clear]"

        lines = [
            "Session Summary",
            f"- Transcript turns: {len(self.transcript)}",
            f"- Compacted turns: {self._session_compacted_turns}",
            f"- Summary chars: {len(self._session_summary)}",
        ]
        if self._session_summary:
            lines.extend(["", self._session_summary])
        else:
            lines.append("- Summary text: <empty>")
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

    async def _run_autopilot_command(self, args: list[str]) -> str:
        """Run bounded generation loop with fail-closed canon verification."""

        if not self.mode_config.allows_autopilot_loop():
            return "Autopilot is disabled. Set /mode autopilot first."

        if not args:
            return "Usage: /autopilot <steps> <prompt>"

        default_steps = max(1, self.mode_config.max_autopilot_turns)
        available_steps = (
            self.autopilot_turns_remaining
            if self.autopilot_turns_remaining > 0
            else default_steps
        )

        steps = 1
        prompt_tokens = args
        if args[0].isdigit():
            steps = max(1, min(available_steps, int(args[0])))
            prompt_tokens = args[1:]
        else:
            steps = min(default_steps, available_steps)

        if not prompt_tokens:
            return "Usage: /autopilot <steps> <prompt>"

        if available_steps <= 0:
            return "No autopilot turns remaining. Run /mode autopilot <max_turns>."

        seed_prompt = " ".join(prompt_tokens).strip()
        chapter = self._active_chapter_for_canon()

        lines = [
            "Autopilot Run",
            f"- Steps requested: {steps}",
            f"- Active chapter: {chapter}",
        ]

        committed = 0
        skipped = 0
        user_prompt = seed_prompt

        for idx in range(1, steps + 1):
            provider = self._active_provider()
            model_id = self._active_model()
            recent_turns = self._recent_turns_for_prompt()
            scoped_prompt, budget, diagnostics = await asyncio.to_thread(
                self.state_engine.compose_prompt_with_diagnostics,
                user_prompt,
                provider=provider,
                model_id=model_id,
                output_reserve_tokens=(
                    self.config.max_tokens if self.config is not None else None
                ),
                recent_turns=recent_turns,
            )
            self._last_prompt_budget = budget
            self._last_prompt_diagnostics = diagnostics
            self._last_prompt_provider = provider
            self._last_prompt_model = model_id
            response = await asyncio.to_thread(
                self._invoke_assistant_sync, scoped_prompt
            )
            self._last_assistant_response = response
            self.transcript.append(
                {
                    "user": f"[autopilot:{idx}] {user_prompt}",
                    "answer": response,
                }
            )
            self._roll_session_summary_if_needed()

            candidates = await self._extract_candidates_with_hybrid_worker(
                response=response,
                chapter=chapter,
            )

            step_committed = 0
            step_skipped = 0
            for candidate in candidates:
                result = await asyncio.to_thread(
                    verify_candidate_against_canon,
                    book_path=str(self.book_path),
                    chapter=chapter,
                    candidate_text=candidate.text,
                )
                if not result.allowed:
                    step_skipped += 1
                    continue

                add_fact(
                    str(self.book_path),
                    chapter=chapter,
                    text=candidate.text,
                    fact_type=candidate.fact_type,
                    source="accepted",
                )
                step_committed += 1

            committed += step_committed
            skipped += step_skipped
            lines.append(
                f"- Step {idx}: committed={step_committed}, skipped={step_skipped}, candidates={len(candidates)}"
            )
            user_prompt = f"Continue scene progression after step {idx}."

        lines.append(f"- Final committed: {committed}")
        lines.append(f"- Final skipped: {skipped}")
        self.autopilot_turns_remaining = max(0, available_steps - steps)
        self._persist_mode_session_state()
        lines.append(f"- Turns remaining: {self.autopilot_turns_remaining}")
        return "\n".join(lines)

    def _handle_mode_command(self, args: list[str]) -> str:
        """Show or update execution mode state for TUI workflows."""

        if not args:
            state = mode_show_impl(str(self.book_path))
            self.mode_config = state.mode_config
            self.autopilot_turns_remaining = state.autopilot_turns_remaining
            return (
                f"Execution mode: {self.execution_mode.value}\n"
                f"Max autopilot turns: {self.mode_config.max_autopilot_turns}\n"
                f"Autopilot turns remaining: {self.autopilot_turns_remaining}\n"
                "Usage: /mode [manual|hybrid|autopilot [max_turns]]"
            )

        requested_mode = args[0].lower().strip()
        if requested_mode not in {"manual", "hybrid", "autopilot"}:
            return "Usage: /mode [manual|hybrid|autopilot [max_turns]]"

        turns: int | None = None
        if requested_mode == "autopilot" and len(args) > 1:
            if not args[1].isdigit():
                return "Usage: /mode autopilot [max_turns]"
            turns = int(args[1])

        try:
            updated = mode_set_impl(
                str(self.book_path),
                requested_mode,
                turns=turns,
            )
        except Exception as exc:
            return f"Failed to persist execution mode: {str(exc)}"

        self.mode_config = updated.mode_config
        self.autopilot_turns_remaining = updated.autopilot_turns_remaining
        self._refresh_mode_indicator()
        if updated.mode_config.mode is ExecutionMode.AUTOPILOT:
            return (
                f"Execution mode set to {self.execution_mode.value} "
                f"({self.autopilot_turns_remaining} turns available)."
            )
        return f"Execution mode set to {self.execution_mode.value}."

    def _handle_stop_command(self) -> str:
        """Force manual mode and stop any further autonomous generation turns."""

        try:
            updated = mode_set_impl(
                str(self.book_path),
                ExecutionMode.MANUAL.value,
                turns=0,
            )
        except Exception as exc:
            return f"Failed to persist execution mode: {str(exc)}"

        self.mode_config = updated.mode_config
        self.autopilot_turns_remaining = updated.autopilot_turns_remaining
        self._refresh_mode_indicator()
        return "Execution stopped. Mode set to manual."

    def _load_mode_session_state(self) -> None:
        """Restore mode configuration and counters from runtime session metadata."""

        session_state = mode_show_impl(str(self.book_path))
        self.mode_config = session_state.mode_config
        self.autopilot_turns_remaining = session_state.autopilot_turns_remaining

    def _persist_mode_session_state(self) -> None:
        """Persist mode configuration and counters to runtime session metadata."""

        session_state = TuiSessionState(
            mode_config=self.mode_config,
            autopilot_turns_remaining=self.autopilot_turns_remaining,
        )
        self._persist_runtime_state_patch(session_state.to_dict())

    def _load_session_summary_state(self) -> None:
        """Restore compact session summary from runtime metadata."""

        state = self.session_manager.load_runtime_state()
        summary_raw = state.get("session_summary")
        if isinstance(summary_raw, str):
            self._session_summary = self._truncate_summary(summary_raw.strip())
        else:
            self._session_summary = ""

    def _persist_runtime_state_patch(self, updates: dict[str, Any]) -> None:
        """Persist runtime metadata updates without clobbering sibling keys."""

        state = self.session_manager.load_runtime_state()
        state.update(updates)
        self.session_manager.save_runtime_state(state)

    def _refresh_mode_indicator(self) -> None:
        """Render the footer-adjacent mode indicator in the TUI."""

        try:
            indicator = self.query_one("#mode-indicator", Static)
        except Exception:
            return
        indicator.update(f"[ MODE: {self.execution_mode.name} ]")

    def _active_chapter_for_canon(self) -> int:
        """Resolve active chapter for canon operations, defaulting to chapter 1."""

        state = self.state_engine.get_state()
        if state.active_chapter is None:
            return 1
        return max(1, int(state.active_chapter))

    async def _maybe_queue_hybrid_canon_candidates(self, response: str) -> None:
        """Queue extracted canon candidates when HYBRID mode is enabled."""

        if self.execution_mode is not ExecutionMode.HYBRID:
            return

        chapter = self._active_chapter_for_canon()
        extracted = await self._extract_candidates_with_hybrid_worker(
            response=response,
            chapter=chapter,
        )
        if not extracted:
            return

        existing_facts = {
            fact.text.strip().lower()
            for fact in list_facts(str(self.book_path), chapter=chapter)
            if fact.text.strip()
        }
        pending = {
            candidate.text.strip().lower()
            for candidate in self.pending_canon_candidates
            if candidate.chapter == chapter and candidate.text.strip()
        }

        added = 0
        for candidate in extracted:
            key = candidate.text.strip().lower()
            if key in existing_facts or key in pending:
                continue
            self.pending_canon_candidates.append(candidate)
            pending.add(key)
            added += 1

        if added <= 0:
            return

        self.query_one("#output", RichLog).write(
            "[cyan]Hybrid Canon:[/cyan] "
            f"queued {added} candidate fact(s). "
            "Review with /canon pending and accept via /canon accept <indexes>."
        )

    async def _warn_about_canon_conflicts(self, response: str) -> None:
        """Surface likely canon contradictions as non-blocking writer warnings."""

        chapter = self._active_chapter_for_canon()
        report = await self._analyze_canon_conflicts(response=response, chapter=chapter)
        self._last_canon_conflict_report = report

        conflicts = report["conflicts"]
        if not conflicts:
            return

        lines = [
            "[yellow]Potential Canon Conflicts[/yellow]",
            f"- Chapter: {chapter}",
        ]
        for entry in conflicts:
            reason = str(entry.get("reason", "unknown"))
            candidate = str(entry.get("candidate", "")).strip()
            conflicting = str(entry.get("conflicting_fact", "")).strip()
            text = f"{reason}: {candidate}" if candidate else reason
            if conflicting:
                text += f" (conflicts with: {conflicting})"
            lines.append(f"- {escape(text)}")
        lines.append(
            "- Review canon with /canon show and adjust before accepting output."
        )

        self.query_one("#output", RichLog).write("\n".join(lines))

    async def _analyze_canon_conflicts(
        self,
        *,
        response: str,
        chapter: int,
    ) -> dict[str, Any]:
        """Analyze response against canon and return structured conflict report."""

        result = await asyncio.to_thread(
            canon_check_impl,
            str(self.book_path),
            chapter=chapter,
            text=response,
            max_candidates=5,
        )
        conflicts: list[dict[str, str]] = []
        duplicate_count = 0
        negation_count = 0
        for row in result.rows:
            if row.reason == "negation-conflict":
                negation_count += 1
                conflicts.append(
                    {
                        "reason": "negation conflict",
                        "candidate": row.candidate,
                        "conflicting_fact": row.conflicting_fact or "",
                    }
                )
            elif row.reason == "duplicate":
                duplicate_count += 1
                conflicts.append(
                    {
                        "reason": "duplicate canon fact",
                        "candidate": row.candidate,
                        "conflicting_fact": "",
                    }
                )

        return {
            "chapter": chapter,
            "checked_candidates": result.checked_candidates,
            "duplicate_count": duplicate_count,
            "negation_conflict_count": negation_count,
            "conflicts": conflicts,
        }

    async def _extract_candidates_with_hybrid_worker(
        self, *, response: str, chapter: int
    ) -> list[CanonCandidate]:
        """Extract candidates using sub-agent worker pool when available."""

        manager = self._ensure_hybrid_extract_manager()
        if manager is None:
            return await asyncio.to_thread(
                extract_canon_candidates,
                response,
                chapter=chapter,
            )

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            manager.executor,
            lambda: extract_canon_candidates(response, chapter=chapter),
        )

    def _ensure_hybrid_extract_manager(self) -> SubAgentJobManager | None:
        """Lazily initialize worker manager used by hybrid extraction."""

        if self._hybrid_extract_manager is not None:
            return self._hybrid_extract_manager

        try:
            self._hybrid_extract_manager = SubAgentJobManager(
                str(self.book_path),
                console=Console(),
            )
        except Exception:
            self._hybrid_extract_manager = None
        return self._hybrid_extract_manager

    async def _handle_canon_command(self, args: list[str]) -> str:
        """Handle chapter-scoped canon ledger commands."""

        active_chapter = self._active_chapter_for_canon()

        try:
            if not args:
                return self._render_canon_summary(active_chapter)

            mode = args[0].lower()
            if mode == "show":
                chapter = active_chapter
                if len(args) >= 2:
                    try:
                        chapter = max(1, int(args[1]))
                    except ValueError:
                        return "Usage: /canon show [chapter_number]"
                return self._render_canon_verbose(chapter)

            if mode == "pending":
                return self._render_canon_pending()

            if mode == "add":
                return self._canon_add_fact(args[1:], active_chapter)

            if mode in {"check-last", "check_latest", "checklatest"}:
                return await self._canon_check_last_response(active_chapter)

            if mode == "accept":
                return self._canon_accept_candidates(args[1:])

            if mode == "reject":
                return self._canon_reject_candidates(args[1:])

            if mode in {"clear", "reset"}:
                if len(args) >= 2 and args[1].lower() == "confirm":
                    removed = clear_chapter_facts(str(self.book_path), active_chapter)
                    return f"[Done] Cleared {removed} canon fact(s) for chapter {active_chapter}."
                return (
                    f"About to clear canon facts for chapter {active_chapter}. "
                    "Run /canon clear confirm to proceed."
                )
        except RuntimeError as exc:
            return f"Canon Guard error: {exc}"

        return (
            "Usage: /canon [show [chapter]|pending] | /canon add <fact> | "
            "/canon add <chapter> :: <fact> | /canon check-last | "
            "/canon accept <n[,m,...]> | "
            "/canon reject [n[,m,...]] | /canon clear [confirm]"
        )

    async def _canon_check_last_response(self, chapter: int) -> str:
        """Rerun canon conflict checks on the last assistant response."""

        if not self._last_assistant_response.strip():
            return "No assistant response available. Generate output first."

        report = await self._analyze_canon_conflicts(
            response=self._last_assistant_response,
            chapter=chapter,
        )
        self._last_canon_conflict_report = report

        conflicts = report.get("conflicts", [])
        if not conflicts:
            return (
                "Canon check complete\n"
                f"- Chapter: {chapter}\n"
                f"- Checked candidates: {report.get('checked_candidates', 0)}\n"
                "- Conflicts: none"
            )

        lines = [
            "Canon check complete",
            f"- Chapter: {chapter}",
            f"- Checked candidates: {report.get('checked_candidates', 0)}",
            f"- Conflicts: {len(conflicts)}",
        ]
        for entry in conflicts:
            reason = str(entry.get("reason", "unknown"))
            candidate = str(entry.get("candidate", "")).strip()
            conflicting = str(entry.get("conflicting_fact", "")).strip()
            text = f"- {reason}: {candidate}" if candidate else f"- {reason}"
            if conflicting:
                text += f" (conflicts with: {conflicting})"
            lines.append(text)
        return "\n".join(lines)

    def _canon_accept_candidates(self, args: list[str]) -> str:
        """Accept pending extraction candidates into the canon ledger."""

        if not self.pending_canon_candidates:
            return "No pending canon candidates to accept."
        if not args:
            return "Usage: /canon accept <n[,m,...]>"

        indexes = self._parse_candidate_indexes(args[0])
        if not indexes:
            return "Usage: /canon accept <n[,m,...]>"

        accepted = 0
        skipped = 0
        kept: list[CanonCandidate] = []
        for idx, candidate in enumerate(self.pending_canon_candidates, start=1):
            if idx not in indexes:
                kept.append(candidate)
                continue
            result = verify_candidate_against_canon(
                book_path=str(self.book_path),
                chapter=candidate.chapter,
                candidate_text=candidate.text,
            )
            if not result.allowed:
                skipped += 1
                continue
            add_fact(
                str(self.book_path),
                chapter=candidate.chapter,
                text=candidate.text,
                fact_type=candidate.fact_type,
                source="accepted",
            )
            accepted += 1

        self.pending_canon_candidates = kept
        return (
            f"[Done] Accepted {accepted} canon candidate(s). "
            f"Skipped {skipped} due to verification."
        )

    def _canon_reject_candidates(self, args: list[str]) -> str:
        """Reject pending candidates either by index list or all at once."""

        if not self.pending_canon_candidates:
            return "No pending canon candidates to reject."

        if not args:
            removed = len(self.pending_canon_candidates)
            self.pending_canon_candidates = []
            return f"[Done] Rejected {removed} pending canon candidate(s)."

        indexes = self._parse_candidate_indexes(args[0])
        if not indexes:
            return "Usage: /canon reject [n[,m,...]]"

        removed = 0
        kept: list[CanonCandidate] = []
        for idx, candidate in enumerate(self.pending_canon_candidates, start=1):
            if idx in indexes:
                removed += 1
                continue
            kept.append(candidate)

        self.pending_canon_candidates = kept
        return f"[Done] Rejected {removed} pending canon candidate(s)."

    def _parse_candidate_indexes(self, raw: str) -> set[int]:
        """Parse one-based candidate index list such as '1,2,4'."""

        parsed: set[int] = set()
        for token in raw.split(","):
            item = token.strip()
            if not item:
                continue
            if not item.isdigit():
                return set()
            value = int(item)
            if value < 1:
                return set()
            parsed.add(value)
        return parsed

    def _canon_add_fact(self, args: list[str], active_chapter: int) -> str:
        """Parse add command and append one canon fact."""

        if not args:
            return "Usage: /canon add <fact> OR /canon add <chapter> :: <fact>"

        raw = " ".join(args).strip()
        chapter = active_chapter
        text = raw

        if "::" in raw:
            prefix, suffix = raw.split("::", maxsplit=1)
            prefix = prefix.strip()
            text = suffix.strip()
            if not text:
                return "Canon fact text cannot be empty."
            try:
                chapter = max(1, int(prefix))
            except ValueError:
                return "Usage: /canon add <chapter> :: <fact>"

        fact = add_fact(str(self.book_path), chapter=chapter, text=text)
        return f"[Done] Canon fact added to chapter {fact.chapter}:\n{fact.text}"

    def _render_canon_summary(self, chapter: int) -> str:
        """Render compact chapter-level canon summary."""

        facts = list_facts(str(self.book_path), chapter=chapter)
        lines = [
            "Canon Guard",
            f"Active chapter: {chapter}",
            f"Accepted facts: {len(facts)}",
            f"Pending candidates: {len(self.pending_canon_candidates)}",
        ]

        if not facts:
            lines.append("No canon facts recorded for this chapter yet.")
            return "\n".join(lines)

        lines.append("")
        lines.extend(f"{idx}. {fact.text}" for idx, fact in enumerate(facts, start=1))
        return "\n".join(lines)

    def _render_canon_verbose(self, chapter: int) -> str:
        """Render verbose chapter-level canon facts with metadata."""

        facts = list_facts(str(self.book_path), chapter=chapter)
        lines = ["Canon Guard", f"Chapter: {chapter}", ""]

        if not facts:
            lines.append("No canon facts recorded for this chapter yet.")
            return "\n".join(lines)

        lines.extend(
            f"- [{fact.type}] {fact.text} (source={fact.source})" for fact in facts
        )
        return "\n".join(lines)

    def _render_canon_pending(self) -> str:
        """Render pending extracted canon candidates awaiting user approval."""

        if not self.pending_canon_candidates:
            return "Canon Guard\nNo pending canon candidates."

        lines = ["Canon Guard", "Pending Canon Candidates", ""]
        for idx, candidate in enumerate(self.pending_canon_candidates, start=1):
            lines.append(
                f"{idx}. (chapter {candidate.chapter}) [{candidate.fact_type}] {candidate.text}"
            )
        lines.extend(
            [
                "",
                "Accept with: /canon accept <n[,m,...]>",
                "Reject with: /canon reject [n[,m,...]]",
            ]
        )
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

        models = fetch_free_openrouter_models(
            api_key=self._openrouter_api_key(),
            force_refresh=force_refresh,
        )
        self._cached_free_models = models
        self._cached_free_models_at = now
        return models

    def _render_model_list(self, force_refresh: bool = False) -> str:
        try:
            models = self._get_free_models(force_refresh=force_refresh)
        except Exception as exc:
            if self._cached_free_models:
                lines = [
                    f"Failed to refresh OpenRouter models: {exc}",
                    "Using cached free model list:",
                ]
                lines.extend(
                    "- "
                    f"{model.model_id} | context={model.context_length} | "
                    f"max_completion={model.max_completion_tokens or 'unknown'} | "
                    f"{model.label}"
                    for model in self._cached_free_models
                )
                return "\n".join(lines)
            return f"Failed to fetch OpenRouter models: {exc}"

        if not models:
            return "No free OpenRouter models were found in the current API response."

        lines = ["Free OpenRouter Models"]
        lines.extend(
            "- "
            f"{model.model_id} | context={model.context_length} | "
            f"max_completion={model.max_completion_tokens or 'unknown'} | "
            f"{model.label}"
            for model in models
        )
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
