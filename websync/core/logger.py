import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from websync.core.paths import PROJECT_ROOT

_logger_initialized = False
_app_logger = None
_log_handler: RotatingFileHandler | None = None
_log_date: str | None = None


class _DailyRotatingFileHandler(RotatingFileHandler):
    """날짜가 바뀌면 새 로그 파일로 전환합니다."""

    def __init__(self, log_dir: str, **kwargs):
        self._log_dir = log_dir
        self._current_date = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(log_dir, f"sync_{self._current_date}.log")
        super().__init__(log_file, **kwargs)

    def emit(self, record):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            self._current_date = today
            self.baseFilename = os.path.abspath(
                os.path.join(self._log_dir, f"sync_{today}.log")
            )
            if self.stream:
                self.stream.close()
                self.stream = None
            self.stream = self._open()
        super().emit(record)


def get_logger() -> logging.Logger:
    global _logger_initialized, _app_logger, _log_handler, _log_date
    if _logger_initialized and _app_logger is not None:
        return _app_logger

    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    _log_date = datetime.now().strftime("%Y-%m-%d")

    logger = logging.getLogger("x3_websync")
    logger.setLevel(logging.DEBUG)

    fh = _DailyRotatingFileHandler(
        log_dir, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    _log_handler = fh

    if sys.stdout and hasattr(sys.stdout, "write"):
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)

    logger.addHandler(fh)
    _app_logger = logger
    _logger_initialized = True
    return logger


def get_log_dir() -> str:
    return os.path.join(PROJECT_ROOT, "logs")
