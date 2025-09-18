from __future__ import annotations

def decide_signal(prev_close, last_close, prev_upper, last_upper, prev_lower, last_lower):
    # Same rules as strategy_bb_confirm.py
    if prev_close < prev_lower and last_close > last_lower:
        return "BUY"
    if prev_close > prev_upper and last_close < last_upper:
        return "SELL"
    return "HOLD"

def run():
    cases = []

    # 1) BUY: pierce below lower then close back inside
    cases.append(("BUY basic", decide_signal(
        prev_close=95, last_close=101, prev_upper=120, last_upper=120, prev_lower=100, last_lower=100), "BUY"))

    # 2) SELL: pierce above upper then close back inside
    cases.append(("SELL basic", decide_signal(
        prev_close=205, last_close=199, prev_upper=200, last_upper=200, prev_lower=180, last_lower=180), "SELL"))

    # 3) HOLD: still below lower on confirmation candle (no re-entry)
    cases.append(("No buy if still below", decide_signal(
        prev_close=95, last_close=98, prev_upper=120, last_upper=120, prev_lower=100, last_lower=100), "HOLD"))

    # 4) HOLD: still above upper on confirmation candle (no re-entry)
    cases.append(("No sell if still above", decide_signal(
        prev_close=205, last_close=203, prev_upper=200, last_upper=200, prev_lower=180, last_lower=180), "HOLD"))

    # 5) HOLD: both candles inside bands
    cases.append(("Both inside", decide_signal(
        prev_close=110, last_close=112, prev_upper=200, last_upper=200, prev_lower=100, last_lower=100), "HOLD"))

    # 6) Boundary: equal to band should NOT trigger (our rule uses strict < and >)
    cases.append(("Equal to lower boundary", decide_signal(
        prev_close=100, last_close=101, prev_upper=120, last_upper=120, prev_lower=100, last_lower=100), "HOLD"))
    cases.append(("Equal to upper boundary", decide_signal(
        prev_close=200, last_close=199, prev_upper=200, last_upper=200, prev_lower=100, last_lower=100), "HOLD"))

    # 7) Whipsaw edge: below->inside->below (should be HOLD for this two-bar check)
    cases.append(("Whipsaw stay below", decide_signal(
        prev_close=95, last_close=99, prev_upper=120, last_upper=120, prev_lower=100, last_lower=100), "HOLD"))

    # Print results
    ok = True
    for name, got, want in cases:
        passed = got == want
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: got={got} want={want}")
    print("\nOVERALL:", "PASS" if ok else "FAIL")

if __name__ == "__main__":
    run()
