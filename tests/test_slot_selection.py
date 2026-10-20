# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Per-operation core-manager slot selection (Transport.slot_scope).

A second process on the same cable (a GUI next to a CLI, two MCP clients)
can write MGR_ACTIVE between any two backend operations.  Each access in a
slot scope carries its own MGR_ACTIVE write in the same backend operation
(a ``jtag sequence`` on hw_server, a ``device_lock`` on Quartus, one Tcl
command line on OpenOCD), so it reaches its slot regardless.
"""

from __future__ import annotations

import re
import threading
import unittest

from fcapz.analyzer import Analyzer, CoreManager
from fcapz.eio import EioController
from fcapz.transport import (
    OpenOcdTransport,
    QuartusStpTransport,
    SlotSelection,
    Transport,
    XilinxHwServerTransport,
)

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
        self.caps = 0x7  # no epochs (MGR_CAPS bit 3): a legacy manager
        self.register_core = True  # 0x0000 answers as an fcapz core
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
            0xF010: self.caps,
            _DESC_INDEX: self.desc_index,
            _DESC_CORE: self.desc[self.desc_index][0],
            _DESC_CAPS: self.desc[self.desc_index][1],
        }.get(addr, 0)

    def _command(self, bits: str) -> None:
        off = self.t._dr_data_offset()
        frame = bits[off : off + 49]
        self._apply(_int_lsb(frame[32:48]), _int_lsb(frame[0:32]), frame[48] == "1")

    def _apply(self, addr: int, data: int, write: bool) -> None:
        """One 49-bit command reaching the hub."""
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
        elif addr == 0x0000 and not self.register_core:
            self.last = 0
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


class FakeManagedQuartus(FakeManagedXsdb):
    """quartus_stp running locked scripts against the same core manager on
    virtual JTAG instance 1, with the other client moving MGR_ACTIVE and
    MGR_DESC_INDEX after every script (every ``device_lock``)."""

    DR = re.compile(
        r"set (\w+) \[device_virtual_dr_shift -instance_index (\d+) "
        r"-length (\d+) -dr_value ([01]+)\]"
    )
    LAPPEND = re.compile(r"lappend (\w+) \$(\w+)")
    RESULT = re.compile(r"set (\w+)$")

    def send(self, script: str, **_kw) -> str:
        values: dict[str, str] = {}
        lists: dict[str, list[str]] = {}
        result = None
        for line in script.splitlines():
            line = line.strip()
            if m := self.DR.match(line):
                name, instance, width = m.group(1), int(m.group(2)), int(m.group(3))
                if instance == 1 and width == 49:
                    # A capture returns the previous command's response.
                    values[name] = f"{self.last:049b}"
                    v = int(m.group(4), 2)
                    self._apply((v >> 32) & 0xFFFF, v & 0xFFFFFFFF, bool(v >> 48))
                else:
                    values[name] = "0" * width
            elif m := self.LAPPEND.match(line):
                lists.setdefault(m.group(1), []).append(values[m.group(2)])
            elif m := self.RESULT.match(line):
                result = m.group(1)
        self.runs += 1
        if self.interfere:
            self.active = (self.active + 1) % len(self.slots)
            self.desc_index = (self.desc_index + 3) % len(self.slots)
        if result in lists:
            return " ".join(lists[result])
        return values.get(result, "")


def _quartus(**kwargs) -> tuple[QuartusStpTransport, FakeManagedQuartus]:
    t = QuartusStpTransport(**kwargs)
    fake = FakeManagedQuartus(t)  # type: ignore[arg-type]
    t._send = fake.send  # type: ignore[method-assign]
    return t, fake


class FakeManagedOpenOcd(FakeManagedXsdb):
    """OpenOCD's Tcl server running one command line at a time against the
    same core manager on USER1 (IR 2), with the other client moving
    MGR_ACTIVE and MGR_DESC_INDEX after every line."""

    SCAN = re.compile(r"(?:set (\w+) \[)?irscan \S+ (\d+); drscan \S+ 49 0x([0-9a-f]+)")
    LIST = re.compile(r"list ((?:\$\w+ ?)+)$")

    def cmd(self, tcl: str) -> str:
        values: dict[str, str] = {}
        result = ""
        for m in self.SCAN.finditer(tcl):
            if int(m.group(2)) == 2:
                # A capture returns the previous command's response.
                result = f"{self.last:013x}"
                v = int(m.group(3), 16)
                self._apply((v >> 32) & 0xFFFF, v & 0xFFFFFFFF, bool(v >> 48))
            else:
                result = "0" * 13
            if m.group(1):
                values[m.group(1)] = result
        self.runs += 1
        if self.interfere:
            self.active = (self.active + 1) % len(self.slots)
            self.desc_index = (self.desc_index + 3) % len(self.slots)
        if m := self.LIST.search(tcl):
            return " ".join(values[v.lstrip("$")] for v in m.group(1).split())
        return result


def _openocd(**kwargs) -> tuple[OpenOcdTransport, FakeManagedOpenOcd]:
    t = OpenOcdTransport(**kwargs)
    fake = FakeManagedOpenOcd(t)  # type: ignore[arg-type]
    t._cmd = fake.cmd  # type: ignore[method-assign]
    return t, fake


def _hw_server(**kwargs) -> tuple[XilinxHwServerTransport, FakeManagedXsdb]:
    t = XilinxHwServerTransport(**kwargs)
    fake = FakeManagedXsdb(t)
    t._send = fake.send  # type: ignore[method-assign]
    return t, fake


def _warm(t: Transport, *slots: int, chain: int = 1) -> None:
    """Enter a scope on each slot once: the first scope on a slot identifies
    the manager and verifies the slot (see Transport.slot_scope)."""
    for slot in slots:
        with t.slot_scope(SlotSelection(chain, _MGR_ACTIVE, slot)):
            pass


def _identified(t: Transport, *slots: int, chain: int = 1, caps: int = 0x0F) -> None:
    """Mark *chain* as an identified manager with *slots* verified, for a
    fake that cannot answer the identification reads."""
    t.__dict__.setdefault("_fcapz_manager_chains", set()).add(chain)
    t.__dict__.setdefault("_fcapz_manager_caps", {})[chain] = caps
    checked = t.__dict__.setdefault("_fcapz_checked_slots", set())
    checked.update((chain, slot) for slot in slots)


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
        _warm(t, 1)
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
        fake.interfere = False
        _warm(t, 1)
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
        _warm(t, 1)
        sent.clear()
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_window_block(0x0100, 10)
        # Three chunks and the flush read: each its own sequence, each selected.
        self.assertEqual(len(sent), 4)
        self.assertEqual([s.count(select) for s in sent], [1, 1, 1, 1])

    def test_block_read_running_out_of_the_manager_block_is_selected(self):
        """A block that starts in the manager block but reaches past it is
        selected: only a sequence that stays inside the block is not."""
        t, fake = _hw_server()
        fake.interfere = False
        sent: list[str] = []
        send = fake.send
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), send(tcl))[1]  # type: ignore[method-assign]
        t.data_window_end = 0x10000
        select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
        _warm(t, 1)
        sent.clear()
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_window_block(0xF0FC, 2)
            t.read_window_block(0xF000, 2)
        self.assertIn(select, sent[0])
        self.assertNotIn(select, sent[2])

    def test_deep_manager_detection_survives_another_client(self):
        """The DESC_INDEX latch probe (for a manager whose 0xF000 could alias
        a deep standalone core) writes and reads back in one sequence."""
        t, fake = _hw_server()
        fake.slots[0].update({0x000C: 32, 0x0010: 32768})  # SAMPLE_W, DEPTH
        a = Analyzer(t, instance=0)
        self.assertTrue(a._behind_manager())

    def test_an_access_select_drops_the_slot_cache(self):
        """The per-access select moves MGR_ACTIVE behind the cache; a cached
        select afterwards must still write."""
        t, fake = _hw_server()
        fake.interfere = False
        CoreManager(t, chain=1).select_raw(0)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1), chain=1):
            t.read_reg(0x0004)
        self.assertEqual(fake.active, 1)
        t.select_manager_instance_cached(1, _MGR_ACTIVE, 0)
        self.assertEqual(fake.active, 0)

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
                    _identified(t, 1)
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
    """A backend without atomic selection: it selects once per scope.  A
    4-slot core manager answers on every chain."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []
        self.manager_active: dict[int, int] = {}

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def _chain_now(self) -> int:
        return getattr(self, "_active_chain", 1)

    def read_reg(self, addr: int) -> int:
        if addr == _MGR_ACTIVE:
            return self.manager_active.get(self._chain_now(), 0)
        return {0x0000: _ELA, 0xF000: 0x0001_434D, 0xF004: 4}.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.writes.append((addr, value))
        if addr == _MGR_ACTIVE and value < 4:
            self.manager_active[self._chain_now()] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


