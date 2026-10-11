# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Hardware tests for the DE25-Nano core-manager variant (de25_nano_manager_top).

One fcapz_debug_multi_intel hub on virtual JTAG instance 1 carries four managed
slots: ELA0 (up counter), ELA1 (second counter XORed with 0xA5), EIO0 and EIO1.
The EJTAG-AXI bridge sits beside it on instance 4. The ELA captures carry
timestamps, so every read goes through the hub's single-chain burst, which is
the path the USB-Blaster transport has to route away from its data chain.

These tests require:
  - A DE25-Nano connected through the onboard USB-Blaster III
  - Quartus command-line tools on PATH (quartus_stp)
  - output_files/de25_nano_manager_fcapz.sof built and programmed:
        python examples/de25_nano/build.py --variant manager
        quartus_pgm -c "<cable>" -m jtag -o "p;<path to de25_nano_manager_fcapz.sof>"

Environment variables match test_hw_integration.py: FPGACAP_SKIP_HW,
FPGACAP_QUARTUS_HARDWARE, FPGACAP_QUARTUS_DEVICE and FPGACAP_QUARTUS_STP.

Run:
    python -m pytest examples/de25_nano/test_hw_manager.py -v
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_SKIP = _env_bool("FPGACAP_SKIP_HW")

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_DIR = Path(__file__).resolve().parent

BITFILE = str(_EXAMPLE_DIR / "output_files" / "de25_nano_manager_fcapz.sof")
_HARDWARE = os.environ.get("FPGACAP_QUARTUS_HARDWARE")
_DEVICE_ENV = os.environ.get("FPGACAP_QUARTUS_DEVICE", "auto")
_DEVICE = None if _DEVICE_ENV.lower() in ("", "auto") else _DEVICE_ENV
_QUARTUS_STP = os.environ.get("FPGACAP_QUARTUS_STP") or None

MANAGER_CHAIN = 1
AXI_CHAIN = 4
SAMPLE_CLOCK_HZ = 50_000_000

# Every input of build_de25_nano_manager.tcl (tests/test_de25_manager_sync.py
# keeps the two lists in step).
_BITSTREAM_SOURCES = [
    _ROOT / "rtl" / "fcapz_version.vh",
    _ROOT / "rtl" / "reset_sync.v",
    _ROOT / "rtl" / "dpram.v",
    _ROOT / "rtl" / "trig_compare.v",
    _ROOT / "rtl" / "fcapz_ela.v",
    _ROOT / "rtl" / "fcapz_eio.v",
    _ROOT / "rtl" / "fcapz_core_manager.v",
    _ROOT / "rtl" / "fcapz_debug_multi_core.v",
    _ROOT / "rtl" / "fcapz_hub_reset.v",
    _ROOT / "rtl" / "fcapz_debug_multi.v",
    _ROOT / "rtl" / "fcapz_debug_multi_intel.v",
    _ROOT / "rtl" / "jtag_pipe_iface.v",
    _ROOT / "rtl" / "jtag_tap" / "jtag_tap_intel.v",
    _ROOT / "rtl" / "fcapz_async_fifo.v",
    _ROOT / "rtl" / "fcapz_ejtagaxi.v",
    _ROOT / "rtl" / "fcapz_ejtagaxi_intel.v",
    _ROOT / "tb" / "axi4_test_slave.v",
    _EXAMPLE_DIR / "de25_nano_manager_top.v",
    _EXAMPLE_DIR / "build_de25_nano_manager.tcl",
    _EXAMPLE_DIR / "de25_nano.qsf",
    _EXAMPLE_DIR / "de25_nano.sdc",
]


def _check_bitstream_freshness() -> str | None:
    bitpath = Path(BITFILE)
    if not bitpath.exists():
        return f"bitfile not found: {BITFILE}"
    bit_mtime = bitpath.stat().st_mtime
    missing = [src.name for src in _BITSTREAM_SOURCES if not src.exists()]
    stale = [
        src.name for src in _BITSTREAM_SOURCES
        if src.exists() and src.stat().st_mtime > bit_mtime
    ]
    if missing or stale:
        parts = []
        if missing:
            parts.append(f"missing build inputs: {', '.join(missing)}")
        if stale:
            parts.append(f"these sources are newer than {bitpath.name}: {', '.join(stale)}")
        return (
            f"bitstream cannot be certified fresh — {'; '.join(parts)}. "
            "Re-run: python examples/de25_nano/build.py --variant manager"
        )
    return None


