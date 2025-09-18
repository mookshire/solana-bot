
import sys, time, json, argparse, requests
from pathlib import Path
from datetime import datetime, timezone

API = "https://api.binance.com/api/v3/klines"
MS_15M = 15 * 60 * 1000

def ts(ms): return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

def fetch(symbol:str, interval:str, start_ms:int, limit:int=1000):
    r = requests.get(API, params=dict(symbol=symbol, interval=interval, startTime=start_ms, limit=limit), timeout=20)
    r.raise_for_status()
    return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("interval", choices=["15m"])
    ap.add_argument("outfile")
    args = ap.parse_args()

    symbol = args.symbol.upper()
    out = Path(args.outfile)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Load/initialize cache
    data = []
    if out.exists():
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
            if not isinstance(data, list): data = []
        except Exception:
            data = []
    last_open = data[-1][0] if data else 0
    start_ms = last_open + 1 if last_open else 0

    print(f"Resuming for {symbol} {args.interval}: have {len(data)} bars; starting from {ts(start_ms) if start_ms else 'earliest'}")

    session = requests.Session()
    total_new = 0
    while True:
        try:
            chunk = fetch(symbol, args.interval, start_ms, limit=1000)
        except Exception as e:
            print(f"Request error: {e} — sleeping 5s and retrying...")
            time.sleep(5)
            continue

        if not chunk:
            print("No more data returned. Done.")
            break

        # Dedup by open time
        if data and chunk[0][0] <= data[-1][0]:
            chunk = [row for row in chunk if row[0] > data[-1][0]]
        if not chunk:
            print("Chunk fully overlapped; advancing…")
            start_ms += 1000 * MS_15M
            continue

        data.extend(chunk)
        total_new += len(chunk)
        start_ms = chunk[-1][0] + 1

        # Persist after every chunk
        out.write_text(json.dumps(data), encoding="utf-8")

        print(f"Appended {len(chunk)} bars — total {len(data)} "
              f"(range {ts(data[0][0])} → {ts(data[-1][0])}); next {ts(start_ms)}")

        # polite rate-limit
        time.sleep(0.25)

    print(f"Saved {len(data)} bars to {out}")
if __name__ == "__main__":
    main()
