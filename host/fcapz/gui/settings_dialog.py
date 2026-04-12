# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Edit ``gui.toml`` viewers, probe profiles, and UI appearance."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .settings import GuiSettings, ProbeProfile, UiSettings, ViewerSettings


class SettingsDialog(QDialog):
    """Modal editor; merges viewer + profile changes into :class:`GuiSettings`."""

    def __init__(self, settings: GuiSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("fcapz-gui settings")
        self.resize(520, 420)
        self._base = settings

        self._default_viewer = QComboBox()
        for key, label in (
            ("gtkwave", "GTKWave"),
            ("surfer", "Surfer"),
            ("wavetrace", "WaveTrace"),
            ("custom", "Custom command"),
        ):
            self._default_viewer.addItem(label, key)
        dv = settings.viewers.default_viewer.strip().lower()
        for i in range(self._default_viewer.count()):
            if self._default_viewer.itemData(i) == dv:
                self._default_viewer.setCurrentIndex(i)
                break

        self._gtkw = QLineEdit()
        self._gtkw.setPlaceholderText("Optional path to gtkwave executable")
        if settings.viewers.gtkwave_executable:
            self._gtkw.setText(settings.viewers.gtkwave_executable)

        self._surf = QLineEdit()
        self._surf.setPlaceholderText("Optional path to surfer executable")
        if settings.viewers.surfer_executable:
            self._surf.setText(settings.viewers.surfer_executable)

        self._wt = QLineEdit()
        self._wt.setPlaceholderText("Optional path to WaveTrace executable")
        if settings.viewers.wavetrace_executable:
            self._wt.setText(settings.viewers.wavetrace_executable)

        self._custom = QPlainTextEdit()
        self._custom.setPlaceholderText(
            "One argv token per line for “Custom command” viewer.\n"
            "Use placeholders {VCD} and optionally {SAVE}.\n"
            'Example: myviewer\n--wave\n{VCD}',
        )
        self._custom.setMaximumHeight(120)
        if settings.viewers.custom_argv:
            self._custom.setPlainText("\n".join(settings.viewers.custom_argv))

        self._open_after_capture = QCheckBox(
            "Open external viewer automatically after each capture",
        )
        self._open_after_capture.setChecked(settings.viewers.open_viewer_after_capture)

        self._reuse_viewer = QCheckBox(
            "Reuse one external viewer (live-wave folder; hot-reload on Unix, respawn on Windows)",
        )
        self._reuse_viewer.setChecked(settings.viewers.reuse_external_viewer)

        self._font_pt = QSpinBox()
        self._font_pt.setRange(8, 20)
        self._font_pt.setSuffix(" pt")
        self._font_pt.setValue(int(settings.ui.font_size_pt))
        self._font_pt.setToolTip(
            "Application-wide default font size. Restart is not required; "
            "takes effect when you click OK.",
        )

        self._log_font_pt = QSpinBox()
        self._log_font_pt.setRange(7, 24)
        self._log_font_pt.setSuffix(" pt")
        self._log_font_pt.setValue(int(settings.ui.log_font_size_pt))
        self._log_font_pt.setToolTip(
            "Monospace font size for the Log dock only. Takes effect when you click OK.",
        )

        appearance_tab = QWidget()
        af = QFormLayout(appearance_tab)
        af.addRow(
            "UI font size",
            self._font_pt,
        )
        af.addRow(
            "Log font size",
            self._log_font_pt,
        )
        _hint = QLabel(
            "Smaller UI values help on small screens (default 9 pt). "
            "Log font size applies only to the bottom Log dock (monospace).",
        )
        _hint.setWordWrap(True)
        af.addRow(_hint)

        viewers_tab = QWidget()
        vf = QFormLayout(viewers_tab)
        vf.addRow("Default viewer", self._default_viewer)
        vf.addRow("GTKWave", self._path_row(self._gtkw, self._browse_btn(self._gtkw)))
        vf.addRow("Surfer", self._path_row(self._surf, self._browse_btn(self._surf)))
        vf.addRow("WaveTrace", self._path_row(self._wt, self._browse_btn(self._wt)))
        vf.addRow("Custom argv", self._custom)
        vf.addRow("", self._open_after_capture)
        vf.addRow("", self._reuse_viewer)

        path_lbl = QLabel(f"Config file: {self._config_path_hint()}")
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet("color: palette(mid); font-size: 11px;")
        vf.addRow(path_lbl)

        self._prof_table = QTableWidget(0, 2)
        self._prof_table.setHorizontalHeaderLabels(["Profile name", "Probes (name:width:lsb,…)"])
        self._prof_table.horizontalHeader().setStretchLastSection(True)
        for name in sorted(settings.probe_profiles):
            prof = settings.probe_profiles[name]
            self._append_profile_row(prof.name, prof.probes)

        prof_btns = QHBoxLayout()
        add_btn = QPushButton("Add row")
        add_btn.clicked.connect(self._add_profile_row)
        rm_btn = QPushButton("Remove selected")
        rm_btn.clicked.connect(self._remove_profile_row)
        prof_btns.addWidget(add_btn)
        prof_btns.addWidget(rm_btn)
        prof_btns.addStretch(1)

        profiles_tab = QWidget()
        pl = QVBoxLayout(profiles_tab)
        pl.addWidget(
            QLabel("Named probe strings for CLI --profile and shared via gui.toml."),
        )
        pl.addWidget(self._prof_table)
        pl.addLayout(prof_btns)

        tabs = QTabWidget()
        tabs.addTab(appearance_tab, "Appearance")
        tabs.addTab(viewers_tab, "Viewers")
        tabs.addTab(profiles_tab, "Probe profiles")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addWidget(buttons)

    def _config_path_hint(self) -> str:
        p = getattr(self.parent(), "_config_path", None)
        if isinstance(p, Path):
            return str(p)
        return "(save path from main window)"

    @staticmethod
    def _path_row(edit: QLineEdit, browse: QPushButton) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, stretch=1)
        h.addWidget(browse)
        return row

    def _browse_btn(self, target: QLineEdit) -> QPushButton:
        btn = QPushButton("Browse…")

        def _go() -> None:
            filt = (
                "Executable (*.exe);;All files (*.*)"
                if sys.platform == "win32"
                else "All files (*)"
            )
            path, _ = QFileDialog.getOpenFileName(self, "Select executable", "", filt)
            if path:
                target.setText(path)

        btn.clicked.connect(_go)
        return btn

    def _append_profile_row(self, name: str = "", probes: str = "") -> None:
        r = self._prof_table.rowCount()
        self._prof_table.insertRow(r)
        self._prof_table.setItem(r, 0, QTableWidgetItem(name))
        self._prof_table.setItem(r, 1, QTableWidgetItem(probes))

    def _add_profile_row(self) -> None:
        self._append_profile_row("", "")

    def _remove_profile_row(self) -> None:
        r = self._prof_table.currentRow()
        if r >= 0:
            self._prof_table.removeRow(r)

    def _on_accept(self) -> None:
        custom_lines = [ln.strip() for ln in self._custom.toPlainText().splitlines() if ln.strip()]
        dv_idx = self._default_viewer.currentData()
        if dv_idx == "custom" and not custom_lines:
            QMessageBox.warning(
                self,
                "Custom viewer",
                "Default viewer is “Custom command” but custom argv is empty.",
            )
            return
        self.accept()

    def merged_settings(self) -> GuiSettings:
        custom_lines = [ln.strip() for ln in self._custom.toPlainText().splitlines() if ln.strip()]
        dv = str(self._default_viewer.currentData() or ViewerSettings().default_viewer)
        viewers = ViewerSettings(
            default_viewer=dv,
            gtkwave_executable=_empty_to_none(self._gtkw.text()),
            surfer_executable=_empty_to_none(self._surf.text()),
            wavetrace_executable=_empty_to_none(self._wt.text()),
            custom_argv=custom_lines,
            open_viewer_after_capture=self._open_after_capture.isChecked(),
            reuse_external_viewer=self._reuse_viewer.isChecked(),
        )
        profiles: dict[str, ProbeProfile] = {}
        for r in range(self._prof_table.rowCount()):
            n_item = self._prof_table.item(r, 0)
            p_item = self._prof_table.item(r, 1)
            name = (n_item.text().strip() if n_item else "") or ""
            probes = (p_item.text().strip() if p_item else "") or ""
            if not name and not probes:
                continue
            if not name:
                continue
            profiles[name] = ProbeProfile(name=name, probes=probes)
        font_pt = max(8, min(24, int(self._font_pt.value())))
        log_font_pt = max(7, min(24, int(self._log_font_pt.value())))
        ui = UiSettings(font_size_pt=font_pt, log_font_size_pt=log_font_pt)
        return GuiSettings(
            connection=self._base.connection,
            viewers=viewers,
            ui=ui,
            probe_profiles=profiles,
            trigger_history=list(self._base.trigger_history),
        )


def _empty_to_none(s: str) -> str | None:
    s = s.strip()
    return s if s else None
