import sqlite3
from pathlib import Path
from .utils import project_root

DB_PATH = project_root() / "data" / "trades.sqlite"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  side TEXT CHECK(side IN ('BUY','SELL')) NOT NULL,
  symbol TEXT NOT NULL,
  size_usdc REAL NOT NULL,
  price REAL NOT NULL,
  tx_sig TEXT,
  pnl REAL,
  mode TEXT NOT NULL,         -- DRY_RUN/TEST/PROD
  dry_run INTEGER NOT NULL,   -- 1/0
  note TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  symbol TEXT NOT NULL,
  price REAL NOT NULL,
  signal TEXT NOT NULL,       -- BUY/SELL/HOLD
  reason TEXT
);

CREATE TABLE IF NOT EXISTS equity (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  equity_usdc REAL NOT NULL,
  drawdown_pct REAL
);

CREATE TABLE IF NOT EXISTS prices_hourly (
  ts TEXT PRIMARY KEY,        -- ISO8601 hour (UTC)
  symbol TEXT NOT NULL,       -- e.g., SOL/USDC
  price REAL NOT NULL
);
"""

def ensure_parent():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def connect():
    ensure_parent()
    return sqlite3.connect(DB_PATH)

def init_db():
    ensure_parent()
    with connect() as cx:
        cx.executescript(SCHEMA)
        cx.commit()
    return DB_PATH

def upsert_prices(symbol: str, rows):
    """
    rows: iterable of (ts_iso, price)
    """
    with connect() as cx:
        cx.executemany(
            "INSERT OR REPLACE INTO prices_hourly(ts, symbol, price) VALUES (?,?,?)",
            [(ts, symbol, float(p)) for ts, p in rows],
        )
        cx.commit()

def fetch_prices(symbol: str, limit: int = 24*8):
    """
    Return latest `limit` rows for symbol sorted ascending by ts.
    """
    with connect() as cx:
        cur = cx.execute(
            "SELECT ts, price FROM prices_hourly WHERE symbol=? ORDER BY ts ASC LIMIT ? OFFSET (SELECT COUNT(*) FROM prices_hourly WHERE symbol=?) - ?",
            (symbol, limit, symbol, limit),
        )
        return cur.fetchall()

def insert_decision(ts_iso: str, symbol: str, price: float, signal: str, reason: str = ""):
    with connect() as cx:
        cx.execute(
            "INSERT INTO decisions(ts, symbol, price, signal, reason) VALUES (?,?,?,?,?)",
            (ts_iso, symbol, float(price), signal, reason),
        )
        cx.commit()

def insert_trade_sim(ts_iso: str, side: str, symbol: str, size_usdc: float, price: float, mode: str, note: str = ""):
    with connect() as cx:
        cx.execute(
            "INSERT INTO trades(ts, side, symbol, size_usdc, price, tx_sig, pnl, mode, dry_run, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts_iso, side, symbol, float(size_usdc), float(price), None, None, mode, 1, note),
        )
        cx.commit()
