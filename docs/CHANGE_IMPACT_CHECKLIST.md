# Change Impact Checklist

## Change History

### 2026-03-06 — CI bottleneck removal and uv cache-key fix
- **Sections reviewed:** 1 (Dependency and Lockfile Integrity), 7 (Security & Tooling), 8 (Documentation & Versioning)
- **Impact:** Removed `jlumbroso/free-disk-space` from `.github/workflows/pytest.yml` and `.github/workflows/pre-commit.yml` to eliminate startup overhead; configured `setup-uv` cache invalidation with explicit dependency globs (`poetry.lock` for pytest jobs, `pyproject.toml` for pre-commit) to avoid default cache-key mismatch behavior.
- **No impact** on sections 2–6: no runtime config schema, LLM routing, sub-agent lifecycle, vector-store contract, or extension IPC behavior changes.

### 2026-03-06 — Release notes wording deduplication
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Refined `release_notes.md` CI update wording to reduce duplication with `CHANGELOG.md` while preserving the same factual coverage and adding a pointer to `[Unreleased]` changelog details.
- **No impact** on sections 1–7: documentation-only phrasing update.

### 2026-03-06 — README and release notes sync for CI workflow changes
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Updated `README.md` with the current CI dependency install pattern and invariants, corrected workflow badge links to the active repository, and added a new `release_notes.md` draft section covering CI acceleration and merge-readiness notes.
- **No impact** on sections 1–7: no runtime code, dependency specs, lockfiles, security tooling policy, or extension/runtime behavior changed.

### 2026-03-06 — Documentation sync for CI install pattern
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Updated `.github/copilot-instructions.md`, `AGENTS.md`, and `CHANGELOG.md` so project guidance and release notes reflect the current CI install convention (`setup-uv` cache + `poetry export` + `uv pip`) and Python 3.13-oriented pytest workflow description.
- **No impact** on sections 1–7: no dependency spec, runtime configuration, LLM routing, sub-agent lifecycle, vector-store behavior, extension IPC, or security-tooling policy changes.

### 2026-03-06 — Pre-commit CI uv cache consistency update
- **Sections reviewed:** 1 (Dependency and Lockfile Integrity), 7 (Security & Tooling), 8 (Documentation & Versioning)
- **Impact:** Updated `.github/workflows/pre-commit.yml` to use `astral-sh/setup-uv@v5` native cache (`enable-cache: true`), removed deprecated `curl | bash` install path from the same step, and removed redundant secondary disk-space maximization action to reduce startup latency while preserving pre-commit behavior.
- **No impact** on sections 2–6: no Story/Paper config, LLM routing, sub-agent lifecycle, vector-store, or VS Code extension contract changes.

### 2026-03-06 — Pytest CI acceleration with uv cache + Poetry export
- **Sections reviewed:** 1 (Dependency and Lockfile Integrity), 6 (VS Code Extension (IPC & UI)), 7 (Security & Tooling), 8 (Documentation & Versioning)
- **Impact:** Updated `.github/workflows/pytest.yml` to use `astral-sh/setup-uv@v5` native cache (`enable-cache: true`), export dependencies from `poetry.lock` (`poetry export`) and install via `uv pip`, add explicit `npm ci` before `npm run compile`, align `embeddings-smoke` to the same export+uv flow, add fail-fast validation for `poetry export` availability, and keep lockfile immutability checks.
- **No impact** on sections 2–5: no config schema, LLM routing, sub-agent lifecycle, or vector-store contract changes.

### 2026-03-06 — Python baseline upgrade to 3.13 (feat: upgrade Python baseline to 3.13)
- **Sections reviewed:** 1 (Dependency and Lockfile Integrity), 7 (Security & Tooling), 8 (Documentation & Versioning)
- **Impact:** Python constraint in `pyproject.toml` updated to `>=3.13,<3.14`; `poetry.lock` regenerated; CI workflows updated to Python 3.13; `CHANGELOG.md` updated.
- **No impact** on sections 2–6: no config schema changes, no LLM/sub-agent/vector-store/VS Code extension changes, no credential or security logic touched.

### 2026-03-06 — Python 3.13 compliance: deprecated import removal, dep floor bump, CI hardening
- **Sections reviewed:** 1 (Dependency and Lockfile Integrity), 5 (Vector Store & RAG), 7 (Security & Tooling), 8 (Documentation & Versioning)
- **Impact:** Replaced deprecated LangChain import paths in `agents.py`; bumped dep floors for `langchain-openai`, `chromadb`, `huggingface-hub`, `sentence-transformers`, `torch`; replaced `curl | bash` uv install with `astral-sh/setup-uv@v5` in CI; pinned all third-party action SHAs; added Python baseline assertion steps; scoped `ci-failure-fix` away from protected branches.
- **No impact** on sections 2–4, 6: no config schema changes, no LLM routing/sub-agent/IPC contract changes.

---

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

- 2026-03-06: Python 3.13 governance and CI consistency hardening.
- Impact: Aligned `.github/workflows/pytest.yml` and `.github/workflows/pre-commit.yml` to Python `3.13`, added explicit Python-baseline assertions, and kept `uv`-based install acceleration in CI.
- Impact: Pinned third-party workflow actions to immutable commit SHAs in `pytest.yml`, `pre-commit.yml`, and `ci-failure-fix.yml`.
- Impact: Scoped autonomous `ci-failure-fix` execution away from `main`/`release/*` and same-repository branch guardrails.
- Impact: Added workflow-governance items to `.github/pull_request_template.md`.
- Impact: Fixed `pyproject.toml` config drift by moving `line-length`/`target-version` into `[tool.black]` and targeting `py313`.
- Impact: Synchronized development-target references in `README.md` and `release_notes.md` to `0.15.2-dev`, and documented Python `3.13.x` runtime requirement in `README.md`.
- No impact: Story/Paper command behavior, LLM routing semantics, sub-agent lifecycle payload schemas, and vector-store persistence contract.
- 2026-03-06: CI supply-chain hardening — replaced `curl | bash` uv install with `astral-sh/setup-uv@v5` GitHub Action in `pytest.yml` and `pre-commit.yml`; pinned `actions/setup-python` to immutable SHA. Python line-length doc corrected from 79 to 88 chars.
- No impact: Runtime behavior, dependency specifications, lockfiles, and application semantics.
- 2026-03-06: Python 3.13 compliance — deprecated import removal and dependency floor bump.
- Impact: Removed three deprecated langchain import paths in `storycraftr/agent/agents.py`; updated minimum dep floors for `langchain-openai`, `chromadb`, `huggingface-hub`, `sentence-transformers`, `torch`; converted `pyproject.toml` to `[tool.poetry]` format; regenerated `poetry.lock` content-hash.
- No impact: Runtime command semantics, LLM provider routing, sub-agent execution, credential resolution precedence, vector store schema, and VS Code extension IPC contract.
