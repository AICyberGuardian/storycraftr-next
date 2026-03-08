import json
import os
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

    result = runner.invoke(cli, ["model-list"])

    assert result.exit_code == 0, result.output
    assert "id | context_length | max_completion_tokens | free" in result.output
    assert "openrouter/free | 32768 | 4096 | yes" in result.output


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
