#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -eq 0 ]]; then
  echo "Usage: $0 -m \"<commit message>\""
  exit 1
fi

# Remove Windows metadata artifacts before staging.
find . -name "*:Zone.Identifier" -type f -delete

echo "[dev_commit] Formatting Python with Black..."
poetry run black .

echo "[dev_commit] Running pre-commit hooks..."
poetry run pre-commit run --all-files

echo "[dev_commit] Staging all changes..."
git add -A

echo "[dev_commit] Creating commit..."
git commit "$@"
