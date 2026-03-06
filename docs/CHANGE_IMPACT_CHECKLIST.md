### 1. Dependency and Lockfile Integrity
- [ ] For routine dependency regeneration after changing `pyproject.toml` or `package.json`, run `make sync-deps` and commit synchronized `poetry.lock` and `package-lock.json`.
- [ ] Avoid raw `poetry lock` or `npm install` for routine dependency regeneration; use `make sync-deps`.
- [ ] Never edit `poetry.lock` or `package-lock.json` manually.
- [ ] CI must fail if lock files change during build or dependency installation.
- [ ] CI must assert lockfile cleanliness with `git diff --exit-code poetry.lock package-lock.json` after dependency steps.

### 2. Dual-Project Configuration Parity
- [ ] Any initialization, discovery, or path check must accept both `storycraftr.json` and `papercraftr.json`.
- [ ] Any config schema add/remove/rename must be applied consistently to both Story and Paper command paths.
- [ ] Any CLI validation tied to config presence must be tested for both config filenames.
- [ ] Any default config field introduced for one project must be intentionally handled for the other project.

### 3. LLM Configuration & Routing
- [ ] Any provider or model routing change must update `storycraftr/llm/factory.py` and `tests/unit/test_llm_factory.py` together.
- [ ] Runtime model overrides must be passed explicitly via function parameters and never through global mutable state.
- [ ] `_ASSISTANT_CACHE` keys must include every parameter that can change LLM behavior, including `book_path` and `model_override`.
- [ ] Provider failures must raise actionable, provider-specific errors that include provider, model, and endpoint.
- [ ] Provider error messages must never expose API keys or secret values.
- [ ] Any credential loading change must preserve strict precedence: `Environment Variable -> OS Keyring -> Legacy Plaintext File`.
- [ ] Changes to override precedence must preserve `CLI flag > config file > default` unless intentionally redesigned and documented.

### 4. Sub-Agents & Background Jobs
- [ ] Any change to sub-agent execution must preserve thread safety guarantees in `storycraftr/subagents/jobs.py`.
- [ ] Any new sub-agent role must include a YAML role definition with an explicit `command_whitelist`.
- [ ] Role whitelists must remain least-privilege and limited to required commands.
- [ ] Sub-agent lifecycle events must continue emitting valid JSONL payloads for queued, running, succeeded, and failed states.
- [ ] Any event payload schema change must be mirrored in the VS Code consumer logic.

### 5. Vector Store & RAG Integrity
- [ ] Any change to `storycraftr/utils/markdown.py` parsing must trigger a review of chunking and retrieval behavior.
- [ ] Any chunking or document-loading change must be validated against Chroma vector store ingestion paths.
- [ ] Embedding-heavy operations must not introduce unexpected blocking in interactive CLI flows.
- [ ] All runtime internal paths (`subagents`, `sessions`, `vector_store`, `vscode_events_file`) must resolve through `resolve_project_paths` and avoid new hardcoded `.storycraftr` literals.

### 6. VS Code Extension (IPC & UI)
- [ ] Any backend event stream path or payload change must be reflected in `src/extension.ts`.
- [ ] Extension watcher setup must read workspace root `storycraftr.json` or `papercraftr.json` for `vscode_events_file` overrides.
- [ ] Extension watcher setup must preserve fallback behavior to `**/.storycraftr/vscode-events.jsonl`.
- [ ] Watchers must attach `onDidCreate` and `onDidChange` handlers for both custom and fallback watcher modes.
- [ ] `npm run compile` must pass before merge and must not rely on missing or implicit type dependencies.
- [ ] Any Story/Paper config detection or custom event path behavior change must be synchronized in user-facing docs (at minimum `README.md` and the architecture reference).

### 7. Security & Tooling
- [ ] Any fake credential literal in tests must include `# nosec B105` and `pragma: allowlist secret` on the exact literal line.
- [ ] Bandit and detect-secrets controls must not be disabled globally in config, CI, or pre-commit.
- [ ] CI must run pre-commit, and if hooks mutate files then CI must fail the build.
- [ ] Error handling and logs must be reviewed to ensure no secret material is emitted.

### 8. Documentation & Versioning
- [ ] Version bumps must be synchronized across `pyproject.toml`, `package.json`, and `package-lock.json`, with a corresponding `CHANGELOG.md` entry in the same change set.
- [ ] Core architecture changes touching LLM factory, sub-agents, or IPC must update `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`.
- [ ] Every feature or fix commit must have a corresponding `CHANGELOG.md` entry.
- [ ] Any behavior-affecting CLI change must be reflected in user-facing docs where relevant.

## Checklist Review Notes

- 2026-03-06: `pyproject.toml` tooling-config cleanup only.
- Impact: Removed invalid pytest options (`line-length`, `target-version`) and added equivalent `[tool.black]` settings.
- No impact: Runtime behavior, dependencies, lockfiles, CLI/LLM/subagent/IPC flows, and user-facing docs.
- 2026-03-06: CI test coverage expanded in `.github/workflows/pytest.yml`.
- Impact: Added matrix testing for Python `3.11` and `3.13` via `actions/setup-python`.
- No impact: Application runtime logic, dependency metadata, lockfiles, and user-facing CLI/docs behavior.
- 2026-03-06: Python 3.13 modernization follow-ups.
- Impact: Migrated core metadata/scripts to PEP 621 (`[project]`, `[project.scripts]`), switched CI dependency install to `uv pip` with `poetry export`, and added a Python 3.13 README badge.
- Impact: Regenerated lock metadata through `make sync-deps` after `pyproject.toml` change.
- No impact: Story/Paper runtime command behavior, LLM routing, sub-agent execution semantics, and IPC payload contracts.
- 2026-03-06: Python 3.13 support policy finalized and validated.
- Impact: CI `pytest.yml` now enforces Python `3.13` only, restores `poetry install` flow, and adds CLI + VS Code extension build smoke steps.
- Impact: Updated Black target runtime from `py39` to `py313`, aligned architecture overview language statement, and documented runtime requirement in `README.md`.
- No impact: Runtime command semantics, vector store schema, sub-agent event payload contract, and credential resolution precedence.
- 2026-03-06: Optional embeddings CI lane added.
- Impact: Added `embeddings-smoke` workflow job in `.github/workflows/pytest.yml` to install `--with embeddings` on Python `3.13` and run import-level smoke validation for `sentence_transformers` and `torch`.
- No impact: Core CLI behavior, base dependency set, LLM provider routing, and extension event payload schema.
- 2026-03-06: pre-commit workflow install path optimized with uv.
- Impact: `.github/workflows/pre-commit.yml` now uses Python `3.13`, installs `uv`, creates `.venv`, and installs `pre-commit`/`poetry` via `uv pip install` for faster CI dependency setup.
- No impact: Hook set, pre-commit behavior, lockfile policies, and application runtime semantics.
- 2026-03-06: Full-stack dependency upgrade matrix added.
- Impact: Added `docs/python-3.13-full-stack-upgrade-matrix.md` with staged upgrade waves, version targets, risk tiers, validation gates, and rollback strategy for Python 3.13-compatible modernization.
- No impact: Runtime behavior, dependency specifications, lockfiles, CI execution logic, and extension IPC contract.
- 2026-03-06: Python 3.13 compliance — deprecated import removal and dependency floor bump.
- Impact: Removed three deprecated langchain import paths in `storycraftr/agent/agents.py` (`langchain.schema`, `langchain.text_splitter`, `langchain_community.vectorstores`) in favour of canonical `langchain_core`/`langchain_text_splitters`/`langchain_chroma` namespaces. Updated minimum version floors for `langchain-openai`, `chromadb`, `huggingface-hub`, `sentence-transformers`, `torch`, and added explicit `langchain-text-splitters` direct dependency in `pyproject.toml`. Regenerated `poetry.lock` content-hash via `make sync-deps` (resolved versions unchanged).
- No impact: Runtime command semantics, LLM provider routing, sub-agent execution, credential resolution precedence, vector store schema, and VS Code extension IPC contract.
