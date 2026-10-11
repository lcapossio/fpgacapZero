# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host side of the core manager's reset registers: burst header, epochs and
the MGR_OWNER token."""

from __future__ import annotations

import types
import unittest

from fcapz.analyzer import Analyzer
from fcapz.registers import (
    ADDR_MGR_EPOCH,
    ADDR_MGR_OWNER,
    ADDR_MGR_SLOT_EPOCH,
)
from fcapz.transport import (
    BurstHeader,
    BurstIntegrityError,
    Transport,
    XilinxHwServerTransport,
)


def make_header(*, slot=1, start_ptr=0x2A, timestamp=False, mgr_epoch=3,
                slot_epoch=5, owner=0x1234, sample_w=8) -> int:
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
            BurstHeader(slot=1, start_ptr=0x2A, timestamp=True, mgr_epoch=3,
                        slot_epoch=5, owner=0x1234, sample_w=8),
        )

    def test_rejects_other_scans(self):
        self.assertIsNone(BurstHeader.parse(0))
        self.assertIsNone(BurstHeader.parse(make_header() ^ 1))  # magic
        self.assertIsNone(BurstHeader.parse(make_header() | (1 << 70)))  # reserved
        self.assertIsNone(BurstHeader.parse(make_header() | (1 << 200)))  # past the header


class HwServerHeaderCheckTests(unittest.TestCase):
    """The priming scan of a hub burst is checked against the expected slot."""

    def setUp(self):
        self.t = XilinxHwServerTransport()
        self.t._burst_sample_width = lambda: 8
        data = sum(i << (8 * i) for i in range(32))
        self.output = f"{lsb_first(make_header())} {lsb_first(data)}"

    def parse(self, header_timestamp=False):
        return self.t._parse_burst_bits(
            self.output, 4, skip_scans=1, header_timestamp=header_timestamp
        )

    def test_matching_header_is_kept(self):
        self.t.burst_header_slot = 1
        self.assertEqual(self.parse(), [0, 1, 2, 3])
        self.assertEqual(self.t.last_burst_header.slot_epoch, 5)

    def test_other_slot_raises(self):
        self.t.burst_header_slot = 0
        with self.assertRaisesRegex(BurstIntegrityError, "slot 1"):
            self.parse()

    def test_other_window_raises(self):
        self.t.burst_header_slot = 1
        with self.assertRaisesRegex(BurstIntegrityError, "timestamps"):
            self.parse(header_timestamp=True)

    def test_missing_header_raises(self):
        self.t.burst_header_slot = 1
        self.output = f"{lsb_first(0)} {self.output.split()[1]}"
        with self.assertRaisesRegex(BurstIntegrityError, "not a burst header"):
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
        self.t.regs[ADDR_MGR_EPOCH] = 3
        self.t.regs[ADDR_MGR_SLOT_EPOCH] = 5
        self.analyzer = types.SimpleNamespace(transport=self.t)
        self.header = BurstHeader.parse(make_header())

    def test_unchanged_epochs_pass(self):
        Analyzer._check_burst_epochs(self.analyzer, self.header)
        self.assertEqual(self.t.regs[0xF014], 1)  # DESC_INDEX on the burst's slot

    def test_slot_reset_during_burst_raises(self):
        self.t.regs[ADDR_MGR_SLOT_EPOCH] = 6
        with self.assertRaisesRegex(BurstIntegrityError, "reset during the burst"):
            Analyzer._check_burst_epochs(self.analyzer, self.header)

    def test_hub_reset_during_burst_raises(self):
        self.t.regs[ADDR_MGR_EPOCH] = 4
        with self.assertRaisesRegex(BurstIntegrityError, "reset during the burst"):
            Analyzer._check_burst_epochs(self.analyzer, self.header)


if __name__ == "__main__":
    unittest.main()
