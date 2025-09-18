from __future__ import annotations
import os, sys, json, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts

from src.jupiter_client import USDC_MINT, SOL_MINT

ROOT = Path(__file__).resolve().parents[1]

S = requests.Session()
S.headers.update({"accept":"application/json","user-agent":"solana-bot/1.0 (+bot)"})

def _dig(obj: Any, path: list[str]):
    cur = obj
    for k in path:
        try:
            cur = cur.get(k) if isinstance(cur, dict) else getattr(cur, k)
        except Exception:
            return None
        if cur is None:
            return None
    return cur

def usdc_balance(client: Client, owner: Pubkey) -> float:
    """Sum all parsed token accounts for the USDC mint (uiAmount)."""
    opts = TokenAccountOpts(mint=Pubkey.from_string(USDC_MINT), encoding="jsonParsed")
    res = client.get_token_accounts_by_owner_json_parsed(owner, opts)
    total = 0.0
    for it in res.value:
        ui = _dig(it, ["account","data","parsed","info","tokenAmount","uiAmount"])
        if ui:
            try: total += float(ui)
            except Exception: pass
    return total

def get_usdc_per_sol() -> float | None:
    # Try Jupiter price endpoints, then CoinGecko
    try:
        r = S.get("https://price.jup.ag/v4/price", params={"ids":"SOL","vsToken":"USDC"}, timeout=8)
        return float(r.json()["data"]["SOL"]["price"])
    except Exception:
        pass
    try:
        r = S.get("https://price.jup.ag/v6/price", params={"ids":"SOL","vsToken":"USDC"}, timeout=8)
        return float(r.json()["data"]["SOL"]["price"])
    except Exception:
        pass
    try:
        r = S.get("https://api.coingecko.com/api/v3/simple/price", params={"ids":"solana","vs_currencies":"usd"}, timeout=8)
        return float(r.json()["solana"]["usd"])
    except Exception:
        return None

@dataclass
class Cfg:
    rpc: str
    keypair_path: Path
    buy_usdc: float
    min_usdc_reserve: float
    dry_run: bool

def load_cfg() -> Cfg:
    return Cfg(
        rpc=os.environ.get("RPC_URL", "https://api.mainnet-beta.solana.com"),
        keypair_path=Path(os.environ["KEYPAIR_PATH"]),
        buy_usdc=float(os.environ.get("BUY_USDC", "1.00")),
        min_usdc_reserve=float(os.environ.get("MIN_USDC_RESERVE", "50.0")),
        dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
    )

def load_owner_pubkey(p: Path) -> Pubkey:
    arr = json.loads(p.read_text())
    return Keypair.from_bytes(bytes(arr)).pubkey()

def main():
    cfg = load_cfg()
    print(f"[buy_guard] cfg: BUY_USDC={cfg.buy_usdc:.2f}, RESERVE_USDC={cfg.min_usdc_reserve:.2f}, DRY_RUN={cfg.dry_run}")

    client = Client(cfg.rpc)
    owner  = load_owner_pubkey(cfg.keypair_path)
    bal    = usdc_balance(client, owner)
    print(f"[buy_guard] USDC balance={bal:.2f}")

    if bal - cfg.min_usdc_reserve < cfg.buy_usdc:
        need = cfg.buy_usdc + cfg.min_usdc_reserve
        print(f"[buy_guard] SKIP: need >= {need:.2f} USDC (buy+reserve); have {bal:.2f}.")
        return 2

    px = get_usdc_per_sol()
    if px:
        est_sol = cfg.buy_usdc / px
        print(f"[buy_guard] mark ~{px:.4f} USDC/SOL; est receive ~{est_sol:.8f} SOL for {cfg.buy_usdc:.2f} USDC")

    # Call buy_live_once with TEST_SWAP_USDC set so it uses our amount
    env = os.environ.copy()
    env["TEST_SWAP_USDC"] = f"{cfg.buy_usdc:.2f}"
    try:
        print("[buy_guard] running buy_live_once…")
        rc = subprocess.call([sys.executable, "-m", "src.buy_live_once"], cwd=str(ROOT), env=env)
        print(f"[buy_guard] buy_live_once exit {rc}")
        return rc
    except Exception as e:
        print(f"[buy_guard] crashed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
