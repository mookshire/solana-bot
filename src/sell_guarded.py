from __future__ import annotations
import os, sys, sqlite3, json, subprocess, time
from pathlib import Path
from dataclasses import dataclass
import requests
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from src.jupiter_client import USDC_MINT, SOL_MINT

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "trades.sqlite"

SESSION = requests.Session()
SESSION.headers.update({
    "accept": "application/json",
    "user-agent": "solana-bot/1.0 (+https://example.local)"
})

@dataclass
class Cfg:
    rpc: str
    keypair_path: Path
    sell_min_profit_bps: int
    min_sell_sol: float
    min_sol_reserve: float

def load_cfg() -> Cfg:
    return Cfg(
        rpc=os.environ.get("RPC_URL", "https://api.mainnet-beta.solana.com"),
        keypair_path=Path(os.environ["KEYPAIR_PATH"]),
        sell_min_profit_bps=int(os.environ.get("SELL_MIN_PROFIT_BPS", "50")),
        min_sell_sol=float(os.environ.get("MIN_SELL_SOL", "0.010")),
        min_sol_reserve=float(os.environ.get("MIN_SOL_RESERVE", "0.020")),
    )

def pubkey_from_keypair(p: Path) -> Pubkey:
    arr = json.loads(p.read_text())
    kp = Keypair.from_bytes(bytes(arr))
    return kp.pubkey()

def get_sol_balance(client: Client, pubkey: Pubkey) -> float:
    lamports = client.get_balance(pubkey).value
    return lamports / 1_000_000_000

def get_usdc_per_sol(max_retries: int = 3) -> float | None:
    # Try Jupiter QUOTE v6 with three sizes
    amounts = [1_000_000_000, 500_000_000, 100_000_000]  # 1.0 / 0.5 / 0.1 SOL
    for amount in amounts:
        for _ in range(max_retries):
            try:
                r = SESSION.get(
                    "https://quote-api.jup.ag/v6/quote",
                    params={"inputMint": SOL_MINT, "outputMint": USDC_MINT, "amount": amount},
                    timeout=12,
                )
                j = r.json()
                data = j.get("data") or []
                if data:
                    px = int(data[0]["outAmount"]) / 1_000_000.0
                    print(f"[sell_guard] price source=quote v6, size={amount/1e9:g} SOL -> {px:.4f} USDC/SOL")
                    return px
            except Exception:
                time.sleep(0.4)
                continue
    # Fallback: Jupiter PRICE v4
    try:
        r = SESSION.get("https://price.jup.ag/v4/price", params={"ids": "SOL", "vsToken": "USDC"}, timeout=8)
        px = float(r.json()["data"]["SOL"]["price"])
        print(f"[sell_guard] price source=price v4 -> {px:.4f} USDC/SOL")
        return px
    except Exception:
        pass
    # Fallback: Jupiter PRICE v6
    try:
        r = SESSION.get("https://price.jup.ag/v6/price", params={"ids": "SOL", "vsToken": "USDC"}, timeout=8)
        px = float(r.json()["data"]["SOL"]["price"])
        print(f"[sell_guard] price source=price v6 -> {px:.4f} USDC/SOL")
        return px
    except Exception:
        pass
    # Final fallback: CoinGecko
    try:
        r = SESSION.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": "solana", "vs_currencies": "usd"}, timeout=8)
        px = float(r.json()["solana"]["usd"])
        print(f"[sell_guard] price source=coingecko -> {px:.4f} USDC/SOL")
        return px
    except Exception:
        return None

def last_buy_price_usdc() -> float | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for col in ("price_usdc", "price"):
        try:
            cur.execute(
                f"SELECT {col} FROM trades WHERE side LIKE 'BUY%' AND tx_sig IS NOT NULL ORDER BY ts DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                try:
                    return float(row[0])
                except Exception:
                    continue
        except sqlite3.OperationalError:
            continue
    return None

def main():
    cfg = load_cfg()
    print(f"[sell_guard] cfg: PROFIT_BPS={cfg.sell_min_profit_bps}, MIN_SELL_SOL={cfg.min_sell_sol}, RESERVE={cfg.min_sol_reserve}")

    client = Client(cfg.rpc)
    pubkey = pubkey_from_keypair(cfg.keypair_path)
    bal = get_sol_balance(client, pubkey)
    if bal - cfg.min_sol_reserve < cfg.min_sell_sol:
        print(f"[sell_guard] SKIP: balance {bal:.6f} SOL too small after reserve {cfg.min_sol_reserve} (need >= {cfg.min_sell_sol}).")
        return 2

    last_buy = last_buy_price_usdc()
    now_px = get_usdc_per_sol()
    if now_px is None:
        print("[sell_guard] SKIP: price unavailable (all sources failed); will retry next loop.")
        return 2
    if last_buy is None:
        print(f"[sell_guard] WARN: no prior BUY price found; skipping SELL for safety. (now {now_px:.4f} USDC/SOL)")
        return 2

    need = last_buy * (1 + cfg.sell_min_profit_bps / 10_000.0)
    if now_px < need:
        print(f"[sell_guard] SKIP: now {now_px:.4f} < target {need:.4f} (last_buy {last_buy:.4f} + {cfg.sell_min_profit_bps}bps).")
        return 2

    print(f"[sell_guard] OK: now {now_px:.4f} >= target {need:.4f}; running sell_execute…")
    rc = subprocess.call([sys.executable, "-m", "src.sell_execute"], cwd=str(ROOT))
    print(f"[sell_guard] sell_execute exit {rc}")
    return rc

if __name__ == "__main__":
    sys.exit(main())