class _ChainedFallbackTransport(_FallbackTransport):
    """A fallback backend that tracks its chain, like OpenOCD and Quartus."""

    def __init__(self) -> None:
        super().__init__()
        self._active_chain = 1
        self.chained_writes: list[tuple[int, int, int]] = []

    def select_chain(self, chain: int) -> None:
        self._active_chain = chain

    def write_reg(self, addr: int, value: int) -> None:
        self.chained_writes.append((self._active_chain, addr, value))
        super().write_reg(addr, value)


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

    def test_exception_in_a_nested_scope_still_restores_the_outer_slot(self):
        """Fallback backends: a nested scope that raises must put the
        enclosing scope's slot back on the hardware."""
        t = _FallbackTransport()
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            with self.assertRaises(ValueError):
                with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 2)):
                    raise ValueError
            self.assertEqual(t.writes[-1], (_MGR_ACTIVE, 1))

    def test_failed_restore_drops_the_cache_and_keeps_the_body_error(self):
        t = _FallbackTransport()
        fail = {"on": False}
        real_write = t.write_reg

        def write_reg(addr, value):
            if fail["on"]:
                raise OSError("cable gone")
            real_write(addr, value)

        t.write_reg = write_reg  # type: ignore[method-assign]
        with self.assertRaises(OSError):
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 2)):
                    fail["on"] = True
        self.assertNotIn("_fcapz_manager_active_cache", t.__dict__)
        fail["on"] = False
        with self.assertRaises(KeyError):
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 2)):
                    fail["on"] = True
                    raise KeyError("body")
        self.assertNotIn("_fcapz_manager_active_cache", t.__dict__)

    def test_a_failed_selector_write_does_not_leave_a_stale_cache(self):
        """The inner select reaches the hardware, then reports an error: the
        enclosing slot must still be written back."""
        t = _FallbackTransport()
        real_write = t.write_reg

        def write_reg(addr, value):
            real_write(addr, value)
            if value == 2:
                raise OSError("no response")

        t.write_reg = write_reg  # type: ignore[method-assign]
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            with self.assertRaises(OSError):
                with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 2)):
                    pass
            self.assertEqual(t.writes[-1], (_MGR_ACTIVE, 1))

    def test_an_interrupted_restore_drops_the_cache_and_propagates(self):
        t = _FallbackTransport()
        real_write = t.write_reg
        interrupt = {"on": False}

        def write_reg(addr, value):
            real_write(addr, value)
            if interrupt["on"]:
                raise KeyboardInterrupt

        t.write_reg = write_reg  # type: ignore[method-assign]
        for body_error in (None, ValueError):
            interrupt["on"] = False
            with self.subTest(body_error=body_error):
                with self.assertRaises(KeyboardInterrupt):
                    with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 2)):
                            interrupt["on"] = True
                            if body_error:
                                raise body_error
                self.assertNotIn("_fcapz_manager_active_cache", t.__dict__)

    def test_nested_probe_restores_a_scope_entered_without_chain(self):
        t, fake = _hw_server()
        fake.interfere = False
        sent: list[str] = []
        send = fake.send
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), send(tcl))[1]  # type: ignore[method-assign]
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            Analyzer(t, chain=2).speaks_register_protocol()
            sent.clear()
            t.write_reg(0x0004, 1)
        select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
        self.assertEqual(t._active_chain, 1)
        self.assertIn(select, sent[0])

    def test_a_scope_without_chain_gives_back_the_chain_that_was_active(self):
        """Entered on chain 2 without chain=, the scope's body runs on chain 2,
        not on its selection's chain, and a nested scope must give 2 back."""
        t, fake = _hw_server()
        fake.interfere = False
        t.select_chain(2)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            with t.slot_scope(None, chain=3):
                pass
            self.assertEqual(t._active_chain, 2)

    def test_a_nested_scope_gives_back_a_chain_switched_without_a_scope(self):
        """Code inside a scope (the GUI's subsidiary chain) switches the chain
        without one; a scope nested there gives back that chain, not the
        outer scope's."""
        t, fake = _hw_server()
        fake.interfere = False
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1), chain=1):
            t.select_chain(2)
            with t.slot_scope(SlotSelection(2, _MGR_ACTIVE, 0)):
                with t.slot_scope(None, chain=3):
                    pass
                self.assertEqual(t._active_chain, 2)
            self.assertEqual(t._active_chain, 2)

    def test_a_scope_gives_back_a_chain_its_own_body_switched(self):
        t, fake = _hw_server()
        fake.interfere = False
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1), chain=1):
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 0), chain=1):
                t.select_chain(2)
                with t.slot_scope(None, chain=3):
                    pass
                self.assertEqual(t._active_chain, 2)
            self.assertEqual(t._active_chain, 1)

    def test_a_slot_is_restored_on_its_own_chain(self):
        """Fallback backends: restoring the enclosing slot from another chain
        writes MGR_ACTIVE on the manager's chain, then comes back."""
        t = _ChainedFallbackTransport()
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1), chain=1):
            t.select_chain(2)
            with t.slot_scope(SlotSelection(2, _MGR_ACTIVE, 0), chain=2):
                pass
            self.assertEqual(t._active_chain, 2)
        self.assertEqual(
            t.chained_writes, [(1, _MGR_ACTIVE, 1), (2, _MGR_ACTIVE, 0), (1, _MGR_ACTIVE, 1)]
        )

    def test_nested_probe_on_another_chain_restores_the_chain(self):
        """A probe on chain 2 inside a chain-1 slot scope must leave the
        enclosing scope's next access on chain 1, with its select."""
        t, fake = _hw_server()
        fake.interfere = False
        sent: list[str] = []
        send = fake.send
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), send(tcl))[1]  # type: ignore[method-assign]
        ela = Analyzer(t, instance=1)
        with ela._selected():
            Analyzer(t, chain=2).speaks_register_protocol()
            sent.clear()
            t.write_reg(0x0004, 1)
        select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
        self.assertEqual(t._active_chain, 1)
        self.assertIn(select, sent[0])
        self.assertIn(t._irshift_tcl("_w", chain=1), sent[0])

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
        _warm(t, 3)
        sent.clear()
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 3)):
            Analyzer(t).speaks_register_protocol()
        self.assertTrue(sent)
        self.assertFalse(any(select in s for s in sent))



