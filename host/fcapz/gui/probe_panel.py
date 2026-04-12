# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Mapping

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGroupBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from .collapsible_section import CollapsibleSection


def _format_probe_summary(info: Mapping[str, Any]) -> str:
    lines: list[str] = []
    vmaj = info.get("version_major")
    vmin = info.get("version_minor")
    if vmaj is not None and vmin is not None:
        lines.append(f"ELA core v{int(vmaj)}.{int(vmin)}")
    sw = info.get("sample_width")
    dep = info.get("depth")
    nch = info.get("num_channels")
    if sw is not None and dep is not None:
        nc = int(nch) if nch is not None else 1
        lines.append(f"{int(sw)}-bit samples · depth {int(dep)} · {nc} channel(s)")
    ts = info.get("trig_stages")
    if ts is not None:
        lines.append(f"Trigger sequencer stages: {int(ts)}")
    flags: list[str] = []
    if info.get("has_storage_qualification"):
        flags.append("storage qualification")
    if info.get("has_decimation"):
        flags.append("decimation")
    if info.get("has_ext_trigger"):
        flags.append("ext trigger")
    if info.get("has_timestamp"):
        tw = info.get("timestamp_width", "?")
        flags.append(f"timestamp ({tw} b)")
    if flags:
        lines.append("Features: " + ", ".join(flags))
    parts: list[str] = []
    nseg = info.get("num_segments")
    if nseg is not None:
        parts.append(f"segments {int(nseg)}")
    pmw = info.get("probe_mux_w")
    if pmw is not None:
        parts.append(f"probe mux width {int(pmw)}")
    if parts:
        lines.append(" · ".join(parts))
    return "\n".join(lines) if lines else "(no summary fields)"


class ProbePanel(QGroupBox):
    """Read-only view of :meth:`fcapz.analyzer.Analyzer.probe` results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ELA identity", parent)
        self._summary = QLabel("Connect to load a short hardware summary.")
        self._summary.setWordWrap(True)

        self._raw = QPlainTextEdit()
        self._raw.setReadOnly(True)
        self._raw.setPlaceholderText("Full JSON from probe() …")
        self._raw.setMaximumBlockCount(0)
        font = self._raw.font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._raw.setFont(font)
        self._raw.setMinimumHeight(80)
        self._raw.setMaximumHeight(220)

        self._raw_section = CollapsibleSection("Raw probe JSON", self._raw, start_open=False)

        lay = QVBoxLayout(self)
        lay.addWidget(self._summary)
        lay.addWidget(self._raw_section)

    def set_probe_info(self, info: Mapping[str, Any] | None) -> None:
        if info is None:
            self._summary.setText(
                "JTAG is connected, but USER1 does not report an fcapz ELA (VERSION "
                "lacks the 'LA' core id). ELA capture and identity details are disabled. "
                "You can still use EIO, EJTAG-AXI, or UART from their docks on the "
                "correct BSCAN chains if your bitstream includes those cores.",
            )
            self._raw.clear()
            self._raw.setPlaceholderText("No ELA — probe JSON not available.")
            return
        self._summary.setText(_format_probe_summary(info))
        self._raw.setPlainText(json.dumps(dict(info), indent=2))
        self._raw.setPlaceholderText("Full JSON from probe() …")

    def clear(self) -> None:
        self._summary.setText("Connect to load a short hardware summary.")
        self._raw.clear()

    def wire_collapsible_persistence(self, callback: Callable[[], None]) -> None:
        self._raw_section.expandedChanged.connect(lambda _e: callback())

    def save_collapsible_ui_prefs(self, st: QSettings) -> None:
        st.setValue("ui/probe_raw_open", self._raw_section.isExpanded())

    def load_collapsible_ui_prefs(self, st: QSettings) -> None:
        if st.contains("ui/probe_raw_open"):
            self._raw_section.setExpanded(bool(st.value("ui/probe_raw_open")))
