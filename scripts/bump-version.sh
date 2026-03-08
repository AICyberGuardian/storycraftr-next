#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <version>" >&2
    exit 1
fi

version="$1"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)?$ ]]; then
    echo "Invalid version '$version'. Expected format like 0.15.0-dev." >&2
    exit 1
fi

series="$(sed -E 's/^([0-9]+\.[0-9]+)\..*/\1/' <<<"$version")"

perl -0pi -e 's/version = "[^"]+"/version = "'"$version"'"/' pyproject.toml

node - "$version" <<'NODE'
const fs = require("fs");
const version = process.argv[2];
const path = "package.json";
const data = JSON.parse(fs.readFileSync(path, "utf8"));
data.version = version;
fs.writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
NODE

node - "$version" <<'NODE'
const fs = require("fs");
const version = process.argv[2];
const path = "package-lock.json";
const data = JSON.parse(fs.readFileSync(path, "utf8"));
data.version = version;
if (data.packages && data.packages[""]) {
  data.packages[""].version = version;
}
fs.writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
NODE

if grep -q "Current development target set to" CHANGELOG.md; then
    perl -pi -e 's#Current development target set to `v[0-9]+\.[0-9]+(?:\.x)?` \(`[^`]+`\)\.#Current development target set to `v'"$series"'` (`'"$version"'`).#' CHANGELOG.md
else
    echo "CHANGELOG.md is missing the development target line under [Unreleased]." >&2
    exit 1
fi

echo "Updated version metadata to $version."
