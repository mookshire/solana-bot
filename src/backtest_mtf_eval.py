from __future__ import annotations
import os, json
import pandas as pd
from typing import Dict, Any
from src.backtest_combo_mtf import (
    fetch_klines, add_indicators, make_bias_series_1h, signals_15m_with_filters
)

def pick_ts(row):
    if "ts" in row: return pd.to_datetime(row["ts"])
    if "close_time" in row: return pd.to_datetime(row["close_time"])
    return pd.to_datetime(row.name)

def run() -> Dict[str, Any]:
    sym   = os.getenv("BB_SYMBOL","SOLUSDT").upper()
    t_int = os.getenv("BB_INTERVAL","15m");  t_lim = int(os.getenv("BB_LIMIT","5000"))
    b_int = os.getenv("MTF_BIAS_INTERVAL","1h"); b_lim = int(os.getenv("MTF_BIAS_LIMIT","2000"))
    fee_bps = float(os.getenv("BB_FEE_BPS","12.5"))
    slp_bps = float(os.getenv("BB_SLP_BPS","12.5"))
    cost_per_side = (fee_bps + slp_bps) / 1e4

    # data + indicators
    df15 = add_indicators(fetch_klines(sym, t_int, t_lim))
    df1h = add_indicators(fetch_klines(sym, b_int, b_lim))
    bias_ok = make_bias_series_1h(df1h, df15)
    sig_df = signals_15m_with_filters(df15, bias_ok)  # has 'signal' and 'reason'

    trades = []
    open_buy = None
    equity = 1.0
    for _, row in sig_df.iterrows():
        act = row.get("signal", "HOLD")
        if act == "BUY" and open_buy is None:
            open_buy = {
                "time": pick_ts(row),
                "px": float(row["close"]),
                "reason": row.get("reason",""),
            }
        elif act == "SELL" and open_buy is not None:
            bt = open_buy["time"]; bp = open_buy["px"]
            st = pick_ts(row);     sp = float(row["close"])
            gross = (sp - bp) / bp
            net   = gross - 2*cost_per_side
            equity *= (1.0 + net)
            trades.append({
                "id": len(trades) + 1,
                "buy_time": bt.isoformat(),
                "buy_px": bp,
                "buy_reason": open_buy.get("reason",""),
                "sell_time": st.isoformat(),
                "sell_px": sp,
                "sell_reason": row.get("reason",""),
                "gross_ret_pct": round(gross*100, 4),
                "net_ret_pct": round(net*100, 4),
                "equity_mult_after": round(equity, 6),
            })
            open_buy = None

    wins = sum(1 for t in trades if t["net_ret_pct"] > 0)
    losses = len(trades) - wins
    wr = round(100*wins/max(1,len(trades)), 3)
    last = sig_df.iloc[-1]

    # always write CSV
    outdir = os.path.join("data","backtests"); os.makedirs(outdir, exist_ok=True)
    pd.DataFrame(trades).to_csv(os.path.join(outdir,"mtf_trades.csv"), index=False)

    return {
        "symbol": sym, "interval": t_int, "bias_interval": b_int,
        "bars": int(len(sig_df)), "trades": int(len(trades)),
        "wins": int(wins), "losses": int(losses), "win_rate_pct": wr,
        "equity_multiple": round(equity, 6),
        "last_signal": str(last.get("signal","HOLD")),
        "last_price": float(last["close"]),
        "last_time": pick_ts(last).isoformat(),
        "RSI_BUY_LT": float(os.getenv("RSI_BUY_LT","55")),
        "RSI_SELL_GT": float(os.getenv("RSI_SELL_GT","61")),
        "VOL_BUY_X": float(os.getenv("VOL_BUY_X","0.85")),
        "VOL_SELL_X": float(os.getenv("VOL_SELL_X","1.25")),
        "BULL_ONLY": int(os.getenv("BULL_ONLY","1")),
        "fee_bps": fee_bps, "slip_bps": slp_bps,
    }

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
