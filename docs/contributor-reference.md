# Contributor Reference

This file is the single shareable reference for contributors and AI agents who
need to know:

- which files explain the project
- which files are mandatory before changing code
- which files are user-facing, area-specific, deep reference, or informational
- which files must be kept in sync when the codebase changes

This document does not replace repository rules. The source of truth for change
impact tracking remains `docs/CHANGE_IMPACT_CHECKLIST.md`.

## Minimum Mandatory Reading Set

For most code changes, read these first:

1. `docs/architecture-onboarding.md`
2. `AGENTS.md`
3. `.github/copilot-instructions.md`
4. `docs/CHANGE_IMPACT_CHECKLIST.md`

Read `README.md` too if the change affects install flow, CLI/TUI behavior,
configuration examples, or public workflow descriptions.

## File Catalog

| File | Category | Summary | Update When |
| --- | --- | --- | --- |
| `docs/contributor-reference.md` | shared-reference | Single shareable catalog of contributor docs, categories, and update-sync rules. | Contributor documentation map, file categories, or maintenance rules change. |
| `docs/architecture-onboarding.md` | contributor-entry | Shortest trustworthy onboarding path; explains what to read first and how the system is laid out. | Contributor workflow, reading order, architecture summary, or doc categorization changes. |
| `AGENTS.md` | canonical-contract | Repo invariants, dependency/version rules, testing expectations, security rules, and contributor conventions. | Repo process, invariants, testing policy, or contributor rules change. |
| `.github/copilot-instructions.md` | canonical-contract | Deep engineering contract for repo-aware coding agents; architecture, pitfalls, invariants, and checklist rules. | Architecture contracts, coding-agent workflow, or implementation constraints change. |
| `docs/CHANGE_IMPACT_CHECKLIST.md` | universal-update | Mandatory impact log and lock-coverage source of truth. | Every repository change. Add impact or explicit no-impact rationale. |
| `README.md` | user-facing | Main public product overview, install/setup flow, config examples, CLI/TUI feature surface, contributor entry point. | Public behavior, install, config, commands, UX, or contributor onboarding messaging changes. |
| `CONTRIBUTING.md` | contributor-guide | Generic contribution process and PR workflow. | Contribution process or contributor entry guidance changes. |
| `CHANGELOG.md` | user-facing | User-visible shipped and unreleased changes. | Behavior changes that matter to users or developers. Also required for version bumps. |
| `release_notes.md` | release-facing | Draft release narrative and grouped highlights. | Release messaging or notable user-facing changes need summarizing. |
| `SECURITY.md` | area-specific | Credential handling, provider safety, secret hygiene, and vulnerability reporting. | Auth, credentials, networking, endpoints, or secret-handling behavior changes. |
| `docs/getting_started.md` | user-facing | Detailed onboarding walkthrough with setup and workflow examples. | Setup steps, runtime flow, config examples, or new user workflows change. |
| `docs/chat.md` | user-facing | Chat and TUI command behavior, session UX, and interactive workflows. | Chat commands, TUI commands, session behavior, or prompt-flow UX changes. |
| `docs/advanced.md` | area-specific | Advanced or non-default usage guidance. | Advanced config or expert workflows change. |
| `docs/iterate.md` | area-specific | Iterate workflow semantics and command usage. | Iterate commands or flow behavior changes. |
| `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md` | deep-reference | Long-form architecture reference for subsystem depth; not part of the routine must-read set. | Deep architecture details, code map, or technical reference content changes. |
| `docs/python-3.13-full-stack-upgrade-matrix.md` | area-specific | Runtime and dependency version matrix for upgrade work. | Python/runtime/dependency baseline or upgrade notes change. |
| `.github/agents/storycraftr-engineering.agent.md` | area-specific | Repo-specific AI engineering agent contract and workflow. | AI-agent guidance, repo-specific engineering flow, or supported validation path changes. |
| `src/event-contract.ts` | sync-contract | Typed VS Code event payload contract. | Backend event payload shape, event names, or extension contract changes. |
| `src/event-contract.test.ts` | sync-contract | Regression tests for the extension event contract. | `src/event-contract.ts` or backend JSONL payload behavior changes. |
| `pyproject.toml` | dependency-manifest | Python dependencies, scripts, and pytest config. | Python deps, package metadata, scripts, or version change. |
| `poetry.lock` | lockfile | Locked Python dependency graph. | `pyproject.toml` changes; regenerate via `make sync-deps`. |
| `package.json` | dependency-manifest | Extension dependencies, npm scripts, and package metadata. | Node deps, scripts, package metadata, or version change. |
| `package-lock.json` | lockfile | Locked Node dependency graph. | `package.json` changes; regenerate via `make sync-deps`. |
| `docs/chat-modernization-plan.md` | informational | Planning/history doc for chat modernization ideas. | Only if that plan itself is being maintained. |
| `docs/langchain-refactor-plan.md` | informational | Planning/history doc for LangChain refactor work. | Only if that plan itself is being maintained. |
| `docs/langchain-graph-plan.md` | informational | Planning/history doc for graph design or refactor ideas. | Only if that plan itself is being maintained. |
| `docs/pdf-generation-plan.md` | informational | Planning/history doc for PDF-related work. | Only if that plan itself is being maintained. |
| `docs/subagents-plan.md` | informational | Planning/history doc for sub-agent work. | Only if that plan itself is being maintained. |

