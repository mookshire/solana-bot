import time, datetime as dt, requests
from .store import init_db, upsert_prices, connect

SYMBOL = "SOL/USDC"

def iso_hour(ts_ms: int) -> str:
    t = dt.datetime.utcfromtimestamp(ts_ms/1000).replace(minute=0, second=0, microsecond=0)
    return t.isoformat() + "Z"

def fetch_klines_1h(symbol="SOLUSDT", start_ms=None, end_ms=None, limit=1000):
    # https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1h
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1h", "limit": limit}
    if start_ms is not None: params["startTime"] = start_ms
    if end_ms is not None: params["endTime"] = end_ms
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def backfill_last_7d():
    init_db()
    now_ms = int(time.time() * 1000)
    seven_days_ms = 7 * 24 * 60 * 60 * 1000
    start_ms = now_ms - seven_days_ms

    klines = fetch_klines_1h(start_ms=start_ms, end_ms=now_ms, limit=1000)
    # Each kline: [openTime, open, high, low, close, volume, closeTime, ...]
    rows = []
    for k in klines:
        ts_ms = int(k[0])
        close_px = float(k[4])
        rows.append((iso_hour(ts_ms), close_px))
    if rows:
        upsert_prices(SYMBOL, rows)
    # report count
    with connect() as cx:
        n, = cx.execute("SELECT COUNT(*) FROM prices_hourly WHERE symbol=?", (SYMBOL,)).fetchone()
    print(f"Inserted/updated rows: {len(rows)}; total rows now: {n}")

if __name__ == "__main__":
    backfill_last_7d()
