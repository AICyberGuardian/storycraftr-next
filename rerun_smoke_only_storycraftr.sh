#!/usr/bin/env bash
set -euo pipefail

# StoryCraftr smoke runner
#
# Purpose:
# - run a fully logged smoke outside the repo
# - keep all generated logs/artifacts in a single timestamped folder
# - generate AI-friendly snapshot files for later diagnosis
# - surface structured reliability signals (token budget, retry, breaker/quarantine, truncation)
#
# Default output root:
#   /home/orion22/Logs/storycraftr_smokes/
#
# Optional overrides:
#   REPO_DIR=...
#   LOGS_ROOT=...
#   RUN_LABEL=...
#   MAIN_MODEL=...
#   CHAPTERS=...
#   EMBED_DEVICE=...
#   MERGED_LOG_NAME=...
#   MAX_RUN_ATTEMPTS=...
#   RETRY_SLEEP_SECONDS=...
#
# Example:
#   RUN_LABEL=v101_trinity CHAPTERS=3 ./rerun_smoke_only_storycraftr.sh

REPO_DIR="${REPO_DIR:-$HOME/storycraftr-next}"
LOGS_ROOT="${LOGS_ROOT:-$HOME/Logs/storycraftr_smokes}"
RUN_LABEL="${RUN_LABEL:-smoke}"
MAIN_MODEL="${MAIN_MODEL:-openrouter/free}"
CHAPTERS="${CHAPTERS:-3}"
EMBED_DEVICE="${EMBED_DEVICE:-cuda}"
MERGED_LOG_NAME="${MERGED_LOG_NAME:-merged_diagnostics.log}"
MAX_RUN_ATTEMPTS="${MAX_RUN_ATTEMPTS:-2}"
RETRY_SLEEP_SECONDS="${RETRY_SLEEP_SECONDS:-10}"

EMBED_DEVICE_NORMALIZED="$(printf '%s' "$EMBED_DEVICE" | tr '[:upper:]' '[:lower:]')"

: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY must be set in the environment}"
# Example export command for local setup:
# echo '  export OPENROUTER_API_KEY="your_actual_key_here"' # pragma: allowlist secret

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "ERROR: REPO_DIR does not look like a git repo:"
  echo "  $REPO_DIR"
  exit 1
fi

if [[ ! -f "$REPO_DIR/.venv/bin/activate" ]]; then
  echo "ERROR: No .venv found at:"
  echo "  $REPO_DIR/.venv"
  exit 1
fi

mkdir -p "$LOGS_ROOT"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SHORT_SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
RUN_DIR="$LOGS_ROOT/${TIMESTAMP}_${RUN_LABEL}_${SHORT_SHA}"
BOOK_DIR="$RUN_DIR/book"
LOG_DIR="$RUN_DIR/logs"
MERGED_LOG="$RUN_DIR/$MERGED_LOG_NAME"

mkdir -p "$BOOK_DIR" "$LOG_DIR"

append_merged_file() {
  local path="$1"
  local title="${2:-$1}"
  {
    echo
    echo "================================================================================"
    echo "TITLE: $title"
    echo "PATH: $path"
    echo "================================================================================"
    if [[ -f "$path" ]]; then
      cat "$path"
    else
      echo "[MISSING] $path"
    fi
    echo
  } >> "$MERGED_LOG"
}

cd "$REPO_DIR"
source .venv/bin/activate

SC_CLI=(storycraftr)
if ! command -v storycraftr >/dev/null 2>&1; then
  if command -v poetry >/dev/null 2>&1; then
    SC_CLI=(poetry run storycraftr)
  else
    echo "ERROR: storycraftr CLI not found and poetry is unavailable."
    exit 1
  fi
fi

echo "==> StoryCraftr command: ${SC_CLI[*]}"

echo "==> Repo: $REPO_DIR"
echo "==> HEAD: $(git log --oneline -n 1)"
echo "==> Python: $(python --version 2>&1)"
echo "==> Run dir: $RUN_DIR"
echo "==> Book dir: $BOOK_DIR"
echo "==> Log dir: $LOG_DIR"

git rev-parse HEAD > "$RUN_DIR/git_revision.txt"
git describe --tags --always > "$RUN_DIR/git_describe.txt" 2>/dev/null || true
git status --short > "$RUN_DIR/git_status.txt" || true

cp "$REPO_DIR/storycraftr/config/rankings.json" \
  "$RUN_DIR/rankings.snapshot.json" 2>/dev/null || true

cp "$REPO_DIR/storycraftr/config/validator_report.schema.json" \
  "$RUN_DIR/validator_report.schema.snapshot.json" 2>/dev/null || true

if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "WARNING: HF_TOKEN is not set; Hugging Face downloads may be slower or rate-limited."
fi

cat > "$BOOK_DIR/storycraftr.json" <<JSON
{
  "book_name": "Storm Couriers",
  "llm_provider": "openrouter",
  "llm_model": "$MAIN_MODEL",
  "temperature": 0.7,
  "request_timeout": 600,
  "embed_model": "BAAI/bge-small-en-v1.5",
  "embed_device": "$EMBED_DEVICE",
  "enable_semantic_review": true
}
JSON

cat > "$BOOK_DIR/seed.md" <<'MD'
# Seed

A coastal city is sealed at dusk while a hidden rebellion forms inside the walls.
Primary POV character: Lyra Voss, a courier embedded in the dockworkers' guild.
Every scene should keep Lyra present on-page and acting on the main decision beat.
MD

echo "==> Smoke config"
cat "$BOOK_DIR/storycraftr.json" | tee "$LOG_DIR/storycraftr.json.snapshot.log"

echo "==> Runtime environment snapshot"
{
  echo "date_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname)"
  echo "pwd=$(pwd)"
  echo "storycraftr_command=${SC_CLI[*]}"
  echo "which_storycraftr=$(command -v storycraftr || true)"
  echo "storycraftr_version=$(${SC_CLI[@]} --version 2>/dev/null || true)"
  echo "python_executable=$(command -v python || true)"
  echo "python_version=$(python --version 2>&1 || true)"
  echo "poetry_version=$(poetry --version 2>&1 || true)"
  echo "main_model=$MAIN_MODEL"
  echo "embed_device=$EMBED_DEVICE"
  echo "chapters=$CHAPTERS"
} | tee "$LOG_DIR/runtime_env.log"

if [[ "$EMBED_DEVICE_NORMALIZED" == "api" ]]; then
  echo "==> Skipping local CUDA and sentence-transformers checks (embed_device=api)"
else
  if [[ "$EMBED_DEVICE_NORMALIZED" == "cuda" ]]; then
    echo "==> Quick CUDA verification"
    python - <<'PY' | tee "$LOG_DIR/cuda_check.log"
import torch
print("torch_version =", torch.__version__)
print("cuda_available =", torch.cuda.is_available())
print("cuda_version =", torch.version.cuda)
print("device_count =", torch.cuda.device_count())
if torch.cuda.is_available():
    print("device_name =", torch.cuda.get_device_name(0))
PY
  else
    echo "==> CUDA check skipped (embed_device=$EMBED_DEVICE)" | tee "$LOG_DIR/cuda_check.log"
  fi

  echo "==> Quick sentence-transformers verification"
  python - <<PY | tee "$LOG_DIR/embedding_check.log"
from sentence_transformers import SentenceTransformer
device = "$EMBED_DEVICE"
model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)
print("sentence_transformer_device =", model.device)
vec = model.encode(["StoryCraftr smoke verification"])
print("embedding_ok =", len(vec), len(vec[0]))
PY
fi

