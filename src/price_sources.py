import requests
import datetime as dt, requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# --- Jupiter primary with robust retries ---
@retry(
    reraise=True,
    stop=stop_after_attempt(5),                    # up to 5 tries
    wait=wait_exponential(multiplier=1, max=10),   # 1s,2s,4s,8s,10s
    retry=retry_if_exception_type(Exception),
)
def try_jupiter():
    headers = {"User-Agent": "solana-bot/1.0"}
    for url in (
        "https://price.jup.ag/v6/price?ids=SOL",
        "https://price.jup.ag/v4/price?ids=SOL",
    ):
        r = requests.get(url, timeout=12, headers=headers)
        r.raise_for_status()
        data = r.json().get("data", {})
        sol = data.get("SOL") or data.get("sol") or {}
        px = sol.get("price")
        if isinstance(px, (int, float)):
            return float(px)
    raise RuntimeError("Jupiter responded but no price parsed")

def try_coinbase():
    r = requests.get("https://api.coinbase.com/v2/prices/SOL-USD/spot", timeout=12)
    r.raise_for_status()
    return float(r.json()["data"]["amount"])

def try_binance():
    r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=12)
    r.raise_for_status()
    return float(r.json()["price"])

def fetch_price_usd():
    # Strong preference ordering
    for fn in (try_jupiter, try_coinbase, try_binance):
        try:
            px = fn()
            if px and px > 0:
                return px, fn.__name__
        except Exception:
            continue
    raise RuntimeError("All price sources failed")

def iso_hour_now_utc():
    t = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    return t.isoformat() + "Z"


def fetch_klines(symbol: str = "SOLUSDT", interval: str = "15m", limit: int = 500):
    """Return Binance OHLCV klines as list[dict] with keys:
    open_time, open, high, low, close, volume, close_time
    """
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    data = r.json()
    out = []
    for k in data:
        out.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": k[6],
        })
    return out
