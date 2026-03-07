# StoryCraftr-Next Architecture Reference

## Scope

This document is the canonical architecture reference for StoryCraftr-Next.
It focuses on current, verified behavior and omits speculative roadmap content.

Current development target: `v0.16` (`0.16.0-dev`).

## System Summary

StoryCraftr-Next is a local-first writing platform with:
- Dual Python CLI entrypoints: `storycraftr` and `papercraftr`
- Textual terminal-native TUI shell (`python -m storycraftr.tui.app`)
- LangChain-based assistant orchestration
- Local Chroma vector store for retrieval-augmented generation (RAG)
- Background sub-agent execution via thread pool
- VS Code companion extension that consumes JSONL events

## Core Runtime Flow

1. CLI command is routed through `storycraftr/cli.py`.
2. Project config is loaded from `storycraftr.json` or `papercraftr.json`.
3. LLM client and embeddings are built from config.
4. Vector store/retriever are prepared.
5. Assistant graph runs retrieval + generation.
6. Output is persisted (sessions/logs/files) and events are emitted to VS Code.

## Primary Components

- `storycraftr/cli.py`: top-level command registration and dual-mode routing.
- `storycraftr/cmd/`: command handlers for story, paper, and chat flows.
- `storycraftr/agent/agents.py`: assistant lifecycle, message execution, orchestration glue.
- `storycraftr/agent/assistant_cache.py`: assistant cache key generation and lock-guarded cache helpers.
- `storycraftr/agent/vector_hydration.py`: vector-store refresh/hydration and markdown ingestion helpers.
- `storycraftr/graph/assistant_graph.py`: LCEL graph composition (`answer` + `documents`).
- `storycraftr/llm/factory.py`: provider/model/endpoint validation and chat model construction.
- `storycraftr/llm/credentials.py`: credential resolution order and keyring helper.
- `storycraftr/llm/embeddings.py`: embedding client construction.
- `storycraftr/vectorstores/chroma.py`: persistent Chroma setup.
- `storycraftr/subagents/jobs.py`: sub-agent job manager lifecycle.
- `storycraftr/tui/app.py`: Textual single-screen command center and slash-command router.
- `storycraftr/tui/openrouter_models.py`: OpenRouter free-model metadata fetch/filter helper for TUI model controls.
- `storycraftr/tui/state_engine.py`: read-only narrative state extraction/cache and prompt-prefix formatter.
- `storycraftr/utils/paths.py`: canonical runtime path resolution.
- `storycraftr/integrations/vscode.py`: JSONL event emission contract.
- `src/extension.ts`: VS Code watcher and UI integration.
- `src/event-contract.ts`: typed event parser and payload contract.
- `src/event-contract.test.ts`: regression tests for event parsing.

## Configuration Model

Project configuration lives in one of:
- `storycraftr.json`
- `papercraftr.json`

Key fields include:
- `llm_provider`, `llm_model`, `llm_endpoint`, `llm_api_key_env`
- `temperature`, `request_timeout`, `max_tokens`
- `embed_model`, `embed_device`, `embed_cache_dir`

`load_book_config()` returns a typed `BookConfig`; callsites should use explicit attributes.

## Credential Resolution Order

Credential loading order is:
1. Environment variables
2. OS keyring (`storycraftr` service by default)
3. Legacy plaintext files under user home directories (compatibility fallback)

This precedence is part of the runtime contract and should be preserved unless intentionally redesigned.

## Path and Persistence Contract

Use `resolve_project_paths(book_path, config)` from `storycraftr/utils/paths.py` instead of hardcoded internal paths.

Default logical locations:
- Internal state root: `.storycraftr`
- Sessions: `.storycraftr/sessions`
- Sub-agent data/logs: `.storycraftr/subagents/...`
- VS Code events: `.storycraftr/vscode-events.jsonl`
- Vector store: `vector_store`

## Assistant and RAG Behavior

- Assistant execution is centered on `LangChainAssistant` in `storycraftr/agent/agents.py`.
- Markdown project files are chunked and indexed for retrieval.
- Graph output shape includes generated answer text and retrieved documents.
- Provider `fake` is supported for offline/test flows.

## TUI Command Center

- The TUI is a thin UI layer over existing assistant/chat APIs and does not replace core generation logic.
- It supports slash-command UX including `/help`, `/status`, `/toggle-tree`, `/chapter <number>`, `/scene <label>`, `/session ...`, `/sub-agent ...`, `/model-list`, and `/model-change <model_id>`.
- The project tree defaults to hidden and can be shown on-demand for filesystem inspection.
- `/model-list` uses OpenRouter `/api/v1/models` metadata and filters free models by zero prompt/completion pricing.
- `/model-change` rebuilds the active TUI assistant via existing safe assistant creation paths with model override, while preserving project and retrieval context and reporting continuity limits explicitly.
- Normal user prompts are prefixed in the TUI layer with a read-only narrative state block before dispatch to existing assistant execution APIs.

## Sub-Agent System

- Roles are defined as YAML-backed models (`storycraftr/subagents/models.py`, `storage.py`, `defaults.py`).
- Jobs run via `SubAgentJobManager` (`storycraftr/subagents/jobs.py`).
- Lifecycle states include `pending`, `running`, `succeeded`, and `failed`.
- Logs are persisted for diagnostics and reproducibility.

## VS Code Integration Contract

Backend emits JSONL events and the extension watches configured/fallback event paths.
Typical event families include:
- Session events
- Chat turn/command events
- Sub-agent lifecycle and log events

Any payload or event-path contract change must be mirrored in `src/extension.ts`.
Keep `src/event-contract.ts` and `src/event-contract.test.ts` aligned with backend payload emitters.

## Testing and Validation Surface

Primary architecture-relevant tests live in:
- `tests/unit/test_llm_factory.py`
- `tests/unit/test_credentials.py`
- `tests/unit/test_core_paths.py`
- `tests/unit/test_assistant_graph.py`
- `tests/unit/test_subagent_jobs.py`
- `tests/unit/test_vscode_integration.py`
- `tests/integration/test_cli_smoke.py`

## CI and Tooling Invariants

- Dependency updates are synchronized via `make sync-deps`.
- CI uses uv + Poetry export for deterministic installs.
- Lockfile drift in CI is a failure condition.

## Canonical Reading Order

For onboarding and architecture understanding, read in this order:
1. `AGENTS.md`
2. `.github/copilot-instructions.md`
3. `docs/architecture-onboarding.md`
4. This file (deep reference)

## Out of Scope

This reference intentionally excludes speculative roadmap designs and optimization proposals that are not yet implemented.
Track future design work in dedicated plan documents under `docs/`.
