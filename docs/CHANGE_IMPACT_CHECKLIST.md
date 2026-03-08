# Change Impact Checklist

## Change History

### 2026-03-08 — CLI model-list test ANSI normalization
- **Sections reviewed:** 8 (Documentation & Versioning contract review)
- **Impact:**
	- Updated `tests/test_cli.py` `test_model_list_command_outputs_limits` to normalize ANSI escape sequences before asserting table row text.
	- Preserves colored CLI output behavior while making test assertions deterministic across environments where Rich emits style codes.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile updates, no runtime prompt/agent behavior changes, no config/schema changes, no sub-agent/vector-store/event-contract changes, no security tooling changes).

### 2026-03-08 — Static craft-rule prompt injection + DSVL schema extension
- **Sections reviewed:** 3, 8 (Prompt/Runtime Behavior and Documentation & Versioning)
- **Impact:**
	- Extended `storycraftr/agent/narrative_state.py` DSVL models with Story Engine character fields (`ghost`, `character_lie`, `external_want`, `internal_need`) and added validated `SceneDirective` schema (`goal`, `conflict`, `stakes`, `outcome`).
	- Updated `storycraftr/agent/story/scene_planner.py` to validate generated scene directives against DSVL `SceneDirective` before prompt assembly.
	- Added `storycraftr/agent/generation_pipeline.py` and wired TUI generation in `storycraftr/tui/app.py` through role-isolated planner -> drafter -> editor passes with bounded planner JSON repair.
	- Added planner directive debug controls in `storycraftr/tui/app.py` via `/context prompt debug [on|off]`, including explicit planner directive logging in runtime output.
	- Hardened fail-closed planner behavior in `storycraftr/tui/app.py`: if planner JSON parsing fails after bounded repair, runtime reuses the last validated `SceneDirective` when available and emits a warning.
	- Added static corpus-derived craft-rule fragments: `storycraftr/prompts/planner_rules.md`, `storycraftr/prompts/drafter_rules.md`, and `storycraftr/prompts/editor_rules.md`.
	- Added deterministic loader `storycraftr/prompts/craft_rules.py` and wired it into `storycraftr/tui/state_engine.py` startup/prompt composition.
	- Updated `storycraftr/tui/context_builder.py` and `storycraftr/tui/app.py` to expose stage-aware prompt diagnostics, including new `/context prompt` output and planner/drafter/editor section telemetry in budget breakdown.
	- Added/updated tests in `tests/unit/test_generation_pipeline.py`, `tests/unit/test_narrative_state.py`, `tests/unit/test_tui_app.py`, `tests/unit/test_tui_context_builder.py`, and `tests/unit/test_tui_state_engine.py`, including an integration-style TUI turn test covering sequential pipeline output + state extraction + canon warning.
	- Synced docs in `docs/chat.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema file changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-08 — Development target bump to v0.19 (`0.19.0-dev`)
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Bumped manifest/lock metadata to `0.19.0-dev` in `pyproject.toml`, `package.json`, and `package-lock.json` via `make bump-version VERSION=0.19.0-dev`.
	- Updated current development target references to `v0.19` (`0.19.0-dev`) across project docs and agent guidance (`README.md`, `CHANGELOG.md`, `release_notes.md`, `docs/getting_started.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `docs/index.html`, `AGENTS.md`, `.github/copilot-instructions.md`, `.github/agents/storycraftr-engineering.agent.md`, `PHASES_2B_TO_5_IMPLEMENTATION_SUMMARY.md`, and `examples/*_example_usage.sh`).
	- Updated `scripts/bump-version.sh` changelog-target matcher to support existing `vX.Y` format (and legacy `vX.Y.x`) so future bumps keep `CHANGELOG.md` in sync automatically.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no runtime behavior changes to CLI/TUI/sub-agents/provider routing/vector-store/VS Code events; no security-tooling policy changes).

