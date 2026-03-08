from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from storycraftr.utils.paths import resolve_project_paths

try:
    from mem0 import Memory as _Mem0Memory
except Exception:  # pragma: no cover - optional dependency guard
    _Mem0Memory = None


@dataclass(frozen=True)
class MemoryContextItem:
    """One memory hit prepared for prompt context injection."""

    source: str
    text: str


class NarrativeMemoryManager:
    """Optional Mem0-backed narrative memory adapter.

    The manager is fail-closed and non-fatal: if Mem0 is unavailable or errors,
    all methods degrade to no-op behavior so existing generation flows continue.
    """

    def __init__(self, *, book_path: str, config: Any | None = None) -> None:
        self.book_path = str(Path(book_path).resolve())
        self.story_id = Path(self.book_path).name or "storycraftr-project"
        project_paths = resolve_project_paths(self.book_path, config)
        self.storage_path = project_paths.internal_state_root / "memory"
        self._config = config
        self._memory: Any | None = None
        self._disabled_reason: str | None = None

    def configure(self, config: Any | None) -> None:
        """Rebind config and reset Mem0 client so path overrides are respected."""

        self._config = config
        project_paths = resolve_project_paths(self.book_path, config)
        self.storage_path = project_paths.internal_state_root / "memory"
        self._memory = None
        self._disabled_reason = None

    @property
    def is_enabled(self) -> bool:
        """Return True when Mem0 is usable in this runtime."""

        return self._ensure_client() is not None

    @property
    def disabled_reason(self) -> str | None:
        """Explain why Mem0 integration is disabled for this runtime."""

        if self._disabled_reason is not None:
            return self._disabled_reason
        if self.is_enabled:
            return None
        return self._disabled_reason

    def remember_turn(
        self,
        *,
        user_prompt: str,
        assistant_response: str,
        chapter: int | None,
        scene: str,
    ) -> bool:
        """Store a turn as long-term memory. Returns True when persisted."""

        memory = self._ensure_client()
        if memory is None:
            return False

        prompt_text = " ".join(user_prompt.split()).strip()
        response_text = " ".join(assistant_response.split()).strip()
        if not prompt_text and not response_text:
            return False

        messages: list[dict[str, str]] = []
        if prompt_text:
            messages.append({"role": "user", "content": prompt_text})
        if response_text:
            messages.append({"role": "assistant", "content": response_text})

        metadata = {
            "category": "narrative_turn",
            "chapter": chapter,
            "scene": scene,
        }
        try:
            memory.add(
                messages,
                user_id=self.story_id,
                metadata=metadata,
                enable_graph=True,
            )
        except TypeError:
            # Compatibility fallback for Mem0 variants that do not expose
            # the enable_graph kwarg in local OSS mode.
            memory.add(
                messages,
                user_id=self.story_id,
                metadata=metadata,
            )
        except Exception:
            return False
        return True

    def get_context_items(
        self,
        *,
        chapter: int | None,
        active_scene: str | None = None,
        active_arc: str | None = None,
        max_items: int = 6,
        query: str | None = None,
    ) -> list[MemoryContextItem]:
        """Retrieve compact memory context lines for prompt assembly.

        When query is provided, uses it for primary semantic retrieval before
        falling back to chapter/scene/arc continuity and generic intent/event
        queries for broader coverage.
        """

        memory = self._ensure_client()
        if memory is None:
            return []

        chapter_hint = chapter if chapter is not None else 0
        scene_hint = " ".join((active_scene or "").split()).strip()
        arc_hint = " ".join((active_arc or "").split()).strip()

        # Build weighted query set: prompt relevance first, then continuity
        # signals (recent chapter + scene/arc), then broad intent/event recall.
        queries: list[tuple[str, str, dict[str, Any]]] = []
        if query and query.strip():
            queries.append(("relevant", query.strip(), {"category": "narrative_turn"}))
        if chapter is not None:
            queries.append(
                (
                    "recent",
                    f"Recent chapter {chapter} developments and unresolved continuity details",
                    {"category": "narrative_turn", "chapter": chapter},
                )
            )
            if chapter > 1:
                queries.append(
                    (
                        "recent",
                        f"Carry-over continuity from chapter {chapter - 1}",
                        {"category": "narrative_turn", "chapter": chapter - 1},
                    )
                )
        if scene_hint:
            queries.append(
                (
                    "scene",
                    f"Scene continuity cues for '{scene_hint}'",
                    {"category": "narrative_turn"},
                )
            )
        if arc_hint:
            queries.append(
                (
                    "arc",
                    f"Arc-level constraints and unresolved beats for '{arc_hint}'",
                    {"category": "narrative_turn"},
                )
            )
        queries.extend(
            [
                (
                    "character_state",
                    "Current character states, motivations, and interpersonal tension",
                    {"category": "narrative_turn"},
                ),
                (
                    "plot_thread",
                    f"Key unresolved plot threads near chapter {chapter_hint}",
                    {"category": "narrative_turn"},
                ),
                (
                    "intent",
                    "Current character goals and motivations",
                    {"category": "narrative_turn"},
                ),
                (
                    "events",
                    f"Key unresolved events and threads near chapter {chapter_hint}",
                    {"category": "narrative_turn"},
                ),
            ]
        )

        items: list[MemoryContextItem] = []
        seen: set[str] = set()

        # Front-loaded weighted allocation: earlier (higher-priority) queries
        # can return up to 3 hits while preserving at least one slot per
        # remaining query.
        for index, (source, query_text, filters) in enumerate(queries):
            remaining_slots = max_items - len(items)
            if remaining_slots <= 0:
                return items
            remaining_queries = len(queries) - index
            per_query_limit = min(3, max(1, remaining_slots - (remaining_queries - 1)))
            for hit in self._search(
                query=query_text,
                limit=per_query_limit,
                filters=filters,
            ):
                normalized = " ".join(hit.split())
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                items.append(MemoryContextItem(source=source, text=normalized))
                if len(items) >= max_items:
                    return items

        return items

    def _ensure_client(self) -> Any | None:
        if self._memory is not None:
            return self._memory
        if self._disabled_reason is not None:
            return None
        if not _env_flag_enabled("STORYCRAFTR_MEM0_ENABLED", default=True):
            self._disabled_reason = "disabled by STORYCRAFTR_MEM0_ENABLED"
            return None
        if _Mem0Memory is None:
            self._disabled_reason = "mem0 package is not installed"
            return None

        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            cfg = self._build_mem0_config()
            factory = getattr(_Mem0Memory, "from_config", None)
            if callable(factory):
                self._memory = factory(cfg)
            else:
                self._memory = _Mem0Memory(config=cfg)
            return self._memory
        except Exception as exc:  # pragma: no cover - runtime fallback path
            self._disabled_reason = str(exc)
            return None

    def _build_mem0_config(self) -> dict[str, Any]:
        """Build provider-aware Mem0 config for local/OpenRouter/OpenAI modes."""

        provider = str(getattr(self._config, "llm_provider", "") or "").strip().lower()
        forced = str(os.getenv("STORYCRAFTR_MEM0_FORCE_PROVIDER", "")).strip().lower()
        if forced in {"openai", "openrouter", "ollama"}:
            provider = forced
        elif _env_flag_enabled("STORYCRAFTR_MEM0_FORCE_OPENROUTER", default=False):
            provider = "openrouter"
        model = str(getattr(self._config, "llm_model", "") or "").strip()

        cfg: dict[str, Any] = {
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": f"{self.story_id}-memory",
                    "path": str(self.storage_path),
                },
            }
        }

        if provider == "ollama":
            ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            cfg["llm"] = {
                "provider": "ollama",
                "config": {
                    "model": model
                    or os.getenv("STORYCRAFTR_MEM0_OLLAMA_MODEL", "llama3.1:8b"),
                    "ollama_base_url": ollama_base,
                },
            }
            cfg["embedder"] = {
                "provider": "ollama",
                "config": {
                    "model": os.getenv(
                        "STORYCRAFTR_MEM0_OLLAMA_EMBED_MODEL", "nomic-embed-text"
                    ),
                },
            }
            return cfg

        if provider == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
            cfg["llm"] = {
                # Mem0 routes OpenRouter through its openai-compatible client.
                "provider": "openai",
                "config": {
                    "model": model
                    or os.getenv(
                        "STORYCRAFTR_MEM0_OPENROUTER_MODEL", "openrouter/auto"
                    ),
                    "openrouter_base_url": "https://openrouter.ai/api/v1",
                    "site_url": os.getenv(
                        "STORYCRAFTR_HTTP_REFERER", "https://storycraftr.app"
                    ),
                    "app_name": os.getenv("STORYCRAFTR_APP_NAME", "StoryCraftr"),
                    "temperature": 0.1,
                },
            }
            return cfg

        # Default fallback for non-OpenRouter cloud providers.
        cfg["llm"] = {
            "provider": "openai",
            "config": {
                "model": model or "gpt-4o-mini",
                "temperature": 0.1,
            },
        }
        return cfg

    def search_memories(
        self,
        *,
        query: str,
        limit: int = 10,
        chapter: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search memory and return normalized rows for CLI/TUI diagnostics."""

        cleaned_query = " ".join(query.split()).strip()
        if not cleaned_query:
            return []

        filters = {"category": "narrative_turn"}
        if chapter is not None:
            filters["chapter"] = chapter

        hits = self._search(
            query=cleaned_query,
            limit=max(1, limit),
            filters=filters,
        )
        return [{"memory": hit} for hit in hits]

    def get_runtime_diagnostics(self) -> dict[str, Any]:
        """Return stable diagnostics about current memory runtime state."""

        enabled = self.is_enabled
        provider = self._effective_provider()
        return {
            "enabled": enabled,
            "reason": self.disabled_reason,
            "provider": provider,
            "story_id": self.story_id,
            "storage_path": str(self.storage_path),
        }

    def _effective_provider(self) -> str:
        provider = str(getattr(self._config, "llm_provider", "") or "").strip().lower()
        forced = str(os.getenv("STORYCRAFTR_MEM0_FORCE_PROVIDER", "")).strip().lower()
        if forced in {"openai", "openrouter", "ollama"}:
            return forced
        if _env_flag_enabled("STORYCRAFTR_MEM0_FORCE_OPENROUTER", default=False):
            return "openrouter"
        if provider:
            return provider
        return "openai"

    def _search(
        self,
        *,
        query: str,
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[str]:
        memory = self._ensure_client()
        if memory is None:
            return []

        try:
            payload = memory.search(
                query,
                user_id=self.story_id,
                limit=max(1, limit),
                filters=filters,
                rerank=True,
            )
        except TypeError:
            payload = memory.search(
                query,
                user_id=self.story_id,
                limit=max(1, limit),
                filters=filters,
            )
        except Exception:
            return []

        raw_results: Any
        if isinstance(payload, dict):
            raw_results = payload.get("results", [])
        else:
            raw_results = payload

        hits: list[str] = []
        for item in raw_results or []:
            if isinstance(item, dict):
                text = item.get("memory") or item.get("text") or ""
            else:
                text = str(item)
            text = str(text).strip()
            if text:
                hits.append(text)
        return hits


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default
