from __future__ import annotations
import numpy as np
import pandas as pd

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = np.where(down == 0, np.nan, up / down)
    return pd.Series(100 - (100 / (1 + rs)), index=series.index)

def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def bollinger(close: pd.Series, period: int = 20, k: float = 2.6):
    ma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = ma + k * std
    lower = ma - k * std
    return ma, upper, lower

def build_signals(df: pd.DataFrame, period: int = 20, k: float = 2.6):
    """
    Returns dict with indicators + entry_signal (+1 long, -1 short, 0 none)
    and ATR-based dynamic targets/stops.
    """
    close = df['close']
    mid, upper, lower = bollinger(close, period, k)
    ema200 = close.ewm(span=200, adjust=False).mean()
    rsi14 = rsi(close, 14)
    atr14 = atr(df, 14)

    # Re-entry inside bands
    reenter_long = (df['close'].shift(1) < lower.shift(1)) & (close > lower)
    reenter_short = (df['close'].shift(1) > upper.shift(1)) & (close < upper)

    long_ok  = reenter_long  & (rsi14 < 35) & (close > ema200)
    short_ok = reenter_short & (rsi14 > 65) & (close < ema200)

    signals = pd.Series(0, index=df.index, dtype=int)
    signals = signals.mask(long_ok,  1)
    signals = signals.mask(short_ok, -1)

    # Exits (price-based)
    tp_long  = close + 3 * atr14
    sl_long  = close - 1.5 * atr14
    tp_short = close - 3 * atr14
    sl_short = close + 1.5 * atr14

    return {
        'mid': mid, 'upper': upper, 'lower': lower,
        'ema200': ema200, 'rsi14': rsi14, 'atr14': atr14,
        'entry_signal': signals,  # +1 long / -1 short / 0 none
        'tp_long': tp_long, 'sl_long': sl_long,
        'tp_short': tp_short, 'sl_short': sl_short,
    }
