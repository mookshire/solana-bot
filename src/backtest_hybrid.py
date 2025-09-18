from __future__ import annotations
import os, json, requests
import pandas as pd
import numpy as np
from typing import List, Dict, Any

SYMBOL = os.getenv("BB_SYMBOL", "SOLUSDT").upper()
INTERVAL = os.getenv("BB_INTERVAL", os.getenv("HY_INTERVAL", "15m"))
REQ_LIMIT = int(float(os.getenv("BB_LIMIT", os.getenv("HY_LIMIT", "1000"))))
LIMIT = max(200, min(REQ_LIMIT, 1000))

BB_PERIOD = int(float(os.getenv("BB_PERIOD", "20")))
BB_K = float(os.getenv("BB_K", "2.0"))

RSI_PERIOD = int(float(os.getenv("RSI_PERIOD", "14")))
RSI_BUY_MAX = float(os.getenv("RSI_BUY_MAX", "35"))
RSI_SELL_MIN = float(os.getenv("RSI_SELL_MIN", "65"))

ATR_PERIOD = int(float(os.getenv("ATR_PERIOD", "14")))
ATR_STOP_MULT = float(os.getenv("ATR_STOP_MULT", "1.5"))
ATR_TP_MULT = float(os.getenv("ATR_TP_MULT", "2.0"))

COOLDOWN_BARS = int(float(os.getenv("BB_COOLDOWN_BARS", "1")))
FEE_BPS = float(os.getenv("BB_FEE_BPS", "12.5"))
SLIP_BPS = float(os.getenv("BB_SLP_BPS", "12.5"))
COST_BPS_PER_SIDE = (FEE_BPS + SLIP_BPS) / 10_000.0

# NEW: volume + trend filters
VOL_MA_N = int(float(os.getenv("VOL_MA_N", "50")))
VOL_MULT = float(os.getenv("VOL_MULT", "1.3"))
EMA_TREND_N = int(float(os.getenv("EMA_TREND_N", "200")))
REQUIRE_TREND = int(float(os.getenv("REQUIRE_TREND", "1")))  # 1=enforce, 0=ignore

SESSION = requests.Session()

def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = SESSION.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    cols = ["open_time","open","high","low","close","volume",
            "close_time","qav","num_trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(data, columns=cols)
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    return df[["open_time","open","high","low","close","volume","close_time"]].reset_index(drop=True)

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def rsi(series: pd.Series, n: int) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).ewm(alpha=1/n, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/n, adjust=False).mean()
    rs = gain / (loss.replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)

def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def bollinger(close: pd.Series, period: int, k: float):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    return mid, upper, lower

def max_drawdown(equity_curve: List[float]) -> float:
    peak = -1e9
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd

def run_backtest() -> Dict[str, Any]:
    df = fetch_klines(SYMBOL, INTERVAL, LIMIT)
    close = df["close"]; high = df["high"]; low = df["low"]; vol = df["volume"]

    mid, upper, lower = bollinger(close, BB_PERIOD, BB_K)
    r = rsi(close, RSI_PERIOD)
    a = atr(high, low, close, ATR_PERIOD)
    ema_trend = ema(close, EMA_TREND_N)
    ema_trend_prev = ema_trend.shift(1)
    vol_ma = vol.rolling(VOL_MA_N).mean()

    df["bb_mid"] = mid; df["bb_up"] = upper; df["bb_lo"] = lower
    df["rsi"] = r; df["atr"] = a
    df["ema_trend"] = ema_trend; df["vol_ma"] = vol_ma

    start = max(BB_PERIOD, RSI_PERIOD, ATR_PERIOD, EMA_TREND_N, VOL_MA_N) + 2
    in_pos = False
    entry_price = entry_idx = None
    stop_lvl = tp_lvl = None
    cooldown = 0

    trades = []; equity = 1.0; eq_curve = [equity]

    for i in range(start, len(df)):
        c_prev, c = close.iloc[i-1], close.iloc[i]
        up_prev, up = upper.iloc[i-1], upper.iloc[i]
        lo_prev, lo = lower.iloc[i-1], lower.iloc[i]
        r_now = r.iloc[i]; a_now = a.iloc[i]
        v_now = vol.iloc[i]; v_avg = vol_ma.iloc[i]
        ema_now, ema_prev = ema_trend.iloc[i], ema_trend_prev.iloc[i]

        if not in_pos:
            if cooldown > 0:
                cooldown -= 1
            else:
                entry_cross = (c_prev < lo_prev) and (c > lo)
                rsi_gate = (r_now <= RSI_BUY_MAX)
                vol_gate = (v_now > v_avg * VOL_MULT) if not np.isnan(v_avg) else False
                trend_gate = True
                if REQUIRE_TREND:
                    trend_gate = (c > ema_now) and (ema_now > ema_prev)
                if entry_cross and rsi_gate and vol_gate and trend_gate:
                    in_pos = True
                    entry_price = c * (1.0 + COST_BPS_PER_SIDE)
                    entry_idx = i
                    stop_lvl = c - ATR_STOP_MULT * a_now
                    tp_lvl = c + ATR_TP_MULT * a_now
        else:
            exit_reason = None; should_exit = False
            if c <= stop_lvl:
                exit_reason = "STOP_ATR"; should_exit = True
            elif c >= tp_lvl:
                exit_reason = "TAKE_PROFIT_ATR"; should_exit = True
            elif r_now >= RSI_SELL_MIN:
                exit_reason = "RSI_EXIT"; should_exit = True
            elif (c_prev > up_prev) and (c < up):
                exit_reason = "BB_UP_CROSSDOWN"; should_exit = True

            if should_exit:
                exit_price = c * (1.0 - COST_BPS_PER_SIDE)
                ret = (exit_price - entry_price) / entry_price
                trades.append({"entry_i": int(entry_idx), "exit_i": int(i), "ret": float(ret), "reason": exit_reason})
                equity *= (1.0 + ret); eq_curve.append(equity)
                in_pos = False; entry_price = entry_idx = stop_lvl = tp_lvl = None
                cooldown = COOLDOWN_BARS

        if not trades or (trades and trades[-1]["exit_i"] != i):
            eq_curve.append(equity)

    open_ret = None
    if in_pos and entry_price is not None:
        last_c = close.iloc[-1] * (1.0 - COST_BPS_PER_SIDE)
        open_ret = (last_c - entry_price) / entry_price

    wins = sum(1 for t in trades if t["ret"] > 0)
    losses = sum(1 for t in trades if t["ret"] <= 0)
    avg_ret = float(np.mean([t["ret"] for t in trades])) if trades else 0.0
    mdd = max_drawdown(eq_curve)

    return {
        "symbol": SYMBOL, "interval": INTERVAL,
        "bb_period": BB_PERIOD, "bb_k": BB_K,
        "rsi_period": RSI_PERIOD, "atr_period": ATR_PERIOD,
        "rsi_buy_max": RSI_BUY_MAX, "rsi_sell_min": RSI_SELL_MIN,
        "atr_stop_mult": ATR_STOP_MULT, "atr_tp_mult": ATR_TP_MULT,
        "fee_bps_per_side": FEE_BPS, "slip_bps_per_side": SLIP_BPS,
        "vol_ma_n": VOL_MA_N, "vol_mult": VOL_MULT,
        "ema_trend_n": EMA_TREND_N, "require_trend": REQUIRE_TREND,
        "bars": int(len(df)), "trades": int(len(trades)),
        "wins": int(wins), "losses": int(losses),
        "win_rate_pct": round(100.0 * wins / max(1, len(trades)), 2),
        "avg_trade_ret_pct": round(100.0 * avg_ret, 4),
        "equity_multiple": round(float(eq_curve[-1]), 6) if eq_curve else 1.0,
        "max_drawdown_pct": round(100.0 * mdd, 2),
        "open_position_ret_pct": round(100.0 * open_ret, 4) if open_ret is not None else None,
        "note": "LIMIT clamped to 1000 on Binance public API" if REQ_LIMIT > 1000 else ""
    }





