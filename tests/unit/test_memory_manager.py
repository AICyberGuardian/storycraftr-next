from __future__ import annotations

from storycraftr.agent import memory_manager as mm
from storycraftr.agent.memory_manager import NarrativeMemoryManager


def _config_stub(*, book_path: str, llm_provider: str, llm_model: str):
    return type(
        "Cfg",
        (),
        {
            "book_path": book_path,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "internal_state_dir": "",
            "subagents_dir": "",
            "subagent_logs_dir": "",
            "sessions_dir": "",
            "vector_store_dir": "",
            "vscode_events_file": "",
        },
    )()


class _FakeMemoryClient:
    def __init__(self) -> None:
        self.add_calls: list[dict] = []
        self.search_calls: list[dict] = []

    def add(self, messages, user_id=None, metadata=None, enable_graph=None):
        self.add_calls.append(
            {
                "messages": messages,
                "user_id": user_id,
                "metadata": metadata,
                "enable_graph": enable_graph,
            }
        )

    def search(self, query, user_id=None, limit=100, filters=None, rerank=True):
        self.search_calls.append(
            {
                "query": query,
                "user_id": user_id,
                "limit": limit,
                "filters": filters,
                "rerank": rerank,
            }
        )
        return {
            "results": [
                {"memory": "Elias distrusts Mara after the bridge incident."},
                {"memory": "Mara intends to secure the archive before dawn."},
            ]
        }


class _FakeMemoryFactory:
    last_config = None

    @staticmethod
    def from_config(_config):
        _FakeMemoryFactory.last_config = _config
        return _FakeMemoryClient()


def test_memory_manager_disables_cleanly_when_mem0_missing(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(mm, "_Mem0Memory", None)

    manager = NarrativeMemoryManager(book_path=str(tmp_path))

    assert manager.is_enabled is False
    assert manager.disabled_reason == "mem0 package is not installed"
    assert manager.get_context_items(chapter=1) == []


def test_memory_manager_records_turn_and_fetches_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mm, "_Mem0Memory", _FakeMemoryFactory)

    manager = NarrativeMemoryManager(book_path=str(tmp_path))

    recorded = manager.remember_turn(
        user_prompt="Keep Elias suspicious of Mara.",
        assistant_response="Elias watches Mara hide the keycard.",
        chapter=3,
        scene="Bridge",
    )

    assert recorded is True
    assert manager.is_enabled is True

    items = manager.get_context_items(chapter=3, max_items=2)

    assert len(items) == 2
    assert items[0].text
    assert {item.source for item in items} <= {"intent", "events"}


def test_memory_manager_builds_openrouter_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mm, "_Mem0Memory", _FakeMemoryFactory)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("STORYCRAFTR_APP_NAME", "StoryCraftr-Test")

    config = _config_stub(
        book_path=str(tmp_path),
        llm_provider="openrouter",
        llm_model="anthropic/claude-3.5-sonnet",
    )

    manager = NarrativeMemoryManager(book_path=str(tmp_path), config=config)

    assert manager.is_enabled is True
    llm_cfg = _FakeMemoryFactory.last_config["llm"]
    assert llm_cfg["provider"] == "openai"
    assert llm_cfg["config"]["model"] == "anthropic/claude-3.5-sonnet"
    assert llm_cfg["config"]["openrouter_base_url"] == "https://openrouter.ai/api/v1"


def test_memory_manager_builds_ollama_local_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mm, "_Mem0Memory", _FakeMemoryFactory)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    config = _config_stub(
        book_path=str(tmp_path),
        llm_provider="ollama",
        llm_model="llama3.1:8b",
    )

    manager = NarrativeMemoryManager(book_path=str(tmp_path), config=config)

    assert manager.is_enabled is True
    cfg = _FakeMemoryFactory.last_config
    assert cfg["llm"]["provider"] == "ollama"
    assert cfg["llm"]["config"]["model"] == "llama3.1:8b"
    assert cfg["embedder"]["provider"] == "ollama"


def test_memory_manager_respects_global_disable_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mm, "_Mem0Memory", _FakeMemoryFactory)
    monkeypatch.setenv("STORYCRAFTR_MEM0_ENABLED", "false")

    manager = NarrativeMemoryManager(book_path=str(tmp_path))

    assert manager.is_enabled is False
    assert manager.disabled_reason == "disabled by STORYCRAFTR_MEM0_ENABLED"


def test_memory_manager_force_provider_overrides_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mm, "_Mem0Memory", _FakeMemoryFactory)
    monkeypatch.setenv("STORYCRAFTR_MEM0_FORCE_PROVIDER", "ollama")

    config = _config_stub(
        book_path=str(tmp_path),
        llm_provider="openrouter",
        llm_model="anthropic/claude-3.5-sonnet",
    )

    manager = NarrativeMemoryManager(book_path=str(tmp_path), config=config)

    assert manager.is_enabled is True
    cfg = _FakeMemoryFactory.last_config
    assert cfg["llm"]["provider"] == "ollama"