### 2026-03-08 — CI stabilization: deterministic canon-conflict warning test
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `tests/unit/test_tui_app.py::test_on_input_submitted_warns_on_canon_conflicts` to monkeypatch `app._analyze_canon_conflicts` with a deterministic local report, preventing unintended external provider calls during test execution.
	- Updated the same test to monkeypatch `app._analyze_state_extraction_issues` with a deterministic local report, preventing state-critic regeneration code paths from reaching provider-authenticated runtime dependencies in CI.
	- Updated the same test to monkeypatch `app._post_generation_hooks` to a canon-only path (`_warn_about_canon_conflicts`) so memory persistence/state extraction side effects do not introduce external runtime dependencies in this unit-level assertion.
	- Verified failure reproduction and fix against the previously failing CI path (`pytest` job) and reran full suite locally.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (test-only change; no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Phase 6B: `/context memory explain` item-level diagnostics
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/agent/memory_manager.py` retrieval snapshot structure to include `selected_items` (source/text pairs) for item-level explainability.
	- Updated `storycraftr/tui/app.py::_handle_context_command` and added `_build_context_memory_explain_text` for `/context memory explain` rendering.
	- Added regression tests in `tests/unit/test_tui_app.py` and `tests/unit/test_memory_manager.py` validating explain output and retrieval snapshot payload structure.
	- Updated `docs/chat.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Phase 6B: memory retrieval telemetry diagnostics
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/agent/memory_manager.py` to track latest retrieval telemetry (`hits_returned`, `queries_run`, `queries_attempted`, `hits_by_source`, `source_order`) and expose it via `get_runtime_diagnostics()`.
	- Updated `storycraftr/tui/app.py::_build_context_memory_text` to render recall telemetry summary lines in `/context memory` diagnostics.
	- Updated `storycraftr/cmd/memory.py::memory_status` to render recall telemetry summary lines in text output while preserving JSON output compatibility.
	- Added regression tests in `tests/unit/test_memory_manager.py`, `tests/unit/test_tui_app.py`, and `tests/test_cli.py` validating telemetry population and rendering.
	- Updated `docs/chat.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Phase 6B: storyline-aware weighted memory retrieval
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/agent/memory_manager.py::get_context_items` to accept optional `active_scene` and `active_arc` hints and to prioritize retrieval in weighted order: user query -> recent chapter continuity (active + previous chapter) -> scene/arc cues -> character-state and plot-thread context -> generic intent/events.
	- Added chapter-scoped memory filters for recent continuity lookups and preserved fail-closed behavior via existing `_search` fallback semantics.
	- Updated `storycraftr/tui/state_engine.py::get_memory_context` to pass active scene/arc hints from `NarrativeState` to memory retrieval.
	- Added/updated regression coverage in `tests/unit/test_memory_manager.py` validating recent chapter filters, scene/arc hint queries, and updated source-label expectations.
	- Updated `docs/chat.md` to document storyline-aware retrieval strategy.
	- Synced release docs in `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-08 — Phase 6B: model-aware memory token budgeting
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/state_engine.py::get_memory_context` to accept optional `provider` and `model_id` parameters for dynamic budget computation.
	- Added `storycraftr/tui/state_engine.py::_compute_memory_budget` helper that scales memory budget as ~2% of model context window (160-1280 token range).
	- Updated `storycraftr/tui/state_engine.py::compose_prompt_with_diagnostics` to pass provider/model_id through to `get_memory_context()`.
	- Backward compatibility preserved: when provider/model_id are None, budgets default to previous behavior.
	- Added regression test in `tests/unit/test_tui_state_engine.py` validating budget scaling for large and small context models.
	- Updated `docs/chat.md` to document model-aware budget behavior.
	- Synced release docs in `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-08 — Phase 6B: memory persistence diagnostics
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py::_post_generation_hooks` to capture persist status (success/failed) from `state_engine.record_turn_memory()` return value instead of catching exceptions.
	- Updated `storycraftr/tui/app.py::_post_generation_hooks` to surface immediate warning in output pane when memory is enabled but persistence fails.
	- Renamed `_last_memory_persist_error` to `_last_memory_persist_status` to track success/failed state.
	- Updated `storycraftr/tui/app.py::_build_context_memory_text` to include last persist status in `/context memory` diagnostics output.
	- Added regression test in `tests/unit/test_tui_app.py` validating persist status appears in diagnostics.
	- Updated `docs/chat.md` to document memory persistence failure visibility.
	- Synced release docs in `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-08 — Phase 6B: query-aware memory retrieval
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/state_engine.py::compose_prompt_with_diagnostics` and `build_scoped_context` to pass `user_query=user_prompt` to `get_memory_context()`.
	- Updated `storycraftr/tui/state_engine.py::get_memory_context()` to accept optional `user_query` parameter and pass it through to memory manager as `query`.
	- Updated `storycraftr/agent/memory_manager.py::get_context_items()` to accept optional `query` parameter and use it as the primary semantic retrieval query before fallback queries (intent/events).
	- Added regression tests in `tests/unit/test_memory_manager.py` validating that user query is used as first retrieval source, and in `tests/unit/test_tui_state_engine.py` confirming query parameter passes through correctly.
	- Updated `docs/chat.md` to document query-aware retrieval behavior.
	- Synced release docs in `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-08 — Phase 6B: memory-context token budget guard
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/state_engine.py::get_memory_context` to enforce a deterministic memory-specific token cap (`max_tokens`) before context is merged into prompt composition.
	- Added regression coverage in `tests/unit/test_tui_state_engine.py` validating memory context is dropped when recall snippets exceed the configured memory budget.
	- Synced release docs in `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-08 — Phase 6 hardening: Mem0 toggles + memory diagnostics/CLI commands
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/agent/memory_manager.py` with explicit runtime toggles (`STORYCRAFTR_MEM0_ENABLED`, `STORYCRAFTR_MEM0_FORCE_PROVIDER`, `STORYCRAFTR_MEM0_FORCE_OPENROUTER`) and diagnostics/search helper APIs.
	- Updated `storycraftr/tui/state_engine.py` and `storycraftr/tui/app.py` to expose memory diagnostics via `/context memory`, add runtime rebind diagnostics via `/context refresh-memory`, and include memory-layer status in the `/context` overview.
	- Added `storycraftr/cmd/memory.py` with `storycraftr memory status|search|remember` for memory inspection, querying, and explicit turn persistence.
	- Added machine-friendly diagnostics output with `storycraftr memory status --format json`.
	- Added line-delimited diagnostics output with `storycraftr memory search --format ndjson` for script/CI-friendly streaming results.
	- Wired memory commands into `storycraftr/cli.py` command registration.
	- Added regression tests in `tests/unit/test_memory_manager.py`, `tests/unit/test_tui_app.py`, and `tests/test_cli.py` for toggles, diagnostics rendering, and CLI command behavior.
	- Synced docs in `README.md`, `docs/chat.md`, `docs/advanced.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Phase 6 foundation: optional Mem0 long-term memory + expanded deterministic scene directives
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/agent/memory_manager.py` as a fail-closed optional Mem0 adapter with Chroma-backed local storage under resolved internal state paths and scoped retrieval helpers.
	- Updated `storycraftr/tui/state_engine.py` to enrich prompt context with retrieved long-term memory snippets and persist post-generation turns to memory (best effort, non-blocking).
	- Updated `storycraftr/tui/app.py` to configure state-engine collaborators from runtime config and invoke memory persistence during post-generation hooks.
	- Expanded `storycraftr/agent/story/scene_planner.py` and prompt assembly (`storycraftr/tui/context_builder.py`) to include explicit scene `stakes` and `ending_beat` fields.
	- Added regression coverage in `tests/unit/test_memory_manager.py` and expanded tests in `tests/unit/test_scene_planner.py`, `tests/unit/test_tui_context_builder.py`, and `tests/unit/test_tui_state_engine.py`.
	- Synced docs in `CHANGELOG.md`, `docs/architecture-onboarding.md`, and `docs/contributor-reference.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Complete documentation sync for Phases 2B–5 (service unification, extraction, verification, state-critic regeneration)
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `docs/architecture-onboarding.md` to include Phase 2B-5 modules in Core Code Map: `storycraftr/services/control_plane.py`, extended description of `storycraftr/agent/state_extractor.py` (verification, retry logic), and phase attribution for state-critic regeneration in `storycraftr/tui/app.py`.
	- Enhanced "Runtime Files and State" section to document canonical file (`outline/canon.yml`) with phase attribution.
	- Extended "TUI autonomy note" section with post-generation state extraction workflow, state-critic retry explanation (`/state extract-last [apply]`), and phase attributions.
	- Updated `docs/contributor-reference.md` "Recent Architecture Context" section: added state extraction & verification, control-plane service layer, state-critic regeneration with phase references, and cross-references to DSVL phase numbers.
	- Created comprehensive Phase 2B–5 implementation summary in `PHASES_2B_TO_5_IMPLEMENTATION_SUMMARY.md`: detailed phase-by-phase breakdown, architectural diagrams, complete file inventory, design patterns, test coverage, developer experience improvements, migration guide, and commit status.
	- All documentation updates reinforce phase attributions, architectural relationships, and cross-references across onboarding, contributor reference, and new summary document.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (documentation-only updates with no code/runtime/lockfile/provider/event-schema/security behavior changes).

### 2026-03-07 — Phase 5: mode-gated state critic regeneration
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py::_generate_with_mode_awareness` to include a bounded state-critic pass using extraction verification diagnostics.
	- Added one constrained regeneration attempt (single retry) in hybrid/autopilot mode when extraction verification reports unsafe transitions.
	- Added helper diagnostics in `storycraftr/tui/app.py` (`_analyze_state_extraction_issues`, `_build_critic_repair_prompt`) and tracked latest state-extraction report metadata for runtime inspection.
	- Added tests in `tests/unit/test_tui_app.py` covering retry-on-state-issues and no-retry behavior in manual mode.
	- Synced docs in `README.md`, `docs/chat.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Phase 4: extraction verification and bounded retry repair
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/services/control_plane.py::state_extract_impl` to add a fail-closed verification pass for extracted `StatePatch` operations before write attempts.
	- Added one deterministic dependency-order retry for extraction operations (location adds before character mutations) and operation dropping when still unsafe.
	- Extended extraction result metadata across shared service/CLI/TUI outputs with verification status, retry-performed flag, dropped-operation count, and verification issue details.
	- Added regression test coverage in `tests/unit/test_control_plane_service.py` for dead-character movement rejection in extraction apply flow.
	- Synced docs in `README.md`, `docs/chat.md`, `release_notes.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Phase 3: deterministic state extraction integration
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/agent/state_extractor.py` for deterministic prose-to-patch extraction (character movement and inventory-drop events).
	- Extended shared services in `storycraftr/services/control_plane.py` with `state_extract_impl` for CLI/TUI parity.
	- Added `storycraftr state extract --text "..." [--apply]` in `storycraftr/cmd/control_plane.py`.
	- Updated `storycraftr/tui/app.py` to apply deterministic extraction in post-generation hooks and added `/state extract-last [apply]` preview/apply command.
	- Added regression coverage in `tests/unit/test_state_extractor.py`, `tests/unit/test_control_plane_service.py`, `tests/test_cli.py`, and `tests/unit/test_tui_app.py`.
	- Updated docs: `README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/architecture-onboarding.md`, `docs/contributor-reference.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `release_notes.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider-routing contract changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Phase 2B: CLI/TUI service unification for control-plane runtime logic
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/services/control_plane.py` with shared implementations: `mode_show_impl`, `mode_set_impl`, `state_audit_impl`, and `canon_check_impl`.
	- Refactored `storycraftr/cmd/control_plane.py` to delegate mode, canon-check, and state-audit behavior to the shared service layer.
	- Refactored `storycraftr/tui/app.py` slash-command paths (`/mode`, `/stop`, `/state audit`, canon conflict analysis) to call the same service implementations used by CLI commands.
	- Added regression tests for the shared service layer (`tests/unit/test_control_plane_service.py`) and delegation-path assertions in `tests/test_cli.py` and `tests/unit/test_tui_app.py`.
	- Updated user and architecture documentation (`README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/architecture-onboarding.md`, `docs/contributor-reference.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `release_notes.md`, and `CHANGELOG.md`).
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema updates, no provider contract changes, no sub-agent lifecycle model changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Click control-plane command surface (tui/state/canon/mode/models)
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/cmd/control_plane.py` with grouped Click commands for `tui`, `state`, `canon`, `mode`, and `models`.
	- Wired new control-plane groups into `storycraftr/cli.py` while preserving existing command compatibility (including legacy `model-list`).
	- Added CLI regressions in `tests/test_cli.py` covering mode round-trip (`show/set/stop`), grouped model listing, and state audit JSON output.
	- Updated user-facing docs (`README.md`, `docs/chat.md`, `docs/getting_started.md`) and release notes (`CHANGELOG.md`) for new command discovery and usage.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no provider routing contract changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Execution Mode Control Plane (manual/hybrid/autopilot)
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/agent/execution_mode.py` with shared `ExecutionMode` enum, `ModeConfig` policy model, and policy helpers (`allows_background_agents`, `allows_autopilot_loop`, `should_auto_regenerate_on_conflict`).
	- Added `storycraftr/tui/session.py` with `TuiSessionState` serialization (`to_dict`/`from_dict`) for `mode_config` and `autopilot_turns_remaining`, including backward-compatible support for legacy `execution_mode` runtime key.
	- Updated `storycraftr/tui/app.py` generation flow to use mode-aware gates via `_generate_with_mode_awareness()` and `_post_generation_hooks()`.
	- Updated `/mode` command to support optional autopilot limit (`/mode autopilot <max_turns>`) and added `/stop` command to force manual mode and clear remaining autopilot turns.
	- Updated autopilot loop execution to consume persisted turn budget and report remaining turns after each run.
	- Added `tests/unit/test_execution_mode.py` (6 tests) covering mode enum values, parsing, policy gates, autopilot limit clamping, and TUI session-state serialization compatibility.
	- Expanded `tests/unit/test_tui_app.py` coverage for mode command updates (`/mode autopilot <max_turns>`, `/stop`, updated help/usage strings).
	- Updated user/dev docs: `README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/architecture-onboarding.md`, `docs/contributor-reference.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no LLM provider contracts changed, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Documentation parity sync for DSVL Phase 2A/2B/2C
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `docs/architecture-onboarding.md` to include DSVL narrative state/audit modules, runtime files, and TUI autonomy notes for `/state` and `/state audit`.
	- Updated `docs/contributor-reference.md` to catalog `storycraftr/agent/state_audit.py`, `tests/unit/test_state_audit.py`, and recent architecture context for audit workflow visibility.
	- Updated user-facing TUI docs for command parity:
		- `README.md`
		- `docs/chat.md`
		- `docs/getting_started.md`
		- `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`
	- Aligned `/state` wording to version-aware state snapshot semantics and documented `/state audit [limit=<n>] [entity=<id>] [type=<character|location|plot_thread>]` filter usage.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (documentation-only updates with no code/runtime/lockfile/provider/event-schema/security behavior changes).

### 2026-03-07 — DSVL Phase 2C: Version-aware prompt injection
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Modified `render_prompt_block()` in `storycraftr/agent/narrative_state.py` to add version metadata header.
	- Header format: `[Narrative State v{version} as of {timestamp}]` prepended to JSON payload.
	- Version and timestamp extracted from `NarrativeStateSnapshot.version` and `NarrativeStateSnapshot.last_modified`.
	- Header is not counted toward `max_chars` truncation limit (truncation applies to JSON only).
	- Empty state continues to return empty string with no header (backward compatible).
	- LLMs can now reference specific narrative state versions in responses for continuity tracking.
	- Added 5 comprehensive tests to `tests/unit/test_narrative_state.py`:
		- test_render_prompt_block_includes_version_header: Validates header presence
		- test_render_prompt_block_header_format: Validates exact format
		- test_render_prompt_block_empty_returns_empty_string: Validates empty state
		- test_render_prompt_block_truncation_preserves_header: Validates truncation behavior
		- test_render_prompt_block_version_increments: Validates version tracking
	- Updated `CHANGELOG.md` with DSVL Phase 2C entry.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no LLM provider changes, no sub-agent lifecycle changes, no vector-store changes, no VS Code event schema changes, and no security-tooling policy changes). Pure prompt enhancement (additive metadata) with no breaking changes to existing prompt format.

### 2026-03-07 — DSVL Phase 2B: TUI audit trail integration
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Modified `storycraftr/tui/app.py` to add `/state audit` command with subcommand routing pattern.
	- Changed `_dispatch_slash_command()` to route `/state` to `_handle_state_command(args)` dispatcher.
	- Added `_handle_state_command()` method to route to `_build_state_text()` (default) or `_build_state_audit_text()` (audit subcommand).
	- Implemented `_build_state_audit_text(args)` method (~75 lines) for audit history query and formatting.
	- Filter support: `limit=<n>` for result count, `entity=<id>` for entity filtering, `type=<character|location|plot_thread>` for entity type filtering.
	- Display format: entry number, timestamp, operation type, actor, patch operation count, changeset modification count, state version.
	- Error handling: validates filter arguments, checks for disabled audit logging, handles empty audit logs.
	- Updated TUI help text to include `/state audit [limit=<n>] [entity=<id>] [type=<type>]` command with filter examples.
	- Added 11 comprehensive tests to `tests/unit/test_tui_app.py` covering all filter combinations, error cases, and disabled audit scenarios.
	- Updated `CHANGELOG.md` with DSVL Phase 2B entry.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no LLM provider changes, no sub-agent lifecycle changes, no vector-store changes, no VS Code event schema changes, and no security-tooling policy changes). Pure TUI enhancement (display-only) with no core behavior or data model changes.

