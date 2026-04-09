# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

try:
    import PySide6  # noqa: F401
    _HAVE_PYSIDE = True
except ImportError:
    _HAVE_PYSIDE = False

if _HAVE_PYSIDE:
    from PySide6.QtWidgets import QApplication

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
        self.assertEqual(len(cfg.probes), 1)
        self.assertEqual(cfg.probes[0].name, "a")


if __name__ == "__main__":
    unittest.main()
