# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host side of the core manager's reset registers: burst header, epochs,
MGR_TLR_COUNT and the MGR_OWNER token."""

from __future__ import annotations

import types
import unittest

from fcapz import _version_tuple
from fcapz.analyzer import (
    CORE_MANAGER_CORE_ID,
    Analyzer,
    CaptureChangedError,
    CaptureConfig,
    ManagerResetError,
    TriggerConfig,
)
from fcapz.eio import EioController
from fcapz.registers import (
    ADDR_MGR_EPOCH,
    ADDR_MGR_OWNER,
    ADDR_MGR_SELECT_COUNT,
    ADDR_MGR_SLOT_EPOCH,
    ADDR_MGR_TLR_COUNT,
)
from fcapz.transport import (
    BurstExpectation,
    BurstHeader,
    BurstIntegrityError,
    Transport,
    XilinxHwServerTransport,
)
from fcapz.transport import ManagerResetError as TransportManagerResetError


def make_header(*, slot=1, start_ptr=0x2A, timestamp=False, mgr_epoch=4,
                slot_epoch=6, owner=0x1234, sample_w=8) -> int:
    return (
        BurstHeader.MAGIC
        | (slot << 16)
        | (start_ptr << 32)
        | (int(timestamp) << 64)
        | (mgr_epoch << 80)
        | (slot_epoch << 96)
        | (owner << 112)
        | (sample_w << 144)
    )


def lsb_first(value: int, width: int = 256) -> str:
    return "".join("1" if (value >> i) & 1 else "0" for i in range(width))


class BurstHeaderTests(unittest.TestCase):
    def test_parse_fields(self):
        header = BurstHeader.parse(make_header(timestamp=True))
        self.assertEqual(
            header,
            BurstHeader(slot=1, start_ptr=0x2A, timestamp=True, mgr_epoch=4,
                        slot_epoch=6, owner=0x1234, sample_w=8),
        )

    def test_rejects_other_scans(self):
        self.assertIsNone(BurstHeader.parse(0))
        self.assertIsNone(BurstHeader.parse(make_header() ^ 1))  # magic
        self.assertIsNone(BurstHeader.parse(make_header() | (1 << 70)))  # reserved
        self.assertIsNone(BurstHeader.parse(make_header() | (1 << 200)))  # past the header


class HwServerHeaderCheckTests(unittest.TestCase):
    """The priming scan of a hub burst is checked against what the analyzer
    read before it: slot, window, start pointer, sample width, reset state."""

    def setUp(self):
        self.t = XilinxHwServerTransport()
        self.t._burst_sample_width = lambda: 8
        self.data = lsb_first(sum(i << (8 * i) for i in range(32)))
        self.set_header()

    def set_header(self, **fields):
        self.output = f"{lsb_first(make_header(**fields))} {self.data}"

    def parse(self, header_timestamp=False):
        return self.t._parse_burst_bits(
            self.output, 4, skip_scans=1, header_timestamp=header_timestamp
        )

    def test_matching_header_is_kept(self):
        self.t.burst_expect = BurstExpectation(1, 0x2A, 8)
        self.assertEqual(self.parse(), [0, 1, 2, 3])
        self.assertEqual(self.t.last_burst_header.slot_epoch, 6)

    def test_other_slot_raises(self):
        self.t.burst_expect = BurstExpectation(0, 0x2A, 8)
        with self.assertRaisesRegex(BurstIntegrityError, "slot 1"):
            self.parse()

    def test_other_window_raises(self):
        self.t.burst_expect = BurstExpectation(1, 0x2A, 8)
        with self.assertRaisesRegex(BurstIntegrityError, "timestamps"):
            self.parse(header_timestamp=True)

    def test_missing_header_raises(self):
        self.t.burst_expect = BurstExpectation(1, 0x2A, 8)
        self.output = f"{lsb_first(0)} {self.data}"
        with self.assertRaisesRegex(BurstIntegrityError, "not a burst header"):
            self.parse()

    def test_other_start_pointer_raises(self):
        """A re-arm or a SEG_SEL write between the analyzer's reads and the
        burst moves the start pointer (BUG-232)."""
        self.t.burst_expect = BurstExpectation(1, 0x2B, 8)
        with self.assertRaisesRegex(BurstIntegrityError, "starts at sample 42"):
            self.parse()

    def test_other_sample_width_raises(self):
        self.t.burst_expect = BurstExpectation(1, 0x2A, 16)
        with self.assertRaisesRegex(BurstIntegrityError, "8-bit samples"):
            self.parse()

    def test_slot_held_in_reset_raises(self):
        """An odd slot epoch: the slot was held in reset as the burst started
        (BUG-235)."""
        self.t.burst_expect = BurstExpectation(1, 0x2A, 8)
        self.set_header(slot_epoch=7)
        with self.assertRaisesRegex(BurstIntegrityError, "held in reset"):
            self.parse()

    def test_other_owner_is_reported_not_refused(self):
        self.t.burst_expect = BurstExpectation(1, 0x2A, 8)
        self.t._fcapz_owner_token = 0x9999
        with self.assertLogs("fcapz.transport", level="WARNING") as logs:
            self.assertEqual(self.parse(), [0, 1, 2, 3])
        self.assertIn("0x00001234", logs.output[0])

    def test_own_or_no_owner_is_quiet(self):
        self.t.burst_expect = BurstExpectation(1, 0x2A, 8)
        self.t._fcapz_owner_token = 0x1234
        for owner in (0x1234, 0):
            self.set_header(owner=owner)
            with self.assertNoLogs("fcapz.transport", level="WARNING"):
                self.parse()

    def test_no_expectation_no_check(self):
        self.output = f"{lsb_first(0)} {self.output.split()[1]}"
        self.assertEqual(self.parse(), [0, 1, 2, 3])
        self.assertIsNone(self.t.last_burst_header)


class ManagerTransport(Transport):
    """One chain with an ELA behind a core manager."""

    def __init__(self, caps: int = 0x3F) -> None:
        self.regs = {0x0000: 0x0001_4C41, 0xF000: 0x434D, 0xF004: 2, 0xF008: 0,
                     0xF010: caps, ADDR_MGR_OWNER: 0}
        self.writes: list[tuple[int, int]] = []

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        pass

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.writes.append((addr, value))
        self.regs[addr] = value

    def read_block(self, addr: int, words: int) -> list[int]:
        return [0] * words


class OwnerTokenTests(unittest.TestCase):
    def test_claim_and_release(self):
        t = ManagerTransport()
        t.select_manager_instance_cached(1, 0xF008, 1)
        token = t.regs[ADDR_MGR_OWNER]
        self.assertNotEqual(token, 0)
        # Claimed once per chain, not on every slot switch.
        t.select_manager_instance_cached(1, 0xF008, 0)
        self.assertEqual([w for w in t.writes if w[0] == ADDR_MGR_OWNER], [(ADDR_MGR_OWNER, token)])
        t.release_manager_ownership()
        self.assertEqual(t.regs[ADDR_MGR_OWNER], 0)

    def test_foreign_token_is_reported_not_obeyed(self):
        t = ManagerTransport()
        t.regs[ADDR_MGR_OWNER] = 0xDEAD
        with self.assertLogs("fcapz.transport", level="WARNING") as logs:
            t.select_manager_instance_cached(1, 0xF008, 1)
        self.assertIn("0x0000DEAD", logs.output[0])
        self.assertEqual(t.regs[0xF008], 1)
        self.assertNotIn(t.regs[ADDR_MGR_OWNER], (0, 0xDEAD))

    def test_release_leaves_a_token_taken_since(self):
        t = ManagerTransport()
        t.select_manager_instance_cached(1, 0xF008, 1)
        t.regs[ADDR_MGR_OWNER] = 0xBEEF
        t.release_manager_ownership()
        self.assertEqual(t.regs[ADDR_MGR_OWNER], 0xBEEF)

    def test_manager_without_owner_register_is_not_written(self):
        t = ManagerTransport(caps=0x7)
        t.select_manager_instance_cached(1, 0xF008, 1)
        self.assertNotIn(ADDR_MGR_OWNER, [addr for addr, _ in t.writes])


class BurstEpochTests(unittest.TestCase):
    def setUp(self):
        self.t = ManagerTransport()
        self.t.regs[ADDR_MGR_EPOCH] = 4
        self.t.regs[ADDR_MGR_SLOT_EPOCH] = 6
        self.t.regs[ADDR_MGR_TLR_COUNT] = 9
        self.analyzer = types.SimpleNamespace(transport=self.t)
        self.header = BurstHeader.parse(make_header())

    def test_unchanged_epochs_pass(self):
        Analyzer._check_burst_epochs(self.analyzer, self.header)
        self.assertEqual(self.t.regs[0xF014], 1)  # DESC_INDEX on the burst's slot

    def test_slot_reset_during_burst_raises(self):
        self.t.regs[ADDR_MGR_SLOT_EPOCH] = 8
        with self.assertRaisesRegex(BurstIntegrityError, "reset during the burst"):
            Analyzer._check_burst_epochs(self.analyzer, self.header)

    def test_hub_reset_during_burst_raises(self):
        self.t.regs[ADDR_MGR_EPOCH] = 5
        with self.assertRaisesRegex(BurstIntegrityError, "reset during the burst"):
            Analyzer._check_burst_epochs(self.analyzer, self.header)

    def test_test_logic_reset_during_burst_raises(self):
        """On a hub whose Test-Logic-Reset cancels bursts, a cancel after the
        priming scan leaves a valid header: only MGR_TLR_COUNT shows it
        (BUG-230)."""
        expect = BurstExpectation(1, 0x2A, 8, tlr_count=8)
        with self.assertRaisesRegex(BurstIntegrityError, "Test-Logic-Reset"):
            Analyzer._check_burst_epochs(self.analyzer, self.header, expect)

    def test_unchanged_tlr_count_passes(self):
        expect = BurstExpectation(1, 0x2A, 8, tlr_count=9)
        Analyzer._check_burst_epochs(self.analyzer, self.header, expect)

    def test_no_tlr_baseline_reads_no_tlr_count(self):
        reads = []
        read = self.t.read_reg
        self.t.read_reg = lambda addr: reads.append(addr) or read(addr)
        Analyzer._check_burst_epochs(self.analyzer, self.header, BurstExpectation(1, 0x2A, 8))
        self.assertNotIn(ADDR_MGR_TLR_COUNT, reads)


_SEG_START = 0x00C8
_CAPTURE_GEN = 0x00F8


class EpochElaTransport(Transport):
    """8-bit ELAs behind a core manager with epochs (MGR_CAPS bit 3).  Every
    slot reads the same registers; ``slots`` sets MGR_COUNT.

    ``hooks`` maps a register address to a function run when that address is
    written (or, for the DATA window, read): tests reset the slot there.
    With ``capture_gen`` the ELA has CAPTURE_GEN (COMPARE_CAPS bit 21).
    """

    def __init__(self, *, caps: int = 0x0B, slot_caps: int = 0, bursting: bool = False,
                 slots: int = 1, capture_gen: bool = False):
        ver = ((_version_tuple()[0] & 0xFF) << 24) | ((_version_tuple()[1] & 0xFF) << 16)
        self.regs = {
            0x0000: ver | 0x4C41, 0x0008: 0x4, 0x000C: 8, 0x0010: 16,
            0x001C: 4, 0x003C: 0x0001_0164, 0x00A4: 1, 0x00B8: 1,
            0x00C4: 0, 0x00E0: 0x3_01FF, _SEG_START: 0x2A,
        }
        self.manager = {
            0xF000: ver | CORE_MANAGER_CORE_ID, 0xF004: slots, 0xF008: 0,
            0xF00C: 0, 0xF010: caps, 0xF014: 0, 0xF01C: slot_caps,
            ADDR_MGR_EPOCH: 2, ADDR_MGR_SLOT_EPOCH: 2, ADDR_MGR_TLR_COUNT: 0,
            ADDR_MGR_SELECT_COUNT: 0xFFF0,  # other controllers' selects; wraps
        }
        if capture_gen:
            self.regs[0x00E0] |= 1 << 21
            self.regs[_CAPTURE_GEN] = 0xFFFE  # wraps during the tests
        self.bursting = bursting
        self.hooks: dict[int, object] = {}
        self.reads: list[int] = []
        self.expectations: list[BurstExpectation | None] = []

    def connect(self):
        return None

    def close(self):
        return None

    def select_chain(self, chain):
        return None

    def reset_slot(self, edges: int = 2) -> None:
        self.manager[ADDR_MGR_SLOT_EPOCH] += edges

    def foreign_select(self, slot: int, back: int | None = None) -> None:
        """Another controller selects *slot*, then *back* if given."""
        for value in (slot,) if back is None else (slot, back):
            self.manager[ADDR_MGR_SELECT_COUNT] = (
                self.manager[ADDR_MGR_SELECT_COUNT] + 1) & 0xFFFF
            self.manager[0xF008] = value

    def rearm(self) -> None:
        """Another controller's CTRL arm."""
        self.regs[_CAPTURE_GEN] = (self.regs[_CAPTURE_GEN] + 1) & 0xFFFF

    def reset_hub(self) -> None:
        """MGR_CTRL bit 0: MGR_ACTIVE back to 0, no slot reset."""
        self.manager[ADDR_MGR_EPOCH] += 2
        self.manager[0xF008] = 0

    def read_reg(self, addr):
        self.reads.append(addr)
        if addr in self.manager:
            return self.manager[addr]
        if 0x0100 <= addr < 0xF000:
            return self.read_window_block(addr, 1)[0]
        return self.regs.get(addr, 0)

    def write_reg(self, addr, value):
        hook = self.hooks.pop(addr, None)
        if hook is not None:
            hook()
        if addr == 0xF008:
            self.manager[ADDR_MGR_SELECT_COUNT] = (
                self.manager[ADDR_MGR_SELECT_COUNT] + 1) & 0xFFFF
        if addr in self.manager:
            self.manager[addr] = value
        else:
            self.regs[addr] = value
        if addr == 0x0004 and value & 0x3 and _CAPTURE_GEN in self.regs:
            self.rearm()

    def bursts_data_window(self, *, timestamp=False):
        return self.bursting

    def read_block(self, addr, words):
        if addr == 0x0100 and self.bursting:
            self.expectations.append(self.burst_expect)
        return self.read_window_block(addr, words)

    def read_window_block(self, addr, words):
        hook = self.hooks.pop(0x0100, None)
        if hook is not None:
            hook()
        first = (addr - 0x0100) // 4
        return list(range(first, first + words))


