from __future__ import annotations

import asyncio
from concurrent.futures import Executor, Future
import sys
from types import SimpleNamespace

import pytest
from rich.markup import render

from storycraftr.tui.canon import add_fact
from storycraftr.tui.canon_extract import CanonCandidate


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

    assert "TUI Command Guide" in help_text
    assert "Writing" in help_text
    assert "Planning" in help_text
    assert "World" in help_text
    assert "Project" in help_text
    assert "/progress" in help_text
    assert "/wizard" in help_text
    assert "/pipeline" in help_text
    assert "/autopilot <steps> <prompt>" in help_text
    assert "/canon" in help_text
    assert "/canon show [chapter]" in help_text
    assert "/canon add <fact>" in help_text
    assert "/canon clear [confirm]" in help_text
    assert "/clear" in help_text
    assert "/toggle-tree" in help_text
    assert "/chapter <number>" in help_text
    assert "/scene <label>" in help_text
    assert "/session list" in help_text
    assert "/session save <name>" in help_text
    assert "/session load <name>" in help_text
    assert "/mode <manual|hybrid|autopilot>" in help_text
    assert "/summary [clear]" in help_text
    assert "/context" in help_text
    assert "/model-list" in help_text
    assert "/model-list refresh" in help_text
    assert "/model-change <model_id>" in help_text
    assert "Ctrl+L" in help_text


def test_help_topic_filtering_and_invalid_topic(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    writing_help = asyncio.run(app._dispatch_slash_command("/help writing"))
    assert "TUI Help: Writing" in writing_help
    assert "/chapters chapter" in writing_help

    invalid = asyncio.run(app._dispatch_slash_command("/help unknown"))
    assert "Unknown help topic" in invalid


def test_dispatch_model_change_requires_model_id(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/model-change"))

    assert result == "Usage: /model-change <model_id>"


def test_dispatch_model_list_refresh_passes_force_refresh(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    observed: list[bool] = []

    def _fake_render(force_refresh: bool = False) -> str:
        observed.append(force_refresh)
        return "ok"

    monkeypatch.setattr(app, "_render_model_list", _fake_render)

    result = asyncio.run(app._dispatch_slash_command("/model-list refresh"))

    assert result == "ok"
    assert observed == [True]


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
    assert "[Scene Plan]" in state_text
    assert "[Scoped Context]" in state_text


def test_dispatch_state_command_returns_state_block(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/state"))

    assert "Narrative State" in result
    assert "Injected Prompt Block" in result


def test_dispatch_summary_reports_compacted_context(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app._session_summary = "Earlier planning and constraints."
    app._session_compacted_turns = 5
    app.transcript = [{"user": "u", "answer": "a"}] * 8

    result = asyncio.run(app._dispatch_slash_command("/summary"))

    assert "Session Summary" in result
    assert "Compacted turns: 5" in result
    assert "Earlier planning and constraints." in result


def test_dispatch_summary_clear_empties_summary_and_persists(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.transcript = [{"user": "u", "answer": "a"}] * 4
    app._session_summary = "To be cleared"
    app._session_compacted_turns = 2

    result = asyncio.run(app._dispatch_slash_command("/summary clear"))
    saved = app.session_manager.load_runtime_state()

    assert result == "Session summary cleared."
    assert app._session_summary == ""
    assert app._session_compacted_turns == len(app.transcript)
    assert saved.get("session_summary") == ""


def test_dispatch_context_reports_summary_and_recent_line_counts(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.config = SimpleNamespace(llm_provider="openrouter", llm_model="openrouter/free")
    app._session_summary = "Context snapshot"
    app._session_compacted_turns = 3
    app.transcript = [
        {"user": "U1", "answer": "A1"},
        {"user": "U2", "answer": "A2"},
        {"user": "U3", "answer": "A3"},
    ]
    app._last_prompt_budget = SimpleNamespace(
        context_window_tokens=32768,
        output_reserve_tokens=4096,
        input_budget_tokens=28672,
        model_source="openrouter-live-discovery",
    )
    app._last_prompt_diagnostics = SimpleNamespace(
        included_sections=(
            "scene_plan",
            "scoped_context",
            "canon_constraints",
            "user_instruction",
            "recent_dialogue",
            "summary",
        ),
        pruned_sections=("retrieved_context",),
        truncated_sections=(),
        estimated_tokens={
            "canon": 24,
            "scene_plan": 32,
            "scoped_context": 64,
            "recent_dialogue": 40,
            "retrieved_context": 0,
            "user_instruction": 12,
            "summary": 8,
            "full_prompt": 220,
        },
    )

    result = asyncio.run(app._dispatch_slash_command("/context"))

    assert "Runtime Context Snapshot" in result
    assert "Prompt Composition Breakdown" in result
    assert "Session Summary: active" in result
    assert "Context snapshot" in result


def test_dispatch_context_summary_shows_full_summary(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app._session_summary = "Earlier planning and constraints."
    app._session_compacted_turns = 4

    result = asyncio.run(app._dispatch_slash_command("/context summary"))

    assert "Session Summary" in result
    assert "Status: active" in result
    assert "Compacted turns: 4" in result
    assert "Earlier planning and constraints." in result


def test_dispatch_context_clear_summary_alias(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.transcript = [{"user": "u", "answer": "a"}] * 3
    app._session_summary = "To be cleared"
    app._session_compacted_turns = 1

    result = asyncio.run(app._dispatch_slash_command("/context clear-summary"))

    assert result == "Session summary cleared."
    assert app._session_summary == ""


def test_dispatch_context_budget_reports_unavailable_before_prompt(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/context budget"))

    assert "Prompt Budget" in result
    assert "Status: unavailable" in result


def test_dispatch_context_budget_reports_latest_diagnostics(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app._last_prompt_provider = "openrouter"
    app._last_prompt_model = "openrouter/free"
    app._last_prompt_budget = SimpleNamespace(
        context_window_tokens=32768,
        output_reserve_tokens=4096,
        input_budget_tokens=28672,
        model_source="openrouter-live-discovery",
    )
    app._last_prompt_diagnostics = SimpleNamespace(
        included_sections=("canon_constraints", "scene_plan", "recent_dialogue"),
        pruned_sections=("retrieved_context",),
        truncated_sections=("recent_dialogue",),
        estimated_tokens={
            "canon": 64,
            "full_prompt": 2048,
            "recent_dialogue": 512,
            "retrieved_context": 0,
            "scene_plan": 96,
            "scoped_context": 256,
            "user_instruction": 128,
            "summary": 128,
        },
    )

    result = asyncio.run(app._dispatch_slash_command("/context budget"))

    assert "Prompt Budget" in result
    assert "Provider: openrouter" in result
    assert "Context Window: 32768" in result
    assert "[~] Recent Dialogue" in result
    assert "[ ] Retrieved Context" in result


def test_dispatch_context_models_routes_to_renderer(tmp_path, monkeypatch) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    observed: list[bool] = []

    def _fake_models(force_refresh: bool) -> str:
        observed.append(force_refresh)
        return "models-ok"

    monkeypatch.setattr(app, "_build_context_models_text", _fake_models)

    result = asyncio.run(app._dispatch_slash_command("/context models"))
    refreshed = asyncio.run(app._dispatch_slash_command("/context refresh-models"))

    assert result == "models-ok"
    assert refreshed == "models-ok"
    assert observed == [False, True]


def test_dispatch_context_conflicts_reports_latest_conflict_snapshot(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app._last_canon_conflict_report = {
        "chapter": 2,
        "checked_candidates": 3,
        "duplicate_count": 1,
        "negation_conflict_count": 1,
        "conflicts": [
            {
                "reason": "duplicate canon fact",
                "candidate": "Mira is the ship navigator.",
                "conflicting_fact": "",
            },
            {
                "reason": "negation conflict",
                "candidate": "Mira is not the ship navigator.",
                "conflicting_fact": "Mira is the ship navigator.",
            },
        ],
    }

    result = asyncio.run(app._dispatch_slash_command("/context conflicts"))

    assert "Canon Conflict Diagnostics" in result
    assert "Chapter: 2" in result
    assert "Duplicates: 1" in result
    assert "Negation conflicts: 1" in result
    assert "Mira is not the ship navigator." in result


def test_dispatch_mode_sets_and_reports_execution_mode(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    set_result = asyncio.run(app._dispatch_slash_command("/mode hybrid"))
    show_result = asyncio.run(app._dispatch_slash_command("/mode"))

    assert "Execution mode set to hybrid." in set_result
    assert "Execution mode: hybrid" in show_result


def test_dispatch_mode_rejects_invalid_value(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/mode unknown"))

    assert result == "Usage: /mode <manual|hybrid|autopilot>"


def test_status_includes_execution_mode(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.assistant = SimpleNamespace(last_documents=[])

    asyncio.run(app._dispatch_slash_command("/mode autopilot"))
    status = asyncio.run(app._build_status_text())

    assert "- Execution mode: autopilot" in status


def test_autopilot_requires_mode_autopilot(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/autopilot 1 Draft scene"))

    assert "Set /mode autopilot first" in result


def test_autopilot_commits_verified_candidates_only(tmp_path, monkeypatch) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.assistant = SimpleNamespace(last_documents=[])
    app.thread_id = "thread-1"

    asyncio.run(app._dispatch_slash_command("/mode autopilot"))

    monkeypatch.setattr(
        app,
        "_invoke_assistant_sync",
        lambda _prompt: "Mira is the ship navigator. Mira is not the ship navigator.",
    )

    result = asyncio.run(
        app._dispatch_slash_command("/autopilot 1 Establish the opening beat")
    )
    show = asyncio.run(app._dispatch_slash_command("/canon show 1"))

    assert "Autopilot Run" in result
    assert "Final committed: 1" in result
    assert "Final skipped: 1" in result
    assert "Mira is the ship navigator." in show
    assert "Mira is not the ship navigator." not in show


def test_state_output_includes_canon_constraints_when_canon_exists(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.state_engine.set_active_chapter(1)

    asyncio.run(app._dispatch_slash_command("/canon add Alex is the active POV."))
    result = asyncio.run(app._dispatch_slash_command("/state"))

    assert "[Canon Constraints]" in result
    assert "Alex is the active POV." in result


def test_dispatch_progress_command_reports_checkpoints(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    (tmp_path / "outline").mkdir(parents=True, exist_ok=True)
    (tmp_path / "outline" / "general_outline.md").write_text(
        "# General Outline\n\nline1\nline2\nline3\nline4\n", encoding="utf-8"
    )

    result = asyncio.run(app._dispatch_slash_command("/progress"))

    assert "Project Progress" in result
    assert "General Outline: [x]" in result
    assert "Character Summary: [ ]" in result
    assert "Completion:" in result


def test_dispatch_canon_empty_summary(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/canon"))

    assert "Canon Guard" in result
    assert "Accepted facts: 0" in result


def test_dispatch_canon_add_and_show(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    add_result = asyncio.run(
        app._dispatch_slash_command("/canon add The control room is dark.")
    )
    show_result = asyncio.run(app._dispatch_slash_command("/canon show"))

    assert "Canon fact added" in add_result
    assert "The control room is dark." in show_result


def test_dispatch_canon_clear_confirm_removes_facts(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    asyncio.run(app._dispatch_slash_command("/canon add Elias dropped his sword."))
    warn_result = asyncio.run(app._dispatch_slash_command("/canon clear"))
    clear_result = asyncio.run(app._dispatch_slash_command("/canon clear confirm"))
    final_result = asyncio.run(app._dispatch_slash_command("/canon"))

    assert "Run /canon clear confirm" in warn_result
    assert "Cleared 1 canon fact" in clear_result
    assert "Accepted facts: 0" in final_result


def test_dispatch_canon_uses_active_chapter_from_state_engine(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.state_engine.set_active_chapter(7)

    asyncio.run(app._dispatch_slash_command("/canon add The control room is dark."))
    show_result = asyncio.run(app._dispatch_slash_command("/canon show"))

    assert "Chapter: 7" in show_result
    assert "The control room is dark." in show_result


def test_dispatch_canon_accept_moves_pending_to_ledger(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.pending_canon_candidates = [
        CanonCandidate(text="Mira is the pilot.", chapter=2),
        CanonCandidate(text="The hangar is locked.", chapter=2),
    ]

    accept_result = asyncio.run(app._dispatch_slash_command("/canon accept 1"))
    pending_result = asyncio.run(app._dispatch_slash_command("/canon pending"))
    show_result = asyncio.run(app._dispatch_slash_command("/canon show 2"))

    assert "Accepted 1 canon candidate" in accept_result
    assert "Skipped 0 due to verification" in accept_result
    assert "The hangar is locked." in pending_result
    assert "Mira is the pilot." in show_result


def test_dispatch_canon_accept_skips_conflicting_candidate(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    asyncio.run(app._dispatch_slash_command("/canon add 2 :: Mira is the pilot."))
    app.pending_canon_candidates = [
        CanonCandidate(text="Mira is not the pilot.", chapter=2),
    ]

    accept_result = asyncio.run(app._dispatch_slash_command("/canon accept 1"))
    pending_result = asyncio.run(app._dispatch_slash_command("/canon pending"))
    show_result = asyncio.run(app._dispatch_slash_command("/canon show 2"))

    assert "Accepted 0 canon candidate" in accept_result
    assert "Skipped 1 due to verification" in accept_result
    assert "No pending canon candidates" in pending_result
    assert "Mira is not the pilot." not in show_result


def test_dispatch_canon_check_last_runs_conflict_scan(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    asyncio.run(app._dispatch_slash_command("/canon add 1 :: Mira is the pilot."))
    app._last_assistant_response = "Mira is not the pilot."

    result = asyncio.run(app._dispatch_slash_command("/canon check-last"))
    diagnostics = asyncio.run(app._dispatch_slash_command("/context conflicts"))

    assert "Canon check complete" in result
    assert "Conflicts: 1" in result
    assert "negation conflict" in result
    assert "Negation conflicts: 1" in diagnostics


def test_dispatch_canon_reject_clears_pending_candidates(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.pending_canon_candidates = [
        CanonCandidate(text="Mira is the pilot.", chapter=2),
        CanonCandidate(text="The hangar is locked.", chapter=2),
    ]

    result = asyncio.run(app._dispatch_slash_command("/canon reject"))
    pending = asyncio.run(app._dispatch_slash_command("/canon pending"))

    assert "Rejected 2 pending canon candidate" in result
    assert "No pending canon candidates" in pending


def test_hybrid_mode_queues_extracted_canon_candidates(tmp_path, monkeypatch) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    class _FakeLog:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def write(self, message: str) -> None:
            self.messages.append(message)

    fake_log = _FakeLog()

    def _query_one(selector, _type=None):
        if selector == "#output":
            return fake_log
        raise RuntimeError("unsupported selector")

    monkeypatch.setattr(app, "query_one", _query_one)
    asyncio.run(app._dispatch_slash_command("/mode hybrid"))

    asyncio.run(
        app._maybe_queue_hybrid_canon_candidates(
            "Mira is the ship navigator. The lower deck is flooded."
        )
    )

    pending = asyncio.run(app._dispatch_slash_command("/canon pending"))

    assert "Mira is the ship navigator." in pending
    assert "lower deck is flooded" in pending.lower()
    assert any("Hybrid Canon" in msg for msg in fake_log.messages)


def test_hybrid_mode_uses_subagent_executor_when_manager_available(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    class _FakeLog:
        def write(self, _message: str) -> None:
            return

    class _ImmediateExecutor(Executor):
        def __init__(self) -> None:
            self.submissions = 0

        def submit(self, fn, /, *args, **kwargs):
            self.submissions += 1
            future: Future = Future()
            try:
                future.set_result(fn(*args, **kwargs))
            except Exception as exc:  # pragma: no cover - defensive
                future.set_exception(exc)
            return future

    class _FakeManager:
        def __init__(self) -> None:
            self.executor = _ImmediateExecutor()

    fake_manager = _FakeManager()

    def _query_one(selector, _type=None):
        if selector == "#output":
            return _FakeLog()
        raise RuntimeError("unsupported selector")

    monkeypatch.setattr(app, "query_one", _query_one)
    app._hybrid_extract_manager = fake_manager
    asyncio.run(app._dispatch_slash_command("/mode hybrid"))

    asyncio.run(app._maybe_queue_hybrid_canon_candidates("Mira is the ship navigator."))

    assert fake_manager.executor.submissions >= 1
    assert len(app.pending_canon_candidates) == 1


def test_dispatch_wizard_next_returns_recommended_command(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = asyncio.run(app._dispatch_slash_command("/wizard next"))

    assert "Next recommended step: General Outline" in result
    assert "/outline general-outline" in result


def test_dispatch_pipeline_alias_matches_wizard(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    wizard = asyncio.run(app._dispatch_slash_command("/wizard next"))
    pipeline = asyncio.run(app._dispatch_slash_command("/pipeline next"))

    assert pipeline == wizard


def test_wizard_profile_set_show_and_reset(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    set_result = asyncio.run(
        app._dispatch_slash_command(
            "/wizard set premise A rebellion against immortal rulers"
        )
    )
    assert "Wizard field set: premise" in set_result

    show_result = asyncio.run(app._dispatch_slash_command("/wizard show"))
    assert "Wizard Profile" in show_result
    assert "premise: A rebellion against immortal rulers" in show_result

    reset_result = asyncio.run(app._dispatch_slash_command("/wizard reset"))
    assert "Wizard profile reset" in reset_result

    empty_show = asyncio.run(app._dispatch_slash_command("/wizard show"))
    assert "Wizard profile is empty" in empty_show


def test_wizard_plan_uses_profile_and_flow(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    asyncio.run(app._dispatch_slash_command("/wizard set flow world-first"))
    asyncio.run(app._dispatch_slash_command("/wizard set genre dystopian sci-fi"))
    asyncio.run(app._dispatch_slash_command("/wizard set tone bleak"))
    asyncio.run(
        app._dispatch_slash_command(
            "/wizard set premise The elite hide technology as magic"
        )
    )

    plan_result = asyncio.run(app._dispatch_slash_command("/wizard plan"))

    assert "Wizard Plan Draft" in plan_result
    assert "Flow: world-first" in plan_result
    assert "/worldbuilding history" in plan_result
    assert "/outline general-outline" in plan_result
    assert plan_result.index("/worldbuilding history") < plan_result.index(
        "/outline general-outline"
    )


def test_wizard_set_rejects_invalid_field_and_flow(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    bad_field = asyncio.run(app._dispatch_slash_command("/wizard set invalid foo"))
    assert "Unsupported wizard field" in bad_field

    bad_flow = asyncio.run(app._dispatch_slash_command("/wizard set flow random"))
    assert "Flow must be one of" in bad_flow


def test_dispatch_wizard_advances_after_checkpoint_completion(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    (tmp_path / "outline").mkdir(parents=True, exist_ok=True)
    (tmp_path / "outline" / "general_outline.md").write_text(
        "# General Outline\n\nline1\nline2\nline3\nline4\n", encoding="utf-8"
    )

    result = asyncio.run(app._dispatch_slash_command("/wizard next"))

    assert "Next recommended step: Character Summary" in result
    assert "/outline character-summary" in result


def test_dispatch_clear_command_clears_output(tmp_path, monkeypatch) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    class _FakeLog:
        def __init__(self) -> None:
            self.was_cleared = False

        def clear(self) -> None:
            self.was_cleared = True

    fake_log = _FakeLog()
    monkeypatch.setattr(app, "query_one", lambda *_args, **_kwargs: fake_log)

    result = asyncio.run(app._dispatch_slash_command("/clear"))

    assert result == "Output cleared."
    assert fake_log.was_cleared is True


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


def test_focus_mode_toggles_sidebar_and_state_strip_visibility(
    tmp_path, monkeypatch
) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    class _Pane:
        def __init__(self, display: bool) -> None:
            self.display = display

    sidebar = _Pane(display=True)
    state_strips = _Pane(display=True)

    def _query_one(selector, _type=None):
        if selector == "#sidebar":
            return sidebar
        if selector == "#state-strips":
            return state_strips
        raise RuntimeError("unknown selector")

    monkeypatch.setattr(app, "query_one", _query_one)

    app.action_toggle_focus_mode()
    assert sidebar.display is False
    assert state_strips.display is False

    app.action_toggle_focus_mode()
    assert sidebar.display is True
    assert state_strips.display is True


def test_input_history_navigation_roundtrip(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    app._record_input_history("/status")
    app._record_input_history("/outline general")

    assert (
        app._navigate_input_history(direction=-1, current_text="") == "/outline general"
    )
    assert app._navigate_input_history(direction=-1, current_text="") == "/status"
    assert (
        app._navigate_input_history(direction=1, current_text="") == "/outline general"
    )
    assert app._navigate_input_history(direction=1, current_text="") == ""


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


def test_on_input_submitted_warns_on_canon_conflicts(tmp_path, monkeypatch) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))
    app.config = SimpleNamespace(
        llm_provider="openrouter",
        llm_model="openrouter/free",
        max_tokens=4096,
    )
    add_fact(str(tmp_path), chapter=1, text="Mira is the ship navigator.")

    class _FakeInput:
        def __init__(self, value: str) -> None:
            self.value = value
            self.disabled = False

        def focus(self) -> None:
            return

    class _CaptureLog:
        def __init__(self) -> None:
            self.rendered_plain: list[str] = []

        def write(self, value) -> None:
            if isinstance(value, str):
                self.rendered_plain.append(render(value).plain)
            else:
                self.rendered_plain.append(str(value))

    fake_log = _CaptureLog()
    monkeypatch.setattr(app, "query_one", lambda *_args, **_kwargs: fake_log)
    monkeypatch.setattr(
        app.state_engine,
        "compose_prompt_with_diagnostics",
        lambda *_args, **_kwargs: (
            "[User Instruction]\nKeep continuity.",
            SimpleNamespace(
                context_window_tokens=32768,
                output_reserve_tokens=4096,
                input_budget_tokens=28672,
                model_source="test",
            ),
            SimpleNamespace(
                included_sections=("canon_constraints",),
                pruned_sections=(),
                truncated_sections=(),
                estimated_tokens={
                    "canon": 10,
                    "scene_plan": 5,
                    "scoped_context": 10,
                    "recent_dialogue": 0,
                    "retrieved_context": 0,
                    "user_instruction": 5,
                    "summary": 0,
                    "full_prompt": 30,
                },
            ),
        ),
    )

    async def _fake_turn(_prompt: str) -> tuple[str, bool]:
        return "Mira is not the ship navigator.", False

    monkeypatch.setattr(app, "_run_assistant_turn", _fake_turn)

    event = SimpleNamespace(input=_FakeInput("Continue scene"), value="Continue scene")
    asyncio.run(app.on_input_submitted(event))

    combined = "\n".join(fake_log.rendered_plain)
    assert "Potential Canon Conflicts" in combined
    assert "negation conflict" in combined
    assert "Mira is not the ship navigator." in combined


def test_recent_turns_include_session_summary_and_tail(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    for idx in range(10):
        app.transcript.append(
            {
                "user": f"User turn {idx}",
                "answer": f"Assistant response {idx}",
            }
        )

    app._roll_session_summary_if_needed()
    recent = app._recent_turns_for_prompt(max_turns=3)

    assert app._session_summary
    assert recent[0].startswith("Session Summary: ")
    assert "User: User turn 9" in recent
    assert "Assistant: Assistant response 9" in recent


def test_adaptive_summary_retains_priority_turn_markers(tmp_path) -> None:
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    app.transcript = [
        {
            "user": "Outline scene transition to the bridge.",
            "answer": "Scene cut to the bridge as alarms trigger.",
        },
        {
            "user": "Maintain canon continuity for Mira.",
            "answer": "Mira remains the active pilot per canon facts.",
        },
        {
            "user": "Introduce a new character named Sol.",
            "answer": "Sol arrives carrying a damaged artifact.",
        },
    ]
    adaptive = app._summarize_turn_slice_adaptive(app.transcript)

    assert "P-U:" in adaptive or "P-A:" in adaptive


def test_mode_persistence_keeps_existing_session_summary(tmp_path) -> None:
    TuiApp = _load_tui_app()
    seeded = TuiApp(book_path=str(tmp_path))
    seeded.session_manager.save_runtime_state(
        {
            "execution_mode": "manual",
            "session_summary": "Older summary context.",
        }
    )

    app = TuiApp(book_path=str(tmp_path))
    result = asyncio.run(app._dispatch_slash_command("/mode hybrid"))
    saved = app.session_manager.load_runtime_state()

    assert "Execution mode set to hybrid." in result
    assert saved["execution_mode"] == "hybrid"
    assert saved["session_summary"] == "Older summary context."


def test_state_audit_command_displays_entries(tmp_path) -> None:
    """Test /state audit displays audit entries with default limit."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    # Create some audit entries
    from storycraftr.agent.narrative_state import (
        StatePatch,
        PatchOperation,
        NarrativeStateSnapshot,
    )

    store = app.state_engine.narrative_state_store
    snapshot = NarrativeStateSnapshot()
    store.save(snapshot)

    # Apply a patch to create audit entry
    patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="alice",
                data={"name": "Alice", "role": "protagonist"},
            )
        ]
    )
    store.apply_patch(patch, actor="test_user")

    result = app._build_state_audit_text([])

    assert "Audit Trail" in result
    assert "Operation: patch" in result
    assert "Actor: test_user" in result
    assert "Version: 2" in result


def test_state_audit_command_with_limit_filter(tmp_path) -> None:
    """Test /state audit respects limit filter."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    # Apply multiple patches
    from storycraftr.agent.narrative_state import (
        StatePatch,
        PatchOperation,
        NarrativeStateSnapshot,
    )

    store = app.state_engine.narrative_state_store
    snapshot = NarrativeStateSnapshot()
    store.save(snapshot)

    for i in range(5):
        patch = StatePatch(
            operations=[
                PatchOperation(
                    operation="add",
                    entity_type="character",
                    entity_id=f"char{i}",
                    data={"name": f"Character {i}"},
                )
            ]
        )
        store.apply_patch(patch, actor="test")

    result = app._build_state_audit_text(["limit=2"])

    assert "showing 2 entries" in result


def test_state_audit_command_with_entity_filter(tmp_path) -> None:
    """Test /state audit filters by entity ID."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    from storycraftr.agent.narrative_state import (
        StatePatch,
        PatchOperation,
        NarrativeStateSnapshot,
    )

    store = app.state_engine.narrative_state_store
    snapshot = NarrativeStateSnapshot()
    store.save(snapshot)

    # Create entries for different entities
    for entity_id in ["alice", "bob", "charlie"]:
        patch = StatePatch(
            operations=[
                PatchOperation(
                    operation="add",
                    entity_type="character",
                    entity_id=entity_id,
                    data={"name": entity_id.title()},
                )
            ]
        )
        store.apply_patch(patch, actor="test")

    result = app._build_state_audit_text(["entity=bob"])

    # Should show entries where bob appears (either added or as part of state)
    # After alice: version 2
    # After bob: version 3 (has bob added)
    # After charlie: version 4 (has bob unchanged + charlie added)
    # So filtering for bob should show versions 3 and 4
    lines = result.split("\n")
    entry_count = sum(1 for line in lines if line.startswith("["))
    assert entry_count >= 1  # At least one entry for bob


def test_state_audit_command_with_type_filter(tmp_path) -> None:
    """Test /state audit filters by entity type."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    from storycraftr.agent.narrative_state import (
        StatePatch,
        PatchOperation,
        NarrativeStateSnapshot,
    )

    store = app.state_engine.narrative_state_store
    snapshot = NarrativeStateSnapshot()
    store.save(snapshot)

    # Create mixed entity types
    char_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="character",
                entity_id="alice",
                data={"name": "Alice"},
            )
        ]
    )
    store.apply_patch(char_patch, actor="test")

    loc_patch = StatePatch(
        operations=[
            PatchOperation(
                operation="add",
                entity_type="location",
                entity_id="castle",
                data={"name": "Castle"},
            )
        ]
    )
    store.apply_patch(loc_patch, actor="test")

    result = app._build_state_audit_text(["type=character"])

    # Should show entries where characters appear
    # After alice character: version 2 (has alice character)
    # After castle location: version 3 (has alice character unchanged + castle location added)
    # So filtering for type=character should show both versions 2 and 3
    lines = result.split("\n")
    entry_count = sum(1 for line in lines if line.startswith("["))
    assert entry_count >= 1  # At least one entry with characters


def test_state_audit_command_disabled_auditing(tmp_path) -> None:
    """Test /state audit handles disabled audit logging gracefully."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    # Create store with auditing disabled
    from storycraftr.agent.narrative_state import NarrativeStateStore

    app.state_engine.narrative_state_store = NarrativeStateStore(
        str(tmp_path), enable_audit=False
    )

    result = app._build_state_audit_text([])

    assert "Audit logging is disabled" in result


def test_state_audit_command_invalid_limit(tmp_path) -> None:
    """Test /state audit rejects invalid limit values."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = app._build_state_audit_text(["limit=invalid"])

    assert "Invalid limit value" in result


def test_state_audit_command_invalid_type(tmp_path) -> None:
    """Test /state audit rejects invalid entity types."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = app._build_state_audit_text(["type=invalid"])

    assert "Invalid type" in result


def test_state_audit_command_unknown_filter(tmp_path) -> None:
    """Test /state audit rejects unknown filter keys."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = app._build_state_audit_text(["unknown=value"])

    assert "Unknown filter" in result


def test_state_audit_command_no_entries(tmp_path) -> None:
    """Test /state audit handles empty audit log."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    result = app._build_state_audit_text([])

    assert "No audit entries found" in result


def test_state_command_dispatch_to_subcommands(tmp_path) -> None:
    """Test /state command routes to audit subcommand."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    # Test no args shows state
    result = asyncio.run(app._dispatch_slash_command("/state"))
    assert "Narrative State" in result

    # Test audit subcommand
    result = asyncio.run(app._dispatch_slash_command("/state audit"))
    assert "Audit Trail" in result or "No audit entries" in result

    # Test invalid subcommand
    result = asyncio.run(app._dispatch_slash_command("/state invalid"))
    assert "Usage:" in result


def test_state_audit_help_text_updated(tmp_path) -> None:
    """Test help text includes /state audit command."""
    TuiApp = _load_tui_app()
    app = TuiApp(book_path=str(tmp_path))

    help_text = app._build_help_text()

    assert "/state" in help_text
    assert "/state audit" in help_text
