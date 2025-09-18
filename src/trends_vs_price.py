import pandas as pd
import ccxt
from pytrends.request import TrendReq
import matplotlib.pyplot as plt
from pathlib import Path

OUT_DIR = Path.home() / "Desktop"

# 1) Google Trends (last 12 months)
pytrends = TrendReq(hl='en-US', tz=360)
kw = ["Solana"]
pytrends.build_payload(kw, timeframe='today 12-m')
trend = pytrends.interest_over_time().reset_index()[["date","Solana"]]

# 2) SOL/USDT daily prices (Binance)
ex = ccxt.binance()
ohlcv = ex.fetch_ohlcv('SOL/USDT', timeframe='1d', limit=365)
price = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
price["date"] = pd.to_datetime(price["ts"], unit="ms")
price = price[["date","close"]]

# 3) Merge & normalize
df = pd.merge(trend, price, on="date", how="inner").sort_values("date")
df["trend_norm"] = df["Solana"] / df["Solana"].max()
df["price_norm"] = df["close"] / df["close"].max()

# 4) Same-day corr
same_day_corr = df["trend_norm"].corr(df["price_norm"])

# 5) Lag tests (1..7 days)
lags = list(range(1,8))
buzz_leads_price = []   # corr( trend(t-lag), price(t) )
price_leads_buzz = []   # corr( price(t-lag), trend(t) )
for L in lags:
    buzz_leads_price.append(df["trend_norm"].shift(L).corr(df["price_norm"]))
    price_leads_buzz.append(df["price_norm"].shift(L).corr(df["trend_norm"]))

# 6) Save CSV
OUT_DIR.mkdir(parents=True, exist_ok=True)
csv_path = OUT_DIR / "sol_trends_price_correlations.csv"
pd.DataFrame({
    "lag_days": lags,
    "buzz_leads_price": buzz_leads_price,
    "price_leads_buzz": price_leads_buzz
}).to_csv(csv_path, index=False)

# 7) Plots (saved as PNGs; no GUI needed)
# 7a) Time-series overlay
fig1 = plt.figure(figsize=(12,5))
plt.plot(df["date"], df["trend_norm"], label="Google Trends (normalized)")
plt.plot(df["date"], df["price_norm"], label="SOL Price (normalized)")
plt.title(f"Solana: Trends vs Price (same-day corr = {same_day_corr:.3f})")
plt.legend()
ts_path = OUT_DIR / "sol_trends_vs_price_timeseries.png"
plt.tight_layout()
plt.savefig(ts_path, dpi=140)
plt.close(fig1)

# 7b) Lag correlation curves
fig2 = plt.figure(figsize=(10,5))
plt.plot(lags, buzz_leads_price, marker="o", label="Buzz leads Price")
plt.plot(lags, price_leads_buzz, marker="o", label="Price leads Buzz")
plt.axhline(0, linestyle="--", linewidth=1)
plt.xlabel("Lag (days)")
plt.ylabel("Correlation")
plt.title("Lagged correlations: Buzz↔Price")
plt.xticks(lags)
plt.legend()
lag_path = OUT_DIR / "sol_trends_vs_price_lagcorr.png"
plt.tight_layout()
plt.savefig(lag_path, dpi=140)
plt.close(fig2)

print({
    "same_day_corr": round(same_day_corr, 3),
    "csv": str(csv_path),
    "timeseries_png": str(ts_path),
    "lagcorr_png": str(lag_path)
})
