from __future__ import annotations
"""
Logging utilities.

Creates:
- a console logger
- a rotating file handler writing to logs directory from config

Usage:
    from utils.logger import configure_logging, get_logger
    configure_logging(logs_dir=Path("logs"))
    logger = get_logger(__name__)
    logger.info("started")
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_BACKUP_COUNT = 5


def configure_logging(
    logs_dir: Optional[Path] = None,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> None:
    """
    Configure root logger with console and rotating file handler.

    :param logs_dir: Path to directory to store logs. If None, uses './logs'.
    """
    if logs_dir is None:
        logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        # Avoid adding multiple handlers if configure_logging is called repeatedly
        return

    root.setLevel(level)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch_formatter = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    ch.setFormatter(ch_formatter)
    root.addHandler(ch)

    # Rotating file handler
    log_file = logs_dir / "z3_strategy.log"
    fh = RotatingFileHandler(str(log_file), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    fh.setLevel(level)
    fh_formatter = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s:%(lineno)d] %(message)s")
    fh.setFormatter(fh_formatter)
    root.addHandler(fh)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Return a logger with the provided name (or root logger if None).
    Ensure configure_logging was called before using; if not, call with defaults.
    """
    root = logging.getLogger()
    if not root.handlers:
        configure_logging()
    return logging.getLogger(name)
