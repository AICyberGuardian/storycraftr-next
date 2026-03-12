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
from storycraftr.agent.book_engine import ChapterRunArtifact, SceneRunArtifact
from storycraftr.agent.narrative_state import SceneDirective
from storycraftr.cmd.story.book import (
    BookEngineError,
    _VALIDATOR_REPORT_SCHEMA_PATH,
    _build_scene_acceptance_contract,
    _build_stage_validator_contract,
    _validate_validator_report_payload,
    run_book_pipeline,
)
from storycraftr.llm.factory import LLMConfigurationError
from storycraftr.llm.credentials import load_local_credentials

pytestmark = pytest.mark.integration


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
            retries=0,
            escalations=0,
            semantic_reviews_run=1,
            elapsed_seconds=1.0,
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


def test_run_book_pipeline_emits_progress_heartbeat_and_model_telemetry(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    class _FakeEvent:
        def __init__(self) -> None:
            self.calls = 0
            self._set = False

        def wait(self, _timeout: float | None = None) -> bool:
            if self._set:
                return True
            self.calls += 1
            return self.calls > 1

        def set(self) -> None:
            self._set = True

    class _FakeThread:
        def __init__(self, *, target, daemon: bool = True) -> None:
            self._target = target
            self.daemon = daemon

        def start(self) -> None:
            self._target()

        def join(self, timeout: float | None = None) -> None:
            _ = timeout

    class _RoleLLM:
        def __init__(self, model_name: str):
            self.model_name = model_name
            self.model_sequence = [model_name, "openrouter/free"]
            self.last_resolved_model_index = 1
            self.last_resolved_model = "openrouter/free"
            self.semantic_calls = 0

        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a global coherence audit over chapter progression." in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Generated Chapter:" in text and "Approved Scene Plan:" in text:
                self.semantic_calls += 1
                if self.semantic_calls < 3:
                    return SimpleNamespace(
                        content='{"status":"FAIL","reason":"policy_miss"}'
                    )
                return SimpleNamespace(content='{"status":"PASS"}')
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content=(
                        '{"goal":"goal ok","conflict":"conflict ok",'
                        '"stakes":"stakes ok","outcome":"decides outcome ok"}'
                    )
                )
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[{"id":"elias","name":"Elias"}],'
                        '"relationship_changes":[],"world_facts":[],"thread_changes":[]}'
                    )
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(3000))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.threading.Event",
        _FakeEvent,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.threading.Thread",
        _FakeThread,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_RoleLLM("assistant-model")),
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
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="arcee-ai/trinity-large-preview:free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "meta-llama/llama-3.3-70b-instruct:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "planner rationale",
            },
            "batch_prose": {
                "primary": "z-ai/glm-4.5-air:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "prose rationale",
            },
            "batch_editing": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["meta-llama/llama-3.3-70b-instruct:free"],
                "why": "editing rationale",
            },
            "repair_json": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "repair rationale",
            },
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["openai/gpt-oss-120b:free"],
                "why": "coherence rationale",
                "context_limit": 128000,
            },
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda settings: _RoleLLM(settings.model),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    output = capsys.readouterr().out
    assert "[Chapter 1] Outline generation started..." in output
    assert "[Chapter 1] Scene planning started..." in output
    assert "[Chapter 1] Drafting scene 1/3..." in output
    assert "[Chapter 1] Editing scene 1/3..." in output
    assert "[Chapter 1] Stitching started..." in output
    assert "[Chapter 1] Chapter validation started..." in output
    assert "[Chapter 1] Semantic review started..." in output
    assert "[Chapter 1] Coherence review started..." in output
    assert "[Chapter 1] State extraction started..." in output
    assert "[Chapter 1] Canon/state/chapter commit started..." in output
    assert "Waiting on OpenRouter response..." in output
    assert "Stage=draft role=batch_prose" in output
    assert "configured=arcee-ai/trinity-large-preview:free" in output
    assert "source=openrouter_free_router" in output
    assert "Chapter validation retry" in output
    assert "Escalating " in output
    assert "Escalating batch_prose model" in output
    assert "Run summary:" in output
    assert "final_status=succeeded" in output
    assert summary.retries >= 2
    assert summary.escalations >= 1
    assert summary.semantic_reviews_run >= 1