echo "==> Running StoryCraftr smoke"
BOOK_EXIT=1
attempt=1
while [[ "$attempt" -le "$MAX_RUN_ATTEMPTS" ]]; do
  attempt_log="$LOG_DIR/run.attempt-${attempt}.log"
  echo "==> StoryCraftr run attempt $attempt/$MAX_RUN_ATTEMPTS"
  set +e
  "${SC_CLI[@]}" book \
    --book-path "$BOOK_DIR" \
    --seed "$BOOK_DIR/seed.md" \
    --chapters "$CHAPTERS" \
    --yes 2>&1 | tee "$attempt_log"
  BOOK_EXIT=${PIPESTATUS[0]}
  set -e

  cp "$attempt_log" "$LOG_DIR/run.log"
  if [[ "$BOOK_EXIT" -eq 0 ]]; then
    echo "==> StoryCraftr run succeeded on attempt $attempt"
    break
  fi

  if [[ "$attempt" -lt "$MAX_RUN_ATTEMPTS" ]]; then
    echo "==> Attempt $attempt failed with exit code $BOOK_EXIT; retrying in $RETRY_SLEEP_SECONDS seconds"
    sleep "$RETRY_SLEEP_SECONDS"
  fi
  attempt=$((attempt + 1))
done

echo "$BOOK_EXIT" > "$RUN_DIR/exit_code.txt"

echo
echo "==> Smoke exit code: $BOOK_EXIT"

echo "==> Artifact inventory"
find "$RUN_DIR" -maxdepth 7 -type f | sort | tee "$LOG_DIR/artifact_inventory.log" || true

echo
echo "==> Chapter word counts"
if compgen -G "$BOOK_DIR/chapters/chapter-*.md" > /dev/null; then
  wc -w "$BOOK_DIR"/chapters/chapter-*.md | tee "$LOG_DIR/chapter_word_counts.log"
else
  echo "No chapter markdown files found." | tee "$LOG_DIR/chapter_word_counts.log"
fi

echo
echo "==> Required artifact checks"
for p in \
  "$LOG_DIR/run.log" \
  "$BOOK_DIR/outline/canon.yml" \
  "$BOOK_DIR/outline/narrative_state.json" \
  "$BOOK_DIR/outline/narrative_audit.jsonl" \
  "$BOOK_DIR/outline/book_audit.json" \
  "$BOOK_DIR/outline/book_audit.md"
do
  if [[ -e "$p" ]]; then
    echo "[OK] $p"
  else
    echo "[MISSING] $p"
  fi
done | tee "$LOG_DIR/artifact_checks.log"

if [[ -d "$BOOK_DIR/outline/chapter_packets" ]]; then
  echo "[OK] $BOOK_DIR/outline/chapter_packets" | tee -a "$LOG_DIR/artifact_checks.log"
else
  echo "[MISSING] $BOOK_DIR/outline/chapter_packets" | tee -a "$LOG_DIR/artifact_checks.log"
fi

echo
echo "==> Book audit summary"
python - <<PY | tee "$LOG_DIR/book_audit_summary.log"
from pathlib import Path
import json

audit = Path(r"$BOOK_DIR/outline/book_audit.json")
if not audit.exists():
    print("book_audit.json missing")
    raise SystemExit(0)

data = json.loads(audit.read_text(encoding="utf-8"))
print("status =", data.get("status"))
print("chapters_generated =", data.get("chapters_generated"))
print("chapters_target =", data.get("chapters_target"))
print("coherence_reviews_run =", data.get("coherence_reviews_run"))
print("patch_operations_applied =", data.get("patch_operations_applied"))
print("failed_guard =", data.get("failed_guard"))
print("error =", data.get("error"))

chapters = data.get("chapters", [])
print("chapter_audit_rows =", len(chapters) if isinstance(chapters, list) else 0)
PY

echo
echo "==> Canon plot_threads check"
if [[ -f "$BOOK_DIR/outline/canon.yml" ]]; then
  grep -n "plot_threads" "$BOOK_DIR/outline/canon.yml" | tee "$LOG_DIR/canon_plot_threads_check.log" || \
    echo "plot_threads marker not found in canon.yml" | tee "$LOG_DIR/canon_plot_threads_check.log"
else
  echo "canon.yml missing" | tee "$LOG_DIR/canon_plot_threads_check.log"
fi

