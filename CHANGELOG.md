# Changelog

## [Unreleased] - 2026-03-03

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
