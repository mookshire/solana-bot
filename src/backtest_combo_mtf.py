from __future__ import annotations
import pandas as pd
from .backtest_hybrid import fetch_klines, ema, rsi  # do NOT import macd

def _macd_hist_from_ema(close: pd.Series) -> pd.Series:
    macd_line = ema(close, 12) - ema(close, 26)
    signal    = ema(macd_line, 9)
    return macd_line - signal

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema9"]   = ema(df["close"], 9)
    df["ema21"]  = ema(df["close"], 21)
    df["sma200"] = df["close"].rolling(200).mean()
    df["rsi"]    = rsi(df["close"], 14)
    df["macd_hist"] = _macd_hist_from_ema(df["close"])
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    return df

def make_bias_series_1h(df1h: pd.DataFrame, df15: pd.DataFrame) -> pd.Series:
    # Bull bias if last close > 200‑SMA on 1h
    bias_1h = df1h["close"] > df1h["close"].rolling(200).mean()
    return bias_1h.reindex(df15.index, method="ffill")

def signals_15m_with_filters(df: pd.DataFrame, bias_ok: pd.Series) -> pd.DataFrame:
    import os
    bull_only  = int(os.getenv("BULL_ONLY","1")) == 1
    rsi_buy_lt = float(os.getenv("RSI_BUY_LT","55"))
    rsi_sell_gt= float(os.getenv("RSI_SELL_GT","61"))
    vol_buy_x  = float(os.getenv("VOL_BUY_X","0.85"))
    vol_sell_x = float(os.getenv("VOL_SELL_X","1.25"))

    out = []
    for i in range(len(df)):
        if bull_only and not bool(bias_ok.iloc[i]):
            out.append("HOLD"); continue
        row = df.iloc[i]
        if (row["rsi"] < rsi_buy_lt) and (row["volume"] > vol_buy_x * row["vol_sma20"]):
            out.append("BUY")
        elif (row["rsi"] > rsi_sell_gt) and (row["volume"] > vol_sell_x * row["vol_sma20"]):
            out.append("SELL")
        else:
            out.append("HOLD")

    df = df.copy()
    df["signal"] = out
    return df
