# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Per-operation core-manager slot selection (Transport.slot_scope).

A second process on the same cable (a GUI next to a CLI, two MCP clients)
can write MGR_ACTIVE between any two backend operations.  On hw_server each
access in a slot scope carries its own MGR_ACTIVE write in the same
``jtag sequence``, so it reaches its slot regardless.
"""

from __future__ import annotations

import re
import threading
import unittest

from fcapz.analyzer import Analyzer, CoreManager
from fcapz.eio import EioController
from fcapz.transport import SlotSelection, Transport, XilinxHwServerTransport

_MGR_ACTIVE = 0xF008
_DESC_INDEX = 0xF014
_DESC_CORE = 0xF018
_DESC_CAPS = 0xF01C
_ELA = 0x0001_4C41
_EIO = 0x0001_494F


def _int_lsb(bits: str) -> int:
    return sum(1 << i for i, b in enumerate(bits) if b == "1")


class FakeManagedXsdb:
    """xsdb running ``jtag sequence`` scans against a 4-slot core manager
    (slots 0-1 ELA, 2-3 EIO), with another client that moves MGR_ACTIVE and
    MGR_DESC_INDEX after every sequence it runs."""

    SCAN = re.compile(r"drshift -state DRUPDATE( -capture)? -bits (\d+) ([01]+)")

    def __init__(self, t: XilinxHwServerTransport, *, interfere: bool = True) -> None:
        self.t = t
        self.interfere = interfere
        self.active = 0
        self.desc_index = 0
        self.slots = [
            {0x0000: _ELA, 0x0008: 0x4},  # STATUS done
            {0x0000: _ELA, 0x0008: 0x0},
            {0x0000: _EIO, 0x0004: 8, 0x0008: 8, 0x0010: 0x11},
            {0x0000: _EIO, 0x0004: 8, 0x0008: 8, 0x0010: 0x33},
        ]
        self.desc = [(0x4C41, 1), (0x4C41, 1), (0x494F, 0), (0x494F, 0)]
        self.last = 0
        self.pending: list[tuple[bool, str]] = []
        self.runs = 0
        self.writes: list[tuple[int, int, int]] = []  # (slot, addr, value)

    def _manager_read(self, addr: int) -> int:
        return {
            0xF000: 0x0001_434D,
            0xF004: len(self.slots),
            _MGR_ACTIVE: self.active,
            0xF00C: 0,
            0xF010: 0x7,
            _DESC_INDEX: self.desc_index,
            _DESC_CORE: self.desc[self.desc_index][0],
            _DESC_CAPS: self.desc[self.desc_index][1],
        }.get(addr, 0)

    def _command(self, bits: str) -> None:
        off = self.t._dr_data_offset()
        frame = bits[off : off + 49]
        data = _int_lsb(frame[0:32])
        addr = _int_lsb(frame[32:48])
        write = frame[48] == "1"
        if write:
            if addr == _MGR_ACTIVE:
                if data < len(self.slots):
                    self.active = data
            elif addr == _DESC_INDEX:
                if data < len(self.slots):
                    self.desc_index = data
            elif not 0xF000 <= addr < 0xF100:
                self.slots[self.active][addr] = data
                self.writes.append((self.active, addr, data))
        elif 0xF000 <= addr < 0xF100:
            self.last = self._manager_read(addr)
        else:
            self.last = self.slots[self.active].get(addr, 0)

    def _token(self, width: int) -> str:
        bits = ["0"] * width
        off = self.t._dr_data_offset()
        for i in range(32):
            if (self.last >> i) & 1:
                bits[off + i] = "1"
        return "".join(bits)

    def send(self, tcl: str, check: bool = False, **_kw) -> str:
        if "[jtag sequence]" in tcl:
            self.pending = []
        for m in self.SCAN.finditer(tcl):
            self.pending.append((bool(m.group(1)), m.group(3)))
        if not re.search(r"\brun\b", tcl):
            return ""
        out = []
        for capture, bits in self.pending:
            if capture:
                out.append(self._token(len(bits)))
            if len(bits) == 49 + self.t.dr_extra_bits:
                self._command(bits)
        self.pending = []
        self.runs += 1
        if self.interfere:
            # Another process: the other ELA and the other EIO descriptor.
            self.active = (self.active + 1) % len(self.slots)
            self.desc_index = (self.desc_index + 3) % len(self.slots)
        return " ".join(out)


def _hw_server(**kwargs) -> tuple[XilinxHwServerTransport, FakeManagedXsdb]:
    t = XilinxHwServerTransport(**kwargs)
    fake = FakeManagedXsdb(t)
    t._send = fake.send  # type: ignore[method-assign]
    return t, fake


class HwServerAtomicSelectionTests(unittest.TestCase):
    def test_accesses_reach_their_slot_while_another_client_moves_it(self):
        """Another client writes MGR_ACTIVE after every sequence; ELA slot 0
        and EIO slot 2 accesses still reach their own slots, with no cache
        invalidation anywhere."""
        t, fake = _hw_server()
        ela = Analyzer(t, instance=0)
        eio = EioController(t, chain=1, instance=2)
        eio.attach()
        for _ in range(3):
            self.assertTrue(ela.status()["done"])
            self.assertEqual(eio.read_inputs(), 0x11)
            eio.write_outputs(0x5A)
        self.assertEqual({w[0] for w in fake.writes}, {2})
        self.assertEqual(fake.slots[2][0x0100], 0x5A)
        self.assertNotIn(0x0100, fake.slots[0])

    def test_slot_core_ids_reads_each_slot_while_another_client_moves_it(self):
        t, fake = _hw_server()
        ids = CoreManager(t).slot_core_ids()
        self.assertEqual(ids, [0x4C41, 0x4C41, 0x494F, 0x494F])

    def test_slot_descriptor_is_read_in_the_same_sequence_as_its_index(self):
        t, fake = _hw_server()
        cm = CoreManager(t)
        for slot, (core, caps) in enumerate(fake.desc):
            info = cm.slot_info(slot)
            self.assertEqual((info["core_id"], info["capabilities"]), (core, caps))

    def test_burst_capability_follows_the_bound_slot(self):
        """A slot's burst capability comes from its own descriptor, even when
        another client moves MGR_DESC_INDEX."""
        t, fake = _hw_server()
        for slot, (_core, caps) in enumerate(fake.desc[:2]):
            a = Analyzer(t, instance=slot)
            self.assertEqual(a._selected_slot_has_burst(), bool(caps & 1))

    def test_select_scan_is_uncaptured_and_heads_the_sequence(self):
        t, fake = _hw_server()
        fake.interfere = False
        sent: list[str] = []
        send = fake.send

        def spy(tcl, check=False, **kw):
            sent.append(tcl)
            return send(tcl, check, **kw)

        t._send = spy  # type: ignore[method-assign]
        select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
            t.write_reg(0x0004, 7)
            t.read_reg(_MGR_ACTIVE)  # manager block: no select
            t.write_reg(_MGR_ACTIVE, 3)
        t.read_reg(0x0008)  # outside any scope: no select
        self.assertEqual([s.count(select) for s in sent], [1, 1, 0, 0, 0])
        for tcl in sent[:2]:
            head = tcl.index(select)
            self.assertLess(head, tcl.index("-bits 49", head + len(select)))
            self.assertNotIn(f"-capture -bits 49 {select}", tcl)
            self.assertIn(f"{select}; $_", tcl)
            self.assertRegex(tcl[head:], rf"^{select}; \$_\w+ state IDLE {t.READ_IDLE_CYCLES};")
        self.assertEqual(sent[0].count("-capture"), 1)

    def test_register_ir_select_uses_the_register_write_idle(self):
        t, fake = _hw_server(use_register_ir=True)
        sent: list[str] = []
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), fake.send(tcl))[1]  # type: ignore[method-assign]
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
        self.assertIn(f"state IDLE {t.WRITE_IDLE_CYCLES_REGISTER}", sent[0])

    def test_no_select_on_another_chain(self):
        """A selection for the manager's chain never prefixes an access on
        another chain (the AXI monitor on USER2, say)."""
        t, fake = _hw_server()
        sent: list[str] = []
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), fake.send(tcl))[1]  # type: ignore[method-assign]
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.select_chain(2)
            try:
                t.read_reg(0x0008)
            finally:
                t.select_chain(1)
        self.assertEqual(sent[0].count("-bits 49"), 2)

    def test_block_read_selects_once_per_executed_sequence(self):
        t, fake = _hw_server()
        fake.interfere = False
        sent: list[str] = []
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), fake.send(tcl))[1]  # type: ignore[method-assign]
        select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
        t._BLOCK_CHUNK = 4
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_window_block(0x0100, 10)
        # Three chunks and the flush read: each its own sequence, each selected.
        self.assertEqual(len(sent), 4)
        self.assertEqual([s.count(select) for s in sent], [1, 1, 1, 1])

    def test_burst_selects_once_before_the_pointer_write(self):
        for single_chain in (True, False):
            for sync in (False, True):
                with self.subTest(single_chain=single_chain, sync=sync):
                    t = XilinxHwServerTransport(single_chain_burst=single_chain)
                    t.burst_start_sync = sync
                    sent: list[str] = []
                    n = 600  # several sends for one sequence
                    t._send = lambda tcl, check=False, **kw: (  # type: ignore[method-assign]
                        sent.append(tcl),
                        " ".join(["0" * 256] * (n + 1)) if "run -bits" in tcl else "",
                    )[1]
                    select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
                    with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                        t.read_sample_block(0x0100, n, 256)
                    body = "; ".join(sent)
                    self.assertEqual(body.count(select), 1)
                    ptr = t._pad_dr(
                        t._frame_bits(addr=t.ADDR_BURST_PTR, data=0, write=True)
                    )
                    self.assertLess(body.index(select), body.index(ptr))
                    self.assertLess(body.index(select), body.index("-bits 256"))
                    self.assertEqual(body.count("-capture"), n + 1)


class _FallbackTransport(Transport):
    """A backend without atomic selection: it selects once per scope."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def read_reg(self, addr: int) -> int:
        return 0

    def write_reg(self, addr: int, value: int) -> None:
        self.writes.append((addr, value))

    def read_block(self, addr: int, words: int):
        return [0] * words


