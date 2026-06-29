import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import ROOT_DIR, settings


def configure_logging() -> None:
    log_dir = ROOT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time_gmtime

    file_handler = RotatingFileHandler(
        log_dir / "marketlab.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def time_gmtime(*args):
    import time

    return time.gmtime(*args)