echo
echo "==> Validator / packet inventory"
find "$BOOK_DIR/outline" -maxdepth 6 \( -name "*validator*" -o -name "*coherence*" -o -name "*semantic*" -o -path "*/failures/*" \) -type f | sort | tee "$LOG_DIR/validator_packet_inventory.log" || true

echo
echo "==> Structured packet forensics inventory"
if [[ -d "$BOOK_DIR/outline/chapter_packets" ]]; then
  find "$BOOK_DIR/outline/chapter_packets" -maxdepth 8 -type f \( \
    -name "diagnostics.json" -o \
    -name "validator_report.json" -o \
    -name "scene_*_validator_report.json" -o \
    -name "canon_delta.yml" -o \
    -name "state_patch.json" -o \
    -name "metadata.json" -o \
    -name "planner_output.txt" -o \
    -name "drafter_output.txt" -o \
    -name "editor_output.txt" -o \
    -name "reviewer_output.txt" -o \
    -name "state_extractor_output.txt" \
  \) | sort | tee "$LOG_DIR/forensics_inventory.log" || true
else
  echo "chapter_packets directory missing" | tee "$LOG_DIR/forensics_inventory.log"
fi

echo
echo "==> Chapter packet inventory"
if [[ -d "$BOOK_DIR/outline/chapter_packets" ]]; then
  find "$BOOK_DIR/outline/chapter_packets" -maxdepth 6 -type f | sort | tee "$LOG_DIR/chapter_packet_inventory.txt" || true
else
  echo "chapter_packets directory missing" | tee "$LOG_DIR/chapter_packet_inventory.txt"
fi

echo
echo "==> Failure inventory"
if [[ -d "$BOOK_DIR/outline/chapter_packets" ]]; then
  find "$BOOK_DIR/outline/chapter_packets" -path "*/failures/*" -type f | sort | tee "$LOG_DIR/failure_inventory.txt" || true
else
  echo "chapter_packets directory missing" | tee "$LOG_DIR/failure_inventory.txt"
fi

echo
echo "==> Narrative audit inventory"
if [[ -f "$BOOK_DIR/outline/narrative_audit.jsonl" ]]; then
  wc -l "$BOOK_DIR/outline/narrative_audit.jsonl" | tee "$LOG_DIR/narrative_audit_line_count.log"
  tail -n 120 "$BOOK_DIR/outline/narrative_audit.jsonl" | tee "$LOG_DIR/narrative_audit_tail.log"
else
  echo "narrative_audit.jsonl missing" | tee "$LOG_DIR/narrative_audit_line_count.log"
fi

echo
echo "==> Run guard signal grep"
grep -nEi "guard|semantic|coherence|validator|canon_fact_conflict|validator_independence_failed|scene_structure_missing|audit_commit_failure|retry|escalat|token_budget_exceeded|sentence_boundary_truncation|breaker_open|quarantin|openrouter_retry|semantic_transport" "$LOG_DIR/run.log" | tee "$LOG_DIR/run_guard_signals.log" || true

echo
echo "==> Tail of run.log"
tail -n 120 "$LOG_DIR/run.log" | tee "$LOG_DIR/run_tail.log" || true

###############################################################################
# Build AI-friendly snapshot files
###############################################################################

echo
echo "==> Building snapshot_manifest.md"

