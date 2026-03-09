[![GitHub Actions Status](https://github.com/AICyberGuardian/storycraftr-next/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/AICyberGuardian/storycraftr-next/actions)
[![GitHub Actions Status](https://github.com/AICyberGuardian/storycraftr-next/actions/workflows/pytest.yml/badge.svg)](https://github.com/AICyberGuardian/storycraftr-next/actions)

# <img src="https://res.cloudinary.com/dyknhuvxt/image/upload/f_auto,q_auto/ofhhkf6f7bryfgvbxxwc" alt="StoryCraftr Logo" width="100" height="100"> StoryCraftr - Your AI-powered Book Creation Assistant 📚🤖

Welcome to [**StoryCraftr**](https://storycraftr.app), the open-source project designed to revolutionize how books are written. With the power of AI and a streamlined command-line interface (CLI), StoryCraftr helps you craft your story, manage worldbuilding, structure your book, and generate chapters — all while keeping you in full control.

StoryCraftr uses a **sequential scene generation pipeline** that separates planning, drafting, and editing into distinct stages. This architecture reduces instruction dilution and improves narrative quality by giving each stage focused responsibilities: the planner builds scene directives, the drafter writes initial prose, and the editor revises for consistency and craft quality.

---

## What's New? Discover AI Craftr 🌐

**[AI Craftr](https://aicraftr.app)** is now available as a powerful suite for AI-assisted writing, featuring specialized tools like **StoryCraftr** for novelists and **[PaperCraftr](https://papercraftr.app)** for researchers. Each tool is designed to simplify your writing process with unique features catered to different types of content. Explore **PaperCraftr** for structuring academic papers, or stay tuned as we add more tools to the AI Craftr suite, such as **LegalCraftr** for legal documents and **EduCraftr** for educational materials.

---

## Development Cycle v0.19

Current development target: `v0.19` (`0.19.0-dev`).

For in-progress changes, see `CHANGELOG.md` under `[Unreleased]`.

Recent dependency baseline updates include `textual` in the Python runtime stack and synchronized lockfile refreshes for related transitive packages.

### CI Dependency Install Pattern

Local development should continue to use Poetry directly (`poetry install`).
CI uses a faster, deterministic hybrid path:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install poetry poetry-plugin-export
poetry export --with dev --format requirements.txt --without-hashes --output requirements-ci.txt
uv pip install -r requirements-ci.txt
uv pip install -e .
pytest
```

Key CI invariants:

- `setup-uv` uses native cache (`enable-cache: true`).
- Lock drift must fail CI via `git diff --exit-code poetry.lock package-lock.json`.
- TypeScript build steps run `npm ci` before `npm run compile`.

## Step 1: Install StoryCraftr

StoryCraftr requires Python `3.13.x`.

First, install **StoryCraftr** using [pipx](https://pypa.github.io/pipx/), a tool to help you install and run Python applications in isolated environments. It works on most platforms, including macOS, Linux, and Windows. Using `pipx` ensures that **StoryCraftr** runs in its own virtual environment, keeping your system's Python installation clean.

To install **StoryCraftr**, run the following command:

```bash
pipx install git+https://github.com/AICyberGuardian/storycraftr-next.git@main
```

Alternatively, if you have `uv` and `uvx` installed on your system, you can run storycraftr without installing it first:

```bash
uvx --from git+https://github.com/AICyberGuardian/storycraftr-next.git@main storycraftr
```

### Configure Provider Credentials

StoryCraftr now uses LangChain and supports OpenAI, OpenRouter, and Ollama out of the box. Credentials are discovered in this order:

1. Existing environment variables (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`)
2. OS keyring entries under the `storycraftr` service (override via `STORYCRAFTR_KEYRING_SERVICE`)
3. Legacy plaintext files in `~/.storycraftr/` or `~/.papercraftr/` (compatibility fallback)

Use the built-in helper to store keys securely in the OS keyring:

```bash
python -c "from storycraftr.llm.credentials import store_local_credential; store_local_credential('OPENAI_API_KEY', 'sk-your-openai-secret')"
python -c "from storycraftr.llm.credentials import store_local_credential; store_local_credential('OPENROUTER_API_KEY', 'or-your-openrouter-secret')"
```

If your system has no usable OS keyring backend, this helper falls back to `~/.storycraftr/*_api_key.txt` and prints a warning.

Legacy plaintext files are still read, but they are now treated as a migration fallback:

```bash
# Optional legacy fallback (less secure)
mkdir -p ~/.storycraftr
echo "or-your-openrouter-secret" > ~/.storycraftr/openrouter_api_key.txt

# Ollama usually runs locally and does not require a key.
export OLLAMA_BASE_URL="http://localhost:11434"
```

### Configure the LLM and Embeddings

Each project stores its configuration in `storycraftr.json` or `papercraftr.json`. New projects include LangChain-centric settings:

```json
{
  "llm_provider": "openai",
  "llm_model": "gpt-4o",
  "llm_endpoint": "",
  "llm_api_key_env": "",
  "temperature": 0.7,
  "request_timeout": 120,
  "max_tokens": 8192,
  "embed_model": "text-embedding-3-small",
  "embed_device": "api",
  "embed_cache_dir": "",
  "enable_semantic_review": false
}
```

- `llm_provider` accepts `openai`, `openrouter`, or `ollama`.
- For `llm_provider=openrouter`, set `llm_model` explicitly in `provider/model` format (for example `meta-llama/llama-3.3-70b-instruct`).
- `llm_endpoint` lets you target custom bases (e.g., `https://openrouter.ai/api/v1`).
- StoryCraftr now validates provider/model/endpoint settings before runtime model calls and raises provider-specific configuration/authentication errors early.
- OpenRouter model selection is now dynamic and free-only: StoryCraftr discovers live models from `GET https://openrouter.ai/api/v1/models`, filters by zero prompt/completion pricing, and rejects paid/unknown models before provider startup.
- OpenRouter discovery uses a user-local cache at `~/.storycraftr/openrouter-models-cache.json` with a default 6-hour TTL; stale cache is reused if live discovery is unavailable.
- OpenRouter calls include native resilience in the factory layer: bounded exponential-backoff retries for transient failures (`429`, timeout, connection), plus an explicit fallback chain where each fallback model is also validated as currently free.
- Configure additional fallback models with `STORYCRAFTR_OPENROUTER_FALLBACK_MODELS` (comma-separated model IDs, for example `meta-llama/llama-3.2-3b-instruct:free,openrouter/free`).
- `max_tokens` caps completion length per LLM request (default `8192`) to reduce truncation risk on long generations.
- TUI prompt assembly now applies a model-aware input budget gate: it resolves an effective context window per active model, reserves output tokens, and prunes context deterministically by priority (canon constraints -> scene/scoped context -> recent turns -> retrieval chunks -> lower-priority extras) to prevent prompt overflow.
- TUI session context now uses a rolling compaction boundary: older turns are collapsed into a bounded `Session Summary` while the latest turns stay verbatim, reducing long-session prompt growth without losing continuity.
- `embed_model` defaults to `text-embedding-3-small` for API-first embeddings.
- `embed_device=api` uses OpenAI-compatible embedding endpoints (OpenAI or OpenRouter based on configured provider).
- For local GPU/CPU embeddings, install dependencies with `poetry install` or `uv pip install -e .`, then switch to `embed_device=auto|cpu|cuda` with a local model such as `BAAI/bge-large-en-v1.5`.
- `enable_semantic_review=true` enables an additional fail-closed semantic reviewer pass (coherence batch model) before state extraction/commit in `storycraftr book`.

### Runtime Storage Paths (Optional)

StoryCraftr now resolves internal runtime directories from the canonical project root (`book_path`) and supports optional overrides in `storycraftr.json` / `papercraftr.json`:

```json
{
  "internal_state_dir": ".storycraftr",
  "subagents_dir": ".storycraftr/subagents",
  "subagent_logs_dir": ".storycraftr/subagents/logs",
  "sessions_dir": ".storycraftr/sessions",
  "vector_store_dir": "vector_store",
  "vscode_events_file": ".storycraftr/vscode-events.jsonl"
}
```

- Relative values are resolved from the project root.
- Absolute values are supported for advanced setups.
- If omitted, defaults match current StoryCraftr layout.

### Supported Providers

- **OpenAI** – works with `ChatOpenAI` via `OPENAI_API_KEY`; set `llm_provider=openai`.
- **OpenRouter** – set `OPENROUTER_API_KEY` and optionally `OPENROUTER_BASE_URL`; use `llm_provider=openrouter`.
- **Ollama** – self-hosted models via `ollama serve`; set `llm_provider=ollama` and optionally `OLLAMA_BASE_URL`.

## Quick Examples

Here are a few ways to get started with **StoryCraftr**:

### Initialize a new book project:

```bash
storycraftr init "La purga de los dioses" \
  --primary-language "es" \
  --alternate-languages "en" \
  --author "Rodrigo Estrada" \
  --genre "science fiction" \
  --behavior "behavior.txt" \
  --llm-provider "openrouter" \
  --llm-model "meta-llama/llama-3.1-70b-instruct" \
  --embed-model "text-embedding-3-small" \
  --embed-device "api"
```

### Generate a general outline:

```bash
storycraftr outline general-outline "Summarize the overall plot of a dystopian science fiction where advanced technology, resembling magic, has led to the fall of humanity’s elite and the rise of a manipulative villain who seeks to destroy both the ruling class and the workers."
```

### Run the disciplined multi-chapter book loop from a seed:

```bash
storycraftr book --seed seed.md --chapters 3 --yes
```

`--yes` now requires `enable_semantic_review=true` for real-provider runs (`openai`, `openrouter`, `ollama`) so autonomous chapter commits stay validator-gated.

In strict autonomous mode (`--yes` + real provider), StoryCraftr also enforces per-chapter coherence gates (`coherence_interval=1`), mandatory severe-canon checks, strict planner JSON directive schema validation, and run-level audit export to `outline/book_audit.json` and `outline/book_audit.md`.

Quality retries now include a model-escalation ladder for OpenRouter ranked roles: repeated scene/chapter quality failures can rotate `batch_prose`/`batch_editing` (and semantic/coherence retries can rotate `coherence_check`) to the next ranked fallback model instead of repeating the same failing model path.

When a scene retry is triggered by minimum-word validation, StoryCraftr injects a craft-aware correction directive that explicitly asks the model to deepen Goal/Conflict/Disaster/Sequel rather than adding filler.

### Book Generation Quick Start

Use this command from your project root:

```bash
storycraftr book --seed seed.md --chapters 3 --yes
```

Expected output structure after a successful run:

```text
<project>/
  .storycraftr/
  chapters/
  outline/canon.yml
  outline/narrative_state.json
```

`storycraftr book` persists artifacts fail-closed on commit: state patch apply -> canon ledger write -> chapter markdown write.

Each successful run also writes a consolidated audit summary under `outline/book_audit.json` and `outline/book_audit.md` with per-chapter validator/coherence outcomes.

Per-chapter validator handoff artifacts are persisted under `outline/chapter_packets/chapter-<nnn>/`, including `validator_report.json`, scene-level validator reports, stage diagnostics, and canonical pre/post-commit packet context.

Operational note: for live OpenRouter runs, buy at least $10 in credits to avoid the free-tier 1000 req/day cap during repeated smoke or soak testing.

Model escalation stress test profile: copy `examples/rankings_stress_weak_primary.json` to `storycraftr/config/rankings.json` in a test branch/worktree to simulate a weaker prose primary and verify retry-time fallback rotation behavior under real-provider runs.

## 💬 Introducing Chat!!! – A Simple Yet Powerful Tool to Supercharge Your Conversations! 💥

Whether you're brainstorming ideas, refining your story, or just need a little creative spark, Chat!!! is here to help. It's a straightforward, easy-to-use feature that lets you dive deep into meaningful discussions, unlock new insights, and get your thoughts flowing effortlessly.

🚀 Sometimes, all you need is a little chat to get the gears turning! Try it out and watch your creativity soar!

![chat](https://res.cloudinary.com/dyknhuvxt/image/upload/v1729551304/chat-example_hdo9yu.png)

## Full Guide

For a complete guide, including more examples and instructions on how to fully leverage StoryCraftr, visit our **Getting Started** page:

👉 [**Getting Started with StoryCraftr**](https://storycraftr.app/getting_started.html) 👈

## Why StoryCraftr?

Writing a book is a journey that involves not only creativity but also structure, consistency, and planning. **StoryCraftr** is here to assist you with:

- **Worldbuilding**: Define the geography, history, cultures, and more.
- **Outline**: Generate a cohesive story outline, from character summaries to chapter synopses.
- **Chapters**: Automatically generate chapters, cover pages, and epilogues based on your ideas.

With StoryCraftr, you'll never feel stuck again. Let AI guide your creative process, generate ideas, and help you bring your world and characters to life.

## StoryCraftr Chat Feature 💬

The **StoryCraftr Chat** feature allows users to engage directly with an AI assistant, helping to brainstorm, refine, and improve your book in real time. The chat supports various commands for outlining, iterating, and world-building, making it a powerful tool for writers to create and enhance their stories interactively.

### Key Commands:

- **Iterate**: Refine character names, motivations, and even insert new chapters mid-book.  
  Example:

  ```bash
  !iterate insert-chapter 3 "Add a flashback between chapters 2 and 3."
  ```

  Target only one chapter:

  ```bash
  !iterate chapter 1 "Strengthen the reveal in the final scene."
  ```

- **Outline**: Generate the general plot, chapter summaries, or key plot points.  
  Example:

  ```bash
  !outline general-outline "Summarize the overall plot of a dystopian sci-fi novel."
  ```

- **Worldbuilding**: Build the world’s history, geography, and technology, or develop the magic system.  
  Example:

  ```bash
  !worldbuilding magic-system "Describe the 'magic' system based on advanced technology."
  ```

- **Chapters**: Write new chapters or adjust existing ones and generate cover text.  
  Example:

  ```bash
  !chapters chapter 1 "Write chapter 1 based on the synopsis." --unsafe-direct-write
  ```

`storycraftr chapters chapter` is now guarded and requires both `--unsafe-direct-write`
and `STORYCRAFTR_ALLOW_UNSAFE=1` because it bypasses BookEngine validation gates.

Example developer-only bypass:

```bash
# In your shell before launching chat/commands:
export STORYCRAFTR_ALLOW_UNSAFE=1

# Then inside chat:
!chapters chapter 1 "Write chapter 1 based on the synopsis." --unsafe-direct-write
```

You can start a chat session with the assistant using:

```bash
storycraftr chat --book-path /path/to/your/book
```

You can also launch the minimal terminal-native TUI command center:

```bash
storycraftr tui --book-path /path/to/your/book
```

Control-plane CLI groups are also available for scripting and CI workflows:

- `storycraftr state show|validate|audit`
- `storycraftr state extract --text "..." [--apply]` with verification status (`passed` vs `adjusted`), dropped-operation count, and surfaced verification issues.
- `storycraftr canon check --chapter <n> --text "..."`
- `storycraftr mode show|set|stop`
- `storycraftr models list|refresh|validate-rankings`
- `storycraftr memory status|search|remember`

Memory diagnostics examples:

```bash
storycraftr memory status
storycraftr memory status --format json
storycraftr memory search --query "Where is Elias?" --chapter 3 --format json
storycraftr memory search --query "Where is Elias?" --limit 5 --format ndjson
```

These control-plane surfaces now share a single implementation layer (`storycraftr/services/control_plane.py`) used by both CLI and TUI to keep runtime behavior consistent.

The v0.1 TUI is now state-driven: the project tree starts hidden by default,
the top bar shows a Narrative strip and Scene Timeline strip, and input routes
through existing CLI dispatchers without changing core agent execution.

Current TUI slash commands include:

- `/help` for a concise command reference
- `/status` for project/assistant/runtime status
- `/mode [manual|hybrid|autopilot [max_turns]]` to control TUI execution policy and autopilot turn limits
- `/stop` to force manual mode and clear remaining autopilot turns
- `/autopilot <steps> <prompt>` to run bounded autonomous turns when mode is `autopilot`
- `/state` to inspect current narrative context snapshot with version/timestamp metadata
- `/state audit [limit=<n>] [entity=<id>] [type=<character|location|plot_thread>]` to inspect append-only narrative state mutation history with optional filters
- `/state extract-last [apply]` to preview or apply deterministic prose-to-state patch extraction from the latest assistant response, including verification/retry diagnostics
- `/summary` and `/summary clear` to inspect or reset rolling compacted session context
- `/context` for an overview dashboard of summary/budget/model-cache diagnostics
- `/context summary`, `/context budget`, `/context models`, `/context memory` for focused runtime diagnostics
- `/context clear-summary`, `/context refresh-models`, and `/context refresh-memory` for summary reset, forced OpenRouter cache refresh, and memory runtime rebind diagnostics
- `/progress` to show canonical generation checkpoint status
- `/wizard` and `/wizard next` for guided pipeline recommendations
- `/pipeline` and `/pipeline next` as aliases for the wizard flow
- `/wizard set <field> <value>`, `/wizard show`, `/wizard plan`, `/wizard reset`
  for profile-based guided planning (advisory, no auto-execution)
- `/canon`, `/canon show [chapter]`, `/canon add <fact>`,
  `/canon add <chapter> :: <fact>`, `/canon pending`, `/canon accept <n[,m,...]>`,
  `/canon reject [n[,m,...]]`, `/canon clear [confirm]`
  for chapter-scoped writer-approved canon constraints and hybrid candidate review
- In `hybrid` mode, candidate extraction runs on the sub-agent worker pool and only accepted candidates are persisted.
- Prompt assembly now uses a scene-scoped context builder: explicit scene Goal/Conflict/Outcome, active chapter constraints, and bounded relevant context to reduce prompt bloat.
- In `autopilot` mode, `/autopilot` runs a bounded loop that verifies extracted canon candidates against accepted facts and fails closed on duplicate/conflicting candidates before commit.
- `/clear` to clear the output pane without resetting session state
- `/toggle-tree` to show/hide the project file tree when needed
- `/chapter <number>` and `/scene <label>` to set in-memory narrative focus
- `/session ...` and `/sub-agent ...` passthrough commands
- `/model-list` to show current free OpenRouter models from local cache
- `/model-list refresh` to force-refresh the OpenRouter catalog
- `/model-change <model_id>` to switch the active TUI session model safely

CLI model discovery:

- `storycraftr model-list` lists free OpenRouter models with discovered limits (`context_length`, `max_completion_tokens`).
- `storycraftr model-list --refresh` forces a live catalog refresh before rendering.
- `storycraftr models list` and `storycraftr models refresh` expose the same discovery flow under the grouped control-plane surface.
- `storycraftr models validate-rankings [--refresh] [--format text|json]` validates `storycraftr/config/rankings.json` fail-closed against strict runtime rules (role keys, `fallbacks`, model-id format, live free-model availability, and coherence context limits).

Keyboard ergonomics:

- `Ctrl+L` toggles focus mode by hiding/showing sidebar and top strips
- `Up` / `Down` arrows navigate prompt history in the command input
- Slash commands now print inline `[Running]`, `[Done]`, or `[Failed]` progress lines

Command discovery:

- `/help` now shows a grouped command menu (`Writing`, `Planning`, `World`, `Project`)
- `/help writing|planning|world|project` filters help to one category

For regular prompts, the TUI prepends a compact scene-scoped block
(`[Scene Plan]` + `[Scoped Context]`) before dispatching to the existing
assistant pipeline.

When Mem0 is installed locally, the scoped context can also include compact
long-term memory recalls (intent/event snippets) from prior turns. If Mem0 is
not installed or unavailable, generation behavior degrades safely with no
memory-layer dependency.

Mem0 runtime behavior can be adjusted with environment flags:

- `STORYCRAFTR_MEM0_ENABLED=true|false` enables or disables Mem0 integration.
- `STORYCRAFTR_MEM0_FORCE_PROVIDER=ollama|openrouter|openai` forces provider mode.
- `STORYCRAFTR_MEM0_FORCE_OPENROUTER=true|false` explicitly toggles OpenRouter mode.

Provider recipes:

```bash
# Local-first Mem0 runtime (Ollama)
export STORYCRAFTR_MEM0_FORCE_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434

# OpenRouter-compatible Mem0 runtime
export STORYCRAFTR_MEM0_FORCE_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-v1-...
```

Generated responses now pass through deterministic state extraction before canon
diagnostics. Valid patches are applied through the existing narrative-state
validation and audit trail pipeline.

In `hybrid` and `autopilot` modes, generation now includes one bounded
state-critic retry: when extraction verification surfaces unsafe transitions,
the TUI requests a single constrained revision before post-generation hooks run.

During long sessions, the TUI automatically rolls older transcript turns into a
persisted summary (`sessions/session.json`) and injects that summary as
budgeted context ahead of recent verbatim turns.

For help with available commands during the session, simply type:

```bash
help()
```

## VSCode Extension

We are excited to introduce the **StoryCraftr** VSCode extension, designed to seamlessly integrate the StoryCraftr CLI into your development environment. This extension allows you to interact with StoryCraftr directly from VSCode, offering powerful tools for novel writing and AI-assisted creativity.

### Key Features:

- **Auto-detection**: Automatically detects if `storycraftr.json` or `papercraftr.json` is present in the project root, ensuring the project is ready to use.
- **Integrated Chat**: Start interactive AI-powered chat sessions for brainstorming and refining your novel without leaving VSCode.
- **Simplified Setup**: If StoryCraftr or its dependencies (Python, pipx) are not installed, the extension assists you in setting them up.
- **Event mirroring**: Chat turns and sub-agent status updates are emitted to `vscode-events.jsonl` (path is configurable via `vscode_events_file`).

### Usage:

Once installed, the extension will:

1. Check if `storycraftr.json` or `papercraftr.json` exists in the root of your project.
2. If one exists, you can start interacting with StoryCraftr by launching a terminal with the `chat` command using:
   - **Command Palette**: Run `Start StoryCraftr Chat`.
3. If not installed, it will guide you through installing Python, pipx, and StoryCraftr to get started.

Let your creativity flow with the power of AI! ✨

## Testing

Run the full Python suite with:

```bash
poetry run pytest
```

Recent regression coverage includes:

- OpenRouter validation hardening (`tests/unit/test_llm_factory.py`)
- Deterministic sub-agent shutdown cancellation behavior (`tests/unit/test_subagent_jobs.py`)
- Runtime path invariants for configurable internal state directories (`tests/unit/test_core_paths.py`)
- CLI init smoke flow with isolated filesystem and mocked model bootstrap (`tests/integration/test_cli_smoke.py`)

All tests are designed to run offline without live LLM network calls.

## Contributing

We welcome contributions of all kinds! Whether you’re a developer, writer, or simply interested in improving the tool, you can help. Here’s how you can contribute:

Before changing code, start with `docs/architecture-onboarding.md`. It is the
consolidated contributor reading guide and points to the smaller set of docs
that are actually mandatory for most changes.

For the one-file maintenance catalog (doc categories, runtime contract files,
and update-sync rules), use `docs/contributor-reference.md`.

1. **Fork the repository** and create your branch:

```bash
git checkout -b feature/YourFeature
```

2. **Make your changes**, ensuring all tests pass.

3. **Submit a pull request** detailing your changes.

Join us on this journey to create an amazing open-source tool for writers everywhere. Together, we can make StoryCraftr the go-to AI writing assistant! 💡

## Powered by AI Craftr

**StoryCraftr** is part of the **AI Craftr** suite, an open-source set of tools designed to assist with creative and academic writing. AI Craftr enhances the productivity of writers, researchers, and educators, providing advanced tools for content creation.

![AI Craftr Logo](https://res.cloudinary.com/dyknhuvxt/image/upload/v1730059761/aicraftr_qzknf4.png)

You can learn more about **AI Craftr** and discover other tools like **PaperCraftr** for academic writing at [https://aicraftr.app](https://aicraftr.app).
