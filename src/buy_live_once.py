from __future__ import annotations
import os, time, json, base64, sqlite3
from decimal import Decimal
import requests

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.api import Client

from src.jupiter_client import ROOT, USDC_MINT, SOL_MINT, load_env, load_pubkey_base58

DB_PATH  = ROOT / "data" / "trades.sqlite"
LOG_PATH = ROOT / "data" / "bot.log"

def log_line(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [buy_live_once] {msg}\n")
    print(msg)

def load_keypair_from_cli_json(path: str) -> Keypair:
    with open(path, "r") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return Keypair.from_bytes(bytes(raw))
    raise ValueError("Unsupported keypair format; expected Solana CLI JSON array")

    since = int(time.time()) - 86400
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trades WHERE side='BUY' AND ts >= ?", (since,))
    count = cur.fetchone()[0] or 0
    if count >= max_trades:
        raise RuntimeError(f"TEST_MODE daily cap reached for BUY: {count} >= {max_trades}")

def jup_quote_buy(amount_usdc: Decimal, slippage_bps: int) -> dict:
    params = {
        "inputMint": USDC_MINT,
        "outputMint": SOL_MINT,
        "amount": str(int(amount_usdc * Decimal(10**6))),
        "slippageBps": str(slippage_bps),
        "onlyDirectRoutes": "false",
        "maxAccounts": "64",
        "restrictIntermediateTokens": "true",
        "asLegacyTransaction": "false",
    }
    r = requests.get("https://quote-api.jup.ag/v6/quote", params=params, timeout=20)
    r.raise_for_status()
    q = r.json()
    if "outAmount" not in q:
        raise RuntimeError(f"Unexpected quote response: {q}")
    return q

def jup_swap_from_quote(quote: dict, user_pubkey: str, as_legacy=False) -> str:
    body = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "asLegacyTransaction": bool(as_legacy),
        "wrapAndUnwrapSol": True,
    }
    r = requests.post("https://quote-api.jup.ag/v6/swap", json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "swapTransaction" not in data:
        raise RuntimeError(f"Unexpected swap response: {data}")
    return data["swapTransaction"]

def main():
    slippage_bps, keypair_path, test_amount_usdc, rpc_url, dry_run = load_env()[:5]
    test_cap = load_env()[5] if len(load_env()) > 5 else 1
    test_mode = os.getenv("TEST_MODE", "true").lower() == "true"

    user_pubkey = load_pubkey_base58(keypair_path)
    kp = load_keypair_from_cli_json(keypair_path)
    client = Client(rpc_url)

    amt_usdc = float(Decimal(str(test_amount_usdc)))
    quote = jup_quote_buy(Decimal(str(test_amount_usdc)), slippage_bps)
    out_sol_est = float(Decimal(quote["outAmount"]) / Decimal(10**9))
    price = round(amt_usdc / out_sol_est, 9) if out_sol_est else 0.0

    print(f"[buy_live_once] DRY_RUN={dry_run} | amount={amt_usdc} USDC → ~{out_sol_est:.9f} SOL @ ~${price}")

    if dry_run:
        print("[buy_live_once] DRY_RUN=true → would build/send tx; stopping here.")
        return

    # removed daily cap check
    conn = sqlite3.connect(DB_PATH)
    conn.close()

    b64_tx = jup_swap_from_quote(quote, user_pubkey, as_legacy=False)
    unsigned_vt = VersionedTransaction.from_bytes(base64.b64decode(b64_tx))
    signed_vt = VersionedTransaction(unsigned_vt.message, [kp])
    sig_str = str(client.send_raw_transaction(bytes(signed_vt)).value)

    ts = int(time.time())
    mode_str = "PROD"
    # removed daily cap check
    conn = sqlite3.connect(DB_PATH)
    conn.close()

    solscan = f"https://solscan.io/tx/{sig_str}"
    log_line(f"BOUGHT ~{out_sol_est:.9f} SOL for {amt_usdc} USDC | sig={sig_str} | {solscan}")
    print(f"[buy_live_once] ✅ Sent. Signature: {sig_str}")
    print(f"[buy_live_once] Solscan: {solscan}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_line(f"ERROR: {e!r}")
        raise
