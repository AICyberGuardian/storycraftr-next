# StoryCraftr Copilot Ecosystem Inventory

**Complete reference of all AI agents, instructions, skills, hooks, workflows, and tools available in this repository.**

---

## 📋 Quick Navigation

- [🤖 Agents (21)](#-agents)
- [📚 Instructions (6)](#-instructions)
- [🛠️ Skills (13)](#-skills)
- [🪝 Hooks (1)](#-hooks)
- [⚙️ Workflows (3)](#-workflows)
- [🎯 Usage Matrix](#-usage-matrix---when-to-use-what)

---

## 🤖 Agents

All agents use **GPT-5.3-Codex** unless otherwise noted. Agents are specialized AI experts that handle domain-specific tasks.

### Repository Maintenance Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **StoryCraftr Engineering Agent** | GPT-5.3-Codex | Principal Software Architect for repository maintenance, modernization, and technical debt reduction | Bug fixes, architecture improvements, dependency updates, performance optimization, safe refactors within the StoryCraftr-Next repository |

### Planning & Architecture Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **Planning Mode** | GPT-5.3-Codex | Generate implementation plans for features or refactoring | Before starting major feature work; request: "Create an implementation plan for..." |
| **gem-planner** | GPT-5.3-Codex | Creates DAG-based plans with pre-mortem analysis & task decomposition | Complex multi-step projects; failure mode analysis needed |
| **SE: Architect** | GPT-5.3-Codex | System architecture review with Well-Architected frameworks, design validation, scalability analysis | Architecture decisions, scalability concerns, security reviews |
| **Implementation Plan Generation Mode** | GPT-5.3-Codex | Generate fully executable implementation plans | Formal planning before development; handoff to other teams |
| **Context Architect** | GPT-5.3-Codex | Plans multi-file changes by identifying context & dependencies | Large refactors, cross-module changes |

### Code Generation & Development Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **Blueprint Mode Codex** | GPT-5.3-Codex | Executes structured workflows with strict correctness; minimal tool usage; self-correction | Complex coding tasks requiring reproducibility & edge-case handling |
| **WG Code Alchemist** | GPT-5.3-Codex | SOLID principles & Clean Code refactoring; eliminates code smells | Improving code quality, applying design patterns, extracting functions |
| **Universal Janitor** | GPT-5.3-Codex | Tech debt cleanup, code removal, simplification | Removing dead code, unused imports, simplifying logic |
| **OpenAPI to Application Generator** | GPT-5.3-Codex | Generates working applications from OpenAPI specifications | Generate complete app projects from API specs; scaffolding controllers, services, models |

### Testing Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **polyglot-test-agent** | GPT-5.3-Codex | Multi-agent test generation pipeline (C#, TS, JS, Python, Go, Rust, Java) | Write unit tests, improve coverage, create test files that compile & pass |
| **gem-reviewer** | GPT-5.3-Codex | Security gatekeeper; OWASP, secrets, compliance checking | Security audits, PRD compliance verification, detecting vulnerabilities |

### Documentation Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **documentation-writer** | GPT-5.3-Codex | Diátaxis framework expert; high-quality technical documentation | Create READMEs, API docs, user guides following best practices |
| **gem-documentation-writer** | GPT-5.3-Codex | Generates docs, diagrams; maintains code-documentation parity | Architecture diagrams, implementation guides, keeping docs in sync |

### Language-Specific Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **Python MCP Server Expert** | GPT-5.3-Codex | Builds production MCP servers using Python SDK; Pydantic, async/await | Developing Model Context Protocol servers in Python |
| **TypeScript MCP Server Expert** | GPT-5.3-Codex | Builds production MCP servers using TypeScript SDK; zod validation | Developing Model Context Protocol servers in TypeScript |

### Framework & Library Expert Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **Context7-Expert** | GPT-5.3-Codex | Latest library versions, best practices, syntax using up-to-date docs | Ask about specific libraries: "Next.js routing", "React hooks", "Tailwind CSS" |

### Governance & Safety Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **Agent Governance Reviewer** | GPT-5.3-Codex | Reviews code for agent safety, governance controls, policy enforcement | Building AI agents; implementing trust scoring, audit trails, rate limits |

### VS Code & Content Agents

| Agent | Model | Purpose | When to Use |
|-------|-------|---------|-----------|
| **VSCode Tour Expert** | GPT-5.3-Codex | Creates & maintains VSCode CodeTour files with guided walkthroughs | Create interactive tours of codebase for onboarding |

### Observability Agents (MCP-based)

| Agent | Purpose | When to Use |
|--------|---------|-----------|
| **Dynatrace Expert** | Observability & security analysis; investigate incidents, detect regressions, validate releases | Performance debugging, incident triage, release validation using Dynatrace data |
| **elasticsearch-agent** | Code debugging (O11y), vector search optimization (RAG), security threat remediation | Debugging with live Elastic data, optimizing vector search, security analysis |

### Infrastructure Agents

| Agent | Purpose | When to Use |
|--------|---------|-----------|
| **gem-orchestrator** | Team Lead—coordinates multi-agent workflows with task delegation & result synthesis | Complex multi-phase projects requiring agent coordination (disabled for direct invocation) |

---

## 📚 Instructions

Instructions are coding guidelines and standards that apply across the codebase. They're automatically applied based on file patterns.

| Instruction | Applies To | Purpose | Key Topics |
|-------------|-----------|---------|-----------|
| **agent-safety.instructions.md** | All files (`**`) | Guidelines for building safe, governed AI agent systems | Tool access controls, content safety, multi-agent safety, audit trails, governance |
| **context-engineering.instructions.md** | All files (`**`) | Maximize Copilot effectiveness through context management | Project structure, semantic naming, working with Copilot, multi-file changes |
| **performance-optimization.instructions.md** | All files (`*`) | Comprehensive performance optimization best practices | Profiling, algorithms, caching, database tuning, concurrency, language-specific tips |
| **python.instructions.md** | Python files (`**/*.py`) | Python coding conventions and standards | Type hints, docstrings, naming, error handling, testing patterns |
| **typescript-5-es2022.instructions.md** | TypeScript files (`**/*.ts`) | TypeScript 5.x development targeting ES2022 | Type safety, async patterns, module system, testing |
| **update-docs-on-code-change.instructions.md** | Code files (`.md, .js, .ts, .py, etc.`) | Keep documentation in sync with code changes | README updates, architecture docs, API documentation |

---

## 🛠️ Skills

Skills are domain-specific expertise packages that add specialized capabilities. Each skill contains detailed patterns, workflows, and best practices.

### AI Agent Skills

| Skill | Purpose | When to Use | Key Capabilities |
|-------|---------|-----------|-----------------|
| **agent-governance** | Add governance, safety, trust controls to AI agents | Building tool-calling LLMs, implementing policy-based access controls, semantic intent classification | Tool allowlists, rate limiting, audit trails, trust scoring |
| **agentic-eval** | Evaluate & improve AI agent outputs | Self-critique loops, quality-critical generation, iterative refinement | Evaluator-optimizer pipelines, rubric-based evaluation, LLM-as-judge |

### Architecture & Design Skills

| Skill | Purpose | When to Use | Key Capabilities |
|-------|---------|-----------|-----------------|
| **architecture-blueprint-generator** | Generate comprehensive architectural documentation | Starting new projects, architecture audits, design documentation | Auto-detect tech stacks, identify patterns, C4/UML diagrams, ADRs, deployment topology |
| **refactor** | Surgical code refactoring for maintainability | Improving code quality, applying design patterns, extracting functions | Incremental improvements, no behavior change |
| **refactor-plan** | Plan multi-file refactors with sequencing & rollback | Large refactoring efforts | DAG-based planning, failure analysis, safe execution order |

### Documentation Skills

| Skill | Purpose | When to Use | Key Capabilities |
|-------|---------|-----------|-----------------|
| **create-readme** | Create comprehensive README.md files | Initializing projects, documenting features | Project overview, setup, usage, contribution guidelines |
| **readme-blueprint-generator** | Intelligent README generation analyzing project structure | Documentation updates, design docs | Scans configs, extracts tech stack, generates markdown |

### Planning & Process Skills

| Skill | Purpose | When to Use | Key Capabilities |
|-------|---------|-----------|-----------------|
| **create-implementation-plan** | Create new implementation plan files | Before building features, refactoring, upgrades | Detailed task breakdown, dependencies, timelines |
| **update-implementation-plan** | Update existing implementation plans | Evolving requirements, new learnings | Incremental planning, requirement changes |

### Testing & Quality Skills

| Skill | Purpose | When to Use | Key Capabilities |
|-------|---------|-----------|-----------------|
| **polyglot-test-agent** | Generate comprehensive unit tests (multi-agent pipeline) | Writing tests, improving coverage, any language | C#, TS, JS, Python, Go, Rust, Java; ensures tests compile & pass |
| **pytest-coverage** | Achieve 100% test coverage for Python | Python project coverage, finding gaps | Coverage reports, line-by-line analysis, deficit identification |

### VS Code Extension Skills

| Skill | Purpose | When to Use | Key Capabilities |
|-------|---------|-----------|-----------------|
| **vscode-ext-commands** | Contribute commands in VS Code extensions | Adding extension features, commands | Naming conventions, visibility, localization, keyboard bindings |
| **vscode-ext-localization** | Proper localization for VS Code extensions | Multi-language extension support | L10n/i18n patterns, VS Code localization libraries |

---

## 🪝 Hooks

Hooks run at specific lifecycle events during Copilot sessions.

| Hook | Event | Purpose | Mechanism |
|------|-------|---------|-----------|
| **session-auto-commit** | `sessionEnd` (end of session) | Automatically commit changes when Copilot session completes | Bash script: `.github/hooks/session-auto-commit/auto-commit.sh` (30s timeout) |

---

## ⚙️ Workflows

Automated CI/CD workflows that run on push and pull requests.

| Workflow | File | Trigger | Purpose | Key Actions |
|----------|------|---------|---------|------------|
| **Run Tests with uv + Poetry** | `pytest.yml` | Push to any branch, PRs | Execute Python test suite | Free disk space, uv venv setup, Poetry install, pytest execution |
| **Run pre-commit on all branches** | `pre-commit.yml` | Push to any branch, PRs | Lint, format, security checks | Black formatting, Bandit, detect-secrets, debug statements |
| **Auto-Fix CI Failures** | `ci-failure-fix.yml` | pytest workflow completion (on failure) | Autonomously propose fixes for CI failures | Download logs, invoke Jules AI agent, generate proposed fixes |

---

## 📌 Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| **copilot-instructions.md** | Central repository guidelines, invariants, architecture, conventions | `.github/copilot-instructions.md` |
| **AGENTS.md** | Repository guidelines, invariants, structure, coding styles | Root directory |

---

## 🎯 Usage Matrix — When to Use What

### By Task Type

#### **Planning & Architecture**
- 🏗️ **New Feature Design**: Use `Planning Mode` → `SE: Architect` (validate design) → `Context Architect` (plan multi-file changes)
- 🔄 **Refactoring**: Use `refactor-plan` skill → `WG Code Alchemist` (apply patterns) → `polyglot-test-agent` (test coverage)
- 🏢 **Architecture Audit**: Use `SE: Architect` → `architecture-blueprint-generator` skill
- 🔒 **Agent Building**: Use `Agent Governance Reviewer` → `agent-governance` skill → `agentic-eval` skill

#### **Development & Implementation**
- 💻 **Coding**: Use `Blueprint Mode Codex` (complex tasks) or standards from instructions
- 🎯 **Python Code**: Follow `python.instructions.md`
- 🔷 **TypeScript Code**: Follow `typescript-5-es2022.instructions.md`
- 🛠️ **Refactoring**: Use `WG Code Alchemist` skill for clean code transformation
- 🧹 **Cleanup**: Use `Universal Janitor` skill for tech debt removal
- 🔧 **StoryCraftr-Next Maintenance**: Use `StoryCraftr Engineering Agent` for repository-specific bug fixes, architecture improvements, and dependency updates

#### **Testing**
- ✅ **Write Tests**: Use `polyglot-test-agent` skill (any language)
- 📊 **Coverage**: Use `pytest-coverage` skill (Python)
- 🔐 **Security Testing**: Use `gem-reviewer` agent

#### **Documentation**
- 📝 **README**: Use `create-readme` skill or `documentation-writer` agent
- 📖 **API Docs**: Use `documentation-writer` agent (Diátaxis framework)
- 📐 **Architecture Docs**: Use `architecture-blueprint-generator` skill
- 🎥 **Codebase Tour**: Use `VSCode Tour Expert` agent

#### **Performance & Quality**
- ⚡ **Performance**: Follow `performance-optimization.instructions.md`
- 🔍 **Code Review**: Use `gem-reviewer` agent + `Agent Governance Reviewer`
- 📈 **Scalability**: Use `SE: Architect` agent

#### **Security & Observability**
- 🔐 **Agent Security**: Use `Agent Governance Reviewer` + `agent-governance` skill
- 🐛 **Incident Debugging**: Use `Dynatrace Expert` agent (with Dynatrace MCP)
- 🔍 **Code Issues**: Use `elasticsearch-agent` (with Elastic MCP)

#### **Library & Framework Questions**
- 📚 **Library Help**: Use `Context7-Expert` agent (provides latest docs & examples)

#### **MCP Server Development**
- 🐍 **Python MCP**: Use `Python MCP Server Expert` agent
- 🔷 **TypeScript MCP**: Use `TypeScript MCP Server Expert` agent

#### **OpenAPI/API Generation**
- 🔌 **Generate from OpenAPI**: Use `OpenAPI to Application Generator` agent

---

## 🚀 Quick Reference: Problem → Solution

| Problem | Solution |
|---------|----------|
| "How do I structure this feature?" | `Planning Mode` agent |
| "Is my architecture scalable?" | `SE: Architect` agent |
| "I need to refactor this mess" | `refactor-plan` skill + `WG Code Alchemist` |
| "How do I test this?" | `polyglot-test-agent` skill |
| "Need comprehensive docs" | `documentation-writer` agent + `readme-blueprint-generator` skill |
| "Is this agent safe?" | `Agent Governance Reviewer` agent + `agent-governance` skill |
| "Performance is slow" | Follow `performance-optimization.instructions.md` + `Dynatrace Expert` |
| "Find library examples" | `Context7-Expert` agent |
| "Build an AI agent" | `agent-governance` skill + `agentic-eval` skill |
| "Generate tests" | `polyglot-test-agent` skill |
| "Build MCP server" | `Python MCP Server Expert` or `TypeScript MCP Server Expert` |
| "Clean up code" | `Universal Janitor` skill |
| "Learn VS Code extension patterns" | `vscode-ext-commands` skill + `vscode-ext-localization` skill |
| "Fix bug in StoryCraftr" | `StoryCraftr Engineering Agent` |
| "Improve StoryCraftr architecture" | `StoryCraftr Engineering Agent` + `SE: Architect` agent |
| "Update StoryCraftr dependencies" | `StoryCraftr Engineering Agent` |

---

## 🎓 Learning Path by Role

### 🔧 Backend Engineer
1. Start with `copilot-instructions.md` (core conventions)
2. Read `python.instructions.md` (Python standards)
3. Use `performance-optimization.instructions.md` when needed
4. Reference `agent-governance` skill if building agents
5. Use `pytest-coverage` skill for testing

### 🎨 Frontend Engineer
1. Start with `context-engineering.instructions.md`
2. Follow `typescript-5-es2022.instructions.md`
3. Use `vscode-ext-commands` & `vscode-ext-localization` skills if building extensions
4. Reference `architecture-blueprint-generator` for component design

### 🏗️ Architect
1. Master `SE: Architect` agent (use for all design reviews)
2. Use `architecture-blueprint-generator` skill
3. Reference `agent-governance` skill for distributed systems
4. Use planning agents: `Planning Mode`, `gem-planner`

### 🔐 Security Engineer
1. Study `agent-safety.instructions.md`
2. Use `gem-reviewer` agent for all code reviews
3. Master `agent-governance` skill
4. Reference `agentic-eval` skill for agent testing

### 📚 Technical Writer
1. Master `documentation-writer` agent
2. Use `create-readme`, `readme-blueprint-generator` skills
3. Reference `architecture-blueprint-generator` for architecture docs

### 🤖 AI/Agent Developer
1. Master `agent-governance` skill
2. Master `agentic-eval` skill
3. Use `agent-governance-reviewer` agent
4. Use appropriate language expert agents (Python/TypeScript MCP)

---

## 🔗 Integration Points

### Standard Workflows
- **Development + Testing**: Code (instructions) → `polyglot-test-agent` → `pytest-coverage`
- **Refactoring**: `refactor-plan` → `WG Code Alchemist` → Tests
- **Feature Design & Building**: `Planning Mode` → `SE: Architect` → Code (instructions) → Tests
- **Documentation**: `architecture-blueprint-generator` → `documentation-writer`

### Multi-Agent Workflows
- **Complex Projects**: `gem-orchestrator` (coordinates) → `gem-planner` (plans) → `gems` (implement) → `gem-reviewer` (validates)
- **Agent Building**: `Agent Governance Reviewer` → `agent-governance` skill → `agentic-eval` skill

### AI/Observability Integration
- **Performance Debugging**: `Dynatrace Expert` → Performance fix
- **Code Issues**: `elasticsearch-agent` → `WG Code Alchemist` → Fix

---

## 📊 Capability Matrix

| Capability | Agents | Skills | Instructions |
|-----------|--------|--------|--------------|
| **Planning** | Planning Mode, gem-planner, SE: Architect | refactor-plan, create-implementation-plan | copilot-instructions.md |
| **Code Generation** | Blueprint Mode Codex, OpenAPI Generator | N/A | python, typescript instructions |
| **Code Quality** | WG Code Alchemist, gem-reviewer | refactor, polyglot-test-agent | all instructions |
| **Testing** | polyglot-test-agent | pytest-coverage, polyglot-test-agent | python instruction |
| **Documentation** | documentation-writer, gem-documentation | create-readme, readme-blueprint-generator, architecture-blueprint-generator | update-docs-on-code-change |
| **Security** | Agent Governance Reviewer, gem-reviewer | agent-governance | agent-safety instruction |
| **Architecture** | SE: Architect, Context Architect | architecture-blueprint-generator | context-engineering |
| **Performance** | (None) | (None) | performance-optimization |
| **Observability** | Dynatrace Expert, elasticsearch-agent | (None) | (None) |
| **MCP Servers** | Python MCP Expert, TypeScript MCP Expert | (None) | (None) |
| **VS Code Extensions** | VSCode Tour Expert | vscode-ext-commands, vscode-ext-localization | (None) |

---

## 🎯 Best Practices for Using This Ecosystem

1. **Start with Planning**: Always use `Planning Mode` or `SE: Architect` before major work
2. **Follow Instructions**: Let instructions auto-apply; don't ignore linting/formatting guidance
3. **Use Skill Specialization**: Choose the right skill for specific domains (not general agents)
4. **Test Coverage First**: Use `polyglot-test-agent` & `pytest-coverage` early, not as an afterthought
5. **Document as You Go**: Use `update-docs-on-code-change` instruction; don't add docs retroactively
6. **Security First**: Use `Agent Governance Reviewer` & `gem-reviewer` before merging agent code
7. **Leverage Context7**: Ask `Context7-Expert` for library questions; it accesses latest docs
8. **Coordinate Complex Work**: Use `gem-orchestrator` for multi-phase projects
9. **Performance Matters**: Reference `performance-optimization.instructions.md` early in design
10. **Version Your Plans**: Save and update implementation plans as requirements evolve

---

**Last Updated**: March 5, 2026  
**Total Resources**: 20 Agents + 6 Instructions + 13 Skills + 1 Hook + 3 Workflows
