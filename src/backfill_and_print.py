import datetime as dt, requests
from .store import init_db, upsert_prices, fetch_prices
from .indicators import sma, slope_simple

SYMBOL = "SOL/USDC"

def iso_hour(ts_ms: int) -> str:
    t = dt.datetime.utcfromtimestamp(ts_ms/1000).replace(minute=0, second=0, microsecond=0)
    return t.isoformat() + "Z"

def backfill_7d_hourly():
    url = "https://api.coingecko.com/api/v3/coins/solana/market_chart"
    params = {"vs_currency": "usd", "days": "7", "interval": "hourly"}
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    prices = r.json().get("prices", [])
    rows = [(iso_hour(ts_ms), float(price)) for ts_ms, price in prices]
    upsert_prices(SYMBOL, rows)
    return len(rows)

def main():
    init_db()
    n = backfill_7d_hourly()
    data = fetch_prices(SYMBOL, limit=24*7)
    prices = [p for _, p in data]
    last_price = prices[-1] if prices else None
    s7d = sma(prices, 24*7)
    trend_window = 24*3
    trend_slope = slope_simple(prices[-trend_window:]) if len(prices) >= trend_window else slope_simple(prices)
    print("Backfilled rows:", n)
    print("Last price:", last_price)
    print("SMA_7d:", round(s7d, 6))
    print("3d trend slope (per hour):", round(trend_slope, 6))
    print("Trend is", "flat/up" if trend_slope >= 0 else "down")

if __name__ == "__main__":
    main()