def test_run_book_pipeline_repairs_scene_plan_after_repeated_structure_drift(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    class _FakeEvent:
        def wait(self, _timeout: float | None = None) -> bool:
            return True

        def set(self) -> None:
            return None

    class _FakeThread:
        def __init__(self, *, target, daemon: bool = True) -> None:
            self._target = target
            self.daemon = daemon

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            _ = timeout

    def _scene_text(outcome: str, label: str) -> str:
        core = (
            "Lyra seeks proof of the hidden rebellion. "
            "City guards crowd the alley and block her contact. "
            "She acts because capture would mean execution as a rebel courier. "
            f"{outcome}. "
        )
        filler = " ".join(f"{label}{idx}" for idx in range(260))
        return core + filler + "."

    state = {
        "scene_one_edit_calls": 0,
        "planner_repair_calls": 0,
    }

    original_outcome = "Lyra discovers the coded message and decides to find the scribe"
    repaired_outcome = "Lyra reveals the coded message and chooses the eastern tunnels"

    class _RoleLLM:
        def __init__(self, model_name: str):
            self.model_name = model_name
            self.model_sequence = [model_name]
            self.last_resolved_model_index = 0
            self.last_resolved_model = model_name

        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a global coherence audit over chapter progression." in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Generated Chapter:" in text and "Approved Scene Plan:" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[{"id":"lyra","name":"Lyra",'
                        '"location":"east tunnels"}],'
                        '"relationship_changes":[],"world_facts":[],'
                        '"thread_changes":[{"id":"rebellion","action":"advance",'
                        '"description":"Lyra commits to the tunnel lead"}]}'
                    )
                )
            if "Create a concise rolling outline for the next chapter." in text:
                return SimpleNamespace(
                    content="- Lyra hunts for proof in the curfewed city."
                )
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                scene_match = re.search(r"Chapter 1, scene (\d) of 3", text)
                scene_number = int(scene_match.group(1)) if scene_match else 1
                if "Previous scene drift feedback:" in text:
                    state["planner_repair_calls"] += 1
                    return SimpleNamespace(
                        content=(
                            '{"goal":"Lyra seeks proof of the hidden rebellion",'
                            '"conflict":"City guards crowd the alley and block her contact",'
                            '"stakes":"If caught Lyra will be executed as a rebel courier",'
                            f'"outcome":"{repaired_outcome}"'
                            "}"
                        )
                    )
                outcome = original_outcome
                if scene_number == 2:
                    outcome = "Lyra bribes the watch clerk and decides to trust Mara"
                if scene_number == 3:
                    outcome = "Lyra escapes the raid and changes the rebel timetable"
                return SimpleNamespace(
                    content=(
                        '{"goal":"Lyra seeks proof of the hidden rebellion",'
                        '"conflict":"City guards crowd the alley and block her contact",'
                        '"stakes":"If caught Lyra will be executed as a rebel courier",'
                        f'"outcome":"{outcome}"'
                        "}"
                    )
                )
            if "Retry draft for chapter 1 scene 1" in text:
                if repaired_outcome in text:
                    return SimpleNamespace(
                        content=_scene_text(repaired_outcome, "repair")
                    )
                return SimpleNamespace(content=_scene_text(original_outcome, "retry"))
            if "Chapter 1 scene 1." in text and "Write 800-1200 words" in text:
                return SimpleNamespace(content=_scene_text(original_outcome, "draft"))
            if "Revise chapter 1 scene 1 for craft and canon." in text:
                state["scene_one_edit_calls"] += 1
                if state["scene_one_edit_calls"] < 3:
                    return SimpleNamespace(
                        content=(
                            "Lyra moved through the alley under heavy guard pressure, "
                            "but the scene ended on a substitute beat that never landed "
                            "the planned turn. "
                            + " ".join(f"drift{idx}" for idx in range(260))
                            + "."
                        )
                    )
                if repaired_outcome in text:
                    return SimpleNamespace(
                        content=_scene_text(repaired_outcome, "edit")
                    )
                return SimpleNamespace(content=_scene_text(original_outcome, "edit"))
            if "Revise chapter 1 scene 2 for craft and canon." in text:
                return SimpleNamespace(
                    content=_scene_text(
                        "Lyra bribes the watch clerk and decides to trust Mara",
                        "scene2",
                    )
                )
            if "Revise chapter 1 scene 3 for craft and canon." in text:
                return SimpleNamespace(
                    content=_scene_text(
                        "Lyra escapes the raid and changes the rebel timetable",
                        "scene3",
                    )
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(2600))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.threading.Event",
        _FakeEvent,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.threading.Thread",
        _FakeThread,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_RoleLLM("assistant-model")),
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
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="arcee-ai/trinity-large-preview:free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "meta-llama/llama-3.3-70b-instruct:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "planner rationale",
            },
            "batch_prose": {
                "primary": "z-ai/glm-4.5-air:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "prose rationale",
            },
            "batch_editing": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["meta-llama/llama-3.3-70b-instruct:free"],
                "why": "editing rationale",
            },
            "repair_json": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "repair rationale",
            },
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["openai/gpt-oss-120b:free"],
                "why": "coherence rationale",
                "context_limit": 128000,
            },
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda settings: _RoleLLM(settings.model),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    output = capsys.readouterr().out
    assert summary.final_status == "succeeded"
    assert state["planner_repair_calls"] == 1
    assert "Repairing scene 1 plan after structure drift..." in output
    assert "Escalating batch_planning model" in output


