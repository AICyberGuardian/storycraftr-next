from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from storycraftr.graph.assistant_graph import build_assistant_graph


def test_build_assistant_graph_requires_retriever():
    assistant = SimpleNamespace(retriever=None, llm=RunnableLambda(lambda _: "ok"))

    with pytest.raises(RuntimeError, match="retriever"):
        build_assistant_graph(assistant)


def test_graph_invokes_retriever_and_assembles_prompt_context():
    docs = [
        Document(
            page_content="Chapter context paragraph.",
            metadata={"source": "chapters/chapter_1.md"},
        )
    ]
    retriever = Mock()
    retriever.invoke.return_value = docs
    captured = {}

    def fake_llm(prompt_value):
        messages = prompt_value.to_messages()
        captured["system"] = messages[0].content
        captured["question"] = messages[1].content
        return "draft answer"

    assistant = SimpleNamespace(
        retriever=retriever,
        llm=RunnableLambda(fake_llm),
        system_prompt="You are the writing assistant.",
    )
    graph = build_assistant_graph(assistant)

    result = graph.invoke({"question": "Summarize chapter one"})

    retriever.invoke.assert_called_once_with("Summarize chapter one")
    assert result["answer"] == "draft answer"
    assert result["documents"] == docs
    assert "Context:" in captured["system"]
    assert "Source: chapters/chapter_1.md" in captured["system"]
    assert "Chapter context paragraph." in captured["system"]
    assert captured["question"] == "Summarize chapter one"


def test_graph_uses_supplied_documents_without_retriever_call():
    provided_docs = [
        Document(
            page_content="Provided context fragment.",
            metadata={"source": "outline/general-outline.md"},
        )
    ]
    retriever = Mock()
    captured = {}

    def fake_llm(prompt_value):
        messages = prompt_value.to_messages()
        captured["system"] = messages[0].content
        captured["question"] = messages[1].content
        return "provided-doc answer"

    assistant = SimpleNamespace(
        retriever=retriever,
        llm=RunnableLambda(fake_llm),
        system_prompt="System prompt base",
    )
    graph = build_assistant_graph(assistant)

    result = graph.invoke({"question": "Refine this", "documents": provided_docs})

    retriever.invoke.assert_not_called()
    assert result["answer"] == "provided-doc answer"
    assert result["documents"] == provided_docs
    assert "Source: outline/general-outline.md" in captured["system"]
    assert "Provided context fragment." in captured["system"]
    assert captured["question"] == "Refine this"


def test_graph_accepts_plain_string_input():
    retriever = Mock()
    retriever.invoke.return_value = []
    assistant = SimpleNamespace(
        retriever=retriever,
        llm=RunnableLambda(lambda prompt_value: "string-input answer"),
        system_prompt="System prompt base",
    )
    graph = build_assistant_graph(assistant)

    result = graph.invoke("Help me brainstorm")

    retriever.invoke.assert_called_once_with("Help me brainstorm")
    assert result["answer"] == "string-input answer"
    assert result["documents"] == []