### 2026-03-07 — DSVL Phase 2A: Persistent audit trail logging
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Created `storycraftr/agent/state_audit.py` with `AuditEntry` frozen dataclass and `StateAuditLog` class.
	- `AuditEntry` contains: timestamp, operation_type (Literal), actor, patch (optional), changeset (optional), metadata.
	- `StateAuditLog` provides append-only JSONL persistence in `{book_path}/outline/narrative_audit.jsonl`.
	- Implemented `append_entry()` for atomic line append (thread-safe on POSIX).
	- Implemented `query_entries()` with filters: entity_id, entity_type, operation_type, after, before, limit.
	- Integrated audit logging into `NarrativeStateStore.apply_patch()` with lazy initialization.
	- Added `enable_audit` flag to `NarrativeStateStore.__init__()` (default: True).
	- Added `actor` parameter to `apply_patch()` for audit trail attribution.
	- Created `tests/unit/test_state_audit.py` with 16 comprehensive tests including integration tests.
	- Updated `CHANGELOG.md` with DSVL Phase 2A entry.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no LLM provider changes, no sub-agent lifecycle changes, no vector-store changes, no VS Code event schema changes, and no security-tooling policy changes). Audit logging is opt-in (enabled by default) and logs to project-local JSONL files with no external dependencies.

