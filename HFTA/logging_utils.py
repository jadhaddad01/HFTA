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
    log_to_console: bool = False,
) -> logging.Logger:
    """
    Configure *root* logging so that ALL HFTA modules share the same handlers.

    - name: logger name returned for convenience (e.g. "HFTA.engine")
    - log_file: path to log file (directories are created automatically)
    - level: logging level (DEBUG by default)
    - log_to_console: if True, logs also go to the terminal
    """

    # Configure the root logger; all other loggers will propagate to it.
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate logs if called multiple times
    if root.handlers:
        root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Optional console handler
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    # Optional file handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # Return a named logger for the caller, but everything now uses root handlers
    logger = logging.getLogger(name)
    return logger
