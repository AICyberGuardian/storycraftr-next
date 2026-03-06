## Draft Update - 2026-03-03 (Security, Reliability, and Path Hardening)

Current development target: `v0.15.x` (`0.15.2-dev`).

### Highlights

- Hardened `build_chat_model` with provider-specific validation and explicit failure classes.
- Enforced explicit OpenRouter model identifiers in `provider/model` format via project config (`llm_model`).
- Migrated credential loading to secure-first order: environment variables -> OS keyring -> legacy plaintext files.
- Added `store_local_credential` helper for OS keyring persistence.
- Hardened sub-agent background job execution with explicit lifecycle locking, crash visibility, and failure persistence.
- Fixed `SubAgentJobManager.shutdown(wait=False)` cancellation race conditions and now persist cancellation failures explicitly.
- Refactored `create_message` to separate prompt assembly/metadata writing from LangChain graph invocation and thread bookkeeping.
- Removed hardcoded runtime storage paths by introducing config-rooted path resolution for sub-agent files/logs, sessions, VS Code event stream, and vector store persistence/cleanup.
- Expanded unit coverage for factory validation and credential loading precedence.
- Added mock-based graph tests for retrieval + prompt assembly without live API calls.
- Added deterministic tests for sub-agent shutdown cancellation, custom runtime path invariants, and CLI init smoke execution (`tests/unit/test_subagent_jobs.py`, `tests/unit/test_core_paths.py`, `tests/integration/test_cli_smoke.py`).
- Updated user and contributor docs (`README.md`, `docs/getting_started.md`, `docs/chat.md`, `AGENTS.md`, `SECURITY.md`, `docs/langchain-refactor-plan.md`, `CHANGELOG.md`).

# PaperCraftr 0.10.1-beta4

## 🎉 Major Release: Complete Command Implementation

We're excited to announce the release of PaperCraftr 0.10.1-beta4, which marks a significant milestone in the development of our academic paper writing tool. This release implements all the core commands that were previously missing, providing a complete workflow for academic paper creation and management.

## ✨ New Features

### 📝 Abstract Generation
- Added `abstract generate` command to create abstracts for different journals
- Implemented `abstract keywords` command to generate relevant keywords
- Added support for multiple languages in abstract generation

### 📚 Reference Management
- Implemented `references add` command to add new references
- Added `references format` command to format references in BibTeX
- Created `references check` command to verify citation consistency

### 📋 Outline and Organization
- Added `outline outline-sections` command to generate paper structure
- Implemented `organize-lit lit-summary` command to organize literature review
- Created `organize-lit lit-map` command to visualize research connections

### 📄 Section Generation
- Implemented `generate section` command to create paper sections
- Added support for generating specific sections (introduction, methodology, etc.)
- Integrated with AI to produce high-quality academic content

### 📊 Publishing
- Enhanced `publish pdf` command with improved LaTeX template
- Added support for IEEE format papers
- Implemented translation options for multilingual papers

## 🔧 Improvements

- Streamlined project structure for better organization
- Enhanced LaTeX template with IEEE format support
- Improved markdown consolidation process
- Added metadata support for abstracts and keywords
- Optimized file structure for academic paper writing

## 🐛 Bug Fixes

- Fixed issues with reference formatting
- Resolved problems with LaTeX compilation
- Addressed inconsistencies in section generation
- Fixed translation issues in multilingual papers

## 📚 Documentation

- Updated documentation for all implemented commands
- Added examples for each command
- Created comprehensive guides for paper writing workflow
- Improved error messages and user feedback

## 🔄 Workflow

PaperCraftr now supports a complete academic paper writing workflow:

1. Initialize a new paper project
2. Generate an outline and organize literature
3. Create abstracts and keywords
4. Generate paper sections
5. Add and format references
6. Publish the final paper in PDF format

## 🚀 Getting Started

To get started with PaperCraftr 0.10.1-beta4:

```bash
# Initialize a new paper project
papercraftr init my-paper

# Generate an outline
papercraftr outline outline-sections

# Create an abstract
papercraftr abstract generate

# Generate paper sections
papercraftr generate section introduction

# Add references
papercraftr references add "Author, Title, Journal, Year"

# Publish your paper
papercraftr publish pdf
```

## 🙏 Acknowledgments

Thank you to all contributors and users who provided feedback during the development of this release. Your input has been invaluable in creating a comprehensive academic paper writing tool.

## 🔜 Next Steps

We're already working on the next release, which will include:

- Enhanced collaboration features
- More journal templates
- Advanced citation analysis
- Integration with reference management systems

Stay tuned for more updates! 
