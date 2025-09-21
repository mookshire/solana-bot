import os, itertools, subprocess, pandas as pd

# --- PARAM GRID (edit as needed) ---
grid = {
    "EMA_FAST_N": [10, 20],
    "EMA_SLOW_N": [50, 100, 200],
    "BB_N":       [20],
    "BB_K":       [2.0],
    "VOL_Q_MIN":  [0.40, 0.50, 0.60],
    "TREND_Q_MR": [0.60, 0.70],
    "TREND_Q_MOM":[0.60, 0.70],
    # fixed training window knobs (tweak if desired)
    "W_TRAIN":    [9],
    "MIN_BARS":   [900],
    # keep baseline costs
    "FEE_BPS":    [5],
    "SLIP_BPS":   [5],
}

rows=[]
keys=list(grid.keys())
for vals in itertools.product(*[grid[k] for k in keys]):
    env = os.environ.copy()
    env["PYTHONPATH"]="."
    for k,v in zip(keys,vals): env[k]=str(v)
    label = ", ".join(f"{k}={env[k]}" for k in keys)
    print("running:", label)
    subprocess.run(["python3","-u","src/walkforward_offline.py"], env=env, check=True)
    df = pd.read_csv("data/backtests/walk_bb_ema_regime_v5_equity.csv")
    strat = float(df["strat_cum"].iloc[-1])
    bh    = float(df["bh_cum"].iloc[-1]) if "bh_cum" in df.columns else None
    ratio = (strat / bh) if bh and bh!=0 else None
    picks = df["pick"].value_counts().to_dict() if "pick" in df.columns else {}
    rows.append({
        **{k:env[k] for k in keys},
        "equity": strat, "bh": bh, "ratio": ratio,
        "p_BH": picks.get("BH",0), "p_EMA": picks.get("EMA",0), "p_BB": picks.get("BB",0),
    })

out = pd.DataFrame(rows)
out = out.sort_values(["equity","ratio"], ascending=[False,False])
out.to_csv("reports/param_sweep.csv", index=False)
print("\nTop 10 configs:\n", out.head(10).to_string(index=False))
