import json
import time
from contextlib import contextmanager
from io import StringIO
from pathlib import Path

from rich.console import Console

from storycraftr.subagents import SubAgentJobManager, seed_default_roles
from storycraftr.subagents.jobs import SubAgentJob
from storycraftr.subagents.storage import ensure_storage_dirs, load_roles


def _wait_for_job_completion(
    manager: SubAgentJobManager, max_attempts: int = 50
) -> str:
    for _ in range(max_attempts):
        status = manager.list_jobs()[0].status
        if status in {"succeeded", "failed"}:
            return status
        time.sleep(0.1)
    return manager.list_jobs()[0].status


def _minimal_config(tmp_path: Path) -> None:
    config = {
        "book_name": "Test",
        "primary_language": "en",
        "alternate_languages": [],
        "default_author": "Tester",
        "genre": "fantasy",
        "license": "CC",
        "reference_author": "",
        "cli_name": "storycraftr",
        "multiple_answer": True,
        "llm_provider": "openai",
        "llm_model": "gpt-4o",
        "llm_endpoint": "",
        "llm_api_key_env": "",
        "temperature": 0.7,
        "request_timeout": 120,
        "embed_model": "BAAI/bge-large-en-v1.5",
        "embed_device": "auto",
        "embed_cache_dir": "",
    }
    (tmp_path / "storycraftr.json").write_text(json.dumps(config), encoding="utf-8")


def test_seed_default_roles_creates_files(tmp_path):
    _minimal_config(tmp_path)
    written = seed_default_roles(tmp_path, language="en", force=True)
    assert written, "Expected the default role YAML files to be created."
    for path in written:
        assert path.is_file()


def test_job_manager_runs_background_job(monkeypatch, tmp_path):
    _minimal_config(tmp_path)
    seed_default_roles(tmp_path, language="en", force=True)

    captured = {}

    def fake_run_module_command(command_text, console, book_path):
        captured["command"] = command_text
        captured["book_path"] = book_path

    monkeypatch.setattr(
        "storycraftr.subagents.jobs.run_module_command", fake_run_module_command
    )

    manager = SubAgentJobManager(
        str(tmp_path), Console(file=StringIO(), force_terminal=False)
    )

    job = manager.submit(
        command_token="!outline",  # nosec B106
        args=["general-outline", "Refine the prologue"],
        role_slug="editor",
    )

    status = _wait_for_job_completion(manager)

    manager.shutdown()

    assert job.job_id
    assert captured["book_path"] == str(tmp_path)
    assert captured["command"].startswith("outline general-outline")
    assert status == "succeeded"


def test_job_manager_records_unexpected_worker_exceptions(monkeypatch, tmp_path):
    _minimal_config(tmp_path)
    seed_default_roles(tmp_path, language="en", force=True)

    def fake_run_module_command(command_text, console, book_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "storycraftr.subagents.jobs.run_module_command", fake_run_module_command
    )

    manager = SubAgentJobManager(
        str(tmp_path), Console(file=StringIO(), force_terminal=False)
    )
    manager.submit(
        command_token="!outline",  # nosec B106
        args=["general-outline", "Refine the prologue"],
        role_slug="editor",
    )

    status = _wait_for_job_completion(manager)
    manager.shutdown()

    job = manager.list_jobs()[0]
    assert status == "failed"
    assert job.error is not None
    assert "RuntimeError: boom" in job.error
    assert job.log_path is not None
    assert job.log_path.exists()


def test_job_manager_marks_job_failed_if_log_persistence_fails(monkeypatch, tmp_path):
    _minimal_config(tmp_path)
    seed_default_roles(tmp_path, language="en", force=True)

    def fake_run_module_command(command_text, console, book_path):
        console.print("ok")

    monkeypatch.setattr(
        "storycraftr.subagents.jobs.run_module_command", fake_run_module_command
    )

    manager = SubAgentJobManager(
        str(tmp_path), Console(file=StringIO(), force_terminal=False)
    )

    def always_fail_persist(job):
        raise OSError("disk full")

    monkeypatch.setattr(manager, "_persist_job", always_fail_persist)

    role = manager.get_role("editor")
    assert role is not None
    job = SubAgentJob(
        job_id="persist-failure",
        role=role,
        command_text="outline general-outline 'Refine the prologue'",
    )

    manager._run_job(job)
    manager.shutdown()

    assert job.status == "failed"
    assert job.error is not None
    assert "Failed to persist sub-agent job logs" in job.error


def test_load_roles_skips_malformed_yaml_files(tmp_path):
    _minimal_config(tmp_path)
    root = ensure_storage_dirs(str(tmp_path))
    (root / "broken.yaml").write_text("slug: [broken", encoding="utf-8")

    roles = load_roles(str(tmp_path))

    assert roles == {}


def test_load_roles_skips_invalid_whitelist_schema(tmp_path):
    _minimal_config(tmp_path)
    root = ensure_storage_dirs(str(tmp_path))
    (root / "bad-role.yaml").write_text(
        "slug: bad\ncommand_whitelist: '!outline'\n",
        encoding="utf-8",
    )

    roles = load_roles(str(tmp_path))

    assert "bad" not in roles


def test_seed_default_roles_uses_project_write_lock(monkeypatch, tmp_path):
    _minimal_config(tmp_path)
    calls: list[str] = []

    @contextmanager
    def fake_lock(book_path: str, *, config=None, **_kwargs):
        calls.append(book_path)
        yield Path(book_path) / ".storycraftr" / "project.lock"

    monkeypatch.setattr("storycraftr.subagents.storage.project_write_lock", fake_lock)

    seed_default_roles(str(tmp_path), language="en", force=True)

    assert calls == [str(tmp_path)]


def test_job_manager_persist_job_uses_project_write_lock(monkeypatch, tmp_path):
    _minimal_config(tmp_path)
    seed_default_roles(tmp_path, language="en", force=True)

    manager = SubAgentJobManager(
        str(tmp_path), Console(file=StringIO(), force_terminal=False)
    )
    lock_calls: list[str] = []

    @contextmanager
    def fake_lock(book_path: str, *, config=None, **_kwargs):
        lock_calls.append(book_path)
        yield Path(book_path) / ".storycraftr" / "project.lock"

    monkeypatch.setattr("storycraftr.subagents.jobs.project_write_lock", fake_lock)

    try:
        role = manager.get_role("editor")
        assert role is not None

        job = SubAgentJob(
            job_id="lock-test-job",
            role=role,
            command_text="outline general-outline 'Refine the prologue'",
            status="succeeded",
            output="ok",
        )
        manager._persist_job(job)
    finally:
        manager.shutdown()

    assert lock_calls
    assert lock_calls[0] == str(tmp_path)
    assert job.job_id
