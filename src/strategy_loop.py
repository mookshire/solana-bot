import os, json
from dotenv import load_dotenv
from .utils import get_logger
from .store import init_db, upsert_prices, fetch_prices, insert_decision, insert_trade_sim
from .indicators import sma, slope_simple
from .price_sources import fetch_price_usd, iso_hour_now_utc
from .positions import get_open_position, open_position, close_position

SYMBOL = "SOL/USDC"

def as_bool(x, default=False):
    if x is None: return default
    return str(x).strip().lower() in ("1","true","yes","y","on")

def load_cfg_and_strategy():
    here = os.path.dirname(__file__)
    load_dotenv(os.path.join(here, "..", "config", ".env"))
    cfg = {
        "DRY_RUN": as_bool(os.getenv("DRY_RUN"), True),
        "TEST_MODE": as_bool(os.getenv("TEST_MODE"), True),
        "PROD_MODE": as_bool(os.getenv("PROD_MODE"), False),
        "BOT_ENABLED": as_bool(os.getenv("BOT_ENABLED"), True),
    }
    with open(os.path.join(here, "..", "config", "strategy.json")) as f:
        strat = json.load(f)
    return cfg, strat

def decide_entry(price, prices, strat):
    need_sma, need_trend = 24*7, 24*3
    if len(prices) < min(need_sma, need_trend):
        return "HOLD", f"insufficient_history:{len(prices)}"
    s7d = sum(prices[-need_sma:]) / need_sma
    slope = (prices[-1] - prices[-need_trend]) / (need_trend - 1)
    discount = float(strat["buy_rule"]["discount_pct"]) / 100.0
    if price <= s7d * (1.0 - discount) and slope >= 0:
        return "BUY", f"price<=SMA7d*(1-{discount}) and slope>=0 (SMA7d={s7d:.4f}, slope={slope:.6f})"
    return "HOLD", f"no_buy_condition (SMA7d={s7d:.4f}, slope={slope:.6f})"

def decide_exit(price, entry_price, strat):
    tp = float(strat["sell_rule"]["take_profit_pct"]) / 100.0
    sl = float(strat["sell_rule"]["stop_loss_pct"]) / 100.0
    if price >= entry_price * (1.0 + tp):
        return "SELL", f"take_profit_hit +{tp*100:.2f}% (entry={entry_price:.4f})"
    if price <= entry_price * (1.0 - sl):
        return "SELL", f"stop_loss_hit -{sl*100:.2f}% (entry={entry_price:.4f})"
    return "HOLD", "hold_position"

def main():
    logger = get_logger("bot")
    init_db()
    cfg, strat = load_cfg_and_strategy()
    if not cfg["BOT_ENABLED"]:
        print("BOT_DISABLED"); logger.warning("BOT_ENABLED=false -> exiting"); return

    # fetch current price, persist to hourly table
    price, source = fetch_price_usd()
    ts = iso_hour_now_utc()
    upsert_prices(SYMBOL, [(ts, price)])
    rows = fetch_prices(SYMBOL, limit=24*7)
    prices = [p for _, p in rows]

    pos = get_open_position(SYMBOL)
    if pos is None:
        # consider new entry
        signal, reason = decide_entry(price, prices, strat)
        insert_decision(ts, SYMBOL, price, signal, reason)
        logger.info("Decision (flat) %s @ %s price=%.6f source=%s reason=%s", signal, ts, price, source, reason)
        print(f"FLAT: {signal} price={price} source={source} rows={len(prices)}")
        if cfg['DRY_RUN'] and signal == "BUY":
            usdc_size = float(strat["sizing"]["test_mode_fixed_usdc"])
            open_position(SYMBOL, entry_price=price, size_usdc=usdc_size, ts=ts)
            insert_trade_sim(ts, "BUY", SYMBOL, usdc_size, price, "DRY_RUN", "simulated_entry")
            logger.info("Simulated BUY opened @ %.6f size %.2f USDC", price, usdc_size)
    else:
        pid, sym, entry_price, size_usdc, ts_open = pos
        signal, reason = decide_exit(price, entry_price, strat)
        insert_decision(ts, SYMBOL, price, signal, reason)
        logger.info("Decision (in-pos) %s @ %s price=%.6f entry=%.6f reason=%s", signal, ts, price, entry_price, reason)
        print(f"IN-POS: {signal} price={price} entry={entry_price} size={size_usdc} source={source}")
        if cfg['DRY_RUN'] and signal == "SELL":
            close_position(SYMBOL)
            insert_trade_sim(ts, "SELL", SYMBOL, size_usdc, price, "DRY_RUN", "simulated_exit")
            logger.info("Simulated SELL closed @ %.6f size %.2f USDC", price, size_usdc)

if __name__ == "__main__":
    main()
