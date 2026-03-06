# Copilot Coding Agent Instructions

Current development target: v0.15.x.

## Repository Invariants

- `DEP_UPDATE`: If `pyproject.toml` changes, update lock files through `make sync-deps`.
- `JS_UPDATE`: If `package.json` changes, update lock files through `make sync-deps`.
- `VER_BUMP`: If version strings change, update `pyproject.toml`, `package.json`, `package-lock.json`, and `CHANGELOG.md` in the same commit.
- `LOCK_IMMUTABLE_CI`: CI must fail if `poetry.lock` or `package-lock.json` changes during workflow execution.
- Do not run raw `poetry lock` / `npm install` as standalone AI actions for routine dependency updates; use `make sync-deps`.

## Project Overview

StoryCraftr is a dual-mode Python CLI plus a lightweight VS Code companion extension that uses LangChain-backed LLM providers to assist with writing books (**StoryCraftr**) and research papers (**PaperCraftr**). The two modes share the same codebase and are distinguished only by the entrypoint name (`storycraftr` vs `papercraftr`). Both CLIs are registered as Poetry scripts in `pyproject.toml`.

---

## Repository Layout

```
storycraftr/          # Python package (all core logic)
  agent/              # LangChain assistant, vector-store logic, story & paper agent modules
    agents.py         # LangChainAssistant dataclass, create_or_get_assistant(), create_message()
    retrieval.py      # Document retrieval helpers
    story/            # Story-specific generation: chapters, outline, worldbuilding, iterate
    paper/            # Paper-specific generation: abstract, generate_section, etc.
  chat/               # Interactive REPL: session.py, module_runner.py, commands.py, render.py
  cmd/                # Click command groups
    story/            # CLI commands for storycraftr (outline, chapters, worldbuilding, iterate, publish)
    paper/            # CLI commands for papercraftr
    chat.py           # Shared chat command
  graph/              # LangChain LCEL graph (assistant_graph.py)
  llm/                # LLM abstraction: factory.py (build_chat_model), embeddings.py, credentials.py
  prompts/            # Prompt strings for story/ and paper/ flows; permute.py for date injection
  subagents/          # Background sub-agent system: models.py, defaults.py, storage.py, jobs.py
  templates/          # Python-side LaTeX/folder templates for project scaffolding
  utils/              # core.py (BookConfig, load_book_config), cleanup.py, markdown.py, pdf.py
  vectorstores/       # chroma.py: build_chroma_store()
  cli.py              # Entrypoint: click CLI group, init command, dual-mode routing
  init.py             # init_structure_story / init_structure_paper
  state.py            # Global debug flag

src/                  # TypeScript VS Code extension (extension.ts → out/extension.js)
tests/
  test_cli.py         # CLI smoke tests
  test_markdown.py
  test_state.py
  unit/               # Focused unit tests (test_subagents.py, test_subagent_models.py, ...)
docs/                 # Markdown docs included in installed package (getting_started.md, iterate.md, chat.md)
examples/             # Shell usage scripts
pyproject.toml        # Poetry config, dependencies, pytest config
package.json          # npm config for VS Code extension
tsconfig.json
.pre-commit-config.yaml  # Black, Bandit, detect-secrets, debug-statements, large-file checks
```

---

## Bootstrap & Development Commands

### Python

```bash
poetry install                          # Install all dependencies
poetry install --extras embeddings      # Include sentence-transformers + torch
make sync-deps                          # Rebuild Python/Node lock files together
make bump-version VERSION=0.15.1-dev    # Bump versions + refresh locks + changelog target line
poetry run storycraftr --help           # Verify CLI loads
poetry run pytest                       # Run all tests
poetry run pre-commit run --all-files   # Lint + security scan (run before every push)
```

