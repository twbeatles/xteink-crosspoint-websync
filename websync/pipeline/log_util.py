"""파이프라인 로그 헬퍼."""

from __future__ import annotations

from typing import Callable, Optional


def make_pipeline_logger(logger, log_callback: Optional[Callable[[str], None]]):
    """logger + optional GUI callback 로 로그 함수 생성."""

    def log(msg: str) -> None:
        logger.info(msg)
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    return log