_STALE_MSG = _check_bitstream_freshness()
if _STALE_MSG and not _SKIP:
    raise RuntimeError(_STALE_MSG)


def _make_transport():
    from fcapz.transport import QuartusStpTransport

    return QuartusStpTransport(
        hardware_name=_HARDWARE,
        device_name=_DEVICE,
        quartus_stp_path=_QUARTUS_STP,
    )


def _counter_errors(samples: list[int]) -> list[tuple[int, int, int]]:
    return [
        (i - 1, samples[i - 1], samples[i])
        for i in range(1, len(samples))
        if ((samples[i] - samples[i - 1]) & 0xFF) != 1
    ]


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestManagerEnumeration(unittest.TestCase):
    """The hub on instance 1 reports its slots and keeps them apart."""

    def test_manager_enumerates_slots(self):
        from fcapz.analyzer import CORE_MANAGER_CORE_ID, ELA_CORE_ID, ElaManager

        t = _make_transport()
        try:
            t.connect()
            manager = ElaManager(t, chain=MANAGER_CHAIN)
            minfo = manager.probe()
            self.assertEqual(minfo["core_id"], CORE_MANAGER_CORE_ID)
            self.assertEqual(minfo["num_slots"], 4)
            self.assertEqual(
                [manager.slot_info(i)["core_id"] for i in range(4)],
                [ELA_CORE_ID, ELA_CORE_ID, 0x494F, 0x494F],
            )
            slots = manager.probe_all()
            self.assertEqual([s["instance"] for s in slots], [0, 1])
            for slot in slots:
                self.assertEqual(slot["core_id"], ELA_CORE_ID)
                self.assertEqual(slot["sample_width"], 8)
                self.assertEqual(slot["depth"], 1024)
                self.assertEqual(slot["timestamp_width"], 32)
                self.assertEqual(slot["num_segments"], 4)
        finally:
            t.close()

    def test_slot_registers_are_independent(self):
        from fcapz.analyzer import Analyzer

        t = _make_transport()
        try:
            t.connect()
            ela0 = Analyzer(t, chain=MANAGER_CHAIN, instance=0)
            ela1 = Analyzer(t, chain=MANAGER_CHAIN, instance=1)
            ela0.select_instance(0)
            t.write_reg(0x0014, 11)  # PRETRIG_LEN
            ela1.select_instance(1)
            t.write_reg(0x0014, 22)
            ela0.select_instance(0)
            self.assertEqual(t.read_reg(0x0014), 11)
            ela1.select_instance(1)
            self.assertEqual(t.read_reg(0x0014), 22)
        finally:
            t.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestManagedCapture(unittest.TestCase):
    """Managed ELA captures read back through the hub's own burst."""

    def _capture(self, instance: int, value: int, pretrigger: int, posttrigger: int):
        from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

        a = Analyzer(_make_transport(), chain=MANAGER_CHAIN, instance=instance)
        try:
            a.connect()
            a.configure(CaptureConfig(
                pretrigger=pretrigger,
                posttrigger=posttrigger,
                trigger=TriggerConfig(mode="value_match", value=value, mask=0xFF),
                sample_width=8,
                depth=1024,
                sample_clock_hz=SAMPLE_CLOCK_HZ,
            ))
            # The bitstream boots STARTUP_ARM=1: go idle before arming.
            a.force_idle()
            a.arm()
            return a.capture(timeout=5.0)
        finally:
            a.close()

    def _assert_timestamps_step(self, result):
        self.assertEqual(len(result.timestamps), len(result.samples))
        gaps = [
            result.timestamps[i] - result.timestamps[i - 1]
            for i in range(1, len(result.timestamps))
        ]
        self.assertTrue(all(g == 1 for g in gaps), result.timestamps[:16])

    def test_first_ela_captures_counter(self):
        result = self._capture(0, 0x40, 4, 8)
        samples = [s & 0xFF for s in result.samples]
        self.assertEqual(len(samples), 13)
        self.assertEqual(_counter_errors(samples), [], samples)
        self.assertEqual(samples[4], 0x40)
        self._assert_timestamps_step(result)

    def test_second_ela_captures_xored_counter(self):
        result = self._capture(1, 0xA5, 4, 8)
        samples = [s & 0xFF for s in result.samples]
        decoded = [s ^ 0xA5 for s in samples]
        self.assertEqual(_counter_errors(decoded), [], samples)
        self.assertEqual(samples[4], 0xA5)
        self._assert_timestamps_step(result)

    def test_long_capture_spans_many_burst_packets(self):
        # 255 samples (one segment of 1024/4) is eight 256-bit packets of
        # 8-bit samples, plus the timestamp burst.
        result = self._capture(0, 0x10, 16, 238)
        samples = [s & 0xFF for s in result.samples]
        self.assertEqual(len(samples), 255)
        self.assertEqual(_counter_errors(samples), [], samples[:32])
        self.assertEqual(samples[16], 0x10)
        self._assert_timestamps_step(result)

    def test_slot_switch_after_burst(self):
        """BUG-221: the ACTIVE write that follows a burst must land."""
        from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

        t = _make_transport()
        try:
            t.connect()
            ela0 = Analyzer(t, chain=MANAGER_CHAIN, instance=0)
            ela1 = Analyzer(t, chain=MANAGER_CHAIN, instance=1)
            for rnd in range(3):
                ela0.configure(CaptureConfig(
                    pretrigger=2, posttrigger=5,
                    trigger=TriggerConfig(mode="value_match", value=0x20 + rnd, mask=0xFF),
                    sample_width=8, depth=1024,
                ))
                ela0.force_idle()
                ela0.arm()
                r0 = ela0.capture(timeout=5.0)
                self.assertEqual(r0.samples[2] & 0xFF, 0x20 + rnd)

                ela1.configure(CaptureConfig(
                    pretrigger=2, posttrigger=5,
                    trigger=TriggerConfig(mode="value_match", value=0xA5, mask=0xFF),
                    sample_width=8, depth=1024,
                ))
                ela1.force_idle()
                ela1.arm()
                r1 = ela1.capture(timeout=5.0)
                self.assertEqual(r1.samples[2] & 0xFF, 0xA5, f"round {rnd}")
        finally:
            t.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestManagedEio(unittest.TestCase):
    """EIO slots 2 and 3 behind the hub."""

    def _eio(self, instance: int):
        from fcapz.eio import EioController

        eio = EioController(_make_transport(), chain=MANAGER_CHAIN, instance=instance)
        eio.connect()
        self.addCleanup(eio.close)
        return eio

    def test_eio_widths(self):
        for instance in (2, 3):
            eio = self._eio(instance)
            self.assertEqual((eio.in_w, eio.out_w), (8, 8), f"slot {instance}")

    def test_slow_counter_advances(self):
        eio = self._eio(2)
        start = eio.read_inputs() & 0x0F
        seen = [start]
        deadline = time.time() + 2.5
        while time.time() < deadline:
            time.sleep(0.25)
            cur = eio.read_inputs() & 0x0F
            seen.append(cur)
            if cur != start:
                return
        self.fail(f"1 Hz EIO counter did not advance: samples={seen}")

    def test_outputs_roundtrip_and_stay_independent(self):
        from fcapz.eio import EioController

        # Both slots on one transport: each session caches the active slot,
        # so two sessions interleaving on one hub would not see each other's
        # switches.
        t = _make_transport()
        eio0 = EioController(t, chain=MANAGER_CHAIN, instance=2)
        eio0.connect()
        self.addCleanup(eio0.close)
        eio1 = EioController(t, chain=MANAGER_CHAIN, instance=3)
        eio1.attach()
        for bit in range(8):
            eio0.write_outputs(1 << bit)
            self.assertEqual(eio0.read_outputs(), 1 << bit)
        eio0.write_outputs(0xA5)
        eio1.write_outputs(0x3C)
        self.assertEqual(eio0.read_outputs(), 0xA5)
        self.assertEqual(eio1.read_outputs(), 0x3C)
        eio0.write_outputs(0x00)
        eio1.write_outputs(0x00)
        self.assertEqual(eio0.read_outputs(), 0x00)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestBridgeBesideManager(unittest.TestCase):
    """The EJTAG-AXI bridge on instance 4 works next to the hub."""

    def test_bridge_roundtrip(self):
        from fcapz.ejtagaxi import _BRIDGE_CORE_ID, EjtagAxiController

        bridge = EjtagAxiController(_make_transport(), chain=AXI_CHAIN)
        try:
            info = bridge.connect()
            self.assertEqual(info["core_id"], _BRIDGE_CORE_ID)
            for val in (0x00000000, 0xFFFFFFFF, 0xA5A5A5A5, 0x12345678):
                bridge.axi_write(0x00, val)
                self.assertEqual(bridge.axi_read(0x00), val)
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
