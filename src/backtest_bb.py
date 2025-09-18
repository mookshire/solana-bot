from __future__ import annotations
import csv, os, sys, json, math
from pathlib import Path
import requests
from typing import List, Dict, Tuple
from src.indicators import bollinger_bands

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT = DATA_DIR / "backtest_bb_report.json"
TRADES_CSV = DATA_DIR / "backtest_bb_trades.csv"

SYMBOL    = os.getenv("BB_SYMBOL", "SOLUSDT")
INTERVAL  = os.getenv("BB_INTERVAL", "5m")          # use 5m by default
LIMIT     = int(os.getenv("BB_LIMIT", "1000"))
PERIOD    = int(os.getenv("BB_PERIOD", "20"))       # BB period
K         = float(os.getenv("BB_K", "2.0"))         # BB stdev
EMA_N     = int(os.getenv("BB_EMA_N", "200"))       # trend filter length
CHOP_PCT  = float(os.getenv("BB_CHOP_PCT", "0.006"))# 0.6% min band width
COOL_BARS = int(os.getenv("BB_COOLDOWN_BARS", "1")) # 1 bar on 5m ~= 5 minutes
FEE_BPS   = float(os.getenv("BB_FEE_BPS", "12.5"))  # per side fees (bps)
SLIP_BPS  = float(os.getenv("BB_SLIP_BPS", "12.5")) # per side slippage (bps)

BINANCE_URL = "https://api.binance.com/api/v3/klines"
UA = {"User-Agent": "solana-bot/1.0"}

def fetch_binance_to_csv(csv_path: Path, symbol: str, interval: str, limit: int):
    r = requests.get(BINANCE_URL, params={"symbol":symbol,"interval":interval,"limit":limit},
                     headers=UA, timeout=20)
    r.raise_for_status()
    kl = r.json()
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["time","open","high","low","close","volume"])
        for k in kl:
            ts = int(k[0])//1000
            w.writerow([ts, k[1], k[2], k[3], k[4], k[5]])

def load_csv(csv_path: Path):
    times, opens, highs, lows, closes = [], [], [], [], []
    with csv_path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            times.append(int(float(row["time"])))
            opens.append(float(row["open"]))
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))
            closes.append(float(row["close"]))
    return times, opens, highs, lows, closes

def ema(values: List[float], n: int) -> List[float]:
    if n <= 0: raise ValueError("EMA length must be > 0")
    out: List[float] = []
    k = 2.0 / (n + 1.0)
    s = 0.0
    # seed with SMA
    if len(values) < n: return out
    s = sum(values[:n]) / n
    out.append(s)
    for v in values[n:]:
        s = v * k + s * (1 - k)
        out.append(s)
    return out  # length = len(values) - n + 1

def decide_confirmation(prev_close, last_close, prev_upper, last_upper, prev_lower, last_lower):
    # confirmation: pierce then re-enter bands
    if prev_close < prev_lower and last_close > last_lower:
        return "BUY"
    if prev_close > prev_upper and last_close < last_upper:
        return "SELL"
    return "HOLD"

