SHELL := /bin/bash

.PHONY: sync-deps check-locks bump-version

sync-deps:
	poetry lock
	npm install --package-lock-only --ignore-scripts
	git add poetry.lock package-lock.json

check-locks:
	poetry check --lock
	npm ci --dry-run --ignore-scripts --loglevel=error

bump-version:
	@if [[ -z "$(VERSION)" ]]; then \
		echo "VERSION is required, e.g. make bump-version VERSION=0.15.1-dev"; \
		exit 1; \
	fi
	./scripts/bump-version.sh "$(VERSION)"
	$(MAKE) sync-deps
	git add pyproject.toml package.json package-lock.json CHANGELOG.md
