# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import atexit
import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.binary import BinaryValue
from cocotb.clock import Clock
from cocotb.triggers import Edge, RisingEdge, FallingEdge, Timer
from cocotbext.axi import AxiBus, AxiRam


class FunctionalCoverage:
    def __init__(self, *, env_var: str, run_env_var: str, bins: tuple[str, ...]) -> None:
        self.env_var = env_var
        self.run_env_var = run_env_var
        self.bins = dict.fromkeys(bins, 0)

    def hit(self, name: str) -> None:
        self.bins[name] += 1

    def write(self) -> None:
        path = os.environ.get(self.env_var)
        if not path:
            return
        covered = sum(1 for count in self.bins.values() if count)
        payload = {
            "run": os.environ.get(self.run_env_var, "manual"),
            "covered_bins": covered,
            "total_bins": len(self.bins),
            "percent": round((covered / len(self.bins)) * 100.0, 2),
            "bins": self.bins,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, indent=2) + "\n")


EIO_FUNCTIONAL_COVERAGE = FunctionalCoverage(
    env_var="EIO_COCOTB_COVERAGE_JSON",
    run_env_var="EIO_COCOTB_RUN",
    bins=(
        "version",
        "width_registers",
        "output_write_low_word",
        "output_readback_low_word",
        "probe_out_low_word",
        "output_clear",
        "output_all_ones",
        "reset_clears_output",
        "input_sync_low_word",
        "input_update",
        "invalid_read_zero",
        "bit_set_clear",
        "input_high_word",
        "input_high_padding_zero",
        "output_high_word",
        "probe_out_high_word",
        "random_output_patterns",
        "random_input_patterns",
        "invalid_write_ignored",
        "reset_during_stress",
    ),
)

atexit.register(EIO_FUNCTIONAL_COVERAGE.write)


async def tick(signal) -> None:
    await RisingEdge(signal)
    await Timer(1, units="ns")


async def _tap_idle(tap, tick_fn, n: int, *,
                    sel: str, capture: str, shift: str, update: str, tdi: str) -> None:
    getattr(tap, sel).value = 0
    getattr(tap, capture).value = 0
    getattr(tap, shift).value = 0
    getattr(tap, update).value = 0
    getattr(tap, tdi).value = 0
    for _ in range(n):
        await tick_fn()


async def _tap_shift_frame(tap, tdo, tick_fn, frame: int, *,
                           sel: str, capture: str, shift: str, update: str, tdi: str,
                           bits: int = 49, capture_bits: int = 32) -> int:
    captured = 0
    getattr(tap, sel).value = 1
    getattr(tap, capture).value = 1
    await tick_fn()
    getattr(tap, capture).value = 0
    getattr(tap, shift).value = 1
    for i in range(bits):
        getattr(tap, tdi).value = (frame >> i) & 1
        if i < capture_bits and int(tdo.value):
            captured |= 1 << i
        await tick_fn()
    getattr(tap, shift).value = 0
    getattr(tap, tdi).value = 0
    getattr(tap, update).value = 1
    await tick_fn()
    getattr(tap, update).value = 0
    getattr(tap, sel).value = 0
    return captured


async def _tap_shift_burst(tap, tdo, tick_fn, *,
                           sel: str, capture: str, shift: str, update: str, tdi: str,
                           bits: int = 256) -> int:
    captured = 0
    getattr(tap, sel).value = 1
    getattr(tap, capture).value = 1
    await tick_fn()
    getattr(tap, capture).value = 0
    getattr(tap, shift).value = 1
    for i in range(bits):
        getattr(tap, tdi).value = 0
        if int(tdo.value):
            captured |= 1 << i
        await tick_fn()
    getattr(tap, shift).value = 0
    getattr(tap, update).value = 1
    await tick_fn()
    getattr(tap, update).value = 0
    getattr(tap, sel).value = 0
    return captured


_DEFAULT_TAP_NAMES = dict(sel="sel", capture="capture", update="update", tdi="tdi")


async def idle_tap(dut, n: int, *, shift_name: str = "shift_en") -> None:
    await _tap_idle(dut, lambda: tick(dut.tck), n, shift=shift_name, **_DEFAULT_TAP_NAMES)


def make_frame(addr: int, data: int, write: bool) -> int:
    return ((1 if write else 0) << 48) | ((addr & 0xFFFF) << 32) | (data & 0xFFFF_FFFF)


async def scan_reg(dut, frame: int, *, shift_name: str = "shift_en", tdo=None) -> int:
    return await _tap_shift_frame(
        dut, tdo if tdo is not None else dut.tdo, lambda: tick(dut.tck), frame,
        shift=shift_name, **_DEFAULT_TAP_NAMES,
    )


async def scan_burst(dut, *, shift_name: str = "shift_en", tdo=None, bits: int = 256) -> int:
    return await _tap_shift_burst(
        dut, tdo if tdo is not None else dut.tdo, lambda: tick(dut.tck),
        shift=shift_name, bits=bits, **_DEFAULT_TAP_NAMES,
    )


def sample_at(bits: int, index: int, width: int = 8) -> int:
    return (bits >> (index * width)) & ((1 << width) - 1)


def width_mask(width: int) -> int:
    return (1 << width) - 1 if width > 0 else 0


def word_mask(width: int, word: int) -> int:
    bits = max(0, min(32, width - word * 32))
    return width_mask(bits)


def word_at(value: int, width: int, word: int) -> int:
    return (value >> (word * 32)) & word_mask(width, word)


async def jtag_write(dut, addr: int, data: int) -> None:
    await RisingEdge(dut.jtag_clk)
    dut.jtag_addr.value = addr
    dut.jtag_wdata.value = data
    dut.jtag_wr_en.value = 1
    await RisingEdge(dut.jtag_clk)
    dut.jtag_wr_en.value = 0


async def jtag_read(dut, addr: int, settle: int = 8) -> int:
    await RisingEdge(dut.jtag_clk)
    dut.jtag_addr.value = addr
    if hasattr(dut, "jtag_rd_en"):
        dut.jtag_rd_en.value = 1
        await RisingEdge(dut.jtag_clk)
        dut.jtag_rd_en.value = 0
        for _ in range(settle):
            await RisingEdge(dut.jtag_clk)
    else:
        await RisingEdge(dut.jtag_clk)
    return int(dut.jtag_rdata.value)


async def arm_ela(dut) -> None:
    await jtag_write(dut, 0x0004, 1)
    for _ in range(80):
        await RisingEdge(dut.sample_clk)
        if int(dut.armed_out.value):
            return
    raise AssertionError("ELA did not arm")


@cocotb.test()
async def trig_compare_light(dut):
    cases = (
        (0x12, 0x10, 0x12, 0xFF, 0, 1),
        (0x12, 0x10, 0x10, 0xFF, 1, 1),
        (0x01, 0x00, 0x00, 0xFF, 6, 1),
        (0x00, 0x01, 0x00, 0xFF, 7, 1),
        (0x5D, 0x55, 0x00, 0xFF, 8, 1),
        (0x05, 0x10, 0x10, 0xFF, 2, 0),
        (0x20, 0x10, 0x10, 0xFF, 3, 0),
        (0x10, 0x10, 0x10, 0xFF, 4, 0),
        (0x10, 0x10, 0x10, 0xFF, 5, 0),
    )
    for probe, prev, value, mask, mode, expected in cases:
        dut.probe.value = probe
        dut.probe_prev.value = prev
        dut.value.value = value
        dut.mask.value = mask
        dut.mode.value = mode
        await Timer(1, units="ns")
        assert int(dut.hit.value) == expected


