# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Waveform Control Protocol (WCP) client side for Surfer ``--wcp-initiate``."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

# Matches surfer-wcp ``WcpCSMessage`` JSON framing: one JSON object per message, NUL-terminated.
_GREETING = '{"type":"greeting","version":"0","commands":[]}'
_RELOAD = '{"type":"command","command":"reload"}'


class SurferWcpBridge(QObject):
    """
    Listens on localhost; Surfer connects outbound when started with ``--wcp-initiate <port>``.

    Surfer requires a greeting as the first client-to-server message before accepting commands.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: QTcpServer | None = None
        self._socket: QTcpSocket | None = None

    def prepare_listener(self) -> int | None:
        """Close any prior session, listen on an ephemeral port, return port or ``None``."""
        self.shutdown()
        srv = QTcpServer(self)
        if not srv.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            return None
        srv.newConnection.connect(self._on_new_connection)
        self._server = srv
        return int(srv.serverPort())

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
        if old is not None and old is not sock:
            old.abort()
            old.deleteLater()
        self._write_frame(sock, _GREETING)

    def _on_disconnected(self) -> None:
        s = self.sender()
        if s is self._socket:
            self._socket = None

    def _drain_incoming(self) -> None:
        s = self.sender()
        if isinstance(s, QTcpSocket):
            s.readAll()

    @staticmethod
    def _write_frame(sock: QTcpSocket, payload: str) -> None:
        sock.write(payload.encode("utf-8") + b"\0")

    def can_reload(self) -> bool:
        return (
            self._socket is not None
            and self._socket.state() == QAbstractSocket.SocketState.ConnectedState
        )

    def send_reload(self) -> bool:
        if not self.can_reload():
            return False
        assert self._socket is not None
        self._write_frame(self._socket, _RELOAD)
        return True

    def shutdown(self) -> None:
        # Hold a local ref: abort() can synchronously emit disconnected and clear
        # ``self._socket`` via ``_on_disconnected`` before deleteLater would run.
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.readyRead.disconnect(self._drain_incoming)
            except (RuntimeError, TypeError):
                pass
            try:
                sock.disconnected.disconnect(self._on_disconnected)
            except (RuntimeError, TypeError):
                pass
            sock.abort()
            sock.deleteLater()
        srv = self._server
        self._server = None
        if srv is not None:
            srv.close()
            srv.deleteLater()