def backtest(times: List[int], closes: List[float]):
    up, mid, lo = bollinger_bands(closes, PERIOD, K)        # aligned to len = N - PERIOD + 1
    ema_series = ema(closes, EMA_N)                         # aligned to len = N - EMA_N + 1
    if not ema_series:
        raise ValueError("Not enough data for EMA_N")

    # align everything to the shortest tail
    off_bb  = len(closes) - len(up)
    off_ema = len(closes) - len(ema_series)
    start_off = max(off_bb, off_ema)                        # first index in closes that has both
    # translate to indices inside each derived list
    shift_bb  = start_off - off_bb
    shift_ema = start_off - off_ema

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    state = "FLAT"
    entry_px = None
    entry_t  = None
    last_trade_bar = -10**9
    trades: List[Dict] = []
    signals = {"BUY":0,"SELL":0,"HOLD":0}

    # walk bands from the second usable band point forward
    for i in range(shift_bb + 1, len(up)):
        bar_idx_close = start_off + (i - shift_bb)         # index into closes/times
        prev_idx_close = bar_idx_close - 1

        prev_close = closes[prev_idx_close]
        last_close = closes[bar_idx_close]

        prev_upper, last_upper = up[i-1], up[i]
        prev_lower, last_lower = lo[i-1], lo[i]

        # chop guard: require band width >= CHOP_PCT of price on the confirmation candle
        width_pct = (last_upper - last_lower) / last_close
        if width_pct < CHOP_PCT:
            signals["HOLD"] += 1
            continue

        # trend filter: align ema index for the same bars
        ema_i = shift_ema + (i - shift_bb)
        ema_prev = ema_series[ema_i - 1]
        ema_last = ema_series[ema_i]

        sig = decide_confirmation(prev_close, last_close, prev_upper, last_upper, prev_lower, last_lower)

        # apply trend filter to entries only
        if state == "FLAT":
            if sig == "BUY" and last_close > ema_last and (i - last_trade_bar) >= COOL_BARS:
                # enter long at last_close with fee+slip
                entry_px = last_close * (1 + (FEE_BPS + SLIP_BPS)/10000.0)
                entry_t  = times[bar_idx_close]
                state = "LONG"
                last_trade_bar = i
            elif sig == "SELL" and last_close < ema_last and (i - last_trade_bar) >= COOL_BARS:
                # optional: could enter short; we keep long-only for now -> treat as HOLD
                pass
        elif state == "LONG":
            # exit only when SELL signal (we don't require trend on exits)
            if sig == "SELL" and (i - last_trade_bar) >= COOL_BARS:
                exit_px = last_close * (1 - (FEE_BPS + SLIP_BPS)/10000.0)
                ret = (exit_px / entry_px) - 1.0
                equity *= (1.0 + ret)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity)/peak)
                trades.append({
                    "entry_time": entry_t,
                    "exit_time": times[bar_idx_close],
                    "entry_px": entry_px,
                    "exit_px": exit_px,
                    "ret_pct": ret*100.0,
                    "width_pct": round(width_pct*100.0,4),
                })
                state = "FLAT"
                entry_px = None
                entry_t = None
                last_trade_bar = i

        signals[sig] = signals.get(sig, 0) + 0  # just to keep counts keys

    open_ret = None
    if state == "LONG" and entry_px:
        last_px = closes[-1]
        open_ret = (last_px / entry_px) - 1.0

    wins = sum(1 for t in trades if t["ret_pct"] > 0)
    losses = len(trades) - wins
    winrate = (wins / len(trades) * 100.0) if trades else 0.0
    avg_ret = (sum(t["ret_pct"] for t in trades) / len(trades)) if trades else 0.0

    report = {
        "symbol": SYMBOL, "interval": INTERVAL,
        "period": PERIOD, "k": K, "ema_n": EMA_N,
        "chop_pct": CHOP_PCT, "cooldown_bars": COOL_BARS,
        "fee_bps_per_side": FEE_BPS, "slip_bps_per_side": SLIP_BPS,
        "bars": len(closes), "trades": len(trades),
        "wins": wins, "losses": losses, "win_rate_pct": round(winrate, 2),
        "avg_trade_ret_pct": round(avg_ret, 4),
        "equity_multiple": round(equity, 6),
        "max_drawdown_pct": round(max_dd*100.0, 2),
        "open_position_ret_pct": round(open_ret*100.0, 4) if open_ret is not None else None,
    }
    return report, trades

def main():
    # fetch latest candles into CSV (quick run window)
    csv_path = DATA_DIR / f"binance_{SYMBOL}_{INTERVAL}.csv"
    fetch_binance_to_csv(csv_path, SYMBOL, INTERVAL, LIMIT)
    times, *_rest, closes = load_csv(csv_path)
    report, trades = backtest(times, closes)
    print(json.dumps(report, indent=2))
    REPORT.write_text(json.dumps(report, indent=2))
    with TRADES_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["entry_time","exit_time","entry_px","exit_px","ret_pct","width_pct"])
        w.writeheader()
        for t in trades:
            w.writerow(t)

if __name__ == "__main__":
    main()
