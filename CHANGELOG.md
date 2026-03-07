# Changelog

## [Unreleased]

### Added

- **DSVL Phase 1A: Validated Narrative State Schema** — Added Pydantic-based validation models (`CharacterState`, `LocationState`, `PlotThreadState`) with strict field validation, model-level invariant enforcement, and cross-entity reference validation. Replaced unvalidated dict-based state with type-safe models while maintaining backward compatibility with legacy "world" field. Comprehensive test suite with 30 validation tests ensures schema integrity and rejection of invalid state transitions.
- **DSVL Phase 1B: Deterministic State Diff Engine** — Added `state_diff.py` module with `DiffType` enum, `FieldDiff`, `EntityDiff`, and `StateChangeset` dataclasses for tracking field-level and entity-level changes between narrative state snapshots. `compute_state_diff()` function provides deterministic diff computation with sorted output for characters, locations, plot threads, and world dict changes. Comprehensive test suite with 16 diff detection tests ensures reliable change tracking.

### Changed

- Updated `docs/contributor-reference.md` with comprehensive runtime contract file catalog reflecting recent architecture: added Canon Guard files (`canon.py`, `canon_extract.py`, `canon_verify.py`), narrative state module (`narrative_state.py`), project locking (`project_lock.py`), path resolution (`paths.py`), scene planner, and their corresponding test files. Enhanced "Notes For AI Agents" with Canon Guard, narrative state, adaptive compaction, TUI execution modes, project write locking, and prompt diagnostics context.
- Added Phase A Textual TUI ergonomics: `/clear` output reset command, `ctrl+l` focus mode toggle, Up/Down command history navigation, and inline slash-command status markers (`[Running]`, `[Done]`, `[Failed]`).
- Added TUI workflow guidance commands: `/progress` for file-backed checkpoint status and `/wizard` (`/wizard next`) for canonical next-step recommendations based on project artifacts.
- Added smart grouped TUI command help (`Writing`, `Planning`, `World`, `Project`) with topic filtering via `/help <topic>`, plus `/pipeline` (`/pipeline next`) as a wizard alias.
- Expanded wizard guidance with profile-based planning commands (`/wizard set`, `/wizard show`, `/wizard plan`, `/wizard reset`) that generate advisory command sequences without auto-running them.
- Added Canon Guard Phase 1 in the TUI/state layer: chapter-scoped `outline/canon.yml` ledger, `/canon` command group (`show`, `add`, `clear confirm`), and prompt injection of accepted canon facts under `[Canon Constraints]`.
- Added TUI execution modes with persistence (`/mode <manual|hybrid|autopilot>`) backed by `sessions/session.json`, plus a visible mode indicator in the TUI footer region.
- Added Hybrid Canon extraction in TUI: when mode is `hybrid`, assistant responses queue pending canon candidates on the sub-agent worker pool for review via `/canon pending`, `/canon accept <n[,m,...]>`, and `/canon reject [n[,m,...]]` before ledger commit.
- Added Priority 3 prompt optimization: scene-scoped prompt assembly with deterministic scene planning (`Goal`, `Conflict`, `Outcome`) and bounded `[Scoped Context]` construction for lower-token, higher-focus generation.
- Added Priority 4 autopilot safety loop: `/autopilot <steps> <prompt>` is now mode-gated (`/mode autopilot`) and autopilot canon candidate commits require fail-closed chapter verification (duplicate and negation-conflict detection).
- Added Priority 0 prompt-overflow guardrails in TUI prompt composition: model-aware input budgeting now resolves an effective context profile per active model, reserves completion tokens, and applies deterministic pruning order (`[Active Constraints]` -> scene/scoped state -> recent turns -> retrieval chunks -> lower-priority strips).
- Added a small in-repo model-context fallback registry (`storycraftr/llm/model_context.py`) with conservative defaults; OpenRouter context/max-completion limits now come from live discovery first and only fall back to registry defaults when discovery data is unavailable.
- Added Priority 1 OpenRouter resilience in `storycraftr/llm/factory.py` via a native wrapper that applies bounded exponential-backoff retries for transient failures and an explicit fallback model chain.
- Added dynamic OpenRouter free-model discovery (`storycraftr/llm/openrouter_discovery.py`) backed by `GET https://openrouter.ai/api/v1/models`, user-local cache (`~/.storycraftr/openrouter-models-cache.json`), default 6-hour TTL, stale-cache fallback, and a minimal emergency fallback profile.
- OpenRouter factory startup now enforces strict free-only model validation for both primary and fallback model IDs; paid/unknown/unavailable model IDs are rejected before provider initialization.
- Added `STORYCRAFTR_OPENROUTER_FALLBACK_MODELS` (comma-separated model IDs) to configure fallback order; `openrouter/free` is included as a conservative terminal fallback when the primary model differs.
- Added OpenRouter discovery UX updates: `storycraftr model-list` (`--refresh`) plus TUI `/model-list refresh` with context/max-completion visibility.
- Added Priority 1 rolling session compaction in the TUI: older transcript turns are collapsed into a bounded persisted `Session Summary` (in `sessions/session.json`) and injected as budgeted context while keeping the latest turns verbatim.
- Expanded TUI runtime diagnostics under `/context` with subcommands: `/context summary`, `/context budget`, `/context models`, `/context clear-summary`, and `/context refresh-models`, plus a compact overview on bare `/context`.
- Added prompt-composition observability metadata wiring for diagnostics: latest budget snapshot, section prune/truncation markers, and per-section estimated usage reporting without changing generation behavior.
- Added OpenRouter cache metadata diagnostics (`cache_status`, `last_refresh`, `age`, `free_model_count`, `cache_path`) via `storycraftr/llm/openrouter_discovery.py::get_cache_metadata` for `/context models`.
- Added Priority 2 structured prompt section schema for TUI generation: `[Canon Constraints]`, `[Scene Plan]`, `[Scoped Context]`, `[Session Summary]`, `[Recent Dialogue]`, and `[User Instruction]` to improve adherence and diagnostics readability.
- Added Priority 3 minimal canon conflict detection in normal TUI chat turns: post-generation output now runs a warn-only chapter-canon check and surfaces `Potential Canon Conflicts` for likely duplicate or negation-contradiction statements.
- Expanded canon continuity tooling with `/canon check-last` plus `/context conflicts` diagnostics, including grouped duplicate vs negation-conflict counts and detailed evidence lines.
- Added adaptive session compaction heuristics in the TUI so rolling summaries preserve high-signal narrative anchors (scene boundaries, canon-relevant turns, major reveals, and new-entity introductions).
- Added structured narrative-state support via `storycraftr/agent/narrative_state.py` (`outline/narrative_state.json`) and prompt injection under `[Structured Narrative State]` when project state data is available.
- Added sub-agent model exhaustion handling: background jobs now emit a `model_exhausted` checkpoint on transient provider exhaustion/rate-limit failures, wait through a bounded cooldown, and retry once before final failure.
- Extended the Textual TUI command UX with a state-driven layout: hidden-by-default project tree (toggle via `ctrl+t` or `/toggle-tree`), Narrative + Timeline strips, chapter/scene focus commands (`/chapter <number>`, `/scene <label>`), and OpenRouter model commands (`/model-list`, `/model-change <model_id>`).
- Added read-only narrative context extraction in `storycraftr/tui/state_engine.py` (chapter frontmatter + optional outline YAML arc mapping) and prompt-prefix state injection in the TUI layer before assistant dispatch.
- Added `/state` TUI command to expose the current narrative state snapshot and exact injected prompt block for user-auditable transparency.
- Hardened `storycraftr/tui/state_engine.py` parsing paths to safely degrade on malformed chapter frontmatter or invalid outline YAML files instead of crashing the TUI loop.
- Added focused unit tests for TUI help/command parsing and OpenRouter free-model metadata filtering/parsing (`tests/unit/test_tui_app.py`, `tests/unit/test_tui_openrouter_models.py`).
- Added a minimal Textual-based TUI shell at `storycraftr/tui/app.py` that reuses existing assistant/chat dispatch logic without modifying core agent/vector/sub-agent behavior.
- Added module launch support for the TUI via `python -m storycraftr.tui.app` with optional `--book-path` argument parsing.
- Phase 0 runtime-safety hardening:
  - Performed a small architectural extraction by moving assistant cache management from `storycraftr/agent/agents.py` into `storycraftr/agent/assistant_cache.py` (cache key normalization, lock-guarded lookup/store, shared cache state).
  - Performed a second small architectural extraction by moving vector-store refresh/hydration helpers from `storycraftr/agent/agents.py` into `storycraftr/agent/vector_hydration.py` and wiring `LangChainAssistant.ensure_vector_store` through the extracted helper functions.
  - Preserved backward compatibility for existing tests/internals by keeping `agents.load_markdown_documents(...)` and `agents._dedupe_documents(...)` as compatibility wrappers that delegate to `vector_hydration`.
  - Synced canonical architecture docs (`.github/copilot-instructions.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`) to match current typed-config semantics and extracted module boundaries.
  - Preserved backward compatibility for existing tests/internals by keeping `agents._ASSISTANT_CACHE`, `agents._ASSISTANT_CACHE_LOCK`, and `_assistant_cache_key(...)` as compatibility aliases/wrapper.
  - Updated cache-focused unit fixtures in `tests/unit/test_agents_create_message.py` to use typed `BookConfig` inputs.
  - Completed a project write-lock coverage audit for runtime mutation paths and closed remaining gaps:
    - `init_structure_story` and `init_structure_paper` now wrap project scaffolding/config/template writes under `project_write_lock`.
    - `VSCodeEventEmitter.emit` now appends JSONL events under `project_write_lock` to prevent cross-process append races.
    - `cleanup_vector_stores` now removes persisted vector-store directories under `project_write_lock`.
    - `build_chroma_store` now performs store-directory creation and failure cleanup under `project_write_lock`.
  - Fixed nested lock deadlock risk by making `project_write_lock` reentrant within the same thread for a lock path while preserving cross-process `flock` behavior.
  - Added lock regression tests in `tests/unit/test_init_locks.py`, `tests/unit/test_project_lock.py`, `tests/unit/test_cleanup.py`, `tests/unit/test_core_paths.py`, and `tests/unit/test_vscode_integration.py`.
  - Added an explicit lock-scope decision matrix in `docs/CHANGE_IMPACT_CHECKLIST.md` to classify remaining mutation paths as must-lock, safe single-writer, non-shared runtime state, or deferred with rationale.
  - Completed typed-config migration for runtime config consumers by replacing `getattr(config, ...)` fallbacks with explicit `BookConfig` attributes across core mapping, assistant prompt composition, chat footer metadata, markdown/pdf rendering metadata, project-path resolution, and sub-agent role seeding.
  - Added typed path-override fields to `BookConfig` (`internal_state_dir`, `subagents_dir`, `subagent_logs_dir`, `sessions_dir`, `vector_store_dir`, `vscode_events_file`) so internal-path configuration remains explicit and testable.
  - Added extension-side event-contract fixtures in TypeScript (`src/event-contract.ts`, `src/event-contract.test.ts`) for representative JSONL events: `session.started`, `chat.turn`, `session.ended`, `sub_agent.roles`, `sub_agent.status`, `sub_agent.queued`, and `sub_agent.error`.
  - Expanded vector-store edge-case hardening in `LangChainAssistant.ensure_vector_store` and regressions in `tests/unit/test_agents_vectorstore_integrity.py` covering retriever-corruption recovery via forced rebuild, reset-failure fallback cleanup path, unreadable/short markdown handling, duplicate document deduplication, force rebuild idempotency, and empty-corpus force rebuild safety.
  - Assistant cache key handling in `storycraftr/agent/agents.py` now normalizes `model_override` and protects cache reads/writes with a re-entrant lock to reduce override bleed and race conditions.
  - Added project-scoped mutation locking via `storycraftr/utils/project_lock.py`; Chroma reset/rebuild and document ingestion writes are now guarded by a file lock under internal state (`project.lock`).
  - Expanded project lock coverage to additional mutating paths: prompt metadata log writes, session transcript saves, markdown save/append/consolidation outputs, sub-agent role seeding, and sub-agent run log persistence.
  - `load_book_config` now returns a typed `BookConfig` model with normalization/coercion for core config fields while preserving attribute-style compatibility expected by existing call sites.
  - Sub-agent role loading is hardened: malformed YAML and invalid role payloads are skipped safely instead of crashing role discovery (`storycraftr/subagents/storage.py`, `storycraftr/subagents/models.py`).
  - Added targeted regression tests for assistant cache keying/normalization, typed config output, and invalid sub-agent role handling.
  - Fixed `chat --prompt` VS Code event lifecycle symmetry by emitting `session.ended` before command return in non-interactive mode; added a CLI regression test asserting prompt-mode event sequence and required payload fields.
  - Added dedicated sub-agent command event-contract tests (`tests/unit/test_chat_commands.py`) to lock event names and payload schemas for `sub_agent.roles`, `sub_agent.status`, `sub_agent.queued`, and `sub_agent.error`.
  - Added vector-store integrity regressions (`tests/unit/test_agents_vectorstore_integrity.py`) for empty-corpus failure handling, deterministic `force=True` rebuild behavior, and non-empty-store reindex bypass in `LangChainAssistant.ensure_vector_store`.
  - Removed import-time credential loading side effect in `storycraftr/cli.py` by introducing lazy one-time bootstrap (`_ensure_local_credentials_loaded`) executed from the Click group callback; added startup regressions in `tests/unit/test_cli_startup.py`.
