from __future__ import annotations

import json
import logging
import re
import shlex
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import CancelledError as FutureCancelledError
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib import import_module
from io import StringIO
from pathlib import Path
from queue import Queue
from typing import Callable, Dict, List, Optional

from rich.console import Console

from storycraftr.chat.module_runner import ModuleCommandError, run_module_command
from storycraftr.utils.core import load_book_config
from storycraftr.utils.paths import resolve_project_paths
from storycraftr.utils.project_lock import project_write_lock

from .models import SubAgentRole
from .storage import ensure_storage_dirs, load_roles, seed_default_roles


logger = logging.getLogger(__name__)

_MODEL_EXHAUSTED_COOLDOWN_SECONDS = 30.0
_MODEL_EXHAUSTED_MAX_RETRIES = 1
_MODEL_EXHAUSTED_PATTERNS = (
    re.compile(r"\b429\b", re.IGNORECASE),
    re.compile(r"rate\s*limit", re.IGNORECASE),
    re.compile(r"quota", re.IGNORECASE),
    re.compile(r"capacity", re.IGNORECASE),
    re.compile(r"model\s+is\s+currently\s+overloaded", re.IGNORECASE),
    re.compile(r"temporarily\s+unavailable", re.IGNORECASE),
)

# Serializes module-level console swaps across concurrent sub-agent workers.
_CONSOLE_SWAP_LOCK = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SubAgentJob:
    job_id: str
    role: SubAgentRole
    command_text: str
    status: str = "pending"
    created_at: datetime = field(default_factory=_utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    output: str = ""
    error: Optional[str] = None
    log_path: Optional[Path] = None
    attempts: int = 0
    cooldown_until: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "role": self.role.slug,
            "role_name": self.role.name,
            "command_text": self.command_text,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "output": self.output,
            "error": self.error,
            "log_path": str(self.log_path) if self.log_path else None,
            "attempts": self.attempts,
            "cooldown_until": (
                self.cooldown_until.isoformat() if self.cooldown_until else None
            ),
        }


