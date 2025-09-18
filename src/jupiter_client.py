from __future__ import annotations
import os, json, base64, time
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
import requests
from dotenv import load_dotenv

from solana.rpc.api import Client
from solana.rpc.types import TxOpts

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction  # deserialize/build v0 tx

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT  = "So11111111111111111111111111111111111111112"

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "config" / ".env"

def load_env():
    load_dotenv(ENV_PATH)
    slippage_bps = int(os.getenv("SLIPPAGE_BPS", "25"))
    keypair_path = os.getenv("KEYPAIR_PATH")
    if not keypair_path:
        raise RuntimeError("KEYPAIR_PATH not set in .env")
    test_amount_usdc = Decimal(os.getenv("TEST_SWAP_USDC", "1.50"))
    rpc_url = os.getenv("RPC_PRIMARY", "https://api.mainnet-beta.solana.com")
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    return slippage_bps, keypair_path, test_amount_usdc, rpc_url, dry_run

def load_pubkey_base58(keypair_path: str) -> str:
    key_bytes = bytes(json.loads(Path(keypair_path).read_text()))
    kp = Keypair.from_bytes(key_bytes)
    return str(kp.pubkey())

def jup_quote(amount_usdc: Decimal, slippage_bps: int):
    amt = int((amount_usdc * Decimal(10**6)).to_integral_value(rounding=ROUND_DOWN))
    params = {
        "inputMint": USDC_MINT,
        "outputMint": SOL_MINT,
        "amount": str(amt),
        "slippageBps": str(slippage_bps),
        "onlyDirectRoutes": "false",
        "maxAccounts": "64",
        "restrictIntermediateTokens": "true",
        "asLegacyTransaction": "false",
    }
    r = requests.get("https://quote-api.jup.ag/v6/quote", params=params, timeout=20)
    r.raise_for_status()
    q = r.json()
    if "outAmount" not in q or "routePlan" not in q:
        raise RuntimeError(f"Unexpected quote shape: {q}")
    return q

def jup_swap(quote: dict, user_pubkey: str, slippage_bps: int):
    payload = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "asLegacyTransaction": False,
        "slippageBps": slippage_bps,
    }
    r = requests.post("https://quote-api.jup.ag/v6/swap", json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "swapTransaction" not in data:
        raise RuntimeError(f"No swapTransaction in response: {data}")
    tx_bytes = base64.b64decode(data["swapTransaction"])
    return tx_bytes, data

def _fmt_route(q: dict) -> str:
    parts = []
    for leg in q.get("routePlan", []):
        info = leg.get("swapInfo", {})
        label = info.get("label") or info.get("ammKey") or "unknown"
        ia = Decimal(info.get("inAmount", "0"))  / (Decimal(10) ** int(info.get("inTokenDecimals", 6)))
        oa = Decimal(info.get("outAmount", "0")) / (Decimal(10) ** int(info.get("outTokenDecimals", 9)))
        parts.append(f"{label}: {ia} -> {oa}")
    return " | ".join(parts) if parts else "(single hop)"

def send_tx(tx_bytes: bytes, keypair_path: str, rpc_url: str, dry_run: bool):
    if dry_run:
        print("[send_tx] DRY_RUN is true — skipping send.")
        return None

    # Load keypair (solders)
    key_bytes = bytes(json.loads(Path(keypair_path).read_text()))
    kp = Keypair.from_bytes(key_bytes)

    # Deserialize Jupiter's unsigned v0 tx, then build a **signed** tx using our signer
    unsigned_vtx = VersionedTransaction.from_bytes(tx_bytes)
    signed_vtx = VersionedTransaction(unsigned_vtx.message, [kp])  # <- pass signers, not signatures
    raw = bytes(signed_vtx)

    # Send via RPC
    client = Client(rpc_url)
    resp = client.send_raw_transaction(raw, opts=TxOpts(skip_preflight=False, preflight_commitment="processed"))
    print(f"[send_tx] Sent! Signature: {resp}")
    return str(resp)

def main():
    slippage_bps, keypair_path, test_amount_usdc, rpc_url, dry_run = load_env()
    user_pubkey = load_pubkey_base58(keypair_path)
    print(f"[jupiter_client] Using TEST amount: {test_amount_usdc} USDC | slippage: {slippage_bps} bps | DRY_RUN={dry_run}")
    print(f"[jupiter_client] User pubkey: {user_pubkey}")

    t0 = time.time()
    quote = jup_quote(test_amount_usdc, slippage_bps)
    out_sol = Decimal(quote["outAmount"]) / Decimal(10**9)
    print(f"[quote] out ≈ {out_sol:.9f} SOL | route: {_fmt_route(quote)} | {int((time.time()-t0)*1000)} ms")

    t1 = time.time()
    tx_bytes, swap_resp = jup_swap(quote, user_pubkey, slippage_bps)
    print(f"[swap build] got base64 v0 tx (bytes={len(tx_bytes)}) in {int((time.time()-t1)*1000)} ms | lastValidBlockHeight: {swap_resp.get('lastValidBlockHeight','n/a')}")

    sig = send_tx(tx_bytes, keypair_path, rpc_url, dry_run)
    if sig:
        print(f"[success] tx sig: {sig}")

if __name__ == "__main__":
    main()