# === EMA CROSS STRAT (added) ===
def run_backtest_ema():
    """
    Long-only EMA crossover with RSI confirmation.
    Entries:  EMA_FAST crosses above EMA_SLOW AND RSI <= RSI_BUY_MAX
    Exits:    EMA_FAST crosses below EMA_SLOW OR  RSI >= RSI_SELL_MIN
    Costs:    FEE_BPS + SLIP_BPS (bps per side)
    """
    import os, numpy as np
    try:
        df = fetch_klines(os.getenv("BB_SYMBOL","SOLUSDT").upper(),
                          os.getenv("BB_INTERVAL","15m"),
                          int(os.getenv("BB_LIMIT","5000")))
    except Exception as e:
        return {"error":"fetch_failed","msg":str(e)}

    # Pull columns (expects a DataFrame-like)
    close = df["close"]; high = df["high"]; low = df["low"]; vol = df["volume"]

    # Params (env-tunable)
    FAST = int(os.getenv("EMA_FAST_N","9"))
    SLOW = int(os.getenv("EMA_SLOW_N","21"))
    RSI_N = int(os.getenv("RSI_PERIOD","14"))
    RSI_BUY_MAX = float(os.getenv("RSI_BUY_MAX","60"))
    RSI_SELL_MIN = float(os.getenv("RSI_SELL_MIN","60"))

    # Costs (per side in bps)
    FEE_BPS = float(os.getenv("FEE_BPS","12.5"))
    SLIP_BPS = float(os.getenv("SLIP_BPS","12.5"))
    COST_PER_SIDE = (FEE_BPS + SLIP_BPS)/10000.0

    fast = ema(close, FAST)
    slow = ema(close, SLOW)
    r = rsi(close, RSI_N)

    pos = False
    entry_price = None
    trades = []
    eq_curve = [1.0]
    equity = 1.0

    # iterate with lookahead exit/entry on next bar close
    start = max(FAST, SLOW, RSI_N) + 1
    for i in range(start, len(close)-1):
        cross_up   = fast[i-1] <= slow[i-1] and fast[i] > slow[i]
        cross_down = fast[i-1] >= slow[i-1] and fast[i] < slow[i]

        if not pos:
            if cross_up and r[i] <= RSI_BUY_MAX:
                entry_price = float(close[i+1])
                entry_price *= (1.0 + COST_PER_SIDE)  # pay costs entering
                pos = True
        else:
            should_exit = cross_down or r[i] >= RSI_SELL_MIN
            if should_exit:
                exit_price = float(close[i+1]) * (1.0 - COST_PER_SIDE)
                ret = (exit_price - entry_price) / entry_price
                trades.append({"i":i, "ret":ret})
                equity *= (1.0 + ret)
                eq_curve.append(equity)
                pos = False
                entry_price = None

    # close any open position at last bar
    if pos and entry_price is not None:
        exit_price = float(close.iloc[-1]) * (1.0 - COST_PER_SIDE)
        ret = (exit_price - entry_price) / entry_price
        trades.append({"i":len(close)-1, "ret":ret})
        equity *= (1.0 + ret)
        eq_curve.append(equity)

    wins = sum(1 for t in trades if t["ret"] > 0)
    losses = sum(1 for t in trades if t["ret"] <= 0)

    return {
        "trades": len(trades),
        "wins": int(wins),
        "losses": int(losses),
        "win_rate_pct": round(100.0 * wins / max(1,len(trades)), 2),
        "equity_multiple": round(float(eq_curve[-1]), 6),
        "max_drawdown_pct": round(100.0 * max_drawdown(eq_curve), 2),
        "avg_trade_ret_pct": round(100.0 * (np.mean([t["ret"] for t in trades]) if trades else 0.0), 4),
    }
# === /EMA CROSS STRAT ===
# === AUTO-MAIN PATCH (do not edit) ===
def _auto_find_entry():
    import inspect
    g = globals()
    preferred = ["run_backtest","backtest","simulate","run","hybrid_backtest","main_backtest"]
    def argcount(fn):
        try:
            sig = inspect.signature(fn)
            return sum(1 for p in sig.parameters.values()
                       if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                       and p.default is p.empty)
        except Exception:
            return 99
    for name in preferred:
        fn = g.get(name)
        if callable(fn):
            ac = argcount(fn)
            if ac in (0,1):
                return fn, name, ac
    return None, None, None

def _to_dataframe(data):
    import pandas as pd
    if hasattr(data, "columns"): 
        return data
    if isinstance(data, list) and data and isinstance(data[0], (list,tuple)):
        return pd.DataFrame({
            "time":   [r[0] for r in data],
            "open":   [float(r[1]) for r in data],
            "high":   [float(r[2]) for r in data],
            "low":    [float(r[3]) for r in data],
            "close":  [float(r[4]) for r in data],
            "volume": [float(r[5]) for r in data],
        })
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return pd.DataFrame(data)
    if isinstance(data, dict):
        return pd.DataFrame(data)
    return data

