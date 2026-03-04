#!/usr/bin/env bash
set -euo pipefail

staged_files="$(git diff --cached --name-only)"

pyproject_version_changed=false
package_version_changed=false

if git diff --cached -- pyproject.toml | grep -Eq '^[+-]version = "[^"]+"'; then
    pyproject_version_changed=true
fi

if git diff --cached -- package.json | grep -Eq '^[+-][[:space:]]*"version":[[:space:]]*"[^"]+"'; then
    package_version_changed=true
fi

if [[ "$pyproject_version_changed" == true || "$package_version_changed" == true ]]; then
    required_files=(
        "pyproject.toml"
        "package.json"
        "package-lock.json"
        "CHANGELOG.md"
    )
    missing=()
    for file in "${required_files[@]}"; do
        if ! grep -qx "$file" <<<"$staged_files"; then
            missing+=("$file")
        fi
    done

    if (( ${#missing[@]} > 0 )); then
        echo "VER_BUMP invariant violation." >&2
        echo "When version changes in pyproject.toml/package.json, stage all of:" >&2
        printf '  - %s\n' "${required_files[@]}" >&2
        echo "Missing staged files: ${missing[*]}" >&2
        exit 1
    fi
fi
