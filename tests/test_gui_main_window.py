# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Programmatic GUI integration tests for :class:`fcapz.gui.app_window.MainWindow`.

Uses ``pytest-qt``'s ``qtbot`` (``QTest`` under the hood) plus mocked JTAG /
:class:`~fcapz.analyzer.Analyzer`. Marked ``@pytest.mark.gui`` (``pytest -m gui``).

Mark real on-target tests with ``@pytest.mark.hw``; default CI uses ``-m "not hw"``.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QPushButton, QToolBar, QToolButton

from fcapz.analyzer import CaptureResult
from fcapz.gui.app_window import MainWindow
from fcapz.gui.settings import GuiSettings


def _button_with_text(root: Any, text: str) -> QPushButton:
    for b in root.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(f"no QPushButton with text {text!r}")


def _toolbar_action(tb: QToolBar, text: str) -> QAction:
    for a in tb.actions():
        if a.text() == text:
            return a
    raise AssertionError(f"no toolbar QAction with text {text!r}")


def _enter_successful_connect_mocks(ex: ExitStack, gui_path: Path) -> MagicMock:
    ex.enter_context(
        patch("fcapz.gui.app_window.default_gui_config_path", return_value=gui_path),
    )
    ex.enter_context(
        patch("fcapz.gui.app_window.load_gui_settings", return_value=GuiSettings()),
    )
    ex.enter_context(patch("fcapz.gui.app_window.save_gui_settings"))

    mock_transport = MagicMock(name="transport")
    ex.enter_context(
        patch(
            "fcapz.gui.worker.transport_from_connection",
            return_value=mock_transport,
        ),
    )

    mock_an = MagicMock(name="analyzer")
    mock_an.probe.return_value = {
        "version_major": 0,
        "version_minor": 3,
        "core_id": 0x4C41,
        "sample_width": 8,
        "depth": 1024,
        "num_channels": 1,
        "has_decimation": True,
        "has_ext_trigger": True,
        "has_storage_qualification": True,
        "has_timestamp": False,
        "timestamp_width": 32,
        "num_segments": 4,
        "probe_mux_w": 0,
        "trig_stages": 4,
    }
    mock_an.transport = mock_transport
    last_cfg: dict = {}

    def _configure(cfg: object) -> None:
        last_cfg["cfg"] = cfg

    def _capture(_timeout: float) -> CaptureResult:
        return CaptureResult(config=last_cfg["cfg"], samples=[0xAA, 0x55], overflow=False)

    mock_an.configure.side_effect = _configure
    mock_an.capture.side_effect = _capture
    mock_an.immediate_variant.side_effect = lambda c: c

    ex.enter_context(patch("fcapz.gui.worker.Analyzer", return_value=mock_an))
    return mock_an


@pytest.mark.gui
def test_main_toolbar_toolbuttons_visible(qtbot: Any, tmp_path: Path) -> None:
    """Regression: main actions toolbar must show labeled buttons with icons (see PR feedback)."""
    gui_path = tmp_path / "gui.toml"
    with ExitStack() as ex:
        _enter_successful_connect_mocks(ex, gui_path)
        ex.enter_context(patch("fcapz.gui.app_window.QMessageBox.critical"))
        w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
        qtbot.addWidget(w)
        # Wide enough that Qt does not move actions into the toolbar extension (») menu.
        w.resize(1920, 800)
        w.show()
        qtbot.waitExposed(w)
        tb = w.findChild(QToolBar, "mainToolbar")
        assert tb is not None
        assert tb.isVisible()
        assert tb.height() >= 20
        want = [
            "Connect",
            "Disconnect",
            "Configure",
            "Arm",
            "Trigger Immediate",
            "Stop",
        ]
        assert [a.text() for a in tb.actions() if a.text()] == want
        got: list[str] = []
        for b in tb.findChildren(QToolButton):
            t = b.text()
            if not t:
                continue
            assert b.isVisible(), t
            assert b.width() >= 40, t
            assert b.height() >= 18, t
            assert not b.icon().pixmap(24, 24).isNull(), t
            got.append(t)
        assert got == want


