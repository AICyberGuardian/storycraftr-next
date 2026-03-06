from __future__ import annotations

import importlib


def test_cli_import_has_no_credential_loading_side_effect(monkeypatch) -> None:
    import storycraftr.cli as cli_module
    import storycraftr.llm.credentials as credentials

    calls = {"count": 0}

    def _fake_load_local_credentials(*_args, **_kwargs):
        calls["count"] += 1

    monkeypatch.setattr(
        credentials, "load_local_credentials", _fake_load_local_credentials
    )
    importlib.reload(cli_module)

    assert calls["count"] == 0


def test_cli_credential_bootstrap_runs_once(monkeypatch) -> None:
    import storycraftr.cli as cli_module

    calls = {"count": 0}

    def _fake_load_local_credentials(*_args, **_kwargs):
        calls["count"] += 1

    monkeypatch.setattr(
        cli_module, "load_local_credentials", _fake_load_local_credentials
    )
    monkeypatch.setattr(cli_module, "_CREDENTIALS_LOADED", False)

    cli_module._ensure_local_credentials_loaded()
    cli_module._ensure_local_credentials_loaded()

    assert calls["count"] == 1
