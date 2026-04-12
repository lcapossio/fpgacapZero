# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
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
from .settings import default_gui_config_path, live_wave_dir
from .surfer_command_writer import write_surfer_command_file_for_capture
from .surfer_wcp import SurferWcpBridge
from .viewer_tile import schedule_vertical_split_with_viewer, win32_set_external_viewer_minimized
from .viewers import GtkWaveViewer, SurferViewer, WaveformViewer
from .waveform_preview import WaveformPreviewWidget


@dataclass
class HistoryEntry:
    index: int
    when: datetime
    result: CaptureResult
    vcd_path: Path
    work_dir: Path


class HistoryPanel(QWidget):
    """Capture history table, embedded lane preview, export, and external viewer launch."""

    status_message = Signal(str)
    open_after_capture_changed = Signal(bool)
    reuse_external_viewer_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[HistoryEntry] = []
        self._viewer_rows: list[tuple[str, WaveformViewer]] = []
        self._analyzer_ref: Analyzer | None = None
        self._viewer_processes: list[QProcess] = []
        self._last_viewer_program: str | None = None
        self._live_wave_root = live_wave_dir(default_gui_config_path())
        self._surfer_wcp = SurferWcpBridge(self)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["#", "Time", "Samples", "Flags"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.doubleClicked.connect(lambda _i: self._on_open_viewer())

        self._viewer_combo = QComboBox()
        self._viewer_combo.setMinimumWidth(120)

        self._open_btn = QPushButton("Open in viewer")
        self._open_btn.clicked.connect(self._on_open_viewer)

        self._reveal_btn = QPushButton("Open capture folder")
        self._reveal_btn.clicked.connect(self._on_reveal_folder)

        self._open_after_capture = QCheckBox("Open viewer after capture")
        self._open_after_capture.toggled.connect(self.open_after_capture_changed.emit)

        self._reuse_viewer = QCheckBox("Reuse external viewer (live wave folder)")
        self._reuse_viewer.setToolTip(
            "Keeps one viewer process when possible. Each open overwrites the live-wave "
            "folder next to gui.toml. Surfer uses WCP reload when launched from here; "
            "GTKWave relies on OS file watching where available.",
        )
        self._reuse_viewer.toggled.connect(self.reuse_external_viewer_changed.emit)

        self._exp_json = QPushButton("Export JSON…")
        self._exp_json.clicked.connect(lambda: self._export_format("json"))
        self._exp_csv = QPushButton("Export CSV…")
        self._exp_csv.clicked.connect(lambda: self._export_format("csv"))
        self._exp_vcd = QPushButton("Export VCD…")
        self._exp_vcd.clicked.connect(lambda: self._export_format("vcd"))

        for b in (self._open_btn, self._reveal_btn, self._exp_json, self._exp_csv, self._exp_vcd):
            b.setEnabled(False)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Viewer:"))
        row1.addWidget(self._viewer_combo, stretch=1)
        row1.addWidget(self._open_btn)
        row1.addWidget(self._reveal_btn)

        row1b = QHBoxLayout()
        row1b.addWidget(self._open_after_capture)
        row1b.addWidget(self._reuse_viewer)
        row1b.addStretch(1)

        row2 = QHBoxLayout()
        row2.addWidget(self._exp_json)
        row2.addWidget(self._exp_csv)
        row2.addWidget(self._exp_vcd)
        row2.addStretch(1)

        self._preview = WaveformPreviewWidget()
        self._preview.setMinimumWidth(240)

        upper = QWidget()
        upper.setMinimumWidth(280)
        uv = QVBoxLayout(upper)
        uv.setContentsMargins(0, 0, 0, 0)
        uv.addWidget(self._table)
        uv.addLayout(row1)
        uv.addLayout(row1b)
        uv.addLayout(row2)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(upper)
        split.addWidget(self._preview)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([380, 520])

        grid = QGridLayout(self)
        grid.addWidget(split, 0, 0)

        self._table.itemSelectionChanged.connect(self._sync_buttons)

    def set_open_viewer_after_capture(self, enabled: bool) -> None:
        self._open_after_capture.blockSignals(True)
        self._open_after_capture.setChecked(enabled)
        self._open_after_capture.blockSignals(False)

    def set_reuse_external_viewer(self, enabled: bool) -> None:
        self._reuse_viewer.blockSignals(True)
        self._reuse_viewer.setChecked(enabled)
        self._reuse_viewer.blockSignals(False)

    def set_live_wave_root(self, root: Path) -> None:
        self._live_wave_root = root

    def set_viewer_choices(self, choices: list[tuple[str, WaveformViewer]]) -> None:
        self._viewer_rows = list(choices)
        self._viewer_combo.clear()
        for label, _ in choices:
            self._viewer_combo.addItem(label)
        self._sync_buttons()

    def select_viewer_index(self, index: int) -> None:
        if 0 <= index < self._viewer_combo.count():
            self._viewer_combo.setCurrentIndex(index)

    def sync_external_viewers_minimized(self, minimized: bool) -> None:
        """Windows: minimize or restore top-level windows of running viewer processes."""
        if sys.platform != "win32":
            return
        for proc in list(self._viewer_processes):
            if proc.state() != QProcess.ProcessState.Running:
                continue
            pid = int(proc.processId())
            if pid > 0:
                win32_set_external_viewer_minimized(pid, minimized=minimized)

    def stop_viewer_processes(self, *, aggressive: bool = False) -> None:
        """Stop external waveform viewer processes.

        ``aggressive=True`` (Ctrl+C / console interrupt): hard-kill with a short wait
        so the GUI can exit quickly instead of waiting up to 3s per ``terminate()``.
        """
        kill_wait_ms = 120 if aggressive else 1000
        for proc in list(self._viewer_processes):
            if proc.state() != QProcess.ProcessState.NotRunning:
                if aggressive:
                    proc.kill()
                    proc.waitForFinished(kill_wait_ms)
                else:
                    proc.terminate()
                    if not proc.waitForFinished(3000):
                        proc.kill()
                        proc.waitForFinished(kill_wait_ms)
            try:
                self._viewer_processes.remove(proc)
            except ValueError:
                pass
            proc.deleteLater()
        self._viewer_processes.clear()
        self._last_viewer_program = None
        self._surfer_wcp.shutdown()

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

        if self._open_after_capture.isChecked() and self._viewer_combo.count() > 0:
            i = self._viewer_combo.currentIndex()
            self._launch_viewer_for_entry(ent, i, silent=True)

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
        self._reveal_btn.setEnabled(has_row)
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

    def _prepare_sidecars(
        self,
        viewer: WaveformViewer,
        ent: HistoryEntry,
        *,
        vcd_path: Path,
        work_dir: Path,
    ) -> Path | None:
        if isinstance(viewer, GtkWaveViewer):
            gtkw = work_dir / "capture.gtkw"
            write_gtkw_for_capture(ent.result, vcd_path, gtkw)
            return gtkw
        if isinstance(viewer, SurferViewer):
            scmd = work_dir / "capture.surfer.txt"
            write_surfer_command_file_for_capture(ent.result, scmd)
            return scmd
        return None

    def _analyzer_for_wave_write(self) -> Analyzer:
        a = self._analyzer_ref
        if a is not None:
            return a
        from ..analyzer import Analyzer
        from ..transport import VendorStubTransport

        return Analyzer(VendorStubTransport("export-only"))

    def _launch_viewer_for_entry(
        self,
        ent: HistoryEntry,
        combo_index: int,
        *,
        silent: bool,
    ) -> None:
        if combo_index < 0 or combo_index >= len(self._viewer_rows):
            return
        label, viewer = self._viewer_rows[combo_index]
        if self._reuse_viewer.isChecked():
            root = self._live_wave_root
            root.mkdir(parents=True, exist_ok=True)
            vcd_path = root / "capture.vcd"
            try:
                self._analyzer_for_wave_write().write_vcd(ent.result, str(vcd_path))
            except OSError as exc:
                if silent:
                    self.status_message.emit(f"Live wave export: {exc}")
                else:
                    QMessageBox.warning(self, "Live wave export", str(exc))
                return
            work_dir = root
        else:
            vcd_path = ent.vcd_path
            work_dir = ent.work_dir

        save_path: Path | None = None
        try:
            save_path = self._prepare_sidecars(
                viewer,
                ent,
                vcd_path=vcd_path,
                work_dir=work_dir,
            )
        except OSError as exc:
            title = (
                "GTKWave layout"
                if isinstance(viewer, GtkWaveViewer)
                else "Surfer command file"
                if isinstance(viewer, SurferViewer)
                else "Viewer sidecar"
            )
            if silent:
                self.status_message.emit(f"{title}: {exc}")
            else:
                QMessageBox.warning(self, title, str(exc))
            return
        try:
            argv = viewer.launch_argv(vcd_path, save_file=save_path)
        except (OSError, ValueError) as exc:
            if silent:
                self.status_message.emit(str(exc))
            else:
                QMessageBox.warning(self, "Viewer", str(exc))
            return
        self._start_viewer_process(
            label,
            argv,
            silent=silent,
            surfer_wcp=isinstance(viewer, SurferViewer) and self._reuse_viewer.isChecked(),
        )

    def _running_viewer_process(self) -> QProcess | None:
        for p in self._viewer_processes:
            st = p.state()
            if st in (
                QProcess.ProcessState.Running,
                QProcess.ProcessState.Starting,
            ):
                return p
        return None

    def _start_viewer_process(
        self,
        viewer_label: str,
        argv: list[str],
        *,
        silent: bool,
        surfer_wcp: bool = False,
    ) -> None:
        if not argv or not argv[0]:
            msg = "Viewer command line is empty."
            self.status_message.emit(msg)
            if not silent:
                QMessageBox.warning(self, "Viewer", msg)
            return
        prog_resolved = str(Path(argv[0]).resolve())
        can_skip_respawn = sys.platform != "win32"
        wcp_ready = surfer_wcp and self._surfer_wcp.can_reload()
        # With WCP, Surfer reload is explicit; do not fall back to "assume file watcher" on Unix.
        unix_file_watcher_ok = can_skip_respawn and not surfer_wcp
        reuse_same = (
            self._reuse_viewer.isChecked()
            and self._running_viewer_process() is not None
            and self._last_viewer_program == prog_resolved
            and (wcp_ready or unix_file_watcher_ok)
        )
        if reuse_same:
            if wcp_ready:
                self._surfer_wcp.send_reload()
                self.status_message.emit(
                    f"Updated live wave for {viewer_label} — reloaded in Surfer (WCP).",
                )
            else:
                self.status_message.emit(
                    f"Updated live wave for {viewer_label} — reload if the viewer did not refresh.",
                )
            return

        # Different viewer binary, or not reusing, or no running process: replace.
        self.stop_viewer_processes()
        if surfer_wcp:
            port = self._surfer_wcp.prepare_listener()
            if port is not None:
                argv = [argv[0], "--wcp-initiate", str(port)] + argv[1:]
        proc = QProcess(self)
        proc.setProgram(argv[0])
        proc.setArguments(argv[1:])
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)

        def _on_started() -> None:
            self._viewer_processes.append(proc)
            self._last_viewer_program = prog_resolved
            self.status_message.emit(f"Started {viewer_label} (separate window)")
            schedule_vertical_split_with_viewer(self, proc)

        def _on_error(_e: QProcess.ProcessError) -> None:
            err = (proc.errorString() or "Viewer failed to start").strip()
            self.status_message.emit(err)
            if not silent:
                QMessageBox.warning(self, "Viewer", err)

        def _on_finished(_exit_code: int, _status: QProcess.ExitStatus) -> None:
            try:
                self._viewer_processes.remove(proc)
            except ValueError:
                pass
            if not self._viewer_processes:
                self._last_viewer_program = None
            proc.deleteLater()

        proc.started.connect(_on_started)
        proc.errorOccurred.connect(_on_error)
        proc.finished.connect(_on_finished)
        proc.start()

    def _on_open_viewer(self) -> None:
        ent = self.selected_entry()
        if ent is None:
            return
        i = self._viewer_combo.currentIndex()
        self._launch_viewer_for_entry(ent, i, silent=False)

    def _on_reveal_folder(self) -> None:
        ent = self.selected_entry()
        if ent is None:
            return
        url = QUrl.fromLocalFile(str(ent.work_dir.resolve()))
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "Open folder",
                "Could not open the capture folder in the file manager.",
            )

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

            a = Analyzer(VendorStubTransport("export-only"))
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
