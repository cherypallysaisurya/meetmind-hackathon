"""Structured logs: one JSON object per line on stdout. CloudWatch reads these as they are in Phase 4."""

import json
import logging
import time

logger = logging.getLogger("meetmind")


def configure() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({"ts": round(time.time(), 3), "event": event, **fields}, default=str))
