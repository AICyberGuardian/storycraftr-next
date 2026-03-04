import json
from pathlib import Path

from storycraftr.chat.session import SessionManager
from storycraftr.integrations.vscode import VSCodeEventEmitter
from storycraftr.subagents.storage import ensure_storage_dirs
from storycraftr.utils.core import load_book_config
from storycraftr.utils.paths import resolve_project_paths
from storycraftr.vectorstores.chroma import build_chroma_store


def _write_config(tmp_path: Path) -> None:
    config = {
        "book_name": "Test",
        "primary_language": "en",
        "llm_provider": "fake",
        "llm_model": "offline-model",
        "internal_state_dir": ".custom-state",
        "vector_store_dir": ".custom-state/vector_store",
    }
    (tmp_path / "storycraftr.json").write_text(json.dumps(config), encoding="utf-8")


def test_runtime_paths_resolve_inside_custom_internal_state_dir(monkeypatch, tmp_path):
    _write_config(tmp_path)
    config = load_book_config(str(tmp_path))
    assert config is not None

    paths = resolve_project_paths(str(tmp_path), config=config)
    state_root = (tmp_path / ".custom-state").resolve()

    assert paths.internal_state_root == state_root

    subagents_root = ensure_storage_dirs(str(tmp_path), config=config)
    assert subagents_root == paths.subagents_root
    assert paths.subagents_logs_root.is_dir()
    assert state_root in paths.subagents_logs_root.parents

    sessions = SessionManager(str(tmp_path))
    saved_session = sessions.save("smoke", [{"role": "user", "content": "hello"}])
    assert saved_session.parent == paths.sessions_root
    assert state_root in saved_session.parents

    emitter = VSCodeEventEmitter(str(tmp_path))
    emitter.emit("ping", {"ok": True})
    assert emitter.path == paths.vscode_events_file
    assert state_root in emitter.path.parents
    assert emitter.path.read_text(encoding="utf-8").strip()

    captured = {}

    class FakeChroma:
        def __init__(
            self, client, collection_name, embedding_function, collection_metadata
        ):
            self._client = client

    def fake_persistent_client(path, settings):
        captured["path"] = path
        return object()

    monkeypatch.setattr("storycraftr.vectorstores.chroma.Chroma", FakeChroma)
    monkeypatch.setattr(
        "storycraftr.vectorstores.chroma.PersistentClient", fake_persistent_client
    )

    store = build_chroma_store(
        str(tmp_path),
        embedding_function=object(),
        config=config,
    )

    assert Path(captured["path"]).resolve() == paths.vector_store_root
    assert (
        Path(getattr(store, "_persist_directory")).resolve() == paths.vector_store_root
    )
    assert state_root in paths.vector_store_root.parents
