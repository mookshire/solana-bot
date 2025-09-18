from __future__ import annotations
import os, json
from pathlib import Path
from itertools import product
from src.backtest_bb import fetch_binance_to_csv, load_csv, backtest, DATA_DIR

SYMBOL   = os.getenv("BB_SYMBOL", "SOLUSDT")
INTERVAL = os.getenv("BB_INTERVAL", "5m")
LIMIT    = int(os.getenv("BB_LIMIT", "1000"))

csv_path = DATA_DIR / f"binance_{SYMBOL}_{INTERVAL}.csv"
fetch_binance_to_csv(csv_path, SYMBOL, INTERVAL, LIMIT)
times, *_rest, closes = load_csv(csv_path)

periods = [20, 30, 40]
ks      = [2.0, 2.5, 3.0]
emas    = [200]
chops   = [0.006, 0.008, 0.010]
cooldowns = [1, 2, 3]
fee_bps = 12.5
slip_bps = 12.5

results = []
for P,K,E,CH,CD in product(periods, ks, emas, chops, cooldowns):
    # inject params via env for backtest()
    os.environ.update({
        "BB_PERIOD": str(P),
        "BB_K": str(K),
        "BB_EMA_N": str(E),
        "BB_CHOP_PCT": str(CH),
        "BB_COOLDOWN_BARS": str(CD),
        "BB_FEE_BPS": str(fee_bps),
        "BB_SLIP_BPS": str(slip_bps),
        "BB_SYMBOL": SYMBOL,
        "BB_INTERVAL": INTERVAL,
    })
    report, trades = backtest(times, closes)
    results.append((report["equity_multiple"], report["trades"], report))

# keep only runs with at least 5 trades, sort by equity desc then drawdown asc
filtered = [x for x in results if x[1] >= 5]
filtered.sort(key=lambda x: (-x[0], x[2]["max_drawdown_pct"]))

print(json.dumps([r[2] for r in filtered[:10]], indent=2))
