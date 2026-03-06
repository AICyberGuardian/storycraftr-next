# Python 3.13 Full-Stack Upgrade Matrix

Date: 2026-03-06
Repository: `storycraftr-next`
Baseline branch: `migration/python-3.13`
Runtime policy: Python `>=3.13,<3.14`

## Goal
Move the full stack toward latest stable versions while preserving StoryCraftr CLI behavior, RAG correctness, sub-agent reliability, and VS Code extension compatibility.

## Evidence Sources
- Local manifest/lock audit from `pyproject.toml`, `poetry.lock`, `package.json`, `package-lock.json`.
- Registry checks against PyPI and npm latest versions.
- Context7 + vendor migration docs for LangChain 1.x migration patterns.

## Current vs Latest (Key Packages)

### Python runtime stack
| Package | Locked | Latest | Gap Type | Risk |
|---|---:|---:|---|---|
| langchain | 0.3.27 | 1.2.10 | Major | High |
| langchain-core | 0.3.79 | 1.2.17 | Major | High |
| langchain-community | 0.3.27 | 0.4.1 | Minor in 0.x (can still break) | Medium-High |
| langchain-openai | 0.3.35 | 1.1.10 | Major | High |
| langchain-huggingface | 0.3.1 | 1.2.1 | Major | High |
| langchain-chroma | 0.2.6 | 1.1.0 | Major | High |
| chromadb | 1.3.2 | 1.5.2 | Major API/behavior shifts | High |
| sentence-transformers | 5.1.2 | 5.2.3 | Minor | Medium |
| torch | 2.9.0 | 2.10.0 | Minor | Medium |
| rich | 14.0.0 | 14.3.3 | Minor | Low |
| requests | 2.32.3 | 2.32.5 | Patch | Low |
| pyyaml | 6.0.2 | 6.0.3 | Patch | Low |
| python-dotenv | 1.1.0 | 1.2.2 | Minor | Low |

### Python tooling stack
| Package | Locked | Latest | Gap Type | Risk |
|---|---:|---:|---|---|
| pytest | 8.3.5 | 9.0.2 | Major | Medium |
| pre-commit | 4.2.0 | 4.5.1 | Minor | Low |
| black | 25.1.0 | 26.1.0 | Major | Medium |
| sphinx | 8.1.3 | 9.1.0 | Major | Medium |
| sphinx-click | 6.0.0 | 6.2.0 | Minor | Low |

### Node/extension stack
| Package | Locked | Latest | Gap Type | Risk |
|---|---:|---:|---|---|
| typescript | 5.9.3 | 5.9.3 | None | Low |
| @types/vscode | 1.109.0 | 1.109.0 | None | Low |
| @types/node | 20.19.35 | 25.3.5 | Major typing jump | Medium |
| vsce | 2.15.0 | 2.15.0 | None (but legacy package) | Low-Medium |

## Migration Constraints (What Can Break)

### LangChain 0.3.x -> 1.x
- Agent creation moved toward `langchain.agents.create_agent` patterns.
- Import paths and agent/middleware patterns changed.
- High probability of code changes in:
  - `storycraftr/agent/agents.py`
  - `storycraftr/graph/assistant_graph.py`
  - tests under `tests/unit/test_assistant_graph.py` and `tests/unit/test_agents_create_message.py`.

### Chroma + LangChain Chroma
- Upgrade should be coordinated (`chromadb` and `langchain-chroma` together).
- Collection initialization, embedding function behavior, and retrieval path assumptions may need updates in:
  - `storycraftr/vectorstores/chroma.py`
  - `storycraftr/agent/retrieval.py`.

### Embeddings
- `sentence-transformers` and `torch` are heavy and platform-sensitive.
- Keep dedicated CI lane (`embeddings-smoke`) and validate CPU first.

## Safe Upgrade Matrix (Execution Order)

### Wave 0: Baseline and guardrails (required first)
| Action | Target | Why | Gate |
|---|---|---|---|
| Freeze current lockfiles | Keep current | Rollback anchor | `git tag` + CI green |
| Keep Python policy pinned | `>=3.13,<3.14` | Avoid mixed-runtime drift | `poetry check --lock` |
| Keep CI smoke lanes | pytest + embeddings + extension compile | Detect regressions quickly | CI all green |

