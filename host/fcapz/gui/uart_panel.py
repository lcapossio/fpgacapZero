# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QWidget,
)

from ..ejtaguart import EjtagUartController


class UartPanel(QGroupBox):
    """JTAG-to-UART send and polled receive."""

    attach_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("UART bridge", parent)
        self._uart: EjtagUartController | None = None

        self._chain_spin = QSpinBox()
        self._chain_spin.setRange(1, 8)
        self._chain_spin.setValue(4)
        self._attach = QPushButton("Attach UART")
        self._attach.clicked.connect(lambda: self.attach_requested.emit())
        self._info = QLabel("Not attached.")
        self._info.setWordWrap(True)

        self._term = QTextEdit()
        self._term.setReadOnly(True)
        self._term.setPlaceholderText("Received data appears here…")

        self._send_edit = QLineEdit()
        self._send_edit.setPlaceholderText("Text to send (UTF-8)")
        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._do_send)

        self._poll_rx = QCheckBox("Poll RX")
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_tick)

        row = QHBoxLayout()
        row.addWidget(QLabel("Chain"))
        row.addWidget(self._chain_spin)
        row.addWidget(self._attach)
        row.addStretch(1)

        form = QFormLayout()
        form.addRow(row)
        form.addRow(self._info)
        form.addRow(self._term)
        srow = QHBoxLayout()
        srow.addWidget(self._send_edit, stretch=1)
        srow.addWidget(self._send_btn)
        form.addRow(srow)
        form.addRow(self._poll_rx)

        g = QGridLayout(self)
        g.addLayout(form, 0, 0)

        self._poll_rx.toggled.connect(self._on_poll_toggled)
        self.clear()

    def clear(self) -> None:
        self._poll_timer.stop()
        self._poll_rx.setChecked(False)
        self._uart = None
        self._info.setText("Not attached.")
        self._send_btn.setEnabled(False)

    def set_transport_available(self, ok: bool) -> None:
        self._attach.setEnabled(ok)

    def bind_uart(self, uart: EjtagUartController, info: dict) -> None:
        self._uart = uart
        maj = info["version_major"]
        minor = info["version_minor"]
        suffix = " legacy ID" if info.get("legacy_id") else ""
        self._info.setText(
            f"UART bridge OK — id=0x{info['id']:04X}, v{maj}.{minor}{suffix}"
        )
        self._send_btn.setEnabled(True)

    def chain(self) -> int:
        return int(self._chain_spin.value())

    def _on_poll_toggled(self, on: bool) -> None:
        if on and self._uart is not None:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def _append_rx(self, chunk: bytes) -> None:
        if not chunk:
            return
        text = chunk.decode("utf-8", errors="replace")
        self._term.moveCursor(QTextCursor.MoveOperation.End)
        self._term.insertPlainText(text)
        self._term.moveCursor(QTextCursor.MoveOperation.End)

    def _poll_tick(self) -> None:
        if self._uart is None:
            return
        try:
            data = self._uart.recv(count=0, timeout=0.05)
        except (OSError, RuntimeError, TimeoutError) as exc:
            self._poll_timer.stop()
            self._poll_rx.setChecked(False)
            QMessageBox.warning(self, "UART recv", str(exc))
            return
        self._append_rx(data)

    def _do_send(self) -> None:
        if self._uart is None:
            return
        s = self._send_edit.text()
        try:
            self._uart.send(s.encode("utf-8"))
            self._append_rx(f"\n>> sent {len(s)} bytes\n".encode())
        except (OSError, RuntimeError, TimeoutError) as exc:
            QMessageBox.warning(self, "UART send", str(exc))
