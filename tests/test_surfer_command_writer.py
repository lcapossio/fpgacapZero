# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest
from fcapz.analyzer import CaptureConfig, CaptureResult, ProbeSpec, TriggerConfig
from fcapz.gui.surfer_command_writer import write_surfer_command_file_for_capture

pytestmark = pytest.mark.gui


class TestSurferCommandWriter(unittest.TestCase):
    def test_probe_list_and_timestamp(self) -> None:
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=1,
            trigger=TriggerConfig("value_match", 0, 0xFF),
            sample_width=8,
            depth=8,
            probes=[ProbeSpec("lo", 4, 0)],
        )
        r = CaptureResult(config=cfg, samples=[1], timestamps=[10])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.surfer.txt"
            write_surfer_command_file_for_capture(r, p)
            text = p.read_text(encoding="utf-8")
        self.assertIn("module_add logic", text)
        self.assertIn("add_variables", text)
        self.assertIn("logic.lo", text)
        self.assertIn("logic.timestamp", text)
        # VCD # times are zero-based per capture when timestamps exist.
        self.assertIn("marker_set fcapz_trigger 0", text)
        self.assertIn("item_set_color blue", text)
        self.assertIn("goto_marker fcapz_trigger", text)
        self.assertLess(
            text.index("marker_set"),
            text.index("item_set_color"),
        )
        self.assertLess(text.index("item_set_color"), text.index("goto_marker"))

    def test_default_sample_bus(self) -> None:
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=1,
            trigger=TriggerConfig("value_match", 0, 0xFF),
            sample_width=8,
            depth=8,
        )
        r = CaptureResult(config=cfg, samples=[0])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "y.surfer.txt"
            write_surfer_command_file_for_capture(r, p)
            text = p.read_text(encoding="utf-8")
        self.assertIn("logic.sample", text)
        self.assertIn("marker_set fcapz_trigger 0", text)
        self.assertIn("item_set_color blue", text)
        self.assertIn("goto_marker fcapz_trigger", text)

    def test_trigger_marker_uses_pretrigger_index_without_timestamps(self) -> None:
        cfg = CaptureConfig(
            pretrigger=2,
            posttrigger=2,
            trigger=TriggerConfig("value_match", 0, 0xFF),
            sample_width=8,
            depth=8,
        )
        r = CaptureResult(config=cfg, samples=[1, 2, 3, 4, 5])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "z.surfer.txt"
            write_surfer_command_file_for_capture(r, p)
            text = p.read_text(encoding="utf-8")
        self.assertIn("marker_set fcapz_trigger 2", text)
        self.assertIn("item_set_color blue", text)

    def test_no_marker_when_no_samples(self) -> None:
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=0,
            trigger=TriggerConfig("value_match", 0, 0xFF),
            sample_width=8,
            depth=8,
        )
        r = CaptureResult(config=cfg, samples=[])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.surfer.txt"
            write_surfer_command_file_for_capture(r, p)
            text = p.read_text(encoding="utf-8")
        self.assertNotIn("marker_set", text)
        self.assertNotIn("item_set_color", text)


if __name__ == "__main__":
    unittest.main()
