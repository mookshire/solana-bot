from typing import Optional, Tuple
from .store import connect

def get_open_position(symbol: str) -> Optional[Tuple[int, str, float, float, str]]:
    """
    Returns (id, symbol, entry_price, size_usdc, ts) for open position, or None.
    """
    with connect() as cx:
        cx.execute("""
            CREATE TABLE IF NOT EXISTS positions (
              id INTEGER PRIMARY KEY,
              symbol TEXT NOT NULL,
              entry_price REAL NOT NULL,
              size_usdc REAL NOT NULL,
              ts TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('OPEN','CLOSED'))
            )
        """)
        row = cx.execute("SELECT id, symbol, entry_price, size_usdc, ts FROM positions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1", (symbol,)).fetchone()
        return row if row else None

def open_position(symbol: str, entry_price: float, size_usdc: float, ts: str) -> int:
    with connect() as cx:
        cx.execute("""
            INSERT INTO positions(symbol, entry_price, size_usdc, ts, status)
            VALUES (?,?,?,?, 'OPEN')
        """, (symbol, float(entry_price), float(size_usdc), ts))
        cx.commit()
        pid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
        return pid

def close_position(symbol: str) -> None:
    with connect() as cx:
        cx.execute("UPDATE positions SET status='CLOSED' WHERE symbol=? AND status='OPEN'", (symbol,))
        cx.commit()
