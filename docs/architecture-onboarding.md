# Developer Onboarding and Reading Guide

This file is the contributor-facing consolidation point for StoryCraftr.
If you are new to the repo or about to change code, start here.

## Why This Exists

Some repo docs are canonical contracts, some are deep references, and some are
historical planning notes. This file reduces that sprawl into a smaller,
practical reading set.

## Minimum Mandatory Set

For most code changes, the required reading set is only:

1. `docs/architecture-onboarding.md` (this file)
2. `AGENTS.md`
3. `.github/copilot-instructions.md`
4. `docs/CHANGE_IMPACT_CHECKLIST.md`

Read `README.md` as part of the mandatory set only when your change affects:
- install/setup instructions
- CLI or TUI user-facing behavior
- configuration examples
- public workflow descriptions

Do not require the long architecture reference for routine changes.

For the file-by-file catalog and update matrix, use
`docs/contributor-reference.md`.

## System In One View

StoryCraftr is a dual-mode Python CLI (`storycraftr` and `papercraftr`) plus a
VS Code extension.

Main runtime flow:
1. CLI entrypoint routes mode and command.
2. Config is loaded from `storycraftr.json` or `papercraftr.json`.
3. LLM and embeddings are built from config.
4. Chroma vector store is created or reused for retrieval.
5. LangChain graph executes retrieval plus generation.
6. Chat/session/sub-agent events are emitted to JSONL for VS Code.

Config note:
`load_book_config()` returns a typed `BookConfig`; runtime code should use
explicit attributes.

## Core Code Map

- `storycraftr/cli.py`: dual-mode command routing and bootstrap.
- `storycraftr/cmd/`: command handlers for story, paper, and chat.
- `storycraftr/cmd/control_plane.py`: grouped Click commands for automation and headless workflows (tui/state/canon/mode/models).
- `storycraftr/services/control_plane.py`: shared control-plane service layer used by both CLI commands and TUI slash commands for mode, canon-check, and state-audit operations.
- `storycraftr/agent/agents.py`: assistant lifecycle, message creation, orchestration glue.
- `storycraftr/agent/assistant_cache.py`: assistant cache keying and lock-guarded cache state.
- `storycraftr/agent/vector_hydration.py`: vector-store refresh/hydration and markdown ingestion helpers.
- `storycraftr/graph/assistant_graph.py`: LCEL retrieval plus answer graph.
- `storycraftr/llm/factory.py`: provider selection/validation plus OpenRouter retry/backoff/fallback wrapper.
- `storycraftr/llm/openrouter_discovery.py`: dynamic OpenRouter free-model discovery, limits metadata, cache diagnostics, and user-local cached catalog.
- `storycraftr/llm/model_context.py`: dynamic-first model-limit resolution (OpenRouter) plus conservative fallback registry and input-budget computation helpers.
- `storycraftr/llm/credentials.py`: env -> keyring -> legacy fallback credential lookup.
- `storycraftr/llm/embeddings.py`: embedding model creation.
- `storycraftr/vectorstores/chroma.py`: persistent Chroma setup.
- `storycraftr/utils/paths.py`: canonical runtime path resolver.
- `storycraftr/subagents/jobs.py`: background role-based job execution.
- `storycraftr/integrations/vscode.py`: JSONL event emission.
- `storycraftr/agent/execution_mode.py`: shared execution-mode policy model (`ExecutionMode`, `ModeConfig`) and policy helpers for runtime gates.
- `storycraftr/agent/narrative_state.py`: Pydantic-validated narrative state store with character, location, and plot-thread entities. Includes patch validation and application, and version-aware prompt rendering with metadata headers (DSVL Phase 1A-1C, 2C).
- `storycraftr/agent/state_extractor.py`: deterministic prose-to-state extraction with validation-ready `StatePatch` proposals. Includes verification pass that fails closed on unsafe operations (e.g., dead-character movement), performs bounded operation-order retry, and drops unsafe operations (DSVL Phase 3-4).
- `storycraftr/agent/state_audit.py`: append-only audit trail logging of all state mutations with timestamped entries, queryable filters by entity/type, and actor attribution (DSVL Phase 2A).
- `storycraftr/services/control_plane.py`: shared service layer for runtime mode controls, state-audit queries, canon verification checks, and extraction verification/retry logic. Both CLI commands and TUI slash commands call shared implementations to prevent behavior drift (Phase 2B).
- `storycraftr/tui/app.py`: Textual terminal command center and slash-command router with `/state audit` subcommand for audit history inspection (DSVL Phase 2B). Includes bounded state-critic regeneration retry in `_generate_with_mode_awareness()` when extraction verification detects unsafe state transitions (Phase 5).
- `storycraftr/tui/session.py`: TUI runtime-session state serialization (`mode_config`, `autopilot_turns_remaining`) with backward-compatible runtime metadata handling.
- `storycraftr/tui/canon.py`: chapter-scoped canon ledger helpers for writer-approved constraints.
- `storycraftr/tui/canon_extract.py`: conservative canon-candidate extraction for hybrid review.
- `storycraftr/tui/canon_verify.py`: fail-closed canon candidate verification for autopilot commits.
- `storycraftr/tui/context_builder.py`: scene-scoped prompt assembly, model-aware budgeting, deterministic pruning, and diagnostics metadata.
- `storycraftr/tui/state_engine.py`: read-only narrative state extraction and prompt orchestration with diagnostics output.
- `storycraftr/agent/story/scene_planner.py`: deterministic scene Goal/Conflict/Outcome planning helper.
- `src/extension.ts`: VS Code event stream watcher and UI integration.
- `src/event-contract.ts`: typed event parser and contract for extension event payloads.
- `src/event-contract.test.ts`: event-contract regression tests.