class SlotScopeTests(unittest.TestCase):
    def test_scope_is_restored_on_exit_and_on_exception(self):
        t = _FallbackTransport()
        a, b = SlotSelection(1, _MGR_ACTIVE, 1), SlotSelection(1, _MGR_ACTIVE, 2)
        with t.slot_scope(a):
            with t.slot_scope(b):
                self.assertEqual(t.current_slot_selection(), b)
            self.assertEqual(t.current_slot_selection(), a)
            with self.assertRaises(ValueError):
                with t.slot_scope(None):
                    self.assertIsNone(t.current_slot_selection())
                    raise ValueError
            self.assertEqual(t.current_slot_selection(), a)
        self.assertIsNone(t.current_slot_selection())

    def test_fallback_selects_on_entry_and_back_for_the_enclosing_scope(self):
        t = _FallbackTransport()
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 2)):
                pass
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                pass  # cached: no write
        self.assertEqual(t.writes, [(_MGR_ACTIVE, 1), (_MGR_ACTIVE, 2), (_MGR_ACTIVE, 1)])

    def test_selection_is_per_thread(self):
        """A raw controller on another thread (EJTAG-UART on USER3, which
        takes no transaction lock) never sees the selection."""
        t, fake = _hw_server()
        seen: list[object] = []
        inside = threading.Event()
        done = threading.Event()

        def holder() -> None:
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                inside.set()
                done.wait(5)

        th = threading.Thread(target=holder, daemon=True)
        th.start()
        self.assertTrue(inside.wait(5))
        try:
            seen.append(t.current_slot_selection())
            self.assertEqual(t._slot_select_tcl("_w", [0x0004]), [])
        finally:
            done.set()
            th.join(5)
        self.assertEqual(seen, [None])

    def test_unbound_probe_inside_a_slot_scope_carries_no_select(self):
        """A slot-less analyzer called from inside an EIO's scope (as EIO
        discovery does) must not inherit the EIO's slot."""
        t, fake = _hw_server()
        fake.interfere = False
        sent: list[str] = []
        send = fake.send
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), send(tcl))[1]  # type: ignore[method-assign]
        select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=3, write=True))
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 3)):
            Analyzer(t).speaks_register_protocol()
        self.assertTrue(sent)
        self.assertFalse(any(select in s for s in sent))


if __name__ == "__main__":
    unittest.main()
