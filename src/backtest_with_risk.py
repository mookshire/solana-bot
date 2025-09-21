from __future__ import annotations
import os, json, math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from statistics import mean
from risk_controls import atr, calc_stops, position_size_units

# --- Config via env ---
SYMBOL   = os.getenv("BB_SYMBOL","SOLUSDT").upper()
INTERVAL = os.getenv("BB_INTERVAL","15m")
LIMIT    = int(os.getenv("BB_LIMIT","2000"))
EMA_FAST = int(os.getenv("EMA_FAST","20"))
EMA_SLOW = int(os.getenv("EMA_SLOW","55"))
ATR_P    = int(os.getenv("ATR_PERIOD","14"))
SL_K     = float(os.getenv("SL_ATR_MULT","1.5"))
TP_K     = float(os.getenv("TP_ATR_MULT","3.0"))
RISK_PCT = float(os.getenv("RISK_PCT","0.005"))  # 0.5% per trade
EQUITY0  = float(os.getenv("EQUITY_USD","10000"))
FEES_BPS = float(os.getenv("FEES_BPS","10"))     # 0.10% per fill

@dataclass
class Candle:
    t: int; o: float; h: float; l: float; c: float; v: float

def ema(series: List[float], n: int) -> List[Optional[float]]:
    if n <= 1: return list(series)
    out: List[Optional[float]] = [None]*len(series)
    k = 2/(n+1)
    s = None
    for i,x in enumerate(series):
        if i+1 == n:
            s = mean(series[:i+1])
            out[i] = s
        elif i+1 > n:
            s = (x - s)*k + s
            out[i] = s
    return out

def fetch_data() -> List[Candle]:
    """
    Try to import user's existing fetch_klines from backtest_hybrid.py.
    Fallback: load from data/klines_{SYMBOL}_{INTERVAL}.json if present.
    Last fallback: small synthetic series.
    """
    # Try backtest_hybrid
    try:
        from backtest_hybrid import fetch_klines
        data = fetch_klines(SYMBOL, INTERVAL, LIMIT)
        out: List[Candle] = [Candle(int(d["t"]), d["o"], d["h"], d["l"], d["c"], d.get("v",0.0)) for d in data]
        return out
    except Exception:
        pass
    # Try local JSON cache
    p = Path(f"data/klines_{SYMBOL}_{INTERVAL}.json")
    if p.exists():
        arr = json.loads(p.read_text())
        return [Candle(int(d["t"]), d["o"], d["h"], d["l"], d["c"], d.get("v",0.0)) for d in arr]
    # Synthetic
    import random
    random.seed(7)
    price = 20.0
    out: List[Candle] = []
    for i in range(1800):
        step = random.gauss(0.0, 0.25) + (0.02 if (i//300)%2==1 else -0.02)
        new = max(0.5, price + step)
        h = max(new, price) + abs(random.gauss(0,0.12))
        l = min(new, price) - abs(random.gauss(0,0.12))
        c = new + random.gauss(0,0.05)
        out.append(Candle(i, price, h, l, c, 0.0))
        price = c
    return out

def run() -> dict:
    candles = fetch_data()
    close = [c.c for c in candles]
    high  = [c.h for c in candles]
    low   = [c.l for c in candles]

    ema_f = ema(close, EMA_FAST)
    ema_s = ema(close, EMA_SLOW)
    A     = atr(high, low, close, period=ATR_P)

    equity = EQUITY0
    peak   = EQUITY0
    max_dd = 0.0

    pos_units = 0.0
    entry = None
    stp = None
    tk  = None
    trades = []
    fees_mult = 1 - FEES_BPS/10000.0  # per fill

    for i in range(len(candles)):
        if ema_f[i] is None or ema_s[i] is None or A[i] is None:
            continue
        # Signals: simple EMA cross
        long_signal  = ema_f[i] > ema_s[i]
        flat_signal  = ema_f[i] <= ema_s[i]

        price = close[i]

        # Manage open position
        if pos_units != 0.0 and entry is not None and stp is not None and tk is not None:
            # Stop / Take checks
            hit_stop = price <= stp
            hit_take = price >= tk
            if flat_signal or hit_stop or hit_take:
                exit_px = stp if hit_stop else (tk if hit_take else price)
                pnl = (exit_px - entry) * pos_units
                # two fills (entry+exit) fees on notional
                notional_entry = abs(entry * pos_units)
                notional_exit  = abs(exit_px * pos_units)
                fee_cost = (1-fees_mult) * (notional_entry + notional_exit)
                equity += pnl - fee_cost
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity)/peak if peak>0 else 0.0)
                trades.append({"entry": entry, "exit": exit_px, "units": pos_units, "pnl": pnl - fee_cost})
                pos_units = 0.0; entry = None; stp = None; tk = None

        # Entry (long only prototype)
        if pos_units == 0.0 and long_signal:
            atr_i = A[i]
            entry = price
            units = position_size_units(equity, RISK_PCT, atr_i, entry, sl_atr_mult=SL_K)
            stops = calc_stops(entry, atr_i, side="long", sl_atr_mult=SL_K, tp_atr_mult=TP_K)
            pos_units = units
            stp, tk = stops.stop, stops.take
            # apply entry fee by reducing equity by fee on notional
            equity -= (1-fees_mult) * abs(entry * pos_units)

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity)/peak if peak>0 else 0.0)

    wins = sum(1 for t in trades if t["pnl"] > 0)
    pnl_total = equity - EQUITY0
    ret_pct = (equity/EQUITY0 - 1.0) * 100
    out = {
        "symbol": SYMBOL, "interval": INTERVAL, "n_candles": len(candles),
        "ema_fast": EMA_FAST, "ema_slow": EMA_SLOW, "atr_period": ATR_P,
        "sl_atr_mult": SL_K, "tp_atr_mult": TP_K,
        "risk_pct": RISK_PCT, "fees_bps": FEES_BPS,
        "trades": len(trades), "wins": wins, "win_rate": (wins/len(trades)*100) if trades else None,
        "equity_start": EQUITY0, "equity_end": equity,
        "pnl_total": pnl_total, "return_pct": ret_pct,
        "max_drawdown_pct": max_dd*100,
    }
    return out

if __name__ == "__main__":
    rep = run()
    Path("reports").mkdir(parents=True, exist_ok=True)
    outp = Path("reports/phase4_with_risk_summary.json")
    outp.write_text(json.dumps(rep, indent=2))
    print("Wrote", outp)
    print(json.dumps(rep, indent=2))
