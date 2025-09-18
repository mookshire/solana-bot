from __future__ import annotations
import os, sys, sqlite3, json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any
from collections import defaultdict

from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from src.pnl import get_mark_usdc_per_sol, iter_trades  # reuse helpers

ROOT = Path(__file__).resolve().parents[1]
ENV  = ROOT / "config" / ".env"
DATA = ROOT / "data"
DB   = DATA / "trades.sqlite"

COOLDOWN_BUY  = DATA / "next_buy_at.txt"
COOLDOWN_SELL = DATA / "next_sell_at.txt"

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC (6dp)

def load_env():
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

def read_dt(p: Path) -> Optional[datetime]:
    try:
        if p.exists():
            return datetime.fromisoformat(p.read_text().strip())
    except Exception:
        pass
    return None

def fmt_cooldown(name: str, p: Path):
    dt = read_dt(p)
    now = datetime.now()
    if not dt: return f"{name}: none"
    if dt <= now: return f"{name}: ready"
    rem = int((dt - now).total_seconds() // 60)
    return f"{name}: {dt.strftime('%H:%M')} (~{rem}m)"

def load_pubkey() -> Pubkey:
    kp_path = Path(os.environ["KEYPAIR_PATH"])
    arr = json.loads(kp_path.read_text())
    kp  = Keypair.from_bytes(bytes(arr))
    return kp.pubkey()

def sol_balance(client: Client, owner: Pubkey) -> float:
    return client.get_balance(owner).value / 1_000_000_000

def _dig(obj: Any, path: list[str]):
    cur = obj
    for key in path:
        try:
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                cur = getattr(cur, key)
        except Exception:
            return None
        if cur is None:
            return None
    return cur

def usdc_balance(client: Client, owner: Pubkey) -> float:
    opts = TokenAccountOpts(mint=Pubkey.from_string(USDC_MINT), encoding="jsonParsed")
    res = client.get_token_accounts_by_owner_json_parsed(owner, opts)
    total = 0.0
    for it in res.value:
        ui_amt = _dig(it, ["account", "data", "parsed", "info", "tokenAmount", "uiAmount"])
        if ui_amt:
            try:
                total += float(ui_amt)
            except Exception:
                continue
    return total

def human_ts(ts_val) -> str:
    try:
        ts_i = int(ts_val)
        return datetime.fromtimestamp(ts_i).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_val)

def fetch_trades(n=10):
    if not DB.exists():
        return []
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(
        """SELECT ts, side, symbol, in_amount, out_amount, price_usdc, price, tx_sig
           FROM trades
           ORDER BY ts DESC LIMIT ?""",
        (n,),
    )
    rows = cur.fetchall()
    out = []
    for ts, side, sym, in_amt, out_amt, px_usdc, px_legacy, tx_sig in rows:
        px = None
        for cand in (px_usdc, px_legacy):
            try:
                if cand is not None:
                    px = float(cand)
                    break
            except Exception:
                pass
        if px is None:
            try:
                if str(side).upper().startswith("BUY"):
                    if out_amt and float(out_amt) > 0:
                        px = float(in_amt) / float(out_amt)
                else:
                    if in_amt and float(in_amt) > 0:
                        px = float(out_amt) / float(in_amt)
            except Exception:
                px = None
        out.append({
            "ts": human_ts(ts),
            "side": side,
            "sym": sym or "SOL_USDC",
            "in": in_amt,
            "out": out_amt,
            "px": px,
            "tx": bool(tx_sig),
        })
    return out

def compute_pnl():
    realized_by_day = defaultdict(float)
    pos_sol, cost_usdc = 0.0, 0.0
    for ts, side, in_amt, out_amt in iter_trades():
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        if side.startswith("BUY"):
            pos_sol += out_amt
            cost_usdc += in_amt
        elif side.startswith("SELL"):
            if pos_sol > 1e-12:
                avg_cost = cost_usdc / pos_sol
                basis = min(cost_usdc, in_amt * avg_cost)
            else:
                basis = 0.0
            realized_by_day[day] += (out_amt - basis)
            pos_sol   = max(0.0, pos_sol - in_amt)
            cost_usdc = max(0.0, cost_usdc - basis)
    total_realized = sum(realized_by_day.values())
    avg_cost = (cost_usdc / pos_sol) if pos_sol > 1e-12 else 0.0
    mark = get_mark_usdc_per_sol()
    unreal = (mark - avg_cost) * pos_sol if (mark is not None and pos_sol > 0) else 0.0
    return realized_by_day, total_realized, pos_sol, avg_cost, mark, unreal

def main():
    load_env()
    rpc = os.environ.get("RPC_URL", "https://api.mainnet-beta.solana.com")
    client = Client(rpc)
    owner = load_pubkey()

    print("== Bot Status ==")
    print(f"AUTO_ENABLE_BUY={os.getenv('AUTO_ENABLE_BUY')}, AUTO_ENABLE_SELL={os.getenv('AUTO_ENABLE_SELL')}")
    print(f"INTERVAL_SEC={os.getenv('BOT_INTERVAL_SEC')}, BUY_COOLDOWN_MIN={os.getenv('BUY_COOLDOWN_MIN')}, SELL_COOLDOWN_MIN={os.getenv('SELL_COOLDOWN_MIN')}")
    print(f"SELL_MIN_PROFIT_BPS={os.getenv('SELL_MIN_PROFIT_BPS')}, MIN_SELL_SOL={os.getenv('MIN_SELL_SOL')}, MIN_SOL_RESERVE={os.getenv('MIN_SOL_RESERVE')}")
    print(fmt_cooldown("next BUY", COOLDOWN_BUY), " | ", fmt_cooldown("next SELL", COOLDOWN_SELL))

    try:
        sol = sol_balance(client, owner)
    except Exception:
        sol = float("nan")
    try:
        usdc = usdc_balance(client, owner)
    except Exception:
        usdc = float("nan")
    print(f"Balances → SOL={sol:.6f}, USDC={usdc:.2f}")

    trades = fetch_trades(10)
    if trades:
        print("\nLast trades:")
        for t in trades:
            px_s = f"{t['px']:.4f}" if isinstance(t['px'], (int, float)) and t['px'] else "-"
            mark = "✓" if t["tx"] else " "
            print(f"  {t['ts']}  {t['side']:<8} {t['sym']:<9} px={px_s:<10} in={t['in']!s:<10} out={t['out']!s:<10} tx={mark}")

    # --- PnL summary ---
    try:
        realized_by_day, total, pos_sol, avg_cost, mark, unreal = compute_pnl()
        print("\nPnL (realized by day):")
        for day in sorted(realized_by_day.keys()):
            v = realized_by_day[day]
            print(f"  {day}: {'+' if v>=0 else '-'}${abs(v):.2f}")
        print(f"Total realized: {'+' if total>=0 else '-'}${abs(total):.2f}")
        if mark is None:
            print(f"Open position: {pos_sol:.6f} SOL @ avg {avg_cost:.4f} | mark n/a")
        else:
            print(f"Open position: {pos_sol:.6f} SOL @ avg {avg_cost:.4f} | mark {mark:.4f} → unrealized {'+' if unreal>=0 else '-'}${abs(unreal):.2f}")
    except Exception as e:
        print(f"\nPnL: error computing summary: {e}")

if __name__ == "__main__":
    main()
