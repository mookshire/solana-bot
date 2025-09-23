#!/usr/bin/env bash
set -euo pipefail
msg="${1:-"autosave: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"}"
branch="$(git rev-parse --abbrev-ref HEAD)"
git add -A
if ! git diff --cached --quiet; then
  git commit -m "$msg"
else
  echo "No changes to commit."
fi
git push -u origin "$branch"
echo "Pushed to origin/$branch"