@cocotb.test()
async def trig_compare_full(dut):
    cases = (
        (0x12, 0x10, 0x12, 0xFF, 0, 1),
        (0x12, 0x10, 0x10, 0xFF, 1, 1),
        (0x01, 0x00, 0x00, 0xFF, 6, 1),
        (0x00, 0x01, 0x00, 0xFF, 7, 1),
        (0x5D, 0x55, 0x00, 0xFF, 8, 1),
        (0x05, 0x10, 0x10, 0xFF, 2, 1),
        (0x20, 0x10, 0x10, 0xFF, 3, 1),
        (0x10, 0x10, 0x10, 0xFF, 4, 1),
        (0x10, 0x10, 0x10, 0xFF, 5, 1),
    )
    for probe, prev, value, mask, mode, expected in cases:
        dut.probe.value = probe
        dut.probe_prev.value = prev
        dut.value.value = value
        dut.mask.value = mask
        dut.mode.value = mode
        await Timer(1, units="ns")
        assert int(dut.hit.value) == expected


async def burst_mem_driver(dut) -> None:
    while True:
        await RisingEdge(dut.tck)
        dut.sample_data.value = int(dut.mem_addr.value) & 0xFF
        if len(dut.timestamp_data) > 1:
            dut.timestamp_data.value = 0xA500_0000 | int(dut.mem_addr.value)


async def start_burst(dut, ptr: int, timestamp: bool) -> None:
    dut.sel.value = 0
    dut.burst_ptr_in.value = ptr
    dut.burst_timestamp.value = int(timestamp)
    dut.burst_start.value = 0 if int(dut.burst_start.value) else 1
    await tick(dut.tck)


def assert_sample_sequence(bits: int, start: int, count: int = 32) -> None:
    for i in range(count):
        assert sample_at(bits, i) == ((start + i) & 0xFF)


def assert_timestamp_sequence(bits: int, start: int, count: int = 8) -> None:
    for i in range(count):
        got = sample_at(bits, i, 32)
        exp = 0xA500_0000 | ((start + i) & 0xFF)
        assert got == exp


@cocotb.test()
async def jtag_burst_read_protocol(dut):
    cocotb.start_soon(Clock(dut.tck, 10, units="ns").start())
    cocotb.start_soon(burst_mem_driver(dut))
    dut.arst.value = 1
    dut.tdi.value = 0
    dut.capture.value = 0
    dut.shift_en.value = 0
    dut.update.value = 0
    dut.sel.value = 0
    dut.sample_data.value = 0
    dut.timestamp_data.value = 0
    dut.burst_start.value = 0
    dut.burst_timestamp.value = 0
    dut.burst_ptr_in.value = 0
    await idle_tap(dut, 4)
    dut.arst.value = 0
    await idle_tap(dut, 4)

    await start_burst(dut, 42, False)
    await idle_tap(dut, 80)
    await scan_burst(dut)
    scan = await scan_burst(dut)
    assert_sample_sequence(scan, 42)
    scan = await scan_burst(dut)
    assert_sample_sequence(scan, 74)

    await start_burst(dut, 250, False)
    await idle_tap(dut, 80)
    await scan_burst(dut)
    scan = await scan_burst(dut)
    assert_sample_sequence(scan, 250)

    await start_burst(dut, 64, True)
    await idle_tap(dut, 80)
    await scan_burst(dut)
    scan = await scan_burst(dut)
    assert_timestamp_sequence(scan, 64)


async def pipe_bus_monitor(dut) -> None:
    while True:
        await RisingEdge(dut.tck)
        dut.sample_data.value = int(dut.mem_addr.value) & 0xFF
        dut.timestamp_data.value = 0xA500_0000 | int(dut.mem_addr.value)
        if int(dut.reg_wr_en.value) and int(dut.reg_addr.value) == 0x002C:
            dut.burst_ptr_in.value = 42
            dut.burst_timestamp.value = (int(dut.reg_wdata.value) >> 31) & 1
            dut.burst_start.value = 0 if int(dut.burst_start.value) else 1


@cocotb.test()
async def jtag_pipe_iface_protocol(dut):
    cocotb.start_soon(Clock(dut.tck, 10, units="ns").start())
    cocotb.start_soon(pipe_bus_monitor(dut))
    dut.arst.value = 1
    dut.tdi.value = 0
    dut.capture.value = 0
    dut.shift_en.value = 0
    dut.update.value = 0
    dut.sel.value = 0
    dut.reg_rdata.value = 0x1234_5678
    dut.sample_data.value = 0
    dut.timestamp_data.value = 0
    dut.burst_start.value = 0
    dut.burst_timestamp.value = 0
    dut.burst_ptr_in.value = 0
    await idle_tap(dut, 4)
    dut.arst.value = 0
    await idle_tap(dut, 4)

    await scan_reg(dut, make_frame(0x0024, 0xCAFE_BABE, True))
    assert int(dut.reg_addr.value) == 0x0024
    assert int(dut.reg_wdata.value) == 0xCAFE_BABE

    await scan_reg(dut, make_frame(0, 0, False))
    await idle_tap(dut, 4)
    captured = await scan_reg(dut, make_frame(0, 0, False))
    assert captured == 0x1234_5678

    await scan_reg(dut, make_frame(0x002C, 0, True))
    await idle_tap(dut, 80)
    await scan_burst(dut)
    first = await scan_burst(dut)
    second = await scan_burst(dut)
    assert_sample_sequence(first, 42)
    assert_sample_sequence(second, 74)


@cocotb.test()
async def jtag_pipe_iface_segmented_alignment(dut):
    cocotb.start_soon(Clock(dut.tck, 10, units="ns").start())
    dut.arst.value = 1
    dut.tdi.value = 0
    dut.capture.value = 0
    dut.shift_en.value = 0
    dut.update.value = 0
    dut.sel.value = 0
    dut.reg_rdata.value = 0
    dut.sample_data.value = 0
    dut.timestamp_data.value = 0
    dut.burst_start.value = 0
    dut.burst_timestamp.value = 0
    dut.burst_ptr_in.value = 256
    await idle_tap(dut, 4)
    dut.arst.value = 0
    await idle_tap(dut, 4)
    dut.sel.value = 1
    dut.capture.value = 1
    dut.burst_start.value = 1
    await tick(dut.tck)
    dut.capture.value = 0
    dut.sel.value = 0
    await idle_tap(dut, 4)
    assert (int(dut.mem_addr.value) >> 8) == 1


@cocotb.test()
async def fcapz_eio_registers(dut):
    in_w = len(dut.probe_in)
    out_w = len(dut.probe_out)
    out_low_mask = word_mask(out_w, 0)

    cocotb.start_soon(Clock(dut.jtag_clk, 14, units="ns").start())
    dut.jtag_rst.value = 1
    dut.probe_in.value = 0
    dut.jtag_wr_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    for _ in range(3):
        await RisingEdge(dut.jtag_clk)
    dut.jtag_rst.value = 0
    for _ in range(2):
        await RisingEdge(dut.jtag_clk)

    version = await jtag_read(dut, 0x0000, settle=0)
    assert version & 0xFFFF == 0x494F
    EIO_FUNCTIONAL_COVERAGE.hit("version")
    assert await jtag_read(dut, 0x0004, settle=0) == in_w
    assert await jtag_read(dut, 0x0008, settle=0) == out_w
    EIO_FUNCTIONAL_COVERAGE.hit("width_registers")

    await jtag_write(dut, 0x0100, 0xABC)
    assert await jtag_read(dut, 0x0100, settle=0) == 0xABC
    EIO_FUNCTIONAL_COVERAGE.hit("output_write_low_word")
    EIO_FUNCTIONAL_COVERAGE.hit("output_readback_low_word")
    assert int(dut.probe_out.value) & out_low_mask == 0xABC & out_low_mask
    EIO_FUNCTIONAL_COVERAGE.hit("probe_out_low_word")

    await jtag_write(dut, 0x0100, 0)
    assert await jtag_read(dut, 0x0100, settle=0) == 0
    assert int(dut.probe_out.value) == 0
    EIO_FUNCTIONAL_COVERAGE.hit("output_clear")

    await jtag_write(dut, 0x0100, 0xFFFF_FFFF)
    assert await jtag_read(dut, 0x0100, settle=0) == 0xFFFF_FFFF
    assert int(dut.probe_out.value) == out_low_mask
    EIO_FUNCTIONAL_COVERAGE.hit("output_all_ones")

    if out_w > 32:
        high = 0xDEAD_BEEF
        await jtag_write(dut, 0x0104, high)
        assert await jtag_read(dut, 0x0104, settle=0) == high
        expected_probe = out_low_mask | ((high & word_mask(out_w, 1)) << 32)
        assert int(dut.probe_out.value) == expected_probe
        EIO_FUNCTIONAL_COVERAGE.hit("output_high_word")
        EIO_FUNCTIONAL_COVERAGE.hit("probe_out_high_word")

    dut.jtag_rst.value = 1
    for _ in range(2):
        await RisingEdge(dut.jtag_clk)
    dut.jtag_rst.value = 0
    for _ in range(2):
        await RisingEdge(dut.jtag_clk)
    assert await jtag_read(dut, 0x0100, settle=0) == 0
    assert int(dut.probe_out.value) == 0
    EIO_FUNCTIONAL_COVERAGE.hit("reset_clears_output")

    input_value = 0xCAFE & width_mask(in_w)
    dut.probe_in.value = input_value
    for _ in range(4):
        await RisingEdge(dut.jtag_clk)
    assert await jtag_read(dut, 0x0010, settle=0) == word_at(input_value, in_w, 0)
    EIO_FUNCTIONAL_COVERAGE.hit("input_sync_low_word")

    input_value = 0x1234 & width_mask(in_w)
    dut.probe_in.value = input_value
    for _ in range(4):
        await RisingEdge(dut.jtag_clk)
    assert await jtag_read(dut, 0x0010, settle=0) == word_at(input_value, in_w, 0)
    EIO_FUNCTIONAL_COVERAGE.hit("input_update")

    if in_w > 32:
        input_value = ((0xAB & word_mask(in_w, 1)) << 32) | 0xCAFE_BABE
        dut.probe_in.value = input_value
        for _ in range(4):
            await RisingEdge(dut.jtag_clk)
        assert await jtag_read(dut, 0x0010, settle=0) == word_at(input_value, in_w, 0)
        assert await jtag_read(dut, 0x0014, settle=0) == word_at(input_value, in_w, 1)
        assert await jtag_read(dut, 0x0014, settle=0) & ~word_mask(in_w, 1) == 0
        EIO_FUNCTIONAL_COVERAGE.hit("input_high_word")
        EIO_FUNCTIONAL_COVERAGE.hit("input_high_padding_zero")

    assert await jtag_read(dut, 0x0200, settle=0) == 0
    EIO_FUNCTIONAL_COVERAGE.hit("invalid_read_zero")

    await jtag_write(dut, 0x0100, 0)
    data = await jtag_read(dut, 0x0100, settle=0)
    await jtag_write(dut, 0x0100, data | 0x8)
    data = await jtag_read(dut, 0x0100, settle=0)
    assert data & 0x8
    assert data & 0xFFFF_FFF7 == 0
    await jtag_write(dut, 0x0100, data & ~0x8)
    assert not (await jtag_read(dut, 0x0100, settle=0) & 0x8)
    EIO_FUNCTIONAL_COVERAGE.hit("bit_set_clear")

    rng = random.Random((in_w << 16) | out_w)
    out_words = (out_w + 31) // 32
    for _ in range(8):
        expected_probe = 0
        written_words = []
        for word in range(out_words):
            value = rng.randrange(1 << 32)
            written_words.append(value)
            await jtag_write(dut, 0x0100 + word * 4, value)
            expected_probe |= (value & word_mask(out_w, word)) << (word * 32)
        for word, value in enumerate(written_words):
            assert await jtag_read(dut, 0x0100 + word * 4, settle=0) == value
        assert int(dut.probe_out.value) == expected_probe

        await jtag_write(dut, 0x0100 + out_words * 4, rng.randrange(1 << 32))
        assert int(dut.probe_out.value) == expected_probe
        EIO_FUNCTIONAL_COVERAGE.hit("invalid_write_ignored")
    EIO_FUNCTIONAL_COVERAGE.hit("random_output_patterns")

    in_words = (in_w + 31) // 32
    for _ in range(8):
        input_value = rng.randrange(1 << in_w)
        dut.probe_in.value = input_value
        for _ in range(4):
            await RisingEdge(dut.jtag_clk)
        for word in range(in_words):
            got = await jtag_read(dut, 0x0010 + word * 4, settle=0)
            assert got == word_at(input_value, in_w, word)
    EIO_FUNCTIONAL_COVERAGE.hit("random_input_patterns")

    dut.jtag_rst.value = 1
    for _ in range(2):
        await RisingEdge(dut.jtag_clk)
    dut.jtag_rst.value = 0
    for _ in range(2):
        await RisingEdge(dut.jtag_clk)
    assert int(dut.probe_out.value) == 0
    for word in range(out_words):
        assert await jtag_read(dut, 0x0100 + word * 4, settle=0) == 0
    EIO_FUNCTIONAL_COVERAGE.hit("reset_during_stress")


async def manager_write(dut, addr: int, data: int) -> None:
    await FallingEdge(dut.jtag_clk)
    dut.jtag_addr.value = addr
    dut.jtag_wdata.value = data
    dut.jtag_wr_en.value = 1
    dut.jtag_rd_en.value = 0
    await FallingEdge(dut.jtag_clk)
    dut.jtag_wr_en.value = 0


async def manager_read(dut, addr: int) -> int:
    await FallingEdge(dut.jtag_clk)
    dut.jtag_addr.value = addr
    dut.jtag_rd_en.value = 1
    dut.jtag_wr_en.value = 0
    await Timer(1, units="ns")
    data = int(dut.jtag_rdata.value)
    await FallingEdge(dut.jtag_clk)
    dut.jtag_rd_en.value = 0
    return data


