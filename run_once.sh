#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/solana-bot"
source .venv/bin/activate
python -m src.strategy_loop

# --- SELL LOGIC ---
./run_sell_once.sh
