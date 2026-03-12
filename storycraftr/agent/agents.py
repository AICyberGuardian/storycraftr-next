from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_chroma import Chroma
from rich.console import Console
from rich.progress import Progress

from storycraftr.llm import build_chat_model, build_embedding_model
from storycraftr.prompts.story.core import FORMAT_OUTPUT
from storycraftr.graph import build_assistant_graph
from storycraftr.agent.assistant_cache import (
    _ASSISTANT_CACHE,
    _ASSISTANT_CACHE_LOCK,
    assistant_cache_key,
    get_cached_assistant,
    store_assistant_if_absent,
)
from storycraftr.agent.vector_hydration import (
    dedupe_documents,
    force_rebuild_vector_store,
    load_markdown_documents as _load_markdown_documents,
    populate_vector_store_if_needed,
    resolve_persist_dir,
)
from storycraftr.utils.core import (
    BookConfig,
    generate_prompt_with_hash,
    load_book_config,
    llm_settings_from_config,
    embedding_settings_from_config,
)
from storycraftr.utils.paths import resolve_project_paths
from storycraftr.vectorstores import build_chroma_store

console = Console()


@dataclass
class ConversationThread:
    id: str
    book_path: str
    messages: List[HumanMessage | AIMessage] = field(default_factory=list)


@dataclass
class LangChainAssistant:
    id: str
    book_path: str
    config: BookConfig
    llm: BaseChatModel
    embeddings: object
    vector_store: Optional[Chroma]
    behavior: str
    retriever: Optional[object] = None
    graph: Optional[object] = None
    last_documents: List[Document] = field(default_factory=list)
    graph: Optional[object] = None

    def ensure_vector_store(self, force: bool = False) -> None:
        """
        Ensure that the local Chroma store is populated with Markdown content.
        """

        if self.vector_store is None:
            raise RuntimeError(
                "Vector store is not initialised. Ensure embeddings are available before continuing."
            )

        project_paths = resolve_project_paths(self.book_path, config=self.config)
        persist_dir = resolve_persist_dir(
            self.vector_store, project_paths.vector_store_root
        )
        if force:
            preflight_documents = _dedupe_documents(
                load_markdown_documents(self.book_path, self.config)
            )
            if not preflight_documents:
                raise RuntimeError(
                    f"No Markdown documents available to index for project {self.book_path}."
                )
            self.vector_store, persist_dir = force_rebuild_vector_store(
                book_path=self.book_path,
                config=self.config,
                embeddings=self.embeddings,
                vector_store=self.vector_store,
                fallback_dir=project_paths.vector_store_root,
                build_store=lambda p, e, c: build_chroma_store(p, e, config=c),
                remove_tree=lambda path, ignore_errors: shutil.rmtree(
                    path, ignore_errors=ignore_errors
                ),
            )

        populate_vector_store_if_needed(
            book_path=self.book_path,
            config=self.config,
            vector_store=self.vector_store,
            persist_dir=persist_dir,
            force=force,
            load_documents=load_markdown_documents,
            splitter_cls=RecursiveCharacterTextSplitter,
        )

        try:
            self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 6})
        except Exception as exc:
            if not force:
                # Recover from corrupted persisted indexes by forcing a full rebuild once.
                self.ensure_vector_store(force=True)
                return
            raise RuntimeError(
                f"Unable to construct retriever from vector store: {exc}"
            ) from exc

        self.graph = build_assistant_graph(self)
        self.last_documents = []

    @property
    def system_prompt(self) -> str:
        format_prompt = FORMAT_OUTPUT.format(
            reference_author=self.config.reference_author,
            language=self.config.primary_language,
        )
        meta = (
            f"Project: {Path(self.book_path).name}\n"
            f"Primary language: {self.config.primary_language}\n"
        )
        return f"{self.behavior.strip()}\n\n{meta}{format_prompt}"


_THREADS: Dict[str, ConversationThread] = {}


def _assistant_cache_key(book_path: str, model_override: str | None = None) -> str:
    return assistant_cache_key(book_path, model_override)


def load_markdown_documents(
    book_path: str, config: BookConfig | None = None
) -> List[Document]:
    return _load_markdown_documents(book_path, config)


def _dedupe_documents(documents: List[Document]) -> List[Document]:
    return dedupe_documents(documents)


def create_or_get_assistant(
    book_path: str, model_override: str | None = None
) -> LangChainAssistant:
    """
    Initialize (or fetch) the LangChain-powered assistant for a project.
    """

    if not book_path:
        raise ValueError("book_path is required to create an assistant.")

    book_path = str(Path(book_path).resolve())
    normalized_override = model_override.strip() if model_override is not None else None
    cache_key = _assistant_cache_key(book_path, normalized_override)
    cached = get_cached_assistant(cache_key)
    if cached is not None:
        return cached

    config = load_book_config(book_path, model_override=normalized_override)
    if not config:
        raise RuntimeError("Unable to load project configuration.")

    behavior_path = Path(book_path) / "behaviors" / "default.txt"
    if behavior_path.exists():
        behavior_text = behavior_path.read_text(encoding="utf-8")
    else:
        behavior_text = (
            "You are the StoryCraftr creative writing assistant. "
            "Respond in markdown, keep outputs structured, and respect the requested tone."
        )

    llm_settings = llm_settings_from_config(config, model_override=normalized_override)
    embedding_settings = embedding_settings_from_config(config)

    llm = build_chat_model(llm_settings)
    embeddings = build_embedding_model(embedding_settings)
    vector_store = build_chroma_store(book_path, embeddings, config=config)

    assistant = LangChainAssistant(
        id=f"assistant:{Path(book_path).name}",
        book_path=book_path,
        config=config,
        llm=llm,
        embeddings=embeddings,
        vector_store=vector_store,
        behavior=behavior_text,
    )
    assistant.ensure_vector_store()

    return store_assistant_if_absent(cache_key, assistant)


def get_thread(book_path: str) -> ConversationThread:
    """
    Create a new in-memory conversation thread for the project.
    """

    thread_id = f"thread:{Path(book_path).name}:{uuid4().hex}"
    thread = ConversationThread(id=thread_id, book_path=book_path)
    _THREADS[thread_id] = thread
    return thread


def _resolve_thread(thread_id: str, book_path: str) -> ConversationThread:
    thread = _THREADS.get(thread_id)
    if thread is None:
        thread = ConversationThread(
            id=thread_id or f"thread:{uuid4().hex}", book_path=book_path
        )
        _THREADS[thread.id] = thread
    return thread


def _build_message_content(
    content: str,
    *,
    config: BookConfig,
    file_path: Optional[str],
    force_single_answer: bool,
) -> str:
    """
    Build the user-facing message payload, including optional file context.
    """

    composed_content = content
    if file_path and os.path.exists(file_path):
        file_text = Path(file_path).read_text(encoding="utf-8")
        composed_content = (
            f"{composed_content}\n\n"
            f"Here is the existing content to adjust:\n{file_text}"
        )

    if config.multiple_answer and not force_single_answer:
        composed_content = (
            "Divide the answer into three titled sections (Part 1, Part 2, Part 3). "
            "Conclude the final section with the token END_OF_RESPONSE. "
            f"{composed_content}"
        )

    return composed_content


def _build_prompt_with_metadata(
    book_path: str, config: BookConfig, content: str
) -> str:
    """
    Build the final prompt and persist prompt metadata for traceability.
    """

    prompt_body = FORMAT_OUTPUT.format(
        reference_author=config.reference_author,
        language=config.primary_language,
    )
    prompt_text = f"{prompt_body}\n\n{content}"
    return generate_prompt_with_hash(
        prompt_text,
        datetime.now().strftime("%B %d, %Y"),
        book_path=book_path,
    )


def _invoke_assistant_graph(
    assistant: LangChainAssistant, prompt_with_hash: str
) -> Tuple[str, List[Document]]:
    """
    Invoke the LangChain graph only and normalize its response payload.
    """

    if not assistant.graph:
        raise RuntimeError("Assistant graph is not initialised.")

    result = assistant.graph.invoke({"question": prompt_with_hash})
    if isinstance(result, dict):
        response_text = str(result.get("answer", ""))
        documents = result.get("documents") or []
        return response_text, documents

    return str(result), []


