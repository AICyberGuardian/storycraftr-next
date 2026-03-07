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
- `AGENTS.md` still references `behavior.txt`, but behavior defaults now live
  under `behaviors/` (for example `behaviors/default.txt`).
