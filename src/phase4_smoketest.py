from __future__ import annotations
import json, math, random
from pathlib import Path
from statistics import mean
from risk_controls import atr, calc_stops, position_size_units

random.seed(42)

# Build a tiny synthetic OHLC series that trends up with noise
n = 200
price = 100.0
high, low, close = [], [], []
for i in range(n):
    step = random.gauss(0.05, 0.6)  # noisy drift
    new = max(1.0, price + step)
    h = max(new, price) + abs(random.gauss(0, 0.3))
    l = min(new, price) - abs(random.gauss(0, 0.3))
    c = new + random.gauss(0, 0.1)
    high.append(h); low.append(l); close.append(c)
    price = c

A = atr(high, low, close, period=14)
# Use the last ATR as representative
last_atr = next((x for x in reversed(A) if x is not None), None)
entry = close[-1]
equity_usd = 10_000
risk_pct = 0.005
sl_mult, tp_mult = 1.5, 3.0

st = calc_stops(entry, last_atr, side="long", sl_atr_mult=sl_mult, tp_atr_mult=tp_mult)
units = position_size_units(equity_usd, risk_pct, last_atr, entry, sl_atr_mult=sl_mult)

report = {
    "phase": "4",
    "module": "risk_controls",
    "entry_price": round(entry, 6),
    "last_atr": round(last_atr, 6) if last_atr else None,
    "stop": round(st.stop, 6),
    "take": round(st.take, 6),
    "risk_pct": risk_pct,
    "units_sol": round(units, 6),
    "notional_usd": round(units * entry, 2),
    "notes": "Synthetic smoketest only; integration with backtest_hybrid.py comes next."
}

out = Path("reports/phase4_smoketest.json")
out.write_text(json.dumps(report, indent=2))
print("Wrote", str(out))
print(json.dumps(report, indent=2))
