# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Serialized JSON-RPC gateway shared by all web clients.

The web frontend speaks the **same** ``cmd``-based JSON-RPC protocol as
``python -m fcapz.rpc`` (stdin/stdout) — one unified API, just a different
transport.  This wraps a single :class:`~fcapz.rpc.RpcServer` behind a lock
(JTAG is one physical resource) and returns the identical success/error
envelopes the line-protocol server returns.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from ..rpc import _SCHEMA_VERSION, RpcServer, error_envelope

_log = logging.getLogger("fcapz.web")

# High-frequency pollers: kept out of the activity log so a steady arm-wait or
# EIO refresh doesn't drown the interesting commands (connect/capture/arm).
_QUIET_CMDS = frozenset({"capture_status", "eio_read"})


def _names_serial(req: Dict[str, Any]) -> bool:
    """True for a request that enumerates or opens serial ports itself."""
    return req.get("cmd") == "list_serial_ports" or req.get("backend") == "serial"


def _serial_denied(req: Dict[str, Any], session_epoch: int) -> Dict[str, Any]:
    resp: Dict[str, Any] = {
        "ok": False,
        "schema_version": _SCHEMA_VERSION,
        "error": (
            "Serial-port access from a remote client needs a server token "
            "(start the server with --token)."
        ),
        "type": "PermissionError",
        "session_epoch": session_epoch,
    }
    if req.get("request_id") is not None:
        resp["request_id"] = req["request_id"]
    return resp


class RpcGateway:
    """Thread-safe wrapper around one :class:`RpcServer`."""

    # Stateless commands that don't touch the shared session.  These run
    # WITHOUT the lock so a slow/hung one (e.g. an XSDB target scan against a
    # dead hw_server, which can hang past its timeout, or an OpenOCD start that
    # waits up to ~10s for the TCL port) can't starve connect / capture / eio
    # on the live session.
    #
    # ``openocd_stop`` is deliberately NOT here: it kills the OpenOCD process,
    # which may be the transport the active analyzer/EIO session is using, so it
    # must run UNDER the lock to avoid pulling JTAG out from under an in-flight
    # capture/connect. ``openocd_start`` spawns a new process (idempotent, never
    # touches the live transport) and ``openocd_status`` only reads launcher
    # state, so both stay lock-free.
    #
    # ``list_serial_ports`` only reads the OS device list -- it touches no
    # session state and opens nothing -- so a rescan in the UI should not have
    # to wait behind an in-flight capture.
    _LOCK_FREE_CMDS = frozenset(
        {"scan_targets", "openocd_start", "openocd_status", "list_serial_ports"}
    )

    def __init__(self, server: Optional[RpcServer] = None) -> None:
        self._server = server or RpcServer()
        # Web clients may be remote: a serial connect opens only a port the
        # OS lists, never a file or (on Windows) a UNC path a client made up.
        self._server.confine_serial_ports = True
        self._lock = threading.RLock()

    def call(
        self, req: Dict[str, Any], *, serial_allowed: bool = True
    ) -> Dict[str, Any]:
        """Dispatch one JSON-RPC request and return its response envelope.

        Errors are returned **in-band** as ``{"ok": false, ...}`` — exactly the
        shape ``fcapz.rpc.main`` emits — not raised, so every transport sees the
        same protocol.

        ``cancel`` runs without the lock, and a ``close`` that finds it held
        interrupts the command holding it first (see :meth:`RpcServer.cancel`).

        ``serial_allowed=False`` refuses anything that reaches a serial port:
        a request that names one, and -- checked under the lock, against the
        session it would act on -- every session command while the open
        session is a byte-stream link.  A ``capture`` or ``close`` carries no
        backend field, so the request alone cannot say.
        """
        cmd = req.get("cmd")
        if cmd is not None and not isinstance(cmd, str):
            return self._dispatch(req)  # refused in-band before touching anything
        if cmd == "cancel":
            # Never behind the lock: the call it interrupts holds it.  Checked
            # like a session command, since it ends the open session -- or
            # the one a running connect is still opening.
            if not serial_allowed and self._server.session_touches_bytestream():
                return self._denied(req)
            return self._dispatch(req)
        if cmd in self._LOCK_FREE_CMDS:
            if not serial_allowed and _names_serial(req):
                return self._denied(req)
            return self._dispatch(req)
        if cmd != "close":
            self._lock.acquire()
        elif not self._lock.acquire(blocking=False):
            # Disconnect while a command holds the session (a hung connect, a
            # long capture): interrupt it, then close once it has let go,
            # instead of waiting out its timeout.
            self._interrupt(req, serial_allowed)
            self._lock.acquire()
        try:
            if not serial_allowed and (
                _names_serial(req)
                or self._server.session_transport_kind() == "bytestream"
            ):
                return self._denied(req)
            return self._dispatch(req)
        finally:
            self._lock.release()

    @property
    def session_epoch(self) -> int:
        return self._server.session_epoch

    def interrupt_if_busy(self, req: Dict[str, Any], *, serial_allowed: bool = True) -> None:
        """Interrupt the session command holding the lock, if there is one.

        What a ``close`` does first when it finds the lock held.  The web app
        calls it on its event loop before handing the ``close`` to the thread
        pool, so a full pool or a queue of requests ahead of the ``close``
        cannot keep it from interrupting.  Does no I/O and never waits.
        """
        if self._lock.acquire(blocking=False):
            self._lock.release()
            return
        self._interrupt(req, serial_allowed)

    def _interrupt(self, req: Dict[str, Any], serial_allowed: bool) -> None:
        # Only for a close that will run (not malformed, not cancelled
        # itself), and only the session commands: a concurrent target scan
        # is not the session being closed.
        if not self._server.would_run(req):
            return
        if serial_allowed or not self._server.session_touches_bytestream():
            self._server.cancel({"cmd": "cancel"}, session_only=True)

    def _denied(self, req: Dict[str, Any]) -> Dict[str, Any]:
        return _serial_denied(req, self._server.session_epoch)

    def _dispatch(self, req: Dict[str, Any]) -> Dict[str, Any]:
        cmd = req.get("cmd")
        t0 = time.perf_counter()
        try:
            resp = self._server.handle(req)
        except Exception as exc:  # noqa: BLE001 - mirror the line-protocol envelope
            # The traceback goes to the log only (the Log tab shows just the
            # message): a reply carries no source path to a remote client.
            _log.warning("%s failed: %s", cmd, exc, exc_info=True)
            return error_envelope(
                exc, req, log=False, session_epoch=self._server.session_epoch
            )
        # Surface command activity (with timing) in the Log tab. The elapsed ms
        # on capture/capture_wait is exactly the readback time the user is
        # chasing — fast burst vs slow fallback shows up here directly.
        if cmd not in _QUIET_CMDS:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            if resp.get("ok", True):
                _log.info("%s ok (%.0f ms)", cmd, dt_ms)
            else:
                _log.warning("%s -> %s: %s", cmd, resp.get("type"), resp.get("error"))
        return resp
