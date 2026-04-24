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
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QLineEdit,
        QSpinBox,
        QTableWidget,
    )

    from fcapz.gui.capture_panel import CapturePanel


@unittest.skipUnless(_HAVE_PYSIDE, "PySide6 not installed")
class TestCapturePanelApplyHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_apply_trigger_history_then_build_config(self) -> None:
        p = CapturePanel()
        p.set_hw_probe_info({"sample_width": 8, "depth": 1024, "num_channels": 1})
        p.apply_trigger_history_entry(
            {
                "pretrigger": 3,
                "posttrigger": 9,
                "trigger_mode": "edge_detect",
                "trigger_value": 5,
                "trigger_mask": 15,
                "sample_clock_hz": 80_000_000,
                "channel": 0,
                "decimation": 0,
                "probe_sel": 1,
                "ext_trigger_mode": "or",
                "stor_qual_mode": 0,
                "stor_qual_value": 0,
                "stor_qual_mask": 0,
                "trigger_holdoff": 7,
                "trigger_delay": 2,
                "probes": "a:2:0",
            },
        )
        cfg = p.build_capture_config()
        self.assertEqual(cfg.pretrigger, 3)
        self.assertEqual(cfg.posttrigger, 9)
        self.assertEqual(cfg.trigger.mode, "edge_detect")
        self.assertEqual(cfg.trigger.value, 5)
        self.assertEqual(cfg.trigger.mask, 15)
        self.assertEqual(cfg.sample_clock_hz, 80_000_000)
        self.assertEqual(cfg.ext_trigger_mode, 1)
        self.assertFalse(cfg.startup_arm)
        self.assertEqual(cfg.trigger_holdoff, 7)
        self.assertEqual(len(cfg.probes), 1)
        self.assertEqual(cfg.probes[0].name, "a")

    def test_build_capture_config_trigger_value_radix_hex(self) -> None:
        p = CapturePanel()
        p.set_hw_probe_info({"sample_width": 8, "depth": 1024, "num_channels": 1})
        trig_radix = p.findChild(QComboBox, "fcapz_capture_trig_val_radix")
        self.assertIsNotNone(trig_radix)
        ri = trig_radix.findData(16)
        self.assertGreaterEqual(ri, 0)
        trig_radix.setCurrentIndex(ri)
        tv = p.findChild(QLineEdit, "fcapz_capture_trig_val")
        self.assertIsNotNone(tv)
        tv.setText("ff")
        cfg = p.build_capture_config()
        self.assertEqual(cfg.trigger.value, 255)

    def test_hw_probe_disables_unsupported_advanced_controls(self) -> None:
        p = CapturePanel()
        p.set_hw_probe_info(
            {
                "sample_width": 8,
                "depth": 1024,
                "num_channels": 1,
                "has_decimation": False,
                "has_ext_trigger": False,
                "has_storage_qualification": False,
                "probe_mux_w": 8,
                "trig_stages": 0,
            },
        )
        decim = p.findChild(QSpinBox, "fcapz_capture_decim")
        self.assertIsNotNone(decim)
        self.assertFalse(decim.isEnabled())
        ext_trig = p.findChild(QComboBox, "fcapz_capture_ext_trig")
        self.assertIsNotNone(ext_trig)
        self.assertFalse(ext_trig.isEnabled())
        self.assertEqual(ext_trig.currentText(), "disabled")
        stor = p.findChild(QSpinBox, "fcapz_capture_stor_mode")
        self.assertIsNotNone(stor)
        self.assertFalse(stor.isEnabled())

    def test_build_capture_config_sequencer_disabled_no_sequence(self) -> None:
        p = CapturePanel()
        p.set_hw_probe_info(
            {
                "sample_width": 8,
                "depth": 1024,
                "num_channels": 1,
                "trig_stages": 4,
            },
        )
        cfg = p.build_capture_config()
        self.assertIsNone(cfg.sequence)

    def test_build_capture_config_with_sequencer(self) -> None:
        p = CapturePanel()
        p.set_hw_probe_info(
            {
                "sample_width": 8,
                "depth": 1024,
                "num_channels": 1,
                "trig_stages": 2,
            },
        )
        enable = p.findChild(QCheckBox, "fcapz_capture_seq_enable")
        self.assertIsNotNone(enable)
        enable.setChecked(True)
        table = p.findChild(QTableWidget, "fcapz_capture_seq_table")
        self.assertIsNotNone(table)
        self.assertEqual(table.rowCount(), 1)
        va = table.cellWidget(0, 6)
        self.assertIsInstance(va, QLineEdit)
        va.setText("0x10")
        cfg = p.build_capture_config()
        self.assertIsNotNone(cfg.sequence)
        self.assertEqual(len(cfg.sequence), 1)
        self.assertEqual(cfg.sequence[0].value_a, 0x10)

    def test_build_capture_config_rejects_unavailable_relational_mode(self) -> None:
        p = CapturePanel()
        p.set_hw_probe_info(
            {
                "sample_width": 8,
                "depth": 1024,
                "num_channels": 1,
                "trig_stages": 2,
                "compare_caps": 0x1C3,
            },
        )
        enable = p.findChild(QCheckBox, "fcapz_capture_seq_enable")
        self.assertIsNotNone(enable)
        enable.setChecked(True)
        table = p.findChild(QTableWidget, "fcapz_capture_seq_table")
        self.assertIsNotNone(table)
        cmp_a = table.cellWidget(0, 0)
        self.assertIsInstance(cmp_a, QSpinBox)
        cmp_a.setValue(3)
        with self.assertRaisesRegex(ValueError, "REL_COMPARE=1"):
            p.build_capture_config()

    def test_apply_trigger_history_restores_sequence(self) -> None:
        p = CapturePanel()
        p.set_hw_probe_info(
            {
                "sample_width": 8,
                "depth": 1024,
                "num_channels": 1,
                "trig_stages": 2,
            },
        )
        p.apply_trigger_history_entry(
            {
                "pretrigger": 1,
                "posttrigger": 2,
                "trigger_mode": "value_match",
                "trigger_value": 0,
                "trigger_mask": 255,
                "sample_clock_hz": 100_000_000,
                "channel": 0,
                "decimation": 0,
                "probe_sel": 0,
                "ext_trigger_mode": "disabled",
                "stor_qual_mode": 0,
                "stor_qual_value": 0,
                "stor_qual_mask": 0,
                "trigger_holdoff": 0,
                "trigger_delay": 0,
                "probes": "",
                "trigger_sequence": [
                    {
                        "cmp_a": 2,
                        "cmp_b": 0,
                        "combine": 0,
                        "next_state": 0,
                        "is_final": True,
                        "count": 5,
                        "value_a": 3,
                        "mask_a": 0xF0,
                        "value_b": 0,
                        "mask_b": 0xFFFFFFFF,
                    },
                ],
            },
        )
        cfg = p.build_capture_config()
        self.assertIsNotNone(cfg.sequence)
        self.assertEqual(cfg.sequence[0].cmp_mode_a, 2)
        self.assertEqual(cfg.sequence[0].count_target, 5)
        self.assertTrue(cfg.sequence[0].is_final)


if __name__ == "__main__":
    unittest.main()
