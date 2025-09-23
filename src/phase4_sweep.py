from __future__ import annotations
import os, json, csv, itertools, subprocess, sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
reports_dir = ROOT / "reports"
runs_dir = reports_dir / "phase4_runs"
runs_dir.mkdir(parents=True, exist_ok=True)

# Base env (symbol/interval/fees/limit, etc.)
BASE_ENV = {
    "BB_SYMBOL":    os.getenv("BB_SYMBOL","SOLUSDC"),
    "BB_INTERVAL":  os.getenv("BB_INTERVAL","15m"),
    "BB_LIMIT":     os.getenv("BB_LIMIT","5000"),
    "EMA_FAST":     os.getenv("EMA_FAST","20"),
    "EMA_SLOW":     os.getenv("EMA_SLOW","55"),
    "ATR_PERIOD":   os.getenv("ATR_PERIOD","14"),
    "FEES_BPS":     os.getenv("FEES_BPS","10"),
    "EQUITY_USD":   os.getenv("EQUITY_USD","10000"),
}

SLs   = [1.0, 1.25, 1.5, 1.75, 2.0]
TPs   = [2.0, 2.5, 3.0, 3.5, 4.0]
RISKS = [0.0025, 0.005, 0.0075]  # 0.25%, 0.5%, 0.75%

results_csv = reports_dir / "phase4_sweep_results.csv"
top_md      = reports_dir / "phase4_sweep_top10.md"

rows = []
combo_id = 0
for sl, tp, rp in itertools.product(SLs, TPs, RISKS):
    combo_id += 1
    env = os.environ.copy()
    env.update(BASE_ENV)
    env["SL_ATR_MULT"] = str(sl)
    env["TP_ATR_MULT"] = str(tp)
    env["RISK_PCT"]    = str(rp)

    # Run the prototype; it writes reports/phase4_with_risk_summary.json
    subprocess.run([sys.executable, str(ROOT / "src" / "backtest_with_risk.py")],
                   check=True, env=env, cwd=str(ROOT))

    # Load summary and store per-run copy
    summary_path = reports_dir / "phase4_with_risk_summary.json"
    data = json.loads(summary_path.read_text())
    run_file = runs_dir / f"run_{combo_id:03d}_sl{sl}_tp{tp}_risk{rp}.json"
    run_file.write_text(json.dumps(data, indent=2))

    rows.append({
        "id": combo_id,
        "symbol": data["symbol"], "interval": data["interval"],
        "ema_fast": data["ema_fast"], "ema_slow": data["ema_slow"],
        "atr_period": data["atr_period"],
        "sl_atr_mult": sl, "tp_atr_mult": tp, "risk_pct": rp,
        "fees_bps": data["fees_bps"],
        "trades": data["trades"], "wins": data["wins"],
        "win_rate": data["win_rate"],
        "equity_start": data["equity_start"], "equity_end": data["equity_end"],
        "pnl_total": data["pnl_total"],
        "return_pct": data["return_pct"],
        "max_drawdown_pct": data["max_drawdown_pct"],
        "score": (data["return_pct"] - 0.5*data["max_drawdown_pct"]) if (data["return_pct"] is not None and data["max_drawdown_pct"] is not None) else None,
    })

# Write CSV
with results_csv.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# Top 10 by score, then by return_pct
sorted_rows = sorted(rows, key=lambda r: (r["score"], r["return_pct"]), reverse=True)[:10]

with top_md.open("w") as f:
    f.write(f"# Phase 4 Sweep — Top 10 (generated {datetime.utcnow().isoformat()}Z)\n\n")
    f.write("|#|SL|TP|Risk|Trades|Win%|Return %|MaxDD %|Score|\n")
    f.write("|-:|--:|--:|---:|----:|---:|------:|------:|----:|\n")
    for i, r in enumerate(sorted_rows, 1):
        f.write(f"|{i}|{r['sl_atr_mult']}|{r['tp_atr_mult']}|{r['risk_pct']}|{r['trades']}|"
                f"{round(r['win_rate'] or 0,2) if r['win_rate'] is not None else 'NA'}|"
                f"{round(r['return_pct'] or 0,3)}|{round(r['max_drawdown_pct'] or 0,3)}|"
                f"{round(r['score'] or 0,3) if r['score'] is not None else 'NA'}|\n")

print("Wrote", results_csv)
print("Wrote", top_md)