@cocotb.test()
async def fcapz_core_manager_mux(dut):
    cocotb.start_soon(Clock(dut.jtag_clk, 10, units="ns").start())
    dut.jtag_rst.value = 1
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    dut.slot_rdata.value = (0x2222_0000 << 64) | (0x1111_0000 << 32)
    dut.slot_burst_rd_data.value = (0xC2 << 16) | (0xB1 << 8) | 0xA0
    dut.slot_burst_rd_ts_data.value = (0x2 << 8) | (0x1 << 4)
    dut.slot_burst_start.value = 0b111
    dut.slot_burst_timestamp.value = 0b101
    dut.slot_burst_start_ptr.value = (0xC << 8) | (0xB << 4) | 0xA
    for _ in range(3):
        await FallingEdge(dut.jtag_clk)
    dut.jtag_rst.value = 0
    await FallingEdge(dut.jtag_clk)

    assert await manager_read(dut, 0xF000) == 0x0004_434D
    assert await manager_read(dut, 0xF004) == 3
    assert await manager_read(dut, 0xF008) == 0
    assert await manager_read(dut, 0xEFFF) == 0
    assert int(dut.slot_rd_en.value) & 1
    assert await manager_read(dut, 0xF000) == 0x0004_434D
    assert int(dut.slot_rd_en.value) == 0

    await manager_write(dut, 0xF014, 2)
    assert await manager_read(dut, 0xF018) == 0x494F
    assert await manager_read(dut, 0xF01C) == 0
    await manager_write(dut, 0xF008, 1)
    assert await manager_read(dut, 0xF008) == 1
    assert await manager_read(dut, 0x0020) == 0x1111_0000
    assert int(dut.slot_rd_en.value) & 0b010
    await manager_write(dut, 0xF008, 2)
    assert await manager_read(dut, 0x0020) == 0x2222_0000
    assert int(dut.burst_rd_data.value) == 0
    assert int(dut.burst_rd_ts_data.value) == 0
    assert int(dut.burst_start.value) == 0
    assert int(dut.burst_timestamp.value) == 0
    assert int(dut.burst_start_ptr.value) == 0
    await manager_write(dut, 0xF008, 1)
    await Timer(1, units="ns")
    assert int(dut.burst_rd_data.value) == 0xB1
    assert int(dut.burst_rd_ts_data.value) == 1
    assert int(dut.burst_start.value) == 1
    assert int(dut.burst_timestamp.value) == 0
    assert int(dut.burst_start_ptr.value) == 0xB
    await manager_write(dut, 0xF008, 7)
    assert await manager_read(dut, 0xF008) == 1


@cocotb.test()
async def fcapz_ela_channel_mux(dut):
    cocotb.start_soon(Clock(dut.sample_clk, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.jtag_clk, 14, units="ns").start())
    dut.sample_rst.value = 1
    dut.jtag_rst.value = 1
    dut.probe_in.value = (0xCC << 16) | (0xBB << 8) | 0xAA
    dut.trigger_in.value = 0
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    dut.burst_rd_addr.value = 0
    for _ in range(4):
        await RisingEdge(dut.sample_clk)
    dut.sample_rst.value = 0
    for _ in range(2):
        await RisingEdge(dut.jtag_clk)
    dut.jtag_rst.value = 0
    for _ in range(4):
        await RisingEdge(dut.jtag_clk)

    assert await jtag_read(dut, 0x00A4) == 3
    assert await jtag_read(dut, 0x00A0) == 0

    async def capture_channel(index: int) -> int:
        await jtag_write(dut, 0x00A0, index)
        await jtag_write(dut, 0x0004, 2)
        for _ in range(10):
            await RisingEdge(dut.sample_clk)
        await jtag_write(dut, 0x0020, 1)
        await jtag_write(dut, 0x0024, 0)
        await jtag_write(dut, 0x0028, 0)
        await jtag_write(dut, 0x0014, 0)
        await jtag_write(dut, 0x0018, 2)
        await arm_ela(dut)
        for _ in range(100):
            await RisingEdge(dut.sample_clk)
        return await jtag_read(dut, 0x0100)

    assert (await capture_channel(0)) & 0xFF == 0xAA
    assert (await capture_channel(1)) & 0xFF == 0xBB
    assert (await capture_channel(2)) & 0xFF == 0xCC
    await jtag_write(dut, 0x00A0, 1)
    assert await jtag_read(dut, 0x00A0) == 1
    await jtag_write(dut, 0x00A0, 0)
    assert await jtag_read(dut, 0x00A0) == 0
    assert (await capture_channel(7)) & 0xFF == 0xAA


@cocotb.test()
async def fcapz_ela_xilinx7_single_chain(dut):
    cocotb.start_soon(Clock(dut.sample_clk, 6, units="ns").start())
    tap = dut.u_tap_ctrl.u_bscan
    dut.sample_rst.value = 1
    dut.probe_in.value = 0
    dut.trigger_in.value = 0
    dut.eio_probe_in.value = 0
    tap.TCK.value = 0
    tap.TDI.value = 0
    tap.CAPTURE.value = 0
    tap.SHIFT.value = 0
    tap.UPDATE.value = 0
    tap.SEL.value = 0

    async def tck_tick() -> None:
        tap.TCK.value = 0
        await Timer(5, units="ns")
        tap.TCK.value = 1
        await Timer(1, units="ns")
        tap.TCK.value = 0
        await Timer(4, units="ns")

    bscane_names = dict(sel="SEL", capture="CAPTURE", shift="SHIFT", update="UPDATE", tdi="TDI")

    async def wrapper_idle(n: int) -> None:
        await _tap_idle(tap, tck_tick, n, **bscane_names)

    async def wrapper_scan_reg(frame: int) -> int:
        return await _tap_shift_frame(tap, dut.tap1_tdo, tck_tick, frame, **bscane_names)

    async def wrapper_read(addr: int) -> int:
        await wrapper_scan_reg(make_frame(addr, 0, False))
        await wrapper_idle(2)
        data = await wrapper_scan_reg(make_frame(addr, 0, False))
        await wrapper_idle(2)
        return data

    async def wrapper_write(addr: int, data: int) -> None:
        await wrapper_scan_reg(make_frame(addr, data, True))
        await wrapper_idle(8)

    async def wrapper_scan_burst() -> int:
        return await _tap_shift_burst(tap, dut.tap1_tdo, tck_tick, **bscane_names)

    async def counter_driver() -> None:
        value = 0
        while True:
            await RisingEdge(dut.sample_clk)
            if int(dut.sample_rst.value):
                value = 0
            else:
                value = (value + 1) & 0xFF
            dut.probe_in.value = value

    cocotb.start_soon(counter_driver())
    await wrapper_idle(8)
    for _ in range(8):
        await RisingEdge(dut.sample_clk)
    dut.sample_rst.value = 0
    await wrapper_idle(12)

    assert await wrapper_read(0x000C) == 8
    await wrapper_write(0x0014, 4)
    await wrapper_write(0x0018, 8)
    await wrapper_write(0x0020, 1)
    await wrapper_write(0x0024, 0x20)
    await wrapper_write(0x0028, 0xFF)
    await wrapper_write(0x0004, 1)

    status = 0
    for _ in range(200):
        await wrapper_idle(8)
        status = await wrapper_read(0x0008)
        if status & 0x4:
            break
    assert status & 0x4
    assert await wrapper_read(0x001C) == 13

    await wrapper_write(0x002C, 0)
    await wrapper_idle(80)
    await wrapper_scan_burst()
    burst = await wrapper_scan_burst()
    prev = sample_at(burst, 0)
    for i in range(1, 13):
        cur = sample_at(burst, i)
        assert cur == ((prev + 1) & 0xFF)
        prev = cur


