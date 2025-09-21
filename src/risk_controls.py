from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Literal

Side = Literal["long","short"]

def _true_range(h: float, l: float, prev_close: float) -> float:
    return max(h - l, abs(h - prev_close), abs(l - prev_close))

def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[float]:
    """
    Wilder-style ATR with simple moving average smoothing over 'period'.
    Returns a list, same length as inputs, with leading values as None until enough data.
    """
    n = len(close)
    if not (len(high) == len(low) == n):
        raise ValueError("high, low, close must be same length")
    if n == 0:
        return []

    tr = [None]*n
    for i in range(1, n):
        tr[i] = _true_range(high[i], low[i], close[i-1])
    # Seed with simple average of first 'period' TR values (ignoring the first None)
    out = [None]*n
    if n <= period:
        return out
    seed = [x for x in tr[1:period+1] if x is not None]
    if len(seed) < period:
        return out
    atr_val = sum(seed) / period
    out[period] = atr_val
    # Wilder smoothing
    for i in range(period+1, n):
        atr_val = ( (atr_val * (period - 1)) + (tr[i] if tr[i] is not None else 0.0) ) / period
        out[i] = atr_val
    return out

@dataclass
class StopsTP:
    stop: float
    take: float

def calc_stops(entry: float, atr_value: float, side: Side, sl_atr_mult: float = 1.5, tp_atr_mult: float = 3.0) -> StopsTP:
    """
    ATR-based stop loss & take profit (in price terms).
    For long: stop = entry - k*ATR, take = entry + m*ATR
    For short: stop = entry + k*ATR, take = entry - m*ATR
    """
    if atr_value is None or atr_value <= 0:
        raise ValueError("ATR value must be positive")
    if side == "long":
        return StopsTP(stop=entry - sl_atr_mult*atr_value, take=entry + tp_atr_mult*atr_value)
    else:
        return StopsTP(stop=entry + sl_atr_mult*atr_value, take=entry - tp_atr_mult*atr_value)

def position_size_units(
    equity_usd: float,
    risk_pct: float,
    atr_value: float,
    entry_price: float,
    sl_atr_mult: float = 1.5,
    min_qty: float = 0.001,
    max_notional_usd: float | None = None,
) -> float:
    """
    Volatility-based sizing: units = risk_dollars / (SL distance in USD per unit).
    SL distance (USD/unit) ≈ sl_atr_mult * atr_value
    For spot SOL/USDT, USD/unit ≈ entry_price; but ATR is in price units already.
    Here we assume ATR is in price units (USDT for SOL/USDT), so SL distance per unit ≈ sl_atr_mult*ATR.
    Risk dollars = equity_usd * risk_pct.
    """
    if equity_usd <= 0 or entry_price <= 0 or atr_value is None or atr_value <= 0:
        raise ValueError("Bad inputs to position sizing")
    risk_dollars = equity_usd * risk_pct
    sl_distance_per_unit = sl_atr_mult * atr_value  # USDT per coin
    if sl_distance_per_unit <= 0:
        raise ValueError("Non-positive SL distance")
    units = risk_dollars / sl_distance_per_unit
    if max_notional_usd is not None:
        units = min(units, max_notional_usd / entry_price)
    if units < min_qty:
        # If account/risk too small for ATR, clip to min_qty; caller may decide to skip the trade instead.
        units = min_qty
    return units
