## Draft Update - 2026-03-07 (Dynamic OpenRouter Discovery, Prompt Budgeting, and Sub-Agent Cooldown)

Current development target: `v0.16` (`0.16.0-dev`).

### Highlights

- Added dynamic OpenRouter free-model discovery (`storycraftr/llm/openrouter_discovery.py`) using `GET https://openrouter.ai/api/v1/models`, with user-local cache at `~/.storycraftr/openrouter-models-cache.json`, default 6-hour TTL, stale-cache fallback, and a minimal emergency fallback profile.
- Added strict free-only OpenRouter startup validation in `storycraftr/llm/factory.py`: paid/unknown/unavailable model IDs are rejected before provider initialization for both primary and fallback models.
- Updated model-aware prompt budgeting in the TUI prompt path to use live-discovered OpenRouter limits first (context length + max completion), with conservative in-repo fallback defaults in `storycraftr/llm/model_context.py`.
- Added native OpenRouter resilience in `storycraftr/llm/factory.py` with bounded retry/backoff and configurable fallback traversal (`STORYCRAFTR_OPENROUTER_FALLBACK_MODELS`).
- Added model discovery visibility commands: `storycraftr model-list` (`--refresh`) and TUI `/model-list refresh`, with model limit output (`context_length`, `max_completion_tokens`).
- Added rolling TUI session compaction that preserves recent turns verbatim while collapsing older turns into a persisted summary in `sessions/session.json`.
- Added TUI diagnostics commands `/summary` (`/summary clear`) and `/context` (`summary`, `budget`, `models`, `clear-summary`, `refresh-models`) for writer-visible prompt-budget, pruning, summary, and OpenRouter cache introspection.
- Added sub-agent `model_exhausted` lifecycle checkpoint handling in `storycraftr/subagents/jobs.py`: transient rate-limit/capacity failures now checkpoint, cooldown, and retry once before terminal failure.
- Added job metadata persistence for retry diagnostics (`attempts`, `cooldown_until`) and surfaced `model_exhausted` counts in chat footer status rendering.
- Synchronized canonical and user-facing docs (`README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `.github/copilot-instructions.md`, and `docs/CHANGE_IMPACT_CHECKLIST.md`).

For complete line-item history, see `CHANGELOG.md` and `docs/CHANGE_IMPACT_CHECKLIST.md`.

## Draft Update - 2026-03-06 (CI, TUI UX, and Documentation Sync)

Current development target: `v0.16` (`0.16.0-dev`).

### Highlights

- CI dependency installation is now modernized for speed and determinism across pytest and pre-commit workflows.
- The pytest pipeline now follows the cached `setup-uv` + `poetry export` + `uv pip` installation path and runs `npm ci` before extension compilation.
- Embeddings smoke checks use the same export-and-install pattern, and CI fails fast when `poetry export` support is unavailable.
- Legacy curl-based uv bootstrap has been removed, and redundant pre-commit startup steps were trimmed to reduce latency.
- Expensive disk cleanup actions were removed from pytest and pre-commit workflows to remove startup bottlenecks.
- `setup-uv` cache invalidation now maps to repository dependency files (`poetry.lock`/`pyproject.toml`) for more reliable reuse across runs.
- Project documentation was synchronized with this CI convention (`README.md`, `CHANGELOG.md`, `AGENTS.md`, `.github/copilot-instructions.md`).
- Repository links and install snippets were normalized to `AICyberGuardian/storycraftr-next`, and `docs/getting_started.md` now reflects development target `0.16.0-dev`.
- Python runtime dependencies were refreshed to include `textual` with synchronized lockfile updates.
- Textual TUI command UX now includes grouped `/help`, `/status`, `/mode <manual|hybrid|autopilot>`, `/autopilot <steps> <prompt>`, `/state`, `/progress`, `/wizard` (`/wizard next`), `/pipeline` (`/pipeline next`), `/model-list` (free OpenRouter discovery), and `/model-change <model_id>` (session-level model switch).
- Execution mode is persisted in `sessions/session.json` and surfaced in the footer region as `[ MODE: MANUAL|HYBRID|AUTOPILOT ]` to harden safety before autonomous features.
- The Textual TUI shifted to a writer-focused state-driven UX: hidden-by-default file tree (`/toggle-tree` or `ctrl+t`), Narrative/Timeline strips, `/chapter` and `/scene` focus commands, `/state` transparency command, and scene-scoped prompt-prefix context assembly implemented entirely in the TUI layer (`storycraftr/tui/state_engine.py`) with chapter-scoped `[Active Constraints]` when canon facts are present.
- Canon Guard Phase 1 is available in the TUI via `/canon`, `/canon show [chapter]`, `/canon add <fact>`, `/canon add <chapter> :: <fact>`, `/canon pending`, `/canon accept <n[,m,...]>`, `/canon reject [n[,m,...]]`, and `/canon clear [confirm]`, backed by `outline/canon.yml`.
- Prompt optimization now uses a scene-scoped context builder and deterministic scene planning (Goal/Conflict/Outcome) to reduce token bloat before generation.
- Added a mode-gated `/autopilot <steps> <prompt>` loop for bounded autonomous turns. Canon candidates extracted during autopilot are conflict-verified against accepted chapter facts and skip duplicate/conflicting commits.
- Narrative state parsing now degrades safely when chapter frontmatter or outline YAML files are malformed, preventing UI-loop crashes.
- Sub-agent lock regression test `tests/unit/test_subagents.py::test_job_manager_persist_job_uses_project_write_lock` now uses a deterministic persistence seam assertion (`_persist_job()`) instead of worker timing.

For full step-level details, see `CHANGELOG.md` under `[Unreleased]`.

### Merge Readiness Notes

- Workflow YAML diagnostics are clean for updated files.
- Lockfile immutability checks are preserved in CI.
- Final merge confidence remains contingent on green GitHub Actions runs.

## Draft Update - 2026-03-03 (Security, Reliability, and Path Hardening)

Current development target: `v0.16` (`0.16.0-dev`).

### Highlights

- Hardened `build_chat_model` with provider-specific validation and explicit failure classes.
- Enforced explicit OpenRouter model identifiers in `provider/model` format via project config (`llm_model`).
- Migrated credential loading to secure-first order: environment variables -> OS keyring -> legacy plaintext files.
- Added `store_local_credential` helper for OS keyring persistence.
- Hardened sub-agent background job execution with explicit lifecycle locking, crash visibility, and failure persistence.
- Fixed `SubAgentJobManager.shutdown(wait=False)` cancellation race conditions and now persist cancellation failures explicitly.
- Refactored `create_message` to separate prompt assembly/metadata writing from LangChain graph invocation and thread bookkeeping.
- Removed hardcoded runtime storage paths by introducing config-rooted path resolution for sub-agent files/logs, sessions, VS Code event stream, and vector store persistence/cleanup.
- Expanded unit coverage for factory validation and credential loading precedence.
- Added mock-based graph tests for retrieval + prompt assembly without live API calls.
- Added deterministic tests for sub-agent shutdown cancellation, custom runtime path invariants, and CLI init smoke execution (`tests/unit/test_subagent_jobs.py`, `tests/unit/test_core_paths.py`, `tests/integration/test_cli_smoke.py`).
- Updated user and contributor docs (`README.md`, `docs/getting_started.md`, `docs/chat.md`, `AGENTS.md`, `SECURITY.md`, `docs/langchain-refactor-plan.md`, `CHANGELOG.md`).

# PaperCraftr 0.10.1-beta4

## 🎉 Major Release: Complete Command Implementation

We're excited to announce the release of PaperCraftr 0.10.1-beta4, which marks a significant milestone in the development of our academic paper writing tool. This release implements all the core commands that were previously missing, providing a complete workflow for academic paper creation and management.

## ✨ New Features

### 📝 Abstract Generation
- Added `abstract generate` command to create abstracts for different journals
- Implemented `abstract keywords` command to generate relevant keywords
- Added support for multiple languages in abstract generation

### 📚 Reference Management
- Implemented `references add` command to add new references
- Added `references format` command to format references in BibTeX
- Created `references check` command to verify citation consistency

### 📋 Outline and Organization
- Added `outline outline-sections` command to generate paper structure
- Implemented `organize-lit lit-summary` command to organize literature review
- Created `organize-lit lit-map` command to visualize research connections

### 📄 Section Generation
- Implemented `generate section` command to create paper sections
- Added support for generating specific sections (introduction, methodology, etc.)
- Integrated with AI to produce high-quality academic content

### 📊 Publishing
- Enhanced `publish pdf` command with improved LaTeX template
- Added support for IEEE format papers
- Implemented translation options for multilingual papers

## 🔧 Improvements

- Streamlined project structure for better organization
- Enhanced LaTeX template with IEEE format support
- Improved markdown consolidation process
- Added metadata support for abstracts and keywords
- Optimized file structure for academic paper writing

## 🐛 Bug Fixes

- Fixed issues with reference formatting
- Resolved problems with LaTeX compilation
- Addressed inconsistencies in section generation
- Fixed translation issues in multilingual papers

## 📚 Documentation

- Updated documentation for all implemented commands
- Added examples for each command
- Created comprehensive guides for paper writing workflow
- Improved error messages and user feedback

## 🔄 Workflow

PaperCraftr now supports a complete academic paper writing workflow:

1. Initialize a new paper project
2. Generate an outline and organize literature
3. Create abstracts and keywords
4. Generate paper sections
5. Add and format references
6. Publish the final paper in PDF format

## 🚀 Getting Started

To get started with PaperCraftr 0.10.1-beta4:

```bash
# Initialize a new paper project
papercraftr init my-paper

# Generate an outline
papercraftr outline outline-sections

# Create an abstract
papercraftr abstract generate

# Generate paper sections
papercraftr generate section introduction

# Add references
papercraftr references add "Author, Title, Journal, Year"

# Publish your paper
papercraftr publish pdf
```

## 🙏 Acknowledgments

Thank you to all contributors and users who provided feedback during the development of this release. Your input has been invaluable in creating a comprehensive academic paper writing tool.

## 🔜 Next Steps

We're already working on the next release, which will include:

- Enhanced collaboration features
- More journal templates
- Advanced citation analysis
- Integration with reference management systems

Stay tuned for more updates! 
