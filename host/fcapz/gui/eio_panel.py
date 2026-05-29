# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..eio import EioController
from ..transport import Transport
from .jtag_chain_scope import subsidiary_jtag_chain

_MAX_BITS_UI = 32
_POLL_MS_PRESETS = (25, 50, 100, 250, 500, 1000)
_DEFAULT_POLL_MS = 250


class EioPanel(QGroupBox):
    """EIO inputs (polled) and output bit toggles."""

    attach_requested = Signal()
    detach_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("EIO (Embedded I/O)", parent)
        self._transport: Transport | None = None
        self._eio: EioController | None = None
        self._managed_eio_slots: list[int] = []

        self._chain_spin = QSpinBox()
        self._chain_spin.setRange(1, 8)
        self._chain_spin.setValue(3)
        self._managed_slot = QCheckBox("Managed slot")
        self._managed_slot.setToolTip(
            "Enable when EIO is behind the USER-chain core manager. "
            "Arty multi-core reference: chain 1, slots 2 and 3.",
        )
        self._core_combo = QComboBox()
        self._core_combo.addItem("core 2", 2)
        self._core_combo.setEnabled(False)
        self._core_combo.setToolTip("Detected EIO core behind the USER-chain manager.")
        self._core_combo.currentIndexChanged.connect(self._on_core_combo_changed)
        self._chain_value = QLabel("chain -")
        self._slot_value = QLabel("slot -")
        self._instance_spin = QSpinBox()
        self._instance_spin.setRange(0, 255)
        self._instance_spin.setValue(2)
        self._instance_spin.setToolTip("Core-manager slot index for this EIO.")
        self._instance_spin.valueChanged.connect(self._sync_core_combo_to_instance)
        self._attach_btn = QPushButton("Attach EIO")
        self._attach_btn.setToolTip(
            "Required before reads/writes. Legacy Arty: chain 3. "
            "Managed Arty: chain 1, slot 2 or 3.",
        )
        self._attach_btn.clicked.connect(self._on_attach_button_clicked)

        self._info = QLabel("Not attached.")
        self._info.setWordWrap(True)

        self._poll_enable = QCheckBox("Poll inputs")
        self._poll_ms_combo = QComboBox()
        for ms in _POLL_MS_PRESETS:
            self._poll_ms_combo.addItem(f"{ms} ms", ms)
        self._poll_ms_combo.setCurrentIndex(_POLL_MS_PRESETS.index(_DEFAULT_POLL_MS))
        self._poll_ms_combo.setMaximumWidth(88)
        self._poll_ms_combo.setToolTip("How often to read EIO inputs while polling is on.")
        self._poll_ms_combo.currentIndexChanged.connect(self._on_poll_interval_changed)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_DEFAULT_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_tick)

        self._in_grid = QWidget()
        self._in_layout = QGridLayout(self._in_grid)
        self._in_checks: list[QCheckBox] = []

        self._out_grid = QWidget()
        self._out_layout = QGridLayout(self._out_grid)
        self._out_checks: list[QCheckBox] = []

        self._all_outputs_on_btn = QPushButton("All outputs on")
        self._all_outputs_on_btn.setToolTip(
            "Write every probe_out bit to 1 at once "
            f"(full OUT_W, not only the first {_MAX_BITS_UI} UI bits).",
        )
        self._all_outputs_on_btn.clicked.connect(self._on_all_outputs_on_clicked)

        self._all_outputs_off_btn = QPushButton("All outputs off")
        self._all_outputs_off_btn.setToolTip(
            "Write every probe_out bit to 0 at once "
            f"(full OUT_W, not only the first {_MAX_BITS_UI} UI bits).",
        )
        self._all_outputs_off_btn.clicked.connect(self._on_all_outputs_off_clicked)

        self._in_scroll = QScrollArea()
        self._in_scroll.setWidgetResizable(True)
        self._in_scroll.setWidget(self._in_grid)
        out_scroll = QScrollArea()
        out_scroll.setWidgetResizable(True)
        out_scroll.setWidget(self._out_grid)
        self._out_scroll = out_scroll

        row = QHBoxLayout()
        row.addWidget(QLabel("Core"))
        row.addWidget(self._core_combo)
        row.addWidget(self._chain_value)
        row.addWidget(self._slot_value)
        row.addWidget(self._attach_btn)
        row.addStretch(1)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Manual chain"))
        manual_row.addWidget(self._chain_spin)
        manual_row.addWidget(self._managed_slot)
        manual_row.addWidget(QLabel("Slot"))
        manual_row.addWidget(self._instance_spin)
        manual_row.addStretch(1)
        self._manual_row_widget = QWidget()
        self._manual_row_widget.setLayout(manual_row)

        form = QFormLayout()
        form.addRow(row)
        form.addRow(self._manual_row_widget)
        form.addRow(self._info)
        poll_row = QHBoxLayout()
        poll_row.addWidget(self._poll_enable)
        poll_row.addWidget(self._poll_ms_combo)
        poll_row.addStretch(1)
        form.addRow(poll_row)
        form.addRow(QLabel("Inputs (read-only)"), self._in_scroll)
        out_lbl = QLabel("Outputs (drive fabric / board LEDs)")
        out_lbl.setToolTip(
            "Writes EIO probe_out. On the Arty reference design, bits 0–3 drive the "
            "four green LEDs (active high). Enable Poll inputs above to refresh the "
            "Inputs checkboxes only — they are not wired to LEDs.",
        )
        out_block = QWidget()
        out_block_layout = QVBoxLayout(out_block)
        out_block_layout.setContentsMargins(0, 0, 0, 0)
        out_master_row = QHBoxLayout()
        out_master_row.addWidget(self._all_outputs_on_btn)
        out_master_row.addWidget(self._all_outputs_off_btn)
        out_master_row.addStretch(1)
        out_block_layout.addLayout(out_master_row)
        out_block_layout.addWidget(self._out_scroll)
        form.addRow(out_lbl, out_block)

        outer = QGridLayout(self)
        outer.addLayout(form, 0, 0)

        self._poll_enable.toggled.connect(self._on_poll_toggled)
        self._managed_slot.toggled.connect(
            lambda _on: self._apply_attach_ui_state(self._eio is not None)
        )
        self.clear()

    def clear(self) -> None:
        self._poll_timer.stop()
        self._poll_enable.setChecked(False)
        self._transport = None
        self._eio = None
        self._managed_eio_slots = []
        self._info.setText("Not attached.")
        self._chain_value.setText("chain -")
        self._slot_value.setText("slot -")
        self._rebuild_bits(0, 0)
        self._attach_btn.setText("Attach EIO")
        self._attach_btn.setEnabled(False)
        self._apply_attach_ui_state(False)

    def set_transport(self, transport: Transport | None) -> None:
        if transport is None:
            self.clear()
            return
        self._transport = transport
        self._attach_btn.setText("Attach EIO")
        self._attach_btn.setEnabled(True)
        self._apply_attach_ui_state(False)

    def set_managed_eio_slots(self, slots: list[int]) -> None:
        self._managed_eio_slots = list(slots)
        self._rebuild_core_combo()
        if self._eio is None and self._managed_eio_slots:
            self._chain_spin.setValue(1)
            self._managed_slot.setChecked(True)
            self._instance_spin.setValue(self._managed_eio_slots[0])
            joined = ", ".join(str(s) for s in self._managed_eio_slots)
            self._chain_value.setText("chain 1")
            self._slot_value.setText(f"slot {self._managed_eio_slots[0]}")
            self._info.setText(f"Managed EIO cores detected: {joined}.")
        elif self._eio is None:
            self._info.setText("Not attached.")
            self._chain_value.setText(f"chain {self._chain_spin.value()}")
            self._slot_value.setText("slot direct")

    def bind_eio(self, transport: Transport, eio: EioController) -> None:
        self._transport = transport
        self._eio = eio
        extra = ""
        if eio.in_w > _MAX_BITS_UI or eio.out_w > _MAX_BITS_UI:
            extra = f" (showing first {_MAX_BITS_UI} of each bus)"
        self._info.setText(
            f"EIO v{eio.version_major}.{eio.version_minor} — "
            f"chain={eio.bscan_chain}, "
            f"slot={eio.instance if eio.instance is not None else 'direct'}, "
            f"in_w={eio.in_w}, out_w={eio.out_w}{extra}",
        )
        self._chain_value.setText(f"chain {eio.bscan_chain}")
        self._slot_value.setText(
            f"slot {eio.instance if eio.instance is not None else 'direct'}"
        )
        self._rebuild_bits(
            min(eio.in_w, _MAX_BITS_UI),
            min(eio.out_w, _MAX_BITS_UI),
        )
        self._apply_attach_ui_state(True)
        try:
            with subsidiary_jtag_chain(transport, eio.bscan_chain):
                outv = eio.read_outputs()
        except (OSError, RuntimeError):
            outv = 0
        self._set_output_widgets_from_value(outv)
        if self._poll_enable.isChecked():
            self._poll_tick()

    def detach_eio(self) -> None:
        self._poll_timer.stop()
        self._poll_enable.setChecked(False)
        self._eio = None
        self._info.setText("Not attached.")
        if self._managed_eio_slots:
            self._chain_value.setText("chain 1")
            self._slot_value.setText(f"slot {self.instance()}")
        else:
            self._chain_value.setText(f"chain {self.chain()}")
            self._slot_value.setText("slot direct")
        self._rebuild_bits(0, 0)
        self._attach_btn.setText("Attach EIO")
        self._apply_attach_ui_state(False)

    def chain(self) -> int:
        return int(self._chain_spin.value())

    def instance(self) -> int | None:
        if not self._managed_slot.isChecked():
            return None
        return int(self._instance_spin.value())

    def _apply_attach_ui_state(self, attached: bool) -> None:
        """Grey out probe UI until EIO is attached; keep chain + attach usable when connected."""
        has_transport = self._transport is not None
        managed_detected = bool(self._managed_eio_slots)
        self._manual_row_widget.setVisible(not managed_detected)
        self._chain_spin.setEnabled(has_transport and not attached)
        self._managed_slot.setEnabled(has_transport and not attached)
        self._core_combo.setEnabled(
            has_transport and managed_detected
        )
        self._instance_spin.setEnabled(
            has_transport and not attached and self._managed_slot.isChecked()
        )
        self._poll_enable.setEnabled(attached)
        self._poll_ms_combo.setEnabled(attached)
        self._in_scroll.setEnabled(attached)
        self._out_scroll.setEnabled(attached)
        out_bits = len(self._out_checks)
        can_out = attached and out_bits > 0
        self._all_outputs_on_btn.setEnabled(can_out)
        self._all_outputs_off_btn.setEnabled(can_out)
        for cb in self._out_checks:
            cb.setEnabled(attached)
        self._attach_btn.setEnabled(has_transport)
        self._attach_btn.setText("Detach EIO" if attached else "Attach EIO")
        self._attach_btn.setVisible(not managed_detected)

    def _on_attach_button_clicked(self) -> None:
        if self._eio is None:
            self.attach_requested.emit()
        else:
            self.detach_requested.emit()

    def _rebuild_core_combo(self) -> None:
        self._core_combo.blockSignals(True)
        self._core_combo.clear()
        if self._managed_eio_slots:
            for slot in self._managed_eio_slots:
                self._core_combo.addItem(f"core {int(slot)}", int(slot))
            idx = self._core_combo.findData(int(self._instance_spin.value()))
            self._core_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self._core_combo.addItem("core 2", 2)
            self._core_combo.setCurrentIndex(0)
        self._core_combo.blockSignals(False)
        self._apply_attach_ui_state(self._eio is not None)

    def _on_core_combo_changed(self, _index: int) -> None:
        data = self._core_combo.currentData()
        if data is None:
            return
        self._managed_slot.setChecked(True)
        self._chain_spin.setValue(1)
        self._instance_spin.setValue(int(data))
        self._chain_value.setText("chain 1")
        self._slot_value.setText(f"slot {int(data)}")
        if self._transport is not None:
            self.attach_requested.emit()

    def _sync_core_combo_to_instance(self, value: int) -> None:
        idx = self._core_combo.findData(int(value))
        if idx < 0:
            return
        self._core_combo.blockSignals(True)
        self._core_combo.setCurrentIndex(idx)
        self._core_combo.blockSignals(False)

    def _full_output_mask(self) -> int:
        if self._eio is None:
            return 0
        return (1 << self._eio.out_w) - 1

    def _set_output_widgets_from_value(self, outv: int) -> None:
        for i, cb in enumerate(self._out_checks):
            v = (outv >> i) & 1
            cb.blockSignals(True)
            cb.setCheckState(
                Qt.CheckState.Checked if v else Qt.CheckState.Unchecked,
            )
            cb.blockSignals(False)

    def _on_poll_toggled(self, on: bool) -> None:
        if on and self._eio is not None:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def _poll_interval_ms(self) -> int:
        data = self._poll_ms_combo.currentData()
        return int(data) if data is not None else _DEFAULT_POLL_MS

    def _on_poll_interval_changed(self, _index: int) -> None:
        self._poll_timer.setInterval(self._poll_interval_ms())

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
        self._set_output_widgets_from_value(outv)

    def _write_full_probe_out(self, value: int) -> bool:
        if self._eio is None or self._transport is None:
            return False
        try:
            with subsidiary_jtag_chain(self._transport, self._eio.bscan_chain):
                self._eio.write_outputs(value)
                outv = self._eio.read_outputs()
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "EIO outputs", str(exc))
            return False
        self._set_output_widgets_from_value(outv)
        return True

    def _on_all_outputs_on_clicked(self) -> None:
        self._write_full_probe_out(self._full_output_mask())

    def _on_all_outputs_off_clicked(self) -> None:
        self._write_full_probe_out(0)

    def _on_output_toggled(self, bit: int, high: bool) -> None:
        if self._eio is None or self._transport is None:
            return
        try:
            with subsidiary_jtag_chain(self._transport, self._eio.bscan_chain):
                self._eio.set_bit(bit, 1 if high else 0)
                outv = self._eio.read_outputs()
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "EIO output", str(exc))
            if self._eio is not None and self._transport is not None:
                try:
                    with subsidiary_jtag_chain(self._transport, self._eio.bscan_chain):
                        outv = self._eio.read_outputs()
                except (OSError, RuntimeError, ValueError):
                    pass
                else:
                    self._set_output_widgets_from_value(outv)
            return
        self._set_output_widgets_from_value(outv)

    def _on_out_bit_state(self, bit: int, state: int) -> None:
        on = Qt.CheckState(state) == Qt.CheckState.Checked
        self._on_output_toggled(bit, on)
