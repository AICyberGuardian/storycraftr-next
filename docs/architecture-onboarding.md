# Architecture Onboarding (Junior Dev)

This file is the shortest trustworthy path to understand how StoryCraftr is built from scratch.

Use this with:
- `AGENTS.md` (workflow + conventions)
- `.github/copilot-instructions.md` (deep technical contract)

## Why This Exists

Some architecture documents in `docs/` are either very long or contain mixed audit-style commentary.
This file keeps only high-signal architecture facts and links to canonical sources.

## System In One View

StoryCraftr is a dual-mode Python CLI (`storycraftr` and `papercraftr`) plus a VS Code extension.

Main runtime flow:
1. CLI entrypoint routes mode and command.
2. Config is loaded from `storycraftr.json` or `papercraftr.json`.
3. LLM and embeddings are built from config.
4. Chroma vector store is created/used for retrieval.
5. LangChain graph executes retrieval + generation.
6. Chat/session/sub-agent events are emitted to JSONL for VS Code.

Config note:
`load_book_config()` returns a typed `BookConfig`; runtime code should use explicit attributes.

## Core Code Map

- `storycraftr/cli.py`: dual-mode command routing and bootstrap.
- `storycraftr/cmd/`: command handlers for story/paper/chat.
- `storycraftr/agent/agents.py`: assistant lifecycle, message creation, orchestration glue.
- `storycraftr/agent/assistant_cache.py`: assistant cache keying and lock-guarded cache state.
- `storycraftr/agent/vector_hydration.py`: vector-store refresh/hydration and markdown ingestion helpers.
- `storycraftr/graph/assistant_graph.py`: LCEL retrieval + answer graph.
- `storycraftr/llm/factory.py`: provider selection and validation.
- `storycraftr/llm/credentials.py`: env -> keyring -> legacy fallback credential lookup.
- `storycraftr/llm/embeddings.py`: embedding model creation.
- `storycraftr/vectorstores/chroma.py`: persistent Chroma setup.
- `storycraftr/utils/paths.py`: canonical runtime path resolver.
- `storycraftr/subagents/jobs.py`: background role-based job execution.
- `storycraftr/integrations/vscode.py`: JSONL event emission.
- `storycraftr/tui/app.py`: Textual terminal command center with slash-command UX and model controls.
- `storycraftr/tui/canon.py`: chapter-scoped canon ledger helpers for writer-approved constraints.
- `storycraftr/tui/canon_extract.py`: conservative canon-candidate extraction for hybrid review.
- `storycraftr/tui/canon_verify.py`: fail-closed canon candidate verification for duplicate/conflict checks in autopilot commits.
- `storycraftr/tui/context_builder.py`: scene-scoped prompt assembly with bounded constraints/context sections.
- `storycraftr/tui/state_engine.py`: read-only narrative state extraction and scoped-context orchestration.
- `storycraftr/agent/story/scene_planner.py`: deterministic scene Goal/Conflict/Outcome planning helper.
- `src/extension.ts`: VS Code event stream watcher and UI integration.
- `src/event-contract.ts`: typed event parser and contract for extension event payloads.
- `src/event-contract.test.ts`: event-contract regression tests.

## Runtime Files and State

At project level:
- `storycraftr.json` or `papercraftr.json`: runtime configuration.
- Markdown content (`chapters/`, `outline/`, `worldbuilding/`, etc.): user source corpus.
- `vector_store/`: Chroma persistence.

Internal state (resolved via `resolve_project_paths`):
- `.storycraftr/subagents/`
- `.storycraftr/sessions/`
   - `session.json` stores lightweight runtime metadata (for example, TUI execution mode).
- `.storycraftr/vscode-events.jsonl`

TUI autonomy note:
- `/mode` controls manual/hybrid/autopilot execution behavior.
- `/autopilot` only runs when mode is `autopilot` and performs bounded steps.
- Canon commits in autopilot flow are verified against accepted chapter facts and skip duplicate/conflicting candidates.

Do not hardcode these paths; use `storycraftr/utils/paths.py`.

## Build and CI Mental Model

Local dev:
- Python: `poetry install`, `poetry run pytest`
- Extension: `npm install`, `npm run compile`

CI model:
- Uses uv + Poetry export (`poetry export` -> `uv pip install`) for deterministic installs.
- Lockfile drift is treated as a failure condition.

Canonical references:
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `.github/workflows/pytest.yml`
- `.github/workflows/pre-commit.yml`
- `docs/CHANGE_IMPACT_CHECKLIST.md` (lock-coverage matrix + impact checklist)

## What Is Canonical vs Informational

Canonical (treat as source of truth):
- `AGENTS.md`
- `.github/copilot-instructions.md`
- Current code under `storycraftr/` and `src/`

Informational (helpful but verify):
- `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`

## 60-Minute Learning Path

1. Read `AGENTS.md` for repo rules and operating model.
2. Read `.github/copilot-instructions.md` for architecture contracts and pitfalls.
3. Read this file, then trace one command end-to-end:
   - Start at `storycraftr/cli.py`
   - Follow into `storycraftr/cmd/chat.py`
   - Follow into `storycraftr/agent/agents.py`
   - Follow into `storycraftr/graph/assistant_graph.py`
4. Validate understanding by running:
   - `poetry run storycraftr --help`
   - `poetry run pytest`