def epoch_config() -> CaptureConfig:
    return CaptureConfig(
        pretrigger=1, posttrigger=2,
        trigger=TriggerConfig(mode="value_match", value=7, mask=0xFF),
        sample_width=8, depth=16,
    )


class SlotEpochAcrossCaptureTests(unittest.TestCase):
    """A slot reset between configure() and the end of the readout puts the
    ELA back at its build defaults: the analyzer refuses, it does not return
    a capture of a configuration the core no longer holds (BUG-234)."""

    def setUp(self):
        self.t = EpochElaTransport()
        self.a = Analyzer(self.t, instance=0)
        self.a.connect()

    def test_clean_capture_passes(self):
        self.a.configure(epoch_config())
        self.a.arm()
        self.assertEqual(self.a.capture(timeout=0.01).samples, [0, 1, 2, 3])

    def test_configure_refuses_a_slot_held_in_reset(self):
        self.t.manager[ADDR_MGR_SLOT_EPOCH] = 3
        with self.assertRaisesRegex(ManagerResetError, "held in reset"):
            self.a.configure(epoch_config())

    def test_reset_during_configure_raises(self):
        self.t.hooks[0x0024] = self.t.reset_slot  # TRIG_VALUE
        with self.assertRaisesRegex(ManagerResetError, "while it was configured"):
            self.a.configure(epoch_config())

    def test_reset_before_arm_raises(self):
        self.a.configure(epoch_config())
        self.t.reset_slot()
        with self.assertRaisesRegex(ManagerResetError, "call configure"):
            self.a.arm()

    def test_reset_before_readout_raises(self):
        self.a.configure(epoch_config())
        self.a.arm()
        self.t.reset_slot()
        with self.assertRaisesRegex(ManagerResetError, "before the readout"):
            self.a.capture(timeout=0.01)

    def test_reset_during_readout_raises(self):
        self.a.configure(epoch_config())
        self.a.arm()
        self.t.hooks[0x0100] = self.t.reset_slot
        with self.assertRaisesRegex(ManagerResetError, "during the readout"):
            self.a.capture(timeout=0.01)

    def test_failed_configure_leaves_no_config(self):
        """A configure that raises may have written part of the new config:
        the old one is not kept to arm and read unchecked (BUG-239)."""
        self.a.configure(epoch_config())
        self.t.hooks[0x0024] = self.t.reset_slot
        with self.assertRaises(ManagerResetError):
            self.a.configure(epoch_config())
        with self.assertRaisesRegex(RuntimeError, "configure"):
            self.a.capture(timeout=0.01)

    def test_reset_while_waiting_is_reported_not_timed_out(self):
        """A slot reset clears DONE, so the wait would time out (BUG-244)."""
        self.a.configure(epoch_config())
        self.a.arm()
        self.t.regs[0x0008] = 0  # STATUS: reset, not done
        self.t.reset_slot()
        with self.assertRaisesRegex(ManagerResetError, "while waiting"):
            self.a.capture(timeout=0.01)

    def test_plain_timeout_still_times_out(self):
        self.a.configure(epoch_config())
        self.a.arm()
        self.t.regs[0x0008] = 0
        with self.assertRaises(TimeoutError):
            self.a.capture(timeout=0.01)

    def test_capture_moved_during_readout_raises(self):
        """Another session's SEG_SEL, or a re-arm, moves SEG_START: samples and
        timestamps would come from different captures (BUG-242)."""
        self.a.configure(epoch_config())
        self.a.arm()

        def move():
            self.t.regs[_SEG_START] = 0x30

        self.t.hooks[0x0100] = move
        with self.assertRaisesRegex(CaptureChangedError, "SEG_START"):
            self.a.capture(timeout=0.01)


class HubResetTests(unittest.TestCase):
    """A hub reset (MGR_CTRL bit 0) resets no slot but moves MGR_ACTIVE to 0:
    reads after it, until the next select, go to slot 0 (BUG-240)."""

    def setUp(self):
        self.t = EpochElaTransport(slots=2)
        self.a = Analyzer(self.t, instance=1)
        self.a.connect()
        self.a.configure(epoch_config())
        self.a.arm()

    def test_hub_reset_before_readout_reselects_the_slot(self):
        self.t.reset_hub()
        self.assertEqual(self.a.capture(timeout=0.01).samples, [0, 1, 2, 3])
        self.assertEqual(self.t.manager[0xF008], 1)

    def test_hub_reset_during_readout_raises(self):
        self.t.hooks[0x0100] = self.t.reset_hub
        with self.assertRaisesRegex(ManagerResetError, "during the readout"):
            self.a.capture(timeout=0.01)
        # The next select reads MGR_ACTIVE back: the retry reads slot 1.
        self.assertEqual(self.a.capture(timeout=0.01).samples, [0, 1, 2, 3])
        self.assertEqual(self.t.manager[0xF008], 1)

    def test_hub_reset_during_configure_raises(self):
        self.t.hooks[0x0024] = self.t.reset_hub
        with self.assertRaisesRegex(ManagerResetError, "active slot is 0.*hub was reset"):
            self.a.configure(epoch_config())