class _Boom(Exception):
    pass


class NestingSweepTests(unittest.TestCase):
    """Every three-deep nesting of slot scopes, with and without chain=, a
    chain switch made without a scope inside each body, and an exception
    from the innermost body.  After each nested scope exits, the enclosing
    body must be back on the chain it was on, and on a fallback backend its
    slot must be selected on its own chain, with a cache that never claims
    a slot the hardware does not have."""

    SELECTIONS = (None, 1, 2)  # no selection, or a slot on chain 1 / 2
    CHAINS = (None, 1, 2)
    SWITCHES = (None, 2)

    def _levels(self):
        one = [
            (sel, ch, sw)
            for sel in self.SELECTIONS
            for ch in self.CHAINS
            for sw in self.SWITCHES
        ]
        return [(a, b, c) for a in one for b in one for c in one]

    def _sweep(self, make):
        for levels in self._levels():
            for raise_inner in (False, True):
                t, hw = make()
                self._run(t, hw, levels, raise_inner)

    def _run(self, t, hw, levels, raise_inner):
        fallback = not t.atomic_slot_select

        def body(i):
            sel_chain, ch, switch = levels[i]
            sel = (
                None
                if sel_chain is None
                else SlotSelection(sel_chain, _MGR_ACTIVE, i + 1)
            )
            with t.slot_scope(sel, chain=ch):
                if switch is not None:
                    t.select_chain(switch)
                if i == len(levels) - 1:
                    if raise_inner:
                        raise _Boom
                    return
                before = t._active_chain
                try:
                    body(i + 1)
                except _Boom:
                    pass
                where = f"levels={levels} raise={raise_inner} at depth {i}"
                self.assertEqual(t._active_chain, before, where)
                if fallback and sel is not None:
                    self.assertEqual(hw.get(sel.chain), sel.slot, where)
                cached = t.__dict__.get("_fcapz_manager_active_cache")
                if fallback and cached is not None:
                    self.assertEqual(hw.get(cached[0]), cached[1], where)

        body(0)

    def test_fallback_backend_with_a_tracked_chain(self):
        def make():
            t = _ChainedFallbackTransport()
            hw: dict[int, int] = {}
            real = t.write_reg

            def write_reg(addr, value):
                real(addr, value)
                if addr == _MGR_ACTIVE:
                    hw[t._active_chain] = value

            t.write_reg = write_reg  # type: ignore[method-assign]
            return t, hw

        self._sweep(make)

    def test_hw_server(self):
        def make():
            t, fake = _hw_server()
            fake.interfere = False
            return t, {}

        self._sweep(make)


