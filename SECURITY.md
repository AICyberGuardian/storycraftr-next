# StoryCraftr Security

## Credential Handling

StoryCraftr resolves provider credentials in secure-first order:

1. Existing environment variables (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`)
2. OS keyring entries under service `storycraftr` (override with `STORYCRAFTR_KEYRING_SERVICE`)
3. Legacy plaintext files in `~/.storycraftr` or `~/.papercraftr` (compatibility fallback only)

Prefer OS keyring storage over plaintext files:

```bash
python -c "from storycraftr.llm.credentials import store_local_credential; store_local_credential('OPENAI_API_KEY', 'sk-...')"
python -c "from storycraftr.llm.credentials import store_local_credential; store_local_credential('OPENROUTER_API_KEY', 'or-...')"
```

## LLM Configuration Safety

- OpenRouter requires an explicit `llm_model` in `provider/model` format (for example, `meta-llama/llama-3.3-70b-instruct`).
- Provider endpoints are validated as full `http(s)` URLs before model startup.
- Invalid model/provider combinations fail fast with provider-specific errors in `storycraftr.llm.factory`.

## Secret Hygiene

- Never commit API keys, `.env` files, or credential text files.
- Run `poetry run detect-secrets scan` after config changes.
- Run `poetry run pre-commit run --all-files` before opening a pull request.

## Reporting Vulnerabilities

Report vulnerabilities through the project issue tracker:

- https://github.com/raestrada/storycraftr/issues

When reporting, include:

- affected StoryCraftr version
- reproduction steps
- impact assessment
- any temporary mitigation you identified
