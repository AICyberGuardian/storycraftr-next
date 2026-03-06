from __future__ import annotations

import errno
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from storycraftr.utils.paths import resolve_project_paths

try:  # pragma: no cover - platform dependent import
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]


_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_THREAD_LOCAL = threading.local()


def _get_process_lock(lock_path: Path) -> threading.RLock:
    key = str(lock_path)
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


def _get_thread_depths() -> dict[str, int]:
    depths = getattr(_THREAD_LOCAL, "lock_depths", None)
    if depths is None:
        depths = {}
        _THREAD_LOCAL.lock_depths = depths
    return depths


@contextmanager
def project_write_lock(
    book_path: str,
    *,
    config: object | None = None,
    timeout_seconds: float = 30.0,
    poll_interval: float = 0.1,
) -> Iterator[Path]:
    """
    Acquire a project-scoped mutation lock.

    The lock is process-safe via ``threading.RLock`` and, on POSIX platforms,
    cross-process safe via an advisory ``flock`` lock file under
    ``<internal_state_root>/project.lock``.
    """

    internal_state_root = resolve_project_paths(
        book_path, config=config
    ).internal_state_root
    lock_path = internal_state_root / "project.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    process_lock = _get_process_lock(lock_path)
    lock_key = str(lock_path)
    with process_lock:
        depths = _get_thread_depths()
        current_depth = depths.get(lock_key, 0)

        if current_depth > 0:
            depths[lock_key] = current_depth + 1
            try:
                yield lock_path
            finally:
                next_depth = depths[lock_key] - 1
                if next_depth > 0:
                    depths[lock_key] = next_depth
                else:
                    depths.pop(lock_key, None)
            return

        if fcntl is None:  # pragma: no cover - non-POSIX fallback
            depths[lock_key] = current_depth + 1
            try:
                yield lock_path
            finally:
                next_depth = depths[lock_key] - 1
                if next_depth > 0:
                    depths[lock_key] = next_depth
                else:
                    depths.pop(lock_key, None)
            return

        with lock_path.open("a+", encoding="utf-8") as handle:
            file_descriptor: int | None
            try:
                candidate_fd = handle.fileno()
            except Exception:
                candidate_fd = None

            # Some unit tests patch Path.open with mock_open; those handles do not
            # provide a real integer descriptor for flock(). Fall back to process-
            # local locking in that case while preserving real-file flock behavior.
            file_descriptor = candidate_fd if isinstance(candidate_fd, int) else None

            if file_descriptor is None:
                depths[lock_key] = current_depth + 1
                try:
                    yield lock_path
                finally:
                    next_depth = depths[lock_key] - 1
                    if next_depth > 0:
                        depths[lock_key] = next_depth
                    else:
                        depths.pop(lock_key, None)
                return

            deadline = time.monotonic() + max(timeout_seconds, 0.0)
            while True:
                try:
                    fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Timed out acquiring project lock at {lock_path}."
                        )
                    time.sleep(max(poll_interval, 0.01))

            depths[lock_key] = current_depth + 1
            try:
                yield lock_path
            finally:
                next_depth = depths[lock_key] - 1
                if next_depth > 0:
                    depths[lock_key] = next_depth
                else:
                    depths.pop(lock_key, None)
                fcntl.flock(file_descriptor, fcntl.LOCK_UN)
