import os
from unittest import mock

import pytest

import storycraftr.llm.credentials as credentials


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    for env_var in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
        "STORYCRAFTR_KEYRING_SERVICE",
    ):
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setattr(credentials, "_KEYRING_BACKEND_AVAILABLE", None)
    monkeypatch.setattr(credentials, "_KEYRING_BACKEND_WARNING_SHOWN", False)


def test_load_local_credentials_prefers_os_keyring(monkeypatch, tmp_path):
    config_dir = tmp_path / ".storycraftr"
    config_dir.mkdir()
    (config_dir / "openai_api_key.txt").write_text("legacy-token", encoding="utf-8")

    fake_keyring = mock.Mock()

    def fake_get_password(service, username):
        if service == "storycraftr" and username == "OPENAI_API_KEY":
            return "keyring-token"
        return None

    fake_keyring.get_password.side_effect = fake_get_password
    monkeypatch.setattr(credentials, "keyring", fake_keyring)
    monkeypatch.setattr(credentials, "KeyringError", RuntimeError)

    with mock.patch("pathlib.Path.home", return_value=tmp_path):
        credentials.load_local_credentials()

    expected = "keyring-token"  # nosec B105  # pragma: allowlist secret
    assert os.environ["OPENAI_API_KEY"] == expected


def test_load_local_credentials_falls_back_to_legacy_file(monkeypatch, tmp_path):
    config_dir = tmp_path / ".storycraftr"
    config_dir.mkdir()
    (config_dir / "openai_api_key.txt").write_text(
        "legacy-fallback-token", encoding="utf-8"
    )

    fake_keyring = mock.Mock()
    fake_keyring.get_password.return_value = None
    monkeypatch.setattr(credentials, "keyring", fake_keyring)
    monkeypatch.setattr(credentials, "KeyringError", RuntimeError)

    with mock.patch("pathlib.Path.home", return_value=tmp_path):
        credentials.load_local_credentials()

    expected = "legacy-fallback-token"  # nosec B105  # pragma: allowlist secret
    assert os.environ["OPENAI_API_KEY"] == expected


def test_store_local_credential_persists_to_keyring(monkeypatch):
    fake_keyring = mock.Mock()
    monkeypatch.setattr(credentials, "keyring", fake_keyring)
    monkeypatch.setattr(credentials, "KeyringError", RuntimeError)
    token = "or-test-token"  # nosec B105  # pragma: allowlist secret

    credentials.store_local_credential(
        "OPENROUTER_API_KEY",
        token,
        service_name="storycraftr-test",
    )

    fake_keyring.set_password.assert_called_once_with(
        "storycraftr-test",
        "OPENROUTER_API_KEY",
        token,
    )
    assert os.environ["OPENROUTER_API_KEY"] == token


def test_store_local_credential_falls_back_when_keyring_package_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(credentials, "keyring", None)

    with mock.patch("pathlib.Path.home", return_value=tmp_path):
        credentials.store_local_credential(
            "OPENAI_API_KEY",
            "abc123",  # nosec B105  # pragma: allowlist secret
        )

    legacy_file = tmp_path / ".storycraftr" / "openai_api_key.txt"
    expected_token = "abc123"  # nosec B105  # pragma: allowlist secret
    assert legacy_file.read_text(encoding="utf-8") == expected_token
    assert os.environ["OPENAI_API_KEY"] == expected_token


def test_store_local_credential_falls_back_when_keyring_backend_unavailable(
    monkeypatch, tmp_path
):
    class FakeNoKeyringError(Exception):
        pass

    fake_keyring = mock.Mock()
    fake_keyring.set_password.side_effect = FakeNoKeyringError("no backend")
    monkeypatch.setattr(credentials, "keyring", fake_keyring)
    monkeypatch.setattr(credentials, "NoKeyringError", FakeNoKeyringError)
    token = "or-backend-fallback-token"  # nosec B105  # pragma: allowlist secret

    with mock.patch("pathlib.Path.home", return_value=tmp_path):
        credentials.store_local_credential("OPENROUTER_API_KEY", token)

    legacy_file = tmp_path / ".storycraftr" / "openrouter_api_key.txt"
    assert legacy_file.read_text(encoding="utf-8") == token
    assert os.environ["OPENROUTER_API_KEY"] == token


def test_load_local_credentials_stops_keyring_reads_after_no_backend(monkeypatch):
    class FakeNoKeyringError(Exception):
        pass

    fake_keyring = mock.Mock()
    fake_keyring.get_password.side_effect = FakeNoKeyringError("no backend")
    monkeypatch.setattr(credentials, "keyring", fake_keyring)
    monkeypatch.setattr(credentials, "NoKeyringError", FakeNoKeyringError)

    credentials.load_local_credentials()

    assert fake_keyring.get_password.call_count == 1
