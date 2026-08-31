# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Hardware integration tests for the Arty A7 VexRiscv (Dhrystone) variant.

Companion to test_hw_integration.py, targeting the arty_a7_vex_top bitstream:
an open-source VexRiscv soft CPU runs Dhrystone from on-chip BRAM and publishes
its score to the shared AXI test slave, which the host reads back over
EJTAG-AXI (and the AXI monitor can capture the CPU's write traffic).

Requires an Arty A7-100T built with:
    RISCV_PREFIX=riscv64-unknown-elf- python examples/arty_a7/build_arty_vex.py

Run:
    FPGACAP_BITFILE=examples/arty_a7/arty_a7_vex_top.bit \
        python -m pytest examples/arty_a7/test_hw_integration_vex.py -v

Skip if no hardware:
    FPGACAP_SKIP_HW=1 python -m pytest examples/arty_a7/test_hw_integration_vex.py -v
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

_SKIP = os.environ.get("FPGACAP_SKIP_HW", "")

_EXAMPLE_DIR = Path(__file__).resolve().parent
_ROOT = _EXAMPLE_DIR.parents[1]
_BITFILE_ENV = os.environ.get("FPGACAP_BITFILE")
BITFILE = str(
    Path(_BITFILE_ENV).resolve() if _BITFILE_ENV
    else _EXAMPLE_DIR / "arty_a7_vex_top.bit"
)
_BACKEND = os.environ.get("FPGACAP_BACKEND", "hw_server").lower()
_OPENOCD_PORT = int(os.environ.get("FPGACAP_OPENOCD_PORT", "6666"))
_OPENOCD_TAP = os.environ.get("FPGACAP_OPENOCD_TAP", "xc7a100t.tap")
PORT = 3121
FPGA = "xc7a100t"

# Sources that feed the VexRiscv bitstream (must match build_arty_vex.tcl); a
# newer source than the bitfile flags a stale build. The fetched VexRiscv core
# is listed but skipped if absent (get_deps.py drops it in on build).
_BITSTREAM_SOURCES = [
    _ROOT / "rtl" / "fcapz_version.vh",
    _ROOT / "rtl" / "fcapz_ela.v",
    _ROOT / "rtl" / "fcapz_core_manager.v",
    _ROOT / "rtl" / "fcapz_debug_multi_xilinx7.v",
    _ROOT / "rtl" / "fcapz_ejtagaxi_xilinx7.v",
    _ROOT / "rtl" / "fcapz_axi_mon_xilinx7.v",
    _ROOT / "tb" / "axi4_test_slave.v",
    _EXAMPLE_DIR / "arty_a7_vex_top.v",
    _EXAMPLE_DIR / "arty_a7.xdc",
    _EXAMPLE_DIR / "vex" / "VexRiscv_Lite.v",
    _EXAMPLE_DIR / "vex" / "vex_cpu.v",
    _EXAMPLE_DIR / "vex" / "vex_sys.v",
    _EXAMPLE_DIR / "vex" / "create_vex_bd.tcl",
    _EXAMPLE_DIR / "vex" / "fw" / "boot.S",
    _EXAMPLE_DIR / "vex" / "fw" / "dhry_1.c",
    _EXAMPLE_DIR / "vex" / "fw" / "dhry_2.c",
    _EXAMPLE_DIR / "vex" / "fw" / "dhry.h",
    _EXAMPLE_DIR / "vex" / "fw" / "platform.h",
    _EXAMPLE_DIR / "vex" / "fw" / "support.c",
    _EXAMPLE_DIR / "vex" / "fw" / "link.ld",
]


def _check_bitstream_freshness() -> str | None:
    bitpath = Path(BITFILE)
    if not bitpath.exists():
        return f"bitfile not found: {BITFILE} (run build_arty_vex.py)"
    bit_mtime = bitpath.stat().st_mtime
    stale = [s.name for s in _BITSTREAM_SOURCES
             if s.exists() and s.stat().st_mtime > bit_mtime]
    if stale:
        return (
            f"bitstream is stale — newer than {bitpath.name}: "
            f"{', '.join(stale)}. Re-run: python examples/arty_a7/build_arty_vex.py"
        )
    return None


_STALE_MSG = _check_bitstream_freshness()
if _STALE_MSG and not _SKIP:
    raise RuntimeError(_STALE_MSG)


def _make_transport():
    if _BACKEND == "openocd":
        from fcapz.transport import OpenOcdTransport
        return OpenOcdTransport(port=_OPENOCD_PORT, tap=_OPENOCD_TAP)
    from fcapz.transport import XilinxHwServerTransport
    return XilinxHwServerTransport(port=PORT, fpga_name=FPGA, bitfile=BITFILE)


# Shared-slave byte offsets (word = (addr >> 2) % 32); must match
# vex/fw/platform.h. Dhrystone leaves words 0..15 for the EJTAG host tests.
GO_OFF = 0x7C      # word31: host go flag (CPU polls)
DONE_OFF = 0x40    # word16: DONE_MAGIC once results are ready
RUNS_OFF = 0x44    # word17: Number_Of_Runs
CYCLES_OFF = 0x48  # word18: measured cycle delta
HZ_OFF = 0x4C      # word19: CPU clock (Hz)
CHECK_OFF = 0x50   # word20: Dhrystone global checksum
DONE_MAGIC = 0xD05ED09E
DHRYSTONE_VAX_DPS = 1757.0  # 1 DMIPS == 1757 Dhrystones/second (VAX 11/780)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
@unittest.skipIf(_BACKEND != "hw_server", "requires hw_server programming on connect")
class TestVexDhrystone(unittest.TestCase):
    """VexRiscv runs Dhrystone; the host reads the score back over EJTAG-AXI."""

    def setUp(self):
        from fcapz.ejtagaxi import EjtagAxiController

        self.t = _make_transport()
        self.t.connect()  # program the bitstream (CPU resets -> go=0, quiet)
        self.bridge = EjtagAxiController(self.t, chain=4)
        self.bridge.attach()
        self._set_go(0)

    def tearDown(self):
        try:
            self._set_go(0)
        finally:
            self.t.close()

    def _set_go(self, value: int) -> None:
        self.bridge.axi_write(GO_OFF, value)

    def _wait_done(self, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.bridge.axi_read(DONE_OFF) == DONE_MAGIC:
                return True
            time.sleep(0.05)
        return False

    def test_dhrystone_runs_and_reports_plausible_dmips(self):
        """Turn the CPU loose, wait for DONE, and check the reported score."""
        self.bridge.axi_write(DONE_OFF, 0)  # clear any stale sentinel
        self._set_go(1)
        self.assertTrue(self._wait_done(), "Dhrystone did not signal DONE in time")

        runs = self.bridge.axi_read(RUNS_OFF)
        cycles = self.bridge.axi_read(CYCLES_OFF)
        hz = self.bridge.axi_read(HZ_OFF)
        checksum = self.bridge.axi_read(CHECK_OFF)

        self.assertGreater(runs, 0, "no Dhrystone runs reported")
        self.assertGreater(cycles, 0, "zero measured cycles")
        self.assertEqual(hz, 100_000_000, f"unexpected clock report: {hz}")
        self.assertNotEqual(checksum, 0, "Dhrystone checksum is zero (loop elided?)")

        seconds = cycles / hz
        dhrystones_per_sec = runs / seconds
        dmips = dhrystones_per_sec / DHRYSTONE_VAX_DPS
        print(
            f"\nVexRiscv Dhrystone: {runs} runs in {cycles} cycles "
            f"({seconds * 1e3:.2f} ms @ {hz / 1e6:.0f} MHz) -> "
            f"{dmips:.1f} DMIPS ({dmips / (hz / 1e6):.3f} DMIPS/MHz)"
        )
        # Wide sanity window: an RV32I VexRiscv with soft mul/div lands well
        # inside this, and a broken counter/loop falls outside it.
        self.assertGreater(dmips, 1.0, "implausibly low DMIPS")
        self.assertLess(dmips, 500.0, "implausibly high DMIPS")

    def test_cpu_traffic_triggers_monitor(self):
        """The AXI monitor (USER2) triggers on the CPU's Dhrystone write bursts."""
        from fcapz.analyzer import Analyzer
        from fcapz.axi_monitor import AxiMonitor

        an = Analyzer(self.t, chain=2)
        mon = AxiMonitor(an)
        self.assertTrue(mon.present, "AXI monitor not detected on USER2")

        cfg = mon.event_capture_config("aw_hs", pretrigger=2, posttrigger=12, depth=256)
        an.configure(cfg)
        an.arm()
        self.t.select_chain(2)
        self.assertEqual(self.t.read_reg(0x0008) & 0x1, 1, "monitor did not arm")

        self.bridge.axi_write(DONE_OFF, 0)
        self._set_go(1)  # CPU starts writing the shared slave

        deadline = time.time() + 5.0
        status = 0
        while time.time() < deadline:
            self.t.select_chain(2)
            status = self.t.read_reg(0x0008)
            if status & 0x4:
                break
        self.assertTrue(status & 0x2, f"monitor did not trigger on CPU writes (0x{status:08X})")

        # Cross-check the CPU really ran: results are readable over EJTAG-AXI.
        self.assertTrue(self._wait_done(), "Dhrystone did not complete")
        self.assertGreater(self.bridge.axi_read(RUNS_OFF), 0)


if __name__ == "__main__":
    unittest.main()