@pytest.mark.gui
def test_main_toolbar_actions_grayed_when_disconnected(qtbot: Any, tmp_path: Path) -> None:
    """Disabled QActions gray out tool buttons; only Connect is usable before connect."""
    gui_path = tmp_path / "gui.toml"
    with ExitStack() as ex:
        _enter_successful_connect_mocks(ex, gui_path)
        ex.enter_context(patch("fcapz.gui.app_window.QMessageBox.critical"))
        w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
        qtbot.addWidget(w)
        w.show()
        qtbot.waitExposed(w)
        tb = w.findChild(QToolBar, "mainToolbar")
        assert tb is not None
        assert _toolbar_action(tb, "Connect").isEnabled()
        for label in (
            "Disconnect",
            "Configure",
            "Arm",
            "Trigger Immediate",
            "Stop",
        ):
            assert not _toolbar_action(tb, label).isEnabled(), label

        qtbot.mouseClick(_button_with_text(w, "Connect"), Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: w._analyzer is not None, timeout=5000)

        assert not _toolbar_action(tb, "Connect").isEnabled()
        assert _toolbar_action(tb, "Disconnect").isEnabled()
        for label in ("Configure", "Arm", "Trigger Immediate"):
            assert _toolbar_action(tb, label).isEnabled(), label
        assert not _toolbar_action(tb, "Stop").isEnabled()


@pytest.mark.gui
def test_connect_and_disconnect_mocked(qtbot: Any, tmp_path: Path) -> None:
    gui_path = tmp_path / "gui.toml"
    with ExitStack() as ex:
        _enter_successful_connect_mocks(ex, gui_path)
        ex.enter_context(patch("fcapz.gui.app_window.QMessageBox.critical"))

        w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
        qtbot.addWidget(w)

        qtbot.mouseClick(_button_with_text(w, "Connect"), Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: w._analyzer is not None, timeout=5000)

        qtbot.mouseClick(_button_with_text(w, "Disconnect"), Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        assert w._analyzer is None


@pytest.mark.gui
def test_single_capture_updates_history_mocked(qtbot: Any, tmp_path: Path) -> None:
    gui_path = tmp_path / "gui.toml"
    with ExitStack() as ex:
        _enter_successful_connect_mocks(ex, gui_path)
        for meth in ("critical", "warning", "about"):
            ex.enter_context(patch(f"fcapz.gui.app_window.QMessageBox.{meth}"))

        w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
        qtbot.addWidget(w)

        qtbot.mouseClick(_button_with_text(w, "Connect"), Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: w._analyzer is not None, timeout=5000)

        before = w._history._table.rowCount()
        qtbot.mouseClick(_button_with_text(w, "Trigger Immediate"), Qt.MouseButton.LeftButton)

        def _done() -> bool:
            return w._history._table.rowCount() > before and not w._capture_running()

        qtbot.waitUntil(_done, timeout=8000)
        assert w._history._table.rowCount() == before + 1


@pytest.mark.gui
def test_connect_failure_does_not_leave_analyzer(qtbot: Any, tmp_path: Path) -> None:
    gui_path = tmp_path / "gui.toml"
    with ExitStack() as ex:
        ex.enter_context(
            patch("fcapz.gui.app_window.default_gui_config_path", return_value=gui_path),
        )
        ex.enter_context(
            patch("fcapz.gui.app_window.load_gui_settings", return_value=GuiSettings()),
        )
        ex.enter_context(patch("fcapz.gui.app_window.save_gui_settings"))
        ex.enter_context(
            patch(
                "fcapz.gui.worker.transport_from_connection",
                side_effect=OSError("no cable"),
            ),
        )
        ex.enter_context(patch("fcapz.gui.app_window.QMessageBox.critical"))

        w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
        qtbot.addWidget(w)
        qtbot.mouseClick(_button_with_text(w, "Connect"), Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: w._connect_thread is None, timeout=5000)
        assert w._analyzer is None
