[![GitHub Actions Status](https://github.com/AICyberGuardian/storycraftr-next/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/AICyberGuardian/storycraftr-next/actions)
[![GitHub Actions Status](https://github.com/AICyberGuardian/storycraftr-next/actions/workflows/pytest.yml/badge.svg)](https://github.com/AICyberGuardian/storycraftr-next/actions)

# <img src="https://res.cloudinary.com/dyknhuvxt/image/upload/f_auto,q_auto/ofhhkf6f7bryfgvbxxwc" alt="StoryCraftr Logo" width="100" height="100"> StoryCraftr - Your AI-powered Book Creation Assistant 📚🤖

Welcome to [**StoryCraftr**](https://storycraftr.app), the open-source project designed to revolutionize how books are written. With the power of AI and a streamlined command-line interface (CLI), StoryCraftr helps you craft your story, manage worldbuilding, structure your book, and generate chapters — all while keeping you in full control.

---

## What's New? Discover AI Craftr 🌐

**[AI Craftr](https://aicraftr.app)** is now available as a powerful suite for AI-assisted writing, featuring specialized tools like **StoryCraftr** for novelists and **[PaperCraftr](https://papercraftr.app)** for researchers. Each tool is designed to simplify your writing process with unique features catered to different types of content. Explore **PaperCraftr** for structuring academic papers, or stay tuned as we add more tools to the AI Craftr suite, such as **LegalCraftr** for legal documents and **EduCraftr** for educational materials.

---

## Development Cycle v0.15.x

Current development target: `v0.15.x` (`0.15.0-dev`).

For in-progress changes, see `CHANGELOG.md` under `[Unreleased]`.

## Step 1: Install StoryCraftr

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
  "embed_model": "BAAI/bge-large-en-v1.5",
  "embed_device": "auto",
  "embed_cache_dir": ""
}
```

- `llm_provider` accepts `openai`, `openrouter`, or `ollama`.
- For `llm_provider=openrouter`, set `llm_model` explicitly in `provider/model` format (for example `meta-llama/llama-3.3-70b-instruct`).
- `llm_endpoint` lets you target custom bases (e.g., `https://openrouter.ai/api/v1`).
- StoryCraftr now validates provider/model/endpoint settings before runtime model calls and raises provider-specific configuration/authentication errors early.
- `max_tokens` caps completion length per LLM request (default `8192`) to reduce truncation risk on long generations.
- `embed_model` defaults to `BAAI/bge-large-en-v1.5` for OpenAI-quality local embeddings. Use a lighter model (e.g., `sentence-transformers/all-MiniLM-L6-v2`) on constrained hardware.

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
  --embed-model "BAAI/bge-large-en-v1.5"
```

### Generate a general outline:

```bash
storycraftr outline general-outline "Summarize the overall plot of a dystopian science fiction where advanced technology, resembling magic, has led to the fall of humanity’s elite and the rise of a manipulative villain who seeks to destroy both the ruling class and the workers."
```

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
  !chapters chapter 1 "Write chapter 1 based on the synopsis."
  ```

You can start a chat session with the assistant using:

```bash
storycraftr chat --book-path /path/to/your/book
```

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
