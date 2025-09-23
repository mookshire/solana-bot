#!/usr/bin/env bash
set -euo pipefail

ENVFILE="${1:-configs/phase4_balanced.env}"
USE_RISK="${USE_RISK:-1}"

# Activate venv and load env file if present
. .venv/bin/activate
if [ -f "$ENVFILE" ]; then
  set -a
  source "$ENVFILE"
  set +a
fi

# Default symbol/interval if not provided by env
export BB_SYMBOL="${BB_SYMBOL:-SOLUSDC}"
export BB_INTERVAL="${BB_INTERVAL:-15m}"

if [ "$USE_RISK" = "1" ]; then
  echo ">>> Running risk-enabled backtest (EMA+ATR stops/TP+sizing)…"
  python3 src/backtest_with_risk.py
  MSG="phase4: main run (risk ON) ${BB_SYMBOL} ${BB_INTERVAL}"
else
  echo ">>> Running baseline backtest (legacy)…"
  python3 src/backtest_hybrid.py
  MSG="phase4: main run (baseline) ${BB_SYMBOL} ${BB_INTERVAL}"
fi

# Auto-commit & push whatever got produced
./scripts/save.sh "$MSG"
