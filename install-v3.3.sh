#!/usr/bin/env bash
set -euo pipefail

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$HOME/job-search-helper}"

if [[ ! -d "$TARGET" ]]; then
  echo "Target project does not exist: $TARGET" >&2
  exit 1
fi
if [[ ! -f "$TARGET/.env" ]]; then
  echo "Refusing to update: $TARGET/.env is missing." >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HOME/job-search-helper-code-backup-v3.3-$STAMP.tar.gz"

echo "Creating code backup: $BACKUP"
tar -czf "$BACKUP" -C "$TARGET" \
  --exclude='.venv' --exclude='.state' --exclude='.secrets' --exclude='credentials.json' \
  src job-search-helper job-search-reviewer pyproject.toml README.md 2>/dev/null || true

echo "Installing v3.3 scraper-only update..."
rsync -av \
  --exclude='.env' \
  --exclude='.state/' \
  --exclude='.secrets/' \
  --exclude='credentials.json' \
  --exclude='.venv/' \
  "$SOURCE/" "$TARGET/"

rm -f "$TARGET/src/job_search_helper/ai_worker.py"
rm -f "$TARGET/prompts/title-reviewer.txt" "$TARGET/prompts/job-reviewer.txt"
rm -f "$TARGET/requirements-ai.txt"

chmod +x "$TARGET/job-search-scraper" "$TARGET/job-search-reviewer" "$TARGET/migrate-v3.3.py"

PYTHON="$TARGET/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="$TARGET/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$TARGET"

echo "Migrating/backfilling Job History for ChatGPT Work..."
"$PYTHON" "$TARGET/migrate-v3.3.py"

echo
echo "v3.3 installed."
echo "Scraper command:  cd $TARGET && ./job-search-scraper start"
echo "Work prompt:      $TARGET/prompts/WORK-JOB-REVIEWER.txt"
echo "Your .env/.state/.secrets/credentials.json/.venv were preserved."
echo "OPENAI_API_KEY can remain in .env, but v3.3 never reads or uses it."