## Runtime Files and State

At project level:
- `storycraftr.json` or `papercraftr.json`: runtime configuration.
- Markdown content (`chapters/`, `outline/`, `worldbuilding/`, etc.): user source corpus.
- `vector_store/`: Chroma persistence.
- `outline/canon.yml`: chapter-scoped canon ledger with writer-approved continuity facts; verified for duplicate/negation conflicts during autopilot commits.
- `outline/narrative_state.json`: structured narrative state store with validated character, location, and plot-thread entities (DSVL Phase 1A-1C).
- `outline/narrative_audit.jsonl`: append-only audit trail logging all state mutations with timestamps and actor attribution (DSVL Phase 2A).

Internal state (resolved via `resolve_project_paths`):
- `.storycraftr/subagents/`
- `.storycraftr/sessions/`
   - `session.json` stores lightweight runtime metadata such as TUI execution mode and rolling session summary state.
- `.storycraftr/vscode-events.jsonl`

TUI autonomy note:
- `/mode` controls manual, hybrid, and autopilot execution behavior.
- `/mode autopilot <max_turns>` sets bounded autopilot turn budget and persists remaining turns.
- `/stop` forces manual mode and clears remaining autopilot turns.
- `/autopilot` only runs when mode is `autopilot` and performs bounded steps.
- Canon commits in autopilot flow are verified against accepted chapter facts and skip duplicate or conflicting candidates.
- Post-generation state extraction runs in preview mode in all flows; if verification reports unsafe state transitions (e.g., dead-character location change), hybrid/autopilot modes request one bounded critic regeneration before applying state patches or advancing autonomy (Phase 5).
- `/summary` and `/context` expose compaction, prompt-budget, pruning, and OpenRouter model-cache diagnostics to keep model-aware pruning visible to writers.
- `/state` displays current narrative state snapshot with version and timestamp (DSVL Phase 2C).
- `/state extract-last [apply]` shows last extraction attempt including verification status, issues, and dropped operations; optional `apply` commits verified patches to narrative state.
- `/state audit [limit=<n>] [entity=<id>] [type=<character|location|plot_thread>]` queries audit trail with optional filters for entity ID, entity type, and result limit (DSVL Phase 2B).
- Sub-agent workers checkpoint transient provider exhaustion as `model_exhausted`, apply bounded cooldown, and retry once before terminal failure.

Do not hardcode these paths; use `storycraftr/utils/paths.py`.

## Build and CI Mental Model

Local dev:
- Python: `poetry install`, `poetry run pytest`
- Extension: `npm install`, `npm run compile`

CI model:
- Uses uv plus Poetry export (`poetry export` -> `uv pip install`) for deterministic installs.
- Lockfile drift is treated as a failure condition.

## What To Read By Change Type

Always consult:
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `docs/CHANGE_IMPACT_CHECKLIST.md`
- Current code under `storycraftr/` and `src/`

Read when the change touches these areas:
- `README.md`: install flow, public CLI or TUI behavior, config examples
- `SECURITY.md`: auth, credentials, networking, provider config, secret handling
- `docs/getting_started.md`: onboarding UX, setup examples, runtime walkthrough
- `docs/chat.md`: chat and TUI command behavior
- `docs/advanced.md`: advanced or non-default configuration
- `docs/iterate.md`: iterate workflow semantics
- `docs/python-3.13-full-stack-upgrade-matrix.md`: dependency or runtime version changes
- `.github/agents/storycraftr-engineering.agent.md`: repo-specific engineering agent workflow

Deep reference, not part of the minimum mandatory set:
- `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`

Informational or history only:
- `docs/chat-modernization-plan.md`
- `docs/langchain-refactor-plan.md`
- `docs/langchain-graph-plan.md`
- `docs/pdf-generation-plan.md`
- `docs/subagents-plan.md`

## 60-Minute Learning Path

1. Read this file.
2. Read `AGENTS.md` for repo rules and operating model.
3. Read `.github/copilot-instructions.md` for architecture contracts and pitfalls.
4. Read `docs/CHANGE_IMPACT_CHECKLIST.md` so you know the required review path.
5. If your change is user-facing, read `README.md` and the relevant area doc (`docs/getting_started.md` or `docs/chat.md`).
6. Trace one command end-to-end:
   - Start at `storycraftr/cli.py`
   - Follow into `storycraftr/cmd/chat.py`
   - Follow into `storycraftr/agent/agents.py`
   - Follow into `storycraftr/graph/assistant_graph.py`
7. Validate understanding by running:
   - `poetry run storycraftr --help`
   - `poetry run pytest`

## Junior Dev Starter Pack

Give a new developer these files in this order:

1. `docs/architecture-onboarding.md`
2. `AGENTS.md`
3. `.github/copilot-instructions.md`
4. `README.md`
5. `docs/getting_started.md`
6. `docs/chat.md`
7. `SECURITY.md`
8. `docs/CHANGE_IMPACT_CHECKLIST.md`

Only after that should they read:
- `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`

## Known Documentation Gap

`AGENTS.md` still references `behavior.txt` as canonical for agent behavior
changes, while the repository now ships behavior defaults under `behaviors/`
(for example `behaviors/default.txt`). Treat the `behavior.txt` wording as a
legacy reference until the contract text is normalized.
