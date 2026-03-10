# Repository Guidelines

Current development target: v0.19.

## Repository Invariants
- `DEP_UPDATE`: Modifying `pyproject.toml` requires updating `poetry.lock` via `make sync-deps` (do not run `poetry lock` directly in routine workflows).
- `JS_UPDATE`: Modifying `package.json` requires updating `package-lock.json` via `make sync-deps` (do not run raw `npm install` directly in routine workflows).
- `VER_BUMP`: Modifying version strings requires synchronized updates to `pyproject.toml`, `package.json`, `package-lock.json`, and `CHANGELOG.md`.
- `LOCK_IMMUTABLE_CI`: CI must fail if dependency lock files drift (`git diff --exit-code poetry.lock package-lock.json`).
- `CI_INSTALL_PATTERN`: CI uses `setup-uv` cache + `poetry export` + `uv pip install`; local development continues to use `poetry install`.

## Project Structure & Module Organization
StoryCraftr ships a Python CLI plus a lightweight VS Code companion extension. Python sources live in `storycraftr/` (agents, CLI entrypoints, prompts, templates, and a Textual TUI under `storycraftr/tui/`) with tests under `tests/` partitioned into `unit/` and `integration/`. The extension code sits in `src/` (TypeScript) and compiles to `out/` during builds. Shared documentation belongs in `docs/`, while runnable samples and starter outlines live in `examples/`. Treat `behavior.txt` as the canonical agent contract when adjusting automated behaviors.

### Key Architecture: Sequential Scene Generation Pipeline

StoryCraftr uses a role-isolated three-stage architecture for scene generation:

1. **Planner Stage**: Produces a validated `SceneDirective` JSON (goal, conflict, stakes, outcome) from user prompt and narrative context.
2. **Drafter Stage**: Writes initial scene prose anchored to the directive without revision concerns.
3. **Editor Stage**: Revises draft prose against directive and static craft rules for quality and consistency.

This separation prevents instruction dilution and improves narrative coherence. The pipeline implementation lives in `storycraftr/agent/generation_pipeline.py` with static craft-rule injection from `storycraftr/prompts/planner_rules.md`, `drafter_rules.md`, and `editor_rules.md`.

## Build, Test, and Development Commands
- Unified dependency runner: `make sync-deps` updates Python/Node lock files together and stages them.
- Version bump runner: `make bump-version VERSION=0.19.0-dev` updates version metadata + lock files atomically.
- Python: `poetry install` bootstraps dependencies; `poetry run storycraftr --help` validates the CLI loads; `poetry run pytest` runs the full suite. Use `poetry run pre-commit run --all-files` before pushing.
- Extension: run `npm install` once, then use `npm run compile` to emit `out/extension.js`. `npm run watch` keeps the TypeScript build live during development.

## Mandatory Commit Workflow

All contributors and coding agents must follow this exact sequence before committing:

1. Apply changes.
2. Format Python code: `poetry run black .`
3. Run repository hooks: `poetry run pre-commit run --all-files`
4. Stage all updates: `git add -A`
5. Re-run `poetry run pre-commit run --all-files` if hooks modified files.
6. Repeat stage + hook run until hooks pass cleanly.
7. Commit.

Additional commit safety rules:

- Never commit secrets (API keys, tokens, passwords, credentials).
- If a synthetic fixture trips detect-secrets, use the repository pattern on that assignment line: `# nosec B105  # pragma: allowlist secret`.
- Never commit Windows metadata files such as `*:Zone.Identifier`; delete them before staging.
- Do not use `--no-verify` for routine commits.

## Coding Style & Naming Conventions
Python code is formatted with Black (88-character lines) and linted via Bandit and detect-secrets through pre-commit; prefer snake_case for functions and lower-case package names mirroring directory structure (for example, `storycraftr.agent.*`). TypeScript follows the repo’s `tsconfig` defaults; prefer camelCase for functions, PascalCase for classes, and keep activation command IDs under the `storycraftr.` namespace. Keep prompts and template YAMLs declarative, mirroring existing filenames.

## Testing Guidelines
Place new Python tests under `tests/unit/` or `tests/integration/` using `test_<feature>.py` naming; assert CLI flows with fixtures in `tests/utils/`. For the extension, add focused unit tests under `tests/unit` or use `npm run compile` to ensure TypeScript builds cleanly. When modifying agents, cover both deterministic parsing helpers and end-to-end flows. Aim to keep pytest coverage from regressing; add regression cases for bugs alongside fixes.

## Commit & Pull Request Guidelines
Adopt Conventional Commit prefixes observed in history (`feat(agents):`, `fix(cli):`, `sec:`) and keep messages imperative and concise. Each PR should describe the user-facing change, list manual or automated test runs, and mention any docs, templates, or prompts updated. Link GitHub issues where applicable and attach screenshots or CLI transcripts when changing UX.

## Security & Configuration Tips
Never commit API keys or `.env` files; the CLI resolves provider secrets (for example, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`) in this order: existing environment variables, OS keyring (`storycraftr` service), then legacy plaintext files under `~/.storycraftr/` or `~/.papercraftr/` as a compatibility fallback. Prefer storing secrets with `store_local_credential` from `storycraftr.llm.credentials` rather than plaintext files. Runtime internal paths (`subagents`, `sessions`, `vector_store`, VS Code event stream) are now resolved from project config via a shared path resolver; avoid introducing new hardcoded directory literals in feature code. Run `poetry run detect-secrets scan` or rely on pre-commit hooks after touching config files. Review `SECURITY.md` when shipping authentication or networking changes, and call out potential token usage impacts in release notes.

### Secret Detection Rules

- Never commit real API keys or credentials.
- All credentials must be loaded from environment variables.
- Example commands showing keys must include: `# pragma: allowlist secret`.
- Example format:

```bash
echo 'export OPENROUTER_API_KEY="your_key_here"' # pragma: allowlist secret
```
