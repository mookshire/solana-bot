#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate

echo "[buy_live_once] Before: $(grep -E '^(DRY_RUN|TEST_MODE|TEST_MODE_MAX_TRADES)=' config/.env || true)"

# Flip to live for this one run; always restore
sed -i 's/^DRY_RUN=.*/DRY_RUN=false/' config/.env
trap 'sed -i "s/^DRY_RUN=.*/DRY_RUN=true/" config/.env; echo "[buy_live_once] Restored DRY_RUN=true";' EXIT

python -m src.buy_live_once

echo "[buy_live_once] After:  $(grep -E "^(DRY_RUN|TEST_MODE|TEST_MODE_MAX_TRADES)=" config/.env || true)"
