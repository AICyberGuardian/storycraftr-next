from __future__ import annotations

import glob
import os
import shutil
from pathlib import Path
from typing import Callable, Type

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich.console import Console

from storycraftr.utils.core import BookConfig
from storycraftr.utils.paths import resolve_project_paths
from storycraftr.utils.project_lock import project_write_lock
from storycraftr.vectorstores import build_chroma_store

console = Console()


def resolve_persist_dir(vector_store: object, fallback_dir: Path) -> Path:
    persist_dir_str = getattr(vector_store, "_persist_directory", str(fallback_dir))
    return Path(persist_dir_str)


def force_rebuild_vector_store(
    *,
    book_path: str,
    config: BookConfig,
    embeddings: object,
    vector_store: object,
    fallback_dir: Path,
    build_store: Callable[[str, object, BookConfig], object] | None = None,
    remove_tree: Callable[[Path, bool], None] | None = None,
) -> tuple[object, Path]:
    if build_store is None:

        def _default_build_store(
            path: str, embedder: object, cfg: BookConfig
        ) -> object:
            return build_chroma_store(path, embedder, config=cfg)

        build_store = _default_build_store
    if remove_tree is None:

        def _default_remove_tree(path: Path, ignore_errors: bool) -> None:
            shutil.rmtree(path, ignore_errors=ignore_errors)

        remove_tree = _default_remove_tree

    with project_write_lock(book_path, config=config):
        reset_succeeded = False
        try:
            client = getattr(vector_store, "_client", None)
            if client is not None and hasattr(client, "reset"):
                client.reset()
                reset_succeeded = True
        except Exception:
            reset_succeeded = False

        persist_dir = resolve_persist_dir(vector_store, fallback_dir)
        if not reset_succeeded:
            remove_tree(persist_dir, True)

        rebuilt_store = build_store(book_path, embeddings, config)
        return rebuilt_store, resolve_persist_dir(rebuilt_store, fallback_dir)


def needs_refresh(*, persist_dir: Path, force: bool) -> bool:
    try:
        return force or not persist_dir.exists() or not any(persist_dir.iterdir())
    except OSError:
        return True


def load_markdown_documents(
    book_path: str,
    config: BookConfig | None = None,
) -> list[Document]:
    """
    Load Markdown files from the project for indexing.
    """

    patterns = [
        os.path.join(book_path, "**", "*.md"),
    ]
    book_path_obj = Path(book_path)
    vector_store_dir = resolve_project_paths(book_path, config=config).vector_store_root
    vector_store_dir_resolved = vector_store_dir.resolve()
    documents: list[Document] = []

    for pattern in patterns:
        for file_path_str in glob.iglob(pattern, recursive=True):
            file_path = Path(file_path_str)
            if not file_path.is_file():
                continue
            try:
                resolved_file = file_path.resolve()
                if vector_store_dir_resolved in resolved_file.parents:
                    continue
            except OSError:
                if str(vector_store_dir) in file_path.as_posix():
                    continue
            try:
                content = file_path.read_text(encoding="utf-8")
                if content.count("\n") < 3:
                    continue

                relative = str(file_path.relative_to(book_path_obj))
                documents.append(
                    Document(
                        page_content=content,
                        metadata={"source": relative},
                    )
                )
            except (UnicodeDecodeError, FileNotFoundError):
                console.print(
                    f"[yellow]Skipping unreadable file for embeddings: {file_path}[/yellow]"
                )

    return documents


def dedupe_documents(documents: list[Document]) -> list[Document]:
    """
    Keep first-occurrence ordering while removing identical content/source duplicates.
    """

    deduped: list[Document] = []
    seen: set[tuple[str, str]] = set()
    for doc in documents:
        source = str(doc.metadata.get("source", ""))
        fingerprint = (source, doc.page_content)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(doc)
    return deduped


def populate_vector_store_if_needed(
    *,
    book_path: str,
    config: BookConfig,
    vector_store: object,
    persist_dir: Path,
    force: bool,
    load_documents: Callable[[str, BookConfig | None], list[Document]],
    splitter_cls: Type[RecursiveCharacterTextSplitter] = RecursiveCharacterTextSplitter,
) -> None:
    if not needs_refresh(persist_dir=persist_dir, force=force):
        return

    with project_write_lock(book_path, config=config):
        if not needs_refresh(persist_dir=persist_dir, force=force):
            return

        documents = dedupe_documents(load_documents(book_path, config))
        if not documents:
            raise RuntimeError(
                f"No Markdown documents available to index for project {book_path}."
            )

        splitter = splitter_cls(chunk_size=1000, chunk_overlap=150)
        chunks = splitter.split_documents(documents)
        try:
            vector_store.add_documents(chunks)
        except Exception as exc:
            raise RuntimeError(f"Failed to populate vector store: {exc}") from exc
