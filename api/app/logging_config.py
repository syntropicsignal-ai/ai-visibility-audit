from __future__ import annotations

import logging
import os
import sys


_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(log_format, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    logging.getLogger("app").setLevel(logging.INFO)

    sql_level = logging.DEBUG if os.environ.get("LOG_SQL") else logging.WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(sql_level)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).propagate = False

    _CONFIGURED = True
