import os, random, subprocess, pandas as pd
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

OUT_DIR = Path("reports"); OUT_DIR.mkdir(parents=True, exist_ok=True)
BASE_MONTHLY = Path("data/backtests/walk_bb_ema_regime_v5.csv")  # monthly rows with ym, equity_multiple, etc.

def ensure_base():
    if BASE_MONTHLY.exists(): return
    env = os.environ.copy(); env["PYTHONPATH"]="."
    print("[RUN] baseline walk-forward to produce", BASE_MONTHLY)
    subprocess.run(["python3","-u","src/walkforward_offline.py"], check=True, env=env)
    if not BASE_MONTHLY.exists():
        raise SystemExit("baseline monthly CSV missing after run")

def load_monthly():
    df = pd.read_csv(BASE_MONTHLY, parse_dates=["ym"])
    if "equity_multiple" not in df.columns:
        raise SystemExit("Expected 'equity_multiple' column in monthly CSV.")
    return df

def equity_stats(mult_series: pd.Series):
    eq_curve = mult_series.cumprod()
    dd = eq_curve / eq_curve.cummax() - 1.0
    return float(eq_curve.iat[-1]), float(dd.min()), len(eq_curve)

def shuffle_trials(month_mult: pd.Series, n=200, seed=42):
    rng = random.Random(seed)
    finals, dds = [], []
    base = list(month_mult.values)
    for _ in range(n):
        rng.shuffle(base)
        eq, dd, _ = equity_stats(pd.Series(base))
        finals.append(eq); dds.append(dd)
    return np.array(finals), np.array(dds)

def block_bootstrap_trials(month_mult: pd.Series, block=3, n=200, seed=123):
    rng = random.Random(seed)
    arr = list(month_mult.values); L = len(arr)
    finals, dds = [], []
    for _ in range(n):
        seq = []
        while len(seq) < L:
            i = rng.randrange(0, max(1, L-block+1))
            seq.extend(arr[i:i+block])
        seq = seq[:L]
        eq, dd, _ = equity_stats(pd.Series(seq))
        finals.append(eq); dds.append(dd)
    return np.array(finals), np.array(dds)

def subperiods(month_mult: pd.Series, windows=(24,36)):
    rows=[]
    for w in windows:
        if len(month_mult) < w: continue
        for label, seg in [("first", month_mult.iloc[:w]), ("last", month_mult.iloc[-w:])]:
            eq, dd, n = equity_stats(seg.reset_index(drop=True))
            rows.append({"case": f"{label}_{w}m", "equity": eq, "max_dd": dd, "months": n})
        for i in range(0, len(month_mult)-w+1, 3):
            seg = month_mult.iloc[i:i+w]
            eq, dd, n = equity_stats(seg.reset_index(drop=True))
            rows.append({"case": f"roll_{w}m@{i}", "equity": eq, "max_dd": dd, "months": n})
    return pd.DataFrame(rows)

def alt_symbols(symbols=("BTCUSDT","ETHUSDT")):
    rows=[]
    for sym in symbols:
        env = os.environ.copy(); env.update({"PYTHONPATH":".","SYMBOL":sym})
        print(f"[TRY] alt symbol {sym}")
        try:
            subprocess.run(["python3","-u","src/walkforward_offline.py"], check=True, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            df = pd.read_csv(BASE_MONTHLY)
            if "equity_multiple" not in df.columns: continue
            eq, dd, n = equity_stats(df["equity_multiple"])
            rows.append({"case": f"symbol_{sym}", "equity": eq, "max_dd": dd, "months": n})
        except Exception as e:
            print(f"[SKIP] {sym}: {e}")
    return pd.DataFrame(rows)

def main():
    ensure_base()
    monthly = load_monthly()
    month_mult = monthly["equity_multiple"]

    # baseline
    base_eq, base_dd, base_n = equity_stats(month_mult)
    rows=[{"case":"baseline", "equity":base_eq, "max_dd":base_dd, "months":base_n}]

    # shuffled
    finals, dds = shuffle_trials(month_mult, n=200)
    rows.append({"case":"shuffle_p50", "equity":float(np.median(finals)), "max_dd":float(np.median(dds)), "months":base_n})
    # histogram with safe bin count
    unique_vals = max(1, len(np.unique(finals)))
    bins = max(5, min(30, unique_vals))
    plt.figure(figsize=(8,4))
    plt.hist(finals, bins=bins)
    plt.axvline(base_eq, linestyle="--")
    plt.title("Shuffled Month-Order Equity (n=200)")
    plt.tight_layout(); plt.savefig(OUT_DIR/"stress_shuffle_hist.png"); plt.close()

    # block bootstrap
    bfinals, bdds = block_bootstrap_trials(month_mult, block=3, n=200)
    rows.append({"case":"block3_p50", "equity":float(np.median(bfinals)), "max_dd":float(np.median(bdds)), "months":base_n})

    # subperiods (median of rolling windows)
    subdf = subperiods(month_mult)
    for w in (24,36):
        wdf = subdf[subdf['case'].str.startswith(f"roll_{w}m")]
        if len(wdf):
            rows.append({"case":f"roll_{w}m_med", "equity":float(wdf['equity'].median()), "max_dd":float(wdf['max_dd'].median()), "months":w})

    # alt symbols (best-effort)
    rows.extend(alt_symbols().to_dict("records"))

    out = pd.DataFrame(rows)
    out.to_csv(OUT_DIR/"stress_tests.csv", index=False)
    print("wrote", OUT_DIR/"stress_tests.csv")
    print(out.to_string(index=False))

if __name__ == "__main__":
    main()
