from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

from storycraftr.agent.agents import LangChainAssistant, load_markdown_documents
from storycraftr.utils.core import BookConfig


class _FakeClient:
    def __init__(self, *, fail_reset: bool = False) -> None:
        self.reset_calls = 0
        self.fail_reset = fail_reset

    def reset(self) -> None:
        self.reset_calls += 1
        if self.fail_reset:
            raise RuntimeError("corrupted-index")


class _FakeVectorStore:
    def __init__(
        self,
        persist_dir: Path,
        *,
        fail_retriever: bool = False,
        fail_reset: bool = False,
    ) -> None:
        self._persist_directory = str(persist_dir)
        self._client = _FakeClient(fail_reset=fail_reset)
        self.added_documents: list[Document] = []
        self.retriever_kwargs: dict | None = None
        self.fail_retriever = fail_retriever

    def add_documents(self, documents: list[Document]) -> None:
        self.added_documents.extend(documents)

    def as_retriever(self, *, search_kwargs: dict):
        if self.fail_retriever:
            raise RuntimeError("retriever-corruption")
        self.retriever_kwargs = search_kwargs
        return {"retriever": "ok", "k": search_kwargs.get("k")}


def _assistant(book_path: Path, vector_store: _FakeVectorStore) -> LangChainAssistant:
    return LangChainAssistant(
        id="assistant:test",
        book_path=str(book_path),
        config=BookConfig.from_mapping(book_path=str(book_path), config_data={}),
        llm=object(),
        embeddings=object(),
        vector_store=vector_store,
        behavior="test",
    )


def test_ensure_vector_store_raises_for_empty_markdown_corpus(monkeypatch, tmp_path):
    project = tmp_path / "book"
    project.mkdir()
    store = _FakeVectorStore(project / "vector_store")
    assistant = _assistant(project, store)

    monkeypatch.setattr(
        "storycraftr.agent.agents.load_markdown_documents", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_assistant_graph", lambda _assistant: "graph"
    )

    with pytest.raises(RuntimeError, match="No Markdown documents available to index"):
        assistant.ensure_vector_store()


def test_ensure_vector_store_force_raises_for_empty_markdown_corpus(
    monkeypatch, tmp_path
):
    project = tmp_path / "book"
    project.mkdir()
    store = _FakeVectorStore(project / "vector_store")
    assistant = _assistant(project, store)

    monkeypatch.setattr(
        "storycraftr.agent.agents.load_markdown_documents", lambda *_args, **_kwargs: []
    )

    with pytest.raises(RuntimeError, match="No Markdown documents available to index"):
        assistant.ensure_vector_store(force=True)


def test_ensure_vector_store_force_rebuild_resets_and_reindexes(monkeypatch, tmp_path):
    project = tmp_path / "book"
    project.mkdir()

    initial_store = _FakeVectorStore(project / "vector_store")
    replacement_store = _FakeVectorStore(project / "vector_store")
    assistant = _assistant(project, initial_store)

    docs = [
        Document(
            page_content="line1\nline2\nline3\nline4", metadata={"source": "chapter.md"}
        )
    ]

    monkeypatch.setattr(
        "storycraftr.agent.agents.load_markdown_documents",
        lambda *_args, **_kwargs: docs,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_chroma_store",
        lambda *_args, **_kwargs: replacement_store,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_assistant_graph",
        lambda _assistant: "graph",
    )

    assistant.ensure_vector_store(force=True)

    assert initial_store._client.reset_calls == 1
    assert replacement_store.added_documents
    assert replacement_store.retriever_kwargs == {"k": 6}
    assert assistant.retriever == {"retriever": "ok", "k": 6}
    assert assistant.graph == "graph"


def test_ensure_vector_store_skips_reindex_when_store_not_empty(monkeypatch, tmp_path):
    project = tmp_path / "book"
    project.mkdir()

    persist_dir = project / "vector_store"
    persist_dir.mkdir(parents=True)
    (persist_dir / "marker.txt").write_text("indexed", encoding="utf-8")

    store = _FakeVectorStore(persist_dir)
    assistant = _assistant(project, store)

    calls = {"load_markdown_documents": 0}

    def _load_docs(*_args, **_kwargs):
        calls["load_markdown_documents"] += 1
        return [Document(page_content="x\ny\nz\nw", metadata={"source": "ignored.md"})]

    monkeypatch.setattr("storycraftr.agent.agents.load_markdown_documents", _load_docs)
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_assistant_graph", lambda _assistant: "graph"
    )

    assistant.ensure_vector_store(force=False)

    assert calls["load_markdown_documents"] == 0
    assert store.added_documents == []
    assert store.retriever_kwargs == {"k": 6}
    assert assistant.graph == "graph"


def test_ensure_vector_store_recovers_when_retriever_is_corrupted(
    monkeypatch, tmp_path
):
    project = tmp_path / "book"
    project.mkdir()

    persist_dir = project / "vector_store"
    persist_dir.mkdir(parents=True)
    (persist_dir / "marker.txt").write_text("indexed", encoding="utf-8")

    corrupted_store = _FakeVectorStore(persist_dir, fail_retriever=True)
    rebuilt_store = _FakeVectorStore(persist_dir)
    assistant = _assistant(project, corrupted_store)

    docs = [
        Document(
            page_content="line1\nline2\nline3\nline4",
            metadata={"source": "chapter.md"},
        )
    ]

    monkeypatch.setattr(
        "storycraftr.agent.agents.load_markdown_documents",
        lambda *_args, **_kwargs: docs,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_chroma_store",
        lambda *_args, **_kwargs: rebuilt_store,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_assistant_graph",
        lambda _assistant: "graph",
    )

    assistant.ensure_vector_store(force=False)

    assert assistant.vector_store is rebuilt_store
    assert rebuilt_store.added_documents
    assert assistant.retriever == {"retriever": "ok", "k": 6}


def test_ensure_vector_store_force_rebuild_falls_back_to_rmtree_on_reset_failure(
    monkeypatch, tmp_path
):
    project = tmp_path / "book"
    project.mkdir()

    initial_store = _FakeVectorStore(project / "vector_store", fail_reset=True)
    replacement_store = _FakeVectorStore(project / "vector_store")
    assistant = _assistant(project, initial_store)

    docs = [
        Document(
            page_content="line1\nline2\nline3\nline4",
            metadata={"source": "chapter.md"},
        )
    ]
    rmtree_calls: list[Path] = []

    monkeypatch.setattr(
        "storycraftr.agent.agents.load_markdown_documents",
        lambda *_args, **_kwargs: docs,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_chroma_store",
        lambda *_args, **_kwargs: replacement_store,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.shutil.rmtree",
        lambda path, ignore_errors: rmtree_calls.append(Path(path)),
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_assistant_graph",
        lambda _assistant: "graph",
    )

    assistant.ensure_vector_store(force=True)

    assert rmtree_calls
    assert replacement_store.added_documents


def test_load_markdown_documents_skips_unreadable_and_short_files(tmp_path):
    project = tmp_path / "book"
    project.mkdir()

    (project / "good.md").write_text("a\nb\nc\nd\n", encoding="utf-8")
    (project / "short.md").write_text("a\nb\nc", encoding="utf-8")
    (project / "bad.md").write_bytes(b"\xff\xfe\xff")

    docs = load_markdown_documents(str(project))

    assert len(docs) == 1
    assert docs[0].metadata["source"] == "good.md"


def test_ensure_vector_store_deduplicates_duplicate_documents(monkeypatch, tmp_path):
    project = tmp_path / "book"
    project.mkdir()

    store = _FakeVectorStore(project / "vector_store")
    assistant = _assistant(project, store)

    duplicate_docs = [
        Document(
            page_content="line1\nline2\nline3\nline4", metadata={"source": "dup.md"}
        ),
        Document(
            page_content="line1\nline2\nline3\nline4", metadata={"source": "dup.md"}
        ),
    ]

    class _NoopSplitter:
        def __init__(self, *args, **kwargs):
            pass

        def split_documents(self, documents):
            return documents

    monkeypatch.setattr(
        "storycraftr.agent.agents.load_markdown_documents",
        lambda *_args, **_kwargs: duplicate_docs,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.RecursiveCharacterTextSplitter",
        _NoopSplitter,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_assistant_graph",
        lambda _assistant: "graph",
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_chroma_store",
        lambda *_args, **_kwargs: store,
    )

    assistant.ensure_vector_store(force=True)

    assert len(store.added_documents) == 1


def test_ensure_vector_store_force_rebuild_is_idempotent(monkeypatch, tmp_path):
    project = tmp_path / "book"
    project.mkdir()

    store = _FakeVectorStore(project / "vector_store")
    assistant = _assistant(project, store)

    docs = [
        Document(
            page_content="line1\nline2\nline3\nline4",
            metadata={"source": "chapter.md"},
        )
    ]

    monkeypatch.setattr(
        "storycraftr.agent.agents.load_markdown_documents",
        lambda *_args, **_kwargs: docs,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_chroma_store",
        lambda *_args, **_kwargs: store,
    )
    monkeypatch.setattr(
        "storycraftr.agent.agents.build_assistant_graph",
        lambda _assistant: "graph",
    )

    assistant.ensure_vector_store(force=True)
    first_count = len(store.added_documents)

    assistant.ensure_vector_store(force=True)

    assert store._client.reset_calls == 2
    assert len(store.added_documents) == first_count * 2
