# HFTA/logging_utils.py

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


def parse_log_level(level_str: str) -> int:
    """
    Convert a string like 'DEBUG', 'INFO', 'warning' into a logging level.

    If the value is unknown or empty, defaults to DEBUG.
    """
    if not level_str:
        return logging.DEBUG

    level_str = level_str.upper()
    mapping = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }
    return mapping.get(level_str, logging.DEBUG)


def setup_logging(
    name: str,
    log_file: Optional[str] = None,
    level: int = logging.DEBUG,
    log_to_console: bool = True,
) -> logging.Logger:
    """
    Configure root logging so that all HFTA modules share the same handlers.

    - name: the logger name returned to the caller (e.g. "HFTA.engine")
    - log_file: path to a log file (directories are created automatically)
    - level: logging level (DEBUG by default)
    - log_to_console: if True, also log to stderr (console)
    """

    # Root logger — single place where handlers are attached.
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate logs if setup_logging is called multiple times.
    if root.handlers:
        root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (optional)
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # Quiet noisy third-party loggers, but still allow warnings/errors through
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("keyring").setLevel(logging.INFO)
    logging.getLogger("yfinance").setLevel(logging.INFO)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)

    # Return a named logger for the caller’s convenience
    logger = logging.getLogger(name)
    return logger