- Current development target set to `v0.16` (`0.16.0-dev`).
- CI dependency installation modernized for speed and determinism:
  - `.github/workflows/pytest.yml` now uses `astral-sh/setup-uv@v5` native cache, validates `poetry export` availability, exports requirements from `poetry.lock`, installs with `uv pip`, and runs `npm ci` before extension compile.
  - `.github/workflows/pytest.yml` `embeddings-smoke` now uses the same `poetry export` + `uv pip` flow for embeddings extras.
  - `.github/workflows/pytest.yml` and `.github/workflows/pre-commit.yml` remove expensive disk cleanup steps (`jlumbroso/free-disk-space`) to eliminate startup bottlenecks.
  - `setup-uv` cache invalidation is now keyed to repository dependency files (`poetry.lock` for pytest jobs, `pyproject.toml` for pre-commit), avoiding stale/default cache-key behavior.
  - `.github/workflows/pre-commit.yml` now uses cached `setup-uv` without curl-based bootstrap and removes redundant secondary disk-space maximization to reduce startup latency.
- Documentation links and install examples were aligned to the canonical repository (`AICyberGuardian/storycraftr-next`) across `README.md`, `docs/getting_started.md`, `CONTRIBUTING.md`, and `SECURITY.md`; `docs/getting_started.md` development target was updated to `0.16.0-dev`.
- Added explicit `max_tokens` support (default `8192`) across config loading and LLM settings mapping, and now pass it directly to OpenAI/OpenRouter `ChatOpenAI` clients to reduce truncation risk.
- Added a targeted `iterate chapter` command for surgical single-chapter rewrites, while keeping `check-consistency` as a global batch workflow.
- **Python 3.13 upgrade**: bumped the project's Python baseline from `>=3.10,<3.13` to `>=3.13,<3.14`.
  - Updated `pyproject.toml` `python` constraint and Black `target-version` to `py313`.
  - Updated CI workflows (`pytest.yml`, `pre-commit.yml`) to use Python 3.13.
  - Regenerated `poetry.lock` for the new baseline.
