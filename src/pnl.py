from __future__ import annotations
import os, sqlite3, requests
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "data" / "trades.sqlite"
OUT  = ROOT / "data" / "pnl_daily.csv"

USDC_PER = 1.0  # trivial helper

def get_mark_usdc_per_sol() -> float | None:
    s = requests.Session()
    s.headers.update({"accept":"application/json","user-agent":"solana-bot/1.0"})
    try:
        r = s.get("https://price.jup.ag/v4/price", params={"ids":"SOL","vsToken":"USDC"}, timeout=8)
        r.raise_for_status()
        return float(r.json()["data"]["SOL"]["price"])
    except Exception:
        try:
            r = s.get("https://api.coingecko.com/api/v3/simple/price", params={"ids":"solana","vs_currencies":"usd"}, timeout=8)
            r.raise_for_status()
            return float(r.json()["solana"]["usd"])
        except Exception:
            return None

def iter_trades():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(
        """SELECT ts, side, in_amount, out_amount, tx_sig
           FROM trades
           WHERE tx_sig IS NOT NULL
           ORDER BY ts ASC"""
    )
    for ts, side, in_amt, out_amt, tx_sig in cur.fetchall():
        yield int(ts), (side or "").upper(), float(in_amt or 0), float(out_amt or 0)

def main():
    if not DB.exists():
        print("No DB found at", DB)
        return

    realized_by_day = defaultdict(float)
    pos_sol = 0.0
    cost_usdc = 0.0   # total cost basis of open SOL position (USDC)

    for ts, side, in_amt, out_amt in iter_trades():
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        if side.startswith("BUY"):  # USDC -> SOL
            usdc_spent = in_amt
            sol_bought = out_amt
            pos_sol   += sol_bought
            cost_usdc += usdc_spent
        elif side.startswith("SELL"):  # SOL -> USDC
            sol_sold      = in_amt
            usdc_received = out_amt
            if pos_sol <= 1e-12:
                # No inventory tracked; treat basis as 0 to avoid crash
                basis = 0.0
            else:
                avg_cost = cost_usdc / pos_sol
                # Cap basis by remaining cost_usdc (guards small rounding drifts)
                basis = min(cost_usdc, sol_sold * avg_cost)
            pnl = usdc_received - basis
            realized_by_day[day] += pnl
            # Reduce position & cost basis
            pos_sol   = max(0.0, pos_sol - sol_sold)
            cost_usdc = max(0.0, cost_usdc - basis)
        else:
            # ignore
            pass

    # Write CSV
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        f.write("date,realized_pnl_usdc\n")
        for day in sorted(realized_by_day.keys()):
            f.write(f"{day},{realized_by_day[day]:.6f}\n")

    # Print summary
    print("== PnL Report ==")
    total = 0.0
    for day in sorted(realized_by_day.keys()):
        val = realized_by_day[day]
        total += val
        sign = "+" if val >= 0 else "-"
        print(f"{day}: {sign}${abs(val):.2f}")
    print(f"Total realized PnL: {'+' if total>=0 else '-'}${abs(total):.2f}")

    avg_cost = (cost_usdc / pos_sol) if pos_sol > 1e-12 else 0.0
    mark = get_mark_usdc_per_sol()
    if mark is None:
        print(f"Open position: {pos_sol:.6f} SOL @ avg cost {avg_cost:.4f} (mark: n/a)")
    else:
        unreal = pos_sol * (mark - avg_cost)
        print(f"Open position: {pos_sol:.6f} SOL @ avg cost {avg_cost:.4f} | mark {mark:.4f} → unrealized {'+' if unreal>=0 else '-'}${abs(unreal):.2f}")

    print(f"\nSaved daily CSV → {OUT}")

if __name__ == "__main__":
    main()
