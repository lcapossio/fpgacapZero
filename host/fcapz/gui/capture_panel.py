# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtCore import QSignalBlocker

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ..analyzer import CaptureConfig, TriggerConfig
from ..cli import _parse_probes
from .settings import ProbeProfile


def _preset_label(ent: Mapping[str, Any]) -> str:
    pre = ent.get("pretrigger", "?")
    post = ent.get("posttrigger", "?")
    mode = ent.get("trigger_mode", "?")
    return f"{pre}/{post} {mode}"


class CapturePanel(QGroupBox):
    """ELA capture parameters (simple trigger path; no sequencer table in v0)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ELA capture", parent)
        self._hw_sample_w: int | None = None
        self._hw_depth: int | None = None
        self._hw_num_chan: int | None = None

        self._hw_label = QLabel("Connect to load sample width / depth from hardware.")
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

        form = QFormLayout()
        form.addRow(self._hw_label)
        form.addRow("Probe profile", self._profile_pick)
        form.addRow("Trigger preset", self._preset)
        form.addRow("Pre-trigger samples", self._pre)
        form.addRow("Post-trigger samples", self._post)
        form.addRow("Trigger mode", self._trig_mode)
        form.addRow("Trigger value", self._trig_val)
        form.addRow("Trigger mask", self._trig_mask)
        form.addRow("Sample clock (Hz)", self._clock_hz)
        form.addRow("Channel", self._channel)
        form.addRow("Decimation", self._decim)
        form.addRow("Probe mux sel", self._probe_sel)
        form.addRow("Ext trigger mode", self._ext_trig)
        form.addRow("Storage qual mode", self._stor_mode)
        form.addRow("Storage qual value", self._stor_val)
        form.addRow("Storage qual mask", self._stor_mask)
        form.addRow("Trigger delay", self._trig_delay)
        form.addRow("Probes", self._probes)
        form.addRow("Capture timeout (s)", self._timeout)

        grid = QGridLayout(self)
        grid.addLayout(form, 0, 0)
        grid.addLayout(row_btns, 1, 0)

    def clear_hw(self) -> None:
        self._hw_sample_w = None
        self._hw_depth = None
        self._hw_num_chan = None
        self._btn_stop.setEnabled(False)
        self._hw_label.setText("Connect to load sample width / depth from hardware.")
        for b in (self._btn_cfg, self._btn_arm, self._btn_cap, self._btn_cont):
            b.setEnabled(False)

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
        self._channel.setMaximum(self._hw_num_chan - 1)
        self._hw_label.setText(
            f"Hardware: sample width = {sw} bits, depth = {depth}, channels = {self._hw_num_chan}."
        )
        for b in (self._btn_cfg, self._btn_arm, self._btn_cap, self._btn_cont):
            b.setEnabled(True)

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
            sequence=None,
            probe_sel=int(self._probe_sel.value()),
            stor_qual_mode=int(self._stor_mode.value()),
            stor_qual_value=sqv,
            stor_qual_mask=sqm,
            trigger_delay=int(self._trig_delay.value()),
        )

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
