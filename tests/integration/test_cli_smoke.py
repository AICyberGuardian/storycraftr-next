from pathlib import Path
import json
from unittest import mock

from click.testing import CliRunner

from storycraftr.cli import cli


def test_storycraftr_init_smoke_creates_expected_structure(tmp_path):
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=str(tmp_path)):
        workspace = Path.cwd()
        Path("behavior.txt").write_text("Be concise and helpful.", encoding="utf-8")

        with (
            mock.patch("storycraftr.init.create_or_get_assistant") as mock_assistant,
            mock.patch("storycraftr.agent.agents.build_chat_model") as mock_llm_factory,
        ):
            result = runner.invoke(
                cli,
                [
                    "init",
                    "demo-book",
                    "--behavior",
                    "behavior.txt",
                    "--llm-provider",
                    "fake",
                    "--llm-model",
                    "offline-model",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_assistant.assert_called_once()
        mock_llm_factory.assert_not_called()

        project = workspace / "demo-book"
        assert project.is_dir()
        assert (project / "storycraftr.json").is_file()
        config = json.loads((project / "storycraftr.json").read_text(encoding="utf-8"))
        assert config["max_tokens"] == 8192
        assert (project / "behaviors" / "default.txt").is_file()
        assert (project / "templates" / "template.tex").is_file()
        assert (project / "storycraftr" / "getting_started.md").is_file()
        assert (project / ".storycraftr" / "subagents").is_dir()
        assert (project / ".storycraftr" / "subagents" / "logs").is_dir()
