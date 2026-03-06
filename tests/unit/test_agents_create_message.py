from types import SimpleNamespace

from storycraftr.agent import agents
from storycraftr.utils.core import BookConfig


class _DummyGraph:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return self.result


def test_invoke_assistant_graph_normalizes_dict_payload():
    docs = [{"source": "chapter-1.md"}]
    graph = _DummyGraph({"answer": "hello", "documents": docs})
    assistant = SimpleNamespace(graph=graph)

    response, returned_docs = agents._invoke_assistant_graph(assistant, "prompt-hash")

    assert response == "hello"
    assert returned_docs == docs
    assert graph.calls == [{"question": "prompt-hash"}]


def test_create_message_separates_prompt_build_from_graph_invocation(
    monkeypatch, tmp_path
):
    book_path = str(tmp_path / "book")
    thread = agents.ConversationThread(id="thread-1", book_path=book_path)
    assistant = SimpleNamespace(
        config=SimpleNamespace(
            multiple_answer=False,
            reference_author="",
            primary_language="en",
        ),
        graph=object(),
        last_documents=[],
    )
    call_order = []

    monkeypatch.setattr(agents, "_resolve_thread", lambda *args, **kwargs: thread)

    def fake_prompt_builder(book_path, config, content):
        call_order.append(("prompt", content))
        return "hashed-prompt"

    def fake_graph_invoke(assistant_obj, prompt_with_hash):
        call_order.append(("invoke", prompt_with_hash))
        return "hello END_OF_RESPONSE", [{"source": "outline/chapter-synopsis.md"}]

    monkeypatch.setattr(agents, "_build_prompt_with_metadata", fake_prompt_builder)
    monkeypatch.setattr(agents, "_invoke_assistant_graph", fake_graph_invoke)

    response = agents.create_message(
        book_path=book_path,
        thread_id="thread-1",
        content="Summarize chapter",
        assistant=assistant,
    )

    assert response == "hello"
    assert call_order == [
        ("prompt", "Summarize chapter"),
        ("invoke", "hashed-prompt"),
    ]
    assert assistant.last_documents == [{"source": "outline/chapter-synopsis.md"}]
    assert len(thread.messages) == 2


def test_create_or_get_assistant_cache_separates_model_overrides(monkeypatch, tmp_path):
    project = tmp_path / "book"
    project.mkdir()

    with agents._ASSISTANT_CACHE_LOCK:
        agents._ASSISTANT_CACHE.clear()

    def fake_load_config(book_path, model_override=None):
        return BookConfig.from_mapping(
            book_path=book_path,
            config_data={
                "llm_provider": "openai",
                "llm_model": model_override or "gpt-4o",
                "primary_language": "en",
                "reference_author": "",
                "embed_model": "test-embed",
                "embed_device": "cpu",
                "embed_cache_dir": "",
            },
        )

    monkeypatch.setattr(agents, "load_book_config", fake_load_config)
    monkeypatch.setattr(agents, "build_chat_model", lambda settings: settings.model)
    monkeypatch.setattr(agents, "build_embedding_model", lambda _: object())
    monkeypatch.setattr(
        agents, "build_chroma_store", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        agents.LangChainAssistant,
        "ensure_vector_store",
        lambda self, force=False: None,
    )

    default_assistant = agents.create_or_get_assistant(
        str(project), model_override=None
    )
    override_assistant = agents.create_or_get_assistant(
        str(project), model_override="openrouter/deepseek"
    )

    assert default_assistant is not override_assistant
    assert default_assistant.llm == "gpt-4o"
    assert override_assistant.llm == "openrouter/deepseek"


def test_create_or_get_assistant_cache_normalizes_model_override(monkeypatch, tmp_path):
    project = tmp_path / "book"
    project.mkdir()

    with agents._ASSISTANT_CACHE_LOCK:
        agents._ASSISTANT_CACHE.clear()

    monkeypatch.setattr(
        agents,
        "load_book_config",
        lambda book_path, model_override=None: BookConfig.from_mapping(
            book_path=book_path,
            config_data={
                "llm_provider": "openai",
                "llm_model": model_override or "gpt-4o",
                "primary_language": "en",
                "reference_author": "",
                "embed_model": "test-embed",
                "embed_device": "cpu",
                "embed_cache_dir": "",
            },
        ),
    )
    monkeypatch.setattr(agents, "build_chat_model", lambda settings: settings.model)
    monkeypatch.setattr(agents, "build_embedding_model", lambda _: object())
    monkeypatch.setattr(
        agents, "build_chroma_store", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        agents.LangChainAssistant,
        "ensure_vector_store",
        lambda self, force=False: None,
    )

    first = agents.create_or_get_assistant(str(project), model_override="custom/model")
    second = agents.create_or_get_assistant(
        str(project), model_override="  custom/model  "
    )

    assert first is second