class SubAgentJobManager:
    """
    Coordinates role discovery, job submission, and logging for sub-agents.
    """

    def __init__(
        self,
        book_path: str,
        console: Console,
        *,
        event_queue: Optional[Queue] = None,
        event_callback: Optional[Callable[[str, dict], None]] = None,
    ):
        self.book_path = Path(book_path)
        self.console = console
        self.event_queue = event_queue
        self.config = load_book_config(str(self.book_path))
        self.root = ensure_storage_dirs(book_path, config=self.config)
        self.logs_root = resolve_project_paths(
            book_path, config=self.config
        ).subagents_logs_root
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent")
        self.roles = self._ensure_roles()
        self.jobs: Dict[str, SubAgentJob] = {}
        self.futures: Dict[str, Future] = {}
        self.event_callback = event_callback

    def shutdown(self, wait: bool = False) -> None:
        with self.lock:
            futures = list(self.futures.values())
            for future in futures:
                future.cancel()
            self.futures.clear()
        self.executor.shutdown(wait=wait, cancel_futures=True)

    # Role management -----------------------------------------------------------------

    def _ensure_roles(self) -> Dict[str, SubAgentRole]:
        roles = load_roles(str(self.book_path), config=self.config)
        if roles:
            return roles
        language = self.config.primary_language if self.config else "en"
        seed_default_roles(
            str(self.book_path),
            language=language,
            force=False,
            config=self.config,
        )
        return load_roles(str(self.book_path), config=self.config)

    def reload_roles(self) -> None:
        with self.lock:
            self.roles = load_roles(str(self.book_path), config=self.config)

    def list_roles(self) -> List[SubAgentRole]:
        with self.lock:
            return sorted(self.roles.values(), key=lambda r: r.name.lower())

    def get_role(self, slug: str) -> Optional[SubAgentRole]:
        slug = slug.lower()
        with self.lock:
            return self.roles.get(slug)

    # Job submission -------------------------------------------------------------------

    def submit(
        self,
        *,
        command_token: str,
        args: List[str],
        role_slug: Optional[str] = None,
    ) -> SubAgentJob:
        if not command_token.startswith("!"):
            raise ValueError("Command token must start with '!'.")

        role = self._select_role(command_token, role_slug)
        if role is None:
            raise ValueError(
                "No role found for the requested command. "
                "Use :sub-agent !list to inspect available roles."
            )

        payload_tokens = [command_token[1:]] + args
        command_text = shlex.join(payload_tokens)
        job = SubAgentJob(job_id=uuid.uuid4().hex, role=role, command_text=command_text)

        with self.lock:
            self.jobs[job.job_id] = job

        self._emit_event("queued", job)
        future = self.executor.submit(self._run_job, job)
        with self.lock:
            self.futures[job.job_id] = future
        future.add_done_callback(
            lambda completed, job_id=job.job_id: self._handle_future_completion(
                job_id, completed
            )
        )
        return job

    def list_jobs(self) -> List[SubAgentJob]:
        with self.lock:
            return sorted(
                self.jobs.values(), key=lambda job: job.created_at, reverse=True
            )

    def job_stats(self) -> Dict[str, int]:
        with self.lock:
            stats = {
                "pending": 0,
                "running": 0,
                "model_exhausted": 0,
                "succeeded": 0,
                "failed": 0,
            }
            for job in self.jobs.values():
                if job.status in stats:
                    stats[job.status] += 1
            return stats

    # Helpers -------------------------------------------------------------------------

    def _select_role(
        self, command_token: str, role_slug: Optional[str]
    ) -> Optional[SubAgentRole]:
        with self.lock:
            if role_slug:
                return self.roles.get(role_slug.lower())
            for role in self.roles.values():
                if command_token in role.command_whitelist:
                    return role
        return None

    def _run_job(self, job: SubAgentJob) -> None:
        max_attempts = 1 + max(_MODEL_EXHAUSTED_MAX_RETRIES, 0)
        output_chunks: List[str] = []
        status = "failed"
        error_text: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            attempt_output, error_text, status = self._run_single_job_attempt(
                job, attempt=attempt
            )
            if attempt_output:
                output_chunks.append(attempt_output)

            if status == "succeeded":
                break

            if (
                status == "failed"
                and error_text
                and self._is_model_exhausted_error(error_text)
                and attempt < max_attempts
            ):
                self._enter_model_exhausted_cooldown(
                    job,
                    error_text,
                    cooldown_seconds=_MODEL_EXHAUSTED_COOLDOWN_SECONDS,
                )
                continue

            break

        with self.lock:
            job.finished_at = _utcnow()
            job.status = status
            job.cooldown_until = None
            job.output = "\n\n".join(output_chunks).strip()
            if error_text:
                job.error = self._merge_errors(job.error, error_text)

        try:
            self._persist_job(job)
        except Exception as exc:  # pragma: no cover - filesystem safety net
            logger.exception("Failed to persist sub-agent job %s", job.job_id)
            with self.lock:
                job.status = "failed"
                persist_error = (
                    f"Failed to persist sub-agent job logs: {type(exc).__name__}: {exc}"
                )
                job.error = self._merge_errors(job.error, persist_error)
            try:
                self._persist_job(job)
            except Exception:  # pragma: no cover - terminal fallback
                logger.exception(
                    "Second persistence attempt failed for sub-agent job %s",
                    job.job_id,
                )

        self._emit_event(job.status, job)

    def _run_single_job_attempt(
        self, job: SubAgentJob, *, attempt: int
    ) -> tuple[str, Optional[str], str]:
        with self.lock:
            if job.started_at is None:
                job.started_at = _utcnow()
            job.attempts = attempt
            job.status = "running"
            job.cooldown_until = None
        self._emit_event("running", job)

        buffer_out = StringIO()
        buffer_err = StringIO()
        job_console = Console(file=buffer_out, force_terminal=False, color_system=None)
        status = "succeeded"
        error_text: Optional[str] = None

        with _CONSOLE_SWAP_LOCK:
            swaps = _swap_storycraftr_consoles(job_console)
            try:
                with redirect_stdout(buffer_out), redirect_stderr(buffer_err):
                    run_module_command(
                        job.command_text,
                        console=job_console,
                        book_path=str(self.book_path),
                    )
            except ModuleCommandError as exc:
                status = "failed"
                error_text = str(exc)
                logger.warning("Sub-agent job %s failed: %s", job.job_id, exc)
            except Exception as exc:  # pragma: no cover - safety net
                status = "failed"
                error_text = f"{type(exc).__name__}: {exc}"
                logger.exception("Unhandled exception in sub-agent job %s", job.job_id)
            finally:
                _restore_storycraftr_consoles(swaps)

        stdout_text = buffer_out.getvalue()
        stderr_text = buffer_err.getvalue()
        if stderr_text:
            stdout_text = f"{stdout_text}\n\n[stderr]\n{stderr_text}".strip()
        return stdout_text.strip(), error_text, status

    def _enter_model_exhausted_cooldown(
        self,
        job: SubAgentJob,
        error_text: str,
        *,
        cooldown_seconds: float,
    ) -> None:
        delay = max(float(cooldown_seconds), 0.0)
        deadline = _utcnow() + timedelta(seconds=delay)
        cooldown_msg = (
            "Model exhausted or rate-limited; entering cooldown before retry."
        )

        with self.lock:
            job.status = "model_exhausted"
            job.cooldown_until = deadline
            job.error = self._merge_errors(job.error, error_text)
            job.error = self._merge_errors(job.error, cooldown_msg)

        self._emit_event("model_exhausted", job)
        try:
            self._persist_job(job)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to persist cooldown checkpoint for sub-agent job %s",
                job.job_id,
            )

        time.sleep(delay)

        with self.lock:
            job.status = "pending"
            job.cooldown_until = None
        self._emit_event("pending", job)

    @staticmethod
    def _is_model_exhausted_error(error_text: str) -> bool:
        for pattern in _MODEL_EXHAUSTED_PATTERNS:
            if pattern.search(error_text):
                return True
        return False

    def _handle_future_completion(self, job_id: str, future: Future) -> None:
        with self.lock:
            self.futures.pop(job_id, None)

        if future.cancelled():
            logger.info("Sub-agent job %s was cancelled.", job_id)
            with self.lock:
                job = self.jobs.get(job_id)
                if not job:
                    return
                job.status = "failed"
                job.finished_at = job.finished_at or _utcnow()
                job.error = self._merge_errors(
                    job.error, "Job was cancelled before execution completed."
                )
            try:
                self._persist_job(job)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "Failed to persist cancellation diagnostics for sub-agent job %s",
                    job_id,
                )
            self._emit_event("failed", job)
            return

        try:
            exc = future.exception()
        except FutureCancelledError:
            return
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Unable to inspect completion state for sub-agent job %s", job_id
            )
            return

        if exc is None:
            return

        logger.error(
            "Sub-agent job %s crashed outside normal error handling.",
            job_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job.status = "failed"
            job.finished_at = job.finished_at or _utcnow()
            job.error = self._merge_errors(
                job.error, f"Unhandled worker exception: {type(exc).__name__}: {exc}"
            )

        try:
            self._persist_job(job)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to persist crash diagnostics for sub-agent job %s", job_id
            )
        self._emit_event("failed", job)

    def _persist_job(self, job: SubAgentJob) -> None:
        with project_write_lock(str(self.book_path), config=self.config):
            log_dir = self.logs_root / job.role.slug
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = (job.finished_at or _utcnow()).strftime("%Y%m%d-%H%M%S")
            log_base = f"{timestamp}-{job.job_id}"
            md_path = log_dir / f"{log_base}.md"
            metadata_path = log_dir / f"{log_base}.json"

            if job.output or job.error:
                md_body = [
                    f"# Sub-Agent Run · {job.role.name}",
                    f"- Role: {job.role.slug}",
                    f"- Command: {job.command_text}",
                    f"- Status: {job.status}",
                    f"- Started: {job.started_at or job.created_at}",
                    f"- Finished: {job.finished_at or ''}",
                    "",
                    "## Output",
                    job.output or "_No output recorded._",
                ]
                if job.error:
                    md_body.extend(["", "## Error", job.error])
                md_path.write_text("\n".join(md_body), encoding="utf-8")
                job.log_path = md_path

            metadata_path.write_text(
                json.dumps(job.to_dict(), indent=2), encoding="utf-8"
            )

    # Logs ----------------------------------------------------------------------------

    def role_logs(self, role_slug: str, limit: int = 5) -> List[Path]:
        role_dir = self.logs_root / role_slug.lower()
        if not role_dir.exists():
            return []
        files = sorted(role_dir.glob("*.md"), reverse=True)
        return files[:limit]

    # Internal helpers -------------------------------------------------------

    def _emit_event(self, event_type: str, job: SubAgentJob) -> None:
        with self.lock:
            job_payload = job.to_dict()
        payload = {
            "type": event_type,
            "job": job_payload,
        }
        if self.event_queue:
            self.event_queue.put(payload)
        if self.event_callback:
            try:
                self.event_callback(event_type, payload["job"])
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Sub-agent event callback failed: %s", exc)

    @staticmethod
    def _merge_errors(existing: Optional[str], new: str) -> str:
        clean_new = (new or "").strip()
        if not clean_new:
            return existing or ""
        if existing:
            return f"{existing}\n{clean_new}"
        return clean_new


