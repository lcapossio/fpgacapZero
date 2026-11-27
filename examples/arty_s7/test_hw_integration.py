# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
# Copyright (c) 2026 Khush Patil

"""
Hardware tests for the Digilent Arty S7-25 example (Spartan-7 XC7S25-1CSGA324).

Requires the board on its onboard USB-JTAG, a running Vivado hw_server
(tested with Vivado 2025.2.1) and the example built (arty_s7_fcapz.bit).
The suite programs the board first, through the same hw_server target the
tests then use, unless FPGACAP_NO_PROGRAM=1.

Environment variables
---------------------
FPGACAP_SKIP_HW=1       skip all hardware tests
FPGACAP_NO_PROGRAM=1    do not program the board (already programmed)
FPGACAP_HW_TARGET=NAME  hw_server target name (default: xc7s25)
FPGACAP_HW_HOST=HOST    hw_server host (default: 127.0.0.1)
FPGACAP_HW_PORT=PORT    hw_server port (default: 3121)

Run:
    python -m pytest examples/arty_s7/test_hw_integration.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_HOST_DIR = _DIR.parents[1] / "host"  # this checkout's fcapz, not an installed one
_BIT = _DIR / "arty_s7_fcapz.bit"
_TARGET = os.environ.get("FPGACAP_HW_TARGET", "xc7s25")
_HW_HOST = os.environ.get("FPGACAP_HW_HOST", "127.0.0.1")
_HW_PORT = int(os.environ.get("FPGACAP_HW_PORT", "3121"))
# The CLI reads port 6666 (its OpenOCD default) as unset and uses 3121; do
# the same here, so the EIO test talks to the server the CLI programmed.
if _HW_PORT == 6666:
    _HW_PORT = 3121
_SKIP = os.environ.get("FPGACAP_SKIP_HW", "").lower() in {"1", "true", "yes", "on"}

if str(_HOST_DIR) not in sys.path:
    sys.path.insert(0, str(_HOST_DIR))

SAMPLE_W = 12          # {btn[3:0], counter[7:0]}
COUNTER_MASK = 0xFF
EIO_CHAIN = 3


def _fcapz(*args: str, cwd: Path | None = None) -> str:
    cmd = [sys.executable, "-m", "fcapz.cli", "--backend", "hw_server",
           "--host", _HW_HOST, "--port", str(_HW_PORT), "--tap", _TARGET]
    env = dict(os.environ)
    env.pop("FCAPZ_BROKER", None)  # --program does not run through the broker
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_HOST_DIR), env.get("PYTHONPATH")) if p
    )
    out = subprocess.run(cmd + list(args), capture_output=True, text=True,
                         timeout=300, env=env, cwd=cwd)
    if out.returncode != 0:
        raise AssertionError(f"fcapz {' '.join(args)} failed:\n{out.stdout}\n{out.stderr}")
    return out.stdout


@unittest.skipIf(_SKIP, "hardware tests disabled")
class ArtyS7Hw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FPGACAP_NO_PROGRAM", "").lower() not in {"1", "true", "yes", "on"}:
            if not _BIT.exists():
                raise unittest.SkipTest("arty_s7_fcapz.bit missing; build it first")
            # Through hw_server and the same target the tests use, so it is
            # the board under test that gets programmed, not the first
            # Digilent cable on the bench.
            # The bitfile by name from its own directory: the transport refuses
            # Tcl-unsafe characters such as "@" that a checkout path may hold.
            _fcapz("--program", _BIT.name, "probe", cwd=_DIR)

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

    def test_eio_outputs_read_back_and_inputs_read(self):
        from fcapz.eio import EioController
        from fcapz.transport import XilinxHwServerTransport

        eio = EioController(
            XilinxHwServerTransport(host=_HW_HOST, port=_HW_PORT, fpga_name=_TARGET),
            chain=EIO_CHAIN,
        )
        try:
            eio.connect()
            # Two different patterns, so an output register stuck at one
            # value cannot pass.
            for pattern in (0x05, 0x0A):
                eio.write_outputs(pattern)  # led[3:0]
                self.assertEqual(eio.read_outputs() & 0x0F, pattern)
            self.assertEqual(eio.read_inputs() & 0x08, 0)  # the unused input bit
        finally:
            eio.close()


if __name__ == "__main__":
    unittest.main()