def test_run_book_pipeline_scene_plan_repair_retries_with_python_error_feedback(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    class _FakeEvent:
        def wait(self, _timeout: float | None = None) -> bool:
            return True

        def set(self) -> None:
            return None

    class _FakeThread:
        def __init__(self, *, target, daemon: bool = True) -> None:
            self._target = target
            self.daemon = daemon

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            _ = timeout

    def _scene_text(outcome: str, label: str) -> str:
        core = (
            "Lyra seeks proof of the hidden rebellion. "
            "City guards crowd the alley and block her contact. "
            "She acts because capture would mean execution as a rebel courier. "
            f"{outcome}. "
        )
        filler = " ".join(f"{label}{idx}" for idx in range(260))
        return core + filler + "."

    state = {
        "scene_one_edit_calls": 0,
        "planner_repair_calls": 0,
        "repair_prompts": [],
    }

    original_outcome = "Lyra discovers the coded message and decides to find the scribe"
    invalid_repair_outcome = "Lyra reaches the tunnel before dawn"
    repaired_outcome = "Lyra reveals the coded message and chooses the eastern tunnels"

    class _RoleLLM:
        def __init__(self, model_name: str):
            self.model_name = model_name
            self.model_sequence = [model_name]
            self.last_resolved_model_index = 0
            self.last_resolved_model = model_name

        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a global coherence audit over chapter progression." in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Generated Chapter:" in text and "Approved Scene Plan:" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[{"id":"lyra","name":"Lyra",'
                        '"location":"east tunnels"}],'
                        '"relationship_changes":[],"world_facts":[],'
                        '"thread_changes":[{"id":"rebellion","action":"advance",'
                        '"description":"Lyra commits to the tunnel lead"}]}'
                    )
                )
            if "Create a concise rolling outline for the next chapter." in text:
                return SimpleNamespace(
                    content="- Lyra hunts for proof in the curfewed city."
                )
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                scene_match = re.search(r"Chapter 1, scene (\d) of 3", text)
                scene_number = int(scene_match.group(1)) if scene_match else 1
                if "Previous scene drift feedback:" in text and scene_number == 1:
                    state["planner_repair_calls"] += 1
                    state["repair_prompts"].append(text)
                    if state["planner_repair_calls"] == 1:
                        return SimpleNamespace(
                            content=(
                                '{"goal":"Lyra seeks proof of the hidden rebellion",'
                                '"conflict":"City guards crowd the alley and block her contact",'
                                '"stakes":"If caught Lyra will be executed as a rebel courier",'
                                f'"outcome":"{invalid_repair_outcome}"'
                                "}"
                            )
                        )
                    return SimpleNamespace(
                        content=(
                            '{"goal":"Lyra seeks proof of the hidden rebellion",'
                            '"conflict":"City guards crowd the alley and block her contact",'
                            '"stakes":"If caught Lyra will be executed as a rebel courier",'
                            f'"outcome":"{repaired_outcome}"'
                            "}"
                        )
                    )

                outcome = original_outcome
                if scene_number == 2:
                    outcome = "Lyra bribes the watch clerk and decides to trust Mara"
                if scene_number == 3:
                    outcome = "Lyra escapes the raid and changes the rebel timetable"
                return SimpleNamespace(
                    content=(
                        '{"goal":"Lyra seeks proof of the hidden rebellion",'
                        '"conflict":"City guards crowd the alley and block her contact",'
                        '"stakes":"If caught Lyra will be executed as a rebel courier",'
                        f'"outcome":"{outcome}"'
                        "}"
                    )
                )
            if "Retry draft for chapter 1 scene 1" in text:
                if repaired_outcome in text:
                    return SimpleNamespace(
                        content=_scene_text(repaired_outcome, "repair")
                    )
                return SimpleNamespace(content=_scene_text(original_outcome, "retry"))
            if "Chapter 1 scene 1." in text and "Write 800-1200 words" in text:
                return SimpleNamespace(content=_scene_text(original_outcome, "draft"))
            if "Revise chapter 1 scene 1 for craft and canon." in text:
                state["scene_one_edit_calls"] += 1
                if state["scene_one_edit_calls"] < 3:
                    return SimpleNamespace(
                        content=(
                            "Lyra moved through the alley under heavy guard pressure, "
                            "but the scene ended on a substitute beat that never landed "
                            "the planned turn. "
                            + " ".join(f"drift{idx}" for idx in range(260))
                            + "."
                        )
                    )
                if repaired_outcome in text:
                    return SimpleNamespace(
                        content=_scene_text(repaired_outcome, "edit")
                    )
                return SimpleNamespace(content=_scene_text(original_outcome, "edit"))
            if "Revise chapter 1 scene 2 for craft and canon." in text:
                return SimpleNamespace(
                    content=_scene_text(
                        "Lyra bribes the watch clerk and decides to trust Mara",
                        "scene2",
                    )
                )
            if "Revise chapter 1 scene 3 for craft and canon." in text:
                return SimpleNamespace(
                    content=_scene_text(
                        "Lyra escapes the raid and changes the rebel timetable",
                        "scene3",
                    )
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(2600))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    monkeypatch.setattr("storycraftr.cmd.story.book.threading.Event", _FakeEvent)
    monkeypatch.setattr("storycraftr.cmd.story.book.threading.Thread", _FakeThread)
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_RoleLLM("assistant-model")),
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
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="arcee-ai/trinity-large-preview:free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "meta-llama/llama-3.3-70b-instruct:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "planner rationale",
            },
            "batch_prose": {
                "primary": "z-ai/glm-4.5-air:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "prose rationale",
            },
            "batch_editing": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["meta-llama/llama-3.3-70b-instruct:free"],
                "why": "editing rationale",
            },
            "repair_json": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "repair rationale",
            },
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["openai/gpt-oss-120b:free"],
                "why": "coherence rationale",
                "context_limit": 128000,
            },
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda settings: _RoleLLM(settings.model),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    output = capsys.readouterr().out
    assert summary.final_status == "succeeded"
    assert state["planner_repair_calls"] == 2
    assert "Repairing scene 1 plan after structure drift..." in output
    assert any(
        "CRITICAL CORRECTION (Attempt 2): Your previous repaired scene directive was rejected."
        in prompt
        for prompt in state["repair_prompts"]
    )
    assert any(
        "Exact validation error: Scene planning outcome must include a decision-beat movement marker"
        in prompt
        for prompt in state["repair_prompts"]
    )


