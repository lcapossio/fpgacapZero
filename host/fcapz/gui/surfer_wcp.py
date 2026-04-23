# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Waveform Control Protocol (WCP) client side for Surfer ``--wcp-initiate``."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

# Matches surfer-wcp ``WcpCSMessage`` JSON framing: one JSON object per message, NUL-terminated.
_GREETING = '{"type":"greeting","version":"0","commands":[]}'
_RELOAD = '{"type":"command","command":"reload"}'
_CLEAR = '{"type":"command","command":"clear"}'


class SurferWcpBridge(QObject):
    """
    Listens on localhost; Surfer connects outbound when started with ``--wcp-initiate <port>``.

    Surfer requires a greeting as the first client-to-server message before accepting commands.
    """

    status_message = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: QTcpServer | None = None
        self._socket: QTcpSocket | None = None
        self._pending_frames: list[str] = []
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.timeout.connect(self._send_next_frame)

    def prepare_listener(self) -> int | None:
        """Close any prior session, listen on an ephemeral port, return port or ``None``."""
        self.shutdown()
        srv = QTcpServer(self)
        if not srv.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            self.status_message.emit(f"WCP listen failed: {srv.errorString()}")
            return None
        srv.newConnection.connect(self._on_new_connection)
        self._server = srv
        port = int(srv.serverPort())
        self.status_message.emit(f"WCP listening on localhost:{port}")
        return port

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        old = self._socket
        self._socket = sock
        sock.readyRead.connect(self._drain_incoming)
        sock.disconnected.connect(self._on_disconnected)
        sock.errorOccurred.connect(self._on_socket_error)
        if old is not None and old is not sock:
            old.abort()
            old.deleteLater()
        self._write_frame(sock, _GREETING)
        self.status_message.emit("WCP connected")

    def _on_disconnected(self) -> None:
        s = self.sender()
        if s is self._socket:
            self._socket = None
            self.status_message.emit("WCP disconnected")

    def _on_socket_error(self, _error: QAbstractSocket.SocketError) -> None:
        s = self.sender()
        if isinstance(s, QTcpSocket):
            self.status_message.emit(f"WCP socket error: {s.errorString()}")

    def _drain_incoming(self) -> None:
        s = self.sender()
        if isinstance(s, QTcpSocket):
            s.readAll()

    @staticmethod
    def _write_frame(sock: QTcpSocket, payload: str) -> None:
        sock.write(payload.encode("utf-8") + b"\0")
        sock.flush()

    def _queue_frame(self, payload: str) -> bool:
        if not self.can_reload():
            return False
        self._pending_frames.append(payload)
        if not self._send_timer.isActive():
            self._send_timer.start(0)
        return True

    def _send_next_frame(self) -> None:
        if not self.can_reload():
            self._pending_frames.clear()
            return
        if not self._pending_frames:
            return
        assert self._socket is not None
        self._write_frame(self._socket, self._pending_frames.pop(0))
        if self._pending_frames:
            self._send_timer.start(1200)

    def can_reload(self) -> bool:
        return (
            self._socket is not None
            and self._socket.state() == QAbstractSocket.SocketState.ConnectedState
        )

    def send_reload(self) -> bool:
        if not self.can_reload():
            return False
        return self._queue_frame(_RELOAD)

    def send_wcp_command(self, command: str, **fields: object) -> bool:
        """Send one structured WCP command."""
        payload = {"type": "command", "command": command}
        payload.update(fields)
        return self._queue_frame(
            json.dumps(payload, separators=(",", ":")),
        )

    def send_clear(self) -> bool:
        if not self.can_reload():
            return False
        return self._queue_frame(_CLEAR)

    def send_add_variables(self, variables: list[str]) -> bool:
        return self.send_wcp_command("add_variables", variables=variables)

    def send_add_marker(self, *, name: str, timestamp: int) -> bool:
        return self.send_wcp_command(
            "add_markers",
            markers=[{"name": name, "timestamp": timestamp}],
        )

    def send_set_viewport_to(self, timestamp: int) -> bool:
        return self.send_wcp_command("set_viewport_to", timestamp=timestamp)

    def shutdown(self) -> None:
        # Hold a local ref: abort() can synchronously emit disconnected and clear
        # ``self._socket`` via ``_on_disconnected`` before deleteLater would run.
        sock = self._socket
        self._socket = None
        self._pending_frames.clear()
        self._send_timer.stop()
        if sock is not None:
            try:
                sock.readyRead.disconnect(self._drain_incoming)
            except (RuntimeError, TypeError):
                pass
            try:
                sock.disconnected.disconnect(self._on_disconnected)
            except (RuntimeError, TypeError):
                pass
            try:
                sock.errorOccurred.disconnect(self._on_socket_error)
            except (RuntimeError, TypeError):
                pass
            sock.abort()
            sock.deleteLater()
        srv = self._server
        self._server = None
        if srv is not None:
            srv.close()
            srv.deleteLater()
