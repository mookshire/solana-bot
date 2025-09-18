import datetime as dt, requests
from .store import init_db, upsert_prices, fetch_prices
from .indicators import sma, slope_simple

SYMBOL = "SOL/USDC"

def try_jupiter():
    for url in [
        "https://price.jup.ag/v6/price?ids=SOL",
        "https://price.jup.ag/v4/price?ids=SOL",
    ]:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json().get("data", {})
        sol = data.get("SOL") or data.get("sol") or {}
        price = sol.get("price")
        if isinstance(price, (int, float)):
            return float(price)

def try_coinbase():
    # Public spot price, no key
    url = "https://api.coinbase.com/v2/prices/SOL-USD/spot"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    amt = r.json()["data"]["amount"]
    return float(amt)

def try_binance():
    # USDT is ≈ USD for our purposes
    url = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return float(r.json()["price"])

def fetch_price_usd():
    for fn in (try_jupiter, try_coinbase, try_binance):
        try:
            px = fn()
            if px and px > 0:
                return px, fn.__name__
        except Exception as e:
            continue
    raise RuntimeError("All price sources failed")

def iso_hour_now_utc() -> str:
    t = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    return t.isoformat() + "Z"

def main():
    init_db()
    px, source = fetch_price_usd()
    ts = iso_hour_now_utc()
    upsert_prices(SYMBOL, [(ts, px)])
    rows = fetch_prices(SYMBOL, limit=24*7)
    prices = [p for _, p in rows]
    print(f"Stored hourly price @ {ts} = {px} (source: {source})")
    print("Total hourly rows now:", len(prices))
    if len(prices) >= 24*7:
        print("SMA_7d:", round(sma(prices, 24*7), 6))
    else:
        print(f"Need {24*7 - len(prices)} more hourly points to compute SMA_7d.")
    if len(prices) >= 24*3:
        print("3d trend slope (per hour):", round(slope_simple(prices[-24*3:]), 6))
    else:
        print("3d trend needs", 24*3 - len(prices), "more hourly points.")

if __name__ == "__main__":
    main()