def test_run_book_pipeline_scene_plan_repair_fails_closed_after_three_attempts(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeEvent:
        def wait(self, _timeout: float | None = None) -> bool:
            return True

        def set(self) -> None:
            return None

    class _FakeThread:
        def __init__(self, *, target, daemon: bool = True) -> None:
            self._target = target
            self.daemon = daemon

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            _ = timeout

    def _scene_text(outcome: str, label: str) -> str:
        core = (
            "Lyra seeks proof of the hidden rebellion. "
            "City guards crowd the alley and block her contact. "
            "She acts because capture would mean execution as a rebel courier. "
            f"{outcome}. "
        )
        filler = " ".join(f"{label}{idx}" for idx in range(260))
        return core + filler + "."

    state = {
        "scene_one_edit_calls": 0,
        "planner_repair_calls": 0,
        "repair_prompts": [],
    }

    original_outcome = "Lyra discovers the coded message and decides to find the scribe"
    invalid_repair_outcome = "Lyra reaches the tunnel before dawn"

    class _RoleLLM:
        def __init__(self, model_name: str):
            self.model_name = model_name
            self.model_sequence = [model_name]
            self.last_resolved_model_index = 0
            self.last_resolved_model = model_name

        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a global coherence audit over chapter progression." in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Generated Chapter:" in text and "Approved Scene Plan:" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[{"id":"lyra","name":"Lyra",'
                        '"location":"east tunnels"}],'
                        '"relationship_changes":[],"world_facts":[],'
                        '"thread_changes":[{"id":"rebellion","action":"advance",'
                        '"description":"Lyra commits to the tunnel lead"}]}'
                    )
                )
            if "Create a concise rolling outline for the next chapter." in text:
                return SimpleNamespace(
                    content="- Lyra hunts for proof in the curfewed city."
                )
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                scene_match = re.search(r"Chapter 1, scene (\d) of 3", text)
                scene_number = int(scene_match.group(1)) if scene_match else 1
                if "Previous scene drift feedback:" in text and scene_number == 1:
                    state["planner_repair_calls"] += 1
                    state["repair_prompts"].append(text)
                    return SimpleNamespace(
                        content=(
                            '{"goal":"Lyra seeks proof of the hidden rebellion",'
                            '"conflict":"City guards crowd the alley and block her contact",'
                            '"stakes":"If caught Lyra will be executed as a rebel courier",'
                            f'"outcome":"{invalid_repair_outcome}"'
                            "}"
                        )
                    )

                outcome = original_outcome
                if scene_number == 2:
                    outcome = "Lyra bribes the watch clerk and decides to trust Mara"
                if scene_number == 3:
                    outcome = "Lyra escapes the raid and changes the rebel timetable"
                return SimpleNamespace(
                    content=(
                        '{"goal":"Lyra seeks proof of the hidden rebellion",'
                        '"conflict":"City guards crowd the alley and block her contact",'
                        '"stakes":"If caught Lyra will be executed as a rebel courier",'
                        f'"outcome":"{outcome}"'
                        "}"
                    )
                )
            if "Retry draft for chapter 1 scene 1" in text:
                return SimpleNamespace(content=_scene_text(original_outcome, "retry"))
            if "Chapter 1 scene 1." in text and "Write 800-1200 words" in text:
                return SimpleNamespace(content=_scene_text(original_outcome, "draft"))
            if "Revise chapter 1 scene 1 for craft and canon." in text:
                state["scene_one_edit_calls"] += 1
                if state["scene_one_edit_calls"] < 3:
                    return SimpleNamespace(
                        content=(
                            "Lyra moved through the alley under heavy guard pressure, "
                            "but the scene ended on a substitute beat that never landed "
                            "the planned turn. "
                            + " ".join(f"drift{idx}" for idx in range(260))
                            + "."
                        )
                    )
                return SimpleNamespace(content=_scene_text(original_outcome, "edit"))
            if "Revise chapter 1 scene 2 for craft and canon." in text:
                return SimpleNamespace(
                    content=_scene_text(
                        "Lyra bribes the watch clerk and decides to trust Mara",
                        "scene2",
                    )
                )
            if "Revise chapter 1 scene 3 for craft and canon." in text:
                return SimpleNamespace(
                    content=_scene_text(
                        "Lyra escapes the raid and changes the rebel timetable",
                        "scene3",
                    )
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(2600))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    monkeypatch.setattr("storycraftr.cmd.story.book.threading.Event", _FakeEvent)
    monkeypatch.setattr("storycraftr.cmd.story.book.threading.Thread", _FakeThread)
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_RoleLLM("assistant-model")),
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
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="arcee-ai/trinity-large-preview:free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "meta-llama/llama-3.3-70b-instruct:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "planner rationale",
            },
            "batch_prose": {
                "primary": "z-ai/glm-4.5-air:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "prose rationale",
            },
            "batch_editing": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["meta-llama/llama-3.3-70b-instruct:free"],
                "why": "editing rationale",
            },
            "repair_json": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "repair rationale",
            },
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["openai/gpt-oss-120b:free"],
                "why": "coherence rationale",
                "context_limit": 128000,
            },
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda settings: _RoleLLM(settings.model),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )

    with pytest.raises(
        BookEngineError,
        match="Scene plan repair exhausted deterministic retries for scene 1",
    ):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )

    assert state["planner_repair_calls"] == 3
    assert any(
        "CRITICAL CORRECTION (Attempt 3): Your previous repaired scene directive was rejected."
        in prompt
        for prompt in state["repair_prompts"]
    )


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
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
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
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
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
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
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
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"decides o"}'
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
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
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
    packet_dir = tmp_path / "outline" / "chapter_packets" / "chapter-001"
    audit_json = tmp_path / "outline" / "book_audit.json"
    audit_md = tmp_path / "outline" / "book_audit.md"
    assert chapter_file.exists()
    assert "generated text" in chapter_file.read_text(encoding="utf-8")
    assert narrative_state_file.exists()
    assert canon_file.exists()
    assert "plot_threads:" in canon_file.read_text(encoding="utf-8")
    assert packet_dir.exists()
    assert (packet_dir / "outline_context.md").exists()
    assert (packet_dir / "scene_plan.json").exists()
    assert (packet_dir / "scene_1_validator_report.json").exists()
    assert (packet_dir / "scene_2_validator_report.json").exists()
    assert (packet_dir / "scene_3_validator_report.json").exists()
    assert (packet_dir / "stitched_chapter.md").exists()
    assert (packet_dir / "state_patch.json").exists()
    assert (packet_dir / "diagnostics.json").exists()
    assert (packet_dir / "validator_report.json").exists()
    report = json.loads(
        (packet_dir / "validator_report.json").read_text(encoding="utf-8")
    )
    assert report["phase"] == "postcommit"
    assert report["precommit"]["phase"] == "precommit"
    assert report["precommit"]["stage_contract"]["all_passed"] is True
    assert (
        report["precommit"]["stage_contract"]["stages"]["scene_plan"]["all_passed"]
        is True
    )
    assert (
        report["precommit"]["stage_contract"]["stages"]["scene_edit"]["all_passed"]
        is True
    )
    assert (
        report["precommit"]["stage_contract"]["stages"]["stitch"]["all_passed"] is True
    )
    assert report["commit_status"]["all_persisted"] is True
    assert audit_json.exists()
    assert audit_md.exists()
    audit_payload = json.loads(audit_json.read_text(encoding="utf-8"))
    assert audit_payload["status"] == "succeeded"
    assert audit_payload["chapters_generated"] == 1
    assert len(audit_payload["chapters"]) == 1
    assert summary.chapters_generated == 1
    assert summary.patch_operations_applied == 1
    assert len(apply_calls) == 1
    assert apply_calls[0][1] == "book-engine"


