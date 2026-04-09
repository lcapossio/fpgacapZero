# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..analyzer import Analyzer, CaptureResult
from .gtkw_writer import write_gtkw_for_capture
from .surfer_command_writer import write_surfer_command_file_for_capture
from .viewers import GtkWaveViewer, SurferViewer, WaveformViewer
from .waveform_preview import WaveformPreviewWidget


@dataclass
class HistoryEntry:
    index: int
    when: datetime
    result: CaptureResult
    vcd_path: Path
    work_dir: Path


class HistoryPanel(QGroupBox):
    """Capture history, embedded preview, export, and external viewer launch."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Capture history & waveform preview", parent)
        self._entries: list[HistoryEntry] = []
        self._viewer_rows: list[tuple[str, WaveformViewer]] = []
        self._analyzer_ref: Analyzer | None = None

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["#", "Time", "Samples", "Flags"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.doubleClicked.connect(lambda _i: self._on_open_viewer())

        self._viewer_combo = QComboBox()
        self._viewer_combo.setMinimumWidth(160)

        self._open_btn = QPushButton("Open in viewer")
        self._open_btn.clicked.connect(self._on_open_viewer)

        self._exp_json = QPushButton("Export JSON…")
        self._exp_json.clicked.connect(lambda: self._export_format("json"))
        self._exp_csv = QPushButton("Export CSV…")
        self._exp_csv.clicked.connect(lambda: self._export_format("csv"))
        self._exp_vcd = QPushButton("Export VCD…")
        self._exp_vcd.clicked.connect(lambda: self._export_format("vcd"))

        for b in (self._open_btn, self._exp_json, self._exp_csv, self._exp_vcd):
            b.setEnabled(False)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Viewer:"))
        row1.addWidget(self._viewer_combo, stretch=1)
        row1.addWidget(self._open_btn)

        row2 = QHBoxLayout()
        row2.addWidget(self._exp_json)
        row2.addWidget(self._exp_csv)
        row2.addWidget(self._exp_vcd)
        row2.addStretch(1)

        self._preview = WaveformPreviewWidget()

        upper = QWidget()
        uv = QVBoxLayout(upper)
        uv.setContentsMargins(0, 0, 0, 0)
        uv.addWidget(self._table)
        uv.addLayout(row1)
        uv.addLayout(row2)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(upper)
        split.addWidget(self._preview)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([260, 340])

        grid = QGridLayout(self)
        grid.addWidget(split, 0, 0)

        self._table.itemSelectionChanged.connect(self._sync_buttons)

    def set_viewer_choices(self, choices: list[tuple[str, WaveformViewer]]) -> None:
        self._viewer_rows = list(choices)
        self._viewer_combo.clear()
        for label, _ in choices:
            self._viewer_combo.addItem(label)
        self._sync_buttons()

    def select_viewer_index(self, index: int) -> None:
        if 0 <= index < self._viewer_combo.count():
            self._viewer_combo.setCurrentIndex(index)

    def add_capture(self, analyzer: Analyzer, result: CaptureResult) -> None:
        work = Path(tempfile.mkdtemp(prefix="fcapz-gui-cap-"))
        vcd = work / "capture.vcd"
        analyzer.write_vcd(result, str(vcd))
        idx = len(self._entries) + 1
        ent = HistoryEntry(
            index=idx,
            when=datetime.now(),
            result=result,
            vcd_path=vcd,
            work_dir=work,
        )
        self._entries.append(ent)
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(str(idx)))
        self._table.setItem(row, 1, QTableWidgetItem(ent.when.strftime("%H:%M:%S")))
        self._table.setItem(row, 2, QTableWidgetItem(str(len(result.samples))))
        flag = "overflow" if result.overflow else "ok"
        self._table.setItem(row, 3, QTableWidgetItem(flag))
        for c in range(4):
            it = self._table.item(row, c)
            if it is not None:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.selectRow(row)
        self._sync_buttons()

    def selected_entry(self) -> HistoryEntry | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        r = rows[0].row()
        if 0 <= r < len(self._entries):
            return self._entries[r]
        return None

    def _sync_buttons(self) -> None:
        has_row = self.selected_entry() is not None
        has_viewer = self._viewer_combo.count() > 0
        can_export = has_row
        self._open_btn.setEnabled(has_row and has_viewer)
        self._exp_json.setEnabled(can_export)
        self._exp_csv.setEnabled(can_export)
        self._exp_vcd.setEnabled(can_export)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        ent = self.selected_entry()
        if ent is None:
            self._preview.clear()
        else:
            self._preview.show_result(ent.result)

    def _on_open_viewer(self) -> None:
        ent = self.selected_entry()
        if ent is None:
            return
        i = self._viewer_combo.currentIndex()
        if i < 0 or i >= len(self._viewer_rows):
            return
        _, viewer = self._viewer_rows[i]
        save_path: Path | None = None
        if isinstance(viewer, GtkWaveViewer):
            gtkw = ent.work_dir / "capture.gtkw"
            try:
                write_gtkw_for_capture(ent.result, ent.vcd_path, gtkw)
                save_path = gtkw
            except OSError as exc:
                QMessageBox.warning(self, "GTKWave layout", str(exc))
        elif isinstance(viewer, SurferViewer):
            scmd = ent.work_dir / "capture.surfer.txt"
            try:
                write_surfer_command_file_for_capture(ent.result, scmd)
                save_path = scmd
            except OSError as exc:
                QMessageBox.warning(self, "Surfer command file", str(exc))
        try:
            viewer.open(ent.vcd_path, save_file=save_path)
        except OSError as exc:
            QMessageBox.warning(self, "Viewer", str(exc))
        except ValueError as exc:
            QMessageBox.warning(self, "Viewer", str(exc))

    def _export_format(self, fmt: str) -> None:
        ent = self.selected_entry()
        if ent is None:
            return
        filt = {"json": "JSON (*.json)", "csv": "CSV (*.csv)", "vcd": "VCD (*.vcd)"}[fmt]
        path, _ = QFileDialog.getSaveFileName(self, f"Export {fmt.upper()}", "", filt)
        if not path:
            return
        a = self._analyzer_ref
        if a is None:
            from ..analyzer import Analyzer
            from ..transport import VendorStubTransport

            a = Analyzer(VendorStubTransport())
        try:
            if fmt == "json":
                a.write_json(ent.result, path)
            elif fmt == "csv":
                a.write_csv(ent.result, path)
            else:
                a.write_vcd(ent.result, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def set_analyzer_ref(self, analyzer: Analyzer | None) -> None:
        """Used for export writers (same as live session)."""
        self._analyzer_ref = analyzer

    def cleanup_temp_dirs(self) -> None:
        for ent in self._entries:
            if ent.work_dir.is_dir():
                shutil.rmtree(ent.work_dir, ignore_errors=True)
        self._entries.clear()
        self._table.setRowCount(0)
        self._preview.clear()
        self._sync_buttons()
