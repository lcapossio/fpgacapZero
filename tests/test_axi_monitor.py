# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host tests for the AxiMonitor helper, against a fake transport that presents
the AM identity/geometry registers and a flattened capture word."""

from __future__ import annotations

import pytest

from fcapz.analyzer import Analyzer
from fcapz.axi_monitor import AxiMonitor, AxiMonitorError
from fcapz.transport import Transport

AM_ID = (0x414D << 16) | (1 << 8) | 0  # "AM", PROTO=AXI4LITE, flags=0
GEOM = (0x1F << 20) | (0 << 16) | (32 << 8) | 32  # cap=0x1F, id_w=0, data_w=32, addr_w=32


class FakeMon(Transport):
    def __init__(self, regs: dict[int, int]) -> None:
        self.regs = dict(regs)
        self.active_chain = 1

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        self.active_chain = chain

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


def _mon(extra: dict[int, int] | None = None) -> AxiMonitor:
    regs = {0x00E8: AM_ID, 0x00EC: GEOM}
    if extra:
        regs.update(extra)
    return AxiMonitor(Analyzer(FakeMon(regs)))


def test_detects_axi_monitor():
    m = _mon()
    assert m.present
    assert m.identity() == AM_ID


def test_absent_when_magic_missing():
    m = AxiMonitor(Analyzer(FakeMon({0x00E8: 0x4C41, 0x00EC: 0})))  # plain ELA "LA"
    assert not m.present
    assert m.identity() is None
    with pytest.raises(AxiMonitorError):
        m.geometry()


def test_geometry_decode():
    g = _mon().geometry()
    assert (g.addr_w, g.data_w, g.id_w, g.cap_channels) == (32, 32, 0, 0x1F)
    assert g.proto == "AXI4LITE"
    assert g.sample_width == 152  # must match fcapz_axi_mon SAMPLE_W


def test_probe_map_matches_rtl_layout():
    pm = _mon().probe_map()
    fields = {p.name: (p.lsb, p.width) for p in pm.probes}
    assert fields["awaddr"] == (0, 32)
    assert fields["awvalid"] == (35, 1)
    assert fields["bresp"] == (75, 2)
    assert fields["rready"] == (151, 1)
    assert pm.sample_width == 152


def test_decode_sample():
    m = _mon()
    value = 0x4000_0000 | (1 << 35)  # awaddr=0x40000000, awvalid=1
    fields = m.decode_sample(value)
    assert fields["awaddr"] == 0x4000_0000
    assert fields["awvalid"] == 1
    assert fields["wvalid"] == 0


def test_write_addr_capture_config():
    cfg = _mon().write_addr_capture_config(0x4000_0000, pretrigger=4, posttrigger=10)
    assert cfg.trigger.mode == "value_match"
    assert cfg.trigger.value == 0x4000_0000
    assert cfg.trigger.mask == 0xFFFF_FFFF
    assert cfg.sample_width == 152
    assert cfg.pretrigger == 4 and cfg.posttrigger == 10
    assert any(p.name == "awaddr" for p in cfg.probes)
