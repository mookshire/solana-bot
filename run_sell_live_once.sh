#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate

# Show current toggles
echo "[live_once] Before: $(grep -E '^(DRY_RUN|TEST_MODE|TEST_MODE_MAX_TRADES)=' config/.env || true)"

# Ensure a fresh plan and then do a one-shot live attempt
# 1) flip DRY_RUN=false
sed -i 's/^DRY_RUN=.*/DRY_RUN=false/' config/.env
sed -i 's/^TEST_MODE=.*/TEST_MODE=false/' config/.env

# Always restore DRY_RUN=true on exit, even if something errors
trap 'sed -i "s/^DRY_RUN=.*/DRY_RUN=true/" config/.env; sed -i "s/^TEST_MODE=.*/TEST_MODE=true/" config/.env; echo "[live_once] Restored DRY_RUN=true, TEST_MODE=true";' EXIT

echo "[live_once] Running sell cycle LIVE (DRY_RUN=false)…"
export DRY_RUN=false
export TEST_MODE=false
python -m src.sell_logic

# Show toggles after (trap already restored)
echo "[live_once] After:  $(grep -E "^(DRY_RUN|TEST_MODE|TEST_MODE_MAX_TRADES)=" config/.env || true)"