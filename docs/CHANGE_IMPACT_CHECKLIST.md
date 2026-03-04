### 1. Dependency and Lockfile Integrity
- [ ] If `pyproject.toml` changes, run `poetry check --lock` and commit the synchronized `poetry.lock`.
- [ ] If `package.json` changes, run `npm install` and commit the synchronized `package-lock.json`.
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
- [ ] Vector store paths must remain resolved through the shared path resolver and not new hardcoded literals.

### 6. VS Code Extension (IPC & UI)
- [ ] Any backend event stream path or payload change must be reflected in `src/extension.ts`.
- [ ] Extension watcher setup must read workspace root `storycraftr.json` or `papercraftr.json` for `vscode_events_file` overrides.
- [ ] Extension watcher setup must preserve fallback behavior to `**/.storycraftr/vscode-events.jsonl`.
- [ ] Watchers must attach `onDidCreate` and `onDidChange` handlers for both custom and fallback watcher modes.
- [ ] `npm run compile` must pass before merge and must not rely on missing or implicit type dependencies.

### 7. Security & Tooling
- [ ] Any fake credential literal in tests must include `# nosec B105` and `pragma: allowlist secret` on the exact literal line.
- [ ] Bandit and detect-secrets controls must not be disabled globally in config, CI, or pre-commit.
- [ ] CI must run pre-commit, and if hooks mutate files then CI must fail the build.
- [ ] Error handling and logs must be reviewed to ensure no secret material is emitted.

### 8. Documentation & Versioning
- [ ] Version bumps must be synchronized across Python and Node metadata files, including `pyproject.toml` and `package.json`.
- [ ] Core architecture changes touching LLM factory, sub-agents, or IPC must update `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`.
- [ ] Every feature or fix commit must have a corresponding `CHANGELOG.md` entry.
- [ ] Any behavior-affecting CLI change must be reflected in user-facing docs where relevant.
