"""Centralised logger configuration for the billing analyser."""
import logging
from core.config import get_log_level


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("billing")
    if logger.handlers:
        return logger

    level_name = get_log_level().upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    ch = logging.StreamHandler()
    ch.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Avoid propagating to root
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return setup_logging()
