import os, subprocess, pandas as pd

fees  = [2.5, 5, 10, 20]
slips = [2.5, 5, 10, 20]

rows = []
for f in fees:
    for s in slips:
        env = os.environ.copy()
        env["FEE_BPS"]   = str(f)
        env["SLIP_BPS"]  = str(s)
        env["PYTHONPATH"] = "."
        print(f"running FEE={f}, SLIP={s}")
        subprocess.run(["python3", "-u", "src/walkforward_offline.py"], env=env, check=True)
        df = pd.read_csv("data/backtests/walk_bb_ema_regime_v5_equity.csv")
        rows.append({"fee": f, "slip": s, "equity": float(df['strat_cum'].iloc[-1])})

out = pd.DataFrame(rows).sort_values("equity", ascending=False)
out.to_csv("reports/cost_sensitivity.csv", index=False)
print("\nTop 10 by equity:\n", out.head(10).to_string(index=False))