def test_build_scene_acceptance_contract_flags_invalid_scene() -> None:
    scene_ok = SceneRunArtifact(
        scene_number=1,
        directive=SceneDirective(
            goal="Clear goal",
            conflict="Clear conflict",
            stakes="Clear stakes",
            outcome="Clear outcome",
        ),
        draft_text="draft words here",
        edited_text="edited words here",
    )
    scene_bad = SceneRunArtifact(
        scene_number=2,
        directive=SceneDirective(
            goal="Clear goal",
            conflict="Clear conflict",
            stakes="Clear stakes",
            outcome="Clear outcome",
        ),
        draft_text="draft words here",
        edited_text="",
    )
    chapter = ChapterRunArtifact(
        chapter_number=1,
        outline_text="outline",
        scene_artifacts=(scene_ok, scene_bad),
        stitched_text="stitched",
        state_update={"patch": SimpleNamespace(operations=[{"operation": "add"}])},
    )

    report = _build_scene_acceptance_contract(chapter=chapter, min_scene_words=0)

    assert report["all_passed"] is False
    assert report["failed_scenes"] == [2]
    assert report["scenes"][1]["checks"]["edit_non_empty"] is False


def test_build_stage_validator_contract_flags_scene_edit_stage_failure() -> None:
    scene_bad = SceneRunArtifact(
        scene_number=1,
        directive=SceneDirective(
            goal="Clear goal",
            conflict="Clear conflict",
            stakes="Clear stakes",
            outcome="Clear outcome",
        ),
        draft_text="sufficient draft",
        edited_text="",
    )
    chapter = ChapterRunArtifact(
        chapter_number=1,
        outline_text="outline ok",
        scene_artifacts=(scene_bad,),
        stitched_text="stitched output",
        state_update={"patch": SimpleNamespace(operations=[{"operation": "add"}])},
    )
    diagnostics = {
        "state_signal_enforced": False,
        "state_signal_meaningful": True,
        "semantic_review_enabled": False,
        "semantic_review_passed": None,
    }
    scene_acceptance = _build_scene_acceptance_contract(
        chapter=chapter, min_scene_words=0
    )

    report = _build_stage_validator_contract(
        chapter=chapter,
        diagnostics=diagnostics,
        patch_operation_count=1,
        min_scene_words=0,
        min_chapter_words=0,
        scene_acceptance=scene_acceptance,
    )

    assert report["all_passed"] is False
    assert report["stages"]["scene_edit"]["all_passed"] is False


def test_validator_report_schema_file_exists_and_has_defs() -> None:
    raw = _VALIDATOR_REPORT_SCHEMA_PATH.read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert payload["$schema"].endswith("draft/2020-12/schema")
    assert "$defs" in payload
    assert "precommitReport" in payload["$defs"]
    assert "postcommitReport" in payload["$defs"]


def test_validate_validator_report_payload_fails_closed_on_missing_required_key() -> (
    None
):
    invalid_precommit = {
        "phase": "precommit",
        "chapter": 1,
        "acceptance": {},
        "scene_acceptance": {},
    }

    with pytest.raises(BookEngineError, match="schema validation failed"):
        _validate_validator_report_payload(invalid_precommit)


def test_validate_validator_report_payload_fails_closed_on_schema_type_mismatch() -> (
    None
):
    invalid_postcommit = {
        "phase": "postcommit",
        "chapter": 1,
        "precommit": {
            "phase": "precommit",
            "chapter": 1,
            "acceptance": {},
            "scene_acceptance": {},
            "stage_contract": {},
        },
        "commit_status": {
            "chapter_file_written": "yes",
            "state_file_written": True,
            "canon_file_written": True,
            "all_persisted": True,
        },
    }

    with pytest.raises(BookEngineError, match="schema validation failed"):
        _validate_validator_report_payload(invalid_postcommit)


def test_run_book_pipeline_does_not_persist_chapter_on_state_commit_failure(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"decides o"}'
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
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
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


def test_run_book_pipeline_fails_closed_on_empty_state_patch_contract(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(3000))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"

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
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="openrouter/free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": [],
                "why": "test",
                "context_limit": 256000,
            }
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda _settings: SimpleNamespace(
            invoke=lambda _prompt: SimpleNamespace(content='{"status":"PASS"}')
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[]),
            events=[],
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.click.confirm", lambda *_, **__: True
    )

    with pytest.raises(BookEngineError, match="no meaningful update"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )

    chapter_file = tmp_path / "chapters" / "chapter-1.md"
    assert not chapter_file.exists()


def test_run_book_pipeline_fails_closed_on_empty_state_patch_without_auto_approve(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[],"relationship_changes":[],"world_facts":[],"thread_changes":[]}'
                    )
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(3000))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"

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
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="openrouter/free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": [],
                "why": "test",
                "context_limit": 256000,
            }
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda _settings: SimpleNamespace(
            invoke=lambda _prompt: SimpleNamespace(content='{"status":"PASS"}')
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[]),
            events=[],
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.click.confirm", lambda *_, **__: True
    )

    with pytest.raises(BookEngineError, match="no meaningful update"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=False,
        )


def test_run_book_pipeline_fails_closed_when_canon_write_fails(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Return ONLY valid JSON" in text or "Repair the following text" in text:
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"decides o"}'
                )
            return SimpleNamespace(content="generated text")

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            self.path = Path(_book_path) / "outline" / "narrative_state.json"

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text('{"version":999}', encoding="utf-8")

    class _FakeMemoryManager:
        def __init__(self, *, book_path: str, config=None):
            self.book_path = book_path
            self.config = config

        def add_memory(self, *, text: str, metadata: dict[str, object] | None = None):
            return True

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
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        _FakeMemoryManager,
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book._persist_canon_ledger",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("disk full")),
    )

    state_file = tmp_path / "outline" / "narrative_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    baseline_state = '{"version":1}'
    state_file.write_text(baseline_state, encoding="utf-8")

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
    assert state_file.read_text(encoding="utf-8") == baseline_state


