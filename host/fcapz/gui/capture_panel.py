# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtCore import QSettings, QSignalBlocker

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QWidget,
)

from ..analyzer import CaptureConfig, SequencerStage, TriggerConfig
from ..cli import _parse_probes
from .collapsible_section import CollapsibleSection
from .settings import ProbeProfile


def _preset_label(ent: Mapping[str, Any]) -> str:
    pre = ent.get("pretrigger", "?")
    post = ent.get("posttrigger", "?")
    mode = ent.get("trigger_mode", "?")
    return f"{pre}/{post} {mode}"


_SEQ_COL_CMP_A = 0
_SEQ_COL_CMP_B = 1
_SEQ_COL_COMBINE = 2
_SEQ_COL_NEXT = 3
_SEQ_COL_FINAL = 4
_SEQ_COL_COUNT = 5
_SEQ_COL_VAL_A = 6
_SEQ_COL_MASK_A = 7
_SEQ_COL_VAL_B = 8
_SEQ_COL_MASK_B = 9

_SEQ_HEADERS = (
    "cmp_a",
    "cmp_b",
    "combine",
    "next",
    "final",
    "count",
    "val_a",
    "mask_a",
    "val_b",
    "mask_b",
)


class CapturePanel(QGroupBox):
    """ELA capture parameters including optional hardware trigger sequencer stages."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ELA capture", parent)
        self._hw_sample_w: int | None = None
        self._hw_depth: int | None = None
        self._hw_num_chan: int | None = None
        self._hw_trig_stages: int = 0

        self._hw_label = QLabel(
            "Connect first (toolbar or Connection panel). "
            "Then sample width and depth load from hardware and the capture buttons unlock.",
        )
        self._hw_label.setWordWrap(True)

        self._profiles: dict[str, ProbeProfile] = {}

        self._profile_pick = QComboBox()
        self._profile_pick.addItem("— Probe profile —", None)
        self._profile_pick.currentIndexChanged.connect(self._on_profile_picked)

        self._preset = QComboBox()
        self._preset.addItem("— Trigger preset (from history) —", None)
        self._preset.currentIndexChanged.connect(self._on_preset_picked)

        self._pre = QSpinBox()
        self._pre.setRange(0, 1_000_000)
        self._pre.setValue(8)
        self._post = QSpinBox()
        self._post.setRange(0, 1_000_000)
        self._post.setValue(16)

        self._trig_mode = QComboBox()
        for m in ("value_match", "edge_detect", "both"):
            self._trig_mode.addItem(m)
        self._trig_val = QLineEdit("0")
        self._trig_mask = QLineEdit("0xFF")

        self._clock_hz = QSpinBox()
        self._clock_hz.setRange(1, 2_000_000_000)
        self._clock_hz.setValue(100_000_000)

        self._channel = QSpinBox()
        self._channel.setRange(0, 15)
        self._channel.setValue(0)

        self._decim = QSpinBox()
        self._decim.setRange(0, 65535)
        self._decim.setValue(0)

        self._probe_sel = QSpinBox()
        self._probe_sel.setRange(0, 1023)
        self._probe_sel.setValue(0)

        self._ext_trig = QComboBox()
        for m in ("disabled", "or", "and"):
            self._ext_trig.addItem(m)

        self._stor_mode = QSpinBox()
        self._stor_mode.setRange(0, 2)
        self._stor_val = QLineEdit("0")
        self._stor_mask = QLineEdit("0")

        self._trig_delay = QSpinBox()
        self._trig_delay.setRange(0, 65535)
        self._trig_delay.setValue(0)

        self._probes = QLineEdit()
        self._probes.setPlaceholderText("name:width:lsb,... (optional)")

        self._timeout = QLineEdit("10.0")

        self._seq_status = QLabel(
            "Connect to see hardware trigger sequencer depth (FEATURES[3:0]).",
        )
        self._seq_status.setWordWrap(True)
        self._seq_enable = QCheckBox("Use trigger sequencer")
        self._seq_enable.setObjectName("fcapz_capture_seq_enable")
        self._seq_enable.toggled.connect(self._on_seq_enable_toggled)
        self._btn_seq_add = QPushButton("Add stage")
        self._btn_seq_add.clicked.connect(self._seq_add_row)
        self._btn_seq_remove = QPushButton("Remove stage")
        self._btn_seq_remove.clicked.connect(self._seq_remove_row)
        row_seq_btns = QHBoxLayout()
        row_seq_btns.addWidget(self._seq_enable)
        row_seq_btns.addWidget(self._btn_seq_add)
        row_seq_btns.addWidget(self._btn_seq_remove)
        row_seq_btns.addStretch(1)

        self._seq_table = QTableWidget(0, len(_SEQ_HEADERS))
        self._seq_table.setObjectName("fcapz_capture_seq_table")
        self._seq_table.setHorizontalHeaderLabels(list(_SEQ_HEADERS))
        self._seq_table.verticalHeader().setVisible(True)
        self._seq_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._seq_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._seq_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._seq_table.horizontalHeader().setStretchLastSection(True)
        self._seq_table.setMinimumHeight(96)

        self._btn_cfg = QPushButton("Configure")
        self._btn_arm = QPushButton("Arm")
        self._btn_cap = QPushButton("Capture")
        self._btn_cont = QPushButton("Continuous")
        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setEnabled(False)

        for b in (
            self._btn_cfg,
            self._btn_arm,
            self._btn_cap,
            self._btn_cont,
            self._btn_stop,
        ):
            b.setEnabled(False)

        row_btns = QHBoxLayout()
        row_btns.addWidget(self._btn_cfg)
        row_btns.addWidget(self._btn_arm)
        row_btns.addWidget(self._btn_cap)
        row_btns.addWidget(self._btn_cont)
        row_btns.addWidget(self._btn_stop)
        row_btns.addStretch(1)

        form_main = QFormLayout()
        form_main.addRow(self._hw_label)
        form_main.addRow("Probe profile", self._profile_pick)
        form_main.addRow("Trigger preset", self._preset)
        form_main.addRow("Pre-trigger samples", self._pre)
        form_main.addRow("Post-trigger samples", self._post)
        form_main.addRow("Trigger mode", self._trig_mode)
        form_main.addRow("Trigger value", self._trig_val)
        form_main.addRow("Trigger mask", self._trig_mask)
        form_main.addRow("Sample clock (Hz)", self._clock_hz)
        form_main.addRow("Channel", self._channel)
        form_main.addRow("Capture timeout (s)", self._timeout)

        adv_body = QWidget()
        form_adv = QFormLayout(adv_body)
        form_adv.addRow("Decimation", self._decim)
        form_adv.addRow("Probe mux sel", self._probe_sel)
        form_adv.addRow("Ext trigger mode", self._ext_trig)
        form_adv.addRow("Storage qual mode", self._stor_mode)
        form_adv.addRow("Storage qual value", self._stor_val)
        form_adv.addRow("Storage qual mask", self._stor_mask)
        form_adv.addRow("Trigger delay", self._trig_delay)
        form_adv.addRow("Probes", self._probes)
        self._adv_section = CollapsibleSection(
            "Advanced (decimation, mux, ext trig, storage qual, probes, …)",
            adv_body,
            start_open=False,
        )

        seq_body = QWidget()
        seq_lay = QGridLayout(seq_body)
        seq_lay.setContentsMargins(0, 0, 0, 0)
        seq_lay.addLayout(row_seq_btns, 0, 0)
        seq_lay.addWidget(self._seq_table, 1, 0)
        self._seq_section = CollapsibleSection(
            "Trigger sequencer table",
            seq_body,
            start_open=False,
        )

        grid = QGridLayout(self)
        grid.addLayout(form_main, 0, 0)
        grid.addWidget(self._adv_section, 1, 0)
        grid.addWidget(self._seq_status, 2, 0)
        grid.addWidget(self._seq_section, 3, 0)
        grid.addLayout(row_btns, 4, 0)

        self._refresh_seq_ui_state()

    def clear_hw(self) -> None:
        self._hw_sample_w = None
        self._hw_depth = None
        self._hw_num_chan = None
        self._hw_trig_stages = 0
        self._btn_stop.setEnabled(False)
        self._hw_label.setText(
            "Connect first (toolbar or Connection panel). "
            "Then sample width and depth load from hardware and the capture buttons unlock.",
        )
        for b in (self._btn_cfg, self._btn_arm, self._btn_cap, self._btn_cont):
            b.setEnabled(False)
        with QSignalBlocker(self._seq_enable):
            self._seq_enable.setChecked(False)
        self._seq_table.setRowCount(0)
        self._refresh_seq_ui_state()

    def set_probe_profiles(self, profiles: Mapping[str, ProbeProfile]) -> None:
        self._profiles = dict(profiles)
        with QSignalBlocker(self._profile_pick):
            self._profile_pick.clear()
            self._profile_pick.addItem("— Probe profile —", None)
            for name in sorted(self._profiles):
                self._profile_pick.addItem(name, name)
            self._profile_pick.setCurrentIndex(0)

    def set_trigger_history(self, entries: list[dict[str, Any]]) -> None:
        with QSignalBlocker(self._preset):
            self._preset.clear()
            self._preset.addItem("— Trigger preset (from history) —", None)
            for ent in entries:
                if not isinstance(ent, dict):
                    continue
                label = _preset_label(ent)
                self._preset.addItem(label, ent)
            self._preset.setCurrentIndex(0)

    def apply_trigger_history_entry(self, entry: Mapping[str, Any]) -> None:
        """Fill the form from a ``trigger_history`` dict (partial / best-effort)."""
        try:
            pre = int(entry.get("pretrigger", 0))
            post = int(entry.get("posttrigger", 0))
            self._pre.setValue(pre)
            self._post.setValue(post)
        except (TypeError, ValueError):
            pass
        mode = str(entry.get("trigger_mode", "value_match"))
        idx = self._trig_mode.findText(mode)
        if idx >= 0:
            self._trig_mode.setCurrentIndex(idx)
        if "trigger_value" in entry:
            try:
                self._trig_val.setText(str(int(entry["trigger_value"])))
            except (TypeError, ValueError):
                self._trig_val.setText(str(entry["trigger_value"]))
        if "trigger_mask" in entry:
            try:
                m = int(entry["trigger_mask"])
                self._trig_mask.setText(hex(m))
            except (TypeError, ValueError):
                self._trig_mask.setText(str(entry["trigger_mask"]))
        for key, spin, default in (
            ("sample_clock_hz", self._clock_hz, 100_000_000),
            ("channel", self._channel, 0),
            ("decimation", self._decim, 0),
            ("probe_sel", self._probe_sel, 0),
            ("stor_qual_mode", self._stor_mode, 0),
            ("trigger_delay", self._trig_delay, 0),
        ):
            if key in entry:
                try:
                    spin.setValue(int(entry[key]))
                except (TypeError, ValueError):
                    spin.setValue(default)
        ext = entry.get("ext_trigger_mode", "disabled")
        if isinstance(ext, int):
            ext = {0: "disabled", 1: "or", 2: "and"}.get(ext, "disabled")
        ext_s = str(ext).lower()
        ei = self._ext_trig.findText(ext_s)
        if ei >= 0:
            self._ext_trig.setCurrentIndex(ei)
        if "stor_qual_value" in entry:
            try:
                self._stor_val.setText(str(int(entry["stor_qual_value"])))
            except (TypeError, ValueError):
                self._stor_val.setText(str(entry["stor_qual_value"]))
        if "stor_qual_mask" in entry:
            try:
                self._stor_mask.setText(hex(int(entry["stor_qual_mask"])))
            except (TypeError, ValueError):
                self._stor_mask.setText(str(entry["stor_qual_mask"]))
        if "probes" in entry and entry["probes"] is not None:
            self._probes.setText(str(entry["probes"]))
        if "trigger_sequence" in entry:
            self._apply_trigger_sequence_entry(entry["trigger_sequence"])

    def _apply_trigger_sequence_entry(self, raw: Any) -> None:
        if self._hw_trig_stages <= 0:
            with QSignalBlocker(self._seq_enable):
                self._seq_enable.setChecked(False)
            self._seq_table.setRowCount(0)
            self._refresh_seq_ui_state()
            return
        if raw is None or raw == []:
            with QSignalBlocker(self._seq_enable):
                self._seq_enable.setChecked(False)
            self._seq_table.setRowCount(0)
            self._refresh_seq_ui_state()
            return
        if not isinstance(raw, list):
            return
        with QSignalBlocker(self._seq_enable):
            self._seq_enable.setChecked(True)
        self._seq_table.setRowCount(0)
        limit = self._hw_trig_stages
        for ent in raw[:limit]:
            if not isinstance(ent, Mapping):
                continue
            self._append_sequencer_row()
            self._fill_sequencer_row(self._seq_table.rowCount() - 1, ent)
        self._refresh_seq_ui_state()

    def _refresh_seq_ui_state(self) -> None:
        if self._hw_trig_stages <= 0:
            self._seq_status.setText(
                "Bitstream reports TRIG_STAGES=0 — hardware trigger sequencer is unavailable."
            )
            self._seq_section.setEnabled(False)
            return
        self._seq_section.setEnabled(True)
        self._seq_status.setText(
            f"Hardware supports up to {self._hw_trig_stages} sequencer stage(s) "
            "(next_state is 0–3 per register layout)."
        )
        use = self._seq_enable.isChecked()
        self._seq_table.setEnabled(use)
        n = self._seq_table.rowCount()
        self._btn_seq_add.setEnabled(use and n < self._hw_trig_stages)
        self._btn_seq_remove.setEnabled(use and n > 0)

    def _on_seq_enable_toggled(self, checked: bool) -> None:
        if checked and self._hw_trig_stages > 0 and self._seq_table.rowCount() == 0:
            self._append_sequencer_row()
        self._refresh_seq_ui_state()

    def _append_sequencer_row(self) -> None:
        row = self._seq_table.rowCount()
        self._seq_table.insertRow(row)
        ca = QSpinBox()
        ca.setRange(0, 8)
        cb = QSpinBox()
        cb.setRange(0, 8)
        comb = QComboBox()
        for label, val in (("A only", 0), ("B only", 1), ("AND", 2), ("OR", 3)):
            comb.addItem(label, val)
        nxt = QSpinBox()
        nxt.setRange(0, 3)
        fin = QCheckBox()
        cnt = QSpinBox()
        cnt.setRange(1, 65535)
        cnt.setValue(1)
        va = QLineEdit("0")
        ma = QLineEdit("0xFFFFFFFF")
        vb = QLineEdit("0")
        mb = QLineEdit("0xFFFFFFFF")
        self._seq_table.setCellWidget(row, _SEQ_COL_CMP_A, ca)
        self._seq_table.setCellWidget(row, _SEQ_COL_CMP_B, cb)
        self._seq_table.setCellWidget(row, _SEQ_COL_COMBINE, comb)
        self._seq_table.setCellWidget(row, _SEQ_COL_NEXT, nxt)
        self._seq_table.setCellWidget(row, _SEQ_COL_FINAL, fin)
        self._seq_table.setCellWidget(row, _SEQ_COL_COUNT, cnt)
        self._seq_table.setCellWidget(row, _SEQ_COL_VAL_A, va)
        self._seq_table.setCellWidget(row, _SEQ_COL_MASK_A, ma)
        self._seq_table.setCellWidget(row, _SEQ_COL_VAL_B, vb)
        self._seq_table.setCellWidget(row, _SEQ_COL_MASK_B, mb)

    def _seq_add_row(self) -> None:
        if self._hw_trig_stages <= 0:
            return
        if self._seq_table.rowCount() >= self._hw_trig_stages:
            return
        self._append_sequencer_row()
        self._refresh_seq_ui_state()

    def _seq_remove_row(self) -> None:
        r = self._seq_table.currentRow()
        if r < 0:
            r = self._seq_table.rowCount() - 1
        if r >= 0:
            self._seq_table.removeRow(r)
        self._refresh_seq_ui_state()

    def _fill_sequencer_row(self, row: int, ent: Mapping[str, Any]) -> None:
        w = self._seq_table.cellWidget(row, _SEQ_COL_CMP_A)
        if isinstance(w, QSpinBox):
            w.setValue(int(ent.get("cmp_a", 0)))
        w = self._seq_table.cellWidget(row, _SEQ_COL_CMP_B)
        if isinstance(w, QSpinBox):
            w.setValue(int(ent.get("cmp_b", 0)))
        w = self._seq_table.cellWidget(row, _SEQ_COL_COMBINE)
        if isinstance(w, QComboBox):
            v = int(ent.get("combine", 0))
            i = w.findData(v)
            if i >= 0:
                w.setCurrentIndex(i)
        w = self._seq_table.cellWidget(row, _SEQ_COL_NEXT)
        if isinstance(w, QSpinBox):
            w.setValue(int(ent.get("next_state", 0)))
        w = self._seq_table.cellWidget(row, _SEQ_COL_FINAL)
        if isinstance(w, QCheckBox):
            w.setChecked(bool(ent.get("is_final", False)))
        w = self._seq_table.cellWidget(row, _SEQ_COL_COUNT)
        if isinstance(w, QSpinBox):
            w.setValue(max(1, min(65535, int(ent.get("count", 1)))))
        for col, key, default in (
            (_SEQ_COL_VAL_A, "value_a", "0"),
            (_SEQ_COL_MASK_A, "mask_a", "0xFFFFFFFF"),
            (_SEQ_COL_VAL_B, "value_b", "0"),
            (_SEQ_COL_MASK_B, "mask_b", "0xFFFFFFFF"),
        ):
            le = self._seq_table.cellWidget(row, col)
            if not isinstance(le, QLineEdit):
                continue
            if key in ent:
                try:
                    n = int(str(ent[key]), 0)
                    le.setText(hex(n) if key.startswith("mask") else str(n))
                except (TypeError, ValueError):
                    le.setText(str(ent[key]))
            else:
                le.setText(default)

    def _parse_sequencer_row(self, row: int) -> SequencerStage:
        def _spin(col: int) -> QSpinBox:
            w = self._seq_table.cellWidget(row, col)
            if not isinstance(w, QSpinBox):
                raise ValueError(f"Stage {row + 1}: missing spin control (column {col}).")
            return w

        comb = self._seq_table.cellWidget(row, _SEQ_COL_COMBINE)
        if not isinstance(comb, QComboBox):
            raise ValueError(f"Stage {row + 1}: missing combine control.")
        raw_c = comb.currentData()
        combine = int(raw_c) if raw_c is not None else comb.currentIndex()
        fin = self._seq_table.cellWidget(row, _SEQ_COL_FINAL)
        if not isinstance(fin, QCheckBox):
            raise ValueError(f"Stage {row + 1}: missing final-stage control.")
        try:
            va_s = self._seq_line(row, _SEQ_COL_VAL_A, "value_a")
            ma_s = self._seq_line(row, _SEQ_COL_MASK_A, "mask_a")
            vb_s = self._seq_line(row, _SEQ_COL_VAL_B, "value_b")
            mb_s = self._seq_line(row, _SEQ_COL_MASK_B, "mask_b")
            value_a = int(va_s.strip(), 0)
            mask_a = int(ma_s.strip(), 0)
            value_b = int(vb_s.strip(), 0)
            mask_b = int(mb_s.strip(), 0)
        except ValueError as exc:
            raise ValueError(f"Stage {row + 1}: value/mask fields must be integers.") from exc
        return SequencerStage(
            cmp_mode_a=int(_spin(_SEQ_COL_CMP_A).value()),
            cmp_mode_b=int(_spin(_SEQ_COL_CMP_B).value()),
            combine=combine,
            next_state=int(_spin(_SEQ_COL_NEXT).value()),
            is_final=bool(fin.isChecked()),
            count_target=int(_spin(_SEQ_COL_COUNT).value()),
            value_a=value_a,
            mask_a=mask_a,
            value_b=value_b,
            mask_b=mask_b,
        )

    def _seq_line(self, row: int, col: int, name: str) -> str:
        w = self._seq_table.cellWidget(row, col)
        if not isinstance(w, QLineEdit):
            raise ValueError(f"Stage {row + 1}: missing {name} field.")
        return w.text()

    def _on_profile_picked(self, _idx: int) -> None:
        name = self._profile_pick.currentData()
        if name is None:
            return
        prof = self._profiles.get(str(name))
        if prof is not None:
            self._probes.setText(prof.probes)

    def _on_preset_picked(self, _idx: int) -> None:
        data = self._preset.currentData()
        if data is None:
            return
        if isinstance(data, dict):
            self.apply_trigger_history_entry(data)

    def set_hw_probe_info(self, info: Mapping[str, Any]) -> None:
        sw = int(info["sample_width"])
        depth = int(info["depth"])
        nch = int(info.get("num_channels", 1))
        self._hw_sample_w = sw
        self._hw_depth = depth
        self._hw_num_chan = max(1, nch)
        self._hw_trig_stages = max(0, int(info.get("trig_stages", 0)))
        self._channel.setMaximum(self._hw_num_chan - 1)
        self._hw_label.setText(
            f"Hardware: sample width = {sw} bits, depth = {depth}, channels = {self._hw_num_chan}."
        )
        for b in (self._btn_cfg, self._btn_arm, self._btn_cap, self._btn_cont):
            b.setEnabled(True)
        while self._seq_table.rowCount() > self._hw_trig_stages > 0:
            self._seq_table.removeRow(self._seq_table.rowCount() - 1)
        self._refresh_seq_ui_state()

    def set_busy(self, busy: bool, *, continuous: bool = False) -> None:
        self._btn_cfg.setEnabled(not busy and self._hw_sample_w is not None)
        self._btn_arm.setEnabled(not busy and self._hw_sample_w is not None)
        self._btn_cap.setEnabled(not busy and self._hw_sample_w is not None)
        self._btn_cont.setEnabled(not busy and self._hw_sample_w is not None)
        self._btn_stop.setEnabled(busy and continuous)

    def timeout_seconds(self) -> float:
        return float(self._timeout.text().strip() or "10.0")

    def build_capture_config(self) -> CaptureConfig:
        if self._hw_sample_w is None or self._hw_depth is None:
            raise ValueError("Not connected — hardware sample width / depth unknown.")
        mode = self._trig_mode.currentText().strip()
        try:
            tval = int(self._trig_val.text().strip(), 0)
            tmask = int(self._trig_mask.text().strip(), 0)
        except ValueError as exc:
            raise ValueError("Trigger value/mask must be integers (0x hex allowed).") from exc
        raw_probes = self._probes.text().strip()
        try:
            probes = _parse_probes(raw_probes) if raw_probes else []
        except argparse.ArgumentTypeError as exc:
            raise ValueError(str(exc)) from exc
        ext_key = self._ext_trig.currentText().strip().lower()
        ext_mode = {"disabled": 0, "or": 1, "and": 2}[ext_key]
        try:
            sqv = int(self._stor_val.text().strip(), 0)
            sqm = int(self._stor_mask.text().strip(), 0)
        except ValueError as exc:
            raise ValueError("Storage qual value/mask must be integers.") from exc
        sequence: list[SequencerStage] | None = None
        if self._seq_enable.isChecked():
            if self._hw_trig_stages <= 0:
                raise ValueError(
                    "Trigger sequencer is enabled but this bitstream reports TRIG_STAGES=0."
                )
            n = self._seq_table.rowCount()
            if n < 1:
                raise ValueError("Trigger sequencer enabled: add at least one stage.")
            if n > self._hw_trig_stages:
                raise ValueError(
                    f"Too many sequencer stages ({n}); hardware allows {self._hw_trig_stages}."
                )
            sequence = []
            for r in range(n):
                sequence.append(self._parse_sequencer_row(r))
        return CaptureConfig(
            pretrigger=int(self._pre.value()),
            posttrigger=int(self._post.value()),
            trigger=TriggerConfig(mode=mode, value=tval, mask=tmask),
            sample_width=self._hw_sample_w,
            depth=self._hw_depth,
            sample_clock_hz=int(self._clock_hz.value()),
            probes=probes,
            channel=int(self._channel.value()),
            decimation=int(self._decim.value()),
            ext_trigger_mode=ext_mode,
            sequence=sequence,
            probe_sel=int(self._probe_sel.value()),
            stor_qual_mode=int(self._stor_mode.value()),
            stor_qual_value=sqv,
            stor_qual_mask=sqm,
            trigger_delay=int(self._trig_delay.value()),
        )

    def wire_collapsible_persistence(self, callback: Callable[[], None]) -> None:
        self._adv_section.expandedChanged.connect(lambda _e: callback())
        self._seq_section.expandedChanged.connect(lambda _e: callback())

    def save_collapsible_ui_prefs(self, st: QSettings) -> None:
        st.setValue("ui/capture_adv_open", self._adv_section.isExpanded())
        st.setValue("ui/capture_seq_open", self._seq_section.isExpanded())

    def load_collapsible_ui_prefs(self, st: QSettings) -> None:
        if st.contains("ui/capture_adv_open"):
            self._adv_section.setExpanded(bool(st.value("ui/capture_adv_open")))
        if st.contains("ui/capture_seq_open"):
            self._seq_section.setExpanded(bool(st.value("ui/capture_seq_open")))

    def wire_handlers(
        self,
        *,
        on_configure: Callable[[], None],
        on_arm: Callable[[], None],
        on_capture: Callable[[], None],
        on_continuous: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        self._btn_cfg.clicked.connect(on_configure)
        self._btn_arm.clicked.connect(on_arm)
        self._btn_cap.clicked.connect(on_capture)
        self._btn_cont.clicked.connect(on_continuous)
        self._btn_stop.clicked.connect(on_stop)