### 2026-03-07 — DSVL Phase 1C: Rule-governed patch validation and application
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `StateValidationError` exception, `PatchOperation`, and `StatePatch` dataclasses to `storycraftr/agent/narrative_state.py`.
	- Implemented `validate_patch()` method with rule enforcement: dead characters cannot change location, location references must exist, cannot remove locations with characters, cannot add duplicate entities.
	- Implemented `apply_patch()` method with atomic multi-operation application, version increments, and timestamp updates.
	- Added internal validators: `_validate_character_patch()`, `_validate_location_patch()`, `_validate_plot_thread_patch()`.
	- Added internal apply methods: `_apply_character_operation()`, `_apply_location_operation()`, `_apply_plot_thread_operation()`.
	- Created `tests/unit/test_patch_validation.py` with 14 comprehensive patch validation tests.
	- Updated `CHANGELOG.md` with DSVL Phase 1C entry.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no LLM provider changes, no sub-agent lifecycle changes, no vector-store changes, no VS Code event schema changes, and no security-tooling policy changes). Pure additive module with no runtime integration yet (pending Phase 2B).

### 2026-03-07 — DSVL Phase 1B: Deterministic state diff engine
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Created `storycraftr/agent/state_diff.py` with `DiffType` enum, `FieldDiff`, `EntityDiff`, and `StateChangeset` dataclasses.
	- Implemented `compute_state_diff()` function with deterministic (sorted) ordering for characters, locations, plot threads.
	- Added field-level change tracking (ADDED, REMOVED, MODIFIED, UNCHANGED).
	- Added entity-level diff detection across all state entity types.
	- Added world dict change detection.
	- Created `tests/unit/test_state_diff.py` with 16 comprehensive diff detection tests.
	- Updated `CHANGELOG.md` with DSVL Phase 1B entry.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no LLM provider changes, no sub-agent lifecycle changes, no vector-store changes, no VS Code event schema changes, and no security-tooling policy changes). Pure additive module with no runtime integration yet (pending Phase 1C/2B).