{
  echo "# StoryCraftr Smoke Snapshot Manifest"
  echo
  echo "## Run Metadata"
  echo "- repo: $REPO_DIR"
  echo "- git_revision: $(cat "$RUN_DIR/git_revision.txt" 2>/dev/null || echo unknown)"
  echo "- git_describe: $(cat "$RUN_DIR/git_describe.txt" 2>/dev/null || echo unknown)"
  echo "- run_dir: $RUN_DIR"
  echo "- exit_code: $BOOK_EXIT"
  echo "- timestamp: $TIMESTAMP"
  echo "- run_label: $RUN_LABEL"
  echo
  echo "## StoryCraftr Config"
  echo '```json'
  cat "$BOOK_DIR/storycraftr.json" 2>/dev/null || true
  echo '```'
  echo
  echo "## Seed"
  echo '```md'
  cat "$BOOK_DIR/seed.md" 2>/dev/null || true
  echo '```'
  echo
  echo "## Book Audit JSON"
  if [[ -f "$BOOK_DIR/outline/book_audit.json" ]]; then
    echo '```json'
    cat "$BOOK_DIR/outline/book_audit.json"
    echo '```'
  else
    echo "book_audit.json missing"
  fi
  echo
  echo "## Book Audit Markdown"
  if [[ -f "$BOOK_DIR/outline/book_audit.md" ]]; then
    echo '```md'
    cat "$BOOK_DIR/outline/book_audit.md"
    echo '```'
  else
    echo "book_audit.md missing"
  fi
  echo
  echo "## Canon"
  if [[ -f "$BOOK_DIR/outline/canon.yml" ]]; then
    echo '```yaml'
    cat "$BOOK_DIR/outline/canon.yml"
    echo '```'
  else
    echo "canon.yml missing"
  fi
  echo
  echo "## Narrative State"
  if [[ -f "$BOOK_DIR/outline/narrative_state.json" ]]; then
    echo '```json'
    cat "$BOOK_DIR/outline/narrative_state.json"
    echo '```'
  else
    echo "narrative_state.json missing"
  fi
  echo
  echo "## Narrative Audit Tail"
  if [[ -f "$LOG_DIR/narrative_audit_tail.log" ]]; then
    echo '```json'
    cat "$LOG_DIR/narrative_audit_tail.log"
    echo '```'
  else
    echo "narrative_audit_tail.log missing"
  fi
  echo
  echo "## Chapter Word Counts"
  echo '```text'
  cat "$LOG_DIR/chapter_word_counts.log" 2>/dev/null || true
  echo '```'
  echo
  echo "## Artifact Checks"
  echo '```text'
  cat "$LOG_DIR/artifact_checks.log" 2>/dev/null || true
  echo '```'
  echo
  echo "## Chapter Packet Inventory"
  echo '```text'
  cat "$LOG_DIR/chapter_packet_inventory.txt" 2>/dev/null || true
  echo '```'
  echo
  echo "## Failure Inventory"
  echo '```text'
  cat "$LOG_DIR/failure_inventory.txt" 2>/dev/null || true
  echo '```'
  echo
  echo "## Forensics Inventory"
  echo '```text'
  cat "$LOG_DIR/forensics_inventory.log" 2>/dev/null || true
  echo '```'
  echo
  echo "## Run Guard Signals"
  echo '```text'
  cat "$LOG_DIR/run_guard_signals.log" 2>/dev/null || true
  echo '```'
  echo
  echo "## Run Log Tail"
  echo '```text'
  cat "$LOG_DIR/run_tail.log" 2>/dev/null || true
  echo '```'
} > "$RUN_DIR/snapshot_manifest.md"

echo "==> Building snapshot_packets.md"
BOOK_DIR="$BOOK_DIR" python - <<'PY' > "$RUN_DIR/snapshot_packets.md"
import os
from pathlib import Path

book_dir = Path(os.environ["BOOK_DIR"])
packets_root = book_dir / "outline" / "chapter_packets"

print("# StoryCraftr Packet Snapshot")
print()

if not packets_root.exists():
    print("chapter_packets directory missing")
    raise SystemExit(0)


