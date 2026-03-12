# Component Inventory

```yaml
inventory_version: "2026-03-11"
project: "storycraftr-next"
format: "machine-readable-markdown"

external_components:
    - name: "tiktoken"
      category: "tokenizer"
      used_for: ["prompt-budget preflight", "token counting"]
      files:
        - "storycraftr/llm/factory.py"

    - name: "structlog"
      category: "logging"
      used_for: ["structured retry/quarantine logging", "validator logs"]
      files:
        - "storycraftr/llm/factory.py"
        - "storycraftr/agent/chapter_validator.py"

    - name: "pysbd"
      category: "sentence-boundary detection"
      used_for: ["chapter validator truncation detection"]
      files:
        - "storycraftr/agent/chapter_validator.py"

    - name: "tenacity"
      category: "retry logic"
      used_for: ["bounded retries for OpenRouter invocation"]
      files:
        - "storycraftr/llm/factory.py"

    - name: "pybreaker"
      category: "circuit breaker"
      used_for: ["resilient model router for OpenRouter"]
      files:
        - "storycraftr/llm/factory.py"

    - name: "flashtext2"
      category: "entity-ledger checks"
      used_for: ["deterministic chapter validation"]
      files:
        - "storycraftr/agent/book_engine.py"

    - name: "pydantic"
      category: "contract validation"
      used_for: ["scene directive validation", "validator contract enforcement"]
      files:
        - "storycraftr/agent/book_engine.py"
  - name: "langchain-core"
    category: "orchestration"
    used_for: ["prompts", "runnables", "documents", "chat model interfaces"]
    files:
      - "storycraftr/graph/assistant_graph.py"
      - "storycraftr/agent/agents.py"
      - "storycraftr/llm/factory.py"

  - name: "langchain-openai"
    category: "llm-provider-adapter"
    used_for: ["OpenAI/OpenRouter chat + embeddings compatibility"]
    files:
      - "storycraftr/llm/factory.py"
      - "storycraftr/llm/embeddings.py"

  - name: "langchain-community"
    category: "llm-provider-adapter"
    used_for: ["Ollama chat model adapter"]
    files:
      - "storycraftr/llm/factory.py"

  - name: "langchain-huggingface"
    category: "embedding-adapter"
    used_for: ["local HuggingFace embeddings wrapper"]
    files:
      - "storycraftr/llm/embeddings.py"

  - name: "langchain-text-splitters"
    category: "retrieval-preprocessing"
    used_for: ["document chunking for vector indexing"]
    files:
      - "storycraftr/agent/agents.py"

  - name: "langchain-chroma"
    category: "vectorstore-adapter"
    used_for: ["LangChain wrapper over Chroma collections"]
    files:
      - "storycraftr/vectorstores/chroma.py"
      - "storycraftr/agent/agents.py"

  - name: "chromadb"
    category: "vector-database"
    used_for: ["persistent local vector storage/retrieval"]
    files:
      - "storycraftr/vectorstores/chroma.py"

  - name: "mem0ai"
    import_name: "mem0"
    category: "long-term-memory"
    optional: true
    used_for: ["narrative turn memory persistence + recall"]
    files:
      - "storycraftr/agent/memory_manager.py"

  - name: "sentence-transformers"
    category: "embedding-model-runtime"
    used_for: ["local semantic embeddings"]
    files:
      - "storycraftr/llm/embeddings.py"

  - name: "torch"
    category: "ml-runtime"
    used_for: ["embedding device/runtime (cuda/mps/cpu)"]
    files:
      - "storycraftr/llm/embeddings.py"

  - name: "requests"
    category: "http-client"
    used_for: ["OpenRouter model catalog fetch"]
    files:
      - "storycraftr/llm/openrouter_discovery.py"

  - name: "pydantic"
    category: "schema-validation"
    used_for: ["narrative state models + patch schemas"]
    files:
      - "storycraftr/agent/narrative_state.py"

  - name: "jsonschema"
    category: "schema-validation"
    used_for: ["validator_report contract enforcement"]
    files:
      - "storycraftr/cmd/story/book.py"

  - name: "json-repair"
    category: "structured-output-hardening"
    used_for: ["repair malformed JSON from model outputs"]
    files:
      - "storycraftr/agent/generation_pipeline.py"
      - "storycraftr/agent/state_extractor.py"
      - "storycraftr/cmd/story/book.py"

  - name: "click"
    category: "cli-framework"
    used_for: ["CLI command definitions + options"]
    files:
      - "storycraftr/cli.py"
      - "storycraftr/cmd/**/*.py"

  - name: "rich"
    category: "cli-rendering"
    used_for: ["console output, progress, markdown rendering"]
    files:
      - "storycraftr/cli.py"
      - "storycraftr/cmd/**/*.py"
      - "storycraftr/chat/render.py"

  - name: "textual"
    category: "terminal-ui"
    used_for: ["interactive TUI app"]
    files:
      - "storycraftr/tui/app.py"

  - name: "prompt-toolkit"
    category: "interactive-input"
    used_for: ["chat prompt session/history"]
    files:
      - "storycraftr/cmd/chat.py"

  - name: "keyring"
    category: "credential-storage"
    optional: true
    used_for: ["OS keyring API key storage with fallback"]
    files:
      - "storycraftr/llm/credentials.py"

  - name: "pyyaml"
    category: "serialization"
    used_for: ["canon/state YAML read/write"]
    files:
      - "storycraftr/cmd/story/book.py"
      - "storycraftr/tui/canon.py"
      - "storycraftr/subagents/storage.py"

  - name: "markdown-pdf"
    category: "publishing"
    used_for: ["markdown -> pdf rendering"]
    files:
      - "storycraftr/pdf/renderer.py"

  - name: "pandoc"
    category: "publishing-tooling"
    used_for: ["paper publish pipeline"]
    files:
      - "storycraftr/cmd/paper/publish.py"

  - name: "vscode-api"
    category: "editor-integration"
    used_for: ["VS Code companion extension event/log UI"]
    files:
      - "src/extension.ts"

internal_components:
  - name: "storycraftr.cli"
    category: "entrypoint"
    used_for: ["top-level CLI dispatch"]
    files:
      - "storycraftr/cli.py"

  - name: "book_pipeline_orchestrator"
    module: "storycraftr.cmd.story.book"
    category: "chapter-runner"
    used_for:
      - "outline/scene generation orchestration"
      - "model role routing"
      - "precommit/postcommit packet handling"
      - "fail-closed state/canon/chapter commit"
    files:
      - "storycraftr/cmd/story/book.py"

  - name: "book_engine"
    module: "storycraftr.agent.book_engine"
    category: "pipeline-engine"
    used_for:
      - "stage sequencing (plan/draft/edit/stitch/validate/state/coherence)"
      - "deterministic + semantic guard integration"
    files:
      - "storycraftr/agent/book_engine.py"

  - name: "generation_pipeline"
    module: "storycraftr.agent.generation_pipeline"
    category: "prompt-contract-layer"
    used_for: ["planner/drafter/editor prompt building", "planner JSON parsing/repair"]
    files:
      - "storycraftr/agent/generation_pipeline.py"

  - name: "state_extractor"
    module: "storycraftr.agent.state_extractor"
    category: "state-delta-extraction"
    used_for: ["prose -> patch operations/events"]
    modes: ["deterministic-regex", "structured-llm"]
    files:
      - "storycraftr/agent/state_extractor.py"

  - name: "narrative_state"
    module: "storycraftr.agent.narrative_state"
    category: "state-model-and-store"
    used_for: ["state snapshot models", "patch apply", "state audit entries"]
    files:
      - "storycraftr/agent/narrative_state.py"

  - name: "control_plane_service"
    module: "storycraftr.services.control_plane"
    category: "deterministic-ops"
    used_for:
      - "state extract/apply operations"
      - "patch verification/reorder"
      - "mode/canon/state commands for TUI/CLI"
    files:
      - "storycraftr/services/control_plane.py"

  - name: "assistant_runtime"
    module: "storycraftr.agent.agents"
    category: "assistant-composition"
    used_for:
      - "LLM + embeddings + vector store assembly"
      - "retriever setup and assistant graph wiring"
    files:
      - "storycraftr/agent/agents.py"

  - name: "assistant_graph"
    module: "storycraftr.graph.assistant_graph"
    category: "rag-graph"
    used_for: ["retrieval context formatting + answer chain"]
    files:
      - "storycraftr/graph/assistant_graph.py"

  - name: "vector_store_builder"
    module: "storycraftr.vectorstores.chroma"
    category: "storage-adapter"
    used_for: ["persistent Chroma initialization under project paths"]
    files:
      - "storycraftr/vectorstores/chroma.py"

  - name: "narrative_memory_manager"
    module: "storycraftr.agent.memory_manager"
    category: "memory-adapter"
    used_for: ["optional Mem0-backed memory write/recall"]
    files:
      - "storycraftr/agent/memory_manager.py"

  - name: "llm_factory"
    module: "storycraftr.llm.factory"
    category: "provider-abstraction"
    used_for:
      - "provider normalization/auth checks"
      - "OpenRouter resilient wrapper"
      - "role-based fallback/escalation wiring"
      - "model health registry"
    files:
      - "storycraftr/llm/factory.py"

  - name: "openrouter_discovery"
    module: "storycraftr.llm.openrouter_discovery"
    category: "catalog-cache"
    used_for: ["free model discovery + cache + limits lookup"]
    files:
      - "storycraftr/llm/openrouter_discovery.py"

  - name: "embeddings_factory"
    module: "storycraftr.llm.embeddings"
    category: "embedding-provider-abstraction"
    used_for: ["local hf embeddings or API embeddings"]
    files:
      - "storycraftr/llm/embeddings.py"

  - name: "credentials_manager"
    module: "storycraftr.llm.credentials"
    category: "secret-resolution"
    used_for: ["env -> keyring -> legacy file credential lookup/store"]
    files:
      - "storycraftr/llm/credentials.py"

  - name: "subagent_job_system"
    module: "storycraftr.subagents.jobs"
    category: "background-execution"
    used_for: ["queued subagent command execution, retries, cooldowns, logs"]
    files:
      - "storycraftr/subagents/jobs.py"

  - name: "textual_tui"
    module: "storycraftr.tui.app"
    category: "operator-console"
    used_for:
      - "interactive local control plane"
      - "model controls, state/canon tooling, memory strip display"
    files:
      - "storycraftr/tui/app.py"

  - name: "vscode_companion_extension"
    module: "src/extension.ts"
    category: "editor-observability"
    used_for:
      - "watch .storycraftr/vscode-events.jsonl"
      - "show transcript, sub-agent status, and log open prompts"
    files:
      - "src/extension.ts"

runtime_artifacts_and_configs:
  - name: "openrouter_rankings_config"
    path: "storycraftr/config/rankings.json"
    used_for: ["role primary/fallback model routing"]

  - name: "validator_report_schema"
    path: "storycraftr/config/validator_report.schema.json"
    used_for: ["packet validator report schema enforcement"]

  - name: "chapter_packets"
    path: "outline/chapter_packets/chapter-*/"
    used_for:
      - "precommit and failure forensics"
      - "scene/state/validator diagnostics persistence"

  - name: "book_audit"
    path: "outline/book_audit.json"
    used_for: ["run-level summary status and guard outcomes"]

notes:
  - "Provider support in code: openai, openrouter, ollama, fake."
  - "Mem0 and keyring are optional and degrade safely when unavailable."
  - "Extension side is TypeScript-only and does not embed LangChain/Chroma directly."
```