- **Python 3.13 Compliance — Dependency & Import Modernisation**:
  - Replaced deprecated `langchain.schema.Document` import in `storycraftr/agent/agents.py` with `langchain_core.documents.Document` (canonical location since langchain 0.2).
  - Replaced deprecated `langchain.text_splitter.RecursiveCharacterTextSplitter` import with `langchain_text_splitters.RecursiveCharacterTextSplitter`; added `langchain-text-splitters` as an explicit direct dependency in `pyproject.toml`.
  - Replaced deprecated `langchain_community.vectorstores.Chroma` import with `langchain_chroma.Chroma`, aligning the type annotation in `LangChainAssistant` with the concrete type returned by `build_chroma_store`.
  - Updated minimum dependency version bounds in `pyproject.toml` to reflect Python 3.13-compatible floor versions:
    - `langchain-openai >= 0.3.0` (aligns with openai SDK 1.x compatibility layer).
    - `chromadb >= 1.0.0` (1.0 introduced a new persistent-client API used throughout `vectorstores/chroma.py`; 0.5.x is incompatible).
    - `huggingface-hub >= 0.30.0` (required for Python 3.13 wheel availability).
    - `sentence-transformers >= 3.0.0` (3.x added Python 3.13 support and a revised inference API).
    - `torch >= 2.5.0` (first PyTorch release with published Python 3.13 wheels).
  - Regenerated `poetry.lock` via `make sync-deps` to record updated content-hash and resolved dependency updates.
  - Added `textual >=8.0.2` and synchronized related lockfile updates (including `rich` `14.3.3` and transitive Markdown/linkify dependencies).
  - Updated `uv venv` creation in CI to explicitly target Python 3.13 (`--python 3.13`).
  - Regenerated `poetry.lock` for the new baseline.