def _record_thread_turn(
    thread: ConversationThread, prompt_with_hash: str, response_text: str
) -> None:
    user_message = HumanMessage(content=prompt_with_hash)
    assistant_message = AIMessage(content=response_text)
    thread.messages.extend([user_message, assistant_message])


def _update_progress(progress: Optional[Progress], task_id) -> None:
    if progress and task_id is not None:
        try:
            progress.update(task_id, completed=1)
        except Exception as exc:
            console.print(f"[yellow]Warning: progress update failed ({exc}).[/yellow]")


def create_message(
    book_path: str,
    thread_id: str,
    content: str,
    assistant: Optional[LangChainAssistant],
    file_path: Optional[str] = None,
    progress: Optional[Progress] = None,
    task_id=None,
    force_single_answer: bool = False,
) -> str:
    """
    Generate a response from the assistant using the shared LangChain pipeline.
    """

    assistant = assistant or create_or_get_assistant(book_path)
    thread = _resolve_thread(thread_id, book_path)
    config = assistant.config

    message_content = _build_message_content(
        content,
        config=config,
        file_path=file_path,
        force_single_answer=force_single_answer,
    )
    prompt_with_hash = _build_prompt_with_metadata(book_path, config, message_content)
    response_text, documents = _invoke_assistant_graph(assistant, prompt_with_hash)

    assistant.last_documents = documents
    _record_thread_turn(thread, prompt_with_hash, response_text)
    _update_progress(progress, task_id)

    return response_text.replace("END_OF_RESPONSE", "").strip()


def update_agent_files(book_path: str, assistant: Optional[LangChainAssistant] = None):
    """
    Rebuild the embedded knowledge base for the assistant.
    """

    assistant = assistant or _ASSISTANT_CACHE.get(
        _assistant_cache_key(str(Path(book_path).resolve()), None)
    )
    if not assistant:
        assistant = create_or_get_assistant(book_path)
    assistant.ensure_vector_store(force=True)

    # Reset active threads for this project to avoid stale context.
    stale_ids = [
        thread_id
        for thread_id, thread in _THREADS.items()
        if thread.book_path == book_path
    ]
    for thread_id in stale_ids:
        _THREADS.pop(thread_id, None)


def process_chapters(
    save_to_markdown,
    book_path: str,
    prompt_template: str,
    task_description: str,
    file_suffix: str,
    **prompt_kwargs,
):
    """
    Process chapter files by generating refinements from the assistant.
    """

    chapters_dir = os.path.join(book_path, "chapters")
    outline_dir = os.path.join(book_path, "outline")
    worldbuilding_dir = os.path.join(book_path, "worldbuilding")

    for dir_path in [chapters_dir, outline_dir, worldbuilding_dir]:
        if not os.path.exists(dir_path):
            raise FileNotFoundError(f"The directory '{dir_path}' does not exist.")

    excluded_files = {"cover.md", "back-cover.md"}
    files_to_process: List[str] = []
    for dir_path in [chapters_dir, outline_dir, worldbuilding_dir]:
        with os.scandir(dir_path) as it:
            for entry in it:
                if entry.name.endswith(".md") and entry.name not in excluded_files:
                    files_to_process.append(entry.path)

    if not files_to_process:
        raise FileNotFoundError(
            "No Markdown (.md) files were found in the chapter directory."
        )

    assistant = create_or_get_assistant(book_path)

    with Progress() as progress:
        task_chapters = progress.add_task(
            f"[cyan]{task_description}",
            total=len(files_to_process),
        )
        task_llm = progress.add_task("[green]Calling language model...", total=1)

        for chapter_file in files_to_process:
            prompt = prompt_template.format(**prompt_kwargs)
            thread = get_thread(book_path)

            progress.reset(task_llm)
            refined_text = create_message(
                book_path,
                thread_id=thread.id,
                content=prompt,
                assistant=assistant,
                progress=progress,
                task_id=task_llm,
                file_path=chapter_file,
            )

            relative_path = os.path.relpath(chapter_file, book_path)
            save_to_markdown(
                book_path,
                relative_path,
                file_suffix,
                refined_text,
                progress=progress,
                task=task_chapters,
            )
            progress.update(task_chapters, advance=1)

    update_agent_files(book_path, assistant)
