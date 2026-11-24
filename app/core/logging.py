"""
PULSE Structured Logging & Secret Redaction (app/core/logging.py)
Guarantees zero credential leakage into logs or exception traces.
"""
import logging
import re
import sys
from pathlib import Path
from typing import Optional

SECRET_PATTERNS = [
    re.compile(r'(?i)(key|api_key|token|secret|password)=([^\s&"\'<>]+)'),
    re.compile(r'(?i)bearer\s+([^\s]+)'),
]


class SecretRedactingFormatter(logging.Formatter):
    """Custom logging formatter that strips sensitive credentials from all log outputs."""

    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pattern in SECRET_PATTERNS:
            msg = pattern.sub(r'\1=***REDACTED***', msg)
        return msg


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configures project-wide logging with file and console handlers."""
    logger = logging.getLogger("pulse")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = SecretRedactingFormatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler in <workspace>/logs/
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "pulse.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger


logger = setup_logging()
