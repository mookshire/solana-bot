
import os, json, csv, subprocess, sys
from pathlib import Path
from itertools import product

DATA = Path("data/SOLUSDT_15m_5000.json")
OUTDIR = Path("data/backtests"); OUTDIR.mkdir(parents=True, exist_ok=True)
OUTCSV = OUTDIR / "sweep_SOLUSDT_15m_fast.csv"

# modest grid
BB_K_vals          = [2.0, 2.2, 2.4, 2.6]
RSI_BUY_MAX_vals   = [55, 60]
RSI_SELL_MIN_vals  = [60, 65]
VOL_MULT_vals      = [0.85, 1.00]
EMA_TREND_N_vals   = [100, 200]
REQUIRE_TREND_vals = [0, 1]
BB_COOLDOWN_vals   = [0, 2]

def need_cache():
    if not DATA.exists():
        print(f"ERROR: {DATA} missing. Create it once:\n"
              "  unset DATA_FILE; export BB_SYMBOL=SOLUSDT BB_INTERVAL=15m BB_LIMIT=5000; "
              "python3 -m src.backtest_hybrid")
        sys.exit(2)

def run_once(env):
    # Use the cached JSON; no network
    child_env = os.environ.copy()
    child_env.update({
        "BB_SYMBOL":"SOLUSDT", "BB_INTERVAL":"15m", "BB_LIMIT":"5000",
        "DATA_FILE": str(DATA)
    })
    for k,v in env.items():
        child_env[k] = str(v)

    proc = subprocess.run(
        [sys.executable, "-m", "src.backtest_hybrid"],
        env=child_env, capture_output=True, text=True
    )
    out = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        res = json.loads(out) if out else {}
    except Exception:
        res = {"error":"bad_json", "stdout": out, "stderr": proc.stderr.strip()}

    row = {}
    if isinstance(res, dict):
        row.update(res)
    row.update(env)
    return row

def main():
    need_cache()
    combos = list(product(
        BB_K_vals, RSI_BUY_MAX_vals, RSI_SELL_MIN_vals, VOL_MULT_vals,
        EMA_TREND_N_vals, REQUIRE_TREND_vals, BB_COOLDOWN_vals
    ))
    print(f"Sweeping {len(combos)} combos on cached 15m data...")

    rows = []
    for i,(k,rbu,rse,volx,ema,req,cd) in enumerate(combos,1):
        env = {
            "BB_K":k, "RSI_BUY_MAX":rbu, "RSI_SELL_MIN":rse,
            "VOL_MA_N":20, "VOL_MULT":volx,
            "EMA_TREND_N":ema, "REQUIRE_TREND":req,
            "BB_COOLDOWN_BARS":cd,
            "FEE_BPS":12.5, "SLIP_BPS":12.5,
        }
        rows.append(run_once(env))
        if i % 20 == 0 or i == len(combos):
            print(f"{i}/{len(combos)} done...")

    # sort: trades desc, equity desc, drawdown asc
    def f(x, default):
        try: return float(x)
        except: return default
    rows.sort(key=lambda r: (
        -f(r.get("trades"), 0.0),
        -f(r.get("equity_multiple") or r.get("equity"), 0.0),
         f(r.get("max_drawdown_pct"), 1e9),
    ))

    # write CSV
    keys = sorted({k for r in rows for k in r.keys()})
    with OUTCSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)

    print("\nTop 10 preview:")
    for r in rows[:10]:
        print({
            "trades": r.get("trades"),
            "equity_multiple": r.get("equity_multiple") or r.get("equity"),
            "max_dd%": r.get("max_drawdown_pct"),
            "BB_K": r.get("BB_K"),
            "RSI_BUY_MAX": r.get("RSI_BUY_MAX"),
            "RSI_SELL_MIN": r.get("RSI_SELL_MIN"),
            "VOL_MULT": r.get("VOL_MULT"),
            "EMA_TREND_N": r.get("EMA_TREND_N"),
            "REQ_TREND": r.get("REQUIRE_TREND"),
            "COOLDOWN": r.get("BB_COOLDOWN_BARS"),
        })
    print(f"\nWrote {OUTCSV}")

if __name__ == "__main__":
    main()
