from __future__ import annotations

from pathlib import Path
from typing import Optional
import shutil
from uuid import uuid4

from langchain_chroma import Chroma
from chromadb import PersistentClient
from chromadb.config import Settings

from storycraftr.utils.paths import resolve_project_paths
from storycraftr.utils.project_lock import project_write_lock


def build_chroma_store(
    project_path: str,
    embedding_function,
    collection_name: str = "storycraftr",
    persist_subdir: Optional[str] = None,
    config: object | None = None,
    metadata: Optional[dict] = None,
) -> Chroma:
    """
    Create (or load) a persistent Chroma collection rooted inside the project directory.
    """

    project_paths = resolve_project_paths(project_path, config=config)
    if persist_subdir:
        candidate = Path(persist_subdir)
        store_path = (
            candidate if candidate.is_absolute() else project_paths.root / candidate
        )
    else:
        store_path = project_paths.vector_store_root

    settings = Settings(anonymized_telemetry=False, allow_reset=True)

    with project_write_lock(project_path, config=config):
        store_path.mkdir(parents=True, exist_ok=True)
        try:
            client = PersistentClient(path=str(store_path), settings=settings)
            store = Chroma(
                client=client,
                collection_name=collection_name,
                embedding_function=embedding_function,
                collection_metadata=metadata,
            )
            setattr(store, "_persist_directory", str(store_path))
            return store
        except Exception as exc:
            shutil.rmtree(store_path, ignore_errors=True)
            raise RuntimeError(
                f"Failed to initialise Chroma vector store at {store_path}: {exc}"
            ) from exc


class SceneMemoryStore:
    """Chroma-backed scene memory used for short-range draft continuity."""

    def __init__(self, store: Chroma):
        self._store = store

    @classmethod
    def from_project(
        cls,
        project_path: str,
        embedding_function,
        *,
        config: object | None = None,
        persist_subdir: Optional[str] = None,
    ) -> "SceneMemoryStore":
        store = build_chroma_store(
            project_path=project_path,
            embedding_function=embedding_function,
            collection_name="scene_memory",
            persist_subdir=persist_subdir,
            config=config,
            metadata={"purpose": "scene_memory"},
        )
        return cls(store)

    def store_scene_text(
        self,
        chapter_number: int,
        scene_number: int,
        stage: str,
        text: str,
    ) -> None:
        cleaned = str(text).strip()
        if not cleaned:
            return

        metadata = {
            "chapter_number": int(chapter_number),
            "scene_number": int(scene_number),
            "stage": str(stage),
        }
        self._store.add_texts(
            texts=[cleaned],
            metadatas=[metadata],
            ids=[str(uuid4())],
        )

    def fetch_recent_context(
        self,
        chapter_number: int,
        scene_number: int,
        directive: object,
        top_k: int = 3,
    ) -> str:
        query = " ".join(
            [
                str(getattr(directive, "goal", "")).strip(),
                str(getattr(directive, "conflict", "")).strip(),
                str(getattr(directive, "outcome", "")).strip(),
            ]
        ).strip()
        if not query:
            query = f"chapter {chapter_number} scene {scene_number}"

        docs = self._store.similarity_search(query, k=max(1, int(top_k)))
        lines: list[str] = []
        for doc in docs:
            metadata = doc.metadata or {}
            doc_chapter = int(metadata.get("chapter_number", 0) or 0)
            doc_scene = int(metadata.get("scene_number", 0) or 0)
            if doc_chapter > chapter_number:
                continue
            if doc_chapter == chapter_number and doc_scene >= scene_number:
                continue
            stage = str(metadata.get("stage", "scene"))
            snippet = str(doc.page_content).strip().replace("\n", " ")
            if not snippet:
                continue
            lines.append(
                f"[chapter {doc_chapter} scene {doc_scene} {stage}] {snippet[:260]}"
            )

        return "\n".join(lines[: max(1, int(top_k))])

    def purge_chapter(self, chapter_number: int) -> None:
        self._store.delete(where={"chapter_number": int(chapter_number)})
