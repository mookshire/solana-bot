from __future__ import annotations
import os, json, time, requests
from itertools import product
from src.backtest_bb import backtest

BINANCE_URL = "https://api.binance.com/api/v3/klines"
UA = {"User-Agent": "solana-bot/1.0"}

def fetch_paged(symbol: str, interval: str, total: int = 10000):
    out = []; end_time = None
    need = total; CHUNK = 1000
    while need > 0:
        limit = CHUNK if need > CHUNK else need
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time is not None: params["endTime"] = end_time
        r = requests.get(BINANCE_URL, params=params, headers=UA, timeout=25); r.raise_for_status()
        batch = r.json()
        if not batch: break
        out = batch + out
        end_time = int(batch[0][0]) - 1
        need -= len(batch)
        time.sleep(0.1)
    return out[-total:]

def run_sweep():
    SYMBOL="SOLUSDT"; INTERVAL="1h"; TOTAL=10000
    ks        = [2.0, 2.2, 2.4, 2.6, 2.8]
    chops     = [0.010, 0.014, 0.018, 0.022]
    cooldowns = [1, 2, 3]
    period    = 20; ema_n = 200
    fee_bps   = 12.5; slip_bps = 12.5

    ks_data = fetch_paged(SYMBOL, INTERVAL, TOTAL)
    times  = [int(k[0]//1000) for k in ks_data]
    closes = [float(k[4]) for k in ks_data]

    results = []
    for K, CH, CD in product(ks, chops, cooldowns):
        os.environ.update({
            "BB_SYMBOL": SYMBOL, "BB_INTERVAL": INTERVAL,
            "BB_PERIOD": str(period), "BB_K": str(K),
            "BB_EMA_N": str(ema_n), "BB_CHOP_PCT": str(CH),
            "BB_COOLDOWN_BARS": str(CD),
            "BB_FEE_BPS": str(fee_bps), "BB_SLIP_BPS": str(slip_bps),
        })
        report, _ = backtest(times, closes)
        results.append(report)

    # keep sets with >= 10 trades, sort by equity desc then drawdown asc
    filt = [r for r in results if r["trades"] >= 10]
    filt.sort(key=lambda r: (-r["equity_multiple"], r["max_drawdown_pct"]))
    print(json.dumps(filt[:12], indent=2))

if __name__ == "__main__":
    run_sweep()
