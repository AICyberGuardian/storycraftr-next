# Changelog

## [v0.14] - 2026-03-03

### Summary of differences between `v0.14` branch and `main` branch

**File-level differences: None.** Both branches share an identical working tree
(`git tree 4a44def0`). The `main` branch incorporated all `v0.14` changes via the
squash-merge commit `cb440c2 Consolidate all changes into v0.14 (#43)`.

The three files changed relative to their common ancestor (`037df3a`) in both branches:

1. **`.github/workflows/ci-failure-fix.yml`** *(new file)*: Auto-Fix CI Failures
   workflow that triggers on test-suite failure and invokes Jules to diagnose and
   fix the root cause automatically.

2. **`README.md`** *(modified)*: Removed the VS Code extension Marketplace installation
   section and one outdated external CLI reference link.

3. **`tests/test_markdown.py`** *(modified)*: Aligned test mocks to use `pathlib.Path`
   methods (`pathlib.Path.exists`, `pathlib.Path.open`) instead of `os.path.exists`
   and `builtins.open`, matching the pathlib-based implementation in the source.

### Commit history differences

| Branch | Unique commits since common ancestor |
|--------|--------------------------------------|
| `main` | 1 squash commit (`cb440c2 Consolidate all changes into v0.14 (#43)`) |
| `v0.14` | 249+ individual feature/fix/chore commits |

### Added (accumulated across v0.11.4-beta9 → v0.14)

- **Auto-Fix CI Failures workflow**: New `.github/workflows/ci-failure-fix.yml` that
  automatically detects test failures and submits a fix via Jules.
- **pathlib-aligned tests**: `tests/test_markdown.py` updated so mock patches target
  `pathlib.Path` rather than `os.path`/`builtins.open`.

### Changed

- **README.md**: Removed VS Code Marketplace installation instructions and one
  stale external CLI reference link.

---

## [0.12.0-beta11] - 2026-03-02

### Added

- **CI hardening**: Stabilised GitHub Actions workflows, de-duplicated runs, and
  hardened pre-commit configuration.

### Changed

- **Version bump**: Package version incremented from `0.12.0-beta10` to
  `0.12.0-beta11`.
- **README cleanup**: Removed GitHub Actions status badges and installation
  instructions for the VS Code extension Marketplace.

---

## [0.12.0-beta10] - 2026-03-02

### Security

- **Subprocess argument injection fix (PDF generation)**: Added strict input
  validation in `generate_pdf` to prevent shell-injection via crafted file paths
  passed to the subprocess call.
- **VS Code extension installer hardening**: Fixed subprocess argument injection
  risk in the VS Code extension installer.

### Added

- **Improved VS Code companion extension**: Enhanced the event-driven companion
  extension with better sentinel detection and optimised file-system scanning.

### Fixed

- **Sub-agent stdout bleed**: Suppressed stdout bleed in sub-agent execution and
  expanded console swap coverage.

---

## [0.11.4-beta9] - 2026-03-01

### Added

- **Native PDF rendering**: `feat(pdf)` – Render Markdown natively with a themed
  book layout instead of delegating to external pandoc/LaTeX pipelines.
- **Redesigned CLI chat**: `feat(chat)` – Rebuilt the interactive chat session
  using a LangChain graph with full session UI.
- **LangChain runnable graph**: `feat(graph)` – Orchestrate the assistant flow via
  a LangChain runnable pipeline.
- **Async sub-agent runners**: `feat(chat)` – Added asynchronous sub-agent runners
  for parallel task processing inside a chat session.
- **Event-driven VS Code companion extension**: `feat(vscode)` – Scaffolded a new
  event-driven companion extension; emits a VS Code event stream and prompts the
  user to install the extension when detected.

---

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