_CONSOLE_MODULES = [
    "storycraftr.cmd.story.chapters",
    "storycraftr.cmd.story.iterate",
    "storycraftr.cmd.story.outline",
    "storycraftr.cmd.story.worldbuilding",
    "storycraftr.cmd.story.publish",
    "storycraftr.cmd.paper.organize_lit",
    "storycraftr.cmd.paper.outline_sections",
    "storycraftr.cmd.paper.generate_section",
    "storycraftr.cmd.paper.references",
    "storycraftr.cmd.paper.iterate",
    "storycraftr.cmd.paper.publish",
    "storycraftr.cmd.paper.abstract",
    "storycraftr.agent.agents",
    "storycraftr.agent.retrieval",
    "storycraftr.agent.story.chapters",
    "storycraftr.agent.story.iterate",
    "storycraftr.agent.story.outline",
    "storycraftr.agent.story.worldbuilding",
    "storycraftr.agent.paper.generate_section",
    "storycraftr.agent.paper.generate_pdf",
    "storycraftr.agent.paper.organize_lit",
    "storycraftr.agent.paper.outline_sections",
    "storycraftr.agent.paper.references",
    "storycraftr.agent.paper.iterate",
]


def _swap_storycraftr_consoles(replacement: Console):
    swaps = []
    for module_name in _CONSOLE_MODULES:
        module = None
        try:
            module = import_module(module_name)
        except Exception as exc:
            logger.debug("Skipping console swap for %s: %s", module_name, exc)
        if module is None:
            continue
        console_obj = getattr(module, "console", None)
        if isinstance(console_obj, Console):
            swaps.append((module, console_obj))
            setattr(module, "console", replacement)
    return swaps


def _restore_storycraftr_consoles(swaps) -> None:
    for module, original in swaps:
        setattr(module, "console", original)
