from __future__ import annotations
import os, json
from pathlib import Path
import pandas as pd, numpy as np

# use the same loader other modules use (absolute import since we run with -m src.*)
from src.price_sources import fetch_klines

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    d = series.diff()
    up = np.where(d>0, d, 0.0)
    dn = np.where(d<0, -d, 0.0)
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1/n, adjust=False).mean()
    roll_dn = pd.Series(dn, index=series.index).ewm(alpha=1/n, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
    return 100 - (100/(1+rs))

def stoch_kd(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14, d: int = 3):
    ll = l.rolling(n).min()
    hh = h.rolling(n).max()
    k = (c - ll) / (hh - ll + 1e-12) * 100.0
    dline = k.rolling(d).mean()
    return k, dline

def bbands(c: pd.Series, p: int = 20, k: float = 2.0):
    ma = c.rolling(p).mean()
    sd = c.rolling(p).std(ddof=0)
    return ma, ma + k*sd, ma - k*sd

def run() -> dict:
    sym   = os.getenv("BB_SYMBOL","SOLUSDT").upper()
    tint  = os.getenv("BB_INTERVAL","15m")
    tlim  = int(os.getenv("BB_LIMIT","5000"))

    fee_bps = float(os.getenv("BB_FEE_BPS","5"))
    slp_bps = float(os.getenv("BB_SLP_BPS","5"))
    cost_per_side = (fee_bps + slp_bps)/1e4

    # indicator params
    EMA_FAST  = int(os.getenv("EMA_FAST","50"))
    EMA_SLOW  = int(os.getenv("EMA_SLOW","200"))
    RSI_N     = int(os.getenv("RSI_N","14"))
    MACD_FAST = int(os.getenv("MACD_FAST","12"))
    MACD_SLOW = int(os.getenv("MACD_SLOW","26"))
    MACD_SIG  = int(os.getenv("MACD_SIG","9"))
    STOCH_N   = int(os.getenv("STOCH_N","14"))
    STOCH_D   = int(os.getenv("STOCH_D","3"))
    BB_P      = int(os.getenv("BB_PERIOD","20"))
    BB_K      = float(os.getenv("BB_K","2.0"))

    # thresholds & confirmations
    RSI_BUY_LT   = float(os.getenv("RSI_BUY_LT","35"))
    RSI_SELL_GT  = float(os.getenv("RSI_SELL_GT","65"))
    # RSI hard gates to avoid exhaustion-chasing
    RSI_SKIP_BUY_GT  = float(os.getenv("RSI_SKIP_BUY_GT","75"))
    RSI_SKIP_SELL_LT = float(os.getenv("RSI_SKIP_SELL_LT","25"))

    ST_BUY_MAX  = float(os.getenv("ST_BUY_MAX","20"))
    ST_SELL_MIN = float(os.getenv("ST_SELL_MIN","80"))
    CONFIRM_BUY = int(os.getenv("CONFIRM_BUY_N","2"))
    CONFIRM_SELL= int(os.getenv("CONFIRM_SELL_N","2"))
    VBUY_X      = float(os.getenv("VOL_BUY_X","0.90"))
    VSELL_X     = float(os.getenv("VOL_SELL_X","1.30"))
    BULL_ONLY   = int(os.getenv("BULL_ONLY","1"))
    COOLDOWN_BARS = int(os.getenv("COOLDOWN_BARS","2"))

    # trailing stop
    TRAIL_ARM_PCT  = float(os.getenv("TRAIL_ARM_PCT","0.02"))  # arm after +2%
    TRAIL_DROP_PCT = float(os.getenv("TRAIL_DROP_PCT","0.01")) # exit if -1% from peak while armed

    import pandas as pd; df = pd.DataFrame(fetch_klines(sym, tint, tlim)).copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True); df = df.set_index("time")

    c = df["close"].astype(float); h = df["high"].astype(float); l = df["low"].astype(float); v = df["volume"].astype(float)

    df["ema_fast"] = ema(c, EMA_FAST); df["ema_slow"] = ema(c, EMA_SLOW)
    df["rsi"] = rsi(c, RSI_N)
    macd_fast = ema(c, MACD_FAST); macd_slow = ema(c, MACD_SLOW)
    df["macd"] = macd_fast - macd_slow
    df["macd_sig"] = ema(df["macd"], MACD_SIG)
    df["st_k"], df["st_d"] = stoch_kd(h, l, c, STOCH_N, STOCH_D)
    df["bb_ma"], df["bb_up"], df["bb_lo"] = bbands(c, BB_P, BB_K)
    df["vol_sma20"] = v.rolling(20).mean()

    start_i = max(BB_P, EMA_SLOW, RSI_N, STOCH_N+STOCH_D, MACD_SLOW+MACD_SIG) + 5
    idx = df.index

    trades = []; equity = 1.0
    open_pos = None
    cooldown = 0

    for i in range(start_i, len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]

        # Cooldown handling
        if cooldown>0: cooldown -= 1

        # Trend gate
        uptrend = row["ema_fast"] > row["ema_slow"]
        downtrend = row["ema_fast"] < row["ema_slow"]

        # confirmations
        conf_buy = 0; conf_sell = 0
        reasons_buy = []; reasons_sell = []

        if uptrend:    conf_buy += 1;  reasons_buy.append("ema_fast>ema_slow")
        if downtrend:  conf_sell += 1; reasons_sell.append("ema_fast<ema_slow")

        if row["close"] < row["bb_lo"]:
            conf_buy += 1; reasons_buy.append("close<BB_low")
        if row["close"] > row["bb_up"]:
            conf_sell += 1; reasons_sell.append("close>BB_up")

        if row["rsi"] < RSI_BUY_LT:
            conf_buy += 1; reasons_buy.append(f"rsi<{RSI_BUY_LT}")
        if row["rsi"] > RSI_SELL_GT:
            conf_sell += 1; reasons_sell.append(f"rsi>{RSI_SELL_GT}")

        macd_bull = (row["macd"] > row["macd_sig"]) and (prev["macd"] <= prev["macd_sig"])
        macd_bear = (row["macd"] < row["macd_sig"]) and (prev["macd"] >= prev["macd_sig"])
        if macd_bull: conf_buy += 1;  reasons_buy.append("macd_cross_up")
        if macd_bear: conf_sell += 1; reasons_sell.append("macd_cross_dn")

        st_buy = (row["st_k"] > row["st_d"]) and (prev["st_k"] <= prev["st_d"]) and (row["st_k"] < ST_BUY_MAX)
        st_sell= (row["st_k"] < row["st_d"]) and (prev["st_k"] >= prev["st_d"]) and (row["st_k"] > ST_SELL_MIN)
        if st_buy:  conf_buy += 1;  reasons_buy.append("stoch_cross_up")
        if st_sell: conf_sell += 1; reasons_sell.append("stoch_cross_dn")

        vol_ok_buy  = row["volume"] > VBUY_X  * row["vol_sma20"]
        vol_ok_sell = row["volume"] > VSELL_X * row["vol_sma20"]

        # RSI exhaustion gates
        if row["rsi"] > RSI_SKIP_BUY_GT:   vol_ok_buy = False
        if row["rsi"] < RSI_SKIP_SELL_LT:  vol_ok_sell = False

        buy_gate  = uptrend if BULL_ONLY else True
        sell_gate = True  # always allow taking profit

        do_buy  = (cooldown==0) and (open_pos is None) and buy_gate and vol_ok_buy  and (conf_buy  >= CONFIRM_BUY)
        do_sell = (open_pos is not None) and sell_gate and vol_ok_sell and (conf_sell >= CONFIRM_SELL)

        # trailing stop logic (only when position open)
        trail_hit = False
        if open_pos is not None:
            px = float(row["close"])
            # update peak
            if px > open_pos["peak"]: open_pos["peak"] = px
            # arm after profit threshold
            if (not open_pos["armed"]) and (px >= open_pos["entry"] * (1.0 + TRAIL_ARM_PCT)):
                open_pos["armed"] = True
            # drop from peak triggers exit
            if open_pos["armed"] and (px <= open_pos["peak"] * (1.0 - TRAIL_DROP_PCT)):
                trail_hit = True
                reasons_sell.append("trailing_stop")

        if do_buy:
            open_pos = {"entry": float(row["close"]), "t": str(idx[i]),
                        "peak": float(row["close"]), "armed": False,
                        "buy_reasons": ";".join(reasons_buy)}
            cooldown = COOLDOWN_BARS
        elif (do_sell or trail_hit):
            bp = open_pos["entry"]; sp = float(row["close"])
            gross = (sp/bp) - 1.0
            net = gross - 2*cost_per_side
            equity *= (1.0 + net)
            trades.append({
                "buy_time": open_pos["t"], "buy_px": round(bp,6),
                "sell_time": str(idx[i]),   "sell_px": round(sp,6),
                "gross_ret_pct": round(gross*100,4), "net_ret_pct": round(net*100,4),
                "equity_mult_after": round(equity,6),
                "buy_reasons": open_pos["buy_reasons"],
                "sell_reasons": ";".join(reasons_sell) if not trail_hit else "trailing_stop",
            })
            open_pos = None
            cooldown = COOLDOWN_BARS

    wins = sum(1 for t in trades if t["net_ret_pct"] > 0)
    losses = len(trades) - wins
    wr = (wins/len(trades)*100.0) if trades else 0.0

    out = Path("data/backtests"); out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades).to_csv(out/"eclectic_trades.csv", index=False)
    summary = {
        "symbol": sym, "interval": tint, "bars": tlim,
        "EMA": [EMA_FAST, EMA_SLOW], "RSI_N": RSI_N,
        "MACD": [MACD_FAST, MACD_SLOW, MACD_SIG], "STOCH": [STOCH_N, STOCH_D],
        "BB": [BB_P, BB_K], "VOL": [VBUY_X, VSELL_X],
        "CONFIRM": [CONFIRM_BUY, CONFIRM_SELL], "BULL_ONLY": BULL_ONLY,
        "fees_bps": fee_bps, "slip_bps": slp_bps,
        "trades": len(trades), "wins": wins, "losses": losses,
        "win_rate_pct": round(wr,3), "equity_multiple": round(equity,6),
        "last_price": float(df["close"].iloc[-1]), "last_time": str(df.index[-1]),
    }
    (out/"eclectic_summary.json").write_text(json.dumps(summary, indent=2))
    return summary

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