### Fixed

- Made `project_write_lock` tolerant of mocked file handles by falling back to process-local locking when `fileno()` is missing or non-integer, preserving real-file `flock` behavior.
- Stabilized `tests/unit/test_subagents.py::test_job_manager_persist_job_uses_project_write_lock` by asserting lock usage through the deterministic `_persist_job()` seam instead of real worker-future timing.

## [0.15.1] - 2026-03-04

### Changed

- Added deterministic task-runner workflows via `Makefile`:
  - `make sync-deps` for atomic Python/Node lock refresh.
  - `make check-locks` for local lock-file consistency verification.
  - `make bump-version VERSION=...` for synchronized version updates.
- Added enforcement scripts:
  - `scripts/bump-version.sh` to update `pyproject.toml`, `package.json`, `package-lock.json`, and changelog development target line.
  - `scripts/check-version-bump.sh` to block partial version bump commits.
- Expanded `.pre-commit-config.yaml` with local invariant hooks:
  - Poetry lock consistency check.
  - NPM lock consistency check.
  - Version-bump staged-file invariant check.
- Hardened CI enforcement in `.github/workflows/pytest.yml` and `.github/workflows/pre-commit.yml`:
  - Added Node setup for lock validation.
  - Added lock-file drift guard (`git diff --exit-code poetry.lock package-lock.json`).
