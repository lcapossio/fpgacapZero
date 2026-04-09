# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import signal
import sys
from functools import partial
from typing import Any

from PySide6.QtCore import QMetaObject, QThread, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
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
from .settings_dialog import SettingsDialog
from .transport_from_settings import transport_from_connection
from .viewer_registry import viewers_for_settings
from .worker import CaptureWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("fcapz-gui")
        self.resize(1000, 820)

        self._config_path = default_gui_config_path()
        self._analyzer: Analyzer | None = None
        self._cap_thread: QThread | None = None
        self._cap_worker: CaptureWorker | None = None
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

        top = QWidget()
        hl = QHBoxLayout(top)
        hl.addWidget(self._conn, stretch=2)
        hl.addWidget(self._probe, stretch=3)

        ela_tab = QWidget()
        ela_layout = QHBoxLayout(ela_tab)
        ela_layout.addWidget(self._capture, stretch=3)
        ela_layout.addWidget(self._history, stretch=4)

        tabs = QTabWidget()
        tabs.addTab(ela_tab, "ELA")
        tabs.addTab(self._eio_panel, "EIO")
        tabs.addTab(self._axi_panel, "AXI")
        tabs.addTab(self._uart_panel, "UART")

        central = QWidget()
        vl = QVBoxLayout(central)
        vl.addWidget(top, stretch=2)
        vl.addWidget(tabs, stretch=4)
        self.setCentralWidget(central)

        self.statusBar().showMessage("Ready")

        self._build_menus()

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
        conn = self._conn.connection_settings()
        self.statusBar().showMessage("Connecting…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            transport = transport_from_connection(conn)
            analyzer = Analyzer(transport)
            analyzer.connect()
            info = analyzer.probe()
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.statusBar().showMessage("Connect failed")
            QMessageBox.critical(self, "Connection failed", str(exc))
            return

        QApplication.restoreOverrideCursor()
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

    def _build_menus(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        act_settings = QAction("&Settings…", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._on_open_settings)
        m_file.addAction(act_settings)
        act_cfg_dir = QAction("Open settings &folder", self)
        act_cfg_dir.triggered.connect(self._on_open_config_folder)
        m_file.addAction(act_cfg_dir)
        m_help = self.menuBar().addMenu("&Help")
        act_about = QAction("&About fcapz-gui", self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

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

    def _on_configure(self) -> None:
        if self._analyzer is None:
            return
        try:
            cfg = self._capture.build_capture_config()
            self._analyzer.configure(cfg)
        except ValueError as exc:
            QMessageBox.warning(self, "Configure", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Configure", str(exc))
            return
        self.statusBar().showMessage("Configured")

    def _on_arm(self) -> None:
        if self._analyzer is None:
            return
        try:
            self._analyzer.arm()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Arm", str(exc))
            return
        self.statusBar().showMessage("Armed")

    def _on_capture_clicked(self) -> None:
        if self._analyzer is None or self._capture_running():
            return
        try:
            cfg = self._capture.build_capture_config()
            timeout = self._capture.timeout_seconds()
        except ValueError as exc:
            QMessageBox.warning(self, "Capture", str(exc))
            return
        self._spawn_capture_thread(cfg, timeout, continuous=False)

    def _on_continuous_clicked(self) -> None:
        if self._analyzer is None or self._capture_running():
            return
        try:
            cfg = self._capture.build_capture_config()
            timeout = self._capture.timeout_seconds()
        except ValueError as exc:
            QMessageBox.warning(self, "Continuous capture", str(exc))
            return
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
            self._history.add_capture(self._analyzer, result)
            self._persist_trigger_snapshot(result.config)

    def _on_worker_failed(self, message: str) -> None:
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
