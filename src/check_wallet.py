import os
from .wallet import load_env, load_keypair, client_for, sol_balance_lamports, usdc_balance_ui

def main():
    rpc, key_path = load_env()
    print("RPC:", rpc)
    print("KEYPAIR_PATH:", key_path)
    if not key_path or not os.path.isfile(key_path):
        print("ERROR: keypair file not found at:", key_path or "<unset>")
        return
    try:
        kp = load_keypair(key_path)
    except Exception as e:
        print("ERROR loading keypair:", e)
        return
    c = client_for(rpc)
    pub = kp.pubkey()
    lamports = sol_balance_lamports(c, pub)
    sol = lamports / 1_000_000_000
    usdc = usdc_balance_ui(c, pub)
    print("Public Key:", str(pub))
    print(f"SOL balance: {sol:.9f} SOL")
    print(f"USDC balance: {usdc:.6f} USDC")

if __name__ == "__main__":
    main()
