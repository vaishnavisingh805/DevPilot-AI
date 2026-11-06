"""Structured logging setup with Rich console formatting."""

import logging
import sys
from rich.logging import RichHandler
from config.settings import settings


def setup_logger(name: str = "MultiAgentSE") -> logging.Logger:
    """Configures structured logger with Rich handler."""
    logger = logging.getLogger(name)
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    if not logger.handlers:
        console_handler = RichHandler(
            rich_tracebacks=True,
            show_time=True,
            show_path=False,
        )
        console_handler.setLevel(level)
        formatter = logging.Formatter("%(message)s")
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


system_logger = setup_logger()