@cocotb.test()
async def fcapz_async_fifo_equiv(dut):
    cocotb.start_soon(Clock(dut.wr_clk, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.rd_clk, 14, units="ns").start())
    dut.rst.value = 1
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    dut.wr_data.value = 0

    async def check_stable() -> None:
        await FallingEdge(dut.rd_clk)
        if int(dut.rd_empty_a.value) != int(dut.rd_empty_b.value):
            raise AssertionError("rd_empty mismatch")
        if int(dut.wr_full_a.value) != int(dut.wr_full_b.value):
            raise AssertionError("wr_full mismatch")
        if not int(dut.rd_empty_a.value) and not int(dut.rd_empty_b.value):
            assert int(dut.rd_data_a.value) == int(dut.rd_data_b.value)

    for _ in range(3):
        await RisingEdge(dut.wr_clk)
    dut.rst.value = 0
    await RisingEdge(dut.wr_clk)

    for i in range(16):
        await RisingEdge(dut.wr_clk)
        dut.wr_data.value = i
        dut.wr_en.value = 1
        await check_stable()
    await RisingEdge(dut.wr_clk)
    dut.wr_en.value = 0
    for _ in range(4):
        await check_stable()

    for _ in range(16):
        await RisingEdge(dut.rd_clk)
        dut.rd_en.value = 1
        await check_stable()
    await RisingEdge(dut.rd_clk)
    dut.rd_en.value = 0

    for _ in range(4):
        await RisingEdge(dut.wr_clk)
    for i in range(8):
        await RisingEdge(dut.wr_clk)
        dut.wr_data.value = (0xA0 + i) & 0xFF
        dut.wr_en.value = 1
        await RisingEdge(dut.rd_clk)
        dut.rd_en.value = 1
        await check_stable()
    await RisingEdge(dut.wr_clk)
    dut.wr_en.value = 0
    await RisingEdge(dut.rd_clk)
    dut.rd_en.value = 0
    for _ in range(8):
        await check_stable()


CMD_NOP = 0x0
CMD_WRITE = 0x1
CMD_READ = 0x2
CMD_WRITE_INC = 0x3
CMD_READ_INC = 0x4
CMD_SET_ADDR = 0x5
CMD_BURST_SETUP = 0x6
CMD_BURST_WDATA = 0x7
CMD_BURST_RDATA = 0x8
CMD_BURST_RSTART = 0x9
CMD_CONFIG = 0xE
CMD_RESET = 0xF


def axi_cmd(cmd: int, addr: int, payload: int, wstrb: int) -> int:
    return (((cmd & 0xF) << 68)
            | ((wstrb & 0xF) << 64)
            | ((payload & 0xFFFF_FFFF) << 32)
            | (addr & 0xFFFF_FFFF))


def axi_status(dout: int) -> int:
    return (dout >> 68) & 0xF


def axi_rdata(dout: int) -> int:
    return dout & 0xFFFF_FFFF


def axi_resp(dout: int) -> int:
    return (dout >> 64) & 0x3


async def axi_cdc_wait(dut, cycles: int = 10) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.tck)


async def dr_scan_72(dut, din: int) -> int:
    dout = 0
    await RisingEdge(dut.tck)
    dut.sel.value = 1
    dut.capture.value = 1
    await RisingEdge(dut.tck)
    dut.capture.value = 0
    dut.shift_en.value = 1
    for i in range(72):
        dut.tdi.value = (din >> i) & 1
        await FallingEdge(dut.tck)
        if int(dut.tdo.value):
            dout |= 1 << i
        await RisingEdge(dut.tck)
    dut.shift_en.value = 0
    await RisingEdge(dut.tck)
    dut.update.value = 1
    await RisingEdge(dut.tck)
    dut.update.value = 0
    dut.sel.value = 0
    return dout


class _AxiIdSignal:
    def __init__(self, width: int = 1) -> None:
        self._width = width
        self._value = BinaryValue(0, n_bits=width, bigEndian=False)

    @property
    def value(self) -> BinaryValue:
        return self._value

    @value.setter
    def value(self, value) -> None:
        if isinstance(value, BinaryValue):
            self._value = value
        elif hasattr(value, "get_binstr"):
            self._value = BinaryValue(value.get_binstr(), n_bits=self._width, bigEndian=False)
        elif hasattr(value, "binstr"):
            self._value = BinaryValue(value.binstr, n_bits=self._width, bigEndian=False)
        else:
            try:
                self._value = BinaryValue(value, n_bits=self._width, bigEndian=False)
            except TypeError:
                self._value = BinaryValue("".join(str(bit) for bit in value),
                                          n_bits=self._width, bigEndian=False)

    def __len__(self) -> int:
        return self._width

    def setimmediatevalue(self, value) -> None:
        self.value = value


def _bind_axi_signal(bus, name: str, signal) -> None:
    setattr(bus, name, signal)
    bus._signals[name] = signal


def _drop_absent_axi_signals(*buses) -> None:
    for bus in buses:
        for name, signal in list(bus._signals.items()):
            if signal is None:
                del bus._signals[name]
                try:
                    delattr(bus, name)
                except AttributeError:
                    pass


def axi_no_id_bus(dut) -> AxiBus:
    bus = AxiBus.from_prefix(dut, "m_axi")
    _bind_axi_signal(bus.write.aw, "awid", _AxiIdSignal())
    _bind_axi_signal(bus.write.b, "bid", _AxiIdSignal())
    _bind_axi_signal(bus.read.ar, "arid", _AxiIdSignal())
    _bind_axi_signal(bus.read.r, "rid", _AxiIdSignal())
    _drop_absent_axi_signals(bus.write.aw, bus.write.w, bus.write.b, bus.read.ar, bus.read.r)
    return bus


def axi_mem_read32(axi_ram: AxiRam, addr: int) -> int:
    return axi_ram.read_dword(addr)


def _signal_int(signal) -> int:
    value = signal.value
    if hasattr(value, "is_resolvable") and not value.is_resolvable:
        return 0
    return int(value)


def _signal_is_one(signal) -> bool:
    return _signal_int(signal) == 1


