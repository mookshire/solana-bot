from __future__ import annotations
import json, os, sys, time, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)

HEARTBEAT = DATA / "heartbeat.txt"
STATEFILE = DATA / "watchdog_state.json"

WINDOW_S = int(os.getenv("WATCHDOG_ALERT_WINDOW_S", "120"))
THRESH   = int(os.getenv("WATCHDOG_ALERT_THRESHOLD", "2"))

def heartbeat_age_s() -> float:
    try:
        return max(0.0, time.time() - (HEARTBEAT.stat().st_mtime))
    except Exception:
        return 10**9

def read_state():
    try:
        if STATEFILE.exists():
            return json.loads(STATEFILE.read_text() or "{}") or {"restarts": []}
    except Exception:
        pass
    return {"restarts": []}

def write_state(st):
    try:
        STATEFILE.write_text(json.dumps(st))
    except Exception as e:
        print(f"[watchdog] WARN: failed to write state: {e}", file=sys.stderr)

def restart_bot():
    print("[watchdog] restarting solana-bot.service …")
    subprocess.run(["systemctl", "restart", "solana-bot.service"], check=False)

def main():
    age = int(heartbeat_age_s())
    print(f"[watchdog] heartbeat age={age}s (<= {WINDOW_S}s?)  DATA={DATA}")
    if age <= WINDOW_S:
        print("[watchdog] healthy ✔")
        return 0
    st = read_state()
    now = int(time.time())
    st.setdefault("restarts", []).append(now)
    st["restarts"] = [t for t in st["restarts"] if now - t <= WINDOW_S]
    write_state(st)
    if len(st["restarts"]) > THRESH:
        print(f"[watchdog] too many restarts in {WINDOW_S}s (>{THRESH}); exiting 2")
        return 2
    restart_bot()
    return 0

if __name__ == "__main__":
    sys.exit(main())
