import os, subprocess, pandas as pd

w_trains  = [6, 9, 12]
min_bars  = [800, 900, 950]

rows = []
for w in w_trains:
    for m in min_bars:
        env = os.environ.copy()
        env["PYTHONPATH"] = "."
        env["W_TRAIN"]    = str(w)
        env["MIN_BARS"]   = str(m)
        print(f"running W_TRAIN={w}, MIN_BARS={m}")
        subprocess.run(["python3", "-u", "src/walkforward_offline.py"], env=env, check=True)
        df = pd.read_csv("data/backtests/walk_bb_ema_regime_v5_equity.csv")
        strat = float(df["strat_cum"].iloc[-1])
        bh    = float(df["bh_cum"].iloc[-1]) if "bh_cum" in df.columns else None
        ratio = (strat / bh) if bh and bh != 0 else None
        rows.append({"w_train": w, "min_bars": m, "equity": strat, "bh": bh, "ratio": ratio})

out = pd.DataFrame(rows).sort_values("equity", ascending=False)
out.to_csv("reports/window_sensitivity.csv", index=False)
print("\nTop configs by equity:\n", out.head(10).to_string(index=False))
