import pandas as pd, matplotlib.pyplot as plt
from pathlib import Path

def monthly_report(equity_curve: pd.Series, out_csv="reports/monthly.csv"):
    monthly = equity_curve.resample("M").last().pct_change().fillna(0)
    monthly.to_csv(out_csv)
    return monthly

def plot_equity(equity_df: pd.DataFrame, out_png="reports/equity.png"):
    # expects df with index=datetime/period, columns: strat_cum, pick
    plt.figure(figsize=(12,5))
    plt.plot(equity_df.index, equity_df["strat_cum"], label="Equity", color="black")

    # regime shading
    colors = {"BB":"#cce5ff","EMA":"#ccffcc","BH":"#eeeeee"}
    last_pick = None
    start = None
    for t, pick in equity_df["pick"].items():
        if last_pick is None:
            last_pick, start = pick, t
        elif pick != last_pick:
            plt.axvspan(start, t, color=colors.get(last_pick,"#f0f0f0"), alpha=0.4)
            last_pick, start = pick, t
    # close final span
    if last_pick is not None:
        plt.axvspan(start, equity_df.index[-1], color=colors.get(last_pick,"#f0f0f0"), alpha=0.4)

    # drawdowns
    ec = equity_df["strat_cum"]
    dd = ec / ec.cummax() - 1.0
    dd_points = dd[dd < -0.1]   # mark dd worse than -10%
    plt.scatter(dd_points.index, ec.loc[dd_points.index], color="red", marker="v", s=40, label="Drawdowns")

    plt.title("Equity Curve with Regimes + Drawdowns")
    plt.legend()
    plt.tight_layout()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png)
    plt.close()