## High-Value Runtime Contract Files

| File | Summary | Update When |
| --- | --- | --- |
| `storycraftr/cmd/control_plane.py` | Grouped Click commands for automation/headless workflows (tui/state/canon/mode/models). | Control-plane command behavior, Click group structure, or runtime service integration changes. |
| `storycraftr/services/control_plane.py` | Shared control-plane service implementations (`mode_show_impl`, `mode_set_impl`, `state_audit_impl`, `canon_check_impl`) used by both CLI and TUI. | Any changes to runtime mode persistence, canon-check semantics, or state-audit query behavior that must stay consistent across CLI/TUI. |
| `storycraftr/llm/factory.py` | Provider validation plus OpenRouter retry, backoff, and fallback behavior. | Provider startup, model validation, retry logic, or fallback chain behavior changes. |
| `storycraftr/llm/openrouter_discovery.py` | Dynamic OpenRouter free-model discovery, user-local cache, cache metadata, and forced refresh helpers. | OpenRouter catalog fetch, cache TTL/fallback, or model discovery diagnostics change. |
| `storycraftr/llm/model_context.py` | Model context-window and completion-limit resolution used by prompt budgeting. | Budget computation, registry defaults, or discovery-driven context resolution changes. |
| `storycraftr/utils/paths.py` | Canonical project path resolver for internal state directories and runtime files. | Internal path resolution contract, runtime state layout, or project structure changes. |
| `storycraftr/utils/project_lock.py` | Cross-process write-lock coordination for project mutation safety. | Lock acquisition contract, reentrancy behavior, or flock coordination changes. |
| `storycraftr/agent/execution_mode.py` | Shared execution-mode policy model (`ExecutionMode`, `ModeConfig`) and gate helpers for manual/hybrid/autopilot runtime behavior. | Mode enums, policy flags, autopilot limits, or gate helper semantics change. |
| `storycraftr/agent/narrative_state.py` | JSON-backed structured narrative state store (characters, world facts) with prompt rendering. | Narrative state schema, JSON persistence contract, or prompt injection format changes. |
| `storycraftr/agent/state_extractor.py` | Deterministic prose-to-patch extraction for character movement and inventory-drop events. | Extraction heuristics, emitted patch shape, or deterministic parsing behavior changes. |
| `storycraftr/agent/memory_manager.py` | Optional Mem0-backed long-term narrative memory adapter with Chroma local storage, env-based runtime controls, and prompt-context retrieval. | Memory persistence/retrieval behavior, Mem0 integration contract, env toggle semantics, or fallback behavior changes. |
| `storycraftr/agent/state_audit.py` | Append-only audit trail logging of all narrative state mutations with timestamps, actor attribution, and queryable filters. | Audit log schema, JSONL persistence contract, query filter API, or audit entry structure changes. |
| `storycraftr/agent/generation_pipeline.py` | Role-isolated sequential scene generation pipeline (planner → drafter → editor) with bounded JSON repair and artifact capture. | Pipeline stage prompts, planner JSON parsing, repair logic, or stage artifact schema changes. |
| `storycraftr/prompts/craft_rules.py` | Deterministic loader for static craft-rule prompt fragments (no RAG dependency). | Static prompt fragment loading contract or craft-rule file paths change. |
| `storycraftr/prompts/planner_rules.md` | Corpus-derived static prompt fragment for planner-stage storytelling mechanics. | Universal planner craft rules or scene directive constraint guidance changes. |
| `storycraftr/prompts/drafter_rules.md` | Corpus-derived static prompt fragment for drafter-stage prose guidelines. | Universal drafting mechanics or prose-quality baseline changes. |
| `storycraftr/prompts/editor_rules.md` | Corpus-derived static prompt fragment for editor-stage revision rules. | Universal revision mechanics or consistency/pacing guidelines changes. |
| `storycraftr/tui/session.py` | TUI runtime session serialization for mode config and autopilot turn counters with legacy key compatibility. | Runtime session schema, `to_dict`/`from_dict`, or execution-mode persistence behavior changes. |
| `storycraftr/agent/story/scene_planner.py` | Deterministic scene Goal/Conflict/Stakes/Outcome/Ending Beat planning for focused generation. | Scene planning schema, deterministic extraction logic, or prompt template changes. |
| `storycraftr/tui/context_builder.py` | Budgeted prompt composition, deterministic pruning, section assembly, stage-aware diagnostics metadata, and static craft-rule injection for planner/drafter/editor stages. | Prompt section priority, truncation strategy, adaptive compaction heuristics, craft-rule injection, or diagnostics fields change. |
| `storycraftr/tui/state_engine.py` | Read-only narrative state extraction, prompt composition orchestration, and diagnostics persistence. | Narrative state parsing, canon ledger integration, or prompt assembly/orchestration changes. |
| `storycraftr/tui/canon.py` | Chapter-scoped canon ledger helpers for writer-approved continuity constraints. | Canon ledger schema, persistence format, or chapter-scoped constraint behavior changes. |
| `storycraftr/tui/canon_extract.py` | Conservative canon candidate extraction for hybrid review workflow. | Candidate extraction heuristics, hybrid mode integration, or pending queue behavior changes. |
| `storycraftr/tui/canon_verify.py` | Fail-closed canon candidate verification (duplicate and negation conflict detection). | Verification logic, conflict detection rules, or autopilot commit gates changes. |
| `storycraftr/tui/app.py` | Slash-command router, writer-visible diagnostics, execution mode persistence, sequential pipeline orchestration with planner directive debug toggle and fail-closed fallback reuse, and adaptive compaction orchestration. | TUI commands, diagnostics UX, execution modes, session compaction behavior, sequential pipeline generation, or canon continuity commands change. |
| `storycraftr/subagents/jobs.py` | Background sub-agent lifecycle including cooldown and retry for model exhaustion. | Job lifecycle, retry checkpoints, or cooldown metadata changes. |
| `tests/unit/test_narrative_state.py` | Regression coverage for narrative state store CRUD operations and prompt rendering. | `storycraftr/agent/narrative_state.py` behavior changes. |
| `tests/unit/test_state_extractor.py` | Regression coverage for deterministic prose extraction into patch operations. | `storycraftr/agent/state_extractor.py` behavior changes. |
| `tests/unit/test_state_audit.py` | Regression coverage for audit trail logging, entry querying, and filter API. | `storycraftr/agent/state_audit.py` behavior changes. |
| `tests/unit/test_generation_pipeline.py` | Regression coverage for sequential pipeline stage prompts, planner JSON parsing with bounded repair, and artifact capture. | `storycraftr/agent/generation_pipeline.py` behavior changes. |
| `tests/unit/test_scene_planner.py` | Regression coverage for deterministic scene planning extraction. | `storycraftr/agent/story/scene_planner.py` behavior changes. |
| `tests/unit/test_openrouter_discovery.py` | Regression coverage for discovery cache, metadata, and free-model parsing behavior. | `storycraftr/llm/openrouter_discovery.py` behavior changes. |
| `tests/unit/test_tui_app.py` | Regression coverage for TUI slash commands, diagnostics surfaces, canon commands, and adaptive compaction. | `storycraftr/tui/app.py` behavior changes. |
| `tests/unit/test_tui_state_engine.py` | Regression coverage for state engine prompt composition and diagnostics persistence. | `storycraftr/tui/state_engine.py` behavior changes. |
| `tests/unit/test_tui_context_builder.py` | Regression coverage for budgeted prompt assembly and section pruning. | `storycraftr/tui/context_builder.py` behavior changes. |
| `tests/unit/test_tui_canon.py` | Regression coverage for canon ledger persistence and chapter-scoped operations. | `storycraftr/tui/canon.py` behavior changes. |
| `tests/unit/test_tui_canon_extract.py` | Regression coverage for canon candidate extraction in hybrid mode. | `storycraftr/tui/canon_extract.py` behavior changes. |
| `tests/unit/test_tui_canon_verify.py` | Regression coverage for fail-closed canon verification (duplicate and conflict detection). | `storycraftr/tui/canon_verify.py` behavior changes. |
| `tests/unit/test_project_lock.py` | Regression coverage for project write lock reentrancy and cross-process coordination. | `storycraftr/utils/project_lock.py` behavior changes. |