if __name__ == "__main__":
    import os, json
    from pathlib import Path
    try:
        from src.price_sources import fetch_klines as _orig_fetch_klines
    except Exception:
        try:
            from .price_sources import fetch_klines as _orig_fetch_klines
        except Exception:
            _orig_fetch_klines = None

    SYMBOL   = os.getenv("BB_SYMBOL","SOLUSDT").upper()
    INTERVAL = os.getenv("BB_INTERVAL","4h")
    LIMIT    = int(os.getenv("BB_LIMIT","5000"))

    data = None
    df = os.getenv("DATA_FILE")
    if df and Path(df).exists():
        data = json.loads(Path(df).read_text(encoding="utf-8", errors="ignore"))
    if data is None:
        cached = Path(f"data/{SYMBOL}_{INTERVAL}_{LIMIT}.json")
        if cached.exists():
            data = json.loads(cached.read_text(encoding="utf-8", errors="ignore"))
    if data is None:
        if _orig_fetch_klines is None:
            print(json.dumps({"error":"no data and fetch_klines unavailable"}))
            raise SystemExit(2)
        data = _orig_fetch_klines(SYMBOL, INTERVAL, LIMIT)
        Path("data").mkdir(parents=True, exist_ok=True)
        Path(f"data/{SYMBOL}_{INTERVAL}_{LIMIT}.json").write_text(json.dumps(data), encoding="utf-8")

    # find entry
    entry_override = os.getenv('RUN_ENTRY')
    if entry_override and entry_override in globals() and callable(globals()[entry_override]):
        _fn = globals()[entry_override]
        import inspect
        try:
            _ac = sum(1 for p in inspect.signature(_fn).parameters.values()
                       if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty)
        except Exception:
            _ac = 0
        fn, name, ac = _fn, entry_override, _ac
    else:
        fn, name, ac = _auto_find_entry()
    if fn is None:
        print(json.dumps({"error":"no entry function found"})); raise SystemExit(3)

    # If entry has 0 args, monkey-patch fetch_klines to return our DataFrame
    if ac == 0:
        import sys as _sys
        import types as _types
        normed_df = _to_dataframe(data)

        def _patched_fetch(*_a, **_k):
            return normed_df

        # replace in this module's globals (used by run_backtest/backtest)
        globals()['fetch_klines'] = _patched_fetch
        # also try to replace symbol imported at top if any alias exists
        if '_orig_fetch_klines' in globals():
            globals()['_orig_fetch_klines'] = _patched_fetch

    try:
        res = fn(_to_dataframe(data)) if ac == 1 else fn()
    except Exception as e:
        print(json.dumps({"error":"entry function raised", "func":name, "type":type(e).__name__, "msg":str(e)}))
        raise

    def _pick(d, keys): return {k:d[k] for k in keys if k in d}
    out = {"entry_func": name}
    if isinstance(res, dict):
        out.update(_pick(res, [
            "equity_multiple","equity","win_rate_pct","win_rate",
            "trades","wins","losses","max_drawdown_pct","profit_factor",
            "avg_trade_ret_pct","cagr_pct","sharpe","last_signal","last_price","last_time"
        ]) or res)
    else:
        out["result"] = str(res)
    print(json.dumps(out, separators=(",",":")))
# === AUTO-MAIN PATCH (do not edit) ===








# === KC_ATR STRAT (do not edit) ===
def run_kc_atr(data=None):
    """
    Keltner-channel breakout (long-only) with ATR stop & ATR take-profit.
    Uses existing helpers: ema(), atr(). Expects a DataFrame-like input.
    Tunables via env:
      KC_N (20), KC_MULT (1.8), EMA_FAST_N (9), EMA_SLOW_N (21),
      ATR_PERIOD (14), ATR_STOP_MULT (1.5), ATR_TP_MULT (2.5)
    Costs: FEE_BPS, SLIP_BPS (or COST_BPS_PER_SIDE/COST_PER_SIDE if present)
    """
    import os, numpy as np

    if data is None:
        data = fetch_klines(os.getenv("BB_SYMBOL","SOLUSDT"), os.getenv("BB_INTERVAL","15m"), int(os.getenv("BB_LIMIT","5000")))

    df = data.copy()
    close = df["close"]; high = df["high"]; low = df["low"]

    KC_N        = int(os.getenv("KC_N", "20"))
    KC_MULT     = float(os.getenv("KC_MULT", "1.8"))
    FAST        = int(os.getenv("EMA_FAST_N", "9"))
    SLOW        = int(os.getenv("EMA_SLOW_N", "21"))
    ATR_N       = int(os.getenv("ATR_PERIOD", "14"))
    ATR_STOP_M  = float(os.getenv("ATR_STOP_MULT", "1.5"))
    ATR_TP_M    = float(os.getenv("ATR_TP_MULT", "2.5"))

    # costs
    fee_bps  = float(globals().get("FEE_BPS", 12.5))
    slip_bps = float(globals().get("SLIP_BPS", 12.5))
    cps = globals().get("COST_PER_SIDE", None)
    if cps is None:
        cps = (fee_bps + slip_bps)/10000.0

    basis = ema(close, KC_N)
    a = atr(high, low, close, ATR_N)
    upper = basis + KC_MULT * a
    lower = basis - KC_MULT * a

    fast = ema(close, FAST)
    slow = ema(close, SLOW)

    trades = []
    eq_curve = [1.0]
    pos = False
    entry = None

    start = max(KC_N, ATR_N, SLOW) + 1
    for i in range(start, len(close)):
        prev_c, c = close[i-1], close[i]
        up, lo, bs = upper[i], lower[i], basis[i]
        atrv = a[i]

        if not pos:
            # breakout + trend filter
            if prev_c <= up and c > up and fast[i] > slow[i]:
                entry = c * (1.0 + cps)  # pay entry costs
                pos = True
        else:
            stop = entry - ATR_STOP_M * atrv
            tp   = entry + ATR_TP_M * atrv
            should_exit = (c <= stop) or (c >= tp) or (c < bs)
            if should_exit:
                exit_px = c * (1.0 - cps)  # pay exit costs
                ret = (exit_px - entry) / entry
                trades.append({"ret": float(ret)})
                eq_curve.append(eq_curve[-1] * (1.0 + ret))
                pos = False
                entry = None

    # if an open trade remains, mark its open return (not equity)
    open_ret = None
    if pos and entry is not None:
        open_ret = (close.iloc[-1] * (1.0 - cps) - entry) / entry

    wins = sum(1 for t in trades if t["ret"] > 0)
    losses = sum(1 for t in trades if t["ret"] <= 0)
    avg_ret = float(np.mean([t["ret"] for t in trades])) if trades else 0.0
    mdd = max_drawdown(eq_curve)

    return {
        "symbol": os.getenv("BB_SYMBOL","SOLUSDT"),
        "interval": os.getenv("BB_INTERVAL","15m"),
        "kc_n": KC_N, "kc_mult": KC_MULT,
        "ema_fast_n": FAST, "ema_slow_n": SLOW,
        "atr_n": ATR_N, "atr_stop_mult": ATR_STOP_M, "atr_tp_mult": ATR_TP_M,
        "fee_bps": fee_bps, "slip_bps": slip_bps,
        "bars": int(len(df)), "trades": int(len(trades)),
        "wins": int(wins), "losses": int(losses),
        "win_rate_pct": round(100.0 * wins / max(1, len(trades)), 2),
        "avg_trade_ret_pct": round(100.0 * avg_ret, 4),
        "equity_multiple": round(float(eq_curve[-1]), 6),
        "max_drawdown_pct": round(100.0 * mdd, 2),
        "open_position_ret_pct": round(100.0 * open_ret, 4) if open_ret is not None else None
    }



# === TV Bollinger Bands (mean reversion) ===
def run_bb_tv(data=None):
    """
    TradingView-style Bollinger Bands mean-reversion:
      - Entry long when close crosses below lower BB
      - Exit when close crosses above middle (SMA) band
    Params via env:
      BB_PERIOD (20), BB_K (2.0), FEE_BPS (5), SLIP_BPS (5)
      COST_BPS_PER_SIDE or COST_PER_SIDE (optional)
    Expects a DataFrame-like input with columns: open, high, low, close, volume.
    """
    import os, math, json
    import numpy as np, pandas as pd

    def _to_df(d):
        if isinstance(d, pd.DataFrame): 
            return d.copy()
        if isinstance(d, list) and d and isinstance(d[0], (list,tuple)) and len(d[0])>=6:
            return pd.DataFrame({
                "time":[r[0] for r in d],
                "open":[float(r[1]) for r in d],
                "high":[float(r[2]) for r in d],
                "low" :[float(r[3]) for r in d],
                "close":[float(r[4]) for r in d],
                "volume":[float(r[5]) for r in d],
            })
        if isinstance(d, list) and d and isinstance(d[0], dict):
            df = pd.DataFrame(d)
            cols = {k.lower():k for k in df.columns}
            need = ["open","high","low","close","volume"]
            if all(c in cols for c in need):
                return df.rename(columns={cols[c]:c for c in need})
        return pd.DataFrame(d)

    # read params
    BB_PERIOD = int(os.getenv("BB_PERIOD","20"))
    BB_K      = float(os.getenv("BB_K","2.0"))
    FEE_BPS   = float(os.getenv("FEE_BPS","5.0"))
    SLIP_BPS  = float(os.getenv("SLIP_BPS","5.0"))
    cps_env   = os.getenv("COST_PER_SIDE")
    cbps_env  = os.getenv("COST_BPS_PER_SIDE")

    # cost per SIDE (entry OR exit)
    if cps_env is not None:
        COST_PER_SIDE = float(cps_env)
    else:
        base_bps = FEE_BPS + SLIP_BPS + (float(cbps_env) if cbps_env else 0.0)
        COST_PER_SIDE = base_bps/10000.0

    # get data (offline if provided by launcher)
    if data is None:
        try:
            df = _to_df(fetch_klines(BB_SYMBOL, BB_INTERVAL, BB_LIMIT))  # module globals if present
        except Exception:
            return {"error":"no_data"}
    else:
        df = _to_df(data)

    if len(df) < BB_PERIOD + 5:
        return {"error":"not_enough_bars","bars":int(len(df))}

    close = df["close"].astype(float)
    mid = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std(ddof=0)  # population std (TV typically sample; close enough)
    upper = mid + BB_K*std
    lower = mid - BB_K*std

    eq = 1.0
    eq_curve = [eq]
    pos = False
    entry = None
    trades = []

    start = BB_PERIOD + 1
    for i in range(start, len(df)-1):
        c_prev, c_now = close.iloc[i-1], close.iloc[i]
        lo_prev, lo_now = lower.iloc[i-1], lower.iloc[i]
        mid_prev, mid_now = mid.iloc[i-1], mid.iloc[i]

        if not pos:
            # cross UNDER lower band -> buy at next bar open proxy (use next close for simplicity)
            if c_prev >= lo_prev and c_now < lo_now and not math.isnan(lo_now):
                entry = float(close.iloc[i+1]) * (1.0 + COST_PER_SIDE)
                pos = True
        else:
            # cross ABOVE middle band -> exit at next bar
            if c_prev <= mid_prev and c_now > mid_now and not math.isnan(mid_now):
                exit_price = float(close.iloc[i+1]) * (1.0 - COST_PER_SIDE)
                ret = (exit_price - entry) / entry
                trades.append({"i":i, "ret":float(ret)})
                eq *= (1.0 + ret)
                eq_curve.append(eq)
                pos = False
                entry = None

    # if still open, mark-to-market
    open_ret = None
    if pos and entry is not None:
        last = float(close.iloc[-1]) * (1.0 - COST_PER_SIDE)
        open_ret = (last - entry) / entry
        eq *= (1.0 + open_ret)
        eq_curve.append(eq)

    wins = sum(1 for t in trades if t["ret"]>0)
    losses = sum(1 for t in trades if t["ret"]<=0)
    avg_ret = float(np.mean([t["ret"] for t in trades])) if trades else 0.0

    # max drawdown of equity curve
    mdd = 0.0
    peak = eq_curve[0] if eq_curve else 1.0
    for x in eq_curve:
        peak = max(peak, x)
        mdd = max(mdd, (peak - x)/peak if peak else 0.0)

    pf_num = sum(t["ret"] for t in trades if t["ret"]>0)
    pf_den = -sum(t["ret"] for t in trades if t["ret"]<=0)
    profit_factor = float(pf_num/pf_den) if pf_den>0 else None

    return {
        "symbol": BB_SYMBOL if "BB_SYMBOL" in globals() else "SOLUSDT",
        "interval": BB_INTERVAL if "BB_INTERVAL" in globals() else "15m",
        "bb_period": BB_PERIOD, "bb_k": BB_K,
        "trades": int(len(trades)), "wins": int(wins), "losses": int(losses),
        "win_rate_pct": round(100.0*wins/max(1,len(trades)),2),
        "avg_trade_ret_pct": round(100.0*avg_ret, 4),
        "equity_multiple": round(float(eq_curve[-1]) if eq_curve else 1.0, 6),
        "max_drawdown_pct": round(100.0*mdd, 2),
        "open_position_ret_pct": round(100.0*open_ret, 4) if open_ret is not None else None,
        "note": "TV-style BB mean reversion"
    }

