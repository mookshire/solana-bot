#!/usr/bin/env bash
set -euo pipefail
ts="$(date -u +'%Y%m%d-%H%M%S')"
src="data/trades.sqlite"
dst="data/backups/trades-${ts}.sqlite.gz"
if [ ! -f "$src" ]; then
  echo "No $src found." >&2
  exit 1
fi
gzip -c "$src" > "$dst"
echo "Local backup written: $dst"
