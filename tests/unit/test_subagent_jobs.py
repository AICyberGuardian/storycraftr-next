import json
import threading
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

from rich.console import Console

from storycraftr.subagents import SubAgentJobManager, seed_default_roles


def _minimal_config(tmp_path) -> None:
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


def test_shutdown_wait_false_cancels_pending_job_deterministically(
    monkeypatch, tmp_path
):
    _minimal_config(tmp_path)
    seed_default_roles(tmp_path, language="en", force=True)

    first_started = threading.Event()
    release_first = threading.Event()
    first_succeeded = threading.Event()
    cancelled_recorded = threading.Event()
    second_executed = threading.Event()
    job_ids: dict[str, str] = {}

    def fake_run_module_command(command_text, console, book_path):
        assert book_path == str(tmp_path)
        if "first-task" in command_text:
            first_started.set()
            assert release_first.wait(
                timeout=5
            ), "Timed out waiting to release first job."
            return
        second_executed.set()
        raise AssertionError("Second job should have been cancelled before execution.")

    def on_event(event_type: str, job_payload: dict):
        if event_type == "succeeded" and job_payload.get("job_id") == job_ids.get(
            "first"
        ):
            first_succeeded.set()
        if event_type == "failed" and job_payload.get("job_id") == job_ids.get(
            "second"
        ):
            error_text = (job_payload.get("error") or "").lower()
            if "cancel" in error_text:
                cancelled_recorded.set()

    monkeypatch.setattr(
        "storycraftr.subagents.jobs.run_module_command", fake_run_module_command
    )

    manager = SubAgentJobManager(
        str(tmp_path),
        Console(file=StringIO(), force_terminal=False),
        event_callback=on_event,
    )

    # Force deterministic queueing: one running worker and one pending job.
    manager.executor.shutdown(wait=True, cancel_futures=True)
    manager.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="subagent")

    first_job = manager.submit(
        command_token="!outline",  # nosec B106
        args=["first-task"],
        role_slug="editor",
    )
    job_ids["first"] = first_job.job_id
    assert first_started.wait(timeout=3), "First job did not start."

    second_job = manager.submit(
        command_token="!outline",  # nosec B106
        args=["second-task"],
        role_slug="editor",
    )
    job_ids["second"] = second_job.job_id

    second_future = manager.futures[second_job.job_id]
    manager.shutdown(wait=False)
    assert second_future.cancelled(), "Expected pending future to be cancelled."

    release_first.set()
    assert first_succeeded.wait(timeout=3), "First running job did not complete."
    assert cancelled_recorded.wait(timeout=3), "Cancelled job did not report failure."

    jobs = {job.job_id: job for job in manager.list_jobs()}
    assert jobs[first_job.job_id].status == "succeeded"
    assert jobs[second_job.job_id].status == "failed"
    assert "cancel" in (jobs[second_job.job_id].error or "").lower()
    assert not second_executed.is_set()
    assert manager.futures == {}
