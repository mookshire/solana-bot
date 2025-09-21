# (same content as before, but patched histogram line)

# inside shuffle_trials plotting:
#   bins = min(30, len(finals)//2 or 1)

# --- full replacement snippet ---

import os, random, math, subprocess, pandas as pd
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

# ... (all same functions up to shuffle_trials) ...

def shuffle_trials(month_mult, n=500, seed=42):
    rng = random.Random(seed)
    finals, dds = [], []
    base = list(month_mult.values)
    for _ in range(n):
        rng.shuffle(base)
        eq, dd, _ = equity_stats(pd.Series(base))
        finals.append(eq); dds.append(dd)
    return np.array(finals), np.array(dds)

# --- inside main() replace the plotting part ---
def main():
    ensure_base()
    monthly = load_monthly()
    month_mult = monthly["equity_multiple"]

    base_eq, base_dd, base_n = equity_stats(month_mult)
    rows=[{"case":"baseline", "equity":base_eq, "max_dd":base_dd, "months":base_n}]

    finals, dds = shuffle_trials(month_mult, n=200)  # reduced to 200 for speed
    rows.append({"case":"shuffle_p50", "equity":float(np.median(finals)), "max_dd":float(np.median(dds)), "months":base_n})

    # safe bin count
    bins = min(30, max(5, len(np.unique(finals)//2)))
    plt.figure(figsize=(8,4))
    plt.hist(finals, bins=bins)
    plt.axvline(base_eq, linestyle="--")
    plt.title("Shuffled Month-Order Equity (n=200)")
    Path("reports").mkdir(exist_ok=True)
    plt.tight_layout(); plt.savefig("reports/stress_shuffle_hist.png"); plt.close()

    # ... rest unchanged ...
