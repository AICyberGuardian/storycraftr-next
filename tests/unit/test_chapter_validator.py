from __future__ import annotations

from types import SimpleNamespace

from storycraftr.agent.chapter_validator import has_meaningful_state_signal


def test_has_meaningful_state_signal_reads_nested_patch_operations() -> None:
    assert (
        has_meaningful_state_signal({"patch": SimpleNamespace(operations=[{"op": 1}])})
        is True
    )
    assert (
        has_meaningful_state_signal({"patch": SimpleNamespace(operations=[])}) is False
    )
