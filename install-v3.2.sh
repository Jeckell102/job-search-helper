#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${1:-$HOME/job-search-helper}"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Target project does not exist: $TARGET_DIR" >&2
  exit 1
fi

if [[ ! -f "$TARGET_DIR/pyproject.toml" ]]; then
  echo "Target does not look like the job-search-helper project: $TARGET_DIR" >&2
  exit 1
fi

rsync -av \
  --exclude='.env' \
  --exclude='.state/' \
  --exclude='.secrets/' \
  --exclude='credentials.json' \
  --exclude='.venv/' \
  "$SOURCE_DIR/" "$TARGET_DIR/"

chmod +x "$TARGET_DIR/job-search-reviewer"

echo
echo "v3.2 efficiency update installed in: $TARGET_DIR"
echo "Preserved: .env, .state, .secrets, credentials.json, .venv"
echo "Start/resume with:"
echo "  cd $TARGET_DIR"
echo "  ./job-search-reviewer start"
