from __future__ import annotations
import os, json, csv, subprocess, sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
reports = ROOT / "reports"
reports.mkdir(parents=True, exist_ok=True)

def run_once(use_risk: int, suffix: str, extra_env: dict):
    env = os.environ.copy()
    env.update(extra_env)
    env["USE_RISK"] = str(use_risk)
    env["REPORT_SUFFIX"] = suffix
    subprocess.run([sys.executable, str(ROOT / "src" / "backtest_with_risk.py")], check=True, env=env, cwd=str(ROOT))
    return json.loads((reports / f"phase4_with_risk_summary{suffix}.json").read_text())

def main():
    # Base env from balanced preset
    base = {
        "BB_SYMBOL": os.getenv("BB_SYMBOL","SOLUSDC"),
        "BB_INTERVAL": os.getenv("BB_INTERVAL","15m"),
        "BB_LIMIT": os.getenv("BB_LIMIT","5000"),
        "EMA_FAST": os.getenv("EMA_FAST","20"),
        "EMA_SLOW": os.getenv("EMA_SLOW","55"),
        "ATR_PERIOD": os.getenv("ATR_PERIOD","14"),
        "SL_ATR_MULT": os.getenv("SL_ATR_MULT","1.5"),
        "TP_ATR_MULT": os.getenv("TP_ATR_MULT","4.0"),
        "RISK_PCT": os.getenv("RISK_PCT","0.005"),
        "FEES_BPS": os.getenv("FEES_BPS","10"),
        "EQUITY_USD": os.getenv("EQUITY_USD","10000"),
        "UNITS_BASELINE": os.getenv("UNITS_BASELINE","1.0"),
    }

    risk = run_once(1, "_risk", base)
    base_res = run_once(0, "_baseline", base)

    # Write CSV
    csv_path = reports / "phase4_compare_baseline_vs_risk.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "mode","trades","win_rate","return_pct","max_drawdown_pct","pnl_total",
            "ema_fast","ema_slow","sl_atr_mult","tp_atr_mult","risk_pct","units_baseline"
        ])
        w.writeheader()
        w.writerow({k:risk.get(k) for k in w.fieldnames})
        w.writerow({k:base_res.get(k) for k in w.fieldnames})

    # Write Markdown
    md_path = reports / "phase4_compare_baseline_vs_risk.md"
    def fmt(x, nd=3):
        return "NA" if x is None else (str(round(x,nd)))
    with md_path.open("w") as f:
        f.write(f"# Baseline vs Risk — {datetime.utcnow().isoformat()}Z\n\n")
        f.write("|Mode|Trades|Win %|Return %|MaxDD %|PnL|\n|---|---:|---:|---:|---:|---:|\n")
        f.write(f"|Risk|{risk['trades']}|{fmt(risk['win_rate'],2)}|{fmt(risk['return_pct'])}|{fmt(risk['max_drawdown_pct'])}|{fmt(risk['pnl_total'])}|\n")
        f.write(f"|Baseline|{base_res['trades']}|{fmt(base_res['win_rate'],2)}|{fmt(base_res['return_pct'])}|{fmt(base_res['max_drawdown_pct'])}|{fmt(base_res['pnl_total'])}|\n")
        if risk["max_drawdown_pct"] and base_res["max_drawdown_pct"] and base_res["max_drawdown_pct"]>0:
            rrr = (risk["return_pct"]/risk["max_drawdown_pct"]) if risk["max_drawdown_pct"] else None
            brr = (base_res["return_pct"]/base_res["max_drawdown_pct"])
            f.write(f"\n**Return/DD:** risk={fmt(rrr,3)}, baseline={fmt(brr,3)}\n")

    print("Wrote", csv_path)
    print("Wrote", md_path)

if __name__ == "__main__":
    main()
