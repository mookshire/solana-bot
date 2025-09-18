from __future__ import annotations
from typing import Sequence, Tuple, List
import math

def sma(values: Sequence[float], period: int) -> List[float]:
    out: List[float] = []
    if period <= 0: raise ValueError("period must be > 0")
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period: s -= values[i - period]
        if i >= period - 1: out.append(s / period)
    return out

def rolling_std(values: Sequence[float], period: int) -> List[float]:
    out: List[float] = []
    if period <= 0: raise ValueError("period must be > 0")
    # Welford rolling variance for stability
    from collections import deque
    q = deque(maxlen=period)
    mean = 0.0
    M2 = 0.0
    for v in values:
        if len(q) == period:
            old = q.popleft()
            # remove old
            prev_mean = mean
            mean = prev_mean + ( -old ) / period
            # recompute M2 from scratch for simplicity when window slides
            # (period is small so cost is fine)
            tmp = list(q) + [v]  # will push after
            m = sum(tmp[:-1]) / period
            M2 = sum((x - m)*(x - m) for x in tmp[:-1])
            # fall-through to add v as usual
        q.append(v)
        if len(q) == period:
            m = sum(q) / period
            var = sum((x - m)*(x - m) for x in q) / period
            out.append(math.sqrt(var))
    return out

def bollinger_bands(
    closes: Sequence[float], period: int = 20, k: float = 2.0
) -> Tuple[List[float], List[float], List[float]]:
    """
    Returns (upper, middle, lower) aligned to the last len(closes)-period+1 points.
    """
    if len(closes) < period:
        raise ValueError("not enough closes for period")
    mid = sma(closes, period)
    std = rolling_std(closes, period)
    # align lengths (both are len = n - period + 1)
    upper = [m + k*s for m, s in zip(mid, std)]
    lower = [m - k*s for m, s in zip(mid, std)]
    return upper, mid, lower