## Update Rules By Change Type

### Always

- `docs/CHANGE_IMPACT_CHECKLIST.md`

### Dependency Changes

- `pyproject.toml` -> `poetry.lock`
- `package.json` -> `package-lock.json`
- Use `make sync-deps`; do not hand-edit lockfiles.

### Version Changes

- `pyproject.toml`
- `package.json`
- `package-lock.json`
- `CHANGELOG.md`

### User-Facing Behavior Changes

- `README.md`
- `docs/getting_started.md`
- `docs/chat.md`
- `CHANGELOG.md`
- `release_notes.md` when the release narrative should reflect the change

### Contributor Workflow Or Repo Contract Changes

- `AGENTS.md`
- `.github/copilot-instructions.md`
- `docs/architecture-onboarding.md`
- `docs/contributor-reference.md`
- `.github/agents/storycraftr-engineering.agent.md` when that agent contract is used

### Security-Sensitive Changes

- `SECURITY.md`
- Relevant user docs when the behavior is externally visible

### VS Code Event Contract Changes

- `src/event-contract.ts`
- `src/event-contract.test.ts`
- Relevant backend emitters and user/developer docs when visible

## Practical Categories

### User-Facing

- `README.md`
- `docs/getting_started.md`
- `docs/chat.md`
- `CHANGELOG.md`
- `release_notes.md`

