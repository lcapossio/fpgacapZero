# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
from .worker import TargetScanWorker

_USB_BLASTER_AUTO_TAPS = {"xc7a100t", "xc7a100t.tap"}


class ConnectionPanel(QGroupBox):
    """Transport parameters, connect/disconnect, and optional bitfile for hw_server."""

    connect_requested = Signal()
    disconnect_requested = Signal()
    connect_cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Connection", parent)
        self._connected = False
        self._scan_thread: QThread | None = None
        self._scan_worker: TargetScanWorker | None = None

        self._backend = QComboBox()
        self._backend.addItem("Xilinx hw_server", "hw_server")
        self._backend.addItem("OpenOCD", "openocd")
        self._backend.addItem("Intel/Altera USB-Blaster", "usb_blaster")

        self._host = QLineEdit()
        self._host.setPlaceholderText("127.0.0.1")

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(6666)

        self._tap = QComboBox()
        self._tap.setEditable(True)
        self._tap.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._tap.lineEdit().setPlaceholderText("xc7a100t.tap or FPGA target name")
        self._scan_targets_btn = QPushButton("Scan")
        self._scan_targets_btn.setToolTip("List JTAG targets from hw_server / XSDB.")
        self._scan_targets_btn.clicked.connect(self._scan_targets)

        tap_row = QWidget()
        tl = QHBoxLayout(tap_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self._tap, stretch=1)
        tl.addWidget(self._scan_targets_btn)

        self._ir = QComboBox()
        self._ir.addItem("Xilinx 7-series", "xilinx7")
        self._ir.addItem("UltraScale+", "ultrascale")

        self._hardware = QLineEdit()
        self._hardware.setPlaceholderText("auto or DE25-Nano [USB-1]")
        self._hardware.setToolTip(
            "Quartus hardware name for USB-Blaster. Leave empty to auto-select "
            "when exactly one Quartus JTAG cable is present.",
        )

        self._quartus_stp = QLineEdit()
        self._quartus_stp.setPlaceholderText("quartus_stp from PATH")
        self._quartus_stp.setToolTip(
            "Optional path to quartus_stp.exe when Quartus is not on PATH.",
        )
        browse_quartus = QPushButton("Browse...")
        browse_quartus.clicked.connect(self._browse_quartus_stp)

        quartus_row = QWidget()
        ql = QHBoxLayout(quartus_row)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(self._quartus_stp, stretch=1)
        ql.addWidget(browse_quartus)
        self._quartus_row = quartus_row

        self._program_on_connect = QCheckBox("Program on connect")
        self._program_on_connect.setChecked(ConnectionSettings().program_on_connect)
        self._program_on_connect.setToolTip(
            "When checked, Connect runs XSDB fpga -file on the path below. "
            "Uncheck to attach over JTAG only (FPGA must already hold the right image, "
            "and captures will reflect whatever image is already loaded)."
        )
        self._program_on_connect.stateChanged.connect(lambda _s: self._refresh_timeout_row_state())

        self._program = QLineEdit()
        self._program.setPlaceholderText("Path to .bit (required if program on connect is checked)")
        self._program.setToolTip(
            "Bitstream used when “Program on connect” is checked. "
            "You can keep a path here and uncheck the box to reconnect without reprogramming."
        )
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
        self._post_program_ms = QSpinBox()
        self._post_program_ms.setRange(0, 3000)
        self._post_program_ms.setValue(200)
        self._post_program_ms.setSuffix(" ms")
        self._post_program_ms.setToolTip(
            "Tcl wait after fpga -file before probing for readiness. Lower speeds up connect "
            "if your bitstream comes up quickly; raise if connect fails right after program.",
        )
        self._ready_poll_ms = QSpinBox()
        self._ready_poll_ms.setRange(5, 500)
        self._ready_poll_ms.setValue(20)
        self._ready_poll_ms.setSuffix(" ms")
        self._ready_poll_ms.setToolTip(
            "Delay between JTAG reads while waiting for a non-zero probe. Lower is snappier.",
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
        form.addRow("TAP / target", tap_row)
        form.addRow("IR table", self._ir)
        form.addRow("Quartus hardware", self._hardware)
        form.addRow("quartus_stp", quartus_row)
        form.addRow("", self._program_on_connect)
        form.addRow("Bitfile path", prog_row)
        form.addRow("Connect timeout", self._tcp_timeout)
        form.addRow("HW ready timeout", self._hw_ready)
        form.addRow("Post-program delay", self._post_program_ms)
        form.addRow("Ready poll interval", self._ready_poll_ms)

        grid = QGridLayout(self)
        grid.addLayout(form, 0, 0)
        grid.addWidget(self._status, 1, 0)
        grid.addWidget(btn_row, 2, 0)

        self._backend.currentIndexChanged.connect(self._on_backend_changed)
        self._on_backend_changed()

    def _on_backend_changed(self) -> None:
        backend = self._backend.currentData()
        is_hw = backend == "hw_server"
        is_usb = backend == "usb_blaster"
        self._host.setEnabled(not is_usb)
        self._port.setEnabled(not is_usb)
        self._ir.setEnabled(not is_usb)
        self._hardware.setEnabled(is_usb)
        self._quartus_stp.setEnabled(is_usb)
        self._quartus_row.setEnabled(is_usb)
        self._program_on_connect.setEnabled(is_hw)
        self._program.setEnabled(is_hw)
        self._scan_targets_btn.setEnabled(is_hw and not self._connected)
        if is_usb and self._tap_text() in _USB_BLASTER_AUTO_TAPS:
            self._set_tap_text("auto")
        self._refresh_timeout_row_state()

    def _scan_targets(self) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        if self._backend.currentData() != "hw_server":
            QMessageBox.information(
                self,
                "Scan targets",
                "JTAG target scanning is currently available for hw_server only.",
            )
            return
        host = self._host.text().strip() or "127.0.0.1"
        port = int(self._port.value())
        if port == 6666:
            port = 3121
        self._status.setText(f"Scanning JTAG targets on {host}:{port}...")
        self._scan_targets_btn.setEnabled(False)
        thread = QThread()
        worker = TargetScanWorker(
            host=host,
            port=port,
            timeout_sec=float(self._tcp_timeout.value()),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_scan_targets_finished)
        worker.failed.connect(self._on_scan_targets_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_scan_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _tap_text(self) -> str:
        return self._tap.currentText().strip()

    def _set_tap_text(self, text: str) -> None:
        idx = self._tap.findText(text)
        if idx >= 0:
            self._tap.setCurrentIndex(idx)
        else:
            self._tap.setEditText(text)

    def _replace_scanned_targets(self, targets: list[str]) -> None:
        current = self._tap_text()
        self._tap.blockSignals(True)
        self._tap.clear()
        seen: set[str] = set()
        if current:
            self._tap.addItem(current)
            seen.add(current)
        for target in targets:
            target = target.strip()
            if target and target not in seen:
                self._tap.addItem(target)
                seen.add(target)
        if current:
            self._set_tap_text(current)
        elif targets:
            self._tap.setCurrentIndex(0)
        self._tap.blockSignals(False)

    def _on_scan_targets_finished(self, targets: object) -> None:
        target_list = [str(t) for t in targets] if isinstance(targets, list) else []
        if not target_list:
            self._status.setText("Scan complete: no JTAG targets reported.")
            QMessageBox.information(
                self,
                "Scan targets",
                "hw_server responded, but XSDB did not report any JTAG targets.",
            )
            return
        self._replace_scanned_targets(target_list)
        self._tap.showPopup()
        self._status.setText(f"Scan complete: {len(target_list)} target(s) found.")

    def _on_scan_targets_failed(self, message: str) -> None:
        self._status.setText(f"Scan failed: {message}")
        QMessageBox.warning(self, "Scan targets failed", message)

    def _on_scan_thread_finished(self) -> None:
        self._scan_worker = None
        self._scan_thread = None
        self._scan_targets_btn.setEnabled(
            self._backend.currentData() == "hw_server" and not self._connected
        )

    def _will_program_bitfile(self) -> bool:
        return (
            self._backend.currentData() == "hw_server"
            and self._program_on_connect.isChecked()
            and bool(self._program.text().strip())
        )

    def _refresh_timeout_row_state(self) -> None:
        en_prog = self._will_program_bitfile()
        self._hw_ready.setEnabled(en_prog)
        self._post_program_ms.setEnabled(en_prog)
        self._ready_poll_ms.setEnabled(en_prog)

    def _browse_bitfile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select bitstream",
            "",
            "Bitstreams (*.bit);;All files (*.*)",
        )
        if path:
            self._program.setText(path)

    def _browse_quartus_stp(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select quartus_stp",
            "",
            "Quartus STP (quartus_stp.exe quartus_stp);;All files (*.*)",
        )
        if path:
            self._quartus_stp.setText(path)

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
        en = not busy and self._refresh_hw_ready_enabled()
        self._hw_ready.setEnabled(en)
        self._post_program_ms.setEnabled(en)
        self._ready_poll_ms.setEnabled(en)
        if busy:
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(False)
        else:
            self._connect_btn.setEnabled(not self._connected)
            self._disconnect_btn.setEnabled(self._connected)
            self._refresh_timeout_row_state()

    def _refresh_hw_ready_enabled(self) -> bool:
        return self._will_program_bitfile()

    def _validate(self) -> str | None:
        backend = self._backend.currentData()
        host = self._host.text().strip()
        if backend != "usb_blaster" and not host:
            return "Host must not be empty."
        tap = self._tap_text()
        if not tap:
            return "TAP / target must not be empty."
        if backend == "usb_blaster":
            quartus = self._quartus_stp.text().strip()
            if quartus and not Path(quartus).is_file():
                return f"quartus_stp not found: {quartus}"
        if backend == "hw_server":
            if self._program_on_connect.isChecked():
                raw = self._program.text().strip()
                if not raw:
                    return "Program on connect is checked but the bitfile path is empty."
                if not Path(raw).is_file():
                    return f"Bitfile not found: {raw}"
        return None

    def connection_settings(self) -> ConnectionSettings:
        program_raw = self._program.text().strip()
        hardware_raw = self._hardware.text().strip()
        quartus_raw = self._quartus_stp.text().strip()
        return ConnectionSettings(
            backend=str(self._backend.currentData()),
            host=self._host.text().strip(),
            port=int(self._port.value()),
            tap=self._tap_text(),
            hardware=hardware_raw if hardware_raw else None,
            quartus_stp=quartus_raw if quartus_raw else None,
            program=program_raw if program_raw else None,
            program_on_connect=self._program_on_connect.isChecked(),
            ir_table=str(self._ir.currentData()),
            connect_timeout_sec=float(self._tcp_timeout.value()),
            hw_ready_timeout_sec=float(self._hw_ready.value()),
            hw_post_program_delay_ms=int(self._post_program_ms.value()),
            hw_ready_poll_interval_ms=int(self._ready_poll_ms.value()),
        )

    def load_from_settings(self, conn: ConnectionSettings) -> None:
        idx = self._backend.findData(conn.backend)
        if idx >= 0:
            self._backend.setCurrentIndex(idx)
        self._host.setText(conn.host)
        self._port.setValue(conn.port)
        self._set_tap_text(conn.tap)
        self._hardware.setText(conn.hardware or "")
        self._quartus_stp.setText(conn.quartus_stp or "")
        ir_idx = self._ir.findData(conn.ir_table)
        if ir_idx >= 0:
            self._ir.setCurrentIndex(ir_idx)
        self._program.setText(conn.program or "")
        self._program_on_connect.setChecked(conn.program_on_connect)
        self._tcp_timeout.setValue(int(max(3, min(600, round(conn.connect_timeout_sec)))))
        self._hw_ready.setValue(int(max(5, min(600, round(conn.hw_ready_timeout_sec)))))
        self._post_program_ms.setValue(
            int(max(0, min(3000, round(conn.hw_post_program_delay_ms))))
        )
        self._ready_poll_ms.setValue(
            int(max(5, min(500, round(conn.hw_ready_poll_interval_ms))))
        )
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
        backend = self._backend.currentData()
        is_hw = backend == "hw_server"
        is_usb = backend == "usb_blaster"
        self._host.setEnabled(editable and not is_usb)
        self._port.setEnabled(editable and not is_usb)
        self._ir.setEnabled(editable and not is_usb)
        self._hardware.setEnabled(editable and is_usb)
        self._quartus_stp.setEnabled(editable and is_usb)
        self._quartus_row.setEnabled(editable and is_usb)
        self._scan_targets_btn.setEnabled(editable and is_hw)
        self._program_on_connect.setEnabled(editable and is_hw)
        self._program.setEnabled(editable and is_hw)
        self._tcp_timeout.setEnabled(editable)
        hw_prog = editable and self._will_program_bitfile()
        self._hw_ready.setEnabled(hw_prog)
        self._post_program_ms.setEnabled(hw_prog)
        self._ready_poll_ms.setEnabled(hw_prog)
        if message is not None:
            self._status.setText(message)
        elif connected:
            self._status.setText("Connected.")
        else:
            self._status.setText("Disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected
