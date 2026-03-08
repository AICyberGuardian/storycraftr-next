import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from click import ClickException
from click.testing import CliRunner

from storycraftr.cli import (
    cli,
    verify_book_path,
    is_initialized,
    project_not_initialized_error,
)
from storycraftr.cmd.story.book import BookEngineError, run_book_pipeline
from storycraftr.llm.factory import LLMConfigurationError
from storycraftr.llm.credentials import load_local_credentials


@pytest.fixture(autouse=True)
def reset_env():
    original = dict(os.environ)
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_API_KEY"):
        os.environ.pop(var, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


@pytest.fixture
def mock_console():
    with mock.patch("storycraftr.cli.console") as console:
        yield console


def test_verify_book_path_success(mock_console):
    with mock.patch(
        "os.path.exists",
        side_effect=lambda path: str(path).endswith("storycraftr.json"),
    ):
        assert verify_book_path("my_project") == "my_project"


def test_verify_book_path_success_with_papercraftr_config(mock_console):
    with mock.patch(
        "os.path.exists",
        side_effect=lambda path: str(path).endswith("papercraftr.json"),
    ):
        assert verify_book_path("my_project") == "my_project"


def test_verify_book_path_failure(mock_console):
    with mock.patch("os.path.exists", return_value=False):
        with pytest.raises(
            ClickException,
            match="Neither storycraftr.json nor papercraftr.json found in: missing_project",
        ):
            verify_book_path("missing_project")


def test_is_initialized_true(mock_console):
    with mock.patch(
        "os.path.exists",
        side_effect=lambda path: str(path).endswith("storycraftr.json"),
    ):
        assert is_initialized("my_project")


def test_is_initialized_true_with_papercraftr_config(mock_console):
    with mock.patch(
        "os.path.exists",
        side_effect=lambda path: str(path).endswith("papercraftr.json"),
    ):
        assert is_initialized("my_project")


def test_is_initialized_false(mock_console):
    with mock.patch("os.path.exists", return_value=False):
        assert not is_initialized("my_project")


def test_project_not_initialized_error(mock_console):
    project_not_initialized_error("demo")
    mock_console.print.assert_called_once()


def test_load_local_credentials(tmp_path):
    config_dir = tmp_path / ".storycraftr"
    config_dir.mkdir()
    key_file = config_dir / "openai_api_key.txt"
    key_file.write_text("placeholder-token", encoding="utf-8")

    with (
        mock.patch("storycraftr.llm.credentials.keyring", None),
        mock.patch("pathlib.Path.home", return_value=tmp_path),
    ):
        load_local_credentials()

    expected = "placeholder-token"  # nosec B105  # pragma: allowlist secret
    assert os.environ["OPENAI_API_KEY"] == expected


def test_chat_llm_model_override_is_passed_to_config_loader(tmp_path):
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    observed = {}

    def fake_load_book_config(book_path, model_override=None):
        observed["book_path"] = book_path
        observed["model_override"] = model_override
        return SimpleNamespace(
            book_name="Demo",
            primary_language="en",
            llm_provider="openrouter",
            llm_model=model_override or "openrouter/free",
            embed_model="BAAI/bge-large-en-v1.5",
        )

    fake_assistant = SimpleNamespace(last_documents=[])
    fake_thread = SimpleNamespace(id="thread-test")
    fake_job_manager = mock.Mock()
    fake_job_manager.job_stats.return_value = {
        "pending": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
    }

    with (
        mock.patch(
            "storycraftr.cmd.chat.load_book_config",
            side_effect=fake_load_book_config,
        ),
        mock.patch(
            "storycraftr.cmd.chat.create_vscode_event_emitter", return_value=None
        ),
        mock.patch(
            "storycraftr.cmd.chat.create_or_get_assistant", return_value=fake_assistant
        ) as mock_create_assistant,
        mock.patch("storycraftr.cmd.chat.get_thread", return_value=fake_thread),
        mock.patch(
            "storycraftr.cmd.chat.SubAgentJobManager", return_value=fake_job_manager
        ),
        mock.patch("storycraftr.cmd.chat.SessionManager"),
        mock.patch(
            "storycraftr.cmd.chat._run_turn",
            return_value={
                "user": "hello",
                "answer": "ok",
                "duration": 0.1,
                "documents": [],
            },
        ),
        mock.patch("storycraftr.cmd.chat.render_turn"),
        mock.patch("storycraftr.cmd.chat._drain_subagent_events"),
        mock.patch("storycraftr.cmd.chat._render_session_footer"),
    ):
        result = runner.invoke(
            cli,
            [
                "chat",
                "--book-path",
                str(project),
                "--prompt",
                "hello",
                "--llm-model",
                "custom/model",
            ],
        )

    assert result.exit_code == 0, result.output
    assert observed["book_path"] == str(project)
    assert observed["model_override"] == "custom/model"
    mock_create_assistant.assert_called_once_with(
        str(project), model_override="custom/model"
    )


def test_chat_prompt_emits_event_contract_payloads(tmp_path):
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    class _Emitter:
        def __init__(self):
            self.events = []

        def emit(self, event_type, payload):
            self.events.append((event_type, payload))

    emitter = _Emitter()
    fake_assistant = SimpleNamespace(last_documents=[])
    fake_thread = SimpleNamespace(id="thread-test")
    fake_job_manager = mock.Mock()
    fake_job_manager.job_stats.return_value = {
        "pending": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
    }

    with (
        mock.patch(
            "storycraftr.cmd.chat.load_book_config",
            return_value=SimpleNamespace(
                book_name="Demo",
                primary_language="en",
                llm_provider="openai",
                llm_model="gpt-4o",
                embed_model="BAAI/bge-large-en-v1.5",
            ),
        ),
        mock.patch(
            "storycraftr.cmd.chat.create_vscode_event_emitter", return_value=emitter
        ),
        mock.patch("storycraftr.cmd.chat.click.confirm", return_value=False),
        mock.patch(
            "storycraftr.cmd.chat.create_or_get_assistant", return_value=fake_assistant
        ),
        mock.patch("storycraftr.cmd.chat.get_thread", return_value=fake_thread),
        mock.patch(
            "storycraftr.cmd.chat.SubAgentJobManager", return_value=fake_job_manager
        ),
        mock.patch("storycraftr.cmd.chat.SessionManager"),
        mock.patch(
            "storycraftr.cmd.chat._run_turn",
            return_value={
                "user": "hello",
                "answer": "ok",
                "duration": 0.1,
                "documents": [],
            },
        ),
        mock.patch("storycraftr.cmd.chat.render_turn"),
        mock.patch("storycraftr.cmd.chat._drain_subagent_events"),
        mock.patch("storycraftr.cmd.chat._render_session_footer"),
    ):
        result = runner.invoke(
            cli,
            [
                "chat",
                "--book-path",
                str(project),
                "--prompt",
                "hello",
            ],
        )

    assert result.exit_code == 0, result.output
    event_names = [name for name, _payload in emitter.events]
    assert event_names == ["session.started", "chat.turn", "session.ended"]

    started_payload = emitter.events[0][1]
    assert set(["book_path", "metadata", "session"]).issubset(started_payload)

    turn_payload = emitter.events[1][1]
    assert set(["user", "answer", "documents", "duration"]).issubset(turn_payload)

    ended_payload = emitter.events[2][1]
    assert set(["book_path", "session"]).issubset(ended_payload)


def test_model_list_command_outputs_limits(monkeypatch) -> None:
    runner = CliRunner()

    model = SimpleNamespace(
        model_id="openrouter/free",
        context_length=32768,
        max_completion_tokens=4096,
    )
    monkeypatch.setattr(
        "storycraftr.cli.get_free_models", lambda force_refresh: [model]
    )

    result = runner.invoke(cli, ["model-list"], color=False)

    assert result.exit_code == 0, result.output
    clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "id | context_length | max_completion_tokens | free" in clean_output
    assert "openrouter/free | 32768 | 4096 | yes" in clean_output


def test_model_list_command_refresh_forces_fetch(monkeypatch) -> None:
    runner = CliRunner()
    observed: dict[str, bool] = {"refresh": False}

    def _fake_models(force_refresh: bool):
        observed["refresh"] = force_refresh
        return []

    monkeypatch.setattr("storycraftr.cli.get_free_models", _fake_models)

    result = runner.invoke(cli, ["model-list", "--refresh"])

    assert result.exit_code == 0, result.output
    assert observed["refresh"] is True


def test_mode_command_set_show_stop_round_trip(tmp_path) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    show_before = runner.invoke(cli, ["mode", "show", "--book-path", str(project)])
    assert show_before.exit_code == 0, show_before.output
    assert "mode: manual" in show_before.output

    set_mode = runner.invoke(
        cli,
        [
            "mode",
            "set",
            "autopilot",
            "--book-path",
            str(project),
            "--turns",
            "4",
        ],
    )
    assert set_mode.exit_code == 0, set_mode.output

    show_after_set = runner.invoke(cli, ["mode", "show", "--book-path", str(project)])
    assert show_after_set.exit_code == 0, show_after_set.output
    assert "mode: autopilot" in show_after_set.output
    assert "autopilot_turns_remaining: 4" in show_after_set.output

    stop_mode = runner.invoke(cli, ["mode", "stop", "--book-path", str(project)])
    assert stop_mode.exit_code == 0, stop_mode.output

    show_after_stop = runner.invoke(cli, ["mode", "show", "--book-path", str(project)])
    assert show_after_stop.exit_code == 0, show_after_stop.output
    assert "mode: manual" in show_after_stop.output
    assert "autopilot_turns_remaining: 0" in show_after_stop.output


def test_mode_set_command_uses_shared_service_impl(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    calls: dict[str, object] = {}

    class _FakeModeConfig:
        mode = SimpleNamespace(value="hybrid")

    class _FakeState:
        mode_config = _FakeModeConfig()
        autopilot_turns_remaining = 0

    def _fake_mode_set(book_path, mode_name, *, turns=None):
        calls["book_path"] = book_path
        calls["mode_name"] = mode_name
        calls["turns"] = turns
        return _FakeState()

    monkeypatch.setattr(
        "storycraftr.cmd.control_plane.mode_set_impl",
        _fake_mode_set,
    )

    result = runner.invoke(
        cli,
        ["mode", "set", "hybrid", "--book-path", str(project)],
    )

    assert result.exit_code == 0, result.output
    assert calls["mode_name"] == "hybrid"
    assert str(project) in str(calls["book_path"])


def test_models_group_list_outputs_rows(monkeypatch) -> None:
    runner = CliRunner()
    model = SimpleNamespace(
        model_id="openrouter/free",
        label="openrouter/free",
        context_length=16384,
        max_completion_tokens=1024,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.control_plane.get_free_models",
        lambda force_refresh: [model],
    )

    result = runner.invoke(cli, ["models", "list"])

    assert result.exit_code == 0, result.output
    assert "OpenRouter Free Models" in result.output
    assert "openrouter/free" in result.output


def test_models_validate_rankings_outputs_success(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(
        "storycraftr.cmd.control_plane.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "meta-llama/llama-3.3-70b-instruct:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "valid planner rationale",
            },
            "batch_prose": {
                "primary": "z-ai/glm-4.5-air:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "valid prose rationale",
            },
            "batch_editing": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["meta-llama/llama-3.3-70b-instruct:free"],
                "why": "valid editing rationale",
            },
            "repair_json": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "valid repair rationale",
            },
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["openai/gpt-oss-120b:free"],
                "context_limit": 256000,
                "why": "valid coherence rationale",
            },
        },
    )

    result = runner.invoke(cli, ["models", "validate-rankings"])

    assert result.exit_code == 0, result.output
    assert "Rankings configuration is valid." in result.output
    assert "batch_planning" in result.output


def test_models_validate_rankings_refresh_option(monkeypatch) -> None:
    runner = CliRunner()
    calls = {"refresh": 0}

    def _fake_refresh():
        calls["refresh"] += 1
        return []

    monkeypatch.setattr(
        "storycraftr.cmd.control_plane.refresh_free_models", _fake_refresh
    )
    monkeypatch.setattr(
        "storycraftr.cmd.control_plane.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "meta-llama/llama-3.3-70b-instruct:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "valid planner rationale",
            },
            "batch_prose": {
                "primary": "z-ai/glm-4.5-air:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "valid prose rationale",
            },
            "batch_editing": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["meta-llama/llama-3.3-70b-instruct:free"],
                "why": "valid editing rationale",
            },
            "repair_json": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "valid repair rationale",
            },
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["openai/gpt-oss-120b:free"],
                "context_limit": 256000,
                "why": "valid coherence rationale",
            },
        },
    )

    result = runner.invoke(
        cli,
        ["models", "validate-rankings", "--refresh", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert calls["refresh"] == 1
    assert '"batch_planning"' in result.output


def test_models_validate_rankings_fails_closed(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(
        "storycraftr.cmd.control_plane.validate_openrouter_rankings_config",
        lambda: (_ for _ in ()).throw(
            LLMConfigurationError("OpenRouter rankings config failed strict validation")
        ),
    )

    result = runner.invoke(cli, ["models", "validate-rankings"])

    assert result.exit_code != 0
    assert "strict validation" in result.output


def test_state_audit_json_output_reads_entries(tmp_path) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    outline = project / "outline"
    outline.mkdir(parents=True)

    audit_line = {
        "timestamp": "2026-03-07T12:34:56",
        "operation_type": "patch",
        "actor": "test-runner",
        "metadata": {},
        "patch": {"operations": [], "description": ""},
    }
    (outline / "narrative_audit.jsonl").write_text(
        f"{json.dumps(audit_line)}\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        cli,
        ["state", "audit", "--book-path", str(project), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert '"actor": "test-runner"' in result.output


def test_book_command_invokes_pipeline(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()
    seed_file = project / "seed.md"
    seed_file.write_text("# Seed\n\nA disciplined narrative seed.", encoding="utf-8")

    called: dict[str, object] = {}

    def _fake_run_book_pipeline(
        *,
        book_path: str,
        seed_text: str,
        chapters: int,
        auto_approve: bool,
    ):
        called["book_path"] = book_path
        called["seed_text"] = seed_text
        called["chapters"] = chapters
        called["auto_approve"] = auto_approve
        return SimpleNamespace(
            chapters_generated=chapters,
            patch_operations_applied=2,
            coherence_reviews_run=1,
        )

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _path: SimpleNamespace(book_name="Demo"),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.run_book_pipeline",
        _fake_run_book_pipeline,
    )

    result = runner.invoke(
        cli,
        [
            "book",
            "--book-path",
            str(project),
            "--seed",
            "seed.md",
            "--chapters",
            "3",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["chapters"] == 3
    assert called["auto_approve"] is True
    assert "Book generation run complete." in result.output


def test_book_command_fails_when_seed_file_missing(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _path: SimpleNamespace(book_name="Demo"),
    )

    result = runner.invoke(
        cli,
        [
            "book",
            "--book-path",
            str(project),
            "--seed",
            "missing-seed.md",
            "--chapters",
            "3",
            "--yes",
        ],
    )

    assert result.exit_code != 0
    assert "Seed file not found" in result.output


def test_run_book_pipeline_fails_closed_when_outline_rejected(monkeypatch) -> None:
    class _FakeLLM:
        def invoke(self, _prompt):
            return SimpleNamespace(content="- Outline bullet")

    fake_assistant = SimpleNamespace(llm=_FakeLLM())

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: fake_assistant,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_craft_rule_set",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(text="planner-rules"),
            drafter=SimpleNamespace(text="drafter-rules"),
            editor=SimpleNamespace(text="editor-rules"),
            stitcher=SimpleNamespace(text="stitcher-rules"),
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.click.confirm",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(BookEngineError, match="Outline rejected"):
        run_book_pipeline(
            book_path="/tmp/storycraftr-demo",  # nosec B108
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=False,
        )


def test_run_book_pipeline_fails_closed_when_state_commit_rejected(
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"o"}'
                )
            return SimpleNamespace(content="generated text")

    fake_assistant = SimpleNamespace(llm=_FakeLLM())

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: fake_assistant,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_craft_rule_set",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(text="planner-rules"),
            drafter=SimpleNamespace(text="drafter-rules"),
            editor=SimpleNamespace(text="editor-rules"),
            stitcher=SimpleNamespace(text="stitcher-rules"),
        ),
    )

    confirmations = iter([True, False])
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.click.confirm",
        lambda *_args, **_kwargs: next(confirmations),
    )

    with pytest.raises(BookEngineError, match="State commit rejected"):
        run_book_pipeline(
            book_path="/tmp/storycraftr-demo",  # nosec B108
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=False,
        )


def test_run_book_pipeline_persists_chapter_and_applies_patch(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"o"}'
                )
            return SimpleNamespace(content="generated text")

    fake_assistant = SimpleNamespace(llm=_FakeLLM())
    apply_calls: list[tuple[object, str]] = []

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            self.book_path = Path(_book_path)

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, patch, actor: str = "system"):
            apply_calls.append((patch, actor))
            outline = self.book_path / "outline"
            outline.mkdir(parents=True, exist_ok=True)
            (outline / "narrative_state.json").write_text(
                json.dumps({"plot_threads": [], "version": 2}, indent=2),
                encoding="utf-8",
            )
            return SimpleNamespace(plot_threads=[])

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: fake_assistant,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_craft_rule_set",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(text="planner-rules"),
            drafter=SimpleNamespace(text="drafter-rules"),
            editor=SimpleNamespace(text="editor-rules"),
            stitcher=SimpleNamespace(text="stitcher-rules"),
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeStateStore",
        _FakeStateStore,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    chapter_file = tmp_path / "chapters" / "chapter-1.md"
    narrative_state_file = tmp_path / "outline" / "narrative_state.json"
    canon_file = tmp_path / "outline" / "canon.yml"
    assert chapter_file.exists()
    assert "generated text" in chapter_file.read_text(encoding="utf-8")
    assert narrative_state_file.exists()
    assert canon_file.exists()
    assert "plot_threads:" in canon_file.read_text(encoding="utf-8")
    assert summary.chapters_generated == 1
    assert summary.patch_operations_applied == 1
    assert len(apply_calls) == 1
    assert apply_calls[0][1] == "book-engine"


def test_run_book_pipeline_does_not_persist_chapter_on_state_commit_failure(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"o"}'
                )
            return SimpleNamespace(content="generated text")

    class _FailingStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"
            raise RuntimeError("invalid patch")

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_FakeLLM()),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_craft_rule_set",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(text="planner-rules"),
            drafter=SimpleNamespace(text="drafter-rules"),
            editor=SimpleNamespace(text="editor-rules"),
            stitcher=SimpleNamespace(text="stitcher-rules"),
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeStateStore",
        _FailingStateStore,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )

    with pytest.raises(BookEngineError, match="State commit failed"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )

    chapter_file = tmp_path / "chapters" / "chapter-1.md"
    assert not chapter_file.exists()


def test_run_book_pipeline_fails_closed_when_canon_write_fails(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"o"}'
                )
            return SimpleNamespace(content="generated text")

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"
            return SimpleNamespace(plot_threads=[])

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_FakeLLM()),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_craft_rule_set",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(text="planner-rules"),
            drafter=SimpleNamespace(text="drafter-rules"),
            editor=SimpleNamespace(text="editor-rules"),
            stitcher=SimpleNamespace(text="stitcher-rules"),
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeStateStore",
        _FakeStateStore,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book._persist_canon_ledger",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("disk full")),
    )

    with pytest.raises(BookEngineError, match="State commit failed"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )

    chapter_file = tmp_path / "chapters" / "chapter-1.md"
    canon_file = tmp_path / "outline" / "canon.yml"
    assert not chapter_file.exists()
    assert not canon_file.exists()


def test_run_book_pipeline_pushes_flavor_memory_after_commit(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"o"}'
                )
            return SimpleNamespace(content="generated text")

    fake_assistant = SimpleNamespace(llm=_FakeLLM())
    add_calls: list[tuple[str, dict[str, object]]] = []

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"

    class _FakeMemoryManager:
        def __init__(self, *, book_path: str, config=None):
            self.book_path = book_path
            self.config = config

        def add_memory(self, *, text: str, metadata: dict[str, object] | None = None):
            add_calls.append((text, dict(metadata or {})))
            return True

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: fake_assistant,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_craft_rule_set",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(text="planner-rules"),
            drafter=SimpleNamespace(text="drafter-rules"),
            editor=SimpleNamespace(text="editor-rules"),
            stitcher=SimpleNamespace(text="stitcher-rules"),
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeStateStore",
        _FakeStateStore,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        _FakeMemoryManager,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(book_name="Demo"),
    )

    run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    assert len(add_calls) == 1
    assert "generated text" in add_calls[0][0]
    assert add_calls[0][1]["type"] == "flavor"
    assert add_calls[0][1]["chapter"] == 1


def test_run_book_pipeline_triggers_coherence_review_on_severe_violation(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(
                    content='{"violation": true, "reason": "dead character alive"}'
                )
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"o"}'
                )
            return SimpleNamespace(content="generated text")

    fake_assistant = SimpleNamespace(llm=_FakeLLM())

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: fake_assistant,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_craft_rule_set",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(text="planner-rules"),
            drafter=SimpleNamespace(text="drafter-rules"),
            editor=SimpleNamespace(text="editor-rules"),
            stitcher=SimpleNamespace(text="stitcher-rules"),
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeStateStore",
        _FakeStateStore,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    assert summary.chapters_generated == 1
    assert summary.coherence_reviews_run == 1


def test_book_command_returns_exit_code_1_on_pipeline_halt(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()
    seed_file = project / "seed.md"
    seed_file.write_text("# Seed\n\nContext", encoding="utf-8")

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _path: SimpleNamespace(book_name="Demo"),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.run_book_pipeline",
        lambda **_kwargs: (_ for _ in ()).throw(BookEngineError("Outline rejected")),
    )

    result = runner.invoke(
        cli,
        ["book", "--book-path", str(project), "--seed", "seed.md", "--yes"],
    )

    assert result.exit_code == 1
    assert "Pipeline Halted:" in result.output


def test_book_command_returns_exit_code_2_on_critical_failure(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()
    seed_file = project / "seed.md"
    seed_file.write_text("# Seed\n\nContext", encoding="utf-8")

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _path: SimpleNamespace(book_name="Demo"),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.run_book_pipeline",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = runner.invoke(
        cli,
        ["book", "--book-path", str(project), "--seed", "seed.md", "--yes"],
    )

    assert result.exit_code == 2
    assert "Critical System Failure:" in result.output


def test_state_extract_command_outputs_patch_summary(tmp_path) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    result = runner.invoke(
        cli,
        [
            "state",
            "extract",
            "--book-path",
            str(project),
            "--text",
            "Elias entered the bridge.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "State Extraction" in result.output
    assert "Operations:" in result.output


def test_memory_status_command_reports_runtime_details(monkeypatch, tmp_path) -> None:
    runner = CliRunner()

    class _FakeManager:
        def get_runtime_diagnostics(self):
            return {
                "enabled": True,
                "provider": "ollama",
                "story_id": "demo-story",
                "storage_path": str(tmp_path / ".storycraftr" / "memory"),
                "reason": None,
                "last_retrieval": {
                    "hits_returned": 2,
                    "queries_run": 3,
                    "queries_attempted": 5,
                    "hits_by_source": {"recent": 2},
                },
            }

    monkeypatch.setattr(
        "storycraftr.cmd.memory._build_manager",
        lambda _book_path: _FakeManager(),
    )

    result = runner.invoke(cli, ["memory", "status"])

    assert result.exit_code == 0, result.output
    assert "Memory Status" in result.output
    assert "Provider Mode: ollama" in result.output
    assert "Last Recall Hits: 2 (queries run: 3/5)" in result.output
    assert "Last Recall Sources: recent=2" in result.output


def test_memory_status_command_outputs_json(monkeypatch, tmp_path) -> None:
    runner = CliRunner()

    class _FakeManager:
        def get_runtime_diagnostics(self):
            return {
                "enabled": False,
                "provider": "openrouter",
                "story_id": "demo-story",
                "storage_path": str(tmp_path / ".storycraftr" / "memory"),
                "reason": "disabled by STORYCRAFTR_MEM0_ENABLED",
            }

    monkeypatch.setattr(
        "storycraftr.cmd.memory._build_manager",
        lambda _book_path: _FakeManager(),
    )

    result = runner.invoke(cli, ["memory", "status", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert '"enabled": false' in result.output.lower()
    assert '"provider": "openrouter"' in result.output


def test_memory_search_command_outputs_json(monkeypatch) -> None:
    runner = CliRunner()

    class _FakeManager:
        def search_memories(self, *, query, chapter, limit):
            assert query == "Where is Elias?"
            assert chapter == 3
            assert limit == 5
            return [{"memory": "Elias is on the bridge."}]

    monkeypatch.setattr(
        "storycraftr.cmd.memory._build_manager",
        lambda _book_path: _FakeManager(),
    )

    result = runner.invoke(
        cli,
        [
            "memory",
            "search",
            "--query",
            "Where is Elias?",
            "--chapter",
            "3",
            "--limit",
            "5",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Elias is on the bridge." in result.output


def test_memory_search_command_outputs_ndjson(monkeypatch) -> None:
    runner = CliRunner()

    class _FakeManager:
        def search_memories(self, *, query, chapter, limit):
            assert query == "What changed?"
            assert chapter is None
            assert limit == 2
            return [
                {"memory": "Elias moved to the bridge."},
                {"memory": "Mara hid the keycard."},
            ]

    monkeypatch.setattr(
        "storycraftr.cmd.memory._build_manager",
        lambda _book_path: _FakeManager(),
    )

    result = runner.invoke(
        cli,
        [
            "memory",
            "search",
            "--query",
            "What changed?",
            "--limit",
            "2",
            "--format",
            "ndjson",
        ],
    )

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines == [
        '{"memory":"Elias moved to the bridge."}',
        '{"memory":"Mara hid the keycard."}',
    ]
