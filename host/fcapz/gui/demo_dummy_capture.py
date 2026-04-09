# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch fcapz-gui against **mock hardware** (no JTAG).

Patches the connect worker so **Connect** completes like a real ELA session. The
window opens and immediately starts a mock connect; use **Capture** / **Arm**
as usual. Your normal ``gui.toml`` (viewers, paths) is still loaded.

Run with the package on ``PYTHONPATH`` or an editable install::

    python -m fcapz.gui.demo_dummy_capture

Requires PySide6 (``pip install 'fpgacapzero[gui]'``).
"""

from __future__ import annotations

import sys
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

from ..analyzer import CaptureResult


def _probe_info() -> dict[str, Any]:
    return {
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
        "trig_stages": 4,
    }


def _install_demo_hw_mocks() -> tuple[ExitStack, MagicMock]:
    """
    Keep patches alive until :meth:`ExitStack.close` (call from ``aboutToQuit``).
    """
    ex = ExitStack()
    mock_transport = MagicMock(name="transport")

    ex.enter_context(
        patch(
            "fcapz.gui.worker.transport_from_connection",
            return_value=mock_transport,
        ),
    )

    mock_an = MagicMock(name="analyzer")
    mock_an.probe.return_value = _probe_info()
    mock_an.transport = mock_transport
    mock_an.connect = MagicMock(return_value=None)
    mock_an.close = MagicMock(return_value=None)
    mock_an.arm = MagicMock(return_value=None)
    last_cfg: dict[str, Any] = {}

    def _configure(cfg: object) -> None:
        last_cfg["cfg"] = cfg

    def _capture(_timeout: float) -> CaptureResult:
        cfg = last_cfg["cfg"]
        return CaptureResult(
            config=cfg,
            samples=[0xAA, 0x55, 0x33, 0xCC] * 8,
            overflow=False,
        )

    mock_an.configure.side_effect = _configure
    mock_an.capture.side_effect = _capture

    ex.enter_context(patch("fcapz.gui.worker.Analyzer", return_value=mock_an))
    return ex, mock_an


def main(_argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            "demo_dummy_capture needs PySide6 "
            "(install: pip install 'fpgacapzero[gui]')",
            file=sys.stderr,
        )
        return 1

    ex, _mock_an = _install_demo_hw_mocks()

    app = QApplication.instance() or QApplication(sys.argv)
    app.aboutToQuit.connect(ex.close)

    from .app_window import MainWindow

    w = MainWindow(restore_saved_layout=False, persist_window_layout=False)
    w.setWindowTitle("fcapz-gui (demo — mock hardware)")

    w.show()
    # Defer so ConnectionPanel and threads wire up before connect runs.
    QTimer.singleShot(0, w._conn.request_connect)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
