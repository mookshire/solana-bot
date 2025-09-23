from __future__ import annotations
import os, json, math, csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from statistics import mean
from datetime import datetime, timezone
from risk_controls import atr, calc_stops, position_size_units

# --- Config via env ---
SYMBOL   = os.getenv("BB_SYMBOL","SOLUSDC").upper()
INTERVAL = os.getenv("BB_INTERVAL","15m")
LIMIT    = int(os.getenv("BB_LIMIT","2000"))
EMA_FAST = int(os.getenv("EMA_FAST","20"))
EMA_SLOW = int(os.getenv("EMA_SLOW","55"))
ATR_P    = int(os.getenv("ATR_PERIOD","14"))
SL_K     = float(os.getenv("SL_ATR_MULT","1.5"))
TP_K     = float(os.getenv("TP_ATR_MULT","4.0"))
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

def _ts_to_sec(t: int) -> int:
    # handle ms vs sec
    return int(t/1000) if t > 10**12 else int(t)

def iso(ts: int) -> str:
    return datetime.fromtimestamp(_ts_to_sec(ts), tz=timezone.utc).isoformat()

def fetch_data() -> List[Candle]:
    """Prefer user's fetch_klines from backtest_hybrid.py; else cached json; else synthetic."""
    try:
        from backtest_hybrid import fetch_klines
        data = fetch_klines(SYMBOL, INTERVAL, LIMIT)
        return [Candle(int(d["t"]), d["o"], d["h"], d["l"], d["c"], d.get("v",0.0)) for d in data]
    except Exception:
        pass
    p = Path(f"data/klines_{SYMBOL}_{INTERVAL}.json")
    if p.exists():
        arr = json.loads(p.read_text())
        return [Candle(int(d["t"]), d["o"], d["h"], d["l"], d["c"], d.get("v",0.0)) for d in arr]
    # Synthetic fallback
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
    entry_t: Optional[int] = None

    trades = []
    equity_curve = []  # (t, equity)

    fees_mult = 1 - FEES_BPS/10000.0  # per fill

    for i, c in enumerate(candles):
        if ema_f[i] is None or ema_s[i] is None or A[i] is None:
            equity_curve.append((c.t, equity))
            continue

        long_signal  = ema_f[i] > ema_s[i]
        flat_signal  = ema_f[i] <= ema_s[i]
        price = close[i]

        # Manage open position
        if pos_units != 0.0 and entry is not None and stp is not None and tk is not None:
            hit_stop = price <= stp
            hit_take = price >= tk
            if flat_signal or hit_stop or hit_take:
                exit_px = stp if hit_stop else (tk if hit_take else price)
                pnl = (exit_px - entry) * pos_units
                fee_cost = (1-fees_mult) * (abs(entry * pos_units) + abs(exit_px * pos_units))
                equity += pnl - fee_cost
                reason = "stop" if hit_stop else ("take" if hit_take else "flat")
                trades.append({
                    "entry_time": iso(entry_t), "exit_time": iso(c.t),
                    "entry": entry, "exit": exit_px, "units": pos_units,
                    "reason": reason, "pnl": pnl - fee_cost
                })
                pos_units = 0.0; entry = None; stp = None; tk = None; entry_t = None

        # Entry (long-only prototype)
        if pos_units == 0.0 and long_signal:
            atr_i = A[i]
            entry = price
            entry_t = c.t
            units = position_size_units(equity, RISK_PCT, atr_i, entry, sl_atr_mult=SL_K)
            stops = calc_stops(entry, atr_i, side="long", sl_atr_mult=SL_K, tp_atr_mult=TP_K)
            pos_units = units
            stp, tk = stops.stop, stops.take
            equity -= (1-fees_mult) * abs(entry * pos_units)

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity)/peak if peak>0 else 0.0)
        equity_curve.append((c.t, equity))

    wins = sum(1 for t in trades if t["pnl"] > 0)
    pnl_total = equity - EQUITY0
    ret_pct = (equity/EQUITY0 - 1.0) * 100

    # --- Write detailed artifacts ---
    reports = Path("reports"); reports.mkdir(parents=True, exist_ok=True)

    # trades.csv
    with (reports / "phase4_trades.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["entry_time","exit_time","entry","exit","units","reason","pnl"])
        w.writeheader(); w.writerows(trades)

    # equity_curve.csv
    with (reports / "phase4_equity_curve.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["time","equity"])
        for t,e in equity_curve: w.writerow([iso(t), f"{e:.6f}"])

    # monthly summary from equity curve
    monthly = {}
    for t,e in equity_curve:
        key = datetime.fromtimestamp(_ts_to_sec(t), tz=timezone.utc).strftime("%Y-%m")
        if key not in monthly: monthly[key] = {"first": e, "last": e}
        else: monthly[key]["last"] = e
    monthly_rows = []
    for m, v in sorted(monthly.items()):
        start, end = v["first"], v["last"]
        r = (end/start - 1.0) * 100 if start>0 else 0.0
        monthly_rows.append({"month": m, "return_pct": r})
    with (reports / "phase4_monthly_risk.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["month","return_pct"])
        w.writeheader(); w.writerows(monthly_rows)

    out = {
        "symbol": SYMBOL, "interval": INTERVAL, "n_candles": len(candles),
        "ema_fast": EMA_FAST, "ema_slow": EMA_SLOW, "atr_period": ATR_P,
        "sl_atr_mult": SL_K, "tp_atr_mult": TP_K,
        "risk_pct": RISK_PCT, "fees_bps": FEES_BPS,
        "trades": len(trades), "wins": wins, "win_rate": (wins/len(trades)*100) if trades else None,
        "equity_start": EQUITY0, "equity_end": equity,
        "pnl_total": pnl_total, "return_pct": ret_pct,
        "max_drawdown_pct": max_dd*100,
        "artifacts": {
            "trades_csv": "reports/phase4_trades.csv",
            "equity_curve_csv": "reports/phase4_equity_curve.csv",
            "monthly_csv": "reports/phase4_monthly_risk.csv",
        }
    }
    Path("reports").mkdir(parents=True, exist_ok=True)
    outp = Path("reports/phase4_with_risk_summary.json")
    outp.write_text(json.dumps(out, indent=2))
    print("Wrote", outp)
    print(json.dumps(out, indent=2))
    return out
