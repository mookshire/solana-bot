import math
from src.risk_controls import atr, calc_stops, position_size_units

def test_calc_stops_long_short():
    st_long  = calc_stops(entry=100.0, atr_value=2.0, side="long",  sl_atr_mult=1.5, tp_atr_mult=3.0)
    st_short = calc_stops(entry=100.0, atr_value=2.0, side="short", sl_atr_mult=1.5, tp_atr_mult=3.0)
    assert st_long.stop  == 97.0
    assert st_long.take  == 106.0
    assert st_short.stop == 103.0
    assert st_short.take == 94.0

def test_position_size_units_basic():
    units = position_size_units(equity_usd=10_000, risk_pct=0.005,
                                atr_value=1.2, entry_price=120.0, sl_atr_mult=1.5)
    exp = (10_000*0.005) / (1.5*1.2)  # risk_dollars / SL distance
    assert math.isclose(units, exp, rel_tol=1e-9)

def test_position_size_units_caps_and_min():
    u_min = position_size_units(equity_usd=10, risk_pct=0.001, atr_value=5.0,
                                entry_price=100.0, sl_atr_mult=2.0, min_qty=0.01)
    assert u_min == 0.01
    u_cap = position_size_units(equity_usd=10_000, risk_pct=0.01, atr_value=1.0,
                                entry_price=50.0, sl_atr_mult=1.0, max_notional_usd=200.0)
    assert u_cap <= 200.0/50.0 + 1e-12

def test_atr_constant_series_zero_after_warmup():
    n = 40
    h = [10.0]*n; l = [10.0]*n; c = [10.0]*n
    A = atr(h, l, c, period=14)
    tail = [x for x in A[14:] if x is not None]
    assert tail and all(abs(x - 0.0) < 1e-12 for x in tail)

def test_atr_impulse_decays():
    h = [10, 12] + [10]*60
    l = [10,  8] + [10]*60
    c = [10, 10] + [10]*60
    A = atr(h, l, c, period=14)
    vals = [x for x in A if x is not None]
    assert vals and vals[-1] < vals[0]
