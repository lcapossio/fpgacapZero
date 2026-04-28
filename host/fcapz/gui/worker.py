# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Background capture and connect so the Qt event loop stays responsive."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Signal, Slot

from ..analyzer import Analyzer, CaptureConfig
from ..transport import connect_timing_logs_enabled, list_xilinx_hw_server_targets
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

    def __init__(
        self,
        analyzer: Analyzer,
        *,
        inter_cycle_delay_s: float = 0.0,
    ) -> None:
        super().__init__()
        self._analyzer = analyzer
        self._cancel_cont = False
        self._inter_cycle_delay_s = max(0.0, float(inter_cycle_delay_s))
        self._pending_cfg: CaptureConfig | None = None
        self._pending_timeout: float = 1.0
        self._pending_auto_rearm: bool = False
        self._pending_immediate: bool = False

    def set_pending_run(
        self,
        cfg: CaptureConfig,
        timeout: float,
        *,
        auto_rearm: bool,
        immediate: bool,
    ) -> None:
        """Read by :meth:`thread_started` after ``QThread.started`` (do not use ``partial``)."""
        self._pending_cfg = cfg
        self._pending_timeout = float(timeout)
        self._pending_auto_rearm = auto_rearm
        self._pending_immediate = immediate

    @Slot()
    def thread_started(self) -> None:
        cfg = self._pending_cfg
        if cfg is None:
            _log.warning("CaptureWorker.thread_started with no pending config")
            return
        timeout = self._pending_timeout
        if self._pending_auto_rearm:
            self.run_auto_rearm(cfg, timeout, immediate=self._pending_immediate)
        else:
            self.run_single(cfg, timeout, immediate=self._pending_immediate)

    def reset_cancel(self) -> None:
        self._cancel_cont = False

    def cancel_continuous(self) -> None:
        self._cancel_cont = True

    def _sleep_interruptible(self, seconds: float) -> None:
        if seconds <= 0.0:
            return
        end = time.monotonic() + seconds
        while not self._cancel_cont and time.monotonic() < end:
            remaining = end - time.monotonic()
            if remaining <= 0.0:
                break
            time.sleep(min(0.05, remaining))

    def run_single(self, cfg: CaptureConfig, timeout: float, *, immediate: bool) -> None:
        try:
            use = self._analyzer.immediate_variant(cfg) if immediate else cfg
            self._analyzer.configure(use)
            self._analyzer.arm()
            result = self._analyzer.capture(timeout)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 — surfaced via GUI
            _log.exception("Single capture failed")
            self.failed.emit(str(exc))

    def run_auto_rearm(self, cfg: CaptureConfig, timeout: float, *, immediate: bool) -> None:
        try:
            self.reset_cancel()
            while not self._cancel_cont:
                use = self._analyzer.immediate_variant(cfg) if immediate else cfg
                self._analyzer.configure(use)
                self._analyzer.arm()
                result = self._analyzer.capture(timeout)
                self.progress.emit(result)
                self._sleep_interruptible(self._inter_cycle_delay_s)
            self.finished.emit(None)
        except Exception as exc:  # noqa: BLE001
            _log.exception("Auto re-arm capture failed")
            self.failed.emit(str(exc))


class ConnectWorker(QObject):
    """Background connect: build transport, ``Analyzer.connect()``, ``probe_optional()``."""

    finished = Signal(object, object)
    """``(analyzer, probe_info)`` on success; ``probe_info`` is ``None`` if USER1 has no ELA."""

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
            t0 = time.monotonic()
            transport = transport_from_connection(self._conn)
            t_build = time.monotonic()
            self._transport = transport
            if self._cancel_requested:
                transport.close()
                self.cancelled.emit()
                return
            analyzer = Analyzer(transport)
            c = self._conn
            if c.backend == "hw_server":
                if c.program_on_connect and c.program:
                    _conn_log.info("hw_server: will program bitfile on connect: %s", c.program)
                elif c.program and not c.program_on_connect:
                    _conn_log.warning(
                        "hw_server: connecting without programming; captures reflect the "
                        "bitstream already loaded on the FPGA, not the saved path: %s",
                        c.program,
                    )
                else:
                    _conn_log.warning(
                        "hw_server: no bitfile path; connecting without programming, "
                        "so captures reflect the image already loaded on the FPGA",
                    )
            analyzer.connect()
            t_connect = time.monotonic()
            if self._cancel_requested:
                analyzer.close()
                self.cancelled.emit()
                return
            info = analyzer.probe_optional()
            t_probe = time.monotonic()
            if info is None:
                _conn_log.info(
                    "USER1 has no fcapz ELA ('LA' core id); JTAG session open for "
                    "subsidiary chains (EIO, EJTAG-AXI, UART, …).",
                )
            if connect_timing_logs_enabled():
                _conn_log.info(
                    "GUI connect worker timing: transport_build=%.3fs transport.connect=%.3fs "
                    "probe=%.3fs total=%.3fs",
                    t_build - t0,
                    t_connect - t_build,
                    t_probe - t_connect,
                    t_probe - t0,
                )
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
            if analyzer is not None:
                try:
                    analyzer.close()
                except OSError:
                    pass
            return
        self.finished.emit(analyzer, info)


class TargetScanWorker(QObject):
    """Background XSDB target scan so the connection panel stays responsive."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        host: str,
        port: int,
        timeout_sec: float,
    ) -> None:
        super().__init__()
        self._host = host
        self._port = int(port)
        self._timeout_sec = float(timeout_sec)

    @Slot()
    def run(self) -> None:
        try:
            targets = list_xilinx_hw_server_targets(
                host=self._host,
                port=self._port,
                timeout_sec=self._timeout_sec,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced via GUI
            self.failed.emit(str(exc))
            return
        self.finished.emit(targets)
