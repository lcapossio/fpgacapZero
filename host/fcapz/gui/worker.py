# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Background capture and connect so the Qt event loop stays responsive."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ..analyzer import Analyzer, CaptureConfig
from .connect_errors import format_connect_error
from .settings import ConnectionSettings
from .transport_from_settings import transport_from_connection

_log = logging.getLogger("fcapz.gui.capture")
_conn_log = logging.getLogger("fcapz.gui.connect")


class CaptureWorker(QObject):
    """Runs :meth:`~fcapz.analyzer.Analyzer.capture` on a :class:`~PySide6.QtCore.QThread`."""

    finished = Signal(object)
    """``CaptureResult`` after a single capture, or ``None`` after continuous mode stops."""

    failed = Signal(str)
    progress = Signal(object)
    """Emitted for each completed capture in continuous mode."""

    def __init__(self, analyzer: Analyzer) -> None:
        super().__init__()
        self._analyzer = analyzer
        self._cancel_cont = False

    def reset_cancel(self) -> None:
        self._cancel_cont = False

    def cancel_continuous(self) -> None:
        self._cancel_cont = True

    def run_single(self, cfg: CaptureConfig, timeout: float) -> None:
        try:
            self._analyzer.configure(cfg)
            self._analyzer.arm()
            result = self._analyzer.capture(timeout)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 — surfaced via GUI
            _log.exception("Single capture failed")
            self.failed.emit(str(exc))

    def run_continuous(self, cfg: CaptureConfig, timeout: float) -> None:
        try:
            self.reset_cancel()
            self._analyzer.configure(cfg)
            while not self._cancel_cont:
                self._analyzer.arm()
                result = self._analyzer.capture(timeout)
                self.progress.emit(result)
            self.finished.emit(None)
        except Exception as exc:  # noqa: BLE001
            _log.exception("Continuous capture failed")
            self.failed.emit(str(exc))


class ConnectWorker(QObject):
    """Background connect: build transport, ``Analyzer.connect()``, ``probe()``."""

    finished = Signal(object, object)
    """``(analyzer, probe_info)`` on success."""

    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, conn: ConnectionSettings) -> None:
        super().__init__()
        self._conn = conn
        self._cancel_requested = False
        self._transport: object | None = None

    def request_cancel(self) -> None:
        """Ask the worker to stop; closes the transport from any thread (may unblock I/O)."""
        self._cancel_requested = True
        t = self._transport
        if t is not None:
            try:
                close = getattr(t, "close", None)
                if callable(close):
                    close()
            except OSError:
                pass

    def run(self) -> None:
        if self._cancel_requested:
            self.cancelled.emit()
            return
        analyzer: Analyzer | None = None
        try:
            transport = transport_from_connection(self._conn)
            self._transport = transport
            if self._cancel_requested:
                transport.close()
                self.cancelled.emit()
                return
            analyzer = Analyzer(transport)
            analyzer.connect()
            if self._cancel_requested:
                analyzer.close()
                self.cancelled.emit()
                return
            info = analyzer.probe()
        except Exception as exc:  # noqa: BLE001 — surfaced via GUI
            if self._cancel_requested:
                if analyzer is not None:
                    try:
                        analyzer.close()
                    except OSError:
                        pass
                self.cancelled.emit()
                return
            _conn_log.exception("Connect worker failed")
            self.failed.emit(format_connect_error(exc, self._conn))
            return
        self.finished.emit(analyzer, info)
