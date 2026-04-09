# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from .settings import ConnectionSettings


class ConnectionPanel(QGroupBox):
    """Transport parameters, connect/disconnect, and optional bitfile for hw_server."""

    connect_requested = Signal()
    disconnect_requested = Signal()
    connect_cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Connection", parent)
        self._connected = False

        self._backend = QComboBox()
        self._backend.addItem("Xilinx hw_server", "hw_server")
        self._backend.addItem("OpenOCD", "openocd")

        self._host = QLineEdit()
        self._host.setPlaceholderText("127.0.0.1")

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(6666)

        self._tap = QLineEdit()
        self._tap.setPlaceholderText("xc7a100t.tap or FPGA target name")

        self._ir = QComboBox()
        self._ir.addItem("Xilinx 7-series", "xilinx7")
        self._ir.addItem("UltraScale+", "ultrascale")

        self._program = QLineEdit()
        self._program.setPlaceholderText("Optional .bit path (hw_server only)")
        self._program.textChanged.connect(self._refresh_timeout_row_state)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_bitfile)

        prog_row = QWidget()
        pl = QHBoxLayout(prog_row)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self._program, stretch=1)
        pl.addWidget(browse)

        self._status = QLabel("Disconnected")
        self._status.setWordWrap(True)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setToolTip(
            "Stop this connect attempt. Closes the transport; if the server hung, "
            "TCP/JTAG may take a moment to unwind before you try again.",
        )
        self._cancel_btn.clicked.connect(self.connect_cancel_requested.emit)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self.disconnect_requested.emit)
        self._disconnect_btn.setEnabled(False)

        self._tcp_timeout = QSpinBox()
        self._tcp_timeout.setRange(3, 600)
        self._tcp_timeout.setValue(60)
        self._tcp_timeout.setSuffix(" s")
        self._tcp_timeout.setToolTip(
            "OpenOCD: TCP connect timeout. For hw_server, use Cancel if XSDB hangs.",
        )
        self._hw_ready = QSpinBox()
        self._hw_ready.setRange(5, 600)
        self._hw_ready.setValue(60)
        self._hw_ready.setSuffix(" s")
        self._hw_ready.setToolTip(
            "After programming a .bit, maximum wait for the FPGA to answer on JTAG.",
        )

        btn_row = QWidget()
        bl = QHBoxLayout(btn_row)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self._connect_btn)
        bl.addWidget(self._cancel_btn)
        bl.addWidget(self._disconnect_btn)
        bl.addStretch(1)

        form = QFormLayout()
        form.addRow("Backend", self._backend)
        form.addRow("Host", self._host)
        form.addRow("Port", self._port)
        form.addRow("TAP / target", self._tap)
        form.addRow("IR table", self._ir)
        form.addRow("Program bitfile", prog_row)
        form.addRow("Connect timeout", self._tcp_timeout)
        form.addRow("HW ready timeout", self._hw_ready)

        grid = QGridLayout(self)
        grid.addLayout(form, 0, 0)
        grid.addWidget(self._status, 1, 0)
        grid.addWidget(btn_row, 2, 0)

        self._backend.currentIndexChanged.connect(self._on_backend_changed)
        self._on_backend_changed()

    def _on_backend_changed(self) -> None:
        is_hw = self._backend.currentData() == "hw_server"
        self._program.setEnabled(is_hw)
        self._refresh_timeout_row_state()

    def _refresh_timeout_row_state(self) -> None:
        is_hw = self._backend.currentData() == "hw_server"
        has_bit = bool(self._program.text().strip())
        self._hw_ready.setEnabled(is_hw and has_bit)

    def _browse_bitfile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select bitstream",
            "",
            "Bitstreams (*.bit);;All files (*.*)",
        )
        if path:
            self._program.setText(path)

    def _on_connect_clicked(self) -> None:
        err = self._validate()
        if err:
            QMessageBox.warning(self, "Invalid connection", err)
            return
        self.connect_requested.emit()

    def request_connect(self) -> None:
        """Same as clicking Connect (runs validation, then emits ``connect_requested``)."""
        self._on_connect_clicked()

    def set_connect_in_progress(self, busy: bool) -> None:
        """While connecting: show Cancel; freeze Connect/Disconnect and timeout edits."""
        self._cancel_btn.setVisible(busy)
        self._tcp_timeout.setEnabled(not busy)
        self._hw_ready.setEnabled(not busy and self._refresh_hw_ready_enabled())
        if busy:
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(False)
        else:
            self._connect_btn.setEnabled(not self._connected)
            self._disconnect_btn.setEnabled(self._connected)
            self._refresh_timeout_row_state()

    def _refresh_hw_ready_enabled(self) -> bool:
        is_hw = self._backend.currentData() == "hw_server"
        return is_hw and bool(self._program.text().strip())

    def _validate(self) -> str | None:
        host = self._host.text().strip()
        if not host:
            return "Host must not be empty."
        tap = self._tap.text().strip()
        if not tap:
            return "TAP / target must not be empty."
        if self._backend.currentData() == "hw_server":
            raw = self._program.text().strip()
            if raw and not Path(raw).is_file():
                return f"Bitfile not found: {raw}"
        return None

    def connection_settings(self) -> ConnectionSettings:
        program_raw = self._program.text().strip()
        return ConnectionSettings(
            backend=str(self._backend.currentData()),
            host=self._host.text().strip(),
            port=int(self._port.value()),
            tap=self._tap.text().strip(),
            program=program_raw if program_raw else None,
            ir_table=str(self._ir.currentData()),
            connect_timeout_sec=float(self._tcp_timeout.value()),
            hw_ready_timeout_sec=float(self._hw_ready.value()),
        )

    def load_from_settings(self, conn: ConnectionSettings) -> None:
        idx = self._backend.findData(conn.backend)
        if idx >= 0:
            self._backend.setCurrentIndex(idx)
        self._host.setText(conn.host)
        self._port.setValue(conn.port)
        self._tap.setText(conn.tap)
        ir_idx = self._ir.findData(conn.ir_table)
        if ir_idx >= 0:
            self._ir.setCurrentIndex(ir_idx)
        self._program.setText(conn.program or "")
        self._tcp_timeout.setValue(int(max(3, min(600, round(conn.connect_timeout_sec)))))
        self._hw_ready.setValue(int(max(5, min(600, round(conn.hw_ready_timeout_sec)))))
        self._on_backend_changed()

    def set_connected(self, connected: bool, message: str | None = None) -> None:
        self._connected = connected
        self._connect_btn.setEnabled(not connected)
        self._disconnect_btn.setEnabled(connected)
        editable = not connected
        self._backend.setEnabled(editable)
        self._host.setEnabled(editable)
        self._port.setEnabled(editable)
        self._tap.setEnabled(editable)
        self._ir.setEnabled(editable)
        self._program.setEnabled(
            editable and self._backend.currentData() == "hw_server",
        )
        self._tcp_timeout.setEnabled(editable)
        self._hw_ready.setEnabled(
            editable
            and self._backend.currentData() == "hw_server"
            and bool(self._program.text().strip()),
        )
        if message is not None:
            self._status.setText(message)
        elif connected:
            self._status.setText("Connected.")
        else:
            self._status.setText("Disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected
