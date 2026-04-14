"""Logging helpers for the application."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure a basic application-wide logging format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)
