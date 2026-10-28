# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Hardware tests for the BRS-100-GW1NR9 core-manager variant
(brs_100_gw1nr9_manager_top.v), driven over OpenOCD.

One fcapz_debug_multi_gowin hub on GW_JTAG ER1 carries four slots: ELA0
(counter), ELA1 (counter XOR 0xA5), EIO0 (buttons + a slow counter in, LEDs
out) and EIO1 (outputs looped back to its inputs).  The Gowin hub has no
burst path, so every capture is read through the register window.

Build and load the variant, then start OpenOCD:

    python examples/brs_100_gw1nr9/build.py --variant manager
    # program out_manager/fcapz_brs_100_gw1nr9_manager.fs with your Gowin flow
    openocd -f examples/brs_100_gw1nr9/brs_100_gw1nr9.cfg

Environment variables are those of test_hw_integration.py: FPGACAP_SKIP_HW,
FPGACAP_OPENOCD_PORT and FPGACAP_OPENOCD_TAP.

Run:
    python -m pytest examples/brs_100_gw1nr9/test_hw_manager.py -v
"""

from __future__ import annotations

import os
import time
import unittest

_SKIP = os.environ.get("FPGACAP_SKIP_HW", "")
_PORT = int(os.environ.get("FPGACAP_OPENOCD_PORT", "6666"))
_TAP = os.environ.get("FPGACAP_OPENOCD_TAP", "GW1NR-9C.tap")

MANAGER_CHAIN = 1
DEPTH = 64
EIO_CORE_ID = 0x494F


def _make_transport():
    from fcapz.transport import OpenOcdTransport

    return OpenOcdTransport(
        host="127.0.0.1",
        port=_PORT,
        tap=_TAP,
        ir_table=OpenOcdTransport.IR_TABLE_GOWIN,
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
        raise unittest.SkipTest(
            f"OpenOCD not reachable on port {_PORT} ({exc}); "
            "start: openocd -f examples/brs_100_gw1nr9/brs_100_gw1nr9.cfg"
        )
    manager = ElaManager(t, chain=MANAGER_CHAIN)
    try:
        info = manager.probe()
    except RuntimeError as exc:
        t.close()
        raise unittest.SkipTest(f"no core manager on ER1 ({exc}); load the manager variant")
    if info["core_id"] != CORE_MANAGER_CORE_ID:
        t.close()
        raise unittest.SkipTest("ER1 holds no core manager; load the manager variant")
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
                self.assertEqual(slot["depth"], DEPTH)
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
                # No burst header (bit 4), no Test-Logic-Reset reset (bit 6).
                self.assertEqual(t.read_reg(ADDR_MGR_CAPS), 0xAF)
                # GW_JTAG's Test-Logic-Reset is not used: the count stays 0.
                self.assertEqual(t.read_reg(ADDR_MGR_TLR_COUNT), 0)
                bursts = []
                for slot in range(4):
                    t.write_reg(ADDR_MGR_DESC_INDEX, slot)
                    bursts.append(t.read_reg(ADDR_MGR_DESC_CAPS))
                # Register-only hub: no slot offers a burst.
                self.assertEqual(bursts, [0, 0, 0, 0])
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
    """Managed ELA captures read back through the register window."""

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
                depth=DEPTH,
            ))
            a.force_idle()
            a.arm()
            return a.capture(timeout=5.0)
        finally:
            a.close()

    def test_first_ela_captures_counter(self):
        result = self._capture(0, 0x40, 4, 8)
        samples = [s & 0xFF for s in result.samples]
        self.assertEqual(len(samples), 13)
        self.assertEqual(_counter_errors(samples), [], samples)
        self.assertEqual(samples[4], 0x40)

    def test_second_ela_captures_xored_counter(self):
        result = self._capture(1, 0xA5, 4, 8)
        samples = [s & 0xFF for s in result.samples]
        self.assertEqual(_counter_errors([s ^ 0xA5 for s in samples]), [], samples)
        self.assertEqual(samples[4], 0xA5)

    def test_full_depth_capture(self):
        result = self._capture(0, 0x10, 8, DEPTH - 9)
        samples = [s & 0xFF for s in result.samples]
        self.assertEqual(len(samples), DEPTH)
        self.assertEqual(_counter_errors(samples), [], samples[:32])
        self.assertEqual(samples[8], 0x10)

    def test_alternating_slots(self):
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
                    sample_width=8, depth=DEPTH,
                ))
                ela0.force_idle()
                ela0.arm()
                r0 = ela0.capture(timeout=5.0)
                self.assertEqual(r0.samples[2] & 0xFF, 0x20 + rnd)

                ela1.configure(CaptureConfig(
                    pretrigger=2, posttrigger=5,
                    trigger=TriggerConfig(mode="value_match", value=0xA5, mask=0xFF),
                    sample_width=8, depth=DEPTH,
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
            eio0.write_outputs(0x15)  # LED0, LED2, LED4
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
