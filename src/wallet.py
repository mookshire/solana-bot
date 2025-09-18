import os, json
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts

USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

def _env_path():
    return os.path.join(os.path.dirname(__file__), "..", "config", ".env")

def load_env():
    load_dotenv(_env_path())
    rpc = os.getenv("RPC_PRIMARY") or "https://api.mainnet-beta.solana.com"
    key_path = os.getenv("KEYPAIR_PATH")
    return rpc, key_path

def load_keypair(path: str) -> Keypair:
    with open(path, "r") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return Keypair.from_bytes(bytes(raw))
    if isinstance(raw, str):
        return Keypair.from_base58_string(raw)
    raise ValueError("Unsupported key format in keypair file")

def client_for(rpc_url: str) -> Client:
    return Client(rpc_url)

def sol_balance_lamports(c: Client, pub: Pubkey) -> int:
    return c.get_balance(pub).value

def usdc_balance_ui(c: Client, owner: Pubkey) -> float:
    # Use Pubkey (not str) for mint param
    resp = c.get_token_accounts_by_owner(owner, TokenAccountOpts(mint=USDC_MINT)).value
    if not resp:
        return 0.0
    ata: Pubkey = resp[0].pubkey  # already a Pubkey
    bal = c.get_token_account_balance(ata).value
    return float(bal.ui_amount or 0.0)
