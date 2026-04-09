# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fcapz.analyzer import CaptureConfig, CaptureResult, ProbeSpec, TriggerConfig
from fcapz.gui.gtkw_writer import write_gtkw_for_capture


class TestGtkwWriter(unittest.TestCase):
    def test_no_probes_lists_sample_bus(self) -> None:
        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=1,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=4,
            probes=[],
        )
        result = CaptureResult(config=cfg, samples=[0, 1, 2])
        with tempfile.TemporaryDirectory() as td:
            vcd = Path(td) / "c.vcd"
            gtkw = Path(td) / "c.gtkw"
            vcd.write_text("x", encoding="utf-8")
            write_gtkw_for_capture(result, vcd, gtkw)
            text = gtkw.read_text(encoding="utf-8")
            self.assertIn("[dumpfile]", text)
            self.assertIn("logic.sample[7:0]", text)

    def test_probes_and_timestamp(self) -> None:
        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=1,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=4,
            probes=[ProbeSpec("a", width=2, lsb=0), ProbeSpec("b", width=4, lsb=4)],
        )
        result = CaptureResult(
            config=cfg,
            samples=[0],
            timestamps=[15],
        )
        with tempfile.TemporaryDirectory() as td:
            vcd = Path(td) / "d.vcd"
            gtkw = Path(td) / "d.gtkw"
            vcd.write_text("x", encoding="utf-8")
            write_gtkw_for_capture(result, vcd, gtkw, timestamp_width=8)
            text = gtkw.read_text(encoding="utf-8")
            self.assertIn("logic.a[1:0]", text)
            self.assertIn("logic.b[7:4]", text)
            self.assertIn("logic.timestamp[7:0]", text)


if __name__ == "__main__":
    unittest.main()
