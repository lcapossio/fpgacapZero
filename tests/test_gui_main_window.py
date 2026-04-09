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
from PySide6.QtWidgets import QApplication, QPushButton

from fcapz.analyzer import CaptureResult
from fcapz.gui.app_window import MainWindow
from fcapz.gui.settings import GuiSettings


def _button_with_text(root: Any, text: str) -> QPushButton:
    for b in root.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(f"no QPushButton with text {text!r}")


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
            "fcapz.gui.app_window.transport_from_connection",
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
        "has_timestamp": False,
        "timestamp_width": 32,
        "num_segments": 4,
        "probe_mux_w": 0,
    }
    mock_an.transport = mock_transport
    last_cfg: dict = {}

    def _configure(cfg: object) -> None:
        last_cfg["cfg"] = cfg

    def _capture(_timeout: float) -> CaptureResult:
        return CaptureResult(config=last_cfg["cfg"], samples=[0xAA, 0x55], overflow=False)

    mock_an.configure.side_effect = _configure
    mock_an.capture.side_effect = _capture

    ex.enter_context(patch("fcapz.gui.app_window.Analyzer", return_value=mock_an))
    return mock_an


@pytest.mark.gui
def test_connect_and_disconnect_mocked(qtbot: Any, tmp_path: Path) -> None:
    gui_path = tmp_path / "gui.toml"
    with ExitStack() as ex:
        _enter_successful_connect_mocks(ex, gui_path)
        ex.enter_context(patch("fcapz.gui.app_window.QMessageBox.critical"))

        w = MainWindow()
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

        w = MainWindow()
        qtbot.addWidget(w)

        qtbot.mouseClick(_button_with_text(w, "Connect"), Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: w._analyzer is not None, timeout=5000)

        before = w._history._table.rowCount()
        qtbot.mouseClick(_button_with_text(w, "Capture"), Qt.MouseButton.LeftButton)

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
                "fcapz.gui.app_window.transport_from_connection",
                side_effect=OSError("no cable"),
            ),
        )
        ex.enter_context(patch("fcapz.gui.app_window.QMessageBox.critical"))

        w = MainWindow()
        qtbot.addWidget(w)
        qtbot.mouseClick(_button_with_text(w, "Connect"), Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        assert w._analyzer is None