- Codified repository invariants in `AGENTS.md` and `.github/copilot-instructions.md`, including mandatory `make sync-deps` usage for routine dependency sync operations.
- Hardened credential storage fallback behavior:
  - `store_local_credential` now falls back to legacy files under `~/.storycraftr` when OS keyring backends are unavailable, while preserving environment > keyring > legacy read precedence.
  - Keyring backend unavailability warnings are emitted once per process instead of repeating for every credential lookup.
- Improved `storycraftr init` behavior-file validation with clearer missing-file guidance and aligned docs/examples.
- Hardened embedding initialization in `storycraftr/llm/embeddings.py`:
  - Lazy-loads ML stack dependencies at runtime to avoid CLI startup penalties.
  - Resolves `embed_device=auto` explicitly to `cuda`, then `mps`, then `cpu`.
  - Raises `LLMConfigurationError` with actionable install instructions when local ML dependencies are missing.

## [0.14.0] - 2026-03-03

### Added

- **Secure Credential Helper**: Added `store_local_credential` in `storycraftr.llm.credentials` so provider secrets can be stored in the OS keyring instead of plaintext files.
- **Targeted Regression Tests**: Added unit test modules covering LLM factory validation, credential loading precedence, and provider-aware model defaults:
  - `tests/unit/test_llm_factory.py`
  - `tests/unit/test_credentials.py`
  - `tests/unit/test_llm_config.py`

### Changed

- **LLM Factory Validation Hardening**:
  - Added explicit preflight checks in `storycraftr.llm.factory.build_chat_model` for provider, model, endpoint URL shape, temperature range, and timeout positivity.
  - Added provider-specific exception classes (`LLMConfigurationError`, `LLMAuthenticationError`, `LLMInitializationError`) for clearer failure modes.
  - Wrapped provider client construction errors to prevent ambiguous runtime failures.