### Area-Specific

- `SECURITY.md`
- `docs/advanced.md`
- `docs/iterate.md`
- `docs/python-3.13-full-stack-upgrade-matrix.md`
- `.github/agents/storycraftr-engineering.agent.md`

### Deep Reference

- `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`

### Informational

- `docs/chat-modernization-plan.md`
- `docs/langchain-refactor-plan.md`
- `docs/langchain-graph-plan.md`
- `docs/pdf-generation-plan.md`
- `docs/subagents-plan.md`

## Notes For AI Agents

- Start with the minimum mandatory reading set, not the full docs tree.
- Treat `docs/CHANGE_IMPACT_CHECKLIST.md` as mandatory on every change.
- Treat `AGENTS.md` and `.github/copilot-instructions.md` as canonical contracts.
- Use the deep reference only when subsystem depth is actually needed.
- `AGENTS.md` still references `behavior.txt`, but the runtime and project
  templates use project-local behavior files under `behaviors/default.txt`.

### Recent Architecture Context

- **Canon Guard**: Chapter-scoped fact ledger (`outline/canon.yml`) with duplicate/negation conflict detection; fail-closed verification gates autopilot commits.
- **Narrative State**: Structured character/world state (`outline/narrative_state.json`) with prompt injection via `[Structured Narrative State]` section and version-aware headers (DSVL Phase 1C, 2C).
- **Audit Trail**: Append-only mutation log (`outline/narrative_audit.jsonl`) with DSVL Phase 2A query API, queryable by entity/type with `/state audit` TUI command (DSVL Phase 2B).
- **State Extraction & Verification**: Deterministic prose-to-patch extraction (`storycraftr/agent/state_extractor.py`) with fail-closed verification, operation-order retry, and unsafe-operation dropping (DSVL Phase 3-4).
- **State-Critic Regeneration**: Bounded single regeneration attempt in hybrid/autopilot modes when extraction verification detects state transition errors; constrained revision prompt includes canon and state diagnostics (Phase 5).
- **Long-Term Memory Layer**: Optional Mem0 integration stores turn memories and retrieves compact intent/event context for prompt enrichment; runtime controls and diagnostics are exposed via env toggles plus `/context memory` and CLI `storycraftr memory` commands; failures degrade safely to no-op behavior.
- **Control-Plane Service Layer**: Shared `storycraftr/services/control_plane.py` for mode controls, state audit, and extraction verification logic used by both CLI and TUI to prevent behavior drift (Phase 2B).
- **Adaptive Compaction**: Rolling session summaries preserve high-signal narrative anchors (scene boundaries, canon-relevant turns, reveals, entity introductions).
- **TUI Execution Modes**: `manual`, `hybrid`, `autopilot` with persistence in `sessions/session.json`; `/autopilot` is bounded and mode-gated.
- **Project Write Locking**: Cross-process coordination via `project_write_lock` (reentrant within thread, file-locked across processes).
- **Path Resolution**: Use `storycraftr/utils/paths.py::resolve_project_paths()` for all internal state paths; never hardcode `.storycraftr/` literals.
- **Prompt Diagnostics**: `PromptDiagnostics` metadata tracks included/pruned/truncated sections with token estimates for observability without generation changes.
