from __future__ import annotations
import os, time, traceback
from src.jupiter_client import ROOT, load_env

LOG_PATH = ROOT / "data" / "bot.log"

def log_line(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [sell_logic] {msg}\n")
    print(msg)


def main():
    import os, time, traceback
    from src.jupiter_client import load_env

    # Read .env, then allow a per-run override via DRY_RUN env var
    env = load_env()  # (..., dry_run, test_cap)
    dry_run = (env[4].lower() == 'true') if isinstance(env[4], str) else bool(env[4])
    ov = os.getenv('DRY_RUN')
    if ov is not None:
        dry_run = (ov.lower() == 'true')

    bot_enabled = os.getenv("BOT_ENABLED", "true").lower() == "true"
    if not bot_enabled:
        print("[sell_logic] BOT_ENABLED=false; skipping.")
        return

    log_line(f"Starting sell cycle | DRY_RUN={dry_run}")

    # 1) Evaluate plan
    try:
        from src.sell_check import main as sell_check_main
        os.environ['DRY_RUN'] = 'true' if dry_run else 'false'
        sell_check_main()
    except Exception as e:
        log_line(f"ERROR in sell_check: {e!r}")
        traceback.print_exc()
        return  # don't attempt execute if check failed

    # 2) Execute if plan says SELL (executor itself decides)
    try:
        from src.sell_execute import main as sell_execute_main
        os.environ['DRY_RUN'] = 'true' if dry_run else 'false'
        sell_execute_main(dry_run=dry_run)
    except Exception as e:
        log_line(f"ERROR in sell_execute: {e!r}")
        traceback.print_exc()

    log_line("Sell cycle complete.")


if __name__ == "__main__":
    main()