class InterimContractTests(unittest.TestCase):
    """Foreign selects are accepted only where routing is proven isolated:
    an atomic backend, a slot of an identified manager, and a prefix the
    manager is sure to take (BUG-260)."""

    def _spy(self, t, fake):
        sent: list[str] = []
        send = fake.send
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), send(tcl))[1]  # type: ignore[method-assign]
        return sent

    def test_no_select_reaches_a_chain_without_a_manager(self):
        """An MGR_ACTIVE write is an EJTAG-AXI bridge's reset command: a
        scope on a chain that never answered as a manager writes none."""
        t, fake = _hw_server()
        fake.interfere = False
        fake.register_core = False
        sent = self._spy(t, fake)
        select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            self.assertIsNone(t.current_slot_selection())
            t.read_reg(0x0008)
        self.assertFalse(any(select in tcl for tcl in sent))
        self.assertFalse(t.slot_routing_isolated(1, 1))

    def test_first_scope_verifies_the_slot_under_interference(self):
        t, fake = _hw_server()  # another client moves ACTIVE after every run
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 2)):
            self.assertTrue(t.slot_routing_isolated(1, 2))
            self.assertEqual(t.read_reg(0x0010), 0x11)

    def test_a_slot_the_manager_refuses_fails_loudly(self):
        t, fake = _hw_server()
        fake.interfere = False
        with self.assertRaises(RuntimeError):
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 9)):
                pass

    def test_a_legacy_manager_gets_a_drain_ahead_of_the_select(self):
        """A manager without epochs ignores an ACTIVE write while its burst
        engine loads: a command scan and a fill's worth of idle go first."""
        for caps, drained in ((0x7, True), (0xF, False)):
            with self.subTest(caps=caps):
                t, fake = _hw_server()
                fake.interfere = False
                fake.caps = caps
                _warm(t, 1)
                sent = self._spy(t, fake)
                with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                    t.read_reg(0x0008)
                select = t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=1, write=True))
                neutral = t._pad_dr(t._frame_bits(addr=0x0000, data=0, write=False))
                head = sent[0][: sent[0].index(select)]
                drain = f"{neutral}; $_s state IDLE {t.BURST_DRAIN_IDLE_CYCLES}"
                self.assertEqual(drain in head, drained, head)
                self.assertNotIn("-capture", head)

    def test_every_prefix_is_counted_as_this_hosts_select(self):
        t, fake = _hw_server()
        fake.interfere = False
        _warm(t, 1)
        before = t.manager_select_writes(1)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
            t.write_reg(0x0004, 1)
            t.read_reg(_MGR_ACTIVE)  # manager block: no prefix
        self.assertEqual(t.manager_select_writes(1) - before, 2)

    def test_identification_outlives_the_slot_cache(self):
        t, fake = _hw_server()
        fake.interfere = False
        _warm(t, 1)
        t.invalidate_manager_instance_cache()
        sent = self._spy(t, fake)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            pass
        self.assertEqual(sent, [])  # nothing to identify or verify again
        t.forget_manager_chains()
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            pass
        self.assertTrue(sent)  # a new session: identified again

    def test_an_isolated_eio_is_not_alarmed_by_foreign_selects(self):
        """MGR_ACTIVE and MGR_SELECT_COUNT move under every access here, and
        are no evidence of a misrouted one: each access selects its slot."""
        t, fake = _hw_server()  # interference after every run
        fake.caps = 0x8F  # epochs and MGR_SELECT_COUNT
        eio = EioController(t, chain=1, instance=2)
        eio.attach()
        for _ in range(3):
            self.assertEqual(eio.read_inputs(), 0x11)

    def test_an_isolated_analyzer_is_not_alarmed_by_foreign_selects(self):
        """configure, arm and the wait's slot check read MGR_ACTIVE and the
        select count around every step; with another client selecting after
        every sequence, neither may raise where each access selects its slot."""
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        t, fake = _hw_server()  # interference after every run
        fake.caps = 0x8F  # epochs and MGR_SELECT_COUNT
        fake.slots[0].update({0x000C: 8, 0x0010: 1024, 0x0014: 1})  # SAMPLE_W, DEPTH
        a = Analyzer(t, instance=0)
        a.configure(CaptureConfig(
            pretrigger=4, posttrigger=8,
            trigger=TriggerConfig(mode="value_match", value=1, mask=0xFF),
            sample_width=8, depth=1024,
        ))
        self.assertIsNotNone(a._config_state)  # the epoch checks are on
        a.arm()
        self.assertTrue(a.wait_done(timeout=1.0))

    def test_a_reconnect_identifies_again(self):
        """Another bitstream may sit behind a new connection: a slot verified
        before it must be identified again, not prefixed with an MGR_ACTIVE
        write (an EJTAG-AXI bridge's reset)."""
        from unittest.mock import patch

        t, fake = _hw_server()
        fake.interfere = False
        fake.caps = 0xF  # MGR_OWNER: the slot's manager gets claimed
        _warm(t, 1)
        self.assertTrue(t.__dict__.get("_fcapz_owned_managers"))
        with patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                t.connect()  # xsdb missing: forgets before it fails
        self.assertFalse(t.__dict__.get("_fcapz_owned_managers"))
        self.assertFalse(t.slot_routing_isolated(1, 1))
        sent = self._spy(t, fake)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            pass
        self.assertTrue(sent)  # identified again

    def test_every_backend_connect_forgets_the_hub(self):
        from unittest.mock import patch

        from fcapz.transport import OpenOcdTransport, QuartusStpTransport

        for t, ctx in (
            (OpenOcdTransport(),
             patch("socket.create_connection", side_effect=OSError("refused"))),
            (QuartusStpTransport(quartus_stp_path="missing_quartus_stp"),
             patch("fcapz.transport.find_quartus_stp", return_value=None)),
        ):
            with self.subTest(backend=type(t).__name__):
                _identified(t, 1)
                t.__dict__["_fcapz_owned_managers"] = {(1, 0xF000)}
                with ctx, self.assertRaises((OSError, RuntimeError)):
                    t.connect()
                self.assertFalse(t.__dict__.get("_fcapz_manager_chains"))
                self.assertFalse(t.__dict__.get("_fcapz_checked_slots"))
                self.assertFalse(t.__dict__.get("_fcapz_owned_managers"))

    def test_program_drops_the_claimed_managers(self):
        """After a new bitstream, 0xF024 on a once-claimed chain may be any
        core's register: close() must not read or clear it there."""
        t, fake = _hw_server()
        fake.interfere = False
        fake.caps = 0xF
        _warm(t, 1)
        t.program("C:/tmp/design.bit")
        sent = self._spy(t, fake)
        t.release_manager_ownership()
        self.assertEqual(sent, [])

    def test_openocd_cancel_releases_no_ownership(self):
        """A cancel runs on another thread: an MGR_OWNER release would put
        scans from it in the middle of the aborted operation."""
        from fcapz.transport import OpenOcdTransport

        t = OpenOcdTransport()
        released: list[bool] = []
        t.release_manager_ownership = lambda: released.append(True)  # type: ignore[method-assign]
        t.__dict__["_fcapz_owned_managers"] = {(1, 0xF000)}

        class _Sock:
            closed = False

            def close(self):
                self.closed = True

        sock = _Sock()
        t._sock = sock  # type: ignore[assignment]
        t.cancel()
        self.assertTrue(sock.closed)
        self.assertEqual(released, [])


