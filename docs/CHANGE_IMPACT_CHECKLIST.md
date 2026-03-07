# Change Impact Checklist

## Change History

### 2026-03-07 — TUI guided planning enhancement: profile-driven /wizard plan
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Extended `storycraftr/tui/app.py` wizard flow with profile commands:
	  - `/wizard set <field> <value>` for premise/protagonist/genre/tone/flow
	  - `/wizard show` and `/wizard reset`
	  - `/wizard plan` to generate an advisory command sequence based on writer inputs.
	- Preserved non-destructive behavior: wizard outputs recommendations only and does not auto-execute generation commands.
	- Expanded `tests/unit/test_tui_app.py` coverage for wizard profile lifecycle, invalid field/flow validation, and plan ordering behavior.
	- Synced docs in `README.md`, `docs/chat.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — TUI command discoverability: grouped /help and /pipeline alias
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` to provide grouped command help (`Writing`, `Planning`, `World`, `Project`) and topic-scoped help via `/help <topic>`.
	- Added `/pipeline` (`/pipeline next`) as an alias to existing wizard guidance behavior for onboarding clarity.
	- Expanded `tests/unit/test_tui_app.py` with regressions for grouped help output, topic filtering, unknown help topic handling, and wizard/pipeline alias parity.
	- Synced user-facing command docs in `README.md`, `docs/chat.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — TUI workflow guidance: /progress checkpoint view and /wizard next-step helper
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` with two new guided workflow commands:
	  - `/progress` renders file-backed completion state for canonical story pipeline checkpoints.
	  - `/wizard` and `/wizard next` provide a guided pipeline checklist and next recommended command derived from missing artifacts.
	- Added helper logic to detect generated artifacts under `outline/`, `worldbuilding/`, `chapters/`, and `book/` for checkpoint status.
	- Expanded `tests/unit/test_tui_app.py` with regressions for `/progress` output and `/wizard next` recommendation sequencing.
	- Synced docs in `README.md`, `docs/chat.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — TUI ergonomics pass: clear output, focus mode, prompt history, inline command status
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` with writer-focused quality-of-life controls:
	  - Added `/clear` slash command to clear the output pane without resetting session state.
	  - Added `ctrl+l` focus-mode binding to hide/show sidebar and state strips together.
	  - Added command-input history navigation with Up/Down arrow handling.
	  - Added inline slash-command execution status messages (`[Running]`, `[Done]`, `[Failed]`) in the output log.
	- Updated TUI command/help regressions in `tests/unit/test_tui_app.py` for `/clear`, focus mode toggling, and history navigation behavior.
	- Synced user-facing docs for the new TUI behavior in `README.md`, `docs/chat.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile updates, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-06 — TUI focus layout fix: collapsible sidebar container and softer strip fallbacks
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` layout IDs and toggle behavior so `/toggle-tree` and `ctrl+t` hide/show the full sidebar container (`#sidebar`) instead of only the `DirectoryTree` widget, allowing the main pane (`#main-pane`) to reclaim full width.
	- Ensured writer-first default view remains consistent by hiding the full sidebar container on mount.
	- Refined startup prompt guidance to list supported commands (`/help`, `/outline`) and removed stale `/agents` example text.
	- Updated `storycraftr/tui/state_engine.py` strip text fallbacks to reduce noisy `Unknown` output (`Timeline: No scene map yet`, `Timeline: Chapter metadata incomplete`, and chapter-first narrative strip formatting).
	- Added/updated TUI regressions in `tests/unit/test_tui_app.py` and `tests/unit/test_tui_state_engine.py` for sidebar toggle behavior and low-confidence strip placeholders.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config contract changes, no LLM provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code IPC contract changes, and no security-tooling policy changes).

