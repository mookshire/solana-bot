import os, logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def project_root() -> Path:
    # src/.. is the project root
    return Path(__file__).resolve().parent.parent

def data_dir() -> Path:
    d = project_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_logger(name: str = "bot"):
    log_path = data_dir() / "bot.log"
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    # also echo to stdout (useful when run in foreground)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger
