# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Hardware tests for the PolarFire SoC Discovery Kit core-manager variant
(mpfs_disco_kit_manager_top.v).

One fcapz_debug_multi_polarfire hub on UJTAG USER1 (IR 0x20) carries four
slots: ELA0 (counter), ELA1 (counter XOR 0xA5), EIO0 (switches + a slow
counter in, LEDs out) and EIO1 (outputs looped back to its inputs).  The ELA
captures carry 32-bit timestamps, and every read goes through the hub's
single-chain burst.

Build and program the variant first:

    python examples/mpfs_disco_kit/build.py --variant manager --program

Environment variables are those of test_hw_integration.py: FPGACAP_SKIP_HW,
FPGACAP_BACKEND (``openocd`` or ``ftdi``), FPGACAP_OPENOCD_PORT,
FPGACAP_OPENOCD_TAP and FPGACAP_FTDI_DEVICE.

Run:
    FPGACAP_BACKEND=ftdi python -m pytest examples/mpfs_disco_kit/test_hw_manager.py -v
"""

from __future__ import annotations

import os
import time
import unittest

_SKIP = os.environ.get("FPGACAP_SKIP_HW", "")
_BACKEND = os.environ.get("FPGACAP_BACKEND", "openocd").strip().lower()
_PORT = int(os.environ.get("FPGACAP_OPENOCD_PORT", "6666"))
_TAP = os.environ.get("FPGACAP_OPENOCD_TAP", "MPFS095T.tap")
_FTDI_DEVICE = os.environ.get("FPGACAP_FTDI_DEVICE") or None

MANAGER_CHAIN = 1
SAMPLE_CLOCK_HZ = 50_000_000
EIO_CORE_ID = 0x494F


def _make_transport():
    if _BACKEND == "ftdi":
        from fcapz.ftdi_transport import FtdiMpsseTransport

        return FtdiMpsseTransport(device=_FTDI_DEVICE)
    from fcapz.transport import OpenOcdTransport

    return OpenOcdTransport(
        host="127.0.0.1",
        port=_PORT,
        tap=_TAP,
        ir_table=OpenOcdTransport.IR_TABLE_POLARFIRE,
        burst=True,
    )


def _counter_errors(samples: list[int]) -> list[tuple[int, int, int]]:
    return [
        (i - 1, samples[i - 1], samples[i])
        for i in range(1, len(samples))
        if ((samples[i] - samples[i - 1]) & 0xFF) != 1
    ]


def _manager_or_skip(t):
    """Return a probed ElaManager on *t*, or raise SkipTest without the design."""
    from fcapz.analyzer import CORE_MANAGER_CORE_ID, ElaManager

    try:
        t.connect()
    except (OSError, RuntimeError) as exc:
        t.close()
        raise unittest.SkipTest(f"{_BACKEND} JTAG not reachable ({exc})")
    manager = ElaManager(t, chain=MANAGER_CHAIN)
    try:
        info = manager.probe()
    except RuntimeError as exc:
        t.close()
        raise unittest.SkipTest(f"no core manager on USER1 ({exc}); program the manager variant")
    if info["core_id"] != CORE_MANAGER_CORE_ID:
        t.close()
        raise unittest.SkipTest("USER1 holds no core manager; program the manager variant")
    return manager


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestManagerEnumeration(unittest.TestCase):
    """The hub reports its slots and keeps them apart."""

    def test_manager_enumerates_slots(self):
        from fcapz.analyzer import ELA_CORE_ID

        t = _make_transport()
        try:
            manager = _manager_or_skip(t)
            self.assertEqual(manager.probe()["num_slots"], 4)
            self.assertEqual(
                [manager.slot_info(i)["core_id"] for i in range(4)],
                [ELA_CORE_ID, ELA_CORE_ID, EIO_CORE_ID, EIO_CORE_ID],
            )
            slots = manager.probe_all()
            self.assertEqual([s["instance"] for s in slots], [0, 1])
            for slot in slots:
                self.assertEqual(slot["sample_width"], 8)
                self.assertEqual(slot["depth"], 1024)
                self.assertEqual(slot["timestamp_width"], 32)
                self.assertEqual(slot["num_segments"], 4)
        finally:
            t.close()

    def test_manager_caps(self):
        from fcapz.registers import ADDR_MGR_TLR_COUNT

        ADDR_MGR_CAPS = 0xF010
        ADDR_MGR_DESC_INDEX = 0xF014
        ADDR_MGR_DESC_CAPS = 0xF01C
        t = _make_transport()
        try:
            _manager_or_skip(t)
            with t.transaction_lock():
                t.select_chain(MANAGER_CHAIN)
                # Burst header on (bit 4), no Test-Logic-Reset reset (bit 6).
                self.assertEqual(t.read_reg(ADDR_MGR_CAPS), 0xBF)
                # UJTAG has no Test-Logic-Reset output: the count stays 0.
                self.assertEqual(t.read_reg(ADDR_MGR_TLR_COUNT), 0)
                bursts = []
                for slot in range(4):
                    t.write_reg(ADDR_MGR_DESC_INDEX, slot)
                    bursts.append(t.read_reg(ADDR_MGR_DESC_CAPS))
                self.assertEqual(bursts, [1, 1, 0, 0])
        finally:
            t.close()

    def test_slot_registers_are_independent(self):
        from fcapz.analyzer import Analyzer

        t = _make_transport()
        try:
            _manager_or_skip(t)
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
    """Managed ELA captures read back through the hub's burst."""

    def _capture(self, instance: int, value: int, pretrigger: int, posttrigger: int):
        from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

        t = _make_transport()
        _manager_or_skip(t)
        a = Analyzer(t, chain=MANAGER_CHAIN, instance=instance)
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
        self.assertEqual(_counter_errors([s ^ 0xA5 for s in samples]), [], samples)
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
            _manager_or_skip(t)
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

    def _eio(self, t, instance: int, *, connect: bool):
        from fcapz.eio import EioController

        eio = EioController(t, chain=MANAGER_CHAIN, instance=instance)
        if connect:
            eio.connect()
        else:
            eio.attach()
        return eio

    def test_eio_widths(self):
        t = _make_transport()
        _manager_or_skip(t)
        t.close()
        for instance in (2, 3):
            eio = self._eio(_make_transport(), instance, connect=True)
            try:
                self.assertEqual((eio.in_w, eio.out_w), (8, 8), f"slot {instance}")
            finally:
                eio.close()

    def test_slow_counter_advances(self):
        t = _make_transport()
        _manager_or_skip(t)
        t.close()
        eio = self._eio(_make_transport(), 2, connect=True)
        try:
            start = eio.read_inputs() & 0x0F
            seen = [start]
            deadline = time.time() + 1.0
            while time.time() < deadline:
                time.sleep(0.05)
                cur = eio.read_inputs() & 0x0F
                seen.append(cur)
                if cur != start:
                    return
            self.fail(f"slow EIO counter did not advance: samples={seen}")
        finally:
            eio.close()

    def test_outputs_roundtrip_and_stay_independent(self):
        t = _make_transport()
        _manager_or_skip(t)
        t.close()
        # Both slots on one transport: each session caches the active slot.
        t = _make_transport()
        eio0 = self._eio(t, 2, connect=True)
        try:
            eio1 = self._eio(t, 3, connect=False)
            for bit in range(8):
                eio0.write_outputs(1 << bit)
                self.assertEqual(eio0.read_outputs(), 1 << bit)
            eio0.write_outputs(0x15)  # LED1, LED3, LED5
            eio1.write_outputs(0x3C)
            self.assertEqual(eio0.read_outputs(), 0x15)
            self.assertEqual(eio1.read_outputs(), 0x3C)
            # EIO1's inputs are its own outputs.
            self.assertEqual(eio1.read_inputs(), 0x3C)
            eio1.write_outputs(0xC3)
            self.assertEqual(eio1.read_inputs(), 0xC3)
            eio0.write_outputs(0x00)
            eio1.write_outputs(0x00)
            self.assertEqual(eio0.read_outputs(), 0x00)
        finally:
            eio0.close()


if __name__ == "__main__":
    unittest.main()
