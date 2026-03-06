# Repository Guidelines

Current development target: v0.16.x.

## Repository Invariants
- `DEP_UPDATE`: Modifying `pyproject.toml` requires updating `poetry.lock` via `make sync-deps` (do not run `poetry lock` directly in routine workflows).
- `JS_UPDATE`: Modifying `package.json` requires updating `package-lock.json` via `make sync-deps` (do not run raw `npm install` directly in routine workflows).
- `VER_BUMP`: Modifying version strings requires synchronized updates to `pyproject.toml`, `package.json`, `package-lock.json`, and `CHANGELOG.md`.
- `LOCK_IMMUTABLE_CI`: CI must fail if dependency lock files drift (`git diff --exit-code poetry.lock package-lock.json`).
- `CI_INSTALL_PATTERN`: CI uses `setup-uv` cache + `poetry export` + `uv pip install`; local development continues to use `poetry install`.

## Project Structure & Module Organization
StoryCraftr ships a Python CLI plus a lightweight VS Code companion extension. Python sources live in `storycraftr/` (agents, CLI entrypoints, prompts, templates) with tests under `tests/` partitioned into `unit/` and `integration/`. The extension code sits in `src/` (TypeScript) and compiles to `out/` during builds. Shared documentation belongs in `docs/`, while runnable samples and starter outlines live in `examples/`. Treat `behavior.txt` as the canonical agent contract when adjusting automated behaviors.

## Build, Test, and Development Commands
- Unified dependency runner: `make sync-deps` updates Python/Node lock files together and stages them.
- Version bump runner: `make bump-version VERSION=0.16.0-dev` updates version metadata + lock files atomically.
- Python: `poetry install` bootstraps dependencies; `poetry run storycraftr --help` validates the CLI loads; `poetry run pytest` runs the full suite. Use `poetry run pre-commit run --all-files` before pushing.
- Extension: run `npm install` once, then use `npm run compile` to emit `out/extension.js`. `npm run watch` keeps the TypeScript build live during development.

## Coding Style & Naming Conventions
Python code is formatted with Black (88-character lines) and linted via Bandit and detect-secrets through pre-commit; prefer snake_case for functions and lower-case package names mirroring directory structure (for example, `storycraftr.agent.*`). TypeScript follows the repo’s `tsconfig` defaults; prefer camelCase for functions, PascalCase for classes, and keep activation command IDs under the `storycraftr.` namespace. Keep prompts and template YAMLs declarative, mirroring existing filenames.

## Testing Guidelines
Place new Python tests under `tests/unit/` or `tests/integration/` using `test_<feature>.py` naming; assert CLI flows with fixtures in `tests/utils/`. For the extension, add focused unit tests under `tests/unit` or use `npm run compile` to ensure TypeScript builds cleanly. When modifying agents, cover both deterministic parsing helpers and end-to-end flows. Aim to keep pytest coverage from regressing; add regression cases for bugs alongside fixes.

## Commit & Pull Request Guidelines
Adopt Conventional Commit prefixes observed in history (`feat(agents):`, `fix(cli):`, `sec:`) and keep messages imperative and concise. Each PR should describe the user-facing change, list manual or automated test runs, and mention any docs, templates, or prompts updated. Link GitHub issues where applicable and attach screenshots or CLI transcripts when changing UX.

## Security & Configuration Tips
Never commit API keys or `.env` files; the CLI resolves provider secrets (for example, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`) in this order: existing environment variables, OS keyring (`storycraftr` service), then legacy plaintext files under `~/.storycraftr/` or `~/.papercraftr/` as a compatibility fallback. Prefer storing secrets with `store_local_credential` from `storycraftr.llm.credentials` rather than plaintext files. Runtime internal paths (`subagents`, `sessions`, `vector_store`, VS Code event stream) are now resolved from project config via a shared path resolver; avoid introducing new hardcoded directory literals in feature code. Run `poetry run detect-secrets scan` or rely on pre-commit hooks after touching config files. Review `SECURITY.md` when shipping authentication or networking changes, and call out potential token usage impacts in release notes.