- **OpenRouter Model Selection Enforcement**:
  - OpenRouter now requires an explicit `llm_model` in `provider/model` format (for example, `meta-llama/llama-3.3-70b-instruct`).
  - Generic fallbacks for OpenRouter model names are no longer accepted; invalid or missing model identifiers fail fast before generation starts.
- **Provider Endpoint Resolution**:
  - OpenRouter endpoint resolution now follows: `llm_endpoint` -> `OPENROUTER_BASE_URL` -> `https://openrouter.ai/api/v1`.
  - Endpoint values are validated as full `http(s)` URLs before provider initialization.
- **Configuration Mapping Behavior**:
  - `storycraftr.utils.core.load_book_config` and `llm_settings_from_config` now apply provider-aware model defaults.
  - Default model fallback (`gpt-4o`) is only auto-applied for OpenAI when `llm_model` is absent; OpenRouter no longer inherits that fallback.
- **Sub-Agent Concurrency and Failure Handling**:
  - `SubAgentJobManager` now uses a re-entrant lock for safer concurrent lifecycle updates.
  - Job submissions retain `Future` references and inspect completion callbacks to surface executor-level crashes.
  - `_run_job` now logs unexpected exceptions with stack traces, preserves stderr in output, and marks persistence failures as explicit failed jobs.
  - `shutdown(wait=False)` now cancels pending jobs using a stable future snapshot, preventing dictionary-mutation races while callbacks run.
  - Cancelled pending jobs are persisted and surfaced as failed jobs with explicit cancellation diagnostics instead of silently disappearing.
- **Message Orchestration Separation**:
  - `create_message` was decomposed into focused helpers that separately handle prompt content construction, prompt metadata persistence, LangChain graph invocation, and thread/progress bookkeeping.
  - This keeps graph execution isolated from metadata-writing concerns and improves testability of each stage.
- **Path Debt Remediation**:
  - Added centralized project path resolution in `storycraftr.utils.paths.resolve_project_paths` and migrated hardcoded runtime directories to config-rooted paths (`subagents`, `sessions`, VS Code events, and `vector_store`).
  - Updated sub-agent storage/job management, session persistence, vector cleanup, Chroma persistence, and assistant document-loading filters to consume dynamic path resolution from project configuration.
  - Affected runtime modules include:
    - `storycraftr/subagents/storage.py`
    - `storycraftr/subagents/jobs.py`
    - `storycraftr/chat/session.py`
    - `storycraftr/integrations/vscode.py`
    - `storycraftr/vectorstores/chroma.py`
    - `storycraftr/utils/cleanup.py`
    - `storycraftr/agent/agents.py`
    - `storycraftr/utils/core.py`

### Security

- **Credential Loading Order Updated**:
  - `load_local_credentials` now resolves secrets in secure-first order:
    1. Existing environment variables
    2. OS keyring (`storycraftr` service by default, overridable via `STORYCRAFTR_KEYRING_SERVICE`)
    3. Legacy plaintext files in `~/.storycraftr` and `~/.papercraftr` (compatibility fallback)
- **Legacy Plaintext Fallback Warning**:
  - When legacy key files are used, CLI output now warns users to migrate credentials into OS keyring storage.

### Dependencies

- Added `keyring >=25.6.0` to `pyproject.toml` for secure local credential management.

### Documentation

- Updated credential and provider docs to reflect the new security and routing contract:
  - `README.md`
  - `docs/getting_started.md`
  - `docs/chat.md`
  - `AGENTS.md`
  - `docs/langchain-refactor-plan.md`
  - `SECURITY.md`
  - `release_notes.md`

### Test Updates

- Updated `tests/test_cli.py` credential test to mock keyring unavailability and preserve deterministic legacy fallback assertions.
- Added regression coverage for background job failure paths and orchestration boundaries:
  - `tests/unit/test_subagents.py`
  - `tests/unit/test_agents_create_message.py`
- Added OpenRouter-focused factory tests and graph mock tests:
  - `tests/unit/test_llm_factory.py`
  - `tests/unit/test_assistant_graph.py`