class AxiTrace:
    def __init__(self, dut) -> None:
        self.dut = dut
        self.aw: list[dict[str, int]] = []
        self.w: list[dict[str, int]] = []
        self.ar: list[dict[str, int]] = []

    async def monitor(self) -> None:
        while True:
            await RisingEdge(self.dut.axi_clk)
            if _signal_is_one(self.dut.axi_rst):
                continue
            if _signal_is_one(self.dut.m_axi_awvalid) and _signal_is_one(self.dut.m_axi_awready):
                self.aw.append({
                    "addr": _signal_int(self.dut.m_axi_awaddr),
                    "len": _signal_int(self.dut.m_axi_awlen),
                    "size": _signal_int(self.dut.m_axi_awsize),
                    "burst": _signal_int(self.dut.m_axi_awburst),
                })
            if _signal_is_one(self.dut.m_axi_wvalid) and _signal_is_one(self.dut.m_axi_wready):
                self.w.append({
                    "data": _signal_int(self.dut.m_axi_wdata),
                    "strb": _signal_int(self.dut.m_axi_wstrb),
                    "last": _signal_int(self.dut.m_axi_wlast),
                })
            if _signal_is_one(self.dut.m_axi_arvalid) and _signal_is_one(self.dut.m_axi_arready):
                self.ar.append({
                    "addr": _signal_int(self.dut.m_axi_araddr),
                    "len": _signal_int(self.dut.m_axi_arlen),
                    "size": _signal_int(self.dut.m_axi_arsize),
                    "burst": _signal_int(self.dut.m_axi_arburst),
                })


async def init_ejtagaxi(dut) -> tuple[AxiRam, AxiTrace]:
    axi_ram = AxiRam(axi_no_id_bus(dut), dut.axi_clk, dut.axi_rst, size=4096)
    axi_trace = AxiTrace(dut)
    cocotb.start_soon(axi_trace.monitor())
    cocotb.start_soon(Clock(dut.tck, 100, units="ns").start())
    cocotb.start_soon(Clock(dut.axi_clk, 30, units="ns").start())
    dut.tdi.value = 0
    dut.capture.value = 0
    dut.shift_en.value = 0
    dut.update.value = 0
    dut.sel.value = 0
    dut.axi_rst.value = 1
    for _ in range(4):
        await RisingEdge(dut.axi_clk)
    dut.axi_rst.value = 0
    await axi_cdc_wait(dut, 10)
    return axi_ram, axi_trace


async def issue_and_wait_valid(dut, command: int, label: str) -> int:
    await dr_scan_72(dut, command)
    await axi_cdc_wait(dut)
    last = 0
    for _ in range(32):
        last = await dr_scan_72(dut, axi_cmd(CMD_NOP, 0, 0, 0))
        status = axi_status(last)
        if status & 0x1:
            return last
        assert status & 0x2, f"{label}: became idle before prev_valid"
        assert not (status & 0x4), f"{label}: error_sticky set"
        await axi_cdc_wait(dut)
    raise AssertionError(
        f"{label}: timed out waiting for prev_valid; last status=0x{axi_status(last):x}")


async def drain_until_idle(dut) -> int:
    last = 0
    for _ in range(32):
        last = await dr_scan_72(dut, axi_cmd(CMD_NOP, 0, 0, 0))
        if not (axi_status(last) & 0x2):
            return last
        await axi_cdc_wait(dut)
    raise AssertionError(f"reset drain timed out; last status=0x{axi_status(last):x}")


def _assert_axi_addr(txn: dict[str, int], addr: int, length: int = 0) -> None:
    assert txn["addr"] == addr
    assert txn["len"] == length
    assert txn["size"] == 2
    assert txn["burst"] == 1


def _assert_axi_write_beats(
    beats: list[dict[str, int]],
    values: list[int],
    *,
    burst: bool,
    strobes: list[int] | None = None,
) -> None:
    assert len(beats) == len(values)
    if strobes is None:
        strobes = [0xF] * len(values)
    assert len(strobes) == len(values)
    for index, (beat, value, strobe) in enumerate(zip(beats, values, strobes, strict=True)):
        assert beat["data"] == value
        assert beat["strb"] == strobe
        expected_last = index == len(values) - 1 if burst else True
        assert beat["last"] == int(expected_last)


def assert_axi_protocol_trace(trace: AxiTrace) -> None:
    assert len(trace.aw) == 9
    assert len(trace.w) == 12
    assert len(trace.ar) == 8

    expected_single_writes = [
        0x0000_0000,
        0x0000_0004,
        0x0000_0008,
        0x0000_0008,
        0x0000_0010,
        0x0000_0014,
        0x0000_0018,
        0x0000_001C,
    ]
    for txn, addr in zip(trace.aw[:8], expected_single_writes, strict=True):
        _assert_axi_addr(txn, addr)
    _assert_axi_addr(trace.aw[8], 0x0000_0020, 3)

    expected_single_write_values = [
        0xDEAD_BEEF,
        0x1234_5678,
        0xFFFF_FFFF,
        0xAABB_CCDD,
        0xA000_0000,
        0xA000_0001,
        0xA000_0002,
        0xA000_0003,
    ]
    _assert_axi_write_beats(
        trace.w[:8],
        expected_single_write_values,
        burst=False,
        strobes=[0xF, 0xF, 0xF, 0x3, 0xF, 0xF, 0xF, 0xF],
    )
    _assert_axi_write_beats(
        trace.w[8:12],
        [0xB000_0000, 0xB000_0001, 0xB000_0002, 0xB000_0003],
        burst=True,
    )

    expected_single_reads = [
        0x0000_0000,
        0x0000_0004,
        0x0000_0008,
        0x0000_0010,
        0x0000_0014,
        0x0000_0018,
        0x0000_001C,
    ]
    for txn, addr in zip(trace.ar[:7], expected_single_reads, strict=True):
        _assert_axi_addr(txn, addr)
    _assert_axi_addr(trace.ar[7], 0x0000_0020, 3)