class UnboundSlotTests(unittest.TestCase):
    """With no instance the analyzer reads the hub's active slot: the
    baseline records which one (BUG-241)."""

    def setUp(self):
        self.t = EpochElaTransport(slots=2)
        self.a = Analyzer(self.t)
        self.a.connect()
        self.a.configure(epoch_config())

    def test_other_active_slot_with_the_same_epoch_raises(self):
        self.t.manager[0xF008] = 1
        with self.assertRaisesRegex(ManagerResetError, "active slot is 1"):
            self.a.arm()

    def test_same_slot_passes(self):
        self.a.arm()
        self.a.capture(timeout=0.01)

    def test_configure_again_recovers(self):
        self.a.configure(epoch_config())
        self.t.reset_slot()
        self.a.configure(epoch_config())
        self.a.arm()
        self.a.capture(timeout=0.01)

    def test_manager_without_epochs_reads_none(self):
        t = EpochElaTransport(caps=0x03)
        a = Analyzer(t, instance=0)
        a.connect()
        a.configure(epoch_config())
        a.arm()
        a.capture(timeout=0.01)
        self.assertNotIn(ADDR_MGR_SLOT_EPOCH, t.reads)


class TlrAcrossReadoutTests(unittest.TestCase):
    """On a hub whose Test-Logic-Reset resets the JTAG protocol (MGR_CAPS bit
    6), one during a readout may have dropped a register command: the
    analyzer refuses the capture (BUG-230)."""

    def run_capture(self, caps):
        t = EpochElaTransport(caps=caps)
        a = Analyzer(t, instance=0)
        a.connect()
        a.configure(epoch_config())
        a.arm()

        def tlr():
            t.manager[ADDR_MGR_TLR_COUNT] += 1

        t.hooks[0x0100] = tlr
        return t, lambda: a.capture(timeout=0.01)

    def test_tlr_during_readout_raises(self):
        _, capture = self.run_capture(0x4B)
        with self.assertRaisesRegex(ManagerResetError, "Test-Logic-Reset"):
            capture()

    def test_tlr_is_harmless_without_cap(self):
        t, capture = self.run_capture(0x0B)
        capture()
        self.assertNotIn(ADDR_MGR_TLR_COUNT, t.reads)


class BurstExpectationSetupTests(unittest.TestCase):
    """The analyzer gives a header-checking burst the slot, SEG_START and
    SAMPLE_W it reads just before, and the TLR baseline where it matters."""

    def expectation(self, caps):
        t = EpochElaTransport(caps=caps, slot_caps=1, bursting=True)
        t.manager[ADDR_MGR_TLR_COUNT] = 5
        a = Analyzer(t, instance=0)
        a.connect()
        a.configure(epoch_config())
        a.arm()
        a.capture(timeout=0.01)
        self.assertIsNone(t.burst_expect)  # not inherited by a later burst
        return t.expectations

    def test_header_hub(self):
        self.assertEqual(self.expectation(0x1B), [BurstExpectation(0, 0x2A, 8, None)])

    def test_header_hub_with_protocol_tlr(self):
        self.assertEqual(self.expectation(0x5B), [BurstExpectation(0, 0x2A, 8, 5)])

    def test_hub_without_header(self):
        self.assertEqual(self.expectation(0x0B), [None])


if __name__ == "__main__":
    unittest.main()


class CaptureGenerationTests(unittest.TestCase):
    """CAPTURE_GEN tells the analyzer that the capture it reads is the one it
    armed, and that no arm or reset hit it during the readout: SEG_START
    alone does not, since a re-arm can leave it where it was (BUG-246)."""

    def analyzer(self, *, managed: bool, capture_gen: bool = True, **kw) -> Analyzer:
        self.t = EpochElaTransport(capture_gen=capture_gen, **kw)
        a = Analyzer(self.t, manager=managed)
        a.connect()
        a.configure(epoch_config())
        return a

    def test_capture_passes(self):
        for managed in (False, True):
            with self.subTest(managed=managed):
                a = self.analyzer(managed=managed)
                a.arm()
                self.assertEqual(a.capture(timeout=0.01).samples, [0, 1, 2, 3])
                # Read again: still the capture this analyzer armed.
                self.assertEqual(a.capture(timeout=0.01).samples, [0, 1, 2, 3])

    def test_rearm_during_readout_raises(self):
        for managed in (False, True):
            with self.subTest(managed=managed):
                a = self.analyzer(managed=managed)
                a.arm()
                self.t.hooks[0x0100] = self.t.rearm
                with self.assertRaisesRegex(CaptureChangedError, "during the readout"):
                    a.capture(timeout=0.01)

    def test_rearm_since_arm_raises(self):
        """Another controller armed again after this analyzer did: the
        capture there is theirs, even with SEG_START unchanged."""
        a = self.analyzer(managed=False)
        a.arm()
        self.t.rearm()
        with self.assertRaisesRegex(CaptureChangedError, "since arm"):
            a.capture(timeout=0.01)

    def test_concurrent_arm_raises_at_arm(self):
        a = self.analyzer(managed=False)
        self.t.hooks[0x0004] = self.t.rearm
        with self.assertRaisesRegex(CaptureChangedError, "across this arm"):
            a.arm()
        # Not this analyzer's capture: nothing to compare with, so a capture
        # read now is only checked during its readout.
        self.assertEqual(a.capture(timeout=0.01).samples, [0, 1, 2, 3])

    def test_own_reset_is_not_a_foreign_capture(self):
        a = self.analyzer(managed=False)
        a.arm()
        a.reset()
        self.assertEqual(a.capture(timeout=0.01).samples, [0, 1, 2, 3])

    def test_every_segment_of_one_capture(self):
        a = self.analyzer(managed=False)
        self.t.regs[0x00B8] = 2  # NUM_SEGMENTS
        a.configure(epoch_config())
        a.arm()
        for seg in (0, 1):
            self.assertEqual(a.capture_segment(seg, timeout=0.01).segment, seg)

    def test_slot_reset_is_reported_as_one(self):
        """A slot reset also moves CAPTURE_GEN; the epoch says more."""
        a = self.analyzer(managed=True)
        a.arm()

        def reset():
            self.t.reset_slot()
            self.t.rearm()

        self.t.hooks[0x0100] = reset
        with self.assertRaises(ManagerResetError):
            a.capture(timeout=0.01)

    def test_core_without_capture_gen_is_not_read(self):
        a = self.analyzer(managed=False, capture_gen=False)
        a.arm()
        a.capture(timeout=0.01)
        self.assertNotIn(_CAPTURE_GEN, self.t.reads)


class ForeignSelectTests(unittest.TestCase):
    """Another controller's select and select back between an analyzer's own
    accesses send some of them to another slot and leave MGR_ACTIVE as it
    was; MGR_SELECT_COUNT (MGR_CAPS bit 7) less the transport's own selects
    says one happened (BUG-245)."""

    def setUp(self):
        self.t = EpochElaTransport(caps=0x8B, slots=2)
        self.a = Analyzer(self.t, instance=1)
        self.a.connect()

    def test_select_and_back_during_readout_raises(self):
        self.a.configure(epoch_config())
        self.a.arm()
        self.t.hooks[0x0100] = lambda: self.t.foreign_select(0, back=1)
        with self.assertRaisesRegex(ManagerResetError, "during the readout"):
            self.a.capture(timeout=0.01)

    def test_select_and_back_during_configure_raises(self):
        self.t.hooks[0x0024] = lambda: self.t.foreign_select(0, back=1)
        with self.assertRaisesRegex(ManagerResetError, "while it was configured"):
            self.a.configure(epoch_config())

    def test_select_and_back_during_arm_raises(self):
        self.a.configure(epoch_config())
        self.t.hooks[0x0004] = lambda: self.t.foreign_select(0, back=1)
        with self.assertRaisesRegex(ManagerResetError, "during arm"):
            self.a.arm()

    def test_select_left_elsewhere_raises(self):
        self.a.configure(epoch_config())
        self.a.arm()
        self.t.hooks[0x0100] = lambda: self.t.foreign_select(0)
        # The readout's own select (for the timestamps) moves it back; the
        # count still differs.
        with self.assertRaisesRegex(ManagerResetError, "during the readout"):
            self.a.capture(timeout=0.01)

    def test_selects_between_operations_pass(self):
        """Other controllers may use the hub between this analyzer's calls:
        each call selects its slot again."""
        self.a.configure(epoch_config())
        self.t.foreign_select(0)
        self.a.arm()
        self.t.foreign_select(0)
        self.assertEqual(self.a.capture(timeout=0.01).samples, [0, 1, 2, 3])

    def test_analyzers_sharing_the_transport_are_not_foreign(self):
        other = Analyzer(self.t, instance=0)
        other.connect()
        for a in (self.a, other, self.a):
            a.configure(epoch_config())
        for a in (other, self.a, other):
            a.arm()
            self.assertEqual(a.capture(timeout=0.01).samples, [0, 1, 2, 3])

    def test_hub_without_select_count_is_not_read(self):
        t = EpochElaTransport(caps=0x0B, slots=2)
        a = Analyzer(t, instance=1)
        a.connect()
        a.configure(epoch_config())
        a.arm()
        a.capture(timeout=0.01)
        self.assertNotIn(ADDR_MGR_SELECT_COUNT, t.reads)


class ManagedEioTransport(Transport):
    """Two EIO slots behind a core manager.  MGR_SELECT_COUNT counts every
    MGR_ACTIVE write; ``hooks`` run another controller's accesses just
    before a slot register access."""

    def __init__(self, caps: int = 0x8B) -> None:
        self.manager = {
            0xF000: CORE_MANAGER_CORE_ID, 0xF004: 2, 0xF008: 0, 0xF010: caps,
            ADDR_MGR_OWNER: 0, ADDR_MGR_SELECT_COUNT: 0xFFFE,
        }
        self.slots = [
            {0x0000: 0x0001_494F, 0x0004: 8, 0x0008: 8, 0x0010: 0x11, 0x0100: 0},
            {0x0000: 0x0001_494F, 0x0004: 8, 0x0008: 8, 0x0010: 0x22, 0x0100: 0},
        ]
        self.hooks: dict = {}
        self.reads: list[int] = []

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        pass

    def _hook(self, addr: int) -> None:
        hook = self.hooks.pop(addr, None)
        if hook is not None:
            hook()

    def read_reg(self, addr: int) -> int:
        self._hook(addr)
        self.reads.append(addr)
        if addr >= 0xF000:
            return self.manager.get(addr, 0)
        return self.slots[self.manager[0xF008]].get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self._hook(addr)
        if addr == 0xF008:
            self.manager[ADDR_MGR_SELECT_COUNT] = (
                self.manager[ADDR_MGR_SELECT_COUNT] + 1) & 0xFFFF
            if value < 2:
                self.manager[addr] = value
        elif addr >= 0xF000:
            self.manager[addr] = value
        else:
            self.slots[self.manager[0xF008]][addr] = value

    def read_block(self, addr: int, words: int) -> list[int]:
        return [self.read_reg(addr + 4 * i) for i in range(words)]

    def foreign_select(self, slot: int, back: int | None = None) -> None:
        """Another controller selects *slot*, then *back* if given."""
        for value in (slot,) if back is None else (slot, back):
            self.manager[ADDR_MGR_SELECT_COUNT] = (
                self.manager[ADDR_MGR_SELECT_COUNT] + 1) & 0xFFFF
            self.manager[0xF008] = value


class ManagedEioSlotTests(unittest.TestCase):
    """Another controller's select, or a hub reset, during a managed EIO's
    access sends some of it to another slot (BUG-222)."""

    def setUp(self):
        self.t = ManagedEioTransport()
        self.eio = EioController(self.t, chain=1, instance=1)
        self.eio.connect()

    def test_error_is_shared_with_the_analyzer(self):
        self.assertIs(ManagerResetError, TransportManagerResetError)

    def test_select_and_back_during_read_raises(self):
        self.t.hooks[0x0010] = lambda: self.t.foreign_select(0, back=1)
        with self.assertRaisesRegex(
                ManagerResetError, "2 time.*during an access to slot 1"):
            self.eio.read_inputs()

    def test_select_left_elsewhere_during_write_raises(self):
        self.t.hooks[0x0100] = lambda: self.t.foreign_select(0)
        with self.assertRaisesRegex(ManagerResetError, "during an access"):
            self.eio.write_outputs(0x5A)
        self.assertEqual(self.t.slots[0][0x0100], 0x5A)  # the write went astray

    def test_hub_reset_during_read_raises_without_select_count(self):
        t = ManagedEioTransport(caps=0x0B)
        eio = EioController(t, chain=1, instance=1)
        eio.connect()
        t.hooks[0x0010] = lambda: t.manager.__setitem__(0xF008, 0)
        with self.assertRaisesRegex(ManagerResetError, "is 0, not 1"):
            eio.read_inputs()
        self.assertNotIn(ADDR_MGR_SELECT_COUNT, t.reads)

    def test_select_and_back_during_connect_raises(self):
        t = ManagedEioTransport()
        eio = EioController(t, chain=1, instance=1)
        t.hooks[0x0004] = lambda: t.foreign_select(0, back=1)
        with self.assertRaisesRegex(ManagerResetError, "during an access"):
            eio.connect()

    def test_selects_between_accesses_pass(self):
        """Each access selects its slot again, so other controllers may use
        the hub between them."""
        self.t.foreign_select(0)
        self.assertEqual(self.eio.read_inputs(), 0x22)
        self.t.foreign_select(0, back=1)
        self.eio.write_outputs(0xA5)
        self.assertEqual(self.t.slots[1][0x0100], 0xA5)
        self.assertEqual(self.eio.read_outputs(), 0xA5)

    def test_controllers_sharing_the_transport_are_not_foreign(self):
        other = EioController(self.t, chain=1, instance=0)
        other.attach()
        for _ in range(3):
            self.assertEqual(self.eio.read_inputs(), 0x22)
            self.assertEqual(other.read_inputs(), 0x11)
        self.eio.set_bit(3, 1)
        other.set_bit(4, 1)
        self.assertEqual(
            (self.t.slots[1][0x0100], self.t.slots[0][0x0100]), (0x08, 0x10))

    def test_direct_eio_is_not_checked(self):
        t = ManagedEioTransport()
        eio = EioController(t, chain=1)
        eio.connect()
        t.reads.clear()
        eio.read_inputs()
        self.assertEqual(t.reads, [0x0010])
