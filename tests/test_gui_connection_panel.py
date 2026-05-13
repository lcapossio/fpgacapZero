# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest
from unittest.mock import patch

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
            program_on_connect=False,
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
        self.assertIsNone(out.hardware)
        self.assertIsNone(out.quartus_stp)
        self.assertEqual(out.program, src.program)
        self.assertFalse(out.program_on_connect)
        self.assertEqual(out.ir_table, src.ir_table)
        self.assertEqual(out.connect_timeout_sec, 45.0)
        self.assertEqual(out.hw_ready_timeout_sec, 120.0)

    def test_scan_finish_populates_target_dropdown(self) -> None:
        p = ConnectionPanel()
        p.load_from_settings(ConnectionSettings(tap="custom.tap"))

        p._on_scan_targets_finished(["xc7a100t", "xck26"])

        self.assertEqual(p.connection_settings().tap, "custom.tap")
        items = [p._tap.itemText(i) for i in range(p._tap.count())]
        self.assertEqual(items, ["custom.tap", "xc7a100t", "xck26"])
        self.assertIn("2 target(s) found", p._status.text())

    def test_target_dropdown_accepts_custom_text(self) -> None:
        p = ConnectionPanel()

        p._tap.setEditText("my-custom-tap")

        self.assertEqual(p.connection_settings().tap, "my-custom-tap")

    def test_usb_blaster_roundtrip_connection_settings(self) -> None:
        p = ConnectionPanel()
        src = ConnectionSettings(
            backend="usb_blaster",
            tap="auto",
            hardware="DE25-Nano [USB-1]",
            quartus_stp=r"C:\altera_lite\25.1std\quartus\bin64\quartus_stp.exe",
            connect_timeout_sec=37.0,
        )

        p.load_from_settings(src)
        out = p.connection_settings()

        self.assertEqual(out.backend, "usb_blaster")
        self.assertEqual(out.tap, "auto")
        self.assertEqual(out.hardware, "DE25-Nano [USB-1]")
        self.assertEqual(
            out.quartus_stp,
            r"C:\altera_lite\25.1std\quartus\bin64\quartus_stp.exe",
        )
        self.assertEqual(out.connect_timeout_sec, 37.0)
        self.assertFalse(p._host.isEnabled())
        self.assertFalse(p._port.isEnabled())
        self.assertFalse(p._ir.isEnabled())
        self.assertTrue(p._hardware.isEnabled())

    def test_usb_blaster_rewrites_legacy_xilinx_tap_to_auto(self) -> None:
        p = ConnectionPanel()

        p.load_from_settings(ConnectionSettings(backend="usb_blaster", tap="xc7a100t"))

        self.assertEqual(p.connection_settings().tap, "auto")

    @patch("fcapz.gui.connection_panel.QMessageBox.information")
    def test_scan_finish_reports_empty_targets(self, info_box) -> None:
        p = ConnectionPanel()

        p._on_scan_targets_finished([])

        self.assertIn("no JTAG targets", p._status.text())
        info_box.assert_called_once()

    @patch("fcapz.gui.connection_panel.QMessageBox.warning")
    def test_scan_failure_updates_status(self, warning_box) -> None:
        p = ConnectionPanel()

        p._on_scan_targets_failed("xsdb not found")

        self.assertEqual(p._status.text(), "Scan failed: xsdb not found")
        warning_box.assert_called_once()


if __name__ == "__main__":
    unittest.main()
