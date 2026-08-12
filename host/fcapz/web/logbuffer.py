# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""In-memory ring buffer of recent fcapz log records for the web Log tab.

Backend diagnostics — JTAG readback fallbacks, connection notices, transport
warnings — normally reach only the server's stderr, invisible to someone using
the browser UI on another machine. This attaches a bounded logging handler to
the ``fcapz`` logger and exposes the newest records over ``GET /api/logs`` so
the Log tab can surface them. Each record carries a monotonic sequence number
so the client fetches only what is new; a bounded deque caps memory use.
"""

from __future__ import annotations

import logging
from collections import deque
from threading import Lock
from typing import Any, Deque, Optional


class RingLogHandler(logging.Handler):
    """Logging handler that keeps the newest ``capacity`` records in memory."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._buf: Deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = Lock()
        self._seq = 0
        self._dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        # Never let logging-of-a-log raise into the emitting thread.
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            msg = str(record.msg)
        with self._lock:
            self._seq += 1
            if self._buf.maxlen is not None and len(self._buf) == self._buf.maxlen:
                self._dropped += 1
            self._buf.append(
                {
                    "seq": self._seq,
                    "ts": record.created,
                    "level": record.levelname,
                    "name": record.name,
                    "msg": msg,
                }
            )

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        """Records with ``seq > since``, plus the latest seq and drop count."""
        with self._lock:
            lines = [r for r in self._buf if r["seq"] > since]
            return {"lines": lines, "next": self._seq, "dropped": self._dropped}

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


_RING: Optional[RingLogHandler] = None


def install_log_capture(
    capacity: int = 2000, level: int = logging.INFO
) -> RingLogHandler:
    """Attach the ring handler to the ``fcapz`` logger once; return the singleton.

    Idempotent: repeated calls (e.g. a second ``create_app``) reuse the same
    handler. Raises the ``fcapz`` logger level to ``level`` if it is stricter,
    so INFO diagnostics propagate even when the app never configured logging
    (the root logger defaults to WARNING).
    """
    global _RING
    if _RING is None:
        _RING = RingLogHandler(capacity)
        _RING.setLevel(logging.NOTSET)  # let the logger's level do the filtering
        logger = logging.getLogger("fcapz")
        logger.addHandler(_RING)
        if logger.level == logging.NOTSET or logger.level > level:
            logger.setLevel(level)
    return _RING


def get_ring() -> Optional[RingLogHandler]:
    return _RING
