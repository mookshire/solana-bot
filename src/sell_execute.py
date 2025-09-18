from __future__ import annotations
import os, json, time, base64, sqlite3
from decimal import Decimal
from pathlib import Path
import requests

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.api import Client

DB_PATH   = os.environ.get("DB_PATH", "data/trades.sqlite")
PLAN_PATH = os.environ.get("SELL_PLAN_PATH", "data/sell_plan.json")
LOG_PATH  = os.environ.get("BOT_LOG_PATH", "data/bot.log")

SOL_MINT   = os.environ.get("SOL_MINT",  "So11111111111111111111111111111111111111112")
USDC_MINT  = os.environ.get("USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

RPC_URL     = os.environ["RPC_URL"]
KEYPAIR_PATH= os.environ["KEYPAIR_PATH"]

TEST_MODE = os.environ.get("TEST_MODE", "true").lower() == "true"
JUP_URL   = "https://quote-api.jup.ag/v6"

def log_line(msg: str) -> None:
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [sell_execute] {msg}\n")
    print(f"[sell_execute] {msg}")

def load_keypair_from_cli_json(path: str) -> Keypair:
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, list):
        return Keypair.from_bytes(bytes(raw))
    raise ValueError("Unsupported keypair format; expected Solana CLI JSON array")

def jup_quote(in_mint: str, out_mint: str, amount_int: int) -> dict:
    params = {
        "inputMint":  in_mint,
        "outputMint": out_mint,
        "amount":     str(amount_int),
        "slippageBps": os.environ.get("SLIPPAGE_BPS", "50"),
        "platformFeeBps": os.environ.get("PLATFORM_FEE_BPS", "0"),
        "swapMode": "ExactIn",
        "asLegacyTransaction": "false",
        "onlyDirectRoutes": "false",
        "dominantQuote": "true",
        "restrictIntermediateTokens": "true",
        "prioritizationFeeLamports": os.environ.get("PRIO_FEE_LAMPORTS", "auto"),
    }
    return requests.get(f"{JUP_URL}/quote", params=params, timeout=25).json()

def jup_swap_tx(quote: dict, user_pubkey: str) -> str:
    payload = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }
    return requests.post(f"{JUP_URL}/swap", json=payload, timeout=25).json()["swapTransaction"]

def insert_trade(
    ts: int, side: str, symbol: str, size_usdc: float, size_real: float,
    price: float, tx_sig: str | None, mode: str, dry_run: bool,
    base_mint: str, quote_mint: str, in_amount: float, out_amount: float
) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trades (
            ts, side, symbol, size_usdc, size_real, price, tx_sig,
            mode, dry_run, base_mint, quote_mint, in_amount, out_amount
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts, side, symbol, float(size_usdc), float(size_real), float(price),
            tx_sig, mode, bool(dry_run), base_mint, quote_mint,
            float(in_amount), float(out_amount),
        ),
    )
    conn.commit()
    conn.close()

def main(dry_run: bool | None = None) -> None:
    if dry_run is None:
        env_dr = os.environ.get("DRY_RUN", "true" if TEST_MODE else "false").lower() == "true"
        dry_run = env_dr

    plan = json.loads(Path(PLAN_PATH).read_text())
    decision = (plan.get("decision") or "").upper()
    qty_sol = Decimal(str(plan.get("sell_qty_sol") or plan.get("sell_qty") or 0))
    if decision != "SELL" or qty_sol <= 0:
        log_line(f"Skipping: decision={decision!r}, qty_sol={qty_sol}.")
        return

    client = Client(RPC_URL)
    kp = load_keypair_from_cli_json(KEYPAIR_PATH)
    user_pubkey = str(kp.pubkey())

    in_amount_sol = qty_sol
    in_amount_lamports = int(in_amount_sol * Decimal(1_000_000_000))

    quote = jup_quote(SOL_MINT, USDC_MINT, in_amount_lamports)
    out_amount_usdc = Decimal(quote.get("outAmount", 0)) / Decimal(1_000_000)
    price_usdc_per_sol = (out_amount_usdc / in_amount_sol) if in_amount_sol > 0 else Decimal(0)

    tx_sig: str | None = None
    if not dry_run:
        b64_tx = jup_swap_tx(quote, user_pubkey)
        vt = VersionedTransaction.from_bytes(base64.b64decode(b64_tx))
        signed = VersionedTransaction(vt.message, [kp])
        tx_sig = str(client.send_raw_transaction(bytes(signed)).value)
        log_line(f"✅ Sent. Signature: {tx_sig}")
        log_line(f"Solscan: https://solscan.io/tx/{tx_sig}")

    now_ts = int(time.time())
    insert_trade(
        ts=now_ts,
        side="SELL",
        symbol="SOL_USDC",
        size_usdc=float(out_amount_usdc),
        size_real=float(in_amount_sol),
        price=float(price_usdc_per_sol),
        tx_sig=tx_sig,
        mode="PROD" if not TEST_MODE else "TEST",
        dry_run=bool(dry_run),
        base_mint=SOL_MINT,
        quote_mint=USDC_MINT,
        in_amount=float(in_amount_sol),
        out_amount=float(out_amount_usdc),
    )
    log_line(f"Recorded SELL: {in_amount_sol} SOL -> {out_amount_usdc:.4f} USDC @ {price_usdc_per_sol:.4f} USDC/SOL")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_line(f"ERROR: {e!r}")
        raise