### 2026-03-07 — DSVL Phase 1A: Validated narrative state schema models
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added Pydantic validation models in `storycraftr/agent/narrative_state.py`: `CharacterState`, `LocationState`, `PlotThreadState` with field validators and model validators.
	- Replaced frozen dataclass `NarrativeStateSnapshot` with validated Pydantic model supporting `characters`, `locations`, `plot_threads`, and legacy `world` fields.
	- Updated `NarrativeStateStore.load()` with validation-first loading and legacy fallback migration via `_load_legacy()`.
	- Updated `NarrativeStateStore.save()` to serialize Pydantic models using `model_dump()`.
	- Updated `NarrativeStateStore.upsert_character()` with validation and graceful failure handling.
	- Updated `NarrativeStateStore.render_prompt_block()` to serialize validated models.
	- Created `tests/unit/test_narrative_state_validation.py` with 30 comprehensive validation tests.
	- Updated existing tests in `tests/unit/test_narrative_state.py` to work with Pydantic models.
	- Updated `CHANGELOG.md` with DSVL Phase 1A entry.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no LLM provider changes, no sub-agent lifecycle changes, no vector-store changes, no VS Code event schema changes, and no security-tooling policy changes). Maintained backward compatibility with existing narrative state files through legacy loading support.

### 2026-03-07 — Updated contributor-reference.md with recent runtime contract files
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `docs/contributor-reference.md` "High-Value Runtime Contract Files" section to include recently added modules: `storycraftr/utils/paths.py`, `storycraftr/utils/project_lock.py`, `storycraftr/agent/narrative_state.py`, `storycraftr/agent/story/scene_planner.py`, canon-related files (`canon.py`, `canon_extract.py`, `canon_verify.py`), and their corresponding test files.
	- Updated descriptions to reflect recent architecture features: Canon Guard, narrative state, adaptive compaction, TUI execution modes, and project write locking.
	- Added "Recent Architecture Context" subsection to "Notes For AI Agents" section to highlight key architectural additions for quick onboarding.
	- Enhanced runtime contract file descriptions to mention specific behaviors like fail-closed verification, adaptive compaction heuristics, and diagnostics persistence.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (no code changes, only documentation catalog updates).

### 2026-03-07 — Adaptive compaction + canon diagnostics + structured narrative-state prompts
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/agent/narrative_state.py` with JSON-backed `NarrativeStateStore` for deterministic character/world state (`outline/narrative_state.json`) and prompt-safe JSON rendering.
	- Updated `storycraftr/tui/state_engine.py` and `storycraftr/tui/context_builder.py` to inject optional `[Structured Narrative State]` blocks and expose section-level diagnostics (`narrative_state`) in budget reports.
	- Updated `storycraftr/tui/app.py` with `/context conflicts` diagnostics, `/canon check-last` rerun checks, reusable conflict analysis reporting, and conflict summary surfacing in bare `/context`.
	- Updated rolling summary compaction in `storycraftr/tui/app.py` to adaptive heuristics that preserve high-signal narrative anchors while compacting lower-signal turns.
	- Added/updated tests in `tests/unit/test_narrative_state.py`, `tests/unit/test_tui_state_engine.py`, and `tests/unit/test_tui_app.py`.
	- Synced docs in `docs/chat.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Minimal post-generation canon conflict warnings in TUI
