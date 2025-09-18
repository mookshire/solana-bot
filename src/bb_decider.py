from __future__ import annotations
import json, time, os
from pathlib import Path
import requests
from src.indicators import bollinger_bands

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = DATA_DIR / "signal_bb.json"
HEARTBEAT = DATA_DIR / "heartbeat.txt"

# Tunables
PERIOD = int(os.getenv("BB_PERIOD", "20"))
K = float(os.getenv("BB_K", "2.0"))
SYMBOL = os.getenv("BB_SYMBOL", "SOLUSDT")  # Binance spot symbol
INTERVAL = os.getenv("BB_INTERVAL", "1m")
LIMIT = int(os.getenv("BB_LIMIT", "500"))   # up to 1000

BINANCE_URL = "https://api.binance.com/api/v3/klines"
HEADERS = {"User-Agent": "solana-bot/1.0"}

def fetch_binance_closes(symbol: str, interval: str, limit: int):
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    r = requests.get(BINANCE_URL, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    # kline format: [openTime, open, high, low, close, volume, closeTime, ...]
    closes = [float(k[4]) for k in data]
    return closes

def decide():
    closes = fetch_binance_closes(SYMBOL, INTERVAL, LIMIT)
    if len(closes) < PERIOD:
        return {"ok": False, "reason": "not_enough_data", "have": len(closes), "need": PERIOD}
    up, mid, lo = bollinger_bands(closes, PERIOD, K)
    price = closes[-1]
    u, m, l = up[-1], mid[-1], lo[-1]

    # Simple rules (we'll evolve later):
    signal = "HOLD"
    if price >= u:
        signal = "SELL"
    elif price <= l:
        signal = "BUY_SOON"

    return {
        "ok": True,
        "exchange": "binance_spot",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "period": PERIOD,
        "k": K,
        "price": price,
        "upper": u,
        "middle": m,
        "lower": l,
        "signal": signal,
        "ts": int(time.time()),
        "source": "binance_klines",
    }

def main():
    res = decide()
    print(json.dumps(res, indent=2, sort_keys=True))
    if res.get("ok"):
        OUT_FILE.write_text(json.dumps(res, separators=(",",":")))
        HEARTBEAT.write_text(str(int(time.time())) + "\n")

if __name__ == "__main__":
    main()
