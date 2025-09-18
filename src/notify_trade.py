from __future__ import annotations
import os, sqlite3
from pathlib import Path
from datetime import datetime
from src.notify import send_text

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "data" / "trades.sqlite"

def fetch_last():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""SELECT ts, side, symbol, in_amount, out_amount, price_usdc, price, tx_sig
                   FROM trades
                   WHERE tx_sig IS NOT NULL AND tx_sig!=''
                   ORDER BY ts DESC LIMIT 1""")
    row = cur.fetchone()
    conn.close()
    return row

def fmt(row):
    ts, side, sym, ina, outa, pxu, px, sig = row
    # compute price if needed
    price = None
    for cand in (pxu, px):
        try:
            if cand is not None: price = float(cand); break
        except: pass
    if price is None:
        try:
            if str(side).upper().startswith("BUY"):
                price = float(ina)/float(outa) if float(outa)>0 else None
            else:
                price = float(outa)/float(ina) if float(ina)>0 else None
        except: pass
    ts_h = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    px_s = f"{price:.4f}" if isinstance(price,(int,float)) else "?"
    link = f"https://solscan.io/tx/{sig}"
    return f"✅ {side} {sym or 'SOL_USDC'} @ ${px_s} | in={ina} out={outa} | {ts_h} | {link}"

def main():
    try:
        row = fetch_last()
        if not row:
            print("[notify_trade] no rows with tx_sig yet")
            return 0
        msg = fmt(row)
        print(f"[notify_trade] {msg}")
        send_text(msg)
        return 0
    except Exception as e:
        print(f"[notify_trade] error: {e}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