- **Sections reviewed:** 4 (Sub-Agents & Background Jobs), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` normal chat-turn flow to run a warn-only post-generation canon check using existing extraction (`extract_canon_candidates`) and verification (`verify_candidate_against_canon`) primitives.
	- Added `_warn_about_canon_conflicts(...)` to surface `Potential Canon Conflicts` in the output pane for likely duplicate facts and negation contradictions against chapter canon.
	- Preserved fail-closed commit behavior and autopilot verification semantics; this change only adds visibility warnings and does not block generation or mutate canon state.
	- Added regression coverage in `tests/unit/test_tui_app.py` for conflict warning emission during normal prompt submission.
	- Synced docs in `docs/chat.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider/model routing contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Structured prompt sections in TUI prompt composer
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/context_builder.py` prompt assembly to use explicit structured sections: `[Canon Constraints]`, `[Scene Plan]`, `[Scoped Context]`, `[Session Summary]`, `[Recent Dialogue]`, and `[User Instruction]`.
	- Preserved model-aware deterministic pruning while splitting compacted summary from dialogue turns so summary can be observed and pruned independently.
	- Updated diagnostics section keys/labels consumed by `storycraftr/tui/app.py` budget views (`canon_constraints`, `recent_dialogue`, `user_instruction`) and aligned estimated-token reporting.
	- Updated regression coverage in `tests/unit/test_tui_context_builder.py`, `tests/unit/test_tui_state_engine.py`, and `tests/unit/test_tui_app.py` to assert new section names and diagnostics keys.
	- Synced user-facing docs in `docs/chat.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — `/context` snapshot hardening (full summary + section breakdown + persisted budget metadata)
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/state_engine.py` to persist `last_budget_metadata` and `last_prompt_diagnostics` on each `compose_prompt_with_diagnostics(...)` call so diagnostics can be retrieved without recomposition.
	- Updated `storycraftr/tui/context_builder.py` to emit more granular section token estimates (`scene_plan`, `scoped_context`, `user_instruction`) used by diagnostics surfaces.
	- Updated `storycraftr/tui/app.py` bare `/context` output to render a full runtime snapshot including active model, budget summary, pruning status, per-section status/estimate breakdown, and full current session summary text.
	- Updated tests in `tests/unit/test_tui_app.py` and `tests/unit/test_tui_state_engine.py` for the enriched `/context` contract and state-engine metadata persistence.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile changes, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — TUI runtime context diagnostics expansion (`/context` subcommands)
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` to add structured `/context` diagnostics commands: bare overview plus `summary`, `budget`, `models`, `clear-summary`, and `refresh-models` subcommands.
	- Added read-only observability state capture for latest prompt budgeting/pruning decisions (including section inclusion/pruning/truncation markers and estimated usage) during normal and autopilot prompt composition.
	- Updated `storycraftr/tui/context_builder.py` with `PromptDiagnostics` and a non-breaking `compose_budgeted_prompt_with_diagnostics(...)` helper while preserving existing prompt generation behavior.
	- Updated `storycraftr/tui/state_engine.py` with `compose_prompt_with_diagnostics(...)` and preserved `compose_prompt(...)` compatibility as a prompt-only wrapper.
	- Added `storycraftr/llm/openrouter_discovery.py::get_cache_metadata()` and `refresh_free_models()` helper to expose cache freshness/age/model counts for diagnostics surfaces.
	- Added/updated tests in `tests/unit/test_tui_app.py` and `tests/unit/test_openrouter_discovery.py`.
	- Synced docs in `README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `docs/contributor-reference.md`, `release_notes.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Contributor-reference execution: release-note parity sync for dynamic OpenRouter discovery
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Reviewed `docs/contributor-reference.md` update rules and verified required user-facing sync targets for the dynamic OpenRouter discovery rollout.
	- Updated `release_notes.md` top draft section to reflect shipped behavior: live free-model discovery, user-local cache + TTL + stale fallback, strict free-only model validation, dynamic model limits in budgeting, and model-list refresh commands.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (documentation-only parity update; no dependency/lockfile changes, runtime code changes, config schema changes, sub-agent lifecycle changes, vector-store/path changes, VS Code event contract changes, or security-tooling policy changes).

### 2026-03-07 — Dynamic OpenRouter free-model discovery + strict free-only validation
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/llm/openrouter_discovery.py` with dynamic OpenRouter catalog fetch (`/api/v1/models`), free-model filtering, typed metadata parsing, user-local cache (`~/.storycraftr/openrouter-models-cache.json`), default 6-hour TTL, stale-cache fallback, and minimal emergency fallback.
	- Updated `storycraftr/llm/model_context.py` to prioritize discovery-driven OpenRouter limits (context length + max completion tokens) for budgeting while preserving conservative registry defaults/fallback behavior for unknown or unavailable discovery data.
	- Updated `storycraftr/llm/factory.py` to enforce strict free-only validation for OpenRouter primary/fallback models before provider initialization, preventing paid or unknown model usage in free-only mode.
	- Updated model discovery UX surfaces: TUI `/model-list` now shows discovered limits with `/model-list refresh`; added CLI `model-list` command with `--refresh`.
	- Added/updated tests across discovery, model context, factory, TUI context budgeting, TUI command dispatch, and CLI command behavior.
	- Synced docs in `README.md`, `docs/chat.md`, `docs/getting_started.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).