The CI pipeline uses **uv** with native caching and **Poetry export** for deterministic installs:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install poetry poetry-plugin-export
poetry export --with dev --format requirements.txt --without-hashes --output requirements-ci.txt
uv pip install -r requirements-ci.txt
uv pip install -e .
pytest
```

> **Do not** mirror CI export/install steps for local development unless needed; local development should continue using `poetry install`.

### TypeScript (VS Code Extension)

```bash
npm install          # First-time setup
npm run compile      # Emit out/extension.js (tsconfig → out/)
npm run watch        # Live rebuild during development
```

---

## CI Workflows

| File | Trigger | Purpose |
|------|---------|---------|
| `.github/workflows/pytest.yml` | push / PR to any branch | Runs tests and smoke checks on Python 3.13 using uv cached setup + `poetry export` + `uv pip` installs |
| `.github/workflows/pre-commit.yml` | push / PR to any branch | Runs pre-commit hooks (Black, Bandit, detect-secrets, large-file) |
| `.github/workflows/ci-failure-fix.yml` | `workflow_run` completion failure | Invokes Jules AI agent to propose a fix |

When investigating CI failures, always use GitHub MCP tools to retrieve actual job logs.

---

## Architecture & Key Patterns

### Dual-CLI Routing

`storycraftr/cli.py` calls `detect_invocation()` to determine whether it was invoked as `storycraftr` or `papercraftr`, then conditionally registers the appropriate command groups. Both share `init`, `reload-files`, `chat`, `publish`, `cleanup`, and `sub-agents`.

### Project Configuration Files

Each project workspace contains either `storycraftr.json` or `papercraftr.json`. These are loaded via `load_book_config(book_path)` which returns a `SimpleNamespace` (not the `BookConfig` NamedTuple — the NamedTuple is for documentation only). Both files share the same JSON schema. The helper `load_book_config` tries `papercraftr.json` first, then falls back to `storycraftr.json`.

Key config fields:

```json
{
  "book_name": "...",
  "primary_language": "en",
  "cli_name": "storycraftr",
  "llm_provider": "openai",           // openai | openrouter | ollama | fake
  "llm_model": "gpt-4o",
  "llm_endpoint": "",                 // Optional custom base URL
  "llm_api_key_env": "",              // Env var override for API key
  "temperature": 0.7,
  "request_timeout": 120,
  "embed_model": "BAAI/bge-large-en-v1.5",
  "embed_device": "auto",
  "embed_cache_dir": ""
}
```

### LLM Factory (`storycraftr/llm/factory.py`)

`build_chat_model(LLMSettings)` supports:
- `openai` / `openrouter` → `ChatOpenAI` via `langchain_openai`
- `ollama` → `ChatOllama` via `langchain_community`
- `fake` → `_OfflineChatModel` (returns placeholder text; used in tests)

API keys are resolved from environment variables. Default variable names: `OPENAI_API_KEY`, `OPENROUTER_API_KEY`. Ollama uses `OLLAMA_BASE_URL` (no key required). Credentials can also be stored as plain-text files in `~/.storycraftr/` (e.g., `openai_api_key.txt`), loaded by `storycraftr/llm/credentials.py`.

### Embedding Model (`storycraftr/llm/embeddings.py`)

Uses `HuggingFaceEmbeddings` from `langchain_huggingface`. BGE models automatically set `normalize_embeddings=True`. Cache directory is configurable via `embed_cache_dir` in config or `STORYCRAFTR_EMBED_CACHE` environment variable.

### Vector Store (`storycraftr/vectorstores/chroma.py`)

`build_chroma_store(project_path, embedding_function, ...)` creates a persistent Chroma collection inside `<project_path>/vector_store/`. `anonymized_telemetry=False` and `allow_reset=True` are always set.

### Assistant (`storycraftr/agent/agents.py`)

`LangChainAssistant` is the central runtime object:
- Holds `llm`, `embeddings`, `vector_store`, `retriever`, and the LangChain `graph`
- `ensure_vector_store(force=False)` populates Chroma with `.md` files from the project
- `create_message(...)` runs inference through the LCEL graph and appends to a `ConversationThread`
- Assistants are cached globally in `_ASSISTANT_CACHE` keyed by resolved `book_path`
- `behavior` text is loaded from `<book_path>/behaviors/default.txt`

### LCEL Graph (`storycraftr/graph/assistant_graph.py`)

The graph uses a `RunnableParallel` that retrieves documents from Chroma and then calls the chat model. Returned as a dict `{"answer": str, "documents": list}`.

### Sub-Agent System (`storycraftr/subagents/`)

- `SubAgentRole` (models.py) — YAML-serialisable dataclass with `slug`, `name`, `command_whitelist`, `system_prompt`, `temperature`
- `storage.py` — reads/writes role YAML files under `<book_path>/.storycraftr/subagents/`; `seed_default_roles()` materialises defaults
- `defaults.py` — four built-in roles: `editor`, `continuity`, `worldbuilding`, `marketing`
- `jobs.py` — `SubAgentJobManager`: thread-pool executor, job lifecycle (`pending` → `running` → `succeeded`/`failed`), persists run logs as Markdown + JSON under `.storycraftr/subagents/logs/<role_slug>/`
- Jobs are submitted via `!<module>` command tokens (e.g., `!outline`, `!chapters`) matched against each role's `command_whitelist`

### Prompt Hash Injection (`storycraftr/utils/core.py`)

`generate_prompt_with_hash()` prepends a random date phrase to every LLM prompt and logs the entry to `<book_path>/prompts.yaml`. This is designed to reduce caching artifacts.

---

## Coding Conventions

- **Python**: Black formatter, 88-character lines, `snake_case` functions, lowercase package names. Use `from __future__ import annotations` in every new module.
- **TypeScript**: camelCase functions, PascalCase classes, activation command IDs must start with `storycraftr.`.
- **Imports**: Grouped — stdlib, third-party (`langchain_*`, `click`, `rich`), internal `storycraftr.*`. Relative imports are acceptable within a sub-package.
- **Error handling**: Use `RuntimeError` for unrecoverable agent/config errors. CLI errors use `click.ClickException` or `sys.exit(1)` after printing a `[red]…[/red]` message with Rich. Never swallow exceptions silently.
- **`console`**: Every module that produces user-facing output owns a module-level `console = Console()` instance. The sub-agent job system temporarily swaps these consoles to capture output (see `jobs.py::_swap_storycraftr_consoles`).
- **Prompts and templates**: Keep prompts in `storycraftr/prompts/story/` or `storycraftr/prompts/paper/` as Python string constants. Keep LaTeX and folder templates in `storycraftr/templates/`.

---

## Testing

- Test files live under `tests/` (top-level) and `tests/unit/`.
- Naming: `test_<feature>.py`.
- Use `tmp_path` (pytest fixture) for filesystem isolation.
- To create a minimal project config in tests, write a `storycraftr.json` to `tmp_path` with all required fields (see `tests/unit/test_subagents.py::_minimal_config` for a reference fixture).
- LLM calls in tests should use `llm_provider: "fake"` or monkeypatch heavy functions.
- The `SubAgentJobManager` background threads must be shut down with `manager.shutdown()` at the end of each test.
- Run: `poetry run pytest` (picks up `testpaths = ["tests"]` from `pyproject.toml`).

---

## Security & Secrets

- **Never** commit API keys, `.env` files, or `~/.storycraftr/*.txt` files.
- `detect-secrets` runs via pre-commit; run `poetry run detect-secrets scan` after touching config files.
- Bandit is enabled via pre-commit with `-s B101` (asserts suppressed); fix any other B-level findings before pushing.
- New networking code should be reviewed against `SECURITY.md`.
- Environment variable names for credentials: `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`, `OLLAMA_BASE_URL`, `STORYCRAFTR_HTTP_REFERER`, `STORYCRAFTR_APP_NAME`, `STORYCRAFTR_EMBED_CACHE`.

---

## Commit & PR Conventions

- Conventional Commit prefixes: `feat(agents):`, `fix(cli):`, `sec:`, `chore(deps):`, `docs:`, `test:`, `refactor:`
- Messages should be imperative and concise (e.g., `feat(subagents): add role temperature override`).
- Each PR description must include: user-facing change description, test coverage notes, and any docs/templates updated.
- Link related GitHub issues with `Fixes #N` or `Closes #N`.

---

## Known Pitfalls & Workarounds

1. **`storycraftr/utils/paths.py` exists and is the canonical path resolver.** It exposes `resolve_project_paths(book_path, config)` which returns a `ProjectPaths` dataclass with all normalized internal-state paths (subagents, sessions, vector store, VS Code events). Always use this helper instead of constructing paths manually; never hardcode `.storycraftr/` directory literals.
2. **`BookConfig` NamedTuple vs `SimpleNamespace`**: `load_book_config()` returns a `SimpleNamespace`, not the `BookConfig` NamedTuple. Always use `getattr(config, "field", default)` when accessing config fields to avoid `AttributeError` on older project files missing newer keys.
3. **Dual graph field on `LangChainAssistant`**: The dataclass declares `graph` twice (a known duplicate); do not add a third declaration.
4. **Chroma telemetry**: `anonymized_telemetry=False` must always be passed to `chromadb.config.Settings` to prevent outbound telemetry calls in tests/CI.
5. **Embedding model download in CI**: Tests that instantiate a real `HuggingFaceEmbeddings` model will attempt to download multi-GB artifacts. Always mock or use `llm_provider=fake` in unit tests.
6. **`uv` + Poetry export in CI**: CI installs `poetry` + `poetry-plugin-export` inside the uv virtual environment, exports requirements from `poetry.lock`, and installs via `uv pip`. Local development should continue to use `poetry install`.
7. **Pre-commit large-file limit**: 500 KB. Do not commit model weights, lock file diffs, or large test fixtures directly.

## Repository Change Impact Checklist — Agent Contract

**Rule 0 — Single source of truth:** All change impact tracking lives in `docs/CHANGE_IMPACT_CHECKLIST.md`. No other checklist, memory, or inference is allowed.
**Rule 1 — Mandatory checklist update:** Any change to the repository MUST be accompanied by a checklist review. If no checklist item applies, you must explicitly mark "No impact" with justification.
**Rule 2 — Source → derived invariants:** Modifying `pyproject.toml` requires regenerating `poetry.lock`. Modifying `package.json` requires regenerating `package-lock.json`. Lock files must never be edited directly.
**Rule 3 — Configuration parity:** Any change to runtime configuration (CLI, env vars, providers) must be reflected in CLI code, VS Code extension, and Docs.
**Rule 4 — Tests and security tooling:** Fake secrets in tests must be isolated to a single assignment line and include `# nosec B105  # pragma: allowlist secret`.
**Rule 5 — Documentation coupling:** Changes to architecture-critical files require confirmation that docs were reviewed.
**Rule 6 — Commit readiness:** A change is incomplete if the checklist is not updated, lockfile checks fail, or pre-commit hooks require `--no-verify`.
**Rule 7 — CI is authoritative:** CI validates invariants only and must never modify repository state.