- Added deterministic concurrency, path-invariant, and CLI smoke coverage:
  - `tests/unit/test_subagent_jobs.py` (`shutdown(wait=False)` cancellation behavior with `threading.Event`)
  - `tests/unit/test_core_paths.py` (custom `internal_state_dir` resolution for sub-agent logs, sessions, vector store, and VS Code event feed)
  - `tests/integration/test_cli_smoke.py` (`storycraftr init` with isolated filesystem and mocked LLM bootstrap)

## [0.10.1-beta4] - 2024-11-01

### Added

- **OpenAI Model and URL Configuration**: Added support for specifying the OpenAI model and URL in the configuration file and during project initialization.
- **Supported LLMs Documentation**: Included documentation for various LLMs compatible with the OpenAI API, such as DeepSeek, Qwen, Gemini, Together AI, and DeepInfra.
- **Behavior File Enhancements**: Improved the behavior file to guide the AI's writing process more effectively, ensuring alignment with the writer's vision.
- **Interactive Chat Enhancements**: Enhanced the chat feature to support more dynamic interactions and command executions directly from the chat interface.

## [0.10.1-beta4] - 2024-10-30

### Added

- **Support for PaperCraftr**: Major refactor to extend support for PaperCraftr, a CLI aimed at academic paper writing. Users can now initialize paper projects with a dedicated structure, distinct from book projects, for enhanced productivity in academic writing.
- **Multiple Prompt Support**: Implemented multi-purpose prompts for both book and paper creation, allowing users to generate and refine content for different aspects such as research questions, contributions, and outlines.
- **Define Command Extensions**: Added new commands under the `define` group to generate key sections for papers, including defining research questions and contributions.
- **Contribution Generation**: Added the `define_contribution` command to generate or refine the main contribution of a paper, supporting improved clarity and focus for academic projects.

## [0.10.1-beta4] - 2024-03-14

### Added

- **Interactive Chat with Commands**: Enhanced chat functionality now allows users to interact with StoryCraftr using direct command prompts, helping with outlining, world-building, and chapter writing.
- **Documentation-Driven Chat**: StoryCraftr's documentation is fully loaded into the system, allowing users to ask for help with commands directly from within the chat interface.
- **Improved User Interface**: New UI elements for an enhanced interactive experience. Chat commands and documentation queries are more intuitive.

![Chat Example](https://res.cloudinary.com/dyknhuvxt/image/upload/v1729551304/chat-example_hdo9yu.png)

## [0.6.1-alpha2] - 2024-02-29

### Added

- **VSCode Extension Alpha**: Launched an alpha version of the StoryCraftr extension for VSCode, which automatically detects the `storycraftr.json` file in the workspace and launches a terminal for interacting with the StoryCraftr CLI.

## [0.6.0-alpha1] - 2024-02-22

### Added

- **VSCode Terminal Chat**: Chat functionality embedded into the VSCode extension, allowing users to launch a terminal directly from VSCode and interact with StoryCraftr.

## [0.5.2-alpha1] - 2024-02-15

### Added

- **Multi-command Iteration**: New CLI functionality allowing iterative refinement of plot points, character motivations, and chapter structures.

## [0.5.0-alpha1] - 2024-02-01

### Added

- **Insert Chapter Command**: Users can now insert chapters between existing ones and automatically renumber subsequent chapters for seamless story progression.

## [0.4.0] - 2024-01-20

### Added

- **Story Iteration**: Introduced the ability to iterate over various aspects of your book, including refining character motivations and checking plot consistency.
- **Flashback Insertion**: Users can now insert flashback chapters that automatically adjust surrounding chapters.

## [0.3.0] - 2024-01-10

### Added

- **Outline Generation**: Generate detailed story outlines based on user-provided prompts.
- **World-Building**: New commands to generate history, geography, culture, and technology elements of your book’s world.

## [0.2.0] - 2023-12-15

### Added

- **Behavior Guidance**: A behavior file that helps guide the AI's understanding of the writing style, themes, and narrative focus of your novel.

## [0.1.0] - 2023-11-28

### Added

- **Initial Release**: Base functionalities including chapter writing, character summaries, and basic outline generation.

---

StoryCraftr has come a long way from simple chapter generation to enabling an entire AI-powered creative writing workflow. With interactive chats, rich command sets, and VSCode integration, it’s now easier than ever to bring your stories to life!
