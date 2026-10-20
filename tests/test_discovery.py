# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Core discovery: chain sweep, manager slots, and bridge safety."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from fcapz import _version_tuple
from fcapz.analyzer import CORE_MANAGER_CORE_ID, ELA_CORE_ID, Analyzer, CoreManager
from fcapz.discovery import discover_cores
from fcapz.eio import EIO_CORE_ID, discover_eio
from fcapz.rpc import RpcServer
from fcapz.transport import Transport

_MAJOR, _MINOR, _ = _version_tuple()


def _version(core_id: int) -> int:
    return ((_MAJOR & 0xFF) << 24) | ((_MINOR & 0xFF) << 16) | core_id


def _ela_regs() -> dict[int, int]:
    return {
        0x0000: _version(ELA_CORE_ID),
        0x000C: 8,            # SAMPLE_W
        0x0010: 1024,         # DEPTH
        0x00A4: 1,            # NUM_CHAN
        0x003C: 0x0001_0164,  # FEATURES
        0x00C4: 0,            # TIMESTAMP_W
        0x00B8: 1,            # NUM_SEGMENTS
        0x00E0: 0x3_01FF,     # COMPARE_CAPS
    }


def _eio_regs(in_w: int = 8, out_w: int = 4) -> dict[int, int]:
    return {0x0000: _version(EIO_CORE_ID), 0x0004: in_w, 0x0008: out_w}