### 2026-03-06 — State-driven TUI UX and read-only narrative state engine
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Refactored `storycraftr/tui/app.py` to a writer-focused state-driven layout: hidden-by-default `DirectoryTree` with `ctrl+t`/`/toggle-tree`, Narrative and Timeline strips, and slash commands `/chapter <number>` and `/scene <label>` for in-memory focus.
	- Added `/state` slash command in `storycraftr/tui/app.py` to expose the active narrative snapshot and exact injected state block for user transparency.
	- Added `storycraftr/tui/state_engine.py` as a read-only narrative state component that parses chapter markdown frontmatter and optional outline YAML arc mappings with safe fallback behavior on malformed files; no autonomous filesystem mutation paths were introduced.
	- Wired TUI prompt dispatch to prefix a read-only state block before calling existing assistant APIs, preserving core `agents.py` and graph orchestration contracts.
	- Added and updated TUI-focused unit tests in `tests/unit/test_tui_state_engine.py` and `tests/unit/test_tui_app.py`.
	- Updated docs for TUI behavior and architecture surfaces (`README.md`, `docs/getting_started.md`, `docs/chat.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `CHANGELOG.md`, `release_notes.md`).
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security tooling policy changes).

### 2026-03-06 — Documentation synchronization for TUI command center and model controls
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Synced architecture and onboarding docs to reflect the Textual TUI module and model-control surface: `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `docs/getting_started.md`, and `docs/chat.md`.
	- Updated repository-level guidance docs (`AGENTS.md`, `.github/copilot-instructions.md`) to include `storycraftr/tui/` in the canonical layout and architecture map.
	- Updated `release_notes.md` draft section to include the new TUI slash-command UX (`/help`, `/status`, `/model-list`, `/model-change`) and deterministic sub-agent lock-test seam update.
- **No impact:** sections 1-7 (no dependency/lockfile updates, no Story/Paper config schema changes, no runtime provider routing changes, no sub-agent lifecycle/IPC contract changes, and no security-tooling policy changes).

### 2026-03-06 — TUI slash-command UX extension with OpenRouter free-model controls
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Extended `storycraftr/tui/app.py` with TUI-native `/help` and `/status` responses, visible model/provider status text, and slash-command handling for `/model-list` and `/model-change <model_id>`.
	- Added `storycraftr/tui/openrouter_models.py` to fetch and normalize free-model metadata from OpenRouter's authoritative `/api/v1/models` endpoint, with graceful failure and cache fallback handling.
	- Model switching remains a thin UI-layer override by reusing `create_or_get_assistant(book_path, model_override=...)`; vector-store/project context is preserved and continuity messaging is explicit.
	- Added focused unit tests in `tests/unit/test_tui_app.py` and `tests/unit/test_tui_openrouter_models.py`.
	- Updated `README.md` and `CHANGELOG.md` with new TUI slash-command behavior.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no lockfile/dependency manifest changes, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/runtime path contract changes, no VS Code IPC schema changes, and no security tooling policy changes).

### 2026-03-06 — Minimal Textual TUI shell (v0.1)
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Added a new thin UI layer module under `storycraftr/tui/` (`__init__.py`, `app.py`) implementing a terminal-native Textual dashboard with `Header`, `Footer`, `DirectoryTree`, `RichLog`, and `Input` widgets.
	- TUI assistant flow reuses existing APIs (`create_or_get_assistant`, `get_thread`, `create_message`) and does not modify core agent/vector/sub-agent/session behavior.
	- Slash-command routing reuses existing chat/CLI dispatchers (`storycraftr.chat.commands.handle_command` and `storycraftr.chat.module_runner.run_module_command`) rather than introducing new execution logic.
	- Added user-facing documentation updates in `README.md` and `CHANGELOG.md` for TUI launch and scope.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile changes, no config schema changes, no sub-agent lifecycle changes, no vector-store contract changes, no VS Code IPC changes, and no security-tooling policy changes).