class _AtomicBackendContract:
    """The interim contract on a backend that runs each access, its slot
    select at the head, as one unit no other client of the cable can split.
    Subclasses give the backend (:meth:`make`), how to watch what it sends
    (:meth:`spy`), and the text of a select and of a legacy drain in it."""

    #: Text found ahead of the select, in the same unit, for a manager
    #: without epochs.
    DRAIN = ""

    def make(self):
        raise NotImplementedError

    def spy(self, t, fake) -> list[str]:
        raise NotImplementedError

    def select_text(self, t, slot: int) -> str:
        raise NotImplementedError

    def test_accesses_reach_their_slot_while_another_client_moves_it(self):
        t, fake = self.make()
        ela = Analyzer(t, instance=0)
        eio = EioController(t, chain=1, instance=2)
        eio.attach()
        for _ in range(3):
            self.assertTrue(ela.status()["done"])
            self.assertEqual(eio.read_inputs(), 0x11)
            eio.write_outputs(0x5A)
        self.assertEqual({w[0] for w in fake.writes}, {2})
        self.assertEqual(fake.slots[2][0x0100], 0x5A)

    def test_slot_core_ids_and_descriptors_survive_another_client(self):
        t, fake = self.make()
        cm = CoreManager(t)
        self.assertEqual(cm.slot_core_ids(), [0x4C41, 0x4C41, 0x494F, 0x494F])
        for slot, (core, caps) in enumerate(fake.desc):
            info = cm.slot_info(slot)
            self.assertEqual((info["core_id"], info["capabilities"]), (core, caps))
        for slot, (_core, caps) in enumerate(fake.desc[:2]):
            self.assertEqual(Analyzer(t, instance=slot)._selected_slot_has_burst(), bool(caps & 1))

    def test_deep_manager_detection_survives_another_client(self):
        t, fake = self.make()
        fake.slots[0].update({0x000C: 32, 0x0010: 32768})  # SAMPLE_W, DEPTH
        self.assertTrue(Analyzer(t, instance=0)._behind_manager())

    def test_each_access_carries_its_own_select(self):
        t, fake = self.make()
        fake.interfere = False
        _warm(t, 1)
        sent = self.spy(t, fake)
        select = self.select_text(t, 1)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
            t.write_reg(0x0004, 7)
            t.read_reg(_MGR_ACTIVE)  # manager block: no select
            t.write_reg(_MGR_ACTIVE, 3)
        t.read_reg(0x0008)  # outside any scope: no select
        self.assertEqual([s.count(select) for s in sent], [1, 1, 0, 0, 0])

    def test_no_select_on_another_chain_or_an_unmanaged_one(self):
        t, fake = self.make()
        sent = self.spy(t, fake)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.select_chain(2)
            try:
                t.read_reg(0x0008)
            finally:
                t.select_chain(1)
        self.assertNotIn(self.select_text(t, 1), sent[-1])

        t, fake = self.make()
        fake.register_core = False
        sent = self.spy(t, fake)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
        self.assertFalse(any(self.select_text(t, 1) in s for s in sent))
        self.assertFalse(t.slot_routing_isolated(1, 1))

    def test_a_slot_the_manager_refuses_fails_loudly(self):
        t, fake = self.make()
        fake.interfere = False
        with self.assertRaises(RuntimeError):
            with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 9)):
                pass

    def test_a_legacy_manager_gets_a_drain_ahead_of_the_select(self):
        for caps, drained in ((0x7, True), (0xF, False)):
            with self.subTest(caps=caps):
                t, fake = self.make()
                fake.interfere = False
                fake.caps = caps
                _warm(t, 1)
                sent = self.spy(t, fake)
                with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                    t.read_reg(0x0008)
                head = sent[0][: sent[0].index(self.select_text(t, 1))]
                self.assertEqual(self.DRAIN in head, drained)
                self.assertEqual(str(t.BURST_DRAIN_IDLE_CYCLES) in head, drained)

    def test_every_prefix_is_counted_as_this_hosts_select(self):
        t, fake = self.make()
        fake.interfere = False
        _warm(t, 1)
        before = t.manager_select_writes(1)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
            t.write_reg(0x0004, 1)
            t.read_reg(_MGR_ACTIVE)
        self.assertEqual(t.manager_select_writes(1) - before, 2)

    def test_an_access_select_drops_the_slot_cache(self):
        t, fake = self.make()
        fake.interfere = False
        CoreManager(t, chain=1).select_raw(0)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1), chain=1):
            t.read_reg(0x0004)
        self.assertEqual(fake.active, 1)
        t.select_manager_instance_cached(1, _MGR_ACTIVE, 0)
        self.assertEqual(fake.active, 0)

    def test_select_instance_leaves_the_hub_on_the_slot(self):
        """Raw transport accesses after select_instance() reach that slot,
        as on a backend that selects on scope entry."""
        t, fake = self.make()
        fake.interfere = False
        ela0 = Analyzer(t, instance=0)
        ela1 = Analyzer(t, instance=1)
        ela0.select_instance(0)
        t.write_reg(0x0014, 11)
        ela1.select_instance(1)
        t.write_reg(0x0014, 22)
        ela0.select_instance(0)
        self.assertEqual(t.read_reg(0x0014), 11)
        ela1.select_instance(1)
        self.assertEqual(t.read_reg(0x0014), 22)

    def test_read_regs_after_write_waits_for_another_threads_transaction(self):
        """The unit reads the active chain and slot once: another thread's
        scope must not switch them while it is being built."""
        t, fake = self.make()
        fake.interfere = False
        done = threading.Event()

        def call():
            t.read_regs_after_write(_DESC_INDEX, 2, [_DESC_CORE])
            done.set()

        with t.transaction_lock():
            worker = threading.Thread(target=call)
            worker.start()
            self.assertFalse(done.wait(0.2))
        worker.join(5)
        self.assertTrue(done.is_set())

    def test_isolated_controllers_are_not_alarmed_by_foreign_selects(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        t, fake = self.make()
        fake.caps = 0x8F  # epochs and MGR_SELECT_COUNT
        fake.slots[0].update({0x000C: 8, 0x0010: 1024, 0x0014: 1})
        eio = EioController(t, chain=1, instance=2)
        eio.attach()
        for _ in range(3):
            self.assertEqual(eio.read_inputs(), 0x11)
        a = Analyzer(t, instance=0)
        a.configure(CaptureConfig(
            pretrigger=4, posttrigger=8,
            trigger=TriggerConfig(mode="value_match", value=1, mask=0xFF),
            sample_width=8, depth=1024,
        ))
        self.assertIsNotNone(a._config_state)
        a.arm()
        self.assertTrue(a.wait_done(timeout=1.0))


class HwServerAtomicContractTests(_AtomicBackendContract, unittest.TestCase):
    """hw_server: the select is the first scan of each ``jtag sequence``."""

    DRAIN = "$_s state IDLE"

    def make(self):
        return _hw_server()

    def spy(self, t, fake):
        sent: list[str] = []
        t._send = lambda tcl, check=False, **kw: (sent.append(tcl), fake.send(tcl))[1]  # type: ignore[method-assign]
        return sent

    def select_text(self, t, slot):
        return t._pad_dr(t._frame_bits(addr=_MGR_ACTIVE, data=slot, write=True))


class QuartusAtomicSelectionTests(_AtomicBackendContract, unittest.TestCase):
    """quartus_stp: the select is shifted inside each access's own
    ``device_lock``, and the other client runs between locks."""

    DRAIN = "__fcapz_select_drain"

    def make(self):
        return _quartus()

    def spy(self, t, fake):
        sent: list[str] = []
        t._send = lambda script, **kw: (sent.append(script), fake.send(script))[1]  # type: ignore[method-assign]
        return sent

    def select_text(self, t, slot):
        return f"-length 49 -dr_value {(1 << 48) | (_MGR_ACTIVE << 32) | slot:049b}]"

    def test_the_select_is_inside_the_lock_ahead_of_the_access(self):
        t, fake = self.make()
        fake.interfere = False
        fake.caps = 0xF  # no drain: the select is the first scan
        _warm(t, 1)
        sent = self.spy(t, fake)
        select = self.select_text(t, 1)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
            t.write_reg(0x0004, 7)
            t.read_window_block(0x0100, 3)
        self.assertEqual([s.count(select) for s in sent], [1, 1, 1])
        for script in sent:
            at = script.index(select)
            self.assertLess(script.index("device_lock"), at)
            self.assertEqual(script.index("-length 49"), at)
            self.assertLess(at, script.index("device_unlock"))

    def test_bursts_select_once_before_the_pointer_and_drain_after(self):
        """The select goes ahead of BURST_PTR, which makes the slot the burst
        owner, never between burst scans; a burst on the control chain ends
        with a command scan and a fill's worth of idle."""
        n = 8
        cases = (
            ("samples", lambda t: t.read_sample_block(0x0100, n, 32), 0x0),
            ("timestamps", lambda t: t.read_timestamp_block_single_chain(0x0100, n, 32), 0x8),
            ("run lengths", lambda t: t.read_run_length_block(n, 32, on_control_chain=True), 0xC),
        )
        for name, read, ptr_top in cases:
            with self.subTest(read=name):
                t, fake = self.make()
                fake.interfere = False
                _warm(t, 1)
                sent = self.spy(t, fake)
                with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
                    read(t)
                (script,) = sent
                select = script.index(self.select_text(t, 1))
                ptr = (1 << 48) | (0x002C << 32) | (ptr_top << 28)
                pointer = script.index(f"-length 49 -dr_value {ptr:049b}]")
                self.assertEqual(script.count(self.select_text(t, 1)), 1)
                self.assertLess(select, pointer)
                self.assertLess(pointer, script.index("-length 256"))
                self.assertNotIn("-instance_index 2", script)
                drain = script.index("__fcapz_drain_discard")
                self.assertGreater(drain, script.rindex("-length 256"))


class OpenOcdAtomicSelectionTests(_AtomicBackendContract, unittest.TestCase):
    """OpenOCD: each access is one Tcl command line, its select at the head;
    the Tcl server runs a whole line before it serves another client."""

    DRAIN = "49 0x0000000000000; runtest"

    def make(self):
        return _openocd()

    def spy(self, t, fake):
        sent: list[str] = []
        t._cmd = lambda tcl: (sent.append(tcl), fake.cmd(tcl))[1]  # type: ignore[method-assign]
        return sent

    def select_text(self, t, slot):
        return f"drscan {t.tap} 49 0x{(1 << 48) | (_MGR_ACTIVE << 32) | slot:013x}"

    def test_the_select_heads_the_line(self):
        t, fake = self.make()
        fake.interfere = False
        fake.caps = 0xF
        _warm(t, 1)
        sent = self.spy(t, fake)
        with t.slot_scope(SlotSelection(1, _MGR_ACTIVE, 1)):
            t.read_reg(0x0008)
            t.write_reg(0x0004, 7)
            t.read_regs_after_write(0x0004, 1, [0x0008, 0x0010])
        for line in sent:
            first = line.split("; ")[1]
            self.assertEqual(first, self.select_text(t, 1))
        self.assertEqual(len(sent), 3)


if __name__ == "__main__":
    unittest.main()