### 2026-03-07 — Post-merge documentation parity sweep (P0-P2)
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `docs/getting_started.md` to reflect OpenRouter fallback resilience, TUI model-aware budgeting and rolling summary context, `/summary` + `/context`, and sub-agent `model_exhausted` cooldown-retry behavior.
	- Updated `release_notes.md` with a consolidated 2026-03-07 draft section covering prompt budgeting, rolling compaction diagnostics, and sub-agent cooldown lifecycle.
	- Updated canonical contributor/architecture contracts in `.github/copilot-instructions.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, and `docs/contributor-reference.md` to align with the current sub-agent lifecycle and behavior-default location.
- **No impact:** sections 1, 2, 3, 4, 5, 6, and 7 (documentation-only sync; no dependency/lockfile, runtime config schema, LLM routing code, sub-agent implementation code, vector-store/path contracts, VS Code event schema, or security-tooling behavior changed).

### 2026-03-07 — P2 sub-agent model exhaustion cooldown + retry checkpoint
- **Sections reviewed:** 4 (Sub-Agents & Background Jobs), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/subagents/jobs.py` to add a `model_exhausted` lifecycle checkpoint for transient model-capacity/rate-limit failures, including bounded cooldown, one retry attempt, and persisted checkpoint metadata (`attempts`, `cooldown_until`).
	- Updated `storycraftr/chat/render.py` session footer to surface `model_exhausted` job counts alongside pending/running/succeeded/failed.
	- Added regressions in `tests/unit/test_subagent_jobs.py` for cooldown retry success and in-cooldown stats visibility.
	- Synced docs in `docs/chat.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no LLM provider factory contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — P1.5 TUI compaction diagnostics + canonical doc sync
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` with diagnostic commands `/summary` (`/summary clear`) and `/context` so users can inspect rolling session summary state and prompt-context composition.
	- Added TUI regressions in `tests/unit/test_tui_app.py` for summary reporting, summary clearing persistence, context diagnostics output, and help text command discovery.
	- Synced user and canonical architecture docs in `README.md`, `docs/chat.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `.github/copilot-instructions.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Unified contributor reference catalog
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `docs/contributor-reference.md` as a single shareable reference for contributors and AI agents covering mandatory reading, file categories, per-file summaries, and update-sync rules.
	- Updated `docs/architecture-onboarding.md` to point to the new contributor reference for the detailed file-by-file catalog and maintenance matrix.
- **No impact:** sections 1–7 (documentation-only consolidation; no dependency, config, LLM, sub-agent, vector-store, IPC, or security-tooling behavior changed).

### 2026-03-07 — Contributor doc surface consolidation via onboarding guide
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Expanded `docs/architecture-onboarding.md` into the single contributor-facing reading guide, including the minimum mandatory doc set, area-specific references, junior-dev starter order, and the current `behavior.txt` documentation gap.
	- Repositioned `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md` as a deep reference instead of part of the minimum must-read set.
	- Updated contributor entry points in `README.md` and `CONTRIBUTING.md` to send developers first to `docs/architecture-onboarding.md`.
- **No impact:** sections 1–7 (documentation-only consolidation; no dependency, config, LLM, sub-agent, vector-store, IPC, or security-tooling behavior changed).

### 2026-03-07 — P1 rolling session summary compaction boundary
- **Sections reviewed:** 4 (Sub-Agents & Background Jobs), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/tui/app.py` to add deterministic rolling transcript compaction for long sessions: older turns are collapsed into a bounded `Session Summary`, recent turns remain verbatim, and summary context is injected through existing budgeted prompt composition.
	- Persisted compact summary state in `sessions/session.json` via runtime-state merge writes so mode/session metadata keys no longer clobber one another.
	- Added regressions in `tests/unit/test_tui_app.py` covering summary injection and runtime-state preservation when changing execution mode.
	- Synced docs in `README.md`, `docs/chat.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 3, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no provider routing contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — P1 OpenRouter native resilience in factory layer
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Updated `storycraftr/llm/factory.py` to wrap OpenRouter models with native resilience (`_ResilientOpenRouterChatModel`) that performs bounded exponential-backoff retries for transient failures (rate limit, timeout, connection) and explicit fallback traversal.
	- Added configurable OpenRouter fallback chain support via `STORYCRAFTR_OPENROUTER_FALLBACK_MODELS`; factory fallback order now appends `openrouter/free` when primary differs.
	- Added resolved provider/model logging for successful OpenRouter calls in the resilience wrapper.
	- Expanded `tests/unit/test_llm_factory.py` for wrapper construction, fallback chain parsing, retry success, and fallback-after-retry-exhaustion behavior while preserving existing provider validation coverage.
	- Synced docs in `README.md` and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — P0 model-aware token budget gate + model-context registry
