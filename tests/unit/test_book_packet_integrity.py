from __future__ import annotations

import pytest

from storycraftr.cmd.story.book import _assert_packet_integrity


def test_packet_integrity_fails_when_required_artifact_missing(tmp_path) -> None:
    packet_dir = tmp_path / "chapter-001"
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / "diagnostics.json").write_text("{}\n", encoding="utf-8")
    (packet_dir / "validator_report.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="packet_integrity_failed"):
        _assert_packet_integrity(packet_dir)


def test_packet_integrity_passes_when_required_artifacts_exist(tmp_path) -> None:
    packet_dir = tmp_path / "chapter-001"
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / "diagnostics.json").write_text("{}\n", encoding="utf-8")
    (packet_dir / "validator_report.json").write_text("{}\n", encoding="utf-8")
    (packet_dir / "raw_payloads.json").write_text(
        '{"stage":"payload"}\n', encoding="utf-8"
    )

    _assert_packet_integrity(packet_dir)
