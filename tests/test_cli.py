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

    with mock.patch("storycraftr.llm.credentials.keyring", None), mock.patch(
        "pathlib.Path.home", return_value=tmp_path
    ):
        load_local_credentials()

    expected = "placeholder-token"  # pragma: allowlist secret
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

    with mock.patch(
        "storycraftr.cmd.chat.load_book_config",
        side_effect=fake_load_book_config,
    ), mock.patch(
        "storycraftr.cmd.chat.create_vscode_event_emitter", return_value=None
    ), mock.patch(
        "storycraftr.cmd.chat.create_or_get_assistant", return_value=fake_assistant
    ) as mock_create_assistant, mock.patch(
        "storycraftr.cmd.chat.get_thread", return_value=fake_thread
    ), mock.patch(
        "storycraftr.cmd.chat.SubAgentJobManager", return_value=fake_job_manager
    ), mock.patch(
        "storycraftr.cmd.chat.SessionManager"
    ), mock.patch(
        "storycraftr.cmd.chat._run_turn",
        return_value={
            "user": "hello",
            "answer": "ok",
            "duration": 0.1,
            "documents": [],
        },
    ), mock.patch(
        "storycraftr.cmd.chat.render_turn"
    ), mock.patch(
        "storycraftr.cmd.chat._drain_subagent_events"
    ), mock.patch(
        "storycraftr.cmd.chat._render_session_footer"
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
