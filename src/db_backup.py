from __future__ import annotations
import os, sqlite3, gzip, shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "data" / "trades.sqlite"
OUT  = ROOT / "data" / "backups"
OUT.mkdir(parents=True, exist_ok=True)

ts   = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
tmp  = OUT / f"trades-{ts}.sqlite"
dest = OUT / f"{tmp.name}.gz"

# Make a consistent copy using sqlite backup API
src = sqlite3.connect(DB)
dst = sqlite3.connect(tmp)
with dst:
    src.backup(dst)
dst.close(); src.close()

# Compress and remove the temp
with open(tmp, "rb") as fi, gzip.open(dest, "wb") as fo:
    shutil.copyfileobj(fi, fo)
tmp.unlink(missing_ok=True)

# Retention
keep = int(os.getenv("BACKUP_KEEP", "30"))
files = sorted(OUT.glob("trades-*.sqlite.gz"))
if len(files) > keep:
    for old in files[: len(files) - keep]:
        try: old.unlink()
        except Exception: pass

print(f"[backup] wrote {dest}  | keep={keep}")
