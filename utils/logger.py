"""Small logging helper so every module logs in the same format."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a module logger. Configures the root handler once."""
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        )
        root = logging.getLogger("smm")
        if not root.handlers:
            root.addHandler(handler)
        root.setLevel(logging.INFO)
        _CONFIGURED = True
    return logging.getLogger(f"smm.{name}")
