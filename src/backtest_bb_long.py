from __future__ import annotations
import os, json, time, requests
from typing import List, Tuple
from src.backtest_bb import backtest  # uses your EMA/BB/chop/cooldown/fees from env

BINANCE_URL = "https://api.binance.com/api/v3/klines"
HEADERS = {"User-Agent": "solana-bot/1.0"}

SYMBOL    = os.getenv("BB_SYMBOL", "SOLUSDT")
INTERVAL  = os.getenv("BB_INTERVAL", "15m")
TOTAL     = int(os.getenv("BB_TOTAL", "5000"))     # how many bars you want (<= 5000)
CHUNK     = 1000                                   # Binance per-request cap

def fetch_paged(symbol: str, interval: str, total: int) -> list:
    """Fetch candles in chunks going backwards then return oldest->newest."""
    out: List[list] = []
    end_time = None
    need = total
    while need > 0:
        limit = CHUNK if need > CHUNK else need
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        r = requests.get(BINANCE_URL, params=params, headers=HEADERS, timeout=25)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        # prepend older batches; batch is oldest->newest already for this window
        out = batch + out
        # next page: everything strictly before the first openTime in this batch
        end_time = int(batch[0][0]) - 1
        need -= len(batch)
        # small safety sleep to avoid rate limits
        time.sleep(0.1)
    # ensure we only keep the last `total` bars oldest->newest
    return out[-total:]

def main():
    ks = fetch_paged(SYMBOL, INTERVAL, TOTAL)
    times = [int(k[0]//1000) for k in ks]
    closes = [float(k[4]) for k in ks]
    report, trades = backtest(times, closes)
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
