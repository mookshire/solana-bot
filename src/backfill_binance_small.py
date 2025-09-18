import time, datetime as dt, requests, math
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .store import init_db, upsert_prices, connect

SYMBOL = "SOL/USDC"

def iso_hour(ts_ms: int) -> str:
    t = dt.datetime.utcfromtimestamp(ts_ms/1000).replace(minute=0, second=0, microsecond=0)
    return t.isoformat() + "Z"

@retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=10),
       retry=retry_if_exception_type(Exception))
def fetch_klines_1h(symbol="SOLUSDT", start_ms=None, end_ms=None, limit=100):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1h", "limit": limit}
    if start_ms is not None: params["startTime"] = start_ms
    if end_ms   is not None: params["endTime"]   = end_ms
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def backfill_last_24h():
    init_db()
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - 24 * 60 * 60 * 1000
    klines = fetch_klines_1h(start_ms=start_ms, end_ms=now_ms, limit=1000)
    rows = [(iso_hour(int(k[0])), float(k[4])) for k in klines]
    if rows:
        upsert_prices(SYMBOL, rows)
    with connect() as cx:
        n, = cx.execute("SELECT COUNT(*) FROM prices_hourly WHERE symbol=?", (SYMBOL,)).fetchone()
    print(f"Inserted rows: {len(rows)}  | total rows now: {n}")

if __name__ == "__main__":
    backfill_last_24h()
