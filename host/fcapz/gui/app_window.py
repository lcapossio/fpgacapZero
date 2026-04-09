# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import logging
import re
import signal
import sys
from functools import partial
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QElapsedTimer,
    QMetaObject,
    QSettings,
    QSize,
    QThread,
    QTimer,
    Qt,
    QUrl,
)
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QToolBar,
    QWidget,
)

from ..analyzer import Analyzer, CaptureConfig, CaptureResult
from ..eio import EioController
from ..ejtagaxi import AXIError, EjtagAxiController
from ..ejtaguart import EjtagUartController
from .axi_panel import AxiPanel
from .capture_panel import CapturePanel
from .connection_panel import ConnectionPanel
from .eio_panel import EioPanel
from .history_panel import HistoryPanel
from .log_panel import LogPanel
from .probe_panel import ProbePanel
from .uart_panel import UartPanel
from .settings import (
    GuiSettings,
    append_trigger_history,
    default_gui_config_path,
    load_gui_settings,
    save_gui_settings,
    trigger_history_entry_from_config,
)
from .scroll_wrap import scroll_wrap
from .settings_dialog import SettingsDialog
from .viewer_registry import viewers_for_settings
from .worker import CaptureWorker, ConnectWorker

_log = logging.getLogger("fcapz.gui")

_DOCK_FEATURES = (
    QDockWidget.DockWidgetFeature.DockWidgetClosable
    | QDockWidget.DockWidgetFeature.DockWidgetMovable
    | QDockWidget.DockWidgetFeature.DockWidgetFloatable
)

# Bump when dock object names / layout schema change so old blobs are not restored.
_WINDOW_STATE_VERSION = 3


def _sanitize_user_layout_key(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_")[:48]
    return s or "layout"


def _qsettings_to_qbytearray(val: object) -> QByteArray | None:
    if isinstance(val, QByteArray):
        return None if val.isEmpty() else val
    if isinstance(val, (bytes, bytearray)) and len(val) > 0:
        return QByteArray(bytes(val))
    return None


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        restore_saved_layout: bool = True,
        persist_window_layout: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle("fcapz-gui")
        self.resize(1000, 820)
        self._gui_log_handler: logging.Handler | None = None
        self._persist_window_layout = persist_window_layout
        self._initial_post_show_layout = False
        self._m_user_load: QMenu | None = None
        self._m_user_delete: QMenu | None = None

        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(50)
        self._reflow_timer.timeout.connect(self._reflow_dock_areas)

        self._persist_layout_timer = QTimer(self)
        self._persist_layout_timer.setSingleShot(True)
        self._persist_layout_timer.setInterval(400)
        self._persist_layout_timer.timeout.connect(self._save_window_layout_to_settings)

        self._ui_prefs_timer = QTimer(self)
        self._ui_prefs_timer.setSingleShot(True)
        self._ui_prefs_timer.setInterval(300)
        self._ui_prefs_timer.timeout.connect(self._save_collapsible_ui_prefs)

        self._config_path = default_gui_config_path()
        self._analyzer: Analyzer | None = None
        self._cap_thread: QThread | None = None
        self._cap_worker: CaptureWorker | None = None
        self._connect_thread: QThread | None = None
        self._connect_worker: ConnectWorker | None = None
        self._continuous_mode = False
        self._eio: EioController | None = None
        self._axi: EjtagAxiController | None = None
        self._uart: EjtagUartController | None = None

        self._conn = ConnectionPanel()
        self._conn.connect_requested.connect(self._on_connect)
        self._conn.disconnect_requested.connect(self._on_disconnect)

        self._probe = ProbePanel()
        self._capture = CapturePanel()
        self._capture.wire_handlers(
            on_configure=self._on_configure,
            on_arm=self._on_arm,
            on_capture=self._on_capture_clicked,
            on_continuous=self._on_continuous_clicked,
            on_stop=self._on_stop_continuous,
        )

        self._history = HistoryPanel()

        self._eio_panel = EioPanel()
        self._eio_panel.attach_requested.connect(self._on_eio_attach)
        self._axi_panel = AxiPanel()
        self._axi_panel.attach_requested.connect(self._on_axi_attach)
        self._uart_panel = UartPanel()
        self._uart_panel.attach_requested.connect(self._on_uart_attach)

        self._log_panel = LogPanel()
        self._gui_log_handler = self._log_panel.make_handler()
        self._gui_log_handler.setLevel(logging.INFO)
        _fcapz_log = logging.getLogger("fcapz")
        _fcapz_log.addHandler(self._gui_log_handler)
        if _fcapz_log.level == logging.NOTSET:
            _fcapz_log.setLevel(logging.INFO)
        self._log_panel.set_qt_handler(self._gui_log_handler)
        _log.info("fcapz-gui started")

        _ui_st = self._window_qsettings()
        self._capture.load_collapsible_ui_prefs(_ui_st)
        self._probe.load_collapsible_ui_prefs(_ui_st)

        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
        )

        self.setCentralWidget(self._history)

        self._dock_capture = QDockWidget("ELA capture", self)
        self._dock_capture.setObjectName("dock_elacapture")
        self._dock_capture.setWidget(
            scroll_wrap(self._capture, min_width=300, min_height=300),
        )
        self._dock_capture.setFeatures(_DOCK_FEATURES)

        self._dock_eio = QDockWidget("EIO", self)
        self._dock_eio.setObjectName("dock_eio")
        self._dock_eio.setWidget(scroll_wrap(self._eio_panel, min_width=280, min_height=260))
        self._dock_eio.setFeatures(_DOCK_FEATURES)

        self._dock_axi = QDockWidget("AXI", self)
        self._dock_axi.setObjectName("dock_axi")
        self._dock_axi.setWidget(scroll_wrap(self._axi_panel, min_width=280, min_height=280))
        self._dock_axi.setFeatures(_DOCK_FEATURES)

        self._dock_uart = QDockWidget("UART", self)
        self._dock_uart.setObjectName("dock_uart")
        self._dock_uart.setWidget(scroll_wrap(self._uart_panel, min_width=280, min_height=220))
        self._dock_uart.setFeatures(_DOCK_FEATURES)

        self._workbench_docks: list[QDockWidget] = [
            self._dock_capture,
            self._dock_eio,
            self._dock_axi,
            self._dock_uart,
        ]

        self._dock_conn = QDockWidget("Connection", self)
        self._dock_conn.setObjectName("dock_connection")
        self._dock_conn.setWidget(
            scroll_wrap(self._conn, min_width=220, min_height=180),
        )
        self._dock_conn.setFeatures(_DOCK_FEATURES)

        self._dock_probe = QDockWidget("ELA identity", self)
        self._dock_probe.setObjectName("dock_identity")
        self._dock_probe.setWidget(
            scroll_wrap(self._probe, min_width=240, min_height=120),
        )
        self._dock_probe.setFeatures(_DOCK_FEATURES)

        self._dock_log = QDockWidget("Log", self)
        self._dock_log.setObjectName("dock_log")
        self._dock_log.setWidget(
            scroll_wrap(self._log_panel, min_width=260, min_height=160),
        )
        self._dock_log.setFeatures(_DOCK_FEATURES)

        self._tool_docks: list[QDockWidget] = [
            *self._workbench_docks,
            self._dock_conn,
            self._dock_probe,
            self._dock_log,
        ]

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._dock_conn)
        self.splitDockWidget(self._dock_conn, self._dock_probe, Qt.Orientation.Vertical)

        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self._dock_capture)
        self.tabifyDockWidget(self._dock_capture, self._dock_eio)
        self.tabifyDockWidget(self._dock_capture, self._dock_axi)
        self.tabifyDockWidget(self._dock_capture, self._dock_uart)
        self._dock_capture.raise_()

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._dock_log)

        for _dock in self._tool_docks:
            _dock.visibilityChanged.connect(self._on_tool_dock_geometry_changed)
            _dock.topLevelChanged.connect(self._on_tool_dock_geometry_changed)
            _dock.dockLocationChanged.connect(self._on_tool_dock_geometry_changed)

        self._layout_default_state = self.saveState(_WINDOW_STATE_VERSION)
        if restore_saved_layout:
            self._restore_window_layout_from_settings()

        self.statusBar().showMessage("Ready")

        self._build_toolbar()
        self._build_menus()

        self._capture.wire_collapsible_persistence(self._schedule_ui_prefs_save)
        self._probe.wire_collapsible_persistence(self._schedule_ui_prefs_save)

        settings = load_gui_settings(self._config_path)
        self._conn.load_from_settings(settings.connection)
        self._capture.set_probe_profiles(settings.probe_profiles)
        self._capture.set_trigger_history(settings.trigger_history)
        self._apply_viewer_choices(settings)

    def _apply_viewer_choices(self, gui_settings: GuiSettings) -> None:
        choices = viewers_for_settings(gui_settings)
        self._history.set_viewer_choices(choices)
        default = gui_settings.viewers.default_viewer.strip().lower()
        for i, (label, _) in enumerate(choices):
            if label.lower() == default or default in label.lower():
                self._history.select_viewer_index(i)
                break

    def _capture_running(self) -> bool:
        return self._cap_thread is not None and self._cap_thread.isRunning()

    def _on_connect(self) -> None:
        if self._connect_thread is not None and self._connect_thread.isRunning():
            return
        conn = self._conn.connection_settings()
        self.statusBar().showMessage("Connecting…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._conn.set_connect_in_progress(True)
        _log.info("Connecting (backend=%s host=%s port=%s)", conn.backend, conn.host, conn.port)

        thread = QThread()
        worker = ConnectWorker(conn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_connect_worker_finished)
        worker.failed.connect(self._on_connect_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_connect_thread_finished)

        self._connect_thread = thread
        self._connect_worker = worker
        thread.start()

    def _on_connect_worker_finished(
        self,
        analyzer: Analyzer,
        info: Mapping[str, Any],
    ) -> None:
        QApplication.restoreOverrideCursor()
        conn = self._conn.connection_settings()
        _log.info(
            "Connected: %d-bit samples depth=%d trig_stages=%d",
            int(info.get("sample_width", 0)),
            int(info.get("depth", 0)),
            int(info.get("trig_stages", 0)),
        )
        self._analyzer = analyzer
        self._probe.set_probe_info(info)
        self._capture.set_hw_probe_info(info)
        self._history.set_analyzer_ref(analyzer)
        self._eio_panel.set_transport(analyzer.transport)
        self._axi_panel.set_transport_available(True)
        self._uart_panel.set_transport_available(True)
        self._conn.set_connected(True, "Connected — ELA identity OK.")
        self.statusBar().showMessage("Connected")

        gui = load_gui_settings(self._config_path)
        gui.connection = conn
        save_gui_settings(gui, self._config_path)
        self._apply_viewer_choices(gui)
        self._capture.set_probe_profiles(gui.probe_profiles)
        self._capture.set_trigger_history(gui.trigger_history)

    def _on_connect_worker_failed(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage("Connect failed")
        _log.error("Connection failed: %s", message)
        QMessageBox.critical(self, "Connection failed", message)

    def _on_connect_thread_finished(self) -> None:
        self._conn.set_connect_in_progress(False)
        w, self._connect_worker = self._connect_worker, None
        t, self._connect_thread = self._connect_thread, None
        if w is not None:
            w.deleteLater()
        if t is not None:
            t.deleteLater()

    def _join_connect_thread(self) -> None:
        """Wait for an in-flight connect without deadlocking the GUI thread."""
        t = self._connect_thread
        if t is None or not t.isRunning():
            return
        timer = QElapsedTimer()
        timer.start()
        while t.isRunning() and timer.elapsed() < 15_000:
            QApplication.processEvents()
            t.wait(50)
        if t.isRunning():
            _log.warning("Connect thread did not finish before window close")

    def _window_settings_path(self) -> Path:
        d = self._config_path.parent
        d.mkdir(parents=True, exist_ok=True)
        return d / "fcapz-gui-window.ini"

    def _window_qsettings(self) -> QSettings:
        """INI next to ``gui.toml`` so layout survives restarts reliably (incl. QByteArray)."""
        return QSettings(str(self._window_settings_path()), QSettings.Format.IniFormat)

    def _on_tool_dock_geometry_changed(self, *_args: object) -> None:
        self._schedule_dock_reflow()
        self._schedule_persist_layout()

    def _schedule_dock_reflow(self) -> None:
        self._reflow_timer.start()

    def _schedule_persist_layout(self) -> None:
        if not self._persist_window_layout:
            return
        self._persist_layout_timer.start()

    def _reflow_dock_areas(self) -> None:
        """After docks show/hide, nudge Qt sizes so the central area and docks stay usable."""
        h = max(1, self.height())
        left = [
            d
            for d in (self._dock_conn, self._dock_probe)
            if d.isVisible() and not d.isFloating()
        ]
        if len(left) == 2:
            h_each = max(180, min(420, (h - 96) // 2))
            self.resizeDocks(left, [h_each, h_each], Qt.Orientation.Vertical)
        elif len(left) == 1:
            self.resizeDocks(left, [max(220, min(520, (h - 96) * 2 // 5))], Qt.Orientation.Vertical)

        top_rep = next(
            (
                d
                for d in self._workbench_docks
                if d.isVisible() and not d.isFloating()
            ),
            None,
        )
        if top_rep is not None:
            h_top = max(260, min(560, (h * 2) // 5))
            self.resizeDocks([top_rep], [h_top], Qt.Orientation.Vertical)

        if self._dock_log.isVisible() and not self._dock_log.isFloating():
            h_bottom = max(120, min(360, h // 4))
            self.resizeDocks([self._dock_log], [h_bottom], Qt.Orientation.Vertical)

    def _apply_post_show_layout(self) -> None:
        self._reflow_dock_areas()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._initial_post_show_layout:
            self._initial_post_show_layout = True
            QTimer.singleShot(0, self._apply_post_show_layout)

    def _restore_window_layout_from_settings(self) -> None:
        st = self._window_qsettings()
        geom = st.value("mainWindow/geometry")
        if isinstance(geom, QByteArray) and not geom.isEmpty():
            self.restoreGeometry(geom)
        elif isinstance(geom, bytes) and len(geom) > 0:
            self.restoreGeometry(QByteArray(geom))

        ws = st.value("mainWindow/windowState")
        blob: QByteArray | None = None
        if isinstance(ws, QByteArray) and not ws.isEmpty():
            blob = ws
        elif isinstance(ws, bytes) and len(ws) > 0:
            blob = QByteArray(ws)
        if blob is None:
            return
        ok = self.restoreState(blob, _WINDOW_STATE_VERSION)
        for legacy_ver in (2, 1, 0):
            if ok:
                break
            ok = self.restoreState(blob, legacy_ver)
        if not ok:
            _log.warning("Saved dock layout was rejected; using built-in default.")

    def _save_window_layout_to_settings(self) -> None:
        if not self._persist_window_layout:
            return
        st = self._window_qsettings()
        st.setValue("mainWindow/geometry", self.saveGeometry())
        st.setValue("mainWindow/windowState", self.saveState(_WINDOW_STATE_VERSION))
        st.setValue("mainWindow/stateSchema", _WINDOW_STATE_VERSION)
        st.sync()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main actions", self)
        tb.setObjectName("mainToolbar")
        tb.setMovable(True)
        # Icon-only avoids text+icon fighting for width on Windows styles (overlapping buttons).
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setIconSize(QSize(24, 24))
        # Movable toolbar grip + tight native sizing can crush the first button; enforce
        # hit-box and margins, and leave a gap after the handle.
        tb.setStyleSheet(
            "#mainToolbar QToolButton {\n"
            "  min-width: 36px;\n"
            "  min-height: 30px;\n"
            "  padding: 5px;\n"
            "  margin-left: 3px;\n"
            "  margin-right: 3px;\n"
            "}\n",
        )
        lay = tb.layout()
        if lay is not None:
            lay.setSpacing(2)
            lay.setContentsMargins(6, 4, 8, 4)

        sty = self.style()

        def _tb_spacer(px: int = 8) -> QWidget:
            w = QWidget()
            w.setFixedWidth(px)
            w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.MinimumExpanding)
            return w

        def _add(icon_pixmap: QStyle.StandardPixmap, text: str, slot: object) -> None:
            act = tb.addAction(sty.standardIcon(icon_pixmap), text, slot)
            act.setToolTip(text)

        tb.addWidget(_tb_spacer(14))
        _add(QStyle.StandardPixmap.SP_ComputerIcon, "Connect", self._conn.request_connect)
        _add(QStyle.StandardPixmap.SP_DialogCancelButton, "Disconnect", self._on_disconnect)
        tb.addWidget(_tb_spacer(10))
        tb.addSeparator()
        _add(
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "Configure",
            self._on_configure,
        )
        _add(QStyle.StandardPixmap.SP_MediaPlay, "Arm", self._on_arm)
        tb.addWidget(_tb_spacer())
        tb.addSeparator()
        _add(QStyle.StandardPixmap.SP_ArrowDown, "Capture", self._on_capture_clicked)
        _add(QStyle.StandardPixmap.SP_BrowserReload, "Continuous", self._on_continuous_clicked)
        _add(QStyle.StandardPixmap.SP_MediaStop, "Stop", self._on_stop_continuous)
        self.addToolBar(tb)

    def _schedule_ui_prefs_save(self) -> None:
        self._ui_prefs_timer.start()

    def _save_collapsible_ui_prefs(self) -> None:
        st = self._window_qsettings()
        self._capture.save_collapsible_ui_prefs(st)
        self._probe.save_collapsible_ui_prefs(st)
        st.sync()

    def _user_layout_keys(self) -> list[str]:
        st = self._window_qsettings()
        st.beginGroup("userLayouts")
        keys = sorted(st.childKeys())
        st.endGroup()
        return keys

    def _refresh_user_layout_menus(self) -> None:
        if self._m_user_load is None or self._m_user_delete is None:
            return
        self._m_user_load.clear()
        self._m_user_delete.clear()
        keys = self._user_layout_keys()
        if not keys:
            na = QAction("(none)", self)
            na.setEnabled(False)
            self._m_user_load.addAction(na)
            nb = QAction("(none)", self)
            nb.setEnabled(False)
            self._m_user_delete.addAction(nb)
            return
        for key in keys:
            disp = key.replace("_", " ")
            act_load = QAction(disp, self)
            act_load.triggered.connect(
                lambda _checked=False, k=key: self._restore_user_layout(k),
            )
            self._m_user_load.addAction(act_load)
            act_del = QAction(disp, self)
            act_del.triggered.connect(
                lambda _checked=False, k=key: self._on_delete_user_layout(k),
            )
            self._m_user_delete.addAction(act_del)

    def _on_save_user_layout(self) -> None:
        name, ok = QInputDialog.getText(self, "Save layout", "Layout name:")
        if not ok or not name.strip():
            return
        key = _sanitize_user_layout_key(name)
        st = self._window_qsettings()
        st.beginGroup("userLayouts")
        st.setValue(key, self.saveState(_WINDOW_STATE_VERSION))
        st.endGroup()
        st.sync()
        self._refresh_user_layout_menus()
        _log.info("Saved user layout %r", key)

    def _restore_user_layout(self, key: str) -> None:
        st = self._window_qsettings()
        st.beginGroup("userLayouts")
        raw = st.value(key)
        st.endGroup()
        blob = _qsettings_to_qbytearray(raw)
        if blob is None:
            QMessageBox.warning(self, "User layout", f"No saved data for {key!r}.")
            return
        ok = self.restoreState(blob, _WINDOW_STATE_VERSION)
        if not ok:
            for legacy in (2, 1, 0):
                if self.restoreState(blob, legacy):
                    ok = True
                    break
        if not ok:
            QMessageBox.warning(self, "User layout", "Saved layout could not be restored.")
            return
        self._schedule_dock_reflow()
        self._schedule_persist_layout()

    def _on_delete_user_layout(self, key: str) -> None:
        r = QMessageBox.question(
            self,
            "Delete layout",
            f"Delete saved layout {key!r}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        st = self._window_qsettings()
        st.beginGroup("userLayouts")
        st.remove(key)
        st.endGroup()
        st.sync()
        self._refresh_user_layout_menus()

    def _build_menus(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        act_settings = QAction("&Settings…", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._on_open_settings)
        m_file.addAction(act_settings)
        act_cfg_dir = QAction("Open settings &folder", self)
        act_cfg_dir.triggered.connect(self._on_open_config_folder)
        m_file.addAction(act_cfg_dir)
        act_clear_log = QAction("Clear &log", self)
        act_clear_log.triggered.connect(self._log_panel.clear)
        m_file.addAction(act_clear_log)

        m_window = self.menuBar().addMenu("&Window")
        for dock in self._tool_docks:
            m_window.addAction(dock.toggleViewAction())
        m_window.addSeparator()
        act_show_all = QAction("Show &all panels", self)
        act_show_all.triggered.connect(self._show_all_tool_docks)
        m_window.addAction(act_show_all)
        m_window.addSeparator()
        m_layouts = m_window.addMenu("Layout &presets")
        act_def = QAction("&Default", self)
        act_def.setStatusTip("Restore the built-in dock layout (also forgets saved positions).")
        act_def.triggered.connect(self._layout_preset_default)
        m_layouts.addAction(act_def)
        act_min = QAction("&Minimal", self)
        act_min.setStatusTip(
            "Connection, ELA capture tab, and history; hide EIO/AXI/UART, identity, and log.",
        )
        act_min.triggered.connect(self._layout_preset_minimal)
        m_layouts.addAction(act_min)
        act_wave = QAction("&Waveform focus", self)
        act_wave.setStatusTip(
            "Maximize capture history / preview (hide workbench tabs, connection, identity, log).",
        )
        act_wave.triggered.connect(self._layout_preset_waveform_focus)
        m_layouts.addAction(act_wave)
        act_diag = QAction("&Diagnostics", self)
        act_diag.setStatusTip("Show every dock (workbench tabs, connection, identity, log).")
        act_diag.triggered.connect(self._layout_preset_diagnostics)
        m_layouts.addAction(act_diag)

        m_window.addSeparator()
        act_save_ul = QAction("Save layout &as…", self)
        act_save_ul.triggered.connect(self._on_save_user_layout)
        m_window.addAction(act_save_ul)
        self._m_user_load = m_window.addMenu("Load &user layout")
        self._m_user_delete = m_window.addMenu("Delete &user layout")
        self._refresh_user_layout_menus()

        m_help = self.menuBar().addMenu("&Help")
        act_about = QAction("&About fcapz-gui", self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

    def _show_all_tool_docks(self) -> None:
        for d in self._tool_docks:
            d.show()
            d.raise_()
        self._schedule_dock_reflow()
        self._schedule_persist_layout()

    def _layout_preset_default(self) -> None:
        for d in self._tool_docks:
            d.show()
        if not self.restoreState(self._layout_default_state, _WINDOW_STATE_VERSION):
            _log.warning("Could not restore default layout bytes.")
        self._dock_capture.raise_()
        self._dock_log.raise_()
        self._schedule_dock_reflow()
        self._schedule_persist_layout()

    def _layout_preset_minimal(self) -> None:
        self._show_all_tool_docks()
        self._dock_probe.hide()
        self._dock_eio.hide()
        self._dock_axi.hide()
        self._dock_uart.hide()
        self._dock_log.hide()
        self._dock_capture.raise_()
        self._schedule_dock_reflow()
        self._schedule_persist_layout()

    def _layout_preset_waveform_focus(self) -> None:
        self._show_all_tool_docks()
        self._dock_conn.hide()
        self._dock_probe.hide()
        for d in self._workbench_docks:
            d.hide()
        self._dock_log.hide()
        self._schedule_dock_reflow()
        self._schedule_persist_layout()

    def _layout_preset_diagnostics(self) -> None:
        self._show_all_tool_docks()
        self._dock_capture.raise_()
        self._dock_log.raise_()
        self._schedule_dock_reflow()
        self._schedule_persist_layout()

    def _on_open_settings(self) -> None:
        gui = load_gui_settings(self._config_path)
        dlg = SettingsDialog(gui, self)
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            return
        merged = dlg.merged_settings()
        save_gui_settings(merged, self._config_path)
        self._apply_viewer_choices(merged)
        self._capture.set_probe_profiles(merged.probe_profiles)
        self._capture.set_trigger_history(merged.trigger_history)

    def _on_open_config_folder(self) -> None:
        p = self._config_path.parent
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About fcapz-gui",
            "<p><b>fcapz-gui</b> — fpgacapZero desktop control panel.</p>"
            "<p>Connect to an ELA over JTAG, capture, and inspect waveforms "
            "(embedded preview or external viewers).</p>",
        )

    def _persist_trigger_snapshot(self, cfg: CaptureConfig) -> None:
        gui = load_gui_settings(self._config_path)
        append_trigger_history(gui, trigger_history_entry_from_config(cfg))
        save_gui_settings(gui, self._config_path)
        self._capture.set_trigger_history(gui.trigger_history)

    def _on_disconnect(self) -> None:
        self._stop_capture_thread()
        if self._analyzer is not None:
            try:
                self._analyzer.close()
            except OSError:
                pass
            self._analyzer = None
        self._history.set_analyzer_ref(None)
        self._clear_subsidiary_controllers()
        self._probe.clear()
        self._capture.clear_hw()
        self._conn.set_connected(False)
        self.statusBar().showMessage("Disconnected")
        _log.info("Disconnected")

    def _clear_subsidiary_controllers(self) -> None:
        self._eio = None
        self._axi = None
        self._uart = None
        self._eio_panel.set_transport(None)
        self._axi_panel.clear()
        self._axi_panel.set_transport_available(False)
        self._uart_panel.clear()
        self._uart_panel.set_transport_available(False)

    def _on_eio_attach(self) -> None:
        if self._analyzer is None:
            return
        t = self._analyzer.transport
        try:
            eio = EioController(t, chain=self._eio_panel.chain())
            eio.attach()
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "EIO attach", str(exc))
            return
        self._eio = eio
        self._eio_panel.bind_eio(t, eio)
        self.statusBar().showMessage("EIO attached")
        _log.info("EIO attached (chain=%d)", self._eio_panel.chain())

    def _on_axi_attach(self) -> None:
        if self._analyzer is None:
            return
        t = self._analyzer.transport
        try:
            axi = EjtagAxiController(t, chain=self._axi_panel.chain())
            info = axi.attach()
        except (AXIError, OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "AXI attach", str(exc))
            return
        self._axi = axi
        self._axi_panel.bind_axi(axi, info)
        self.statusBar().showMessage("AXI bridge attached")
        _log.info("AXI bridge attached (chain=%d)", self._axi_panel.chain())

    def _on_uart_attach(self) -> None:
        if self._analyzer is None:
            return
        t = self._analyzer.transport
        try:
            uart = EjtagUartController(t, chain=self._uart_panel.chain())
            info = uart.attach()
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "UART attach", str(exc))
            return
        self._uart = uart
        self._uart_panel.bind_uart(uart, info)
        self.statusBar().showMessage("UART bridge attached")
        _log.info("UART bridge attached (chain=%d)", self._uart_panel.chain())

    def _on_configure(self) -> None:
        if self._analyzer is None:
            return
        try:
            cfg = self._capture.build_capture_config()
            self._analyzer.configure(cfg)
        except ValueError as exc:
            _log.warning("Configure rejected: %s", exc)
            QMessageBox.warning(self, "Configure", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            _log.warning("Configure failed: %s", exc)
            QMessageBox.warning(self, "Configure", str(exc))
            return
        self.statusBar().showMessage("Configured")
        _log.info("ELA configured")

    def _on_arm(self) -> None:
        if self._analyzer is None:
            return
        try:
            self._analyzer.arm()
        except Exception as exc:  # noqa: BLE001
            _log.warning("Arm failed: %s", exc)
            QMessageBox.warning(self, "Arm", str(exc))
            return
        self.statusBar().showMessage("Armed")
        _log.info("ELA armed")

    def _on_capture_clicked(self) -> None:
        if self._analyzer is None or self._capture_running():
            return
        try:
            cfg = self._capture.build_capture_config()
            timeout = self._capture.timeout_seconds()
        except ValueError as exc:
            _log.warning("Capture: invalid config: %s", exc)
            QMessageBox.warning(self, "Capture", str(exc))
            return
        _log.info("Starting single capture (timeout=%.1fs)", timeout)
        self._spawn_capture_thread(cfg, timeout, continuous=False)

    def _on_continuous_clicked(self) -> None:
        if self._analyzer is None or self._capture_running():
            return
        try:
            cfg = self._capture.build_capture_config()
            timeout = self._capture.timeout_seconds()
        except ValueError as exc:
            _log.warning("Continuous capture: invalid config: %s", exc)
            QMessageBox.warning(self, "Continuous capture", str(exc))
            return
        _log.info("Starting continuous capture (timeout=%.1fs per run)", timeout)
        self._spawn_capture_thread(cfg, timeout, continuous=True)

    def _on_stop_continuous(self) -> None:
        if self._cap_worker is not None:
            self._cap_worker.cancel_continuous()

    def _spawn_capture_thread(
        self,
        cfg: CaptureConfig,
        timeout: float,
        *,
        continuous: bool,
    ) -> None:
        assert self._analyzer is not None
        self._continuous_mode = continuous
        self._cap_thread = QThread()
        self._cap_worker = CaptureWorker(self._analyzer)
        self._cap_worker.moveToThread(self._cap_thread)
        if continuous:
            self._cap_thread.started.connect(
                partial(self._cap_worker.run_continuous, cfg, timeout),
            )
        else:
            self._cap_thread.started.connect(
                partial(self._cap_worker.run_single, cfg, timeout),
            )
        self._cap_worker.finished.connect(self._on_worker_finished)
        self._cap_worker.finished.connect(self._cap_thread.quit)
        self._cap_worker.failed.connect(self._on_worker_failed)
        self._cap_worker.failed.connect(self._cap_thread.quit)
        self._cap_worker.progress.connect(self._on_worker_progress)
        self._cap_thread.finished.connect(self._on_thread_finished)
        self._capture.set_busy(True, continuous=continuous)
        self._cap_thread.start()

    def _on_worker_progress(self, result: CaptureResult) -> None:
        if self._analyzer is not None:
            self._history.add_capture(self._analyzer, result)

    def _on_worker_finished(self, result: CaptureResult | None) -> None:
        was_cont = self._continuous_mode
        self._continuous_mode = False
        if (
            not was_cont
            and result is not None
            and self._analyzer is not None
        ):
            _log.info(
                "Capture done: %d samples overflow=%s",
                len(result.samples),
                result.overflow,
            )
            self._history.add_capture(self._analyzer, result)
            self._persist_trigger_snapshot(result.config)
        elif was_cont and result is None:
            _log.info("Continuous capture stopped")

    def _on_worker_failed(self, message: str) -> None:
        _log.error("Capture worker failed: %s", message)
        QMessageBox.warning(self, "Capture", message)
        self._continuous_mode = False

    def _on_thread_finished(self) -> None:
        w, self._cap_worker = self._cap_worker, None
        t, self._cap_thread = self._cap_thread, None
        if w is not None:
            w.deleteLater()
        if t is not None:
            t.deleteLater()
        self._capture.set_busy(False, continuous=False)

    def _stop_capture_thread(self) -> None:
        if self._cap_worker is not None:
            self._cap_worker.cancel_continuous()
        if self._cap_thread is not None and self._cap_thread.isRunning():
            self._cap_thread.quit()
            self._cap_thread.wait(8000)
        QApplication.processEvents()
        self._on_thread_finished()
        self._continuous_mode = False

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._reflow_timer.stop()
        self._persist_layout_timer.stop()
        self._ui_prefs_timer.stop()
        self._save_collapsible_ui_prefs()
        if self._persist_window_layout:
            self._save_window_layout_to_settings()
        self._log_panel.shutdown()
        if self._gui_log_handler is not None:
            logging.getLogger("fcapz").removeHandler(self._gui_log_handler)
            self._gui_log_handler = None
        self._join_connect_thread()
        self._stop_capture_thread()
        if self._analyzer is not None:
            try:
                self._analyzer.close()
            except OSError:
                pass
            self._analyzer = None
        self._history.cleanup_temp_dirs()
        self._clear_subsidiary_controllers()
        self._probe.clear()
        self._capture.clear_hw()
        super().closeEvent(event)


def _request_quit(app: QApplication) -> None:
    """Thread-safe: console handlers may run off the Qt GUI thread."""
    QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)


def _install_windows_console_ctrl_handler(app: QApplication) -> Any | None:
    """
    Windows: Ctrl+C is delivered via SetConsoleCtrlHandler, not reliably as SIGINT
    once a GUI message loop is active.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    kernel32 = ctypes.windll.kernel32
    HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    CTRL_C_EVENT = 0
    CTRL_BREAK_EVENT = 1

    def _handler(ctrl_type: int) -> bool:
        if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
            _request_quit(app)
            return True
        return False

    callback = HandlerRoutine(_handler)
    if kernel32.SetConsoleCtrlHandler(callback, True):
        return callback
    return None


def _install_ctrl_c_quit(app: QApplication) -> tuple[QTimer, Any | None]:
    """
    Quit on Ctrl+C from a terminal.

    - Unix: SIGINT + a short wake timer so Python can run the handler while Qt
      owns the event loop.
    - Windows: add a console control handler (SIGINT alone is often unreliable).
    """

    def _on_sigint(_signum: int, _frame: object | None) -> None:
        _request_quit(app)

    signal.signal(signal.SIGINT, _on_sigint)
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(50)
    win_cb = _install_windows_console_ctrl_handler(app)
    return wake, win_cb


def run_app(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough,
    )
    app = QApplication(args)
    app.setApplicationName("fcapz-gui")
    app.setOrganizationName("fpgacapzero")
    _wake, _win_cb = _install_ctrl_c_quit(app)
    w = MainWindow()
    w.show()
    try:
        return app.exec()
    finally:
        _wake.stop()
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        if _win_cb is not None and sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetConsoleCtrlHandler(_win_cb, False)
