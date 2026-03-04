from types import SimpleNamespace

from storycraftr.agent import agents


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
