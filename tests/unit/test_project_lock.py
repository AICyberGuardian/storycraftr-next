from __future__ import annotations

from storycraftr.utils.project_lock import project_write_lock


def test_project_write_lock_allows_nested_reentrant_acquire(tmp_path):
    with project_write_lock(str(tmp_path)) as outer:
        with project_write_lock(str(tmp_path)) as inner:
            assert inner == outer
