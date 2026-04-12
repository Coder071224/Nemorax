"""Logging setup for the Nemorax backend."""

from __future__ import annotations

import logging


_FORMAT = "%(asctime)s %(levelname)s %(name)s :: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=level.upper(), format=_FORMAT)
    else:
        root_logger.setLevel(level.upper())

    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
