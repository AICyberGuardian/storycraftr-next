from __future__ import annotations

from pathlib import Path
from typing import Optional
import shutil

from langchain_chroma import Chroma
from chromadb import PersistentClient
from chromadb.config import Settings

from storycraftr.utils.paths import resolve_project_paths


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

    store_path.mkdir(parents=True, exist_ok=True)

    settings = Settings(anonymized_telemetry=False, allow_reset=True)

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
