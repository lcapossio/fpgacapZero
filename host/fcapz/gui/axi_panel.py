# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    QTextEdit,
    QWidget,
)

from ..ejtagaxi import AXIError, EjtagAxiController


class AxiPanel(QGroupBox):
    """JTAG-to-AXI: single read/write, block dump, binary load."""

    attach_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("AXI bridge", parent)
        self._axi: EjtagAxiController | None = None

        self._chain_spin = QSpinBox()
        self._chain_spin.setRange(1, 8)
        self._chain_spin.setValue(4)
        self._attach = QPushButton("Attach AXI")
        self._attach.clicked.connect(lambda: self.attach_requested.emit())
        self._info = QLabel("Not attached.")
        self._info.setWordWrap(True)

        self._addr = QLineEdit("0x0")
        self._data = QLineEdit("0x0")
        self._wstrb = QLineEdit("0xF")
        self._read_btn = QPushButton("Read")
        self._write_btn = QPushButton("Write")
        self._read_btn.clicked.connect(self._do_read)
        self._write_btn.clicked.connect(self._do_write)

        self._dump_addr = QLineEdit("0x0")
        self._dump_count = QSpinBox()
        self._dump_count.setRange(1, 65536)
        self._dump_count.setValue(16)
        self._dump_burst = QCheckBox("Burst read")
        self._dump_btn = QPushButton("Dump")
        self._dump_btn.clicked.connect(self._do_dump)

        self._load_addr = QLineEdit("0x0")
        self._load_burst = QCheckBox("Burst write")
        self._load_btn = QPushButton("Load file…")
        self._load_btn.clicked.connect(self._do_load)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(180)

        row = QHBoxLayout()
        row.addWidget(QLabel("Chain"))
        row.addWidget(self._chain_spin)
        row.addWidget(self._attach)
        row.addStretch(1)

        form = QFormLayout()
        form.addRow(row)
        form.addRow(self._info)
        form.addRow("Address", self._addr)
        form.addRow("Write data", self._data)
        form.addRow("WSTRB", self._wstrb)
        rw = QHBoxLayout()
        rw.addWidget(self._read_btn)
        rw.addWidget(self._write_btn)
        form.addRow(rw)
        form.addRow("Dump address", self._dump_addr)
        form.addRow("Word count", self._dump_count)
        form.addRow(self._dump_burst)
        form.addRow(self._dump_btn)
        form.addRow("Load address", self._load_addr)
        form.addRow(self._load_burst)
        form.addRow(self._load_btn)
        form.addRow(QLabel("Log"), self._log)

        grid = QGridLayout(self)
        grid.addLayout(form, 0, 0)
        self.clear()

    def clear(self) -> None:
        self._axi = None
        self._info.setText("Not attached.")
        for b in (
            self._read_btn,
            self._write_btn,
            self._dump_btn,
            self._load_btn,
        ):
            b.setEnabled(False)

    def set_transport_available(self, ok: bool) -> None:
        self._attach.setEnabled(ok)

    def bind_axi(self, axi: EjtagAxiController, info: dict) -> None:
        self._axi = axi
        self._info.setText(
            f"AXI v{info['version_major']}.{info['version_minor']}, "
            f"addr_w={info['addr_w']}, data_w={info['data_w']}, "
            f"fifo_depth={info['fifo_depth']}",
        )
        for b in (
            self._read_btn,
            self._write_btn,
            self._dump_btn,
            self._load_btn,
        ):
            b.setEnabled(True)

    def chain(self) -> int:
        return int(self._chain_spin.value())

    def _parse_hex(self, field: QLineEdit, name: str) -> int:
        try:
            return int(field.text().strip(), 0)
        except ValueError as exc:
            raise ValueError(f"{name} must be hex or decimal") from exc

    def _append(self, line: str) -> None:
        self._log.append(line.rstrip())

    def _do_read(self) -> None:
        if self._axi is None:
            return
        try:
            addr = self._parse_hex(self._addr, "Address")
            val = self._axi.axi_read(addr)
            self._append(f"READ 0x{addr:08X} -> 0x{val:08X}")
        except (AXIError, OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "AXI read", str(exc))

    def _do_write(self) -> None:
        if self._axi is None:
            return
        try:
            addr = self._parse_hex(self._addr, "Address")
            data = self._parse_hex(self._data, "Data")
            wstrb = self._parse_hex(self._wstrb, "WSTRB")
            resp = self._axi.axi_write(addr, data, wstrb=wstrb)
            self._append(f"WRITE 0x{data:08X} -> 0x{addr:08X} (resp={resp})")
        except (AXIError, OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "AXI write", str(exc))

    def _do_dump(self) -> None:
        if self._axi is None:
            return
        try:
            addr = self._parse_hex(self._dump_addr, "Dump address")
            n = int(self._dump_count.value())
            if self._dump_burst.isChecked():
                words = self._axi.burst_read(addr, n)
            else:
                words = self._axi.read_block(addr, n)
            for i, w in enumerate(words):
                self._append(f"0x{addr + i * 4:08X}: 0x{w:08X}")
        except (AXIError, OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "AXI dump", str(exc))

    def _do_load(self) -> None:
        if self._axi is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Binary to load", "", "All (*.*)")
        if not path:
            return
        try:
            addr = self._parse_hex(self._load_addr, "Load address")
            raw = Path(path).read_bytes()
            if len(raw) % 4 != 0:
                raw += b"\x00" * (4 - len(raw) % 4)
            words = [
                int.from_bytes(raw[i : i + 4], "little")
                for i in range(0, len(raw), 4)
            ]
            if self._load_burst.isChecked():
                self._axi.burst_write(addr, words)
            else:
                self._axi.write_block(addr, words)
            self._append(f"Loaded {len(words)} words from {path} @ 0x{addr:08X}")
        except (AXIError, OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "AXI load", str(exc))