### Wave 1: Low-risk updates (should upgrade now)
| Group | Targets | Strategy | Risk |
|---|---|---|---|
| Runtime patches/minors | `requests`, `pyyaml`, `python-dotenv`, `rich` | Bump together | Low |
| Dev minors | `pre-commit`, `sphinx-click` | Bump together | Low |
| Node types (conservative) | keep `@types/node` 20.x OR move to 22.x first | Avoid abrupt 25.x typing breakage | Low-Medium |

Validation gates:
- `poetry run pytest -q`
- `poetry run storycraftr --help`
- `poetry run storycraftr chat --help`
- `poetry run papercraftr --help`
- `npm run compile`

### Wave 2: Toolchain majors (moderate)
| Group | Targets | Strategy | Risk |
|---|---|---|---|
| Test/lint/docs | `pytest 9`, `black 26`, `sphinx 9` | Separate PR from runtime AI stack | Medium |
| Node typings | `@types/node` latest compatible with TS config | Upgrade after compile/tests clean | Medium |

Validation gates:
- full `pytest`
- `pre-commit run --all-files`
- docs build smoke if applicable

### Wave 3: AI stack modernization (high risk, separate PRs)
| PR | Targets | Code Areas Expected to Change | Risk |
|---|---|---|---|
| PR-A | `langchain*` family to 1.x-compatible set | `storycraftr/agent/agents.py`, `storycraftr/graph/assistant_graph.py` | High |
| PR-B | `chromadb` + `langchain-chroma` latest | `storycraftr/vectorstores/chroma.py`, retrieval flow/tests | High |
| PR-C | `sentence-transformers` + `torch` latest | embeddings init and retrieval-quality tests | Medium-High |

Validation gates:
- full tests
- RAG integration smoke (ingest + retrieve)
- sub-agent job lifecycle tests
- VS Code event stream smoke

## Recommended Version Pin Strategy

### Stable operations profile (recommended)
- Pin high-risk AI stack exactly after validation:
  - `langchain==1.2.10`
  - `langchain-core==1.2.17`
  - `langchain-community==0.4.1`
  - `langchain-openai==1.1.10`
  - `langchain-huggingface==1.2.1`
  - `langchain-chroma==1.1.0`
  - `chromadb==1.5.2`
- Keep heavy embeddings pinned exactly:
  - `sentence-transformers==5.2.3`
  - `torch==2.10.0`
- Keep low-risk libs on compatible minor ranges:
  - `requests~=2.32`
  - `pyyaml~=6.0`
  - `rich~=14.3`

### Why this split
- Exact pins for fast-moving AI ecosystem improve reproducibility and reduce surprise breakages.
- Compatible ranges on low-risk utilities reduce maintenance burden.

## CI/Automation Policy for Upgrades
- Use `make sync-deps` after dependency spec edits.
- Keep lockfile immutability checks in CI (`git diff --exit-code poetry.lock package-lock.json`).
- Keep embeddings CI lane mandatory for any embeddings/chroma/langchain changes.
- Keep extension compile step mandatory for Python backend changes that affect event contracts.

## Performance and Stability Guidance
- Do not combine LangChain 1.x + Chroma + embeddings in one PR.
- Prefer 3 PRs with isolated blast radius and rollback points.
- Benchmark startup and first-response latency before/after each wave.
- Add regression tests before each high-risk wave, not after.

## Rollback Plan
For each wave:
1. Revert dependency spec commit.
2. Re-run `make sync-deps`.
3. Restore prior lockfiles.
4. Run CI smoke gates.

## Suggested Next Execution Commands
```bash
# wave-by-wave working pattern
make sync-deps
poetry run pytest -q
poetry run storycraftr --help
poetry run storycraftr chat --help
poetry run papercraftr --help
npm run compile
```

## Decision Summary
- You are not on latest for a significant portion of Python dependencies.
- You can safely reach latest, but only with staged execution.
- The highest-risk path is LangChain + Chroma modernization; treat it as explicit refactor work, not a lockfile refresh.