class _Plain:
    """A standalone register core (ELA, EIO, or ELA + EIO behind a mux)."""

    def __init__(self, regs: dict[int, int]):
        self.regs = regs

    def read(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write(self, addr: int, value: int) -> None:
        self.regs[addr] = value


class _Hub:
    """A core manager over per-slot register banks."""

    def __init__(self, slots: list[dict[int, int]], *, active: int = 0,
                 descriptors: bool = True):
        self.slots = slots
        self.mgr = {
            0xF000: _version(CORE_MANAGER_CORE_ID),
            0xF004: len(slots),
            0xF008: active,
            0xF00C: 0,
            0xF010: 0x3 if descriptors else 0x1,
            0xF014: 0,
        }

    def read(self, addr: int) -> int:
        if addr == 0xF018:
            return self.slots[self.mgr[0xF014]][0x0000] & 0xFFFF
        if addr == 0xF01C:
            return 0
        if addr in self.mgr:
            return self.mgr[addr]
        return self.slots[self.mgr[0xF008]].get(addr, 0)

    def write(self, addr: int, value: int) -> None:
        if addr in (0xF008, 0xF014):
            if int(value) < len(self.slots):
                self.mgr[addr] = int(value)
            return
        self.slots[self.mgr[0xF008]][addr] = value


class _Bridge:
    """An EJTAG bridge as the register protocol sees it: TDO reads 0."""

    def read(self, addr: int) -> int:
        return 0

    def write(self, addr: int, value: int) -> None:
        pass


class MultiChainTransport(Transport):
    """One device per chain; a missing chain fails its first access, as a
    missing ``sld_virtual_jtag`` instance does."""

    def __init__(self, devices: dict[int, object]):
        self.devices = devices
        self._active_chain = 1
        self.log: list[tuple[int, str, int]] = []

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        self._active_chain = int(chain)

    def discovery_chains(self) -> tuple[int, ...]:
        return (1, 2, 3, 4, 5)

    def _device(self):
        dev = self.devices.get(self._active_chain)
        if dev is None:
            raise RuntimeError("virtual JTAG instance cannot be found")
        return dev

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        return 0

    def read_reg(self, addr: int) -> int:
        dev = self._device()
        self.log.append((self._active_chain, "r", addr))
        return int(dev.read(addr))

    def write_reg(self, addr: int, value: int) -> None:
        dev = self._device()
        self.log.append((self._active_chain, "w", addr))
        dev.write(addr, value)

    def read_block(self, addr: int, words: int) -> list[int]:
        return [self.read_reg(addr + 4 * i) for i in range(words)]

    def accesses(self, chain: int) -> list[tuple[str, int]]:
        return [(op, addr) for c, op, addr in self.log if c == chain]


class _FakeBridge:
    """Stands in for a bridge controller: answers on its own chains only."""

    chains: dict[int, dict] = {}
    probed: list[int] = []

    def __init__(self, transport, chain: int):
        self.chain = chain

    def attach(self) -> dict:
        type(self).probed.append(self.chain)
        info = type(self).chains.get(self.chain)
        if info is None:
            raise RuntimeError("not this bridge")
        return info


class _FakeUart(_FakeBridge):
    chains = {3: {"core_id": 0x4A55, "version_major": _MAJOR, "version_minor": _MINOR}}
    probed: list[int] = []


class _FakeAxi(_FakeBridge):
    chains = {4: {"core_id": 0x4A58, "version_major": _MAJOR, "version_minor": _MINOR,
                  "addr_w": 32, "data_w": 32, "fifo_depth": 16}}
    probed: list[int] = []


def _board(*, hub_descriptors: bool = True) -> MultiChainTransport:
    """USER1 hub (EIO left active, then an ELA), USER2 ELA + mux EIO,
    USER3 UART, USER4 AXI bridge, no instance 5."""
    mux = _ela_regs()
    mux.update({0x8000 | a: v for a, v in _eio_regs(2, 6).items()})
    return MultiChainTransport({
        1: _Hub([_eio_regs(), _ela_regs()], active=0, descriptors=hub_descriptors),
        2: _Plain(mux),
        3: _Bridge(),
        4: _Bridge(),
    })


def _bridges_patched():
    _FakeUart.probed = []
    _FakeAxi.probed = []
    return (
        patch("fcapz.discovery.EjtagUartController", _FakeUart),
        patch("fcapz.discovery.EjtagAxiController", _FakeAxi),
    )


def _only_safe_reads(test: unittest.TestCase, t: MultiChainTransport, chain: int) -> None:
    """A chain nobody identified sees reads below 0x2000 only: in the bridges'
    command field those are NOPs."""
    for op, addr in t.accesses(chain):
        test.assertEqual(op, "r", f"chain {chain}: write to 0x{addr:04X}")
        test.assertLess(addr, 0x2000, f"chain {chain}: read of 0x{addr:04X}")


class DiscoverCoresTests(unittest.TestCase):
    def _discover(self, t: MultiChainTransport, **kw):
        uart, axi = _bridges_patched()
        with uart, axi:
            return discover_cores(t, **kw)

    def test_finds_every_core_on_every_chain(self):
        t = _board()
        found = self._discover(t)
        got = [(e["type"], e["chain"], e["instance"], e["base_addr"]) for e in found]
        self.assertEqual(got, [
            ("manager", 1, None, 0),
            ("eio", 1, 0, 0),
            ("ela", 1, 1, 0),
            ("ela", 2, None, 0),
            ("eio", 2, None, 0x8000),
            ("ejtag_uart", 3, None, 0),
            ("ejtag_axi", 4, None, 0),
        ])
        self.assertEqual(found[0]["info"]["num_slots"], 2)
        self.assertEqual(found[1]["info"], {"in_w": 8, "out_w": 4})
        self.assertEqual(found[2]["info"]["sample_width"], 8)
        self.assertEqual(found[4]["info"], {"in_w": 2, "out_w": 6})
        self.assertEqual(found[6]["info"]["fifo_depth"], 16)

    def test_bridge_chains_see_only_reads_below_0x2000(self):
        t = _board()
        self._discover(t)
        for chain in (3, 4):
            self.assertTrue(t.accesses(chain))
            _only_safe_reads(self, t, chain)

    def test_register_chains_never_get_bridge_probes(self):
        t = _board()
        self._discover(t)
        self.assertEqual(_FakeUart.probed, [3, 4])
        self.assertEqual(_FakeAxi.probed, [4])

    def test_active_slot_is_put_back(self):
        t = _board()
        self._discover(t)
        self.assertEqual(t.devices[1].mgr[0xF008], 0)

    def test_hub_without_descriptors_is_walked_and_put_back(self):
        t = _board(hub_descriptors=False)
        found = self._discover(t, chains=(1,))
        self.assertEqual([(e["type"], e["instance"]) for e in found],
                         [("manager", None), ("eio", 0), ("ela", 1)])
        self.assertEqual(t.devices[1].mgr[0xF008], 0)

    def test_bridges_can_be_skipped(self):
        t = _board()
        found = self._discover(t, bridges=False)
        self.assertNotIn("ejtag_uart", [e["type"] for e in found])
        self.assertEqual(_FakeUart.probed, [])
        self.assertEqual(_FakeAxi.probed, [])

    def test_missing_instance_is_skipped(self):
        t = _board()
        found = self._discover(t, chains=(5, 2))
        self.assertEqual([e["chain"] for e in found], [2, 2])

    def test_chain_1_is_selected_on_return(self):
        t = _board()
        self._discover(t)
        self.assertEqual(t._active_chain, 1)


class ProbeOptionalManagerTests(unittest.TestCase):
    def test_eio_left_active_selects_the_first_ela_slot(self):
        t = _board()
        analyzer = Analyzer(t, chain=1)
        info = analyzer.probe_optional()
        self.assertIsNotNone(info)
        self.assertEqual(info["core_id"], ELA_CORE_ID)
        self.assertEqual(analyzer.instance, 1)
        self.assertEqual(t.devices[1].mgr[0xF008], 1)

    def test_probe_stays_strict(self):
        t = _board()
        with self.assertRaisesRegex(RuntimeError, "identity check failed"):
            Analyzer(t, chain=1).probe()
        self.assertEqual(t.devices[1].mgr[0xF008], 0)

    def test_an_explicit_slot_is_not_moved(self):
        t = _board()
        analyzer = Analyzer(t, chain=1, instance=0)
        self.assertIsNone(analyzer.probe_optional())
        self.assertEqual(analyzer.instance, 0)
        self.assertEqual(t.devices[1].mgr[0xF008], 0)

    def test_bridge_chain_is_only_read_below_0x2000(self):
        t = _board()
        self.assertIsNone(Analyzer(t, chain=4).probe_optional())
        _only_safe_reads(self, t, 4)

    def test_manager_without_an_ela_returns_none(self):
        t = MultiChainTransport({1: _Hub([_eio_regs(), _eio_regs()])})
        analyzer = Analyzer(t, chain=1)
        self.assertIsNone(analyzer.probe_optional())
        self.assertIsNone(analyzer.instance)


class SlotCoreIdsTests(unittest.TestCase):
    def test_descriptors(self):
        t = _board()
        self.assertEqual(CoreManager(t).slot_core_ids(), [EIO_CORE_ID, ELA_CORE_ID])
        self.assertFalse([a for _c, op, a in t.log if op == "w" and a == 0xF008])

    def test_without_descriptors_restores_the_active_slot(self):
        t = _board(hub_descriptors=False)
        t.devices[1].mgr[0xF008] = 1
        self.assertEqual(CoreManager(t).slot_core_ids(), [EIO_CORE_ID, ELA_CORE_ID])
        self.assertEqual(t.devices[1].mgr[0xF008], 1)


class DiscoverEioSafetyTests(unittest.TestCase):
    def test_high_base_is_read_only_on_register_chains(self):
        t = MultiChainTransport({1: _Plain(_ela_regs()), 4: _Bridge()})
        self.assertIsNone(discover_eio(t, chains=(4, 1)))
        _only_safe_reads(self, t, 4)
        self.assertIn(("r", 0x8000), t.accesses(1))

    def test_finds_the_mux_eio(self):
        t = _board()
        eio = discover_eio(t, chains=(2,))
        self.assertIsNotNone(eio)
        self.assertEqual((eio.bscan_chain, eio._base_addr), (2, 0x8000))  # noqa: SLF001


class RpcDiscoverTests(unittest.TestCase):
    def _server(self, t: MultiChainTransport) -> RpcServer:
        srv = RpcServer()
        srv._analyzer = Analyzer(t, chain=1)  # noqa: SLF001
        return srv

    def test_discover_lists_every_chain_and_restores_the_session_chain(self):
        t = _board()
        srv = self._server(t)
        uart, axi = _bridges_patched()
        with uart, axi:
            r = srv.handle({"cmd": "discover"})
        self.assertTrue(r["ok"])
        self.assertEqual([c["type"] for c in r["cores"]],
                         ["manager", "eio", "ela", "ela", "eio", "ejtag_uart", "ejtag_axi"])
        self.assertEqual(t._active_chain, 1)

    def test_discover_honours_chains(self):
        t = _board()
        srv = self._server(t)
        uart, axi = _bridges_patched()
        with uart, axi:
            r = srv.handle({"cmd": "discover", "chains": [2]})
        self.assertEqual([c["chain"] for c in r["cores"]], [2, 2])

    def test_list_cores_reports_the_manager_slots(self):
        t = _board()
        srv = self._server(t)
        srv._analyzer.probe_optional()  # noqa: SLF001 - selects ELA slot 1
        r = srv.handle({"cmd": "list_cores"})
        got = [(c["type"], c["chain"], c.get("instance")) for c in r["cores"]]
        # The connected ELA, then the manager and its other slot; the EIO
        # sweep is skipped since the manager's EIO slot is listed.
        self.assertEqual(got, [
            ("ela", 1, 1), ("manager", 1, None), ("eio", 1, 0), ("ela", 2, None),
        ])
        self.assertEqual(t.devices[1].mgr[0xF008], 1)


    def test_list_cores_on_a_bridge_chain_reads_only_below_0x2000(self):
        # A session connected to the bridge chain: list_cores must not read
        # the manager block there.
        t = _board()
        srv = RpcServer()
        srv._analyzer = Analyzer(t, chain=4)  # noqa: SLF001
        srv.handle({"cmd": "list_cores"})
        _only_safe_reads(self, t, 4)


class CliDiscoverTests(unittest.TestCase):
    def test_prints_the_core_list(self):
        from fcapz import cli

        t = _board()
        uart, axi = _bridges_patched()
        out = io.StringIO()
        argv = ["fcapz", "--backend", "hw_server", "discover", "--chains", "1", "2"]
        with uart, axi, patch.object(sys, "argv", argv), \
                patch("fcapz.cli._make_transport", return_value=t), redirect_stdout(out):
            self.assertEqual(cli.main(), 0)
        cores = json.loads(out.getvalue())
        self.assertEqual([(c["type"], c["chain"]) for c in cores],
                         [("manager", 1), ("eio", 1), ("ela", 1), ("ela", 2), ("eio", 2)])


if __name__ == "__main__":
    unittest.main()