@cocotb.test()
async def fcapz_ejtagaxi_protocol(dut):
    axi_ram, axi_trace = await init_ejtagaxi(dut)

    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x0000_0000, 0xDEAD_BEEF, 0xF), "S1 write")
    assert axi_resp(out) == 0
    assert axi_mem_read32(axi_ram, 0x0000_0000) == 0xDEAD_BEEF
    await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ, 0x0000_0000, 0, 0), "S2 read")
    assert axi_rdata(out) == 0xDEAD_BEEF
    await axi_cdc_wait(dut)

    await issue_and_wait_valid(dut, axi_cmd(CMD_WRITE, 0x0000_0004, 0x1234_5678, 0xF), "S3 write")
    out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ, 0x0000_0004, 0, 0), "S3 read")
    assert axi_rdata(out) == 0x1234_5678
    await axi_cdc_wait(dut)

    await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x0000_0008, 0xFFFF_FFFF, 0xF), "S4 full write")
    await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x0000_0008, 0xAABB_CCDD, 0x3), "S4 partial write")
    out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ, 0x0000_0008, 0, 0), "S4 read")
    assert axi_rdata(out) == 0xFFFF_CCDD
    await axi_cdc_wait(dut)

    await dr_scan_72(dut, axi_cmd(CMD_SET_ADDR, 0x0000_0010, 0, 0))
    await axi_cdc_wait(dut)
    for i in range(4):
        await issue_and_wait_valid(
            dut, axi_cmd(CMD_WRITE_INC, 0, 0xA000_0000 + i, 0xF),
            f"S5 write_inc {i}")
    assert axi_mem_read32(axi_ram, 0x0000_0010) == 0xA000_0000
    assert axi_mem_read32(axi_ram, 0x0000_0014) == 0xA000_0001
    assert axi_mem_read32(axi_ram, 0x0000_0018) == 0xA000_0002
    assert axi_mem_read32(axi_ram, 0x0000_001C) == 0xA000_0003

    await dr_scan_72(dut, axi_cmd(CMD_SET_ADDR, 0x0000_0010, 0, 0))
    await axi_cdc_wait(dut)
    for i in range(4):
        out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ_INC, 0, 0, 0), f"S6 read_inc {i}")
        assert axi_rdata(out) == 0xA000_0000 + i
        await axi_cdc_wait(dut)

    burst_setup = (0b01 << 12) | (0b010 << 8) | 3
    await dr_scan_72(dut, axi_cmd(CMD_BURST_SETUP, 0x0000_0020, burst_setup, 0))
    await axi_cdc_wait(dut)
    for i in range(4):
        await dr_scan_72(dut, axi_cmd(CMD_BURST_WDATA, 0, 0xB000_0000 + i, 0xF))
        await axi_cdc_wait(dut)
        await dr_scan_72(dut, axi_cmd(CMD_NOP, 0, 0, 0))
        await axi_cdc_wait(dut)
    assert axi_mem_read32(axi_ram, 0x0000_0020) == 0xB000_0000
    assert axi_mem_read32(axi_ram, 0x0000_0024) == 0xB000_0001
    assert axi_mem_read32(axi_ram, 0x0000_0028) == 0xB000_0002
    assert axi_mem_read32(axi_ram, 0x0000_002C) == 0xB000_0003

    await dr_scan_72(dut, axi_cmd(CMD_BURST_SETUP, 0x0000_0020, burst_setup, 0))
    await axi_cdc_wait(dut)
    await dr_scan_72(dut, axi_cmd(CMD_BURST_RSTART, 0, 0, 0))
    await axi_cdc_wait(dut)
    await axi_cdc_wait(dut, 20)
    await dr_scan_72(dut, axi_cmd(CMD_BURST_RDATA, 0, 0, 0))
    await axi_cdc_wait(dut)
    for i in range(4):
        out = await dr_scan_72(dut, axi_cmd(CMD_BURST_RDATA, 0, 0, 0))
        assert axi_rdata(out) == 0xB000_0000 + i
        await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(dut, axi_cmd(CMD_CONFIG, 0x0000_0000, 0, 0), "S9 version")
    assert axi_rdata(out) == 0x0004_4A58
    await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_CONFIG, 0x0000_0004, 0, 0), "S9 version alias")
    assert axi_rdata(out) == 0x0004_4A58
    await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(dut, axi_cmd(CMD_CONFIG, 0x0000_002C, 0, 0), "S9 features")
    assert axi_rdata(out) == 0x000F_2020
    await axi_cdc_wait(dut)

    await dr_scan_72(dut, axi_cmd(CMD_RESET, 0, 0, 0))
    await axi_cdc_wait(dut)
    out = await drain_until_idle(dut)
    assert not (axi_status(out) & 0x4)
    assert not (axi_status(out) & 0x2)
    assert_axi_protocol_trace(axi_trace)


@cocotb.test()
async def fcapz_ejtagaxi_reset_regression(dut):
    axi_ram, axi_trace = await init_ejtagaxi(dut)

    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x0000_0000, 0x1234_5678, 0xF), "write addr 0")
    assert axi_resp(out) == 0
    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x0000_0004, 0x89AB_CDEF, 0xF), "write addr 4")
    assert axi_resp(out) == 0
    assert axi_mem_read32(axi_ram, 0x0000_0000) == 0x1234_5678
    assert axi_mem_read32(axi_ram, 0x0000_0004) == 0x89AB_CDEF

    await dr_scan_72(dut, axi_cmd(CMD_RESET, 0, 0, 0))
    await axi_cdc_wait(dut)
    out = await drain_until_idle(dut)
    status = axi_status(out)
    assert not (status & 0x2)

    out = await dr_scan_72(dut, axi_cmd(CMD_NOP, 0, 0, 0))
    status = axi_status(out)
    assert not (status & 0x1)
    assert not (status & 0x4)
    await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_READ, 0x0000_0000, 0, 0), "first post-reset read")
    assert axi_resp(out) == 0
    assert axi_rdata(out) == 0x1234_5678

    await dr_scan_72(dut, axi_cmd(CMD_SET_ADDR, 0x0000_0004, 0, 0))
    await axi_cdc_wait(dut)
    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_READ_INC, 0, 0, 0), "first post-reset read_inc")
    assert axi_resp(out) == 0
    assert axi_rdata(out) == 0x89AB_CDEF
    assert int(dut.debug_tck.value) == 0
    assert int(dut.debug_tck_edge.value) == 0
    assert int(dut.debug_axi.value) == 0
    assert int(dut.debug_axi_edge.value) == 0
    assert len(axi_trace.aw) == 2
    assert len(axi_trace.w) == 2
    assert len(axi_trace.ar) == 2
    _assert_axi_addr(axi_trace.aw[0], 0x0000_0000)
    _assert_axi_addr(axi_trace.aw[1], 0x0000_0004)
    _assert_axi_write_beats(axi_trace.w, [0x1234_5678, 0x89AB_CDEF], burst=False)
    _assert_axi_addr(axi_trace.ar[0], 0x0000_0000)
    _assert_axi_addr(axi_trace.ar[1], 0x0000_0004)


UART_CMD_NOP = 0x0
UART_CMD_TX_PUSH = 0x1
UART_CMD_RX_POP = 0x2
UART_CMD_TXRX = 0x3
UART_CMD_CONFIG = 0xE
UART_CMD_RESET = 0xF
UART_BIT_PERIOD_NS = 10_000
UART_TX_FIFO_DEPTH = 16
UART_RX_FIFO_DEPTH = 16
UART_BAUD_DIV = 100


def uart_cmd(cmd: int, tx_byte: int) -> int:
    return ((cmd & 0xF) << 28) | (tx_byte & 0xFF)


def uart_rx_byte(dout: int) -> int:
    return dout & 0xFF


def uart_tx_free(dout: int) -> int:
    return (dout >> 8) & 0xFF


def uart_rx_ready(dout: int) -> int:
    return (dout >> 24) & 1


def uart_rx_valid(dout: int) -> int:
    return (dout >> 28) & 1


def uart_tx_full(dout: int) -> int:
    return (dout >> 29) & 1


def uart_rx_overflow(dout: int) -> int:
    return (dout >> 30) & 1


def uart_frame_err(dout: int) -> int:
    return (dout >> 31) & 1


async def uart_cdc_wait(dut, cycles: int = 10) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.tck)


async def dr_scan_32(dut, din: int) -> int:
    dout = 0
    await RisingEdge(dut.tck)
    dut.sel.value = 1
    dut.capture.value = 1
    await RisingEdge(dut.tck)
    dut.capture.value = 0
    dut.shift.value = 1
    for i in range(32):
        dut.tdi.value = (din >> i) & 1
        await FallingEdge(dut.tck)
        if int(dut.tdo.value):
            dout |= 1 << i
        await RisingEdge(dut.tck)
    dut.shift.value = 0
    await RisingEdge(dut.tck)
    dut.update.value = 1
    await RisingEdge(dut.tck)
    dut.update.value = 0
    dut.sel.value = 0
    return dout