def _emit_block(title: str, path: Path, lang: str, max_chars: int = 120000) -> None:
    if not path.exists():
        return
    print(f"## {title}")
    print(f"- path: {path}")
    print(f"- size_bytes: {path.stat().st_size}")
    print(f"```{lang}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        print(text[:max_chars].rstrip())
        print("\n...[truncated]...")
    else:
        print(text.rstrip())
    print("```")
    print()

for chapter_dir in sorted([p for p in packets_root.iterdir() if p.is_dir()]):
    chapter_name = chapter_dir.name
    print(f"# {chapter_name}")
    print()

    _emit_block(f"{chapter_name} Diagnostics", chapter_dir / "diagnostics.json", "json")
    _emit_block(f"{chapter_name} Validator Report", chapter_dir / "validator_report.json", "json")
    _emit_block(f"{chapter_name} Scene Plan", chapter_dir / "scene_plan.json", "json")
    _emit_block(f"{chapter_name} Canon Delta", chapter_dir / "canon_delta.yml", "yaml")
    _emit_block(f"{chapter_name} State Patch", chapter_dir / "state_patch.json", "json")

    for scene_validator in sorted(chapter_dir.glob("scene_*_validator_report.json")):
        _emit_block(
            f"{chapter_name} {scene_validator.name}",
            scene_validator,
            "json",
            max_chars=50000,
        )

    failures_dir = chapter_dir / "failures"
    if failures_dir.exists():
        for failure_file in sorted(failures_dir.rglob("*")):
            if not failure_file.is_file():
                continue
            rel = failure_file.relative_to(chapter_dir)
            lang = "json" if failure_file.suffix == ".json" else "text"
            _emit_block(
                f"{chapter_name} Failure Artifact: {rel}",
                failure_file,
                lang,
                max_chars=50000,
            )
PY

echo "==> Building run_summary.json"
python - <<PY > "$RUN_DIR/run_summary.json"
from pathlib import Path
import json
import glob

run_dir = Path(r"$RUN_DIR")
book_dir = Path(r"$BOOK_DIR")
log_dir = Path(r"$LOG_DIR")

audit_path = book_dir / "outline" / "book_audit.json"
audit = {}
if audit_path.exists():
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        audit = {}

chapters = sorted(glob.glob(str(book_dir / "chapters" / "chapter-*.md")))
word_counts = {}
for chapter in chapters:
    p = Path(chapter)
    try:
        word_counts[p.name] = len(p.read_text(encoding="utf-8").split())
    except Exception:
        word_counts[p.name] = None

summary = {
    "repo": r"$REPO_DIR",
    "git_revision": (run_dir / "git_revision.txt").read_text(encoding="utf-8").strip() if (run_dir / "git_revision.txt").exists() else None,
    "git_describe": (run_dir / "git_describe.txt").read_text(encoding="utf-8").strip() if (run_dir / "git_describe.txt").exists() else None,
    "run_dir": str(run_dir),
    "book_dir": str(book_dir),
    "log_dir": str(log_dir),
    "timestamp": r"$TIMESTAMP",
    "run_label": r"$RUN_LABEL",
    "exit_code": int(Path(r"$RUN_DIR/exit_code.txt").read_text(encoding="utf-8").strip()),
    "chapters_requested": int("$CHAPTERS"),
    "chapters_written": len(chapters),
    "chapter_word_counts": word_counts,
    "artifact_presence": {
        "run_log": (log_dir / "run.log").exists(),
        "canon_yml": (book_dir / "outline" / "canon.yml").exists(),
        "narrative_state_json": (book_dir / "outline" / "narrative_state.json").exists(),
      "narrative_audit_jsonl": (book_dir / "outline" / "narrative_audit.jsonl").exists(),
        "book_audit_json": (book_dir / "outline" / "book_audit.json").exists(),
        "book_audit_md": (book_dir / "outline" / "book_audit.md").exists(),
        "chapter_packets": (book_dir / "outline" / "chapter_packets").exists(),
    },
    "packet_counts": {
      "validator_report_json": len(glob.glob(str(book_dir / "outline" / "chapter_packets" / "chapter-*" / "validator_report.json"))),
      "scene_validator_report_json": len(glob.glob(str(book_dir / "outline" / "chapter_packets" / "chapter-*" / "scene_*_validator_report.json"))),
      "diagnostics_json": len(glob.glob(str(book_dir / "outline" / "chapter_packets" / "chapter-*" / "diagnostics.json"))),
      "failure_artifacts": len(glob.glob(str(book_dir / "outline" / "chapter_packets" / "chapter-*" / "failures" / "**" / "*"), recursive=True)),
    },
    "audit": {
        "status": audit.get("status"),
        "chapters_generated": audit.get("chapters_generated"),
      "chapters_target": audit.get("chapters_target"),
        "coherence_reviews_run": audit.get("coherence_reviews_run"),
      "patch_operations_applied": audit.get("patch_operations_applied"),
      "failed_guard": audit.get("failed_guard"),
        "error": audit.get("error"),
    },
}
print(json.dumps(summary, indent=2))
PY

echo
echo "==> Building merged diagnostics bundle"
: > "$MERGED_LOG"
{
  echo "# StoryCraftr merged diagnostics bundle"
  echo "repo=$REPO_DIR"
  echo "run_dir=$RUN_DIR"
  echo "book_dir=$BOOK_DIR"
  echo "log_dir=$LOG_DIR"
  echo "merged_log=$MERGED_LOG"
  echo "timestamp=$TIMESTAMP"
  echo "run_label=$RUN_LABEL"
  echo "main_model=$MAIN_MODEL"
  echo "chapters=$CHAPTERS"
  echo "embed_device=$EMBED_DEVICE"
  echo "exit_code=$BOOK_EXIT"
  echo
  echo "This file merges the run-level logs, summary files, outline artifacts,"
  echo "chapter-packet artifacts, and failure forensics for single-file diagnosis."
  echo
} >> "$MERGED_LOG"

for p in \
  "$RUN_DIR/exit_code.txt" \
  "$RUN_DIR/git_revision.txt" \
  "$RUN_DIR/git_describe.txt" \
  "$RUN_DIR/git_status.txt" \
  "$RUN_DIR/rankings.snapshot.json" \
  "$RUN_DIR/validator_report.schema.snapshot.json" \
  "$BOOK_DIR/storycraftr.json" \
  "$BOOK_DIR/seed.md"
do
  append_merged_file "$p"
done

while IFS= read -r path; do
  append_merged_file "$path"
done < <(find "$LOG_DIR" -maxdepth 1 -type f | sort)

for p in \
  "$BOOK_DIR/outline/book_audit.json" \
  "$BOOK_DIR/outline/book_audit.md" \
  "$BOOK_DIR/outline/canon.yml" \
  "$BOOK_DIR/outline/narrative_state.json" \
  "$BOOK_DIR/outline/narrative_audit.jsonl"
do
  append_merged_file "$p"
done

if [[ -d "$BOOK_DIR/chapters" ]]; then
  while IFS= read -r path; do
    append_merged_file "$path"
  done < <(find "$BOOK_DIR/chapters" -maxdepth 2 -type f | sort)
fi

if [[ -d "$BOOK_DIR/outline/chapter_packets" ]]; then
  while IFS= read -r path; do
    append_merged_file "$path"
  done < <(find "$BOOK_DIR/outline/chapter_packets" -maxdepth 8 -type f | sort)
fi

for p in \
  "$RUN_DIR/snapshot_manifest.md" \
  "$RUN_DIR/snapshot_packets.md" \
  "$RUN_DIR/run_summary.json"
do
  append_merged_file "$p"
done

echo
echo "==> Summary"
echo "RUN_DIR=$RUN_DIR"
echo "BOOK_DIR=$BOOK_DIR"
echo "LOG_DIR=$LOG_DIR"
echo "GIT_REVISION=$(cat "$RUN_DIR/git_revision.txt")"
echo "EXIT_CODE=$BOOK_EXIT"
echo "SNAPSHOT_MANIFEST=$RUN_DIR/snapshot_manifest.md"
echo "SNAPSHOT_PACKETS=$RUN_DIR/snapshot_packets.md"
echo "RUN_SUMMARY_JSON=$RUN_DIR/run_summary.json"
echo "MERGED_LOG=$MERGED_LOG"

if [[ "$BOOK_EXIT" -eq 0 ]]; then
  echo "Smoke run completed successfully."
else
  echo "Smoke run failed fail-closed with exit code $BOOK_EXIT."
fi

exit "$BOOK_EXIT"
