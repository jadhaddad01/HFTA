# HFTA/logging_utils.py

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


def parse_log_level(level_str: str) -> int:
    """
    Convert a string like 'DEBUG', 'INFO', 'warning' into a logging level.
    Defaults to DEBUG if unknown.
    """
    if not level_str:
        return logging.DEBUG
    level_str = level_str.upper()
    return {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }.get(level_str, logging.DEBUG)


def setup_logging(
    name: str,
    log_file: Optional[str] = None,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """
    Configure and return a logger that logs to both stdout and (optionally) a file.

    - name: logger name, e.g. "HFTA.backtest"
    - log_file: path to log file (directories are created automatically)
    - level: logging level (DEBUG by default)
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # avoid double logging via root

    # If logger already has handlers, just update their level and return it.
    if logger.handlers:
        for h in logger.handlers:
            h.setLevel(level)
        return logger

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # Optional file handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger
