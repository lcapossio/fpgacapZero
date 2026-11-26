# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
# Copyright (c) 2026 Khush Patil

"""
Hardware tests for the Digilent Arty S7-25 example (Spartan-7 XC7S25-1CSGA324).

Requires the board on its onboard USB-JTAG, a running Vivado hw_server
(tested with Vivado 2025.2.1) and the example built (arty_s7_fcapz.bit).
The suite programs the board first (openFPGALoader -c digilent) unless
FPGACAP_NO_PROGRAM=1.

Environment variables
---------------------
FPGACAP_SKIP_HW=1       skip all hardware tests
FPGACAP_NO_PROGRAM=1    do not program the board (already programmed)
FPGACAP_HW_TARGET=NAME  hw_server target name (default: xc7s25)

Run:
    python -m pytest examples/arty_s7/test_hw_integration.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_BIT = _DIR / "arty_s7_fcapz.bit"
_TARGET = os.environ.get("FPGACAP_HW_TARGET", "xc7s25")
_SKIP = os.environ.get("FPGACAP_SKIP_HW", "").lower() in {"1", "true", "yes", "on"}

SAMPLE_W = 12          # {btn[3:0], counter[7:0]}
COUNTER_MASK = 0xFF


def _fcapz(*args: str) -> str:
    cmd = ["fcapz", "--backend", "hw_server", "--tap", _TARGET]
    out = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise AssertionError(f"fcapz {' '.join(args)} failed:\n{out.stdout}\n{out.stderr}")
    return out.stdout


@unittest.skipIf(_SKIP, "hardware tests disabled")
class ArtyS7Hw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FPGACAP_NO_PROGRAM", "").lower() not in {"1", "true", "yes", "on"}:
            loader = shutil.which("openFPGALoader")
            if not loader or not _BIT.exists():
                raise unittest.SkipTest("openFPGALoader or arty_s7_fcapz.bit missing")
            subprocess.run([loader, "-c", "digilent", str(_BIT)], check=True,
                           capture_output=True, timeout=300)

    def test_probe_reports_sample_width_and_depth(self):
        text = _fcapz("probe")
        info = json.loads(text[text.index("{"):])
        self.assertEqual(info["sample_width"], SAMPLE_W)
        self.assertEqual(info["depth"], 1024)

    def test_capture_counter_increments_and_triggers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cap.json"
            _fcapz("capture", "--pretrigger", "8", "--posttrigger", "24",
                   "--trigger-mode", "value_match", "--trigger-value", "0x40",
                   "--trigger-mask", "0xFF", "--sample-clock-hz", "12000000",
                   "--out", str(out))
            samples = json.loads(out.read_text())["samples"]
        values = [(s if isinstance(s, int) else int(s["value"])) & COUNTER_MASK for s in samples]
        self.assertEqual(len(values), 33)
        self.assertEqual(values[8], 0x40)
        for a, b in zip(values, values[1:]):
            self.assertEqual(b, (a + 1) & COUNTER_MASK)

    def test_eio_write_then_read_inputs(self):
        _fcapz("eio-write", "0x5")       # led[3:0]
        value = int(_fcapz("eio-read").split()[-1], 16)
        self.assertEqual(value & 0x08, 0)  # the unused input bit reads 0


if __name__ == "__main__":
    unittest.main()