- **Sections reviewed:** 3 (LLM Configuration & Routing), 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/llm/model_context.py` with a small in-repo model-context registry, conservative unknown-model fallback, and input-budget computation (`context_window - output_reserve`).
	- Added deterministic, model-aware prompt compaction in `storycraftr/tui/context_builder.py` via `compose_budgeted_prompt(...)` with explicit pruning order: active constraints, scoped scene context, recent turns, retrieval chunks, then low-priority state strips.
	- Updated `storycraftr/tui/state_engine.py` and `storycraftr/tui/app.py` to pass active provider/model and reserved output tokens into budgeted prompt composition for both interactive and autopilot turns.
	- Added regressions in `tests/unit/test_model_context.py`, `tests/unit/test_tui_context_builder.py`, and `tests/unit/test_tui_state_engine.py`.
	- Synced docs in `README.md`, `docs/chat.md`, and `CHANGELOG.md`.
- **No impact:** sections 1, 2, 4, 5, 6, and 7 (no dependency/lockfile updates, no Story/Paper config schema changes, no sub-agent lifecycle contract changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — StoryCraftr Engineering Agent Context7 usage contract update
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `.github/agents/storycraftr-engineering.agent.md` to add an explicit Context7 operating policy for third-party library research.
	- Added mandatory resolve-first workflow (`resolve-library-id` then `query-docs`), per-question query cap guidance, and rules for when Context7 should and should not be used.
	- Added repository-specific Context7 targeting guidance for LangChain, Chroma, Textual, and VS Code extension API work.
- **No impact:** sections 1–7 (no dependency/lockfile updates, no runtime config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — StoryCraftr Engineering Agent instruction refresh
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Updated `.github/agents/storycraftr-engineering.agent.md` to reflect current architecture and operating contracts, including TUI execution modes, `/autopilot` bounded-loop semantics, Canon Guard candidate approval + fail-closed verification, and explicit memory/recall integrity priorities.
	- Aligned engineering workflow guidance with current validation surfaces (`test_tui_app`, `test_tui_state_engine`, `test_tui_context_builder`, `test_tui_canon_extract`, `test_tui_canon_verify`).
- **No impact:** sections 1–7 (no dependency/lockfile updates, no runtime config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Priority 4 autopilot safety: conflict verification + bounded loop
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/tui/canon_verify.py` with fail-closed candidate verification against accepted chapter facts, including duplicate and negation-conflict checks.
	- Updated `storycraftr/tui/app.py` with `/autopilot <steps> <prompt>` command handling that is gated by execution mode (`/mode autopilot`) and bounded to a safe step range.
	- Integrated verification-before-write behavior into the `/autopilot` commit path so only non-conflicting candidates are persisted to `outline/canon.yml`.
	- Added tests in `tests/unit/test_tui_canon_verify.py` and expanded `tests/unit/test_tui_app.py` for mode gating and verified commit behavior.
	- Synced docs in `README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `release_notes.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Priority 3 prompt efficiency: scene planner + scoped context
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/agent/story/scene_planner.py` with deterministic scene planning (`Goal`, `Conflict`, `Outcome`) from current state and user prompt.
	- Added `storycraftr/tui/context_builder.py` with bounded `[Scoped Context]` assembly (active state, constraints, relevant context) and dedupe/cap logic.
	- Refactored `storycraftr/tui/state_engine.py` prompt composition to build scene-scoped context via `build_scoped_context(...)` before appending `[User Prompt]`.
	- Updated `storycraftr/tui/app.py` `/state` output path to display the same scoped context block used for injection.
	- Added/updated tests in `tests/unit/test_scene_planner.py`, `tests/unit/test_tui_context_builder.py`, `tests/unit/test_tui_state_engine.py`, and `tests/unit/test_tui_app.py`.
	- Synced docs in `README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `release_notes.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — Hybrid canon extraction queue and approval commands
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/tui/canon_extract.py` with conservative fact-like sentence extraction for pending canon candidates.
	- Added `storycraftr/tui/canon_verify.py` as the fail-closed verifier used when autopilot attempts to commit extracted candidates.
	- Updated `storycraftr/tui/app.py` hybrid-mode behavior to queue extracted candidates after assistant responses using `SubAgentJobManager` executor workers, with lifecycle-safe shutdown on TUI unmount, and surface review guidance in TUI output.
	- Expanded `/canon` command group with pending/approval controls: `/canon pending`, `/canon accept <n[,m,...]>`, and `/canon reject [n[,m,...]]`.
	- Added/updated tests in `tests/unit/test_tui_canon_extract.py`, `tests/unit/test_tui_canon_verify.py`, and `tests/unit/test_tui_app.py` for extraction, queue, accept, reject, and conflict-guard flows.
	- Synced docs in `README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

### 2026-03-07 — TUI execution mode safety gate: manual/hybrid/autopilot
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `ExecutionMode` control layer in `storycraftr/tui/app.py` with `/mode <manual|hybrid|autopilot>` command handling.
	- Added footer-region mode indicator (`[ MODE: ... ]`) and status/help integration for execution mode visibility, including explicit `/autopilot <steps> <prompt>` discoverability.
	- Added runtime persistence for execution mode in `storycraftr/chat/session.py` via `sessions/session.json` (`load_runtime_state`, `save_runtime_state`) and filtered session listings to ignore runtime metadata file.
	- Added test coverage in `tests/unit/test_tui_app.py` and `tests/unit/test_core_paths.py` for mode command behavior, status visibility, runtime-state round-trip, and session listing behavior.
	- Synced user/developer docs in `README.md`, `docs/chat.md`, `docs/getting_started.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, `release_notes.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).
### 2026-03-07 — Canon Guard Phase 1: manual canon ledger and prompt constraints
- **Sections reviewed:** 8 (Documentation & Versioning)
- **Impact:**
	- Added `storycraftr/tui/canon.py` with chapter-scoped canonical fact storage in `outline/canon.yml` (`load`, `save`, `list`, `add`, `clear`) and malformed-YAML safety errors.
	- Integrated Canon Guard into `storycraftr/tui/app.py` with `/canon` command group:
	  - `/canon`, `/canon show [chapter]`, `/canon add <fact>`, `/canon add <chapter> :: <fact>`, `/canon clear [confirm]`.
	- Integrated chapter-scoped canon constraints in `storycraftr/tui/state_engine.py` prompt composition via `[Active Constraints]` block (capped injection, current chapter only).
	- Added/updated unit tests in `tests/unit/test_tui_canon.py`, `tests/unit/test_tui_state_engine.py`, and `tests/unit/test_tui_app.py`.
	- Synced user-facing docs in `README.md`, `docs/chat.md`, `docs/getting_started.md`, `release_notes.md`, `docs/architecture-onboarding.md`, `docs/StoryCraftr-Next Complete Architecture & Technical Reference.md`, and `CHANGELOG.md`.
- **No impact:** sections 1–7 (no dependency/lockfile changes, no Story/Paper config schema changes, no provider routing changes, no sub-agent lifecycle changes, no vector-store/path contract changes, no VS Code event schema changes, and no security-tooling policy changes).

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
