# -*- coding: utf-8 -*-
"""Logging: timestamps in UTC+8, written to stdout and a mounted log file."""
import logging
import os
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("MINERU_WEB_DATA_DIR", "/data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
TZ = ZoneInfo("Asia/Shanghai")


class _TZFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        from datetime import datetime
        return datetime.fromtimestamp(record.created, TZ).isoformat(timespec="milliseconds")


def setup_logging(level=logging.INFO):
    root = logging.getLogger()
    root.setLevel(level)
    fmt = _TZFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(LOG_DIR, "app.log"),
                                 maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:  # pragma: no cover - logging must never crash the app
        root.warning("Could not create file log handler", exc_info=True)

    return logging.getLogger("mineru_web")