def test_run_book_pipeline_rolls_back_partial_writes_on_canon_failure_atomic_commit(
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
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[{"id":"elias","name":"Elias"}],'
                        '"relationship_changes":[],"world_facts":[],"thread_changes":[]}'
                    )
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(3000))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    class _FakeStateStore:
        def __init__(self, book_path: str):
            self.path = Path(book_path) / "outline" / "narrative_state.json"

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text('{"version":999}', encoding="utf-8")
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
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book._persist_canon_ledger",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("disk full")),
    )

    state_file = tmp_path / "outline" / "narrative_state.json"
    canon_file = tmp_path / "outline" / "canon.yml"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    baseline_state = '{"version":1}'
    baseline_canon = "chapters: {}\n"
    state_file.write_text(baseline_state, encoding="utf-8")
    canon_file.write_text(baseline_canon, encoding="utf-8")

    with pytest.raises(BookEngineError, match="State commit failed"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )

    chapter_file = tmp_path / "chapters" / "chapter-1.md"
    assert state_file.read_text(encoding="utf-8") == baseline_state
    assert canon_file.read_text(encoding="utf-8") == baseline_canon
    assert not chapter_file.exists()


def test_run_book_pipeline_rich_extraction_captures_narrative_facts(
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
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[{"id":"elias","name":"Elias","location":"city_gate","status":"alive"}],'
                        '"relationship_changes":[{"character_id":"elias","details":"trusts mara after the duel"}],'
                        '"world_facts":[{"location_id":"city_gate","location_name":"City Gate","description":"The gate is sealed at dusk."}],'
                        '"thread_changes":[{"id":"gate_mystery","action":"open","description":"Who sealed the gate?"}]}'
                    )
                )
            return SimpleNamespace(
                content=" ".join(f"chapterword{idx}" for idx in range(900))
            )

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
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    assert summary.chapters_generated == 1
    state_file = tmp_path / "outline" / "narrative_state.json"
    payload = json.loads(state_file.read_text(encoding="utf-8"))

    assert "elias" in payload["characters"]
    assert payload["characters"]["elias"]["location"] is None
    assert "trusts mara" in payload["characters"]["elias"]["notes"]
    assert "city_gate" in payload["locations"]
    assert "sealed at dusk" in payload["locations"]["city_gate"]["description"]
    assert payload["plot_threads"][0]["id"] == "gate_mystery"
    assert payload["plot_threads"][0]["status"] == "OPEN"


def test_run_book_pipeline_full_global_coherence_halts_on_parse_error(
    tmp_path,
    monkeypatch,
) -> None:
    coherence_prompts: list[str] = []

    class _AssistantLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(3000))
                )
            return SimpleNamespace(
                content=" ".join(f"chapterword{idx}" for idx in range(900))
            )

    class _RoleLLM:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def invoke(self, prompt):
            text = str(prompt)
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content=(
                        '{"character_deltas":[{"id":"elias","name":"Elias"}],'
                        '"relationship_changes":[],"world_facts":[],"thread_changes":[]}'
                    )
                )
            if "Generated Chapter:" in text and "Chapter:" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Run a global coherence audit over chapter progression." in text:
                coherence_prompts.append(text)
                return SimpleNamespace(content="not-json")
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitchedchapterword{idx}" for idx in range(3000))
                )
            return SimpleNamespace(
                content=" ".join(f"chapterword{idx}" for idx in range(900))
            )

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_AssistantLLM()),
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
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="openrouter/free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "planner-model",
                "fallbacks": [],
            },
            "batch_prose": {
                "primary": "prose-model",
                "fallbacks": [],
            },
            "batch_editing": {
                "primary": "edit-model",
                "fallbacks": [],
            },
            "repair_json": {
                "primary": "repair-model",
                "fallbacks": [],
            },
            "coherence_check": {
                "primary": "coherence-model",
                "fallbacks": [],
                "context_limit": 128000,
            },
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda settings: _RoleLLM(settings.model),
    )

    with pytest.raises(
        BookEngineError,
        match="Coherence gate (failed|rejected)",
    ):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=2,
            auto_approve=True,
        )

    assert coherence_prompts
    prompt = coherence_prompts[-1]
    assert "All chapter history (full text in order):" in prompt
    assert "Canon Facts JSON:" in prompt
    assert "Seed:" in prompt
    assert "chapterword" in prompt


def test_run_book_pipeline_pushes_flavor_memory_after_commit(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"decides o"}'
                )
            return SimpleNamespace(content="generated text")

    fake_assistant = SimpleNamespace(llm=_FakeLLM())
    add_calls: list[tuple[str, dict[str, object]]] = []

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(
                characters={},
                locations={},
                plot_threads=[
                    SimpleNamespace(
                        id="thread-a",
                        status="open",
                        introduced_chapter=1,
                        resolved_chapter=None,
                    )
                ],
            )

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
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
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
            if "Run a coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"decides o"}'
                )
            return SimpleNamespace(content="generated text")

    fake_assistant = SimpleNamespace(llm=_FakeLLM())

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(
                characters={},
                locations={},
                plot_threads=[
                    SimpleNamespace(
                        id="thread-a",
                        status="open",
                        introduced_chapter=1,
                        resolved_chapter=None,
                    )
                ],
            )

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
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
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


def test_run_book_pipeline_fails_closed_when_coherence_gate_rejects(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": true}')
            if "Run a coherence audit" in text:
                return SimpleNamespace(
                    content='{"status":"FAIL","reason":"timeline break"}'
                )
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"g","conflict":"c","stakes":"s","outcome":"decides o"}'
                )
            return SimpleNamespace(content="generated text")

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(
                characters={},
                locations={},
                plot_threads=[
                    SimpleNamespace(
                        id="thread-a",
                        status="open",
                        introduced_chapter=1,
                        resolved_chapter=None,
                    )
                ],
            )

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"

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
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )

    with pytest.raises(
        BookEngineError,
        match="Coherence gate (failed|rejected)",
    ):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )


def test_run_book_pipeline_semantic_review_uses_coherence_rankings(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(content=_long_text("stitched", 3000))
            return SimpleNamespace(content=_long_text("generated", 820))

    class _FakeReviewerLLM:
        def __init__(self):
            self.calls = 0

        def invoke(self, _prompt):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content='{"status":"FAIL","reason":"canon drift"}'
                )
            return SimpleNamespace(content='{"status":"PASS"}')

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"

    def _long_text(label: str, words: int) -> str:
        return " ".join(f"{label}{idx}" for idx in range(words))

    fake_reviewer = _FakeReviewerLLM()
    seen_models: list[str] = []

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
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="openrouter/free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["openai/gpt-oss-120b:free"],
                "why": "test",
                "context_limit": 256000,
            }
        },
    )

    def _fake_build_chat_model(settings):
        seen_models.append(settings.model)
        return fake_reviewer

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        _fake_build_chat_model,
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    assert summary.chapters_generated == 1
    assert seen_models[0] == "stepfun/step-3.5-flash:free"
    assert "openai/gpt-oss-120b:free" in seen_models
    assert fake_reviewer.calls == 3
    failure_artifact = (
        tmp_path
        / "outline"
        / "chapter_packets"
        / "chapter-001"
        / "failures"
        / "attempt-1.txt"
    )
    assert failure_artifact.exists()
    assert "semantic_review:canon drift" in failure_artifact.read_text(encoding="utf-8")


def test_run_book_pipeline_uses_ranked_fallback_after_primary_failure(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    class _RoleLLM:
        def __init__(self, model_name: str):
            self.model_name = model_name
            self._outline_failures = 0

        def invoke(self, prompt):
            text = str(prompt)
            if (
                self.model_name == "meta-llama/llama-3.3-70b-instruct:free"
                and "Return markdown bullets only." in text
            ):
                self._outline_failures += 1
                raise RuntimeError("Model invocation failed: Error code: 429")

            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a global coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Generated Chapter:" in text and "Approved Scene Plan:" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Return markdown bullets only." in text:
                return SimpleNamespace(content="- Scene 1\n- Scene 2\n- Scene 3")
            if (
                "Return ONLY valid JSON" in text
                or "Repair this into strict JSON" in text
            ):
                return SimpleNamespace(
                    content=(
                        '{"goal":"goal ok","conflict":"conflict ok",'
                        '"stakes":"stakes ok","outcome":"decides outcome ok"}'
                    )
                )
            if "Extract narrative state deltas from chapter prose" in text:
                return SimpleNamespace(
                    content='{"character_deltas":[{"id":"protagonist","name":"Protagonist"}],"relationship_changes":[],"world_facts":[],"thread_changes":[]}'
                )
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(3000))
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_RoleLLM("assistant-model")),
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
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="arcee-ai/trinity-large-preview:free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {
                "primary": "meta-llama/llama-3.3-70b-instruct:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "test",
            },
            "batch_prose": {
                "primary": "arcee-ai/trinity-large-preview:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "test",
            },
            "batch_editing": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "test",
            },
            "repair_json": {
                "primary": "google/gemma-3-27b-it:free",
                "fallbacks": ["stepfun/step-3.5-flash:free"],
                "why": "test",
            },
            "coherence_check": {
                "primary": "stepfun/step-3.5-flash:free",
                "fallbacks": ["google/gemma-3-27b-it:free"],
                "why": "test",
                "context_limit": 128000,
            },
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda settings: _RoleLLM(settings.model),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.NarrativeMemoryManager",
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )

    summary = run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\n\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    output = capsys.readouterr().out
    assert summary.chapters_generated == 1
    assert "Stage=outline role=batch_planning" in output
    assert "effective=stepfun/step-3.5-flash:free" in output
    assert "source=fallback" in output

    packet_dir = tmp_path / "outline" / "chapter_packets" / "chapter-001"
    diagnostics_payload = json.loads(
        (packet_dir / "diagnostics.json").read_text(encoding="utf-8")
    )
    invocations = diagnostics_payload.get("model_invocations", [])
    failed_rows = [
        row
        for row in invocations
        if row.get("role") == "batch_planning" and row.get("status") == "failed"
    ]
    assert failed_rows
    assert failed_rows[0].get("effective_model_id")
    assert failed_rows[0].get("configured_model_id")

    transport_rows = diagnostics_payload.get("transport_errors", [])
    assert transport_rows
    assert transport_rows[0].get("provider") == "openrouter"
    assert transport_rows[0].get("effective_model")


def test_run_book_pipeline_injects_canon_state_and_history_grounding(
    tmp_path,
    monkeypatch,
) -> None:
    prompts_by_model: dict[str, list[str]] = {}

    class _FallbackAssistantLLM:
        def invoke(self, _prompt):
            return SimpleNamespace(content="fallback")

    class _RoleLLM:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def invoke(self, prompt):
            text = str(prompt)
            prompts_by_model.setdefault(self.model_name, []).append(text)
            if "canon safety checker" in text:
                return SimpleNamespace(content='{"violation": false}')
            if "Run a global coherence audit" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Generated Chapter:" in text and "Chapter:" in text:
                return SimpleNamespace(content='{"status":"PASS"}')
            if "Stitch chapter" in text and "[Scene 1]" in text:
                return SimpleNamespace(
                    content=" ".join(f"stitched{idx}" for idx in range(3000))
                )
            if "Return ONLY valid JSON" in text:
                return SimpleNamespace(
                    content='{"goal":"goal ok","conflict":"conflict ok","stakes":"stakes ok","outcome":"decides outcome ok"}'
                )
            return SimpleNamespace(content=" ".join(f"word{idx}" for idx in range(900)))

    class _FakeStateStore:
        def __init__(self, _book_path: str):
            pass

        def load(self):
            return SimpleNamespace(characters={}, locations={}, plot_threads=[])

        def render_prompt_block(self, *, max_chars: int = 2400):
            _ = max_chars
            return '[Narrative State v1 as of now]\\n{"characters":{}}'

        def apply_patch(self, _patch, actor: str = "system"):
            assert actor == "book-engine"
            return SimpleNamespace(plot_threads=[])

    monkeypatch.setattr(
        "storycraftr.cmd.story.book.create_or_get_assistant",
        lambda _book_path: SimpleNamespace(llm=_FallbackAssistantLLM()),
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
        lambda **_kwargs: SimpleNamespace(add_memory=lambda **__kwargs: True),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            llm_model="openrouter/free",
            llm_endpoint="",
            llm_api_key_env="",
            temperature=0.7,
            request_timeout=30,
            max_tokens=8192,
            enable_semantic_review=True,
        ),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.validate_openrouter_rankings_config",
        lambda: {
            "batch_planning": {"primary": "planner-model", "fallbacks": []},
            "batch_prose": {"primary": "prose-model", "fallbacks": []},
            "batch_editing": {"primary": "edit-model", "fallbacks": []},
            "repair_json": {"primary": "repair-model", "fallbacks": []},
            "coherence_check": {"primary": "coherence-model", "fallbacks": []},
        },
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.build_chat_model",
        lambda settings: _RoleLLM(settings.model),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.extract_state_patch",
        lambda _text, snapshot, **_kwargs: SimpleNamespace(
            patch=SimpleNamespace(operations=[{"operation": "add"}]),
            events=[],
        ),
    )

    run_book_pipeline(
        book_path=str(tmp_path),
        seed_text="# Seed\\n\\nPinned context",
        chapters=1,
        auto_approve=True,
    )

    all_prompts = "\n".join(
        prompt for prompts in prompts_by_model.values() for prompt in prompts
    )
    assert "[Continuity Grounding for Chapter 1]" in all_prompts
    assert "[Canon Facts JSON]" in all_prompts
    assert "Narrative State" in all_prompts

    coherence_prompts = "\n".join(prompts_by_model.get("coherence-model", []))
    assert "All chapter history (full text in order):" in coherence_prompts


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


