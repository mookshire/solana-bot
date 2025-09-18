from __future__ import annotations
import sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "data" / "trades.sqlite"

def main():
    print(f"[db_maint] opening {DB}")
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Quick integrity check
    ok = True
    rows = list(cur.execute("PRAGMA quick_check"))
    print("[db_maint] quick_check:", rows)
    if not rows or rows[0][0] != "ok":
        ok = False

    # Analyze & vacuum regardless (helps size/plan quality)
    print("[db_maint] ANALYZE…")
    cur.execute("ANALYZE")
    print("[db_maint] VACUUM…")
    cur.execute("VACUUM")
    con.commit()
    con.close()
    print("[db_maint] done")

    # non-zero exit if integrity failed so systemd surfaces it
    return 0 if ok else 2

if __name__ == "__main__":
    raise SystemExit(main())