### 2026-03-06 — Documentation and dependency snapshot synchronization (v0.16 target + textual lock update)
- **Sections reviewed:** 1 (Dependency and Lockfile Integrity), 8 (Documentation & Versioning)
- **Impact:**
	- Synchronized development target wording to `v0.16` (`0.16.0-dev`) across core docs (`README.md`, `AGENTS.md`, `release_notes.md`, `docs/getting_started.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `CHANGELOG.md`).
	- Updated dependency documentation to reflect current lock state by recording `textual` in runtime dependency narratives and updating `docs/python-3.13-full-stack-upgrade-matrix.md` locked rows (`rich` `14.3.3`, `textual` `8.0.2`, `black` `26.1.0`).
	- Updated unreleased release notes/changelog text to reflect the lockfile change semantics accurately.
- **No impact:** sections 2–7 (no runtime config schema, LLM routing logic, sub-agent lifecycle behavior, vector-store logic, VS Code IPC contract, or security-tooling policy changes).

### 2026-03-06 — Test compatibility fix: mock-safe project lock + deterministic sub-agent persistence assertion
- **Sections reviewed:** 4 (Sub-Agents & Background Jobs), 5 (Vector Store & RAG Integrity), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/utils/project_lock.py` to gracefully fall back to process-local locking when the opened lock-handle does not provide a usable integer file descriptor (for example, `mock_open` handles in unit tests), while preserving POSIX `flock` behavior for real file descriptors.
	- Updated `tests/unit/test_subagents.py::test_job_manager_persist_job_uses_project_write_lock` to assert lock usage through a deterministic `_persist_job()` seam, removing executor timing dependence from the lock-behavior assertion.
	- Restored passing regressions for `tests/test_markdown.py::test_append_to_markdown_success` and `tests/unit/test_subagents.py::test_job_manager_persist_job_uses_project_write_lock`.
- **No impact:** sections 1, 2, 3, 6, and 7 (no dependency/lockfile changes, no config schema or LLM routing contract changes, no VS Code IPC contract changes, and no security-tooling policy changes).

### 2026-03-06 — Small architectural extraction: vector hydration helper module + canonical docs sync
- **Sections reviewed:** 5 (Vector Store & RAG Integrity), 6 (VS Code Extension (IPC & UI)), 8 (Documentation & Versioning)
- **Impact:**
	- Extracted vector-store refresh/hydration responsibilities from `storycraftr/agent/agents.py` into `storycraftr/agent/vector_hydration.py` (`resolve_persist_dir`, force rebuild helper, refresh checks, markdown ingestion, dedupe, conditional populate).
	- Updated `LangChainAssistant.ensure_vector_store` in `storycraftr/agent/agents.py` to delegate to helper functions while preserving existing compatibility wrappers (`load_markdown_documents`, `_dedupe_documents`) for existing tests/monkeypatch seams.
	- Synced canonical architecture docs to current implementation contracts:
		- `.github/copilot-instructions.md`
		- `docs/architecture-onboarding.md`
		- `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`
	- Documentation now reflects typed `BookConfig` runtime semantics, extracted `assistant_cache.py`/`vector_hydration.py` seams, lock-scope matrix reference, and VS Code event-contract test artifacts (`src/event-contract.ts`, `src/event-contract.test.ts`).
- **No impact:** sections 1, 2, 3, 4, and 7 (no dependency/lockfile changes, config schema changes, provider routing changes, sub-agent lifecycle changes, or security-tooling policy changes).

### 2026-03-06 — Small architectural extraction: assistant cache helper module
- **Sections reviewed:** 3 (LLM Configuration & Routing), 5 (Vector Store & RAG Integrity), 8 (Documentation & Versioning)
- **Impact:**
	- Extracted assistant cache management into `storycraftr/agent/assistant_cache.py`, moving cache key generation/normalization plus lock-guarded cache lookup/store helpers out of `storycraftr/agent/agents.py`.
	- Preserved compatibility by re-exporting cache internals through `storycraftr/agent/agents.py` (`_ASSISTANT_CACHE`, `_ASSISTANT_CACHE_LOCK`, `_assistant_cache_key`) so existing tests and call patterns remain stable.
	- Updated `tests/unit/test_agents_create_message.py` cache fixtures to use `BookConfig.from_mapping(...)` for typed-config parity.
	- Validated targeted assistant/runtime regressions: `tests/unit/test_agents_create_message.py`, `tests/unit/test_agents_vectorstore_integrity.py`, `tests/test_cli.py`, `tests/unit/test_cli_startup.py`.
- **No impact:** sections 1, 2, 4, 6, and 7 (no dependency/lockfile changes, dual-config schema changes, sub-agent runtime contract changes, extension IPC schema changes, or security-tooling policy changes).

### 2026-03-06 — P1 lock audit completion: runtime mutation coverage + reentrant lock safety
- **Sections reviewed:** 4 (Sub-Agents & Background Jobs), 5 (Vector Store & RAG Integrity), 6 (VS Code Extension (IPC & UI)), 8 (Documentation & Versioning)
- **Impact:**
	- Completed lock-coverage hardening for remaining runtime mutation paths by adding `project_write_lock` usage to:
		- `storycraftr/init.py::init_structure_story` and `storycraftr/init.py::init_structure_paper` (project scaffolding/config/template writes)
		- `storycraftr/integrations/vscode.py::VSCodeEventEmitter.emit` (JSONL append serialization)
		- `storycraftr/utils/cleanup.py::cleanup_vector_stores` (vector-store directory removal)
		- `storycraftr/vectorstores/chroma.py::build_chroma_store` (store-directory creation/failure cleanup)
	- Fixed nested lock acquisition behavior in `storycraftr/utils/project_lock.py` by tracking per-thread lock depth per lock path so nested calls do not deadlock while outer acquisitions still enforce cross-process `flock`.
	- Added lock regression tests:
		- `tests/unit/test_init_locks.py` (init scaffolding lock usage)
		- `tests/unit/test_project_lock.py` (nested reentrant acquire)
		- `tests/unit/test_cleanup.py` (cleanup lock usage)
		- `tests/unit/test_core_paths.py` (Chroma builder lock usage)
		- `tests/unit/test_vscode_integration.py` (event emitter lock usage)
	- Added a lock-coverage decision matrix under Checklist Review Notes to classify remaining mutation paths as must-lock, safe single-writer, non-shared runtime state, or deferred with rationale.
- **No impact:** sections 1, 2, 3, and 7 (no dependency/lockfile changes, config schema changes, provider/model routing semantics, or security tooling policy changes).

### 2026-03-06 — Contract consolidation: typed config migration, TS event fixtures, and RAG edge-case coverage
- **Sections reviewed:** 3 (LLM Configuration & Routing), 5 (Vector Store & RAG Integrity), 6 (VS Code Extension (IPC & UI)), 8 (Documentation & Versioning)
- **Impact:**
	- Replaced runtime `getattr(config, ...)` usage with explicit `BookConfig` attributes across core config mapping, assistant prompt composition, chat metadata payloads, markdown/pdf metadata readers, sub-agent role bootstrap language selection, and `resolve_project_paths` path-override resolution.
	- Expanded `BookConfig` typed schema/defaults to include runtime path overrides (`internal_state_dir`, `subagents_dir`, `subagent_logs_dir`, `sessions_dir`, `vector_store_dir`, `vscode_events_file`) and normalized `authors` as a string list.
	- Added extension event parser contract module `src/event-contract.ts` and fixture-based TypeScript tests (`src/event-contract.test.ts`) validating representative JSONL event parsing for `session.started`, `chat.turn`, `session.ended`, `sub_agent.roles`, `sub_agent.status`, `sub_agent.queued`, and `sub_agent.error`.
	- Hardened `LangChainAssistant.ensure_vector_store` by deduplicating identical source/content documents before chunking and adding one-shot force-rebuild recovery when retriever construction fails.
	- Expanded `tests/unit/test_agents_vectorstore_integrity.py` with edge cases for corrupted retriever recovery, reset-failure fallback cleanup, unreadable/short markdown handling, duplicate ingestion deduplication, force rebuild idempotency, and empty-corpus force rebuild failure path.
- **No impact:** sections 1, 2, 4, and 7 (no dependency/lockfile changes, no dual-config filename behavior changes, no sub-agent command lifecycle/payload contract changes, and no security tooling policy changes).

### 2026-03-06 — CLI startup hardening: remove import-time credential side effect
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/cli.py` to stop calling `load_local_credentials()` at module import time.
	- Added lazy one-time bootstrap helper (`_ensure_local_credentials_loaded`) guarded by a process lock and invoked from the Click group callback.
	- Added startup regressions in `tests/unit/test_cli_startup.py` to verify:
		- importing/reloading CLI module does not trigger credential loading
		- credential bootstrap executes once when explicitly invoked repeatedly
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile changes, project config schema changes, sub-agent runtime semantics, vector-store indexing behavior, IPC schema updates, or security tooling policy changes).

### 2026-03-06 — RAG/vector-store integrity regression coverage
- **Sections reviewed:** 5 (Vector Store & RAG Integrity), 8 (Documentation & Versioning)
- **Impact:**
	- Added `tests/unit/test_agents_vectorstore_integrity.py` to validate `LangChainAssistant.ensure_vector_store` behavior for:
		- empty Markdown corpus failure path (`RuntimeError`)
		- `force=True` rebuild path (client reset + reindex + retriever wiring)
		- no-op reindex path when persistent store is already non-empty
	- Re-ran combined regression suites including event-contract tests to ensure no integration drift.
- **No impact:** sections 1–4, 6, and 7 (no dependency manifests/lockfiles, config schema, CLI routing semantics, sub-agent runtime behavior, extension IPC schema changes, or security tooling policy changes).

### 2026-03-06 — Event contract hardening: prompt-mode session lifecycle completion
- **Sections reviewed:** 6 (VS Code Extension (IPC & UI)), 8 (Documentation & Versioning)
- **Impact:**
	- Fixed chat non-interactive prompt path in `storycraftr/cmd/chat.py` to emit `session.ended` before returning, preserving session lifecycle symmetry with interactive mode.
	- Added event-contract regression in `tests/test_cli.py` to assert prompt-mode emission sequence (`session.started`, `chat.turn`, `session.ended`) and required payload keys for each event.
	- Added sub-agent command contract tests in `tests/unit/test_chat_commands.py` to assert event type + payload shape for `sub_agent.roles`, `sub_agent.status`, `sub_agent.queued`, and `sub_agent.error` emissions.
	- Re-validated baseline integration behavior with `tests/unit/test_vscode_integration.py`.
- **No impact:** sections 1–5 and 7 (no dependency/lockfile, config schema, LLM routing, sub-agent execution semantics, vector-store behavior, or security tooling policy changes).

### 2026-03-06 — Phase 0 stability follow-up: extended mutation lock coverage
- **Sections reviewed:** 4 (Sub-Agents & Background Jobs), 5 (Vector Store & RAG Integrity), 8 (Documentation & Versioning)
- **Impact:**
	- Extended `project_write_lock` usage to additional mutation paths:
		- prompt metadata log writes (`storycraftr/utils/core.py::generate_prompt_with_hash`)
		- session transcript saves (`storycraftr/chat/session.py::SessionManager.save`)
		- markdown save/append/consolidation output writes (`storycraftr/utils/markdown.py`)
		- sub-agent role seeding writes (`storycraftr/subagents/storage.py::seed_default_roles`)
		- sub-agent run log/metadata writes (`storycraftr/subagents/jobs.py::_persist_job`)
	- Added lock invocation regression tests in `tests/unit/test_core_paths.py`, `tests/unit/test_llm_config.py`, and `tests/unit/test_subagents.py`.
- **No impact:** sections 1, 2, 3, 6, and 7 (no dependency/lockfile changes, no dual-config filename behavior changes, no LLM routing changes, no VS Code extension payload/path changes, and no security tooling configuration changes).

### 2026-03-06 — Phase 0 stability: assistant cache hardening, typed config, role YAML validation, project mutation lock
- **Sections reviewed:** 3 (LLM Configuration & Routing), 4 (Sub-Agents & Background Jobs), 5 (Vector Store & RAG Integrity), 8 (Documentation & Versioning)
- **Impact:**
	- Hardened assistant cache behavior in `storycraftr/agent/agents.py`: cache key normalization now trims `model_override`; cache access is protected by a re-entrant lock; cache key separation for model overrides is regression-tested.
	- Introduced typed configuration model `BookConfig` in `storycraftr/utils/core.py` while preserving attribute-style compatibility; `load_book_config` now normalizes/coerces core fields (provider, booleans, numeric timeouts/tokens) and returns `BookConfig`.
	- Added project-scoped mutation lock utility `storycraftr/utils/project_lock.py` and applied it to Chroma reset/rebuild and document ingestion writes in `storycraftr/agent/agents.py` to reduce concurrent mutation risk.
	- Hardened sub-agent role loading in `storycraftr/subagents/models.py` and `storycraftr/subagents/storage.py`: malformed YAML or invalid role schema no longer crashes role discovery; invalid role files are skipped with warnings.
	- Added regression tests in `tests/unit/test_agents_create_message.py`, `tests/unit/test_llm_config.py`, and `tests/unit/test_subagents.py`.
- **No impact:** sections 1, 2, 6, and 7 (no dependency manifest/lockfile changes, no dual-config file name behavior changes, no VS Code extension payload/path changes, and no security tooling config changes).

### 2026-03-06 — Tooling ecosystem-wide metadata/version audit refresh
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Audited all current Copilot customization assets (`Agents: 21`, `Skills: 13`, `Instructions: 6`, `Hooks: 1`, `Workflows: 3`) and applied targeted normalization updates: Python baseline wording updated to `3.13+` in `.github/agents/python-mcp-expert.agent.md`; `.github/copilot-instructions.md` target wording normalized to `v0.16` and bump-version example updated to `0.16.0`.
- **No impact** on sections 1–7: metadata/instructions-only changes with no runtime package code, dependency lock regeneration, config schema, LLM routing, sub-agent lifecycle, vector-store behavior, IPC contract, or security-tooling policy changes.

### 2026-03-06 — StoryCraftr engineering agent spec refresh
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Updated `.github/agents/storycraftr-engineering.agent.md` to align with current repository contracts: `v0.16` target wording, dependency/lockfile invariants (`make sync-deps`), Python 3.13 baseline, runtime path resolver requirement, mandatory `docs/CHANGE_IMPACT_CHECKLIST.md` tracking, Story/Paper config parity emphasis, and validation guidance including optional uv CI-parity flow.
- **No impact** on sections 1–7: agent instruction/docs-only update with no runtime package code, dependency metadata, config schema, LLM routing, sub-agent lifecycle, vector-store behavior, IPC contract, or security-tooling policy changes.

### 2026-03-06 — Example scripts aligned to v0.16 and uv execution option
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Updated `examples/storycraftr_example_usage.sh` and `examples/papercraftr_example_usage.sh` with `v0.16`/canonical repository header notes and consistent execution flag support including `--use-uv` (`uv run ...`) alongside existing direct and Poetry execution modes.
- **No impact** on sections 1–7: examples-only script ergonomics update with no runtime package code, dependency, config schema, LLM, sub-agent, vector-store, IPC, or security-tooling behavior changes.

### 2026-03-06 — Getting started refresh for v0.16 and uv guidance
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Revised `docs/getting_started.md` to normalize target-version wording to `v0.16`, retain canonical GitHub repository URLs under `AICyberGuardian/storycraftr-next`, add uv-based install and optional CI-parity contributor workflow guidance, and clarify chat invocation examples.
- **No impact** on sections 1–7: docs-only update with no runtime, dependency, config schema, LLM, sub-agent, vector-store, IPC, or security-tooling behavior changes.

### 2026-03-06 — Inventory enrichment with usage guidance
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Expanded `docs/Complete StoryCraftr-Next Awesome Copilot Inventory.txt` with per-item details for all agents, skills, instructions, hooks, and workflows, including practical "what it does" and "when to use" guidance.
- **No impact** on sections 1–7: docs-only enhancement with no runtime, dependency, config schema, LLM, sub-agent, vector-store, IPC, or security-tooling behavior changes.

### 2026-03-06 — Copilot ecosystem inventory normalization
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Rewrote `docs/Complete StoryCraftr-Next Awesome Copilot Inventory.txt` into a single canonical inventory based on actual `.github/` assets, removed duplicated/conflicting sections, and corrected resource counts (agents/skills/instructions/hooks/workflows).
- **No impact** on sections 1–7: docs-only update with no runtime, dependency, config schema, LLM, sub-agent, vector-store, IPC, or security-tooling behavior changes.

### 2026-03-06 — Architecture docs cleanup and deprecation removal
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Rewrote `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md` into a concise canonical architecture reference, removed deprecated duplicate `docs/storycraftr-next_Architecture Overview.txt`, and aligned onboarding references to the cleaned architecture set.
- **No impact** on sections 1–7: docs-only cleanup with no runtime, config, dependency, IPC, LLM, vector-store, or security-tooling behavior changes.

### 2026-03-06 — Architecture onboarding consolidation for junior developers
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Added `docs/architecture-onboarding.md` as a concise, canonical onboarding map that consolidates key architecture context and points to source-of-truth files for structure, runtime flow, and CI model.
- **No impact** on sections 1–7: documentation-only addition; no runtime code, dependency, config schema, LLM, sub-agent, vector-store, IPC, or security-tooling behavior changes.

### 2026-03-06 — Repository link and docs target version alignment
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:** Updated repository links in `README.md`, `docs/getting_started.md`, `CONTRIBUTING.md`, and `SECURITY.md` to `AICyberGuardian/storycraftr-next`; updated `CONTRIBUTING.md` clone command to the canonical repository, removed a non-canonical external GitHub link in `CODE_OF_CONDUCT.md`, and updated `docs/getting_started.md` development target to `0.16.0-dev`.
- **No impact** on sections 1–7: documentation-only link/version corrections.

### 2026-03-06 — v0.16 target normalization
- **Sections reviewed:** 1 (Dependency and Lockfile Integrity), 8 (Documentation & Versioning)
- **Impact:** Bumped project version metadata to `0.16.0-dev` via `scripts/bump-version.sh` (`pyproject.toml`, `package.json`, `package-lock.json`, `CHANGELOG.md`), and updated development-target references across docs/instructions to `v0.16.x`/`0.16.0-dev`.
- **No impact** on sections 2–7: no runtime config schema, LLM routing, sub-agent lifecycle, vector-store contract, extension IPC behavior, or security-tooling policy changes.

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

### Lock Coverage Decision Matrix (Phase 0.5)

| Module | Mutation Type | Shared Runtime State | Lock Required | Decision | Rationale |
|---|---|---:|---:|---|---|
| `storycraftr/init.py` | Project scaffolding + config/template writes | Yes | Yes | Patched | Initializes canonical project state that can race with assistant/vector bootstrap and role seeding. |
| `storycraftr/integrations/vscode.py` | JSONL append events | Yes | Yes | Patched | Shared event stream consumed concurrently by CLI and extension watchers. |
| `storycraftr/vectorstores/chroma.py` | Vector-store dir create/reset-on-failure | Yes | Yes | Patched | Shared persisted retrieval state; concurrent create/reset must serialize. |
| `storycraftr/utils/cleanup.py` | Vector-store recursive delete | Yes | Yes | Patched | Deletes shared persisted retrieval state used by runtime assistant. |
| `storycraftr/cmd/paper/abstract.py` | One-off section directory creation | No | No | Safe single-writer path | Main content writes already route through `save_to_markdown` lock path; directory ensure is command-local. |
| `storycraftr/cmd/paper/publish.py` | Output artifact directory creation + external tool output | No | No | Safe single-writer path | Export artifacts are non-authoritative runtime state; command intentionally run as single writer. |
| `storycraftr/pdf/renderer.py` | Output PDF write | No | No | Not shared runtime state | Generates derived publish artifact only; no impact on assistant/sub-agent mutable state. |
| `storycraftr/llm/credentials.py` | User home credential persistence | No (project-scoped) | No (project lock) | Defer with rationale | Uses user-level secret storage outside project paths; requires separate credential-store locking strategy if needed. |

- 2026-03-06: Python 3.13 governance and CI consistency hardening.
- Impact: Aligned `.github/workflows/pytest.yml` and `.github/workflows/pre-commit.yml` to Python `3.13`, added explicit Python-baseline assertions, and kept `uv`-based install acceleration in CI.
- Impact: Pinned third-party workflow actions to immutable commit SHAs in `pytest.yml`, `pre-commit.yml`, and `ci-failure-fix.yml`.
- Impact: Scoped autonomous `ci-failure-fix` execution away from `main`/`release/*` and same-repository branch guardrails.
- Impact: Added workflow-governance items to `.github/pull_request_template.md`.
- Impact: Fixed `pyproject.toml` config drift by moving `line-length`/`target-version` into `[tool.black]` and targeting `py313`.
- Impact: Synchronized development-target references in `README.md` and `release_notes.md` to `0.16.0-dev`, and documented Python `3.13.x` runtime requirement in `README.md`.
- No impact: Story/Paper command behavior, LLM routing semantics, sub-agent lifecycle payload schemas, and vector-store persistence contract.
- 2026-03-06: CI supply-chain hardening — replaced `curl | bash` uv install with `astral-sh/setup-uv@v5` GitHub Action in `pytest.yml` and `pre-commit.yml`; pinned `actions/setup-python` to immutable SHA. Python line-length doc corrected from 79 to 88 chars.
- No impact: Runtime behavior, dependency specifications, lockfiles, and application semantics.
- 2026-03-06: Python 3.13 compliance — deprecated import removal and dependency floor bump.
- Impact: Removed three deprecated langchain import paths in `storycraftr/agent/agents.py`; updated minimum dep floors for `langchain-openai`, `chromadb`, `huggingface-hub`, `sentence-transformers`, `torch`; converted `pyproject.toml` to `[tool.poetry]` format; regenerated `poetry.lock` content-hash.
- No impact: Runtime command semantics, LLM provider routing, sub-agent execution, credential resolution precedence, vector store schema, and VS Code extension IPC contract.
