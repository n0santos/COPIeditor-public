import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_LOG_PATH = Path(os.getenv("DATA_DIR", "data")) / "guest_access.log"
_logger: logging.Logger | None = None


def _build_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"guest_access_{log_path}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            str(log_path), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


def log_guest_access(ip: str, method: str, path: str) -> None:
    global _logger
    if _logger is None:
        _logger = _build_logger(_DEFAULT_LOG_PATH)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    _logger.info("%s | %s | %s | %s", ts, ip, method, path)
