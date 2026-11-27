# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
# Copyright (c) 2026 Khush Patil

"""
Hardware tests for the Terasic DE0-Nano example (Cyclone IV E EP4CE22F17C6).

Requires the board on its onboard USB-Blaster, Quartus command-line tools
(quartus_stp, quartus_pgm; tested with Quartus II 13.1) and the example built
(output_files/de0_nano.sof). The suite programs the board first unless
FPGACAP_NO_PROGRAM=1.

Environment variables
---------------------
FPGACAP_SKIP_HW=1         skip all hardware tests
FPGACAP_NO_PROGRAM=1      do not program the board (already programmed)
FPGACAP_QUARTUS_STP=PATH  quartus_stp to use (default: on PATH)
FPGACAP_QUARTUS_PGM=PATH  quartus_pgm to use (default: on PATH)

Run:
    python -m pytest examples/de0_nano/test_hw_integration.py -v
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
_SOF = _DIR / "output_files" / "de0_nano.sof"
_STP = os.environ.get("FPGACAP_QUARTUS_STP") or shutil.which("quartus_stp")
_PGM = os.environ.get("FPGACAP_QUARTUS_PGM") or shutil.which("quartus_pgm")
_SKIP = os.environ.get("FPGACAP_SKIP_HW", "").lower() in {"1", "true", "yes", "on"}

SAMPLE_W = 10          # {KEY[1:0], counter[7:0]}
COUNTER_MASK = 0xFF


def _fcapz(*args: str) -> str:
    cmd = ["fcapz", "--backend", "usb_blaster", "--tap", "auto"]
    if _STP:
        cmd += ["--quartus-stp", _STP]
    out = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise AssertionError(f"fcapz {' '.join(args)} failed:\n{out.stdout}\n{out.stderr}")
    return out.stdout


@unittest.skipIf(_SKIP or not _STP, "hardware tests disabled or quartus_stp not found")
class De0NanoHw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FPGACAP_NO_PROGRAM", "").lower() not in {"1", "true", "yes", "on"}:
            if not _PGM or not _SOF.exists():
                raise unittest.SkipTest("quartus_pgm or output_files/de0_nano.sof missing")
            subprocess.run([_PGM, "-m", "jtag", "-o", f"p;{_SOF}"], check=True,
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
                   "--trigger-mask", "0xFF", "--sample-clock-hz", "50000000",
                   "--out", str(out))
            samples = json.loads(out.read_text())["samples"]
        values = [(s if isinstance(s, int) else int(s["value"])) & COUNTER_MASK for s in samples]
        self.assertEqual(len(values), 33)
        self.assertEqual(values[8], 0x40)
        for a, b in zip(values, values[1:]):
            self.assertEqual(b, (a + 1) & COUNTER_MASK)

    def test_eio_write_then_read_inputs(self):
        _fcapz("eio-write", "0xA5")      # LED[7:0]
        value = int(_fcapz("eio-read").split()[-1], 16)
        self.assertEqual(value & 0xC0, 0)  # unused input bits read 0


if __name__ == "__main__":
    unittest.main()
