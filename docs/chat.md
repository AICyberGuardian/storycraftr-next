# StoryCraftr Chat Feature Tutorial 💬✨

![chat](https://res.cloudinary.com/dyknhuvxt/image/upload/v1729551304/chat-example_hdo9yu.png)

## Getting Help in Chat

At any time, if you're unsure of what commands are available or how to use them, you can get help within the chat by typing:

```bash
help()
```

This will provide a list of available commands and their usage.

## Using Multi-word Prompts

When interacting with the StoryCraftr assistant, it's important to enclose multi-word inputs in quotes to ensure they are processed as a single cohesive prompt. For example:

`[You]: "Explain how Zevid manipulates the elite using their own biotechnology in the rebellion."`

This ensures that the assistant treats the entire input as one argument rather than splitting it into separate terms.

**Bonus!** The assistant is pre-loaded with the full StoryCraftr documentation, so you can ask it about any command or feature. For example, if you need help with a specific command:

`[You]: "Show me how to use the insert-chapter command and its parameters."`

This will provide you with clear guidance directly within the chat, ensuring you have everything you need to use StoryCraftr to its full potential!

## Overview

The **Chat** feature in **StoryCraftr** allows you to interact directly with the AI assistant to brainstorm ideas, refine content, or improve any aspect of your book in real time. The feature includes the ability to prompt specific commands related to story development, iterative refinement, and world-building, all from within the chat environment. Reliability stack contracts (prompt-budget preflight, structured retry logging, validator checks) are enforced throughout chat-driven workflows, and audit artifacts are persisted for each chapter and scene.

## Getting Started with Chat

Before you can use the chat feature, ensure that you have **StoryCraftr** installed and that your book project is initialized. Once your project is ready, you can start a chat session with this command:

```bash
storycraftr chat --book-path /path/to/your/book
```

### Example:

```bash
storycraftr chat --book-path ~/projects/la-purga-de-los-dioses
```

Once the session starts, you’ll be able to type messages to the assistant and receive responses directly in your terminal.

If you want a structured terminal dashboard instead of REPL-only chat, launch
the Textual TUI:

```bash
storycraftr tui --book-path /path/to/your/book
```

The TUI adds a narrative-memory strip, scene timeline strip, and slash commands
for command discovery/model operations while still reusing the same StoryCraftr
assistant/backend flow.

### Key TUI Slash Commands

- `/help` — Show available TUI slash commands.
- `/status` — Show active project/provider/model and assistant retrieval status.
- `/mode [manual|hybrid|autopilot [max_turns]]` — Set execution mode and optional autopilot turn limits.
- `/stop` — Force manual mode and clear remaining autopilot turns.
- `/autopilot <steps> <prompt>` — Run bounded autonomous turns when execution mode is `autopilot`.
- `/state` — Show active narrative state snapshot with version and timestamp metadata.
- `/state audit [limit=<n>] [entity=<id>] [type=<character|location|plot_thread>]` — Query append-only state audit history with optional filters.
- `/summary` and `/summary clear` — Inspect or reset rolling compacted session summary state.
- `/context` — Show a compact runtime diagnostics dashboard (summary, budget, model cache).
- `/context summary` — Show full rolling summary state (status, compacted turns, summary text).
- `/context budget` — Show latest prompt budget and deterministic pruning/truncation diagnostics.
- `/context prompt` — Show stage-by-stage prompt composition diagnostics for planner, drafter, and editor turns.
- `/context prompt debug [on|off]` — Toggle planner-directive debug logging after each planner stage.
- `/context models` — Show OpenRouter cache metadata and resolved active-model limits/source.
- `/context memory` — Show long-term memory runtime diagnostics (status, provider mode, storage path, last persist status).
- `/context memory explain` — Show detailed breakdown of the latest recall pass, including source order and selected memory lines by source.
- `/context conflicts` — Show the latest canon conflict diagnostics (candidate counts, grouped reasons, details).
- `/context clear-summary` — Clear compacted summary while retaining recent transcript tail.
- `/context refresh-models` — Force-refresh OpenRouter model discovery cache and report status.
- `/context refresh-memory` — Rebind the memory runtime and print refreshed diagnostics.
- `/progress` — Show canonical writing-pipeline checkpoint completion.
- `/wizard` and `/wizard next` — Guided pipeline view and next-step recommendation.
- `/pipeline` and `/pipeline next` — Alias for wizard-guided pipeline flow.
- `/wizard set <field> <value>`, `/wizard show`, `/wizard plan`, `/wizard reset`
  — Build and revise a guided command plan from writer inputs.
- `/canon`, `/canon show [chapter]`, `/canon add <fact>`,
  `/canon add <chapter> :: <fact>`, `/canon check-last`, `/canon pending`, `/canon accept <n[,m,...]>`,
  `/canon reject [n[,m,...]]`, `/canon clear [confirm]`
  — Manage writer-approved chapter canon facts and hybrid extraction candidate approvals.
- `/clear` — Clear the output pane while keeping current session context.
- `/toggle-tree` — Show/hide the project file tree (hidden by default).
- `/chapter <number>` and `/scene <label>` — Set active narrative focus.
- `/model-list` — Display free OpenRouter models from local discovery cache.
- `/model-list refresh` — Force-refresh the OpenRouter catalog before rendering.
- `/model-change <model_id>` — Switch the active TUI session model.
- `/session ...` and `/sub-agent ...` — Route to existing chat command handlers.

### Control-Plane CLI Commands

- `storycraftr state show` — Print the current narrative-state snapshot.
- `storycraftr state validate` — Run consistency checks on narrative-state data.
- `storycraftr state audit --format json` — Query append-only state audit history.
- `storycraftr state extract --text "..." [--apply]` — Build deterministic state patch proposals from prose and optionally apply them; output includes verification status, dropped-operation count, and any verification issues.
- `storycraftr canon check --chapter <n> --text "..."` — Verify candidate facts against accepted chapter canon.
- `storycraftr mode show|set|stop` — Inspect or mutate persisted execution mode state.
- `storycraftr models list|refresh` — List or refresh free OpenRouter discovery results.
- `storycraftr models validate-rankings [--refresh] [--format text|json]` — Fail-closed validation for `storycraftr/config/rankings.json` using strict schema/runtime checks and live free-model compatibility rules.
- `storycraftr memory status [--format text|json]` — Show long-term memory runtime status and provider diagnostics.
- `storycraftr memory search --query "..." [--chapter N] [--limit K] [--format table|json|ndjson]` — Search persisted memory recalls.
- `storycraftr memory remember --user "..." --assistant "..." [--chapter N] [--scene LABEL]` — Persist one explicit memory turn.

The control-plane runtime logic is centralized in `storycraftr/services/control_plane.py` and shared by both Click commands and TUI slash commands to avoid feature drift.

The TUI now also supports `/state extract-last [apply]` to preview/apply deterministic extraction from the latest assistant response, including one bounded dependency-order retry and verification diagnostics.
When mode policy enables auto-regeneration (`/mode hybrid` or `/mode autopilot`),
normal generation applies one bounded state-critic retry: if extraction
verification detects unsafe transitions, a single constrained revision is
requested before post-generation hooks run.

### Keyboard Shortcuts

- `Ctrl+L` — Toggle focus mode (hide/show sidebar and state strips).
- `Up` / `Down` — Navigate command input history.

Slash commands also emit inline status markers (`[Running]`, `[Done]`, `[Failed]`) so long-running tasks provide immediate feedback in the output pane.

The TUI help menu is grouped by intent (`Writing`, `Planning`, `World`, `Project`), and `/help <topic>` shows only one group.

For normal prompts, the TUI prepends structured sections before calling the
existing assistant pipeline: `[Canon Constraints]`, `[Scene Plan]`,
`[Planner Rules]`, `[Drafter Rules]`, `[Editor Rules]`, `[Scoped Context]`, optional `[Structured Narrative State]`, optional
`[Session Summary]` and `[Recent Dialogue]`, then `[User Instruction]`.

The three craft-rule sections are loaded from static prompt fragments in
`storycraftr/prompts/planner_rules.md`, `storycraftr/prompts/drafter_rules.md`,
and `storycraftr/prompts/editor_rules.md` (derived from the canonical
`storycraftr/prompts/corpus.md`). They are injected deterministically to avoid
retrieval misses for universal storytelling mechanics.

Planner-stage JSON parsing remains fail-closed. If planner output is invalid,
the runtime performs one bounded repair pass. If that also fails and a prior
valid `SceneDirective` exists, the system reuses that last validated directive
for continuity and emits a visible warning in the output pane.

When Mem0 is available in the local environment, `[Scoped Context]` may include
compact long-term memory recalls (intent/event snippets) to reduce narrative
drift across long autonomous runs. Memory retrieval is **query-aware**: the
system uses the user's current prompt to retrieve semantically relevant memories
before falling back to generic intent/event queries. If Mem0 is unavailable,
this layer is silently skipped and standard context composition continues.

Memory token budgets are **model-aware**: larger context models (e.g., 128k tokens)
receive proportionally larger memory budgets (up to 1280 tokens) to take advantage
of available capacity, while smaller models (e.g., 8k tokens) use conservative
budgets (160+ tokens) to preserve space for critical prompt sections.

Memory retrieval strategy is now **storyline-aware**: after the user's prompt
query, recall prioritizes recent chapter continuity (active chapter and previous
chapter), then active scene/arc cues, then broader character-state and
plot-thread signals before generic fallback intent/event queries.

After generation, the system attempts to persist the turn to long-term memory.
When memory is enabled and persistence fails, a warning is displayed in the
output pane and the failure is logged to `/context memory` diagnostics for
operator review.

`/context memory` and `storycraftr memory status` now include recall telemetry
from the latest retrieval pass (hits returned, query stages run/attempted, and
hit distribution by source label) to help tune memory strategy behavior.
Use `/context memory explain` to inspect which source label contributed each
selected memory line in the latest retrieval snapshot.

Mem0 runtime mode follows StoryCraftr provider settings:
- `llm_provider=ollama` uses local Ollama inference for memory extraction plus local embedding model.
- `llm_provider=openrouter` uses OpenRouter-compatible Mem0 LLM routing when `OPENROUTER_API_KEY` is present.
- Other providers fall back to Mem0's OpenAI-compatible mode.

Mem0 behavior can be overridden with environment flags:
- `STORYCRAFTR_MEM0_ENABLED=true|false` enables/disables Mem0 integration.
- `STORYCRAFTR_MEM0_FORCE_PROVIDER=ollama|openrouter|openai` forces provider mode.
- `STORYCRAFTR_MEM0_FORCE_OPENROUTER=true|false` explicitly toggles OpenRouter mode.

Example provider setups:

```bash
# Local-first memory runtime
export STORYCRAFTR_MEM0_FORCE_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434

# OpenRouter-compatible memory runtime
export STORYCRAFTR_MEM0_FORCE_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-v1-...
```

After generation, the TUI runs a lightweight, warn-only canon conflict check
against accepted chapter facts and surfaces likely duplicates/contradictions as
`Potential Canon Conflicts` in the output pane for writer review.

Before canon warnings, generated responses are processed by deterministic state
extraction and validation; accepted patch operations are committed to
`outline/narrative_state.json` and logged to `outline/narrative_audit.jsonl`.
 
`storycraftr book` follows the same continuity contract on successful commit and
additionally persists chapter-scoped canon facts to `outline/canon.yml`
(including a stable `plot_threads` fact snapshot) before writing
`chapters/chapter-<n>.md`.

Writers can rerun the same continuity scan at any time with `/canon check-last`,
and inspect grouped diagnostics with `/context conflicts`.

Prompt assembly is now model-aware: the TUI computes an input budget from the
active model context window, reserves output tokens (`max_tokens` from config
when available), and prunes context in deterministic priority order:
canon constraints -> scene/scoped context -> minimal recent turns -> retrieval
chunks -> lower-priority extras.

OpenRouter model metadata is discovered dynamically from
`https://openrouter.ai/api/v1/models`, cached locally for 6 hours in
`~/.storycraftr/openrouter-models-cache.json`, and reused in stale mode if the
upstream API is temporarily unavailable.

`/model-change` validates requested OpenRouter models against the current
free-only discovery catalog; paid, unknown, or unavailable models are rejected.
Long-running sessions now apply rolling transcript compaction: older turns are
collapsed into a bounded `Session Summary` with adaptive retention of
scene/canon/reveal anchor turns, and persisted in
`sessions/session.json`, while the most recent turns remain verbatim in prompt
context.

Canon candidate commits from `/autopilot` are verified against accepted
chapter facts before write; duplicate or contradiction-like candidates are
skipped (fail-closed) and reported in command output.

## Available Commands within Chat

While in a chat session, you can use commands to quickly execute tasks that StoryCraftr supports, such as refining your outline, improving chapters, or updating your world-building. These commands provide flexibility, allowing you to iterate on various aspects of your novel without leaving the chat.

### Command Examples

You can trigger the following commands within the chat by typing the appropriate prompt.

### **Iterate**: Refining the Story Iteratively

The **Iterate** commands are designed to help you iteratively improve the book's content. You can refine specific aspects such as character names, motivations, or plot points.

- **Check character names**:

  ```bash
  !iterate check-names "Check character names for consistency."
  ```

- **Refine character motivation**:

  ```bash
  !iterate refine-motivation "Refine character motivation for Zevid."
  ```

- **Check consistency**:

  ```bash
  !iterate check-consistency "Ensure consistency of character arcs and motivations."
  ```

  This runs as a global batch pass across all chapter files.

- **Target a single chapter**:

  ```bash
  !iterate chapter 1 "Tighten dialogue and add a stronger cliffhanger ending."
  ```

- **Insert a chapter**:

  ```bash
  !iterate insert-chapter 3 "Insert a chapter about Zevid's backstory between chapters 2 and 3."
  ```

### **Outline**: Outlining the Book

The **Outline** commands help you generate or refine various components of your book's outline, including character summaries, plot points, or the entire general outline.

- **General outline**:

  ```bash
  !outline general-outline "Summarize the overall plot of a dystopian sci-fi novel."
  ```

- **Plot points**:

  ```bash
  !outline plot-points "Identify key plot points in the story."
  ```

- **Character summary**:

  ```bash
  !outline character-summary "Summarize Zevid’s character."
  ```

- **Chapter synopsis**:

  ```bash
  !outline chapter-synopsis "Outline each chapter of a dystopian society."
  ```

### **Worldbuilding**: Building the World of Your Story

With **Worldbuilding** commands, you can flesh out various aspects of your story's world, such as the history, culture, and even the "magic" system (which could be advanced technology in disguise).

- **History**:

  ```bash
  !worldbuilding history "Describe the history of a dystopian world."
  ```

- **Geography**:

  ```bash
  !worldbuilding geography "Describe the geography of a dystopian society."
  ```

- **Culture**:

  ```bash
  !worldbuilding culture "Describe the culture of a society controlled by an elite class."
  ```

- **Technology**:

  ```bash
  !worldbuilding technology "Describe the advanced biotechnology mistaken for magic."
  ```

- **Magic system**:

  ```bash
  !worldbuilding magic-system "Describe the 'magic' system based on advanced technology."
  ```

### **Chapters**: Managing and Writing Specific Chapters

The **Chapters** commands focus on generating or improving specific chapters of your book. You can also create cover and back-cover text for your novel using this command group.

- **Generate a chapter**:

  ```bash
  !chapters chapter 1 "Write chapter 1 based on the synopsis provided." --unsafe-direct-write
  ```

  Direct chapter writes bypass `storycraftr book` validator gates and now require
  both explicit opt-ins: `--unsafe-direct-write` and `STORYCRAFTR_ALLOW_UNSAFE=1`
  (set in your shell before launching StoryCraftr chat).

  ```bash
  export STORYCRAFTR_ALLOW_UNSAFE=1
  storycraftr chat --book-path /path/to/your/book
  ```

- **Insert a chapter**:

  ```bash
  !chapters insert-chapter 5 "Insert a chapter revealing Zevid’s manipulation."
  ```

- **Generate cover text**:

  ```bash
  !chapters cover "Generate the cover text for the novel."
  ```

- **Generate back-cover text**:

  ```bash
  !chapters back-cover "Generate the back-cover text for the novel."
  ```

## Exiting the Chat

When you're ready to exit the chat, simply type:

```bash
exit()
```

This will end the chat session and return you to the terminal.

## Sub-Agent Background Jobs

While command shortcuts are great for quick edits, some operations (large outlines, full chapter rewrites, PDF builds) take time. Prefix those with `:sub-agent` to run them in the background via role-specific prompts that live under `subagents_dir` (default: `.storycraftr/subagents/`).

- Inspect roles and their whitelisted commands:

  ```bash
  :sub-agent !list
  :sub-agent !describe editor
  ```

- Queue a command with an explicit role:

  ```bash
  :sub-agent !outline editor general-outline "Tighten the pacing for Act II"
  ```

- Let StoryCraftr auto-select a role (it matches the `!command` against each role’s whitelist):

  ```bash
  :sub-agent !chapters chapter 5 "Reframe the midpoint twist" --unsafe-direct-write
  ```

- Monitor background work or inspect past outputs:

  ```bash
  :sub-agent !status
  :sub-agent !logs continuity
  ```

- Reseed the role YAML files (useful after changing languages):

  ```bash
  :sub-agent !seed --language es --force
  ```

While a job runs, the chat shows `[Role ⏳ …]` badges and drops a completion panel in-line when the task finishes. Raw logs are stored in `subagent_logs_dir/<role>/timestamp.md` (default: `.storycraftr/subagents/logs/<role>/timestamp.md`), so pipx users can still review them outside the chat.

If the model returns a transient exhaustion/rate-limit error (for example `429`), the job enters a temporary `model_exhausted` state, performs a bounded cooldown, and retries once before reporting a final failure.

## VS Code Event Stream

Launching `storycraftr chat` inside the VS Code terminal enables a JSONL event feed at `vscode_events_file` (default: `.storycraftr/vscode-events.jsonl`). The StoryCraftr companion extension tails this file to mirror chat turns, background jobs, and command output in the editor (Status Bar counts, output channel, and log prompts). Remove the file if you want to reset or disable the stream.

When VS Code is detected, the CLI also offers to install/update the `storycraftr.storycraftr` extension automatically (it shells out to `code --install-extension`). Decline the prompt to skip the installation and run the command manually later.

## Conclusion

The **StoryCraftr Chat** feature, combined with powerful commands like **Iterate**, **Outline**, **Worldbuilding**, and **Chapters**, provides you with everything you need to write your book efficiently. Whether you are refining existing content or generating new chapters, this feature allows you to enhance your creative process with ease.

---

Happy writing with **StoryCraftr** and its powerful chat feature! ✍️✨