async def uart_send_byte(dut, data: int, stop_high: bool = True) -> None:
    dut.uart_rxd.value = 0
    await Timer(UART_BIT_PERIOD_NS, units="ns")
    for i in range(8):
        dut.uart_rxd.value = (data >> i) & 1
        await Timer(UART_BIT_PERIOD_NS, units="ns")
    dut.uart_rxd.value = 1 if stop_high else 0
    await Timer(UART_BIT_PERIOD_NS, units="ns")
    dut.uart_rxd.value = 1


async def uart_recv_byte_timeout(dut, timeout_ns: int) -> tuple[bool, int]:
    waited = 0
    while int(dut.uart_txd.value) == 1 and waited < timeout_ns:
        await Timer(100, units="ns")
        waited += 100
    if int(dut.uart_txd.value) != 0:
        return False, 0
    await Timer(UART_BIT_PERIOD_NS // 2, units="ns")
    data = 0
    for i in range(8):
        await Timer(UART_BIT_PERIOD_NS, units="ns")
        data |= int(dut.uart_txd.value) << i
    await Timer(UART_BIT_PERIOD_NS, units="ns")
    return True, data


async def uart_recv_byte(dut) -> int:
    while int(dut.uart_txd.value) == 1:
        await Edge(dut.uart_txd)
    await Timer(UART_BIT_PERIOD_NS // 2, units="ns")
    data = 0
    for i in range(8):
        await Timer(UART_BIT_PERIOD_NS, units="ns")
        data |= int(dut.uart_txd.value) << i
    await Timer(UART_BIT_PERIOD_NS, units="ns")
    return data


async def init_ejtaguart(dut) -> None:
    cocotb.start_soon(Clock(dut.tck, 100, units="ns").start())
    cocotb.start_soon(Clock(dut.uart_clk, 100, units="ns").start())
    dut.tdi.value = 0
    dut.capture.value = 0
    dut.shift.value = 0
    dut.update.value = 0
    dut.sel.value = 0
    dut.uart_rxd.value = 1
    dut.uart_rst.value = 1
    for _ in range(4):
        await RisingEdge(dut.uart_clk)
    dut.uart_rst.value = 0
    await uart_cdc_wait(dut, 20)


@cocotb.test()
async def fcapz_ejtaguart_protocol(dut):
    await init_ejtaguart(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_CONFIG, 0x00))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_CONFIG, 0x01))
    assert uart_rx_byte(out) == 0x55
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_CONFIG, 0x02))
    assert uart_rx_byte(out) == 0x4A
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_CONFIG, 0x03))
    assert uart_rx_byte(out) == 0x04
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0x00))
    assert uart_rx_byte(out) == 0x00
    await uart_cdc_wait(dut)
    await dr_scan_32(dut, uart_cmd(UART_CMD_CONFIG, 0x04))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0x00))
    assert uart_rx_byte(out) == 0x55
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, 0xA5))
    await uart_cdc_wait(dut)
    valid, tx_byte = await uart_recv_byte_timeout(dut, UART_BIT_PERIOD_NS * 12)
    assert valid
    assert tx_byte == 0xA5
    for _ in range(20):
        await RisingEdge(dut.uart_clk)

    await uart_send_byte(dut, 0x3C)
    await uart_cdc_wait(dut, 40)
    await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_byte(out) == 0x3C
    assert uart_rx_valid(out)
    await uart_cdc_wait(dut)

    await uart_send_byte(dut, 0xBE)
    await uart_cdc_wait(dut, 40)
    await dr_scan_32(dut, uart_cmd(UART_CMD_TXRX, 0x55))
    valid, tx_byte = await uart_recv_byte_timeout(dut, UART_BIT_PERIOD_NS * 14)
    assert valid
    assert tx_byte == 0x55
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_byte(out) == 0xBE
    assert uart_rx_valid(out)
    for _ in range(UART_BAUD_DIV * 12):
        await RisingEdge(dut.uart_clk)

    await uart_send_byte(dut, 0xAA)
    await uart_cdc_wait(dut, 40)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_ready(out)
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_ready(out)
    assert not uart_rx_valid(out)
    await uart_cdc_wait(dut)
    await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_byte(out) == 0xAA
    await uart_cdc_wait(dut)

    for i in range(UART_TX_FIFO_DEPTH + 8):
        await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, i))
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_tx_full(out)
    for _ in range(UART_TX_FIFO_DEPTH * UART_BAUD_DIV * 12):
        await RisingEdge(dut.uart_clk)
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 30)
    for i in range(UART_RX_FIFO_DEPTH + 2):
        await uart_send_byte(dut, i)
    await uart_cdc_wait(dut, 50)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    await uart_cdc_wait(dut, 10)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_overflow(out)
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 30)
    await uart_send_byte(dut, 0, stop_high=False)
    await uart_cdc_wait(dut, 50)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_frame_err(out)
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 30)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert not uart_rx_overflow(out)
    assert not uart_frame_err(out)
    assert not uart_tx_full(out)
    assert not uart_rx_ready(out)
    await uart_cdc_wait(dut)

    for expected in (0x11, 0x22, 0x33, 0x44):
        await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, expected))
        got = await uart_recv_byte(dut)
        await uart_send_byte(dut, got)
        await uart_cdc_wait(dut, 40)
        await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
        await uart_cdc_wait(dut)
        out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
        assert uart_rx_byte(out) == expected
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, 0xFF))
    while int(dut.uart_txd.value) == 1:
        await Edge(dut.uart_txd)
    await Timer(UART_BIT_PERIOD_NS * 10, units="ns")
    for _ in range(20):
        await RisingEdge(dut.uart_clk)
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 20)
    for _ in range(UART_BAUD_DIV * 12 * 4):
        await RisingEdge(dut.uart_clk)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_tx_free(out) == UART_TX_FIFO_DEPTH
    for i in range(3):
        await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, i))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_tx_free(out) < UART_TX_FIFO_DEPTH
    for _ in range(100):
        await RisingEdge(dut.uart_clk)
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 30)
    for data in (0xD1, 0xD2, 0xD3):
        await uart_send_byte(dut, data)
    await uart_cdc_wait(dut, 40)
    await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
    assert uart_rx_byte(out) == 0xD1
    assert uart_rx_valid(out)
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
    assert uart_rx_byte(out) == 0xD2
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_byte(out) == 0xD3
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 20)
    for _ in range(UART_BAUD_DIV * 12 * 4):
        await RisingEdge(dut.uart_clk)

    bridge_on = True

    async def bridge_txd_to_rxd() -> None:
        dut.uart_rxd.value = int(dut.uart_txd.value)
        while bridge_on:
            await Edge(dut.uart_txd)
            dut.uart_rxd.value = int(dut.uart_txd.value)

    bridge_task = cocotb.start_soon(bridge_txd_to_rxd())
    stress = (0x10, 0x21, 0x32, 0x43, 0x54, 0x65, 0x76, 0x87)
    for data in stress:
        await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, data))
    for _ in range(UART_BAUD_DIV * 12 * len(stress)):
        await RisingEdge(dut.uart_clk)
    await uart_cdc_wait(dut)
    await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
    await uart_cdc_wait(dut)
    for expected in stress[:-1]:
        out = await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
        assert uart_rx_byte(out) == expected
        assert uart_rx_valid(out)
        await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_byte(out) == stress[-1]
    assert uart_rx_valid(out)
    bridge_on = False
    bridge_task.kill()
    dut.uart_rxd.value = 1
