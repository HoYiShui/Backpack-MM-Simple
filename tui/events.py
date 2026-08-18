"""Logging bridge used by the TUI without changing file logging."""
from __future__ import annotations

import logging
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from typing import Deque, Iterator, List, Tuple


class RecentEventHandler(logging.Handler):
    """Keep a compact, human-readable tail of meaningful strategy events."""

    KEYWORDS = (
        "成交",
        "網格利潤",
        "网格利润",
        "補充",
        "补充",
        "重試",
        "重试",
        "重新掛",
        "重新挂",
        "WebSocket",
        "觸發",
        "触发",
        "失敗",
        "失败",
        "錯誤",
        "错误",
    )

    def __init__(self, capacity: int = 50) -> None:
        super().__init__(level=logging.INFO)
        self._events: Deque[Tuple[datetime, int, str]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage().replace("\n", " ").strip()
        except Exception:
            return
        if record.levelno < logging.WARNING and not any(word in message for word in self.KEYWORDS):
            return
        with self._lock:
            self._events.append((datetime.fromtimestamp(record.created), record.levelno, message))

    def tail(self, count: int = 3) -> List[Tuple[datetime, int, str]]:
        with self._lock:
            return list(self._events)[-count:]


def _project_loggers() -> List[logging.Logger]:
    result: List[logging.Logger] = []
    for value in logging.Logger.manager.loggerDict.values():
        if isinstance(value, logging.Logger) and value.handlers:
            result.append(value)
    return result


@contextmanager
def tui_logging(handler: RecentEventHandler) -> Iterator[None]:
    """Mute terminal stream handlers while preserving every file handler."""
    removed: List[Tuple[logging.Logger, logging.Handler]] = []
    loggers = _project_loggers()
    for project_logger in loggers:
        for existing in list(project_logger.handlers):
            if isinstance(existing, logging.StreamHandler) and not isinstance(existing, logging.FileHandler):
                project_logger.removeHandler(existing)
                removed.append((project_logger, existing))
        project_logger.addHandler(handler)

    try:
        yield
    finally:
        for project_logger in loggers:
            project_logger.removeHandler(handler)
        for project_logger, existing in removed:
            project_logger.addHandler(existing)
