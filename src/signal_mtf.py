from __future__ import annotations
import os, json
from datetime import datetime, timezone
from .backtest_combo_mtf import (
    fetch_klines, add_indicators, make_bias_series_1h, signals_15m_with_filters
)

def latest_signal() -> dict:
    sym   = os.getenv("BB_SYMBOL","SOLUSDT").upper()
    t_int = os.getenv("BB_INTERVAL","15m")
    t_lim = int(os.getenv("BB_LIMIT","5000"))
    b_int = os.getenv("MTF_BIAS_INTERVAL","1h")
    b_lim = int(os.getenv("MTF_BIAS_LIMIT","2000"))

    df15 = fetch_klines(sym, t_int, t_lim)
    df1h = fetch_klines(sym, b_int, b_lim)

    # indicators + bias
    df15i = add_indicators(df15)
    df1hi = add_indicators(df1h)
    bias_ok = make_bias_series_1h(df1hi, df15i)

    # signals with filters (RSI/Volume/BULL_ONLY via env)
    sig_df = signals_15m_with_filters(df15i, bias_ok)

    # last bar info
    last = sig_df.iloc[-1]

    # Decide action mapping for our bot
    raw_sig = str(last["signal"])  # BUY / SELL / HOLD
    action = (
        "BUY_SOL"  if raw_sig == "BUY"  else
        "SELL_SOL" if raw_sig == "SELL" else
        "HOLD"
    )

    # Build a readable reason
    filters = {
        "BULL_ONLY": int(os.getenv("BULL_ONLY","1")),
        "RSI_BUY_LT": float(os.getenv("RSI_BUY_LT","55")),
        "RSI_SELL_GT": float(os.getenv("RSI_SELL_GT","61")),
        "VOL_BUY_X": float(os.getenv("VOL_BUY_X","0.85")),
        "VOL_SELL_X": float(os.getenv("VOL_SELL_X","1.25")),
    }

    reasons = []
    if not bool(last.get("bias_ok", True)) and filters["BULL_ONLY"] == 1:
        reasons.append("Bull-only: 1h bias not OK")

    # Note: these mirror the rules in signals_15m_with_filters
    if raw_sig == "BUY":
        reasons.append(f"RSI {last['rsi']:.1f} < {filters['RSI_BUY_LT']}")
        reasons.append(f"Vol {last['volume']:.0f} > {filters['VOL_BUY_X']} × vol_sma20 {last['vol_sma20']:.0f}")
    elif raw_sig == "SELL":
        reasons.append(f"RSI {last['rsi']:.1f} > {filters['RSI_SELL_GT']}")
        reasons.append(f"Vol {last['volume']:.0f} > {filters['VOL_SELL_X']} × vol_sma20 {last['vol_sma20']:.0f}")
    else:
        reasons.append("No condition met")

    out = {
        "symbol": sym,
        "interval": t_int,
        "bias_interval": b_int,
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "last_time": last["close_time"].isoformat(),
        "last_price": float(last["close"]),
        "ema9": float(last["ema9"]),
        "ema21": float(last["ema21"]),
        "rsi": float(last["rsi"]),
        "macd_hist": float(last["macd_hist"]),
        "vol": float(last["volume"]),
        "vol_sma20": float(last["vol_sma20"]),
        "sma200": float(last["sma200"]),
        "bias_ok": bool(bias_ok.iloc[-1]),
        "signal": raw_sig,          # BUY / SELL / HOLD
        "action": action,           # BUY_SOL / SELL_SOL / HOLD
        "reason": "; ".join(reasons),
        "filters": filters
    }
    return out

if __name__ == "__main__":
    print(json.dumps(latest_signal(), indent=2))
