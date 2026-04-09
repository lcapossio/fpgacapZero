# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

from fcapz.analyzer import CaptureConfig, CaptureResult, ProbeSpec, TriggerConfig

if PySide6 is not None:
    import numpy as np

    from fcapz.gui.waveform_preview import _x_axis_and_label, _x_edges_for_step_plot, lanes_from_capture


@unittest.skipUnless(PySide6 is not None, "PySide6 not installed")
class TestLanesFromCapture(unittest.TestCase):
    def _cfg(self, **kwargs: object) -> CaptureConfig:
        vals: dict[str, object] = {
            "pretrigger": 0,
            "posttrigger": 3,
            "trigger": TriggerConfig(mode="value_match", value=0, mask=0xFF),
            "sample_width": 8,
            "depth": 16,
            "sample_clock_hz": 100_000_000,
            "probes": [],
        }
        vals.update(kwargs)
        return CaptureConfig(**vals)  # type: ignore[arg-type]

    def test_single_sample_word(self) -> None:
        cfg = self._cfg()
        r = CaptureResult(config=cfg, samples=[0b1010_1100, 0x0F])
        lanes = lanes_from_capture(r)
        self.assertEqual(lanes, [("sample", [0b1010_1100, 15])])

    def test_named_probes(self) -> None:
        cfg = self._cfg(
            probes=[
                ProbeSpec(name="lo", width=4, lsb=0),
                ProbeSpec(name="hi", width=4, lsb=4),
            ],
        )
        r = CaptureResult(config=cfg, samples=[0xAB])
        lanes = lanes_from_capture(r)
        self.assertEqual(lanes[0], ("lo", [11]))
        self.assertEqual(lanes[1], ("hi", [10]))

    def test_x_axis_sample_index(self) -> None:
        cfg = self._cfg()
        r = CaptureResult(config=cfg, samples=[1, 2, 3])
        x, label = _x_axis_and_label(r)
        self.assertEqual(label, "Sample index")
        self.assertEqual(x, [0.0, 1.0, 2.0])

    def test_x_axis_timestamps(self) -> None:
        cfg = self._cfg()
        r = CaptureResult(config=cfg, samples=[1, 2], timestamps=[10, 20])
        x, label = _x_axis_and_label(r)
        self.assertEqual(label, "Time (s)")
        # 100 MHz -> 10 ns timescale; 10 ticks -> 100e-9 s
        self.assertAlmostEqual(x[0], 100e-9)
        self.assertAlmostEqual(x[1], 200e-9)

    def test_x_edges_for_step_plot(self) -> None:
        e = _x_edges_for_step_plot(np.array([0.0, 1.0, 2.0, 3.0]))
        self.assertEqual(e.tolist(), [-0.5, 0.5, 1.5, 2.5, 3.5])
        e1 = _x_edges_for_step_plot(np.array([5.0]))
        self.assertEqual(e1.tolist(), [4.5, 5.5])


if __name__ == "__main__":
    unittest.main()
