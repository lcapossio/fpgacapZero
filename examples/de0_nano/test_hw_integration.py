# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
# Copyright (c) 2026 Khush Patil

"""
Hardware tests for the Terasic DE0-Nano example (Cyclone IV E EP4CE22F17C6).

Requires the board on its onboard USB-Blaster, Quartus command-line tools
(quartus_stp, quartus_pgm; tested with Quartus II 13.1) and the example built
(output_files/de0_nano.sof). The suite programs the board first unless
FPGACAP_NO_PROGRAM=1.

With more than one cable attached, name the board's cable (as ``jtagconfig``
lists it) in FPGACAP_QUARTUS_HARDWARE: programming and the tests then both use
it, so no other board is reprogrammed.

Environment variables
---------------------
FPGACAP_SKIP_HW=1               skip all hardware tests
FPGACAP_NO_PROGRAM=1            do not program the board (already programmed)
FPGACAP_QUARTUS_HARDWARE=NAME   cable, e.g. "USB-Blaster [1-1]" (default: the only one)
FPGACAP_QUARTUS_STP=PATH        quartus_stp to use (default: on PATH)
FPGACAP_QUARTUS_PGM=PATH        quartus_pgm to use (default: on PATH)

Run:
    python -m pytest examples/de0_nano/test_hw_integration.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_HOST_DIR = _DIR.parents[1] / "host"  # this checkout's fcapz, not an installed one
_SOF = _DIR / "output_files" / "de0_nano.sof"
_STP = os.environ.get("FPGACAP_QUARTUS_STP") or shutil.which("quartus_stp")
_PGM = os.environ.get("FPGACAP_QUARTUS_PGM") or shutil.which("quartus_pgm")
_CABLE = os.environ.get("FPGACAP_QUARTUS_HARDWARE") or None
_SKIP = os.environ.get("FPGACAP_SKIP_HW", "").lower() in {"1", "true", "yes", "on"}

if str(_HOST_DIR) not in sys.path:
    sys.path.insert(0, str(_HOST_DIR))

SAMPLE_W = 10          # {KEY[1:0], counter[7:0]}
COUNTER_MASK = 0xFF
EIO_CHAIN = 3


def _fcapz(*args: str) -> str:
    cmd = [sys.executable, "-m", "fcapz.cli", "--backend", "usb_blaster", "--tap", "auto"]
    if _CABLE:
        cmd += ["--hardware", _CABLE]
    if _STP:
        cmd += ["--quartus-stp", _STP]
    env = dict(os.environ)
    env.pop("FCAPZ_BROKER", None)  # run directly, not as broker jobs
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_HOST_DIR), env.get("PYTHONPATH")) if p
    )
    out = subprocess.run(cmd + list(args), capture_output=True, text=True,
                         timeout=300, env=env)
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
            cmd = [_PGM, "-m", "jtag"]
            if _CABLE:
                cmd += ["-c", _CABLE]
            subprocess.run(cmd + ["-o", f"p;{_SOF}"], check=True,
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

    def test_eio_outputs_read_back_and_inputs_read(self):
        from fcapz.eio import EioController
        from fcapz.transport import QuartusStpTransport

        eio = EioController(
            QuartusStpTransport(hardware_name=_CABLE, quartus_stp_path=_STP),
            chain=EIO_CHAIN,
        )
        try:
            eio.connect()
            # Two different patterns, so an output register stuck at one
            # value cannot pass.
            for pattern in (0xA5, 0x5A):
                eio.write_outputs(pattern)  # LED[7:0]
                self.assertEqual(eio.read_outputs(), pattern)
            self.assertEqual(eio.read_inputs() & 0xC0, 0)  # unused input bits
        finally:
            eio.close()


if __name__ == "__main__":
    unittest.main()
