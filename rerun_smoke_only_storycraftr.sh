#!/usr/bin/env bash
set -euo pipefail

# StoryCraftr smoke runner
#
# Purpose:
# - run a fully logged smoke outside the repo
# - keep all generated logs/artifacts in a single timestamped folder
# - generate AI-friendly snapshot files for later diagnosis
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
#
# Example:
#   RUN_LABEL=v101_trinity CHAPTERS=3 /home/orion22/rerun_smoke_only_storycraftr.sh

REPO_DIR="${REPO_DIR:-$HOME/storycraftr-next}"
LOGS_ROOT="${LOGS_ROOT:-$HOME/Logs/storycraftr_smokes}"
RUN_LABEL="${RUN_LABEL:-smoke}"
MAIN_MODEL="${MAIN_MODEL:-arcee-ai/trinity-large-preview:free}"
CHAPTERS="${CHAPTERS:-3}"
EMBED_DEVICE="${EMBED_DEVICE:-cuda}"

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

mkdir -p "$BOOK_DIR" "$LOG_DIR"

cd "$REPO_DIR"
source .venv/bin/activate

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

echo "==> Quick sentence-transformers verification"
python - <<PY | tee "$LOG_DIR/embedding_check.log"
from sentence_transformers import SentenceTransformer
device = "$EMBED_DEVICE"
model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)
print("sentence_transformer_device =", model.device)
vec = model.encode(["StoryCraftr smoke verification"])
print("embedding_ok =", len(vec), len(vec[0]))
PY

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
MD

echo "==> Smoke config"
cat "$BOOK_DIR/storycraftr.json" | tee "$LOG_DIR/storycraftr.json.snapshot.log"

echo "==> Running StoryCraftr smoke"
set +e
storycraftr book \
  --book-path "$BOOK_DIR" \
  --seed "$BOOK_DIR/seed.md" \
  --chapters "$CHAPTERS" \
  --yes 2>&1 | tee "$LOG_DIR/run.log"
BOOK_EXIT=${PIPESTATUS[0]}
set -e

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
print("coherence_reviews_run =", data.get("coherence_reviews_run"))
print("error =", data.get("error"))
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
echo "==> Chapter packet inventory"
find "$BOOK_DIR/outline/chapter_packets" -maxdepth 6 -type f | sort | tee "$LOG_DIR/chapter_packet_inventory.txt" || true

echo
echo "==> Failure inventory"
find "$BOOK_DIR/outline/chapter_packets" -path "*/failures/*" -type f | sort | tee "$LOG_DIR/failure_inventory.txt" || true

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
  echo "## Run Log Tail"
  echo '```text'
  cat "$LOG_DIR/run_tail.log" 2>/dev/null || true
  echo '```'
} > "$RUN_DIR/snapshot_manifest.md"

echo "==> Building snapshot_packets.md"

{
  echo "# StoryCraftr Packet Snapshot"
  echo

  CH1="$BOOK_DIR/outline/chapter_packets/chapter-001"
  CH2="$BOOK_DIR/outline/chapter_packets/chapter-002"

  if [[ -f "$CH1/diagnostics.json" ]]; then
    echo "## Chapter 1 Diagnostics"
    echo '```json'
    cat "$CH1/diagnostics.json"
    echo '```'
    echo
  fi

  if [[ -f "$CH1/validator_report.json" ]]; then
    echo "## Chapter 1 Validator Report"
    echo '```json'
    cat "$CH1/validator_report.json"
    echo '```'
    echo
  fi

  if [[ -f "$CH1/scene_plan.json" ]]; then
    echo "## Chapter 1 Scene Plan"
    echo '```json'
    cat "$CH1/scene_plan.json"
    echo '```'
    echo
  fi

  if [[ -f "$CH1/canon_delta.yml" ]]; then
    echo "## Chapter 1 Canon Delta"
    echo '```yaml'
    cat "$CH1/canon_delta.yml"
    echo '```'
    echo
  fi

  if [[ -f "$CH1/state_patch.json" ]]; then
    echo "## Chapter 1 State Patch"
    echo '```json'
    cat "$CH1/state_patch.json"
    echo '```'
    echo
  fi

  if [[ -f "$CH2/failures/attempt-1.txt" ]]; then
    echo "## Chapter 2 Failure Attempt 1"
    echo '```text'
    cat "$CH2/failures/attempt-1.txt"
    echo '```'
    echo
  fi

  if [[ -f "$CH2/failures/attempt-2.txt" ]]; then
    echo "## Chapter 2 Failure Attempt 2"
    echo '```text'
    cat "$CH2/failures/attempt-2.txt"
    echo '```'
    echo
  fi

  # Include all other failure files if they exist
  if [[ -d "$CH2/failures" ]]; then
    for f in "$CH2"/failures/*; do
      [[ -f "$f" ]] || continue
      base="$(basename "$f")"
      if [[ "$base" != "attempt-1.txt" && "$base" != "attempt-2.txt" ]]; then
        echo "## Chapter 2 Failure: $base"
        echo '```text'
        cat "$f"
        echo '```'
        echo
      fi
    done
  fi
} > "$RUN_DIR/snapshot_packets.md"

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
        "book_audit_json": (book_dir / "outline" / "book_audit.json").exists(),
        "book_audit_md": (book_dir / "outline" / "book_audit.md").exists(),
        "chapter_packets": (book_dir / "outline" / "chapter_packets").exists(),
    },
    "audit": {
        "status": audit.get("status"),
        "chapters_generated": audit.get("chapters_generated"),
        "coherence_reviews_run": audit.get("coherence_reviews_run"),
        "error": audit.get("error"),
    },
}
print(json.dumps(summary, indent=2))
PY

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

if [[ "$BOOK_EXIT" -eq 0 ]]; then
  echo "Smoke run completed successfully."
else
  echo "Smoke run failed fail-closed with exit code $BOOK_EXIT."
fi

exit "$BOOK_EXIT"