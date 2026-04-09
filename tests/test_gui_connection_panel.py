# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

import pytest

pytestmark = pytest.mark.gui

try:
    import PySide6  # noqa: F401
    _HAVE_PYSIDE = True
except ImportError:
    _HAVE_PYSIDE = False

if _HAVE_PYSIDE:
    from PySide6.QtWidgets import QApplication

    from fcapz.gui.connection_panel import ConnectionPanel
    from fcapz.gui.settings import ConnectionSettings


@unittest.skipUnless(_HAVE_PYSIDE, "PySide6 not installed")
class TestConnectionPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_roundtrip_connection_settings(self) -> None:
        p = ConnectionPanel()
        src = ConnectionSettings(
            backend="hw_server",
            host="1.2.3.4",
            port=3121,
            tap="xc7.tap",
            program=r"C:\demo\design.bit",
            ir_table="ultrascale",
            connect_timeout_sec=45.0,
            hw_ready_timeout_sec=120.0,
        )
        p.load_from_settings(src)
        out = p.connection_settings()
        self.assertEqual(out.backend, src.backend)
        self.assertEqual(out.host, src.host)
        self.assertEqual(out.port, src.port)
        self.assertEqual(out.tap, src.tap)
        self.assertEqual(out.program, src.program)
        self.assertEqual(out.ir_table, src.ir_table)
        self.assertEqual(out.connect_timeout_sec, 45.0)
        self.assertEqual(out.hw_ready_timeout_sec, 120.0)


if __name__ == "__main__":
    unittest.main()
