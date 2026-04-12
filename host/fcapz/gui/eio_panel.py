# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from ..eio import EioController
from ..transport import Transport
from .jtag_chain_scope import subsidiary_jtag_chain

_MAX_BITS_UI = 32


class EioPanel(QGroupBox):
    """EIO inputs (polled) and output bit toggles."""

    attach_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("EIO (Embedded I/O)", parent)
        self._transport: Transport | None = None
        self._eio: EioController | None = None

        self._chain_spin = QSpinBox()
        self._chain_spin.setRange(1, 8)
        self._chain_spin.setValue(3)
        self._attach_btn = QPushButton("Attach EIO")
        self._attach_btn.clicked.connect(lambda: self.attach_requested.emit())

        self._info = QLabel("Not attached.")
        self._info.setWordWrap(True)

        self._poll_enable = QCheckBox("Poll inputs")
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._poll_tick)

        self._in_grid = QWidget()
        self._in_layout = QGridLayout(self._in_grid)
        self._in_checks: list[QCheckBox] = []

        self._out_grid = QWidget()
        self._out_layout = QGridLayout(self._out_grid)
        self._out_checks: list[QCheckBox] = []

        in_scroll = QScrollArea()
        in_scroll.setWidgetResizable(True)
        in_scroll.setWidget(self._in_grid)
        out_scroll = QScrollArea()
        out_scroll.setWidgetResizable(True)
        out_scroll.setWidget(self._out_grid)

        row = QHBoxLayout()
        row.addWidget(QLabel("Chain"))
        row.addWidget(self._chain_spin)
        row.addWidget(self._attach_btn)
        row.addStretch(1)

        form = QFormLayout()
        form.addRow(row)
        form.addRow(self._info)
        form.addRow(self._poll_enable)
        form.addRow(QLabel("Inputs (read-only)"), in_scroll)
        form.addRow(QLabel("Outputs"), out_scroll)

        outer = QGridLayout(self)
        outer.addLayout(form, 0, 0)

        self._poll_enable.toggled.connect(self._on_poll_toggled)
        self.clear()

    def clear(self) -> None:
        self._poll_timer.stop()
        self._poll_enable.setChecked(False)
        self._transport = None
        self._eio = None
        self._info.setText("Not attached.")
        self._rebuild_bits(0, 0)
        self._attach_btn.setEnabled(False)

    def set_transport(self, transport: Transport | None) -> None:
        if transport is None:
            self.clear()
            return
        self._transport = transport
        self._attach_btn.setEnabled(True)

    def bind_eio(self, transport: Transport, eio: EioController) -> None:
        self._transport = transport
        self._eio = eio
        extra = ""
        if eio.in_w > _MAX_BITS_UI or eio.out_w > _MAX_BITS_UI:
            extra = f" (showing first {_MAX_BITS_UI} of each bus)"
        self._info.setText(
            f"EIO v{eio.version_major}.{eio.version_minor} — "
            f"in_w={eio.in_w}, out_w={eio.out_w}{extra}",
        )
        self._rebuild_bits(
            min(eio.in_w, _MAX_BITS_UI),
            min(eio.out_w, _MAX_BITS_UI),
        )
        if self._poll_enable.isChecked():
            self._poll_tick()

    def chain(self) -> int:
        return int(self._chain_spin.value())

    def _on_poll_toggled(self, on: bool) -> None:
        if on and self._eio is not None:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def _rebuild_bits(self, in_n: int, out_n: int) -> None:
        for c in self._in_checks:
            c.deleteLater()
        self._in_checks.clear()
        for c in self._out_checks:
            c.deleteLater()
        self._out_checks.clear()
        while self._in_layout.count():
            item = self._in_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        while self._out_layout.count():
            item = self._out_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cols = 8
        for i in range(in_n):
            cb = QCheckBox(str(i))
            cb.setEnabled(False)
            self._in_layout.addWidget(cb, i // cols, i % cols)
            self._in_checks.append(cb)
        for i in range(out_n):
            cb = QCheckBox(str(i))
            cb.setTristate(False)
            cb.stateChanged.connect(partial(self._on_out_bit_state, i))
            self._out_layout.addWidget(cb, i // cols, i % cols)
            self._out_checks.append(cb)

    def _poll_tick(self) -> None:
        if self._eio is None or self._transport is None:
            return
        try:
            with subsidiary_jtag_chain(self._transport, self._eio.bscan_chain):
                inv = self._eio.read_inputs()
                outv = self._eio.read_outputs()
        except OSError as exc:
            self._poll_timer.stop()
            self._poll_enable.setChecked(False)
            QMessageBox.warning(self, "EIO poll", str(exc))
            return
        except RuntimeError as exc:
            self._poll_timer.stop()
            self._poll_enable.setChecked(False)
            QMessageBox.warning(self, "EIO poll", str(exc))
            return
        for i, cb in enumerate(self._in_checks):
            v = (inv >> i) & 1
            cb.setCheckState(
                Qt.CheckState.Checked if v else Qt.CheckState.Unchecked,
            )
        for i, cb in enumerate(self._out_checks):
            v = (outv >> i) & 1
            cb.blockSignals(True)
            cb.setCheckState(
                Qt.CheckState.Checked if v else Qt.CheckState.Unchecked,
            )
            cb.blockSignals(False)

    def _on_output_toggled(self, bit: int, high: bool) -> None:
        if self._eio is None or self._transport is None:
            return
        try:
            with subsidiary_jtag_chain(self._transport, self._eio.bscan_chain):
                self._eio.set_bit(bit, 1 if high else 0)
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "EIO output", str(exc))

    def _on_out_bit_state(self, bit: int, state: int) -> None:
        on = Qt.CheckState(state) == Qt.CheckState.Checked
        self._on_output_toggled(bit, on)
