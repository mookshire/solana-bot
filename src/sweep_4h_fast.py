import os, json, itertools, subprocess, time
from pathlib import Path

DATA_FILE = "data/SOLUSDT_4h_5000.json"
OUT_CSV   = Path("data/backtests/sweep_4h_fast_"+time.strftime("%Y%m%d_%H%M%S")+".csv")
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

# Modest grid (tweak as desired)
Ks    = [2.4, 2.6, 2.8, 3.0, 3.2]     # BB_K
EMAs  = [200, 300, 400, 500]          # EMA_N
RSIs  = [65, 70, 75, 80]              # RSI exit
CDs   = [1, 2, 3, 4]                  # cooldown bars

def run_once(env):
    e = os.environ.copy()
    e.update(env)
    out = subprocess.check_output(["python3", "src/backtest_hybrid.py"], env=e, timeout=90)
    return json.loads(out.decode())

rows = []
grid = list(itertools.product(Ks, EMAs, RSIs, CDs))
total = len(grid)
for i, (K, EMA, RSI, CD) in enumerate(grid, 1):
    env = {
        "DATA_FILE": DATA_FILE,
        "BB_SYMBOL":"SOLUSDT", "BB_INTERVAL":"4h", "BB_LIMIT":"5000",
        "BB_PERIOD":"20", "BB_K":str(K),
        "EMA_N":str(EMA),
        "RSI_N":"14", "RSI_EXIT":str(RSI),
        "COOLDOWN_BARS":str(CD),
        # Realistic frictions (per side) – adjust if your hybrid expects combined bps:
        "FEE_BPS_PER_SIDE":"12.5",
        "SLIP_BPS_PER_SIDE":"12.5",
    }
    try:
        res = run_once(env)
        res.update({"BB_K":K, "EMA_N":EMA, "RSI_EXIT":RSI, "COOLDOWN_BARS":CD})
        rows.append(res)
    except Exception as ex:
        # keep going; capture minimal info on the failure if needed
        pass
    if i % 10 == 0 or i == total:
        print(f"{i}/{total} done...")

# Sort by equity first (desc), then drawdown (asc), then trades (desc)
def keyf(r):
    eq  = r.get("equity_multiple", 0.0)
    dd  = r.get("max_drawdown_pct", 999.0)
    trd = r.get("trades", 0)
    return (-eq, dd, -trd)

rows.sort(key=keyf)

# Write CSV
import pandas as pd
keep = ["equity_multiple","win_rate_pct","trades","wins","losses",
        "max_drawdown_pct","profit_factor","BB_K","EMA_N","RSI_EXIT","COOLDOWN_BARS"]
df = pd.DataFrame(rows)
if df.empty:
    print("No sweep results captured. Check backtest_hybrid.py JSON output or env var names.")
else:
    for col in keep:
        if col not in df.columns:
            df[col] = None
    df[keep].to_csv(OUT_CSV, index=False)
    print(f"WROTE: {OUT_CSV}")
    print("Top 10 preview:")
    print(df[keep].head(10).to_string(index=False))
