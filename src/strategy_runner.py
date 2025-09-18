from __future__ import annotations
import os, json, time, subprocess, sqlite3
from pathlib import Path
from datetime import datetime, timezone

DRY_RUN    = os.getenv("DRY_RUN", "true").lower() in ("1","true","yes")
BUY_SCRIPT = os.getenv("BUY_SCRIPT",  "src/buy_live_once.py")
SELL_SCRIPT= os.getenv("SELL_SCRIPT", "src/sell_execute.py")
STATE_FILE = Path(os.getenv("STATE_FILE", "data/last_action.json"))
POLL_SECS  = int(os.getenv("POLL_SECS", "60"))
TEST_ACTION= os.getenv("TEST_ACTION", "").strip().upper()  # optional, one-shot force

DB_PATH    = Path(os.getenv("SIGNALS_DB", "data/signals.sqlite"))

from src.signal_mtf import latest_signal  # noqa: E402

def db_init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc TEXT NOT NULL,
        symbol TEXT, interval TEXT, bias_interval TEXT,
        last_time TEXT, last_price REAL,
        ema9 REAL, ema21 REAL, rsi REAL, macd_hist REAL,
        vol REAL, vol_sma20 REAL, sma200 REAL,
        bias_ok INTEGER, signal TEXT, action TEXT, reason TEXT,
        filters_json TEXT, raw_json TEXT
    );
    """)
    con.commit()
    con.close()

def db_log(sig: dict):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
      INSERT INTO signals
      (ts_utc, symbol, interval, bias_interval, last_time, last_price,
       ema9, ema21, rsi, macd_hist, vol, vol_sma20, sma200,
       bias_ok, signal, action, reason, filters_json, raw_json)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        sig["now_utc"], sig["symbol"], sig["interval"], sig["bias_interval"],
        str(sig["last_time"]), float(sig["last_price"]),
        float(sig["ema9"]), float(sig["ema21"]), float(sig["rsi"]), float(sig["macd_hist"]),
        float(sig["vol"]), float(sig["vol_sma20"]), float(sig["sma200"]),
        1 if bool(sig["bias_ok"]) else 0, sig["signal"], sig["action"], sig["reason"],
        json.dumps(sig["filters"]), json.dumps(sig),
    ))
    con.commit()
    con.close()

def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"last_action": "HOLD", "last_time": None}

def write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def run_cmd(cmd: list[str]) -> int:
    try:
        print(f"→ running: {' '.join(cmd)}")
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        print(p.stdout.strip())
        if p.stderr.strip():
            print("STDERR:", p.stderr.strip())
        return p.returncode
    except Exception as e:
        print("ERROR running command:", e)
        return 1

def maybe_execute(action: str) -> None:
    if action == "BUY_SOL":
        if DRY_RUN:
            print("DRY_RUN=on → would BUY")
        else:
            if Path(BUY_SCRIPT).exists():
                run_cmd(["python", BUY_SCRIPT])
            else:
                print(f"BUY script missing: {BUY_SCRIPT}")
    elif action == "SELL_SOL":
        if DRY_RUN:
            print("DRY_RUN=on → would SELL")
        else:
            if Path(SELL_SCRIPT).exists():
                run_cmd(["python", SELL_SCRIPT])
            else:
                print(f"SELL script missing: {SELL_SCRIPT}")

def loop_once() -> dict:
    db_init()
    sig = latest_signal()

    # Optional one-shot forced action for wiring tests
    if TEST_ACTION in ("BUY_SOL", "SELL_SOL"):
        sig["action"] = TEST_ACTION
        sig["reason"] = f"FORCED via TEST_ACTION={TEST_ACTION}"

    # Summary + JSON
    print(f"{sig['now_utc']} | {sig['symbol']} {sig['interval']} | "
          f"price={sig['last_price']:.3f} rsi={sig['rsi']:.1f} "
          f"ema9/21={sig['ema9']:.2f}/{sig['ema21']:.2f} "
          f"bias_ok={sig['bias_ok']} action={sig['action']} reason={sig['reason']}")
    print(json.dumps(sig))

    # Log to SQLite
    db_log(sig)

    # Fire only on action change
    state = read_state()
    last_action = state.get("last_action", "HOLD")
    if sig["action"] in ("BUY_SOL", "SELL_SOL") and sig["action"] != last_action:
        print(f"✳️ action changed: {last_action} → {sig['action']}")
        maybe_execute(sig["action"])
        state = {"last_action": sig["action"],
                 "last_time": sig.get("last_time"),
                 "updated_utc": datetime.now(timezone.utc).isoformat()}
        write_state(state)
    else:
        state["updated_utc"] = datetime.now(timezone.utc).isoformat()
        write_state(state)

    return sig

def main():
    once = os.getenv("RUN_ONCE","0") in ("1","true","yes")
    if once:
        loop_once()
        return
    print("strategy_runner starting… (Ctrl+C to stop)")
    while True:
        loop_once()
        time.sleep(POLL_SECS)

if __name__ == "__main__":
    main()
