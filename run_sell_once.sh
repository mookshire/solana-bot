#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Always use the venv
source .venv/bin/activate

# Safety pin: keep DRY_RUN on unless you explicitly change it
sed -i 's/^DRY_RUN=.*/DRY_RUN=true/' config/.env

echo "[run_sell_once] Starting sell cycle…"
python -m src.sell_logic
echo "[run_sell_once] Done."
