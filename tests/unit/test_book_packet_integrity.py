from __future__ import annotations

import pytest

from storycraftr.cmd.story.book import (
    _assert_packet_integrity,
    _write_attempt_transport_error,
)


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


def test_write_attempt_transport_error_persists_json_artifact(tmp_path) -> None:
    packet_dir = tmp_path / "chapter-001"
    payload = {
        "http_status": 429,
        "provider": "openrouter",
        "configured_model": "openrouter/free",
        "effective_model": "openrouter/free",
        "raw_error_body": "rate limited",
        "retryable": True,
    }

    _write_attempt_transport_error(packet_dir=packet_dir, attempt=2, payload=payload)

    artifact = packet_dir / "failures" / "attempt-2" / "transport_error.json"
    assert artifact.exists()
    text = artifact.read_text(encoding="utf-8")
    assert '"http_status": 429' in text
    assert '"provider": "openrouter"' in text
