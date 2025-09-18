from __future__ import annotations
import os, time
from datetime import datetime

def _int_ts(x):
    try:
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            try:
                return int(datetime.fromisoformat(str(x)).timestamp())
            except Exception:
                return int(time.time())
import json
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
import sqlite3
import requests

# reuse helpers/constants from our Jupiter client
from src.jupiter_client import (
    ROOT, USDC_MINT, SOL_MINT,
    load_env, load_pubkey_base58,
)

PLAN_PATH = (ROOT / "data" / "sell_plan.json")

def jup_quote_sell(amount_sol: Decimal, slippage_bps: int) -> dict:
    """Quote SOL -> USDC for amount_sol using Jupiter v6."""
    lamports = int((amount_sol * Decimal(10**9)).to_integral_value(rounding=ROUND_DOWN))
    params = {
        "inputMint": SOL_MINT,
        "outputMint": USDC_MINT,
        "amount": str(lamports),
        "slippageBps": str(slippage_bps),
        "onlyDirectRoutes": "false",
        "maxAccounts": "64",
        "restrictIntermediateTokens": "true",
        "asLegacyTransaction": "false",
    }
    r = requests.get("https://quote-api.jup.ag/v6/quote", params=params, timeout=20)
    r.raise_for_status()
    q = r.json()
    if "outAmount" not in q or "routePlan" not in q:
        raise RuntimeError(f"Unexpected quote shape: {q}")
    return q

def main():
    # env & safety (still DRY-RUN — no sends here)
    _env = load_env()
    # handle both 5- and 6-tuple returns
    slippage_bps, keypair_path, _test_amount_usdc, _rpc_url, dry_run = _env[:5]
    test_cap = _env[5] if len(_env) > 5 else 1

    user = load_pubkey_base58(keypair_path)
    tp_bps = int(os.getenv("TAKE_PROFIT_BPS", "100"))     # 100 = +1.00%
    sl_bps = int(os.getenv("STOP_LOSS_BPS", "300"))       # 300 = -3.00%
    sell_frac = Decimal(os.getenv("TP_SELL_PCT", "1.0"))  # fraction of position to consider selling

    print(f"[sell_check] DRY_RUN={dry_run} | user={user}")
    print(f"[sell_check] TAKE_PROFIT_BPS={tp_bps} | STOP_LOSS_BPS={sl_bps} | TP_SELL_PCT={sell_frac}")

    # fetch last BUY to compute entry price
    db_path = ROOT / "data" / "trades.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""SELECT ts, in_amount, out_amount, tx_sig
                   FROM trades
                   WHERE side IN ('BUY','BUY_SOL') AND tx_sig IS NOT NULL
                   ORDER BY ts DESC LIMIT 1""")
    row = cur.fetchone()
    conn.close()

    plan = {
        "generated_at": int(time.time()),
        "user": user,
        "decision": "NONE",
        "reason": "",
        "sell_qty_sol": "0",
        "entry_usdc_per_sol": None,
        "tp_bps": tp_bps,
        "sl_bps": sl_bps,
        "tp_target_usdc": None,
        "sl_target_usdc": None,
        "quoted_out_usdc": None,
        "price_impact_pct": None,
        "slippage_bps": slippage_bps,
    }

    if not row:
        print("[sell_check] No prior BUY_SOL with tx_sig found; nothing to evaluate.")
        PLAN_PATH.write_text(json.dumps(plan, indent=2))
        return

    ts, usdc_in, sol_out_est, sig = row
    entry_usdc_per_sol = (Decimal(usdc_in) / Decimal(max(sol_out_est, 1e-9))).quantize(Decimal("0.000001"))
    time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_int_ts(ts)))
    print(f"[sell_check] Last BUY at {time_str} | spent ≈{usdc_in:.4f} USDC, got ≈{sol_out_est:.9f} SOL (est) | tx={str(sig)[:12]}…")
    print(f"[sell_check] Entry price ≈ {entry_usdc_per_sol} USDC/SOL")

    # choose how much to consider selling
    sell_qty_sol = (Decimal(sol_out_est) * sell_frac).quantize(Decimal("0.000000001"))
    if sell_qty_sol <= 0:
        print("[sell_check] Computed sell quantity is 0; nothing to do.")
        PLAN_PATH.write_text(json.dumps(plan, indent=2))
        return

    # quote SOL -> USDC now
    q0 = time.time()
    quote = jup_quote_sell(sell_qty_sol, slippage_bps)
    ms = int((time.time() - q0) * 1000)
    out_usdc_now = Decimal(quote["outAmount"]) / Decimal(10**6)
    price_impact_pct = Decimal(quote.get("priceImpactPct", 0)) * Decimal(100)
    print(f"[sell_check] Quote now: {sell_qty_sol} SOL -> {out_usdc_now:.4f} USDC "
          f"| impact ≈ {price_impact_pct:.3f}% | {ms} ms")

    # thresholds for this sell size
    tp_target = (entry_usdc_per_sol * sell_qty_sol) * (Decimal(1) + Decimal(tp_bps) / Decimal(10_000))
    sl_target = (entry_usdc_per_sol * sell_qty_sol) * (Decimal(1) - Decimal(sl_bps) / Decimal(10_000))

    print(f"[sell_check] TP needs ≥ {tp_target:.4f} USDC | SL triggers ≤ {sl_target:.4f} USDC for {sell_qty_sol} SOL")
    decision = 'SELL'
    reason = 'FORCED_TEST'
    print('DECISION: ✅ Forced SELL for testing')
    plan.update({
        "decision": decision,
        "reason": reason,
        "sell_qty_sol": str(sell_qty_sol),
        "entry_usdc_per_sol": str(entry_usdc_per_sol),
        "tp_target_usdc": str(tp_target.quantize(Decimal('0.0001'))),
        "sl_target_usdc": str(sl_target.quantize(Decimal('0.0001'))),
        "quoted_out_usdc": str(out_usdc_now.quantize(Decimal('0.0001'))),
        "price_impact_pct": str(price_impact_pct),
        "quote_raw": quote,  # executor can reuse this to avoid re-quoting if timely
    })

    # ensure data dir exists
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2))
    print(f"[sell_check] Wrote plan → {PLAN_PATH}")

if __name__ == "__main__":
    main()