def test_book_command_requires_semantic_review_for_autonomous_runs(
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
        lambda _path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            enable_semantic_review=False,
        ),
    )

    result = runner.invoke(
        cli,
        ["book", "--book-path", str(project), "--seed", "seed.md", "--yes"],
    )

    assert result.exit_code == 1
    assert "require semantic validation" in result.output


def test_book_command_requires_semantic_review_without_yes_flag(
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
        lambda _path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            enable_semantic_review=False,
        ),
    )

    result = runner.invoke(
        cli,
        ["book", "--book-path", str(project), "--seed", "seed.md"],
    )

    assert result.exit_code == 1
    assert "require semantic validation" in result.output


def test_run_book_pipeline_requires_semantic_review_for_strict_autonomous(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            enable_semantic_review=False,
        ),
    )

    with pytest.raises(BookEngineError, match="require semantic review enabled"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )


def test_run_book_pipeline_requires_semantic_review_without_auto_approve(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "storycraftr.cmd.story.book.load_book_config",
        lambda _book_path: SimpleNamespace(
            book_name="Demo",
            llm_provider="openrouter",
            enable_semantic_review=False,
        ),
    )

    with pytest.raises(BookEngineError, match="require semantic review enabled"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=False,
        )


def test_run_book_pipeline_fails_on_invalid_planner_schema(
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
                    content='{"goal":"ok","conflict":"ok","stakes":"ok","outcome":"decides ok","extra":"nope"}'
                )
            return SimpleNamespace(content="generated text")

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

    with pytest.raises(BookEngineError, match="strict directive schema validation"):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )


def test_run_book_pipeline_writes_failed_book_audit_on_halt(
    tmp_path,
    monkeypatch,
) -> None:
    class _FakeLLM:
        def invoke(self, prompt):
            text = str(prompt)
            if "Return ONLY valid JSON" in text:
                return SimpleNamespace(content='{"goal":"ok","extra":"bad"}')
            return SimpleNamespace(content="generated text")

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

    with pytest.raises(BookEngineError):
        run_book_pipeline(
            book_path=str(tmp_path),
            seed_text="# Seed\n\nPinned context",
            chapters=1,
            auto_approve=True,
        )

    audit_json = tmp_path / "outline" / "book_audit.json"
    audit_md = tmp_path / "outline" / "book_audit.md"
    assert audit_json.exists()
    assert audit_md.exists()
    payload = json.loads(audit_json.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "strict directive schema" in payload["error"]
    assert "failed_guard" in payload


def test_chapters_chapter_requires_explicit_unsafe_flag(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    monkeypatch.setattr(
        "storycraftr.cmd.story.chapters.load_book_config",
        lambda _path: SimpleNamespace(book_name="Demo"),
    )

    result = runner.invoke(
        cli,
        [
            "chapters",
            "chapter",
            "1",
            "prompt text",
            "--book-path",
            str(project),
        ],
    )

    assert result.exit_code == 1
    assert "Direct chapter generation is disabled by default" in result.output


def test_chapters_chapter_blocks_unsafe_write_without_env_flag(
    tmp_path, monkeypatch
) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()

    monkeypatch.setattr(
        "storycraftr.cmd.story.chapters.load_book_config",
        lambda _path: SimpleNamespace(book_name="Demo"),
    )

    result = runner.invoke(
        cli,
        [
            "chapters",
            "chapter",
            "1",
            "prompt text",
            "--book-path",
            str(project),
            "--unsafe-direct-write",
        ],
    )

    assert result.exit_code == 1
    assert "STORYCRAFTR_ALLOW_UNSAFE=1" in result.output


def test_chapters_chapter_allows_unsafe_write_with_env_flag(
    tmp_path, monkeypatch
) -> None:
    runner = CliRunner()
    project = tmp_path / "demo"
    project.mkdir()
    called: list[tuple[str, int, str]] = []

    monkeypatch.setattr(
        "storycraftr.cmd.story.chapters.load_book_config",
        lambda _path: SimpleNamespace(book_name="Demo"),
    )
    monkeypatch.setattr(
        "storycraftr.cmd.story.chapters.generate_chapter",
        lambda book_path, chapter_number, prompt: called.append(
            (book_path, chapter_number, prompt)
        ),
    )
    monkeypatch.setenv("STORYCRAFTR_ALLOW_UNSAFE", "1")

    result = runner.invoke(
        cli,
        [
            "chapters",
            "chapter",
            "2",
            "prompt text",
            "--book-path",
            str(project),
            "--unsafe-direct-write",
        ],
    )

    assert result.exit_code == 0
    assert called == [(str(project), 2, "prompt text")]


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
