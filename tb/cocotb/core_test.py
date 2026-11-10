# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import atexit
import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, Timer
from cocotbext.axi import AxiBus, AxiRam

# VERSION register prefix ({major, minor} in bits 31:16) of this release.
_MAJOR, _MINOR, _ = (
    int(x) for x in (Path(__file__).resolve().parents[2] / "VERSION").read_text().split(".")
)
_VERSION_HI = (_MAJOR << 24) | (_MINOR << 16)

try:
    from cocotb.binary import BinaryValue
except ModuleNotFoundError:
    BinaryValue = None

try:
    from cocotb.types import LogicArray
except ModuleNotFoundError:
    LogicArray = None


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

JTAG_BURST_FUNCTIONAL_COVERAGE = FunctionalCoverage(
    env_var="JTAG_BURST_COCOTB_COVERAGE_JSON",
    run_env_var="JTAG_BURST_COCOTB_RUN",
    bins=(
        "data_burst_start",
        "data_burst_contiguous_first",
        "data_burst_contiguous_second",
        "data_burst_wrap",
        "timestamp_burst",
    ),
)

JTAG_PIPE_FUNCTIONAL_COVERAGE = FunctionalCoverage(
    env_var="JTAG_PIPE_COCOTB_COVERAGE_JSON",
    run_env_var="JTAG_PIPE_COCOTB_RUN",
    bins=(
        "register_write_frame",
        "register_read_frame",
        "burst_pointer_command",
        "burst_read_first",
        "burst_read_second",
        "segmented_burst_alignment",
        "padded_register_frames",
        "padded_command_window",
        "padded_burst_read",
        "partial_burst_update",
        "foreign_scan_suffix",
    ),
)

ASYNC_FIFO_FUNCTIONAL_COVERAGE = FunctionalCoverage(
    env_var="ASYNC_FIFO_COCOTB_COVERAGE_JSON",
    run_env_var="ASYNC_FIFO_COCOTB_RUN",
    bins=(
        "reset_empty_flags_match",
        "write_fill_flags_match",
        "read_drain_data_match",
        "mixed_read_write_match",
        "post_idle_stable",
        "stopped_wr_clk_reset_blocks_reads",
    ),
)

EJTAG_AXI_FUNCTIONAL_COVERAGE = FunctionalCoverage(
    env_var="EJTAG_AXI_COCOTB_COVERAGE_JSON",
    run_env_var="EJTAG_AXI_COCOTB_RUN",
    bins=(
        "single_write",
        "single_read",
        "partial_strobe_write",
        "incrementing_write",
        "incrementing_read",
        "burst_write",
        "burst_read",
        "config_version",
        "config_features",
        "soft_reset",
        "axi_protocol_trace",
        "reset_post_read",
        "reset_read_increment",
        "reset_debug_outputs_idle",
        "reset_axi_trace",
        "r_timeout_drain",
        "burst_timeout_drain",
        "reset_inflight_drain",
        "drain_bounded",
        "burst_beat_acks",
        "aw_stall_detached",
        "write_quarantine",
        "late_b_absorbed",
        "collect_reset_discard",
        "collect_cmd_discard",
        "collect_setup_restart",
        "w_stall_reset_completes",
        "w_before_aw",
        "burst_refused",
        "burst_legal_edges",
        "ar_stall_held",
        "ar_reset_held",
        "axi_valid_stable",
    ),
)

EJTAG_UART_FUNCTIONAL_COVERAGE = FunctionalCoverage(
    env_var="EJTAG_UART_COCOTB_COVERAGE_JSON",
    run_env_var="EJTAG_UART_COCOTB_RUN",
    bins=(
        "config_registers",
        "tx_push_serializes_byte",
        "rx_pop_reads_byte",
        "txrx_exchange",
        "rx_ready_without_pop",
        "tx_full_status",
        "rx_overflow_status",
        "frame_error_status",
        "reset_clears_status",
        "loopback_order",
        "tx_free_accounting",
        "rx_fifo_order",
        "bridge_loopback_stress",
    ),
)

atexit.register(EIO_FUNCTIONAL_COVERAGE.write)
atexit.register(JTAG_BURST_FUNCTIONAL_COVERAGE.write)
atexit.register(JTAG_PIPE_FUNCTIONAL_COVERAGE.write)
atexit.register(ASYNC_FIFO_FUNCTIONAL_COVERAGE.write)
atexit.register(EJTAG_AXI_FUNCTIONAL_COVERAGE.write)
atexit.register(EJTAG_UART_FUNCTIONAL_COVERAGE.write)


async def tick(signal) -> None:
    await RisingEdge(signal)
    await Timer(1, unit="ns")


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
        await Timer(1, unit="ns")
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
        await Timer(1, unit="ns")
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
    cocotb.start_soon(Clock(dut.tck, 10, unit="ns").start())
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
    JTAG_BURST_FUNCTIONAL_COVERAGE.hit("data_burst_start")
    await idle_tap(dut, 80)
    await scan_burst(dut)
    scan = await scan_burst(dut)
    assert_sample_sequence(scan, 42)
    JTAG_BURST_FUNCTIONAL_COVERAGE.hit("data_burst_contiguous_first")
    scan = await scan_burst(dut)
    assert_sample_sequence(scan, 74)
    JTAG_BURST_FUNCTIONAL_COVERAGE.hit("data_burst_contiguous_second")

    await start_burst(dut, 250, False)
    await idle_tap(dut, 80)
    await scan_burst(dut)
    scan = await scan_burst(dut)
    assert_sample_sequence(scan, 250)
    JTAG_BURST_FUNCTIONAL_COVERAGE.hit("data_burst_wrap")

    await start_burst(dut, 64, True)
    await idle_tap(dut, 80)
    await scan_burst(dut)
    scan = await scan_burst(dut)
    assert_timestamp_sequence(scan, 64)
    JTAG_BURST_FUNCTIONAL_COVERAGE.hit("timestamp_burst")


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
    cocotb.start_soon(Clock(dut.tck, 10, unit="ns").start())
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
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("register_write_frame")

    await scan_reg(dut, make_frame(0, 0, False))
    await idle_tap(dut, 4)
    captured = await scan_reg(dut, make_frame(0, 0, False))
    assert captured == 0x1234_5678
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("register_read_frame")

    await scan_reg(dut, make_frame(0x002C, 0, True))
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("burst_pointer_command")
    await idle_tap(dut, 80)
    await scan_burst(dut)
    first = await scan_burst(dut)
    second = await scan_burst(dut)
    assert_sample_sequence(first, 42)
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("burst_read_first")
    assert_sample_sequence(second, 74)
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("burst_read_second")


@cocotb.test()
async def jtag_pipe_iface_register_ends_preload(dut):
    """A register command ends the preload its Capture-DR started (BUG-233).

    With 1-bit samples a scan preloads 256 words, far longer than a 49-bit
    register scan, so without the abort the read it issues meets a busy
    memory port (the ELA then answers 0)."""
    assert len(dut.sample_data) == 1
    cocotb.start_soon(Clock(dut.tck, 10, unit="ns").start())
    collisions: list[tuple[int, int]] = []

    async def bus() -> None:
        while True:
            await RisingEdge(dut.tck)
            dut.sample_data.value = int(dut.mem_addr.value) & 1
            if int(dut.reg_wr_en.value) and int(dut.reg_addr.value) == 0x002C:
                dut.burst_ptr_in.value = 0
                dut.burst_start.value = 0 if int(dut.burst_start.value) else 1
            access = int(dut.reg_rd_en.value) or int(dut.reg_wr_en.value)
            if access and int(dut.mem_active.value):
                collisions.append((int(dut.reg_addr.value), int(dut.reg_wr_en.value)))

    cocotb.start_soon(bus())
    dut.arst.value = 1
    for name in ("tdi", "capture", "shift_en", "update", "sel", "burst_start",
                 "burst_timestamp", "burst_ptr_in", "timestamp_data"):
        getattr(dut, name).value = 0
    dut.reg_rdata.value = 0x1234_5678
    await idle_tap(dut, 4)
    dut.arst.value = 0
    await idle_tap(dut, 4)

    def check_bits(scan: int, start: int) -> None:
        for i in range(256):
            assert (scan >> i) & 1 == (start + i) & 1, f"bit {i} of the burst from {start}"

    for command in (make_frame(0x0100, 0, False), make_frame(0x0024, 7, True)):
        await scan_reg(dut, make_frame(0x002C, 0, True))
        await idle_tap(dut, 300)
        await scan_burst(dut)                      # priming
        check_bits(await scan_burst(dut), 0)       # its Capture-DR starts a preload
        await scan_reg(dut, command)               # ... this command must end
        await idle_tap(dut, 4)
        assert collisions == [], f"register access during a burst preload: {collisions}"
    # The aborted preload leaves nothing behind: the next burst starts clean.
    await scan_reg(dut, make_frame(0x002C, 0, True))
    await idle_tap(dut, 300)
    await scan_burst(dut)
    check_bits(await scan_burst(dut), 0)
    check_bits(await scan_burst(dut), 256)


async def pipe_command_monitor(dut, events: list) -> None:
    """Record every register-bus strobe as (kind, addr, wdata)."""
    while True:
        await RisingEdge(dut.tck)
        await ReadOnly()
        if int(dut.reg_wr_en.value):
            events.append(("wr", int(dut.reg_addr.value), int(dut.reg_wdata.value)))
        if int(dut.reg_rd_en.value):
            events.append(("rd", int(dut.reg_addr.value), 0))


def pad_frame(frame: int, pad: int, pad_value: int) -> int:
    """TDI stream for a 49-bit frame behind *pad* bits of chain padding.

    The pipe receives the pad bits first (a BYPASS register upstream of it
    captures 0; a device downstream receives host filler that passes through
    the pipe first), then the frame.  Only the last 49 bits may decode.
    """
    return (frame << pad) | (((1 << pad) - 1) if pad_value else 0)


async def scan_raw(dut, bits: int, count: int, *, update: bool = True) -> int:
    """Shift *count* TDI bits (LSB first); return the first 32 TDO bits."""
    captured = 0
    dut.sel.value = 1
    dut.capture.value = 1
    await tick(dut.tck)
    dut.capture.value = 0
    dut.shift_en.value = 1
    for i in range(count):
        dut.tdi.value = (bits >> i) & 1
        if i < 32 and int(dut.tdo.value):
            captured |= 1 << i
        await tick(dut.tck)
    dut.shift_en.value = 0
    dut.tdi.value = 0
    if update:
        dut.update.value = 1
        await tick(dut.tck)
        dut.update.value = 0
    dut.sel.value = 0
    return captured


@cocotb.test()
async def jtag_pipe_iface_padded_chain(dut):
    """Commands survive chain padding; bursts and short scans never execute."""
    burst_w = int(os.environ.get("FCAPZ_COCOTB_BURST_W", "256"))
    events: list = []
    cocotb.start_soon(Clock(dut.tck, 10, unit="ns").start())
    cocotb.start_soon(pipe_bus_monitor(dut))
    cocotb.start_soon(pipe_command_monitor(dut, events))
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

    # Odd write data (ARM is CTRL[0]) and reads, across padding depths and
    # both pad polarities, up to the widest legal command scan.
    max_pad = burst_w - 1 - 49
    for pad in sorted({p for p in (0, 1, 2, 7, max_pad) if p <= max_pad}):
        for pad_value in (0, 1):
            data = 0x8000_0001 ^ (pad << 8)
            events.clear()
            await scan_raw(dut, pad_frame(make_frame(0x0004, data, True), pad, pad_value),
                           49 + pad)
            await idle_tap(dut, 2)
            assert events == [("wr", 0x0004, data)], (pad, pad_value, events)
            events.clear()
            await scan_raw(dut, pad_frame(make_frame(0xF000, 0, False), pad, pad_value),
                           49 + pad)
            await idle_tap(dut, 2)
            assert events == [("rd", 0xF000, 0)], (pad, pad_value, events)
            captured = await scan_raw(
                dut, pad_frame(make_frame(0xF000, 0, False), pad, pad_value), 49 + pad)
            assert captured == 0x1234_5678, (pad, pad_value, hex(captured))
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("padded_register_frames")

    # Window edges: 48 is too short; burst_w and beyond are bursts (the shift
    # counter saturates at BURST_W), whatever TDI carried.  A scan of
    # 2**SHIFT_CTR_W + 49 shifts would wrap an unsaturated counter back onto
    # 49, so it proves the saturation.
    wrap_scan = (1 << burst_w.bit_length()) + 49
    ones = (1 << wrap_scan) - 1
    for count, executes in ((48, False), (49, True), (burst_w - 1, True),
                            (burst_w, False), (burst_w + 1, False), (burst_w + 40, False),
                            (wrap_scan, False)):
        events.clear()
        await scan_raw(dut, ones, count)
        await idle_tap(dut, 2)
        if executes:
            assert events == [("wr", 0xFFFF, 0xFFFF_FFFF)], (count, events)
        else:
            assert events == [], (count, events)
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("padded_command_window")

    # Burst session on a one-pad chain: BURST_PTR -> prime -> two bursts,
    # all padded; then a padded READ exits burst mode and a new BURST_PTR
    # restarts it.
    mask = (1 << burst_w) - 1
    events.clear()
    await scan_raw(dut, pad_frame(make_frame(0x002C, 0, True), 1, 0), 50)
    await idle_tap(dut, 80)
    await scan_raw(dut, 0, burst_w + 1)
    first = await scan_burst(dut, bits=burst_w + 1) & mask
    second = await scan_burst(dut, bits=burst_w + 1) & mask
    assert_sample_sequence(first, 42, burst_w // 8)
    assert_sample_sequence(second, 42 + burst_w // 8, burst_w // 8)
    assert events == [("wr", 0x002C, 0)], events
    events.clear()
    await scan_raw(dut, pad_frame(make_frame(0x0000, 0, False), 1, 0), 50)
    await idle_tap(dut, 2)
    assert events == [("rd", 0x0000, 0)], events
    captured = await scan_raw(dut, pad_frame(make_frame(0x0000, 0, False), 1, 0), 50)
    assert captured == 0x1234_5678, hex(captured)
    await scan_raw(dut, pad_frame(make_frame(0x002C, 0, True), 1, 0), 50)
    await idle_tap(dut, 80)
    await scan_raw(dut, 0, burst_w + 1)
    again = await scan_burst(dut, bits=burst_w + 1) & mask
    assert_sample_sequence(again, 42, burst_w // 8)
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("padded_burst_read")

    # A burst cut short: without UPDATE nothing executes; with UPDATE the
    # zero-filled command register decodes as a READ of address 0 (never a
    # write) and leaves burst mode.
    await scan_raw(dut, pad_frame(make_frame(0x002C, 0, True), 1, 0), 50)
    await idle_tap(dut, 80)
    partial = (49 + burst_w) // 2
    events.clear()
    await scan_raw(dut, 0, partial, update=False)
    await idle_tap(dut, 2)
    assert events == [], events
    await scan_raw(dut, 0, partial)
    await idle_tap(dut, 2)
    assert events == [("rd", 0x0000, 0)], events
    captured = await scan_raw(dut, make_frame(0x0000, 0, False), 49)
    assert captured == 0x1234_5678, hex(captured)
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("partial_burst_update")

    # A foreign scan shorter than a burst executes its last 49 bits.  This is
    # the documented cost of padding tolerance (jtag_reg_iface behaves the
    # same): a 72-bit EJTAG-AXI CONFIG frame lands as WRITE 0xC000.
    if burst_w > 72:
        events.clear()
        config = (0xE << 68) | 0x0004  # CMD_CONFIG, addr 0x0004
        await scan_raw(dut, config, 72)
        await idle_tap(dut, 2)
        assert events == [("wr", 0xC000, 0)], events
        JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("foreign_scan_suffix")


@cocotb.test()
async def jtag_pipe_iface_segmented_alignment(dut):
    cocotb.start_soon(Clock(dut.tck, 10, unit="ns").start())
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
    JTAG_PIPE_FUNCTIONAL_COVERAGE.hit("segmented_burst_alignment")


@cocotb.test()
async def fcapz_eio_registers(dut):
    in_w = len(dut.probe_in)
    out_w = len(dut.probe_out)
    out_low_mask = word_mask(out_w, 0)

    cocotb.start_soon(Clock(dut.jtag_clk, 14, unit="ns").start())
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


def manager_reset(dut, level: int) -> None:
    """Drive jtag_rst and proto_rst together; no Test-Logic-Reset or slot reset.

    The tests of a target share one simulation, so each starts from both
    resets: jtag_rst alone leaves the burst start event of the last test.
    """
    dut.jtag_rst.value = level
    dut.proto_rst.value = level
    dut.tlr.value = 0
    dut.slot_rst.value = 0


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
    await Timer(1, unit="ns")
    data = int(dut.jtag_rdata.value)
    await FallingEdge(dut.jtag_clk)
    dut.jtag_rd_en.value = 0
    return data


@cocotb.test()
async def fcapz_core_manager_mux(dut):
    cocotb.start_soon(Clock(dut.jtag_clk, 10, unit="ns").start())
    manager_reset(dut, 1)
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    dut.slot_rdata.value = (0x2222_0000 << 64) | (0x1111_0000 << 32)
    dut.slot_burst_rd_data.value = (0xC2 << 16) | (0xB1 << 8) | 0xA0
    dut.slot_burst_rd_ts_data.value = (0x2 << 8) | (0x1 << 4)
    if hasattr(dut, "burst_rd_active"):
        dut.burst_rd_active.value = 0
    dut.slot_burst_start.value = 0b111
    dut.slot_burst_timestamp.value = 0b101
    dut.slot_burst_start_ptr.value = (0xC << 8) | (0xB << 4) | 0xA
    for _ in range(3):
        await FallingEdge(dut.jtag_clk)
    manager_reset(dut, 0)
    await FallingEdge(dut.jtag_clk)

    assert await manager_read(dut, 0xF000) == _VERSION_HI | 0x434D
    assert await manager_read(dut, 0xF004) == 3
    # bit2: the burst start is raised on every BURST_PTR write; bits 3..6:
    # epochs and owner, burst header, MGR_CTRL, Test-Logic-Reset resets;
    # bit 7: MGR_SELECT_COUNT
    assert await manager_read(dut, 0xF010) == 0xFF
    assert await manager_read(dut, 0xF008) == 0
    assert await manager_read(dut, 0xEFFF) == 0
    assert int(dut.slot_rd_en.value) & 1
    assert await manager_read(dut, 0xF000) == _VERSION_HI | 0x434D
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
    await Timer(1, unit="ns")
    assert int(dut.burst_rd_data.value) == 0xB1
    assert int(dut.burst_rd_ts_data.value) == 1
    # The start event is the manager's own: no BURST_PTR write yet.
    assert int(dut.burst_start.value) == 0
    assert int(dut.burst_timestamp.value) == 0
    assert int(dut.burst_start_ptr.value) == 0xB
    await manager_write(dut, 0xF008, 7)
    assert await manager_read(dut, 0xF008) == 1
    # MGR_SELECT_COUNT: every MGR_ACTIVE write, the refused one too, and
    # nothing else; a hub soft reset keeps it.
    assert await manager_read(dut, 0xF034) == 4
    await manager_write(dut, 0xF014, 1)
    await manager_write(dut, 0xF024, 5)
    assert await manager_read(dut, 0xF034) == 4
    await manager_write(dut, 0xF028, 1)
    for _ in range(3):
        await FallingEdge(dut.jtag_clk)
    assert await manager_read(dut, 0xF008) == 0
    assert await manager_read(dut, 0xF034) == 4


@cocotb.test()
async def fcapz_core_manager_burst_start_per_write(dut):
    """Every BURST_PTR write to a burst slot is a new start at the pipe.

    Each slot toggles its own start flag on its own BURST_PTR writes, but the
    pipe keeps one last-seen copy. Moving the burst from slot 0 to slot 1
    when both flags hold the same value must still read as a start, or the
    pipe reads slot 1 from slot 0's old pointer.
    """
    cocotb.start_soon(Clock(dut.jtag_clk, 10, unit="ns").start())
    manager_reset(dut, 1)
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    dut.slot_rdata.value = 0
    dut.slot_burst_rd_data.value = 0
    dut.slot_burst_rd_ts_data.value = 0
    if hasattr(dut, "burst_rd_active"):
        dut.burst_rd_active.value = 0
    dut.slot_burst_start.value = 0
    dut.slot_burst_timestamp.value = 0
    dut.slot_burst_start_ptr.value = (0xC << 8) | (0xB << 4) | 0xA
    for _ in range(3):
        await FallingEdge(dut.jtag_clk)
    manager_reset(dut, 0)
    await FallingEdge(dut.jtag_clk)

    flags = [0, 0, 0]

    async def burst_ptr_write(slot: int) -> None:
        # What the slot does on the same edge: an ELA toggles its own flag.
        await manager_write(dut, 0xF008, slot)
        await manager_write(dut, 0x002C, 0)
        flags[slot] ^= 1
        dut.slot_burst_start.value = flags[0] | (flags[1] << 1) | (flags[2] << 2)
        await Timer(1, unit="ns")

    seen = int(dut.burst_start.value)
    for slot, ptr in ((0, 0xA), (1, 0xB), (0, 0xA), (0, 0xA), (1, 0xB), (1, 0xB)):
        await burst_ptr_write(slot)
        now = int(dut.burst_start.value)
        assert now != seen, f"BURST_PTR write to slot {slot} (flags {flags}) raised no start"
        assert int(dut.burst_start_ptr.value) == ptr
        seen = now

    # Slot 2 has no burst wiring, and other writes are not starts.
    await burst_ptr_write(2)
    assert int(dut.burst_start.value) == seen
    await manager_write(dut, 0xF008, 0)
    await manager_write(dut, 0x0020, 0x1234)
    await manager_write(dut, 0xF02C, 0)
    await Timer(1, unit="ns")
    assert int(dut.burst_start.value) == seen


@cocotb.test()
async def fcapz_core_manager_resets(dut):
    """Epochs, MGR_OWNER, MGR_CTRL, the Test-Logic-Reset count and the header."""
    cocotb.start_soon(Clock(dut.jtag_clk, 10, unit="ns").start())
    manager_reset(dut, 1)
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    dut.slot_rdata.value = 0
    dut.slot_burst_rd_data.value = 0
    dut.slot_burst_rd_ts_data.value = 0
    dut.burst_rd_active.value = 0
    dut.slot_burst_start.value = 0
    dut.slot_burst_timestamp.value = 0b010
    dut.slot_burst_start_ptr.value = (0xC << 8) | (0xB << 4) | 0xA

    requests: list[int] = []

    async def watch_requests() -> None:
        while True:
            await RisingEdge(dut.jtag_clk)
            if int(dut.slot_rst_req.value):
                requests.append(int(dut.slot_rst_req.value))

    cocotb.start_soon(watch_requests())
    for _ in range(3):
        await FallingEdge(dut.jtag_clk)
    manager_reset(dut, 0)
    await FallingEdge(dut.jtag_clk)

    async def slot_epoch(slot: int) -> int:
        await manager_write(dut, 0xF014, slot)
        return await manager_read(dut, 0xF02C)

    # The counters never reset, and earlier tests of this simulation counted
    # too: measure from here.
    epoch = await manager_read(dut, 0xF020)
    assert epoch >= 1
    tlr_count = await manager_read(dut, 0xF030)
    base = [await slot_epoch(s) for s in range(3)]
    await manager_write(dut, 0xF024, 0xA5A5_0001)
    assert await manager_read(dut, 0xF024) == 0xA5A5_0001
    await manager_write(dut, 0xF008, 1)

    # A slot's own reset counts in its epoch only, at both edges: odd while
    # it is held (BUG-235).
    dut.slot_rst.value = 0b010
    await FallingEdge(dut.jtag_clk)
    await FallingEdge(dut.jtag_clk)
    assert [await slot_epoch(s) for s in range(3)] == [base[0], base[1] + 1, base[2]]
    dut.slot_rst.value = 0
    await FallingEdge(dut.jtag_clk)
    assert [await slot_epoch(s) for s in range(3)] == [base[0], base[1] + 2, base[2]]

    # MGR_CTRL: bit 1 requests DESC_INDEX's slot, bit 2 every slot, one
    # cycle each; MGR_CTRL reads 0.
    await manager_write(dut, 0xF014, 2)
    await manager_write(dut, 0xF028, 0x2)
    await FallingEdge(dut.jtag_clk)
    await FallingEdge(dut.jtag_clk)
    assert requests == [0b100], requests
    requests.clear()
    await manager_write(dut, 0xF028, 0x4)
    await FallingEdge(dut.jtag_clk)
    await FallingEdge(dut.jtag_clk)
    assert requests == [0b111], requests
    requests.clear()
    assert await manager_read(dut, 0xF028) == 0
    assert await manager_read(dut, 0xF008) == 1
    assert await manager_read(dut, 0xF020) == epoch

    # Bit 0 resets the hub: ACTIVE, DESC_INDEX and the owner; no slot request.
    await manager_write(dut, 0xF028, 0x1)
    await FallingEdge(dut.jtag_clk)
    await FallingEdge(dut.jtag_clk)
    assert await manager_read(dut, 0xF020) == epoch + 2
    assert await manager_read(dut, 0xF008) == 0
    assert await manager_read(dut, 0xF014) == 0
    assert await manager_read(dut, 0xF024) == 0
    assert requests == []

    # Test-Logic-Reset counts once per entry.
    dut.tlr.value = 1
    for _ in range(3):
        await FallingEdge(dut.jtag_clk)
    dut.tlr.value = 0
    await FallingEdge(dut.jtag_clk)
    assert await manager_read(dut, 0xF030) == tlr_count + 1

    # The burst header of a BURST_PTR write to slot 1.
    await manager_write(dut, 0xF008, 1)
    await manager_write(dut, 0xF024, 0x1234)
    await manager_write(dut, 0x002C, 0)
    await Timer(1, unit="ns")
    header = int(dut.burst_header.value)
    assert header & 0xFFFF == 0x4248
    assert (header >> 16) & 0xFFFF == 1
    assert (header >> 32) & 0xFFFF_FFFF == 0xB
    assert (header >> 64) & 1 == 1
    assert (header >> 65) & 0x7FFF == 0
    assert (header >> 80) & 0xFFFF == epoch + 2
    assert (header >> 96) & 0xFFFF == base[1] + 2
    assert (header >> 112) & 0xFFFF_FFFF == 0x1234
    assert (header >> 144) & 0xFFFF == 8

    # proto_rst clears only the burst start event.
    assert int(dut.burst_start.value) == 1
    dut.proto_rst.value = 1
    await FallingEdge(dut.jtag_clk)
    dut.proto_rst.value = 0
    await FallingEdge(dut.jtag_clk)
    assert int(dut.burst_start.value) == 0
    assert await manager_read(dut, 0xF008) == 1
    assert await manager_read(dut, 0xF024) == 0x1234
    assert await manager_read(dut, 0xF020) == epoch + 2


@cocotb.test()
async def fcapz_core_manager_epoch_parity(dut):
    """An epoch's parity is the reset level whatever its counters hold.

    PolarFire ignores initial values, so the release counters and the
    registered reset levels power up random; an odd epoch with no reset held
    would make the host refuse the slot for good.
    """
    cocotb.start_soon(Clock(dut.jtag_clk, 10, unit="ns").start())
    manager_reset(dut, 0)
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.burst_rd_active.value = 0
    await FallingEdge(dut.jtag_clk)
    if hasattr(dut, "u_dut"):
        # GHDL keeps a forced or deposited signal after Release, so the VHDL
        # twin cannot start from garbage here; formal parity covers it.
        cocotb.pass_test("Verilog only: GHDL cannot release a forced signal")
    # Force for half a cycle, then release.
    core = dut
    garbage = {
        "mgr_releases": 0x2AAB,
        "mgr_rst_d": 1,
        "slot_releases": (0x7FFF << 30) | (0x1235 << 15) | 0x0001,
        "slot_rst_d": 0b101,
    }
    for name, value in garbage.items():
        getattr(core, name).value = Force(value)
    await RisingEdge(dut.jtag_clk)
    await Timer(1, unit="ns")
    for name in garbage:
        getattr(core, name).value = Release()
    await FallingEdge(dut.jtag_clk)
    await FallingEdge(dut.jtag_clk)

    async def slot_epoch(slot: int) -> int:
        await manager_write(dut, 0xF014, slot)
        return await manager_read(dut, 0xF02C)

    epoch = await manager_read(dut, 0xF020)
    assert epoch % 2 == 0, epoch
    base = [await slot_epoch(s) for s in range(3)]
    assert [e % 2 for e in base] == [0, 0, 0], base

    dut.slot_rst.value = 0b001
    await FallingEdge(dut.jtag_clk)
    await FallingEdge(dut.jtag_clk)
    assert await slot_epoch(0) == (base[0] + 1) & 0xFFFF
    dut.slot_rst.value = 0
    await FallingEdge(dut.jtag_clk)
    assert [await slot_epoch(s) for s in range(3)] == [
        (base[0] + 2) & 0xFFFF, base[1], base[2]]
    await manager_write(dut, 0xF028, 0x1)
    await FallingEdge(dut.jtag_clk)
    await FallingEdge(dut.jtag_clk)
    assert await manager_read(dut, 0xF020) == (epoch + 2) & 0xFFFF


@cocotb.test()
async def fcapz_ela_channel_mux(dut):
    cocotb.start_soon(Clock(dut.sample_clk, 10, unit="ns").start())
    cocotb.start_soon(Clock(dut.jtag_clk, 14, unit="ns").start())
    dut.sample_rst.value = 1
    dut.jtag_rst.value = 1
    dut.probe_in.value = (0xCC << 16) | (0xBB << 8) | 0xAA
    dut.trigger_in.value = 0
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    if hasattr(dut, "burst_rd_active"):
        dut.burst_rd_active.value = 0
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
async def fcapz_ela_seq_count_saturates(dut):
    """BUG-255: hits the external-trigger AND holds back keep counting.

    A 16-bit counter wrapped after 65535 of them, so a stage whose count was
    long met read as not reached again until it re-counted to its target.
    With a target of 0x8000 and ~1000 hits past the wrap, the old RTL ignored
    the external trigger for ~31000 more cycles; the counter now saturates.
    """
    cocotb.start_soon(Clock(dut.sample_clk, 10, unit="ns").start())
    cocotb.start_soon(Clock(dut.jtag_clk, 14, unit="ns").start())
    dut.sample_rst.value = 1
    dut.jtag_rst.value = 1
    dut.probe_in.value = 0x55
    dut.trigger_in.value = 0
    dut.jtag_wr_en.value = 0
    dut.jtag_rd_en.value = 0
    dut.jtag_addr.value = 0
    dut.jtag_wdata.value = 0
    if hasattr(dut, "burst_rd_active"):
        dut.burst_rd_active.value = 0
    dut.burst_rd_addr.value = 0
    for _ in range(4):
        await RisingEdge(dut.sample_clk)
    dut.sample_rst.value = 0
    for _ in range(2):
        await RisingEdge(dut.jtag_clk)
    dut.jtag_rst.value = 0
    for _ in range(4):
        await RisingEdge(dut.jtag_clk)

    target = 0x8000
    # Stage 0: final, comparator A EQ 0x55 on every bit, count target 0x8000.
    await jtag_write(dut, 0x0040, (target << 16) | (1 << 12))
    await jtag_write(dut, 0x0044, 0x55)
    await jtag_write(dut, 0x0048, 0xFF)
    await jtag_write(dut, 0x00B4, 2)          # external trigger: AND
    await jtag_write(dut, 0x0014, 0)          # no pretrigger history
    await jtag_write(dut, 0x0018, 2)
    await arm_ela(dut)

    # Every sample matches, so the stage counts every cycle while the
    # external trigger holds the hit back: run ~1000 hits past the wrap.
    await ClockCycles(dut.sample_clk, 0x10000 + 1000)
    assert not (await jtag_read(dut, 0x0008)) & 0x2, "triggered without trigger_in"

    dut.trigger_in.value = 1
    for _ in range(200):
        await RisingEdge(dut.sample_clk)
        if int(dut.trigger_out.value):
            break
    else:
        raise AssertionError(
            "count target long met, but trigger_in did not trigger: "
            "the stage hit counter wrapped"
        )
    for _ in range(100):
        await RisingEdge(dut.sample_clk)
    assert (await jtag_read(dut, 0x0008)) & 0x2, "STATUS.triggered not set"


@cocotb.test()
async def fcapz_ela_xilinx7_single_chain(dut):
    cocotb.start_soon(Clock(dut.sample_clk, 6, unit="ns").start())
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
        await Timer(5, unit="ns")
        tap.TCK.value = 1
        await Timer(1, unit="ns")
        tap.TCK.value = 0
        await Timer(4, unit="ns")

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


# fcapz_debug_multi_<vendor> shells as the fcapz_debug_multi_* targets in
# sim/run_cocotb.py build them: default slots (two 8-bit ELAs, DEPTH 1024,
# one 1-bit EIO) on a nondefault chain; the *_tlr targets add TLR_RESET_EN.
_DEBUG_MULTI_CHAIN = 3
# ECP5 and Gowin have two user chains; PolarFire selects by UJTAG IR opcode.
_DEBUG_MULTI_ER_CHAIN = 2
_DEBUG_MULTI_POLARFIRE_IR = 0x24
_DEBUG_MULTI_SAMPLE_W = 8
_DEBUG_MULTI_DEPTH = 1024
_DEBUG_MULTI_BURST_W = 256
# MGR_CAPS of the shell; bit 6 is TLR_RESET_EN.
_DEBUG_MULTI_CAPS = 0xBF
_MGR_CAPS_TLR_RESET = 0x40


def _debug_multi_primitive(dut):
    """Return (primitive, pin names, chain parameter name or None, select level)
    for the shell's TAP stub.  A pin named None does not exist on that TAP."""
    target = os.environ.get("FCAPZ_COCOTB_TARGET", "")
    vendor = next(v for v in ("xilinx7", "xilinxus", "intel", "polarfire", "efinix")
                  if f"_{v}" in target)
    if vendor == "intel":
        # sld_virtual_jtag has no sel; jtag_tap_intel ties it high.
        pins = dict(tck="tck", tdi="tdi", capture="virtual_state_cdr",
                    shift="virtual_state_sdr", update="virtual_state_udr", sel=None,
                    tlr="jtag_state_tlr")
        return dut.u_tap_ctrl.u_vjtag, pins, "sld_instance_index", 1
    if vendor == "polarfire":
        # UJTAG selects the chain by the user instruction in UIREG.
        pins = dict(tck="UDRCK", tdi="UTDI", capture="UDRCAP", shift="UDRSH",
                    update="UDRUPD", sel="UIREG", tlr=None)
        # The VHDL shell keeps the default IR_USER1 (run_cocotb.py).
        ir = _DEBUG_MULTI_POLARFIRE_IR if os.environ.get("FCAPZ_COCOTB_HDL") == "verilog" else 0x20
        return dut.u_tap_ctrl.u_ujtag, pins, None, ir
    if vendor == "efinix":
        # The Interface Designer User TAP block's signals are shell ports.
        pins = dict(tck="jtag1_tck", tdi="jtag1_tdi", capture="jtag1_capture",
                    shift="jtag1_shift", update="jtag1_update", sel="jtag1_sel", tlr=None)
        return dut, pins, None, 1
    pins = dict(tck="TCK", tdi="TDI", capture="CAPTURE", shift="SHIFT",
                update="UPDATE", sel="SEL", tlr="RESET")
    ctrl = dut.u_tap_ctrl.u_tap if vendor == "xilinxus" else dut.u_tap_ctrl
    return ctrl.u_bscan, pins, "JTAG_CHAIN", 1


def _check_burst_header(header: int, *, slot: int, mgr_epoch: int, slot_epoch: int,
                        owner: int) -> None:
    """The priming scan of a burst carries the manager's burst header."""
    assert header & 0xFFFF == 0x4248, f"header magic {header & 0xFFFF:#x}"
    assert (header >> 16) & 0xFFFF == slot, "header slot"
    assert (header >> 32) & 0xFFFF_FFFF < _DEBUG_MULTI_DEPTH, "header start pointer"
    assert (header >> 64) & 1 == 0, "header timestamp select"
    assert (header >> 65) & 0x7FFF == 0, "header reserved bits"
    assert (header >> 80) & 0xFFFF == mgr_epoch, "header MGR_EPOCH"
    assert (header >> 96) & 0xFFFF == slot_epoch, "header slot epoch"
    assert (header >> 112) & 0xFFFF_FFFF == owner, "header MGR_OWNER"
    assert (header >> 144) & 0xFFFF == _DEBUG_MULTI_SAMPLE_W, "header SAMPLE_W"
    assert header >> 160 == 0, "header upper bits"


class _DebugMultiBench:
    """Drives an fcapz_debug_multi_<vendor> shell at its TAP primitive's pins."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.prim, pins, self.chain_param, self.sel_on = _debug_multi_primitive(dut)
        self.pin = {role: getattr(self.prim, name) for role, name in pins.items() if name}
        self.intel = pins["sel"] is None
        # Whether scan(ours=False) scans another instruction's register.
        self.foreign_scans = False
        self.rng = random.Random(0x5EED)
        # A probe value per ELA that replaces its count while not None.
        self.hold: list[int | None] = [None, None]

    def _tap_init(self) -> None:
        if self.chain_param and os.environ.get("FCAPZ_COCOTB_HDL") == "verilog":
            assert int(getattr(self.prim, self.chain_param).value) == _DEBUG_MULTI_CHAIN
        for role in ("tck", "tdi", "capture", "shift", "update", "sel", "tlr"):
            if role in self.pin:
                self.pin[role].value = 0

    async def start(self) -> None:
        dut = self.dut
        self._tap_init()
        # Shell inputs the bench does not use (JTAG pads, Efinix's DR clock).
        for name in ("jtag1_drck", "tck_pad_i", "tms_pad_i", "tdi_pad_i", "trstb_pad_i",
                     "hub_por"):
            if hasattr(dut, name):
                getattr(dut, name).value = 0
        dut.ela_sample_clk.value = 0
        dut.ela_sample_rst.value = 0b11
        dut.ela_probe_in.value = 0
        dut.ela_trigger_in.value = 0
        dut.eio_probe_in.value = 0
        cocotb.start_soon(self._sample_clocks())
        await self.idle(8)
        await Timer(60, unit="ns")
        dut.ela_sample_rst.value = 0
        await self.idle(12)

    async def _sample_clocks(self) -> None:
        # Both ELAs on one clock; ELA0 counts up, ELA1 counts down, each held
        # at 0 by its own sample reset.
        dut = self.dut
        up = down = 0
        while True:
            dut.ela_sample_clk.value = 0b11
            await Timer(3, unit="ns")
            dut.ela_sample_clk.value = 0b00
            rst = int(dut.ela_sample_rst.value)
            up = 0 if rst & 1 else (up + 1) & 0xFF
            down = 0 if rst & 2 else (down - 1) & 0xFF
            probe = [up if self.hold[0] is None else self.hold[0],
                     down if self.hold[1] is None else self.hold[1]]
            dut.ela_probe_in.value = (probe[1] << _DEBUG_MULTI_SAMPLE_W) | probe[0]
            await Timer(3, unit="ns")

    async def tck_tick(self) -> None:
        tck = self.pin["tck"]
        tck.value = 0
        await Timer(5, unit="ns")
        tck.value = 1
        await Timer(1, unit="ns")
        tck.value = 0
        await Timer(4, unit="ns")

    async def idle(self, n: int) -> None:
        # On Intel, TCK keeps running for the other virtual JTAG instances
        # while this one's states are low; tdi carries their traffic.
        pin = self.pin
        for role in ("capture", "shift", "update", "sel"):
            if role in pin:
                pin[role].value = 0
        for _ in range(n):
            pin["tdi"].value = self.rng.getrandbits(1) if self.intel else 0
            await self.tck_tick()
        pin["tdi"].value = 0

    async def scan(self, bits: int, frame: int = 0) -> int:
        """One DR scan of this shell's register."""
        pin = self.pin
        captured = 0
        if "sel" in pin:
            pin["sel"].value = self.sel_on
        if "capture" in pin:
            pin["capture"].value = 1
        await self.tck_tick()
        if "capture" in pin:
            pin["capture"].value = 0
        pin["shift"].value = 1
        for i in range(bits):
            pin["tdi"].value = (frame >> i) & 1
            if self._tdo():
                captured |= 1 << i
            await self.tck_tick()
        pin["shift"].value = 0
        pin["tdi"].value = 0
        pin["update"].value = 1
        await self.tck_tick()
        pin["update"].value = 0
        if "sel" in pin:
            pin["sel"].value = 0
        return captured

    def _tdo(self) -> int:
        return int(self.dut.tap_tdo.value)

    async def read(self, addr: int) -> int:
        await self.scan(49, make_frame(addr, 0, False))
        await self.idle(2)
        data = await self.scan(49, make_frame(addr, 0, False)) & 0xFFFF_FFFF
        await self.idle(2)
        return data

    async def write(self, addr: int, data: int) -> None:
        await self.scan(49, make_frame(addr, data, True))
        await self.idle(8)

    async def test_logic_reset(self) -> None:
        """The TAP passes through Test-Logic-Reset while TCK runs."""
        self.pin["tlr"].value = 1
        await self.idle(4)
        self.pin["tlr"].value = 0
        await self.idle(4)

    async def slot_epoch(self, slot: int) -> int:
        await self.write(0xF014, slot)
        return await self.read(0xF02C)

    async def slot_epochs(self) -> list[int]:
        return [await self.slot_epoch(slot) for slot in range(3)]

    async def capture(self, slot: int, pretrig: int = 8, posttrig: int = 40) -> int:
        """Arm ELA *slot* on sample 0x80 and wait for DONE; return the capture length."""
        await self.write(0xF008, slot)
        assert await self.read(0xF008) == slot
        await self.write(0x0014, pretrig)
        await self.write(0x0018, posttrig)
        await self.write(0x0020, 1)
        await self.write(0x0024, 0x80)
        await self.write(0x0028, 0xFF)
        await self.write(0x0004, 1)
        status = 0
        for _ in range(200):
            await self.idle(8)
            status = await self.read(0x0008)
            if status & 0x4:
                break
        assert status & 0x4, f"slot {slot} never reached DONE"
        capture_len = pretrig + posttrig + 1
        assert await self.read(0x001C) == capture_len
        return capture_len

    async def burst(self, slot: int, capture_len: int, step: int) -> int:
        """Burst-read ELA *slot*'s capture (ACTIVE already on it); return the header."""
        per_packet = _DEBUG_MULTI_BURST_W // _DEBUG_MULTI_SAMPLE_W
        await self.write(0x002C, 0)
        await self.idle(160)
        header = await self.scan(_DEBUG_MULTI_BURST_W)  # priming scan
        first = await self.scan(_DEBUG_MULTI_BURST_W)
        second = await self.scan(_DEBUG_MULTI_BURST_W)
        samples = [sample_at(first, i) for i in range(per_packet)]
        samples += [sample_at(second, i) for i in range(capture_len - per_packet)]
        for i in range(1, capture_len):
            assert samples[i] == (samples[i - 1] + step) & 0xFF, \
                f"slot {slot} sample {i}: {samples[i - 1]:#x} -> {samples[i]:#x}"
        assert 0x80 in samples, f"slot {slot} trigger sample missing"
        return header

    async def check_capture(self, slot: int, capture_len: int, step: int) -> None:
        """Read ELA *slot*'s capture back the fastest way the shell offers."""
        await self.burst(slot, capture_len, step)


class _Ecp5DebugMultiBench(_DebugMultiBench):
    """Drives fcapz_debug_multi_ecp5 through the JTAG pins of its JTAGG model.

    sim/jtagg_stub.v models JTAGG's timing (TDI registered on the rising edge,
    TDO on the falling edge), so a full TAP walk is the only way in: each scan
    selects ER<CTRL_CHAIN> with an instruction scan first.
    """

    _IR_ER = {1: 0x32, 2: 0x38}
    _IR_BYPASS = 0xFF

    def __init__(self, dut) -> None:
        self.dut = dut
        self.prim = dut.u_tap_ctrl.u_jtagg
        self.pin = {}
        self.chain_param = None
        self.intel = False
        self.foreign_scans = True
        self.ir: int | None = None
        self.rng = random.Random(0x5EED)
        self.hold = [None, None]

    def _tap_init(self) -> None:
        self.prim.tck_pin.value = 0
        self.prim.tms_pin.value = 1
        self.prim.tdi_pin.value = 0

    async def tck_tick(self, tms: int = 0, tdi: int = 0) -> int:
        """One TCK period; returns TDO as sampled before the rising edge."""
        prim = self.prim
        prim.tms_pin.value = tms
        prim.tdi_pin.value = tdi
        await Timer(5, unit="ns")
        tdo = int(prim.tdo_pin.value)
        prim.tck_pin.value = 1
        await Timer(5, unit="ns")
        prim.tck_pin.value = 0
        return tdo

    async def idle(self, n: int) -> None:
        # Run-Test/Idle (the first tick leaves Test-Logic-Reset).
        for _ in range(n):
            await self.tck_tick()

    async def _load_ir(self, ir: int) -> None:
        for tms in (1, 1, 0, 0):  # Select-DR, Select-IR, Capture-IR, Shift-IR
            await self.tck_tick(tms)
        for i in range(8):
            await self.tck_tick(int(i == 7), (ir >> i) & 1)
        await self.tck_tick(1)  # Update-IR
        await self.tck_tick(0)  # Run-Test/Idle
        self.ir = ir

    async def scan(self, bits: int, frame: int = 0, ours: bool = True) -> int:
        """One DR scan; *ours* False scans BYPASS instead, whose Update-DR
        JTAGG still flags on JUPDATE."""
        ir = self._IR_ER[_DEBUG_MULTI_ER_CHAIN] if ours else self._IR_BYPASS
        if self.ir != ir:
            await self._load_ir(ir)
        for tms in (1, 0, 0):  # Select-DR, Capture-DR, Shift-DR
            await self.tck_tick(tms)
        captured = 0
        for i in range(bits):
            if await self.tck_tick(int(i == bits - 1), (frame >> i) & 1):
                captured |= 1 << i
        await self.tck_tick(1)  # Exit1-DR -> Update-DR
        await self.tck_tick(0)  # Run-Test/Idle
        return captured


def _debug_multi_bench(dut) -> _DebugMultiBench:
    target = os.environ.get("FCAPZ_COCOTB_TARGET", "")
    if "_gowin" in target:
        return _GowinDebugMultiBench(dut)
    if "_ecp5" in target:
        return _Ecp5DebugMultiBench(dut)
    return _DebugMultiBench(dut)


@cocotb.test()
async def fcapz_debug_multi_wrapper(dut):
    tb = _debug_multi_bench(dut)
    await tb.start()

    # Manager identity and slot descriptors
    assert await tb.read(0xF000) & 0xFFFF == 0x434D
    assert await tb.read(0xF004) == 3
    assert await tb.read(0xF010) & ~_MGR_CAPS_TLR_RESET == _DEBUG_MULTI_CAPS
    for slot, (core, burst) in enumerate(((0x4C41, 1), (0x4C41, 1), (0x494F, 0))):
        await tb.write(0xF014, slot)
        assert await tb.read(0xF018) == core, f"slot {slot} core id"
        assert await tb.read(0xF01C) == burst, f"slot {slot} burst capability"

    if tb.foreign_scans:
        # BUG-275: a write commits at Update-DR with JCE already low, and the
        # Update-DR of another instruction's scan does not repeat it
        # (MGR_SELECT_COUNT counts every MGR_ACTIVE write).
        count = await tb.read(0xF034)
        await tb.write(0xF008, 1)
        await tb.scan(49, make_frame(0xF008, 1, True), ours=False)
        await tb.idle(8)
        assert await tb.read(0xF008) == 1
        assert await tb.read(0xF034) == (count + 1) & 0xFFFF
        await tb.write(0xF008, 0)

    # Each ELA: capture, then two burst packets, then straight back to the
    # register path by switching ACTIVE.
    await tb.write(0xF024, 0x0BAD_F00D)
    mgr_epoch = await tb.read(0xF020)
    epochs = await tb.slot_epochs()
    for slot, step in ((0, 1), (1, -1)):
        capture_len = await tb.capture(slot)
        header = await tb.burst(slot, capture_len, step)
        _check_burst_header(header, slot=slot, mgr_epoch=mgr_epoch,
                            slot_epoch=epochs[slot], owner=0x0BAD_F00D)

        await tb.write(0xF008, 1 - slot)
        assert await tb.read(0xF008) == 1 - slot
        assert await tb.read(0x0010) == _DEBUG_MULTI_DEPTH

    # EIO slot
    await tb.write(0xF008, 2)
    assert await tb.read(0x0004) == 1
    assert await tb.read(0x0008) == 1
    for level in (1, 0):
        await tb.write(0x0100, level)
        await tb.idle(8)
        assert int(dut.eio_probe_out.value) == level
        dut.eio_probe_in.value = level
        await tb.idle(8)
        assert await tb.read(0x0010) == level


@cocotb.test()
async def fcapz_debug_multi_resets(dut):
    """Each slot resets alone; MGR_CTRL resets the hub or slots (BUG-229)."""
    tb = _debug_multi_bench(dut)
    await tb.start()

    # The hub resets only at power-up, and the counters never: tests that ran
    # before in this simulation leave theirs.  Measure from here.
    mgr_epoch = await tb.read(0xF020)
    assert mgr_epoch >= 1
    e0, e1, e2 = await tb.slot_epochs()

    # ELA 1 armed once and DONE, so its arm toggle is odd; its probe then
    # stops off the trigger value, so a phantom arm would stay armed.  EIO
    # output high, ACTIVE on ELA 1, an owner token.
    capture_len = await tb.capture(1)
    tb.hold[1] = 0x00
    await tb.write(0xF008, 2)
    await tb.write(0x0100, 1)
    await tb.write(0xF024, 0xC0FFEE)
    await tb.write(0xF008, 1)

    # ELA 0's own sample reset reaches only ELA 0.
    dut.ela_sample_rst.value = 0b01
    await tb.idle(20)
    dut.ela_sample_rst.value = 0
    await tb.idle(40)
    status = await tb.read(0x0008)
    assert status & 0x5 == 0x4, f"ELA 1 STATUS {status:#x} after ELA 0's reset (phantom arm)"
    assert await tb.read(0x001C) == capture_len
    assert await tb.read(0xF008) == 1, "ACTIVE lost to a slot reset"
    assert await tb.read(0xF024) == 0xC0FFEE, "MGR_OWNER lost to a slot reset"
    assert await tb.read(0xF020) == mgr_epoch, "a slot reset reset the hub"
    assert int(dut.eio_probe_out.value) == 1, "EIO output lost to a slot reset"
    assert await tb.slot_epochs() == [e0 + 2, e1, e2]
    tb.hold[1] = None
    # ELA 0 captures again after its reset.
    capture_len = await tb.capture(0)
    await tb.check_capture(0, capture_len, 1)

    # MGR_CTRL bit 1 resets the DESC_INDEX slot only.
    await tb.write(0xF008, 1)
    await tb.write(0xF014, 1)
    await tb.write(0xF028, 0x2)
    await tb.idle(40)
    assert await tb.read(0xF028) == 0
    assert await tb.read(0x0008) & 0x7 == 0, "ELA 1 not reset by MGR_CTRL bit 1"
    assert await tb.slot_epochs() == [e0 + 2, e1 + 2, e2]
    assert await tb.read(0xF008) == 1
    assert int(dut.eio_probe_out.value) == 1

    # Bit 2 resets every slot, the EIO outputs included, but not the hub.
    await tb.write(0xF028, 0x4)
    await tb.idle(40)
    assert await tb.slot_epochs() == [e0 + 4, e1 + 4, e2 + 2]
    assert int(dut.eio_probe_out.value) == 0
    assert await tb.read(0xF008) == 1
    assert await tb.read(0xF020) == mgr_epoch

    # Bit 0 resets the hub: ACTIVE, DESC_INDEX and the owner, not the slots.
    await tb.write(0xF008, 2)
    await tb.write(0x0100, 1)
    await tb.write(0xF014, 1)
    await tb.write(0xF028, 0x1)
    await tb.idle(8)
    assert await tb.read(0xF020) == mgr_epoch + 2
    assert await tb.read(0xF008) == 0
    assert await tb.read(0xF014) == 0
    assert await tb.read(0xF024) == 0
    assert int(dut.eio_probe_out.value) == 1
    assert await tb.slot_epochs() == [e0 + 4, e1 + 4, e2 + 2]


@cocotb.test()
async def fcapz_debug_multi_hub_por(dut):
    """hub_por resets the hub and every slot after hub_started is set.

    On PolarFire hub_started powers up random, so a hub that came up with it
    set never saw its power-up reset; hub_por, held while TCK is still
    idle, must give it one anyway.
    """
    tb = _debug_multi_bench(dut)
    await tb.start()
    mgr_epoch = await tb.read(0xF020)
    e0, e1, e2 = await tb.slot_epochs()
    capture_len = await tb.capture(1)
    assert capture_len > 0
    await tb.write(0xF008, 2)
    await tb.write(0x0100, 1)
    await tb.write(0xF024, 0xC0FFEE)
    await tb.write(0xF008, 1)
    assert int(dut.eio_probe_out.value) == 1

    # Power-on reset with no TCK, as at power-up.
    dut.hub_por.value = 1
    await Timer(200, unit="ns")
    assert int(dut.eio_probe_out.value) == 0, "hub_por did not reset the EIO outputs"
    dut.hub_por.value = 0
    await tb.idle(40)
    assert await tb.read(0xF024) == 0, "MGR_OWNER survived hub_por"
    assert await tb.read(0xF008) == 0, "ACTIVE survived hub_por"
    assert await tb.read(0xF020) == (mgr_epoch + 2) & 0xFFFF
    assert await tb.slot_epochs() == [e0 + 2, e1 + 2, e2 + 2]
    await tb.write(0xF008, 1)
    assert await tb.read(0x0008) & 0x7 == 0, "ELA 1 not reset by hub_por"

    # The hub runs as usual afterwards; a later slot reset stays local.
    dut.ela_sample_rst.value = 0b01
    await tb.idle(20)
    dut.ela_sample_rst.value = 0
    await tb.idle(40)
    assert await tb.read(0xF020) == (mgr_epoch + 2) & 0xFFFF
    capture_len = await tb.capture(0)
    await tb.check_capture(0, capture_len, 1)


@cocotb.test()
async def fcapz_debug_multi_tlr(dut):
    """Test-Logic-Reset is counted; with TLR_RESET_EN it also cancels a burst."""
    tb = _debug_multi_bench(dut)
    await tb.start()
    tlr_reset = os.environ.get("FCAPZ_COCOTB_TARGET", "").endswith("_tlr")
    caps = await tb.read(0xF010)
    assert caps == _DEBUG_MULTI_CAPS | (_MGR_CAPS_TLR_RESET if tlr_reset else 0), hex(caps)
    tlr_count = await tb.read(0xF030)
    mgr_epoch = await tb.read(0xF020)
    owner = await tb.read(0xF024)
    slot_epoch = await tb.slot_epoch(0)

    capture_len = await tb.capture(0)
    # BURST_PTR is written, so the next scan would prime the burst ...
    await tb.write(0x002C, 0)
    await tb.idle(160)
    # ... but the host restarts and walks the TAP through Test-Logic-Reset.
    await tb.test_logic_reset()
    first = await tb.scan(_DEBUG_MULTI_BURST_W)
    if tlr_reset:
        assert first & 0xFFFF != 0x4248, "burst survived Test-Logic-Reset"
    else:
        _check_burst_header(first, slot=0, mgr_epoch=mgr_epoch, slot_epoch=slot_epoch,
                            owner=owner)
    assert await tb.read(0xF030) == tlr_count + 1
    # Only the burst protocol was reset: the hub and the capture stay.
    assert await tb.read(0xF020) == mgr_epoch
    assert await tb.read(0xF008) == 0
    assert await tb.read(0x0008) & 0x4
    header = await tb.burst(0, capture_len, 1)
    _check_burst_header(header, slot=0, mgr_epoch=mgr_epoch, slot_epoch=slot_epoch,
                        owner=owner)
    await tb.test_logic_reset()
    assert await tb.read(0xF030) == tlr_count + 2


@cocotb.test()
async def fcapz_debug_multi_tlr_powerup(dut):
    """MGR_TLR_COUNT starts at 0 and counts only entries seen happen.

    Run alone on a fresh simulation (the *_powerup targets): the count has no
    reset, so it carries the power-up state.  The *_powerup_tlrhigh target
    holds the TAP in Test-Logic-Reset from time 0, as after configuration;
    that residency is not an entry.
    """
    target = os.environ.get("FCAPZ_COCOTB_TARGET", "")
    tb = _debug_multi_bench(dut)
    has_tlr = "tlr" in getattr(tb, "pin", {})
    start_high = target.endswith("_tlrhigh")
    assert has_tlr or not start_high
    if start_high:
        tap_init = tb._tap_init

        def _tap_init_in_tlr() -> None:
            tap_init()
            tb.pin["tlr"].value = 1

        tb._tap_init = _tap_init_in_tlr
    await tb.start()
    assert await tb.read(0xF030) == 0, "power-up counted as a Test-Logic-Reset"
    if not has_tlr:
        await tb.idle(16)
        assert await tb.read(0xF030) == 0
        return
    if start_high:
        tb.pin["tlr"].value = 0
        await tb.idle(4)
        assert await tb.read(0xF030) == 0, "Test-Logic-Reset at power-up counted"
    await tb.test_logic_reset()
    assert await tb.read(0xF030) == 1
    await tb.test_logic_reset()
    assert await tb.read(0xF030) == 2


class _GowinDebugMultiBench(_DebugMultiBench):
    """Drives fcapz_debug_multi_gowin at its GW_JTAG primitive's outputs.

    jtag_tap_gowin oversamples GW_JTAG on clk and acts once per TCK falling
    edge, so each tick holds TCK high and low for several clk periods.  The
    TAP state outputs change with TCK's rising edge.  The instruction (ER1 or
    ER2) stays loaded throughout, so enable_er<n>_o stays high; the TAP then
    raises capture on every falling edge outside a scan, from the
    shift_dr_capture_dr_o rise until the falling edge after Update-DR.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.prim = dut.u_tap_ctrl.u_jtag
        self.chain_idx = _DEBUG_MULTI_ER_CHAIN - 1
        self.intel = False
        self.rng = random.Random(0x5EED)
        self.hold: list[int | None] = [None, None]

    def _tap_init(self) -> None:
        prim = self.prim
        cocotb.start_soon(Clock(self.dut.clk, 10, unit="ns").start())
        for name in ("tck_o", "tdi_o", "shift_dr_capture_dr_o", "update_dr_o"):
            getattr(prim, name).value = 0
        prim.enable_er1_o.value = int(self.chain_idx == 0)
        prim.enable_er2_o.value = int(self.chain_idx == 1)

    async def start(self) -> None:
        await super().start()
        # jtag_tap_gowin's hold and chain flags have no reset; the first
        # scan sets them.  It reads address 0, which changes nothing.
        await self.scan(49)
        await self.idle(4)

    async def gw_tick(self, sc: int = 0, update: int = 0, tdi: int = 0) -> int:
        """One TCK period; return the chain's TDO as it stood before TCK fell."""
        prim = self.prim
        prim.tck_o.value = 1
        prim.shift_dr_capture_dr_o.value = sc
        prim.update_dr_o.value = update
        prim.tdi_o.value = tdi
        await Timer(50, unit="ns")
        tdo = self._tdo()
        prim.tck_o.value = 0
        await Timer(50, unit="ns")
        return tdo

    def _tdo(self) -> int:
        return (int(self.dut.tap_tdo.value) >> self.chain_idx) & 1

    async def idle(self, n: int) -> None:
        for _ in range(n):
            await self.gw_tick()

    async def check_capture(self, slot: int, capture_len: int, step: int) -> None:
        # No burst path: the capture comes through the register window.
        samples = [await self.read(0x0100 + 4 * i) & 0xFF for i in range(capture_len)]
        for i in range(1, capture_len):
            assert samples[i] == (samples[i - 1] + step) & 0xFF, (
                f"slot {slot} sample {i}: {samples[i - 1]:#x} -> {samples[i]:#x}"
            )
        assert 0x80 in samples, f"slot {slot} trigger sample missing"

    async def scan(self, bits: int, frame: int = 0) -> int:
        # Capture-DR, bits Shift-DR states, then Exit1-DR: the TAP shifts in
        # on the falling edge after each shift_dr_capture_dr_o one, so TDI
        # lags a tick behind TDO.
        captured = 0
        for k in range(bits + 1):
            tdi = (frame >> (k - 1)) & 1 if k else 0
            tdo = await self.gw_tick(sc=int(k < bits), tdi=tdi)
            if k < bits:
                captured |= tdo << k
        await self.gw_tick(update=1)
        await self.gw_tick()
        return captured


@cocotb.test()
async def fcapz_debug_multi_gowin(dut):
    """The register-only Gowin hub: no slot bursts, captures read back
    through the register window."""
    tb = _GowinDebugMultiBench(dut)
    await tb.start()

    assert await tb.read(0xF000) & 0xFFFF == 0x434D
    assert await tb.read(0xF004) == 3
    # No burst header and no Test-Logic-Reset reset.
    assert await tb.read(0xF010) == _DEBUG_MULTI_CAPS & ~0x50
    for slot, core in enumerate((0x4C41, 0x4C41, 0x494F)):
        await tb.write(0xF014, slot)
        assert await tb.read(0xF018) == core, f"slot {slot} core id"
        assert await tb.read(0xF01C) == 0, f"slot {slot} burst capability"

    for slot, step in ((0, 1), (1, -1)):
        await tb.check_capture(slot, await tb.capture(slot), step)

    await tb.write(0xF008, 2)
    assert await tb.read(0x0004) == 1
    for level in (1, 0):
        await tb.write(0x0100, level)
        await tb.idle(8)
        assert int(dut.eio_probe_out.value) == level
        dut.eio_probe_in.value = level
        await tb.idle(8)
        assert await tb.read(0x0010) == level


# fcapz_axi_mon_<vendor> wrappers as the fcapz_axi_mon_* targets in
# sim/run_cocotb.py build them: AXI4-Lite 32/32 (152-bit samples), DEPTH 64,
# one trigger stage (so TRIG_VALUE/TRIG_MASK trigger), on the chain or IR the
# debug-multi benches drive.
# The flattened sample, LSB first: (port, width) as fcapz_axi_mon packs it.
_AXI_MON_FIELDS = (
    ("AWADDR", 32), ("AWPROT", 3), ("AWVALID", 1), ("AWREADY", 1),
    ("WDATA", 32), ("WSTRB", 4), ("WVALID", 1), ("WREADY", 1),
    ("BRESP", 2), ("BVALID", 1), ("BREADY", 1),
    ("ARADDR", 32), ("ARPROT", 3), ("ARVALID", 1), ("ARREADY", 1),
    ("RDATA", 32), ("RRESP", 2), ("RVALID", 1), ("RREADY", 1),
)
_AXI_MON_SAMPLE_W = sum(width for _, width in _AXI_MON_FIELDS)
_AXI_MON_WORDS = (_AXI_MON_SAMPLE_W + 31) // 32


def _axi_mon_flatten(beat: dict[str, int]) -> int:
    sample, pos = 0, 0
    for name, width in _AXI_MON_FIELDS:
        sample |= beat[name] << pos
        pos += width
    return sample


class _AxiMonBench:
    """Starts an fcapz_axi_mon_<vendor> wrapper in place of a debug-multi
    shell; the vendor bench it is mixed into drives the TAP."""

    async def start(self) -> None:
        dut = self.dut
        self._tap_init()
        for name in ("jtag1_drck", "tck_pad_i", "tms_pad_i", "tdi_pad_i", "trstb_pad_i"):
            if hasattr(dut, name):
                getattr(dut, name).value = 0
        for name, _ in _AXI_MON_FIELDS:
            getattr(dut, name).value = 0
        dut.trigger_in.value = 0
        dut.ARESETN.value = 0
        cocotb.start_soon(Clock(dut.ACLK, 8, unit="ns").start())
        await self.idle(8)
        dut.ARESETN.value = 1
        await self.idle(12)
        if isinstance(self, _GowinDebugMultiBench):
            await self.scan(49)  # sets jtag_tap_gowin's hold and chain flags
            await self.idle(4)

    def _tdo(self) -> int:
        """TDO where the TAP primitive takes it (Efinix: the exported port),
        so a broken return path fails the test."""
        if isinstance(self, _GowinDebugMultiBench):
            pin = getattr(self.prim, f"tdo_er{self.chain_idx + 1}_i")
        elif hasattr(self.dut, "jtag1_tdo"):
            pin = self.dut.jtag1_tdo
        else:
            pin = next(getattr(self.prim, name) for name in ("UTDO", "TDO", "tdo")
                       if hasattr(self.prim, name))
        return int(pin.value)

    async def axi_stream(self, beats: list[dict[str, int]]) -> None:
        """Drive one beat per ACLK on every monitored input, then idle."""
        dut = self.dut
        for beat in beats:
            await RisingEdge(dut.ACLK)
            for name, value in beat.items():
                getattr(dut, name).value = value
        await RisingEdge(dut.ACLK)
        for name, _ in _AXI_MON_FIELDS:
            getattr(dut, name).value = 0


class _AxiMonDefaultBench(_AxiMonBench, _DebugMultiBench):
    pass


class _AxiMonEcp5Bench(_AxiMonBench, _Ecp5DebugMultiBench):
    pass


class _AxiMonGowinBench(_AxiMonBench, _GowinDebugMultiBench):
    pass


@cocotb.test()
async def fcapz_axi_mon_vendor(dut):
    """An fcapz_axi_mon_<vendor> wrapper through its vendor TAP: identity, a
    capture triggered on an AXI write address, read back through the register
    window and, except on register-only Gowin, the burst path."""
    target = os.environ.get("FCAPZ_COCOTB_TARGET", "")
    gowin = "_gowin" in target
    tb = (_AxiMonGowinBench if gowin else
          _AxiMonEcp5Bench if "_ecp5" in target else _AxiMonDefaultBench)(dut)
    await tb.start()

    assert await tb.read(0x0000) & 0xFFFF == 0x4C41
    assert await tb.read(0x000C) == _AXI_MON_SAMPLE_W
    amid = await tb.read(0x00E8)
    assert amid >> 16 == 0x414D, f"AXI_MON_ID {amid:#x}"
    assert (amid >> 8) & 0xFF == 1, f"AXI_MON_ID protocol {amid:#x}"

    # Every field of every beat random, except AWADDR, which steps so the
    # trigger matches only the third beat: the pretrigger samples are beats
    # too, and a dropped or crossed field changes the sample.
    pretrig, posttrig, base, step = 2, 5, 0x4000_0000, 4
    rng = random.Random(0xA11)
    beats = [{name: rng.getrandbits(width) for name, width in _AXI_MON_FIELDS}
             for _ in range(pretrig + posttrig + 8)]
    for i, beat in enumerate(beats):
        beat["AWADDR"] = base + i * step
    await tb.write(0x0014, pretrig)
    await tb.write(0x0018, posttrig)
    await tb.write(0x0020, 1)
    await tb.write(0x0024, base + pretrig * step)  # awaddr is sample[31:0]
    await tb.write(0x0028, 0xFFFF_FFFF)
    await tb.write(0x0004, 1)
    for _ in range(100):
        if int(dut.armed_out.value):
            break
        await tb.idle(4)
    assert int(dut.armed_out.value), "arm never reached the AXI clock domain"

    await tb.axi_stream(beats)
    status = 0
    for _ in range(200):
        status = await tb.read(0x0008)
        if status & 0x4:
            break
        await tb.idle(8)
    assert status & 0x4, f"capture never reached DONE (STATUS {status:#x})"
    capture_len = pretrig + posttrig + 1
    assert await tb.read(0x001C) == capture_len

    samples = []
    for i in range(capture_len):
        sample = 0
        for w in range(_AXI_MON_WORDS):
            sample |= await tb.read(0x0100 + 4 * (i * _AXI_MON_WORDS + w)) << (32 * w)
        samples.append(sample)
    for i, sample in enumerate(samples):
        expected = _axi_mon_flatten(beats[i])
        assert sample == expected, f"sample {i}: {sample:#x}, expected {expected:#x}"

    if gowin:
        return
    # One 152-bit sample per 256-bit burst scan, after the priming scan.
    await tb.write(0x002C, 0)
    await tb.idle(160)
    await tb.scan(_DEBUG_MULTI_BURST_W)
    for i in range(capture_len):
        packet = await tb.scan(_DEBUG_MULTI_BURST_W)
        expected = _axi_mon_flatten(beats[i])
        assert packet & width_mask(_AXI_MON_SAMPLE_W) == expected, f"burst sample {i}"


@cocotb.test()
async def fcapz_async_fifo_equiv(dut):
    wr_clk_task = cocotb.start_soon(Clock(dut.wr_clk, 10, unit="ns").start())
    cocotb.start_soon(Clock(dut.rd_clk, 14, unit="ns").start())
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
    # The XPM branch holds its reset a few wr_clk cycles after rst falls,
    # reading full and empty until then; compare once it is out of reset.
    await RisingEdge(dut.wr_clk)
    while int(dut.wr_rst_busy_b.value) or int(dut.rd_rst_busy_b.value):
        await RisingEdge(dut.wr_clk)
    await check_stable()
    ASYNC_FIFO_FUNCTIONAL_COVERAGE.hit("reset_empty_flags_match")

    for i in range(16):
        await RisingEdge(dut.wr_clk)
        dut.wr_data.value = i
        dut.wr_en.value = 1
        await check_stable()
    await RisingEdge(dut.wr_clk)
    dut.wr_en.value = 0
    for _ in range(4):
        await check_stable()
    ASYNC_FIFO_FUNCTIONAL_COVERAGE.hit("write_fill_flags_match")

    for _ in range(16):
        await RisingEdge(dut.rd_clk)
        dut.rd_en.value = 1
        await check_stable()
    await RisingEdge(dut.rd_clk)
    dut.rd_en.value = 0
    ASYNC_FIFO_FUNCTIONAL_COVERAGE.hit("read_drain_data_match")

    for _ in range(4):
        await RisingEdge(dut.wr_clk)
    for i in range(8):
        await RisingEdge(dut.wr_clk)
        dut.wr_data.value = (0xA0 + i) & 0xFF
        dut.wr_en.value = 1
        await RisingEdge(dut.rd_clk)
        dut.rd_en.value = 1
        await check_stable()
    ASYNC_FIFO_FUNCTIONAL_COVERAGE.hit("mixed_read_write_match")
    await RisingEdge(dut.wr_clk)
    dut.wr_en.value = 0
    await RisingEdge(dut.rd_clk)
    dut.rd_en.value = 0
    for _ in range(8):
        await check_stable()
    ASYNC_FIFO_FUNCTIONAL_COVERAGE.hit("post_idle_stable")

    # Reset with wr_clk stopped (TCK between scans) and a word queued: the
    # XPM branch must stop reads at once and never hand out that word.
    await RisingEdge(dut.wr_clk)
    dut.wr_data.value = 0x5A
    dut.wr_en.value = 1
    await RisingEdge(dut.wr_clk)
    dut.wr_en.value = 0
    while int(dut.rd_empty_b.value):
        await RisingEdge(dut.rd_clk)
    await FallingEdge(dut.wr_clk)
    wr_clk_task.cancel()
    dut.wr_clk.value = 0
    await RisingEdge(dut.rd_clk)
    dut.rst.value = 1
    await RisingEdge(dut.rd_clk)
    dut.rst.value = 0
    dut.rd_en.value = 1
    for _ in range(10):
        await RisingEdge(dut.rd_clk)
        await ReadOnly()
        assert int(dut.rd_empty_b.value) and int(dut.rd_rst_busy_b.value), (
            "XPM read side open after reset with wr_clk stopped")
    await FallingEdge(dut.rd_clk)
    cocotb.start_soon(Clock(dut.wr_clk, 10, unit="ns").start())
    while int(dut.wr_rst_busy_b.value) or int(dut.rd_rst_busy_b.value):
        await RisingEdge(dut.rd_clk)
    for _ in range(4):
        await RisingEdge(dut.rd_clk)
    assert int(dut.rd_empty_b.value), "stale word survived the reset"
    dut.rd_en.value = 0
    ASYNC_FIFO_FUNCTIONAL_COVERAGE.hit("stopped_wr_clk_reset_blocks_reads")


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
        self._value = self._coerce_value(0)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value) -> None:
        self._value = self._coerce_value(value)

    def _coerce_value(self, value):
        if BinaryValue is None:
            if LogicArray is None:
                return int(value) & ((1 << self._width) - 1)
            if isinstance(value, LogicArray):
                return value
            if hasattr(value, "get_binstr"):
                return LogicArray(str(value.get_binstr()))
            if hasattr(value, "binstr"):
                return LogicArray(str(value.binstr))
            try:
                return LogicArray.from_unsigned(int(value), self._width)
            except TypeError:
                return LogicArray("".join(str(bit) for bit in value))
        if isinstance(value, BinaryValue):
            return value
        if hasattr(value, "get_binstr"):
            return BinaryValue(value.get_binstr(), n_bits=self._width, bigEndian=False)
        if hasattr(value, "binstr"):
            return BinaryValue(value.binstr, n_bits=self._width, bigEndian=False)
        try:
            return BinaryValue(value, n_bits=self._width, bigEndian=False)
        except TypeError:
            return BinaryValue("".join(str(bit) for bit in value),
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
    """Records AW/W/AR handshakes and checks the master side of AXI4: once a
    VALID is up it stays up, with its payload unchanged, until READY."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cycle = 0
        self.aw: list[dict[str, int]] = []
        self.w: list[dict[str, int]] = []
        self.ar: list[dict[str, int]] = []
        self.violations: list[str] = []
        self._pending: dict[str, dict[str, int] | None] = {"aw": None, "w": None, "ar": None}

    def _payload(self, channel: str) -> dict[str, int]:
        d = self.dut
        if channel == "aw":
            return {"addr": _signal_int(d.m_axi_awaddr), "len": _signal_int(d.m_axi_awlen),
                    "size": _signal_int(d.m_axi_awsize), "burst": _signal_int(d.m_axi_awburst)}
        if channel == "w":
            return {"data": _signal_int(d.m_axi_wdata), "strb": _signal_int(d.m_axi_wstrb),
                    "last": _signal_int(d.m_axi_wlast)}
        return {"addr": _signal_int(d.m_axi_araddr), "len": _signal_int(d.m_axi_arlen),
                "size": _signal_int(d.m_axi_arsize), "burst": _signal_int(d.m_axi_arburst)}

    def _check(self, channel: str, valid, ready, log: list[dict[str, int]]) -> None:
        is_valid = _signal_is_one(valid)
        payload = self._payload(channel) if is_valid else None
        held = self._pending[channel]
        if held is not None:
            if not is_valid:
                self.violations.append(f"cycle {self.cycle}: {channel}valid dropped before ready")
            elif payload != held:
                self.violations.append(
                    f"cycle {self.cycle}: {channel} payload changed while stalled: "
                    f"{held} -> {payload}")
        if is_valid and _signal_is_one(ready):
            log.append({**payload, "cycle": self.cycle})
            self._pending[channel] = None
        else:
            self._pending[channel] = payload

    async def monitor(self) -> None:
        d = self.dut
        while True:
            await RisingEdge(d.axi_clk)
            self.cycle += 1
            if _signal_is_one(d.axi_rst):
                self._pending = {"aw": None, "w": None, "ar": None}
                continue
            self._check("aw", d.m_axi_awvalid, d.m_axi_awready, self.aw)
            self._check("w", d.m_axi_wvalid, d.m_axi_wready, self.w)
            self._check("ar", d.m_axi_arvalid, d.m_axi_arready, self.ar)


async def init_ejtagaxi(dut) -> tuple[AxiRam, AxiTrace]:
    axi_ram = AxiRam(axi_no_id_bus(dut), dut.axi_clk, dut.axi_rst, size=4096)
    axi_trace = AxiTrace(dut)
    cocotb.start_soon(axi_trace.monitor())
    cocotb.start_soon(Clock(dut.tck, 100, unit="ns").start())
    cocotb.start_soon(Clock(dut.axi_clk, 30, unit="ns").start())
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
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("single_write")
    await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ, 0x0000_0000, 0, 0), "S2 read")
    assert axi_rdata(out) == 0xDEAD_BEEF
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("single_read")
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
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("partial_strobe_write")
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
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("incrementing_write")

    await dr_scan_72(dut, axi_cmd(CMD_SET_ADDR, 0x0000_0010, 0, 0))
    await axi_cdc_wait(dut)
    for i in range(4):
        out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ_INC, 0, 0, 0), f"S6 read_inc {i}")
        assert axi_rdata(out) == 0xA000_0000 + i
        await axi_cdc_wait(dut)
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("incrementing_read")

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
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("burst_write")

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
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("burst_read")

    out = await issue_and_wait_valid(dut, axi_cmd(CMD_CONFIG, 0x0000_0000, 0, 0), "S9 version")
    assert axi_rdata(out) == _VERSION_HI | 0x4A58
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("config_version")
    await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_CONFIG, 0x0000_0004, 0, 0), "S9 version alias")
    assert axi_rdata(out) == _VERSION_HI | 0x4A58
    await axi_cdc_wait(dut)

    out = await issue_and_wait_valid(dut, axi_cmd(CMD_CONFIG, 0x0000_002C, 0, 0), "S9 features")
    assert axi_rdata(out) == 0x020F_2020
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("config_features")
    await axi_cdc_wait(dut)

    await dr_scan_72(dut, axi_cmd(CMD_RESET, 0, 0, 0))
    await axi_cdc_wait(dut)
    out = await drain_until_idle(dut)
    assert not (axi_status(out) & 0x4)
    assert not (axi_status(out) & 0x2)
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("soft_reset")
    assert_axi_protocol_trace(axi_trace)
    assert not axi_trace.violations, axi_trace.violations
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("axi_protocol_trace")


@cocotb.test()
async def fcapz_ejtagaxi_burst_fill(dut):
    """A burst read longer than the burst FIFO fills it, stalls, and resumes.

    The host drains nothing until the FIFO is full, so the R channel is held
    off by back-pressure.  Every beat the slave hands over must be written
    exactly once: a registered rready used to accept a beat in the cycle the
    FIFO filled and drop it.
    """
    axi_ram, _ = await init_ejtagaxi(dut)
    beats = 24  # more than FIFO_DEPTH (16)
    base = 0x0000_0100
    values = [0xC000_0000 + i for i in range(beats)]
    for i, value in enumerate(values):
        axi_ram.write_dword(base + 4 * i, value)

    accepted: list[int] = []

    async def watch_r() -> None:
        while True:
            await RisingEdge(dut.axi_clk)
            if _signal_is_one(dut.m_axi_rvalid) and _signal_is_one(dut.m_axi_rready):
                accepted.append(_signal_int(dut.m_axi_rdata))

    cocotb.start_soon(watch_r())

    setup = (0b01 << 12) | (0b010 << 8) | (beats - 1)
    await dr_scan_72(dut, axi_cmd(CMD_BURST_SETUP, base, setup, 0))
    await axi_cdc_wait(dut)
    await dr_scan_72(dut, axi_cmd(CMD_BURST_RSTART, 0, 0, 0))
    await axi_cdc_wait(dut, 60)
    assert 0 < len(accepted) < beats, (
        f"R channel did not stall on a full FIFO ({len(accepted)} beats accepted)")

    await dr_scan_72(dut, axi_cmd(CMD_BURST_RDATA, 0, 0, 0))  # priming scan
    await axi_cdc_wait(dut)
    got = []
    for _ in range(beats):
        out = await dr_scan_72(dut, axi_cmd(CMD_BURST_RDATA, 0, 0, 0))
        assert not (axi_status(out) & 0x4), "error_sticky set during burst read"
        got.append(axi_rdata(out))
        await axi_cdc_wait(dut)

    def first_mismatch(seen: list[int]) -> str:
        for index, (have, want) in enumerate(zip(seen, values)):
            if have != want:
                return f"beat {index}: 0x{have:08X} != 0x{want:08X}"
        return f"{len(seen)} beats, expected {len(values)}"

    assert got == values, f"bridge returned wrong data, {first_mismatch(got)}"
    assert accepted == values, f"R-channel handshakes wrong, {first_mismatch(accepted)}"

    out = await drain_until_idle(dut)
    assert not (axi_status(out) & 0x4)


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
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("reset_post_read")

    await dr_scan_72(dut, axi_cmd(CMD_SET_ADDR, 0x0000_0004, 0, 0))
    await axi_cdc_wait(dut)
    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_READ_INC, 0, 0, 0), "first post-reset read_inc")
    assert axi_resp(out) == 0
    assert axi_rdata(out) == 0x89AB_CDEF
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("reset_read_increment")
    assert int(dut.debug_tck.value) == 0
    assert int(dut.debug_tck_edge.value) == 0
    assert int(dut.debug_axi.value) == 0
    assert int(dut.debug_axi_edge.value) == 0
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("reset_debug_outputs_idle")
    assert len(axi_trace.aw) == 2
    assert len(axi_trace.w) == 2
    assert len(axi_trace.ar) == 2
    _assert_axi_addr(axi_trace.aw[0], 0x0000_0000)
    _assert_axi_addr(axi_trace.aw[1], 0x0000_0004)
    _assert_axi_write_beats(axi_trace.w, [0x1234_5678, 0x89AB_CDEF], burst=False)
    _assert_axi_addr(axi_trace.ar[0], 0x0000_0000)
    _assert_axi_addr(axi_trace.ar[1], 0x0000_0004)
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("reset_axi_trace")


async def wait_resp(dut, label: str) -> int:
    """Poll NOPs until prev_valid; unlike issue_and_wait_valid, an error is fine."""
    last = 0
    for _ in range(64):
        last = await dr_scan_72(dut, axi_cmd(CMD_NOP, 0, 0, 0))
        if axi_status(last) & 0x1:
            return last
        await axi_cdc_wait(dut)
    raise AssertionError(
        f"{label}: timed out waiting for prev_valid; last status=0x{axi_status(last):x}")


async def clear_after_error(dut) -> None:
    await dr_scan_72(dut, axi_cmd(CMD_RESET, 0, 0, 0))
    await axi_cdc_wait(dut)
    out = await drain_until_idle(dut)
    assert not (axi_status(out) & 0x4)


@cocotb.test()
async def fcapz_ejtagaxi_r_drain(dut):
    """A read the slave answers too late (R timeout) or that RESET cuts off is
    drained: its late beats must not become the data of the next read, and a
    slave that never answers must not wedge the bridge.

    Runs with TIMEOUT=64; the slave holds its R channel back past it.
    """
    axi_ram, axi_trace = await init_ejtagaxi(dut)
    r_channel = axi_ram.read_if.r_channel
    for i in range(8):
        axi_ram.write_dword(0x100 + 4 * i, 0x1111_0000 + i)
        axi_ram.write_dword(0x200 + 4 * i, 0x2222_0000 + i)

    async def read_ok(addr: int, want: int, label: str) -> None:
        out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ, addr, 0, 0), label)
        assert axi_resp(out) == 0, f"{label}: resp {axi_resp(out)}"
        assert axi_rdata(out) == want, (
            f"{label}: read 0x{axi_rdata(out):08X}, expected 0x{want:08X}")

    # Single read past the R timeout.
    r_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_READ, 0x100, 0, 0))
    out = await wait_resp(dut, "timed-out read")
    assert axi_resp(out) == 2, "R timeout must answer SLVERR"
    r_channel.pause = False
    await axi_cdc_wait(dut, 20)
    await clear_after_error(dut)
    await read_ok(0x200, 0x2222_0000, "read after R timeout")
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("r_timeout_drain")

    # Burst read past the R timeout: every late beat is drained.
    r_channel.pause = True
    setup = (0b01 << 12) | (0b010 << 8) | 3
    await dr_scan_72(dut, axi_cmd(CMD_BURST_SETUP, 0x100, setup, 0))
    await axi_cdc_wait(dut)
    await dr_scan_72(dut, axi_cmd(CMD_BURST_RSTART, 0, 0, 0))
    await axi_cdc_wait(dut, 60)
    r_channel.pause = False
    await axi_cdc_wait(dut, 20)
    await clear_after_error(dut)
    await read_ok(0x204, 0x2222_0001, "read after burst R timeout")
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("burst_timeout_drain")

    # RESET while the slave owes the R beat.
    r_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_READ, 0x108, 0, 0))
    await axi_cdc_wait(dut, 4)
    await dr_scan_72(dut, axi_cmd(CMD_RESET, 0, 0, 0))
    await axi_cdc_wait(dut)
    r_channel.pause = False
    await axi_cdc_wait(dut, 20)
    out = await drain_until_idle(dut)
    assert not (axi_status(out) & 0x4)
    await read_ok(0x208, 0x2222_0002, "read after RESET with a read in flight")
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("reset_inflight_drain")

    # A slave that keeps the beat: after TIMEOUT cycles commands run again,
    # but a read answers SLVERR without an AR while the beat is owed, and a
    # write goes through.  Once the beat arrives it is drained and reads work.
    r_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_READ, 0x10C, 0, 0))
    out = await wait_resp(dut, "read to a silent slave")
    assert axi_resp(out) == 2
    await clear_after_error(dut)
    ars = len(axi_trace.ar)
    await dr_scan_72(dut, axi_cmd(CMD_READ, 0x20C, 0, 0))
    out = await wait_resp(dut, "read while a beat is owed")
    assert axi_resp(out) == 2
    assert len(axi_trace.ar) == ars, "a read issued an AR while a beat was owed"
    await clear_after_error(dut)
    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x300, 0x3333_0000, 0xF), "write while a beat is owed")
    assert axi_resp(out) == 0
    assert axi_mem_read32(axi_ram, 0x300) == 0x3333_0000
    r_channel.pause = False
    await axi_cdc_wait(dut, 20)
    await read_ok(0x210, 0x2222_0004, "read once the owed beat is drained")
    assert not axi_trace.violations, axi_trace.violations
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("drain_bounded")


CFG_AXI_STATUS = 0x0030
AXI_ST_WE_BUSY = 0x01
AXI_ST_WE_DETACHED = 0x02
AXI_ST_AR_ORPHAN = 0x04
AXI_ST_R_DRAIN = 0x08
AXI_ST_COLLECTING = 0x10
AXI_ST_OWED = 0x20  # registered OR of WE_BUSY, AR_ORPHAN, R_DRAIN


def burst_cfg(length: int, size: int = 2, burst: int = 1) -> int:
    return ((burst & 0x3) << 12) | ((size & 0x7) << 8) | (length & 0xFF)


async def axi_bus_status(dut) -> int:
    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_CONFIG, CFG_AXI_STATUS, 0, 0), "AXI_STATUS")
    return axi_rdata(out)


async def axi_wait_bus_idle(dut, label: str) -> None:
    for _ in range(16):
        if await axi_bus_status(dut) == 0:
            return
        await axi_cdc_wait(dut, 10)
    raise AssertionError(f"{label}: AXI_STATUS never went idle")


async def collect_responses(dut, label: str) -> list[int]:
    """NOP-poll until the bridge goes idle; return every response's resp code."""
    resps: list[int] = []
    for _ in range(96):
        out = await dr_scan_72(dut, axi_cmd(CMD_NOP, 0, 0, 0))
        status = axi_status(out)
        if status & 0x1:
            resps.append(axi_resp(out))
        elif not (status & 0x2):
            return resps
        await axi_cdc_wait(dut, 4)
    raise AssertionError(f"{label}: bridge never went idle ({resps})")


async def scan_seq(dut, cmds: list[int], label: str) -> list[int]:
    """Run *cmds* back to back, then NOP-poll until idle, like the host's
    batched transfers; return the resp code of every response seen."""
    resps: list[int] = []
    for i, cmd in enumerate(cmds):
        out = await dr_scan_72(dut, cmd)
        if i and axi_status(out) & 0x1:
            resps.append(axi_resp(out))
    return resps + await collect_responses(dut, label)


@cocotb.test()
async def fcapz_ejtagaxi_w_safety(dut):
    """Bus safety of the write path and of held ARs (BUG-280/289/296/299).

    Runs with TIMEOUT=64.  The slave stalls single channels; the bridge must
    never drop a VALID before READY (AxiTrace checks every cycle), must finish
    every write it started with exactly the beats it announced, must take every
    B itself, and must never put a burst on the bus before all of its beats are
    in, or one that breaks an AXI burst rule.
    """
    axi_ram, trace = await init_ejtagaxi(dut)
    wif = axi_ram.write_if
    rif = axi_ram.read_if
    mem = axi_ram.read_dword

    out = await issue_and_wait_valid(dut, axi_cmd(CMD_CONFIG, 0x002C, 0, 0), "FEATURES")
    assert axi_rdata(out) & (1 << 25), "FEATURES[25] (bus-safe writes) not set"
    assert await axi_bus_status(dut) == 0

    # ---- A burst answers one response per beat (Verilog and VHDL alike).
    resps = await scan_seq(dut, [axi_cmd(CMD_BURST_SETUP, 0x080, burst_cfg(3), 0)] + [
        axi_cmd(CMD_BURST_WDATA, 0, 0x0800_0000 + i, 0xF) for i in range(4)], "burst acks")
    assert resps == [0, 0, 0, 0], f"burst responses {resps}"
    assert [mem(0x080 + 4 * i) for i in range(4)] == [0x0800_0000 + i for i in range(4)]
    assert trace.aw[-1]["len"] == 3 and len(trace.w) == 4
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("burst_beat_acks")

    # ---- AW stalled past TIMEOUT: SLVERR, but AWVALID stays up and the write
    # completes once the slave takes it; its B produces no second response.
    aw0, w0 = len(trace.aw), len(trace.w)
    wif.aw_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_WRITE, 0x100, 0x1111_1111, 0xF))
    out = await wait_resp(dut, "write with AW stalled")
    assert axi_resp(out) == 2
    await clear_after_error(dut)
    st = await axi_bus_status(dut)
    assert st & (AXI_ST_WE_BUSY | AXI_ST_WE_DETACHED | AXI_ST_OWED) == (
        AXI_ST_WE_BUSY | AXI_ST_WE_DETACHED | AXI_ST_OWED), hex(st)
    assert len(trace.aw) == aw0
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("aw_stall_detached")

    # A write while the engine still owes the slave: SLVERR, no AW of its own.
    await dr_scan_72(dut, axi_cmd(CMD_WRITE, 0x104, 0x2222_2222, 0xF))
    out = await wait_resp(dut, "write while the engine is busy")
    assert axi_resp(out) == 2
    await clear_after_error(dut)
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("write_quarantine")

    wif.aw_channel.pause = False
    await axi_wait_bus_idle(dut, "AW stall")
    assert mem(0x100) == 0x1111_1111
    assert mem(0x104) == 0, "a quarantined write reached the bus"
    assert len(trace.aw) == aw0 + 1 and len(trace.w) == w0 + 1
    assert trace.w[-1]["cycle"] <= trace.aw[-1]["cycle"], "expected W before AW here"
    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x108, 0x3333_3333, 0xF), "write after the stall")
    assert axi_resp(out) == 0 and mem(0x108) == 0x3333_3333
    assert await collect_responses(dut, "no stray B response") == []

    # ---- B held back past TIMEOUT: absorbed by the engine, never handed to a
    # later write.
    wif.b_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_WRITE, 0x200, 0x4444_4444, 0xF))
    out = await wait_resp(dut, "write with B stalled")
    assert axi_resp(out) == 2
    await clear_after_error(dut)
    assert await axi_bus_status(dut) & AXI_ST_WE_DETACHED
    aw1 = len(trace.aw)
    await dr_scan_72(dut, axi_cmd(CMD_WRITE, 0x204, 0x5555_5555, 0xF))
    out = await wait_resp(dut, "write while B is owed")
    assert axi_resp(out) == 2
    await clear_after_error(dut)
    assert len(trace.aw) == aw1
    wif.b_channel.pause = False
    await axi_wait_bus_idle(dut, "late B")
    out = await issue_and_wait_valid(
        dut, axi_cmd(CMD_WRITE, 0x208, 0x6666_6666, 0xF), "write after late B")
    assert axi_resp(out) == 0
    assert await collect_responses(dut, "late B gave no response") == []
    assert mem(0x200) == 0x4444_4444 and mem(0x204) == 0 and mem(0x208) == 0x6666_6666
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("late_b_absorbed")

    # ---- Incomplete bursts never reach the bus.
    aw2 = len(trace.aw)
    await dr_scan_72(dut, axi_cmd(CMD_BURST_SETUP, 0x300, burst_cfg(3), 0))
    await dr_scan_72(dut, axi_cmd(CMD_BURST_WDATA, 0, 0x7000_0000, 0xF))
    await dr_scan_72(dut, axi_cmd(CMD_BURST_WDATA, 0, 0x7000_0001, 0xF))
    await axi_cdc_wait(dut, 10)
    # Collecting alone owes the slave nothing.
    assert await axi_bus_status(dut) & (AXI_ST_COLLECTING | AXI_ST_OWED) == AXI_ST_COLLECTING
    await clear_after_error(dut)  # CMD_RESET mid-collection
    assert await axi_bus_status(dut) == 0
    assert len(trace.aw) == aw2 and mem(0x300) == 0 and mem(0x304) == 0
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("collect_reset_discard")

    resps = await scan_seq(dut, [
        axi_cmd(CMD_BURST_SETUP, 0x340, burst_cfg(3), 0),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7100_0000, 0xF),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7100_0001, 0xF),
        axi_cmd(CMD_WRITE, 0x380, 0x7200_0000, 0xF)], "write ends a collection")
    assert resps == [0, 0, 0], resps
    assert len(trace.aw) == aw2 + 1 and trace.aw[-1]["addr"] == 0x380
    assert mem(0x340) == 0 and mem(0x380) == 0x7200_0000
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("collect_cmd_discard")

    resps = await scan_seq(dut, [
        axi_cmd(CMD_BURST_SETUP, 0x400, burst_cfg(3), 0),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7300_0000, 0xF),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7300_0001, 0xF),
        axi_cmd(CMD_BURST_SETUP, 0x440, burst_cfg(1), 0),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7400_0000, 0xF),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7400_0001, 0xF)], "SETUP restarts a collection")
    assert resps == [0, 0, 0, 0], resps
    assert len(trace.aw) == aw2 + 2
    assert trace.aw[-1]["addr"] == 0x440 and trace.aw[-1]["len"] == 1
    assert mem(0x400) == 0 and mem(0x440) == 0x7400_0000 and mem(0x444) == 0x7400_0001
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("collect_setup_restart")

    # ---- W stalled mid-burst, then CMD_RESET: the burst still completes with
    # exactly its four beats, WLAST on the fourth, and the original data.
    w2 = len(trace.w)
    values = [0x7500_0000 + i for i in range(4)]
    wif.w_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_BURST_SETUP, 0x500, burst_cfg(3), 0))
    for v in values:
        await dr_scan_72(dut, axi_cmd(CMD_BURST_WDATA, 0, v, 0xF))
    await axi_cdc_wait(dut, 6)
    await clear_after_error(dut)
    assert await axi_bus_status(dut) & AXI_ST_WE_DETACHED
    wif.w_channel.pause = False
    await axi_wait_bus_idle(dut, "W stall + RESET")
    beats = trace.w[w2:]
    assert [b["data"] for b in beats] == values, beats
    assert [b["last"] for b in beats] == [0, 0, 0, 1]
    assert [mem(0x500 + 4 * i) for i in range(4)] == values
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("w_stall_reset_completes")

    # ---- Single-beat burst whose W is taken before its AW.
    wif.aw_channel.pause = True

    async def release_aw_after_w() -> None:
        w_now = len(trace.w)
        while len(trace.w) == w_now:
            await RisingEdge(dut.axi_clk)
        for _ in range(4):
            await RisingEdge(dut.axi_clk)
        wif.aw_channel.pause = False

    release = cocotb.start_soon(release_aw_after_w())
    resps = await scan_seq(dut, [
        axi_cmd(CMD_BURST_SETUP, 0x600, burst_cfg(0), 0),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7600_0000, 0xF)], "W-before-AW single-beat burst")
    await release
    assert resps == [0], resps
    assert trace.w[-1]["cycle"] < trace.aw[-1]["cycle"]
    assert mem(0x600) == 0x7600_0000
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("w_before_aw")

    # ---- Bursts that break an AXI rule or exceed the buffer: SLVERR for every
    # beat, nothing on the bus.
    refused = [
        (0xFFC, burst_cfg(1)),            # INCR crossing 4 KB
        (0x700, burst_cfg(0, size=3)),    # 8-byte beats on a 4-byte bus
        (0x700, burst_cfg(0, burst=3)),   # reserved burst type
        (0x700, burst_cfg(16, burst=0)),  # FIXED longer than 16 beats
        (0x700, burst_cfg(2, burst=2)),   # WRAP of 3 beats
        (0x702, burst_cfg(1, burst=2)),   # WRAP from an unaligned address
        (0x700, burst_cfg(16)),           # 17 beats > FIFO_DEPTH (16)
    ]
    for addr, cfg in refused:
        aw_n, ar_n = len(trace.aw), len(trace.ar)
        beats_n = (cfg & 0xFF) + 1
        resps = await scan_seq(dut, [axi_cmd(CMD_BURST_SETUP, addr, cfg, 0)] + [
            axi_cmd(CMD_BURST_WDATA, 0, 0xBAD0_0000 + i, 0xF) for i in range(beats_n)],
            f"refused burst 0x{addr:X}/0x{cfg:X}")
        assert resps == [2] * beats_n, (hex(addr), hex(cfg), resps)
        await clear_after_error(dut)
        assert len(trace.aw) == aw_n, f"refused burst 0x{addr:X}/0x{cfg:X} reached the bus"
        if cfg == burst_cfg(16):
            continue  # a 17-beat INCR read is legal (reads may exceed the FIFO)
        resps = await scan_seq(dut, [axi_cmd(CMD_BURST_SETUP, addr, cfg, 0),
                                     axi_cmd(CMD_BURST_RSTART, 0, 0, 0)],
                               f"refused read 0x{addr:X}/0x{cfg:X}")
        assert resps == [2], (hex(addr), hex(cfg), resps)
        assert len(trace.ar) == ar_n, f"refused read 0x{addr:X}/0x{cfg:X} reached the bus"
        await clear_after_error(dut)
    assert mem(0x700) == 0 and mem(0x704) == 0
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("burst_refused")

    # Legal edge cases go through.
    assert await scan_seq(dut, [
        axi_cmd(CMD_BURST_SETUP, 0xFF8, burst_cfg(1), 0),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7700_0000, 0xF),
        axi_cmd(CMD_BURST_WDATA, 0, 0x7700_0001, 0xF)], "INCR to the 4 KB edge") == [0, 0]
    assert mem(0xFF8) == 0x7700_0000 and mem(0xFFC) == 0x7700_0001
    assert await scan_seq(dut, [axi_cmd(CMD_BURST_SETUP, 0x780, burst_cfg(3, burst=0), 0)] + [
        axi_cmd(CMD_BURST_WDATA, 0, 0x7800_0000 + i, 0xF) for i in range(4)],
        "FIXED burst") == [0, 0, 0, 0]
    assert mem(0x780) == 0x7800_0003 and mem(0x784) == 0
    assert await scan_seq(dut, [axi_cmd(CMD_BURST_SETUP, 0x7C8, burst_cfg(3, burst=2), 0)] + [
        axi_cmd(CMD_BURST_WDATA, 0, 0x7900_0000 + i, 0xF) for i in range(4)],
        "WRAP burst") == [0, 0, 0, 0]
    assert [mem(0x7C0 + 4 * i) for i in range(4)] == [
        0x7900_0002, 0x7900_0003, 0x7900_0000, 0x7900_0001]
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("burst_legal_edges")

    # ---- AR stalled past TIMEOUT: SLVERR, ARVALID stays up, reads are refused
    # without an AR until the slave takes it, then its beat is drained.
    axi_ram.write_dword(0x900, 0x9000_0000)
    axi_ram.write_dword(0x904, 0x9000_0001)
    ar0 = len(trace.ar)
    rif.ar_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_READ, 0x900, 0, 0))
    out = await wait_resp(dut, "read with AR stalled")
    assert axi_resp(out) == 2
    await clear_after_error(dut)
    assert await axi_bus_status(dut) & (AXI_ST_AR_ORPHAN | AXI_ST_OWED) == (
        AXI_ST_AR_ORPHAN | AXI_ST_OWED)
    await dr_scan_72(dut, axi_cmd(CMD_READ, 0x904, 0, 0))
    out = await wait_resp(dut, "read while the AR is held")
    assert axi_resp(out) == 2
    await clear_after_error(dut)
    assert len(trace.ar) == ar0
    rif.ar_channel.pause = False
    await axi_wait_bus_idle(dut, "AR stall")
    assert len(trace.ar) == ar0 + 1 and trace.ar[-1]["addr"] == 0x900
    out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ, 0x904, 0, 0), "read after AR stall")
    assert axi_rdata(out) == 0x9000_0001
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("ar_stall_held")

    # CMD_RESET while a burst AR waits: the AR stays up, then is drained.
    rif.ar_channel.pause = True
    await dr_scan_72(dut, axi_cmd(CMD_BURST_SETUP, 0x900, burst_cfg(1), 0))
    await dr_scan_72(dut, axi_cmd(CMD_BURST_RSTART, 0, 0, 0))
    await axi_cdc_wait(dut, 8)
    await clear_after_error(dut)
    assert await axi_bus_status(dut) & (AXI_ST_AR_ORPHAN | AXI_ST_OWED) == (
        AXI_ST_AR_ORPHAN | AXI_ST_OWED)
    rif.ar_channel.pause = False
    await axi_wait_bus_idle(dut, "AR held over RESET")
    out = await issue_and_wait_valid(dut, axi_cmd(CMD_READ, 0x900, 0, 0), "read after held AR")
    assert axi_rdata(out) == 0x9000_0000
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("ar_reset_held")

    assert not trace.violations, trace.violations
    EJTAG_AXI_FUNCTIONAL_COVERAGE.hit("axi_valid_stable")


@cocotb.test()
async def fcapz_ejtagaxi_ar_reset_race(dut):
    """CMD_RESET recognized in the very cycle the slave takes a pending AR.

    Runs with TIMEOUT=1024, so the AR is still the FSM's own (not yet held
    after a timeout) when the RESET arrives.  The slave's ARREADY is released
    at every AXI cycle offset around the RESET; in each case the bridge must
    issue that AR exactly once (a VALID left up after its handshake is a
    second read nobody drains) and the next read must return its own data.
    """
    axi_ram, trace = await init_ejtagaxi(dut)
    rif = axi_ram.read_if
    axi_ram.write_dword(0xA00, 0xA000_0000)
    axi_ram.write_dword(0xA04, 0xA000_0004)

    async def release_ar(k: int) -> None:
        await RisingEdge(dut.update)
        for _ in range(k):
            await RisingEdge(dut.axi_clk)
        rif.ar_channel.pause = False

    for d, k in [(d, k) for d in range(3) for k in range(12)]:
        ar0 = len(trace.ar)
        rif.ar_channel.pause = True
        await dr_scan_72(dut, axi_cmd(CMD_READ, 0xA00, 0, 0))
        # d shifts the TCK/axi_clk phase of the RESET by a third of a cycle.
        await axi_cdc_wait(dut, 2 + d)
        rel = cocotb.start_soon(release_ar(k))
        await dr_scan_72(dut, axi_cmd(CMD_RESET, 0, 0, 0))
        await rel
        await axi_cdc_wait(dut)
        await drain_until_idle(dut)
        await axi_wait_bus_idle(dut, f"AR/RESET race d={d} k={k}")
        await axi_cdc_wait(dut, 20)
        assert len(trace.ar) == ar0 + 1, (
            f"d={d} k={k}: {len(trace.ar) - ar0} AR handshakes for one READ")
        out = await issue_and_wait_valid(
            dut, axi_cmd(CMD_READ, 0xA04, 0, 0), f"read after race d={d} k={k}")
        assert axi_rdata(out) == 0xA000_0004, f"d={d} k={k}: {axi_rdata(out):#x}"

    assert not trace.violations, trace.violations


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
    await Timer(UART_BIT_PERIOD_NS, unit="ns")
    for i in range(8):
        dut.uart_rxd.value = (data >> i) & 1
        await Timer(UART_BIT_PERIOD_NS, unit="ns")
    dut.uart_rxd.value = 1 if stop_high else 0
    await Timer(UART_BIT_PERIOD_NS, unit="ns")
    dut.uart_rxd.value = 1


async def uart_recv_byte_timeout(dut, timeout_ns: int) -> tuple[bool, int]:
    waited = 0
    while int(dut.uart_txd.value) == 1 and waited < timeout_ns:
        await Timer(100, unit="ns")
        waited += 100
    if int(dut.uart_txd.value) != 0:
        return False, 0
    await Timer(UART_BIT_PERIOD_NS // 2, unit="ns")
    data = 0
    for i in range(8):
        await Timer(UART_BIT_PERIOD_NS, unit="ns")
        data |= int(dut.uart_txd.value) << i
    await Timer(UART_BIT_PERIOD_NS, unit="ns")
    return True, data


async def uart_recv_byte(dut) -> int:
    while int(dut.uart_txd.value) == 1:
        await dut.uart_txd.value_change
    await Timer(UART_BIT_PERIOD_NS // 2, unit="ns")
    data = 0
    for i in range(8):
        await Timer(UART_BIT_PERIOD_NS, unit="ns")
        data |= int(dut.uart_txd.value) << i
    await Timer(UART_BIT_PERIOD_NS, unit="ns")
    return data


async def init_ejtaguart(dut) -> None:
    cocotb.start_soon(Clock(dut.tck, 100, unit="ns").start())
    cocotb.start_soon(Clock(dut.uart_clk, 100, unit="ns").start())
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
    assert uart_rx_byte(out) == _MINOR
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0x00))
    assert uart_rx_byte(out) == _MAJOR
    await uart_cdc_wait(dut)
    await dr_scan_32(dut, uart_cmd(UART_CMD_CONFIG, 0x04))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0x00))
    assert uart_rx_byte(out) == 0x55
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("config_registers")
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, 0xA5))
    await uart_cdc_wait(dut)
    valid, tx_byte = await uart_recv_byte_timeout(dut, UART_BIT_PERIOD_NS * 12)
    assert valid
    assert tx_byte == 0xA5
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("tx_push_serializes_byte")
    for _ in range(20):
        await RisingEdge(dut.uart_clk)

    await uart_send_byte(dut, 0x3C)
    await uart_cdc_wait(dut, 40)
    await dr_scan_32(dut, uart_cmd(UART_CMD_RX_POP, 0))
    await uart_cdc_wait(dut)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_rx_byte(out) == 0x3C
    assert uart_rx_valid(out)
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("rx_pop_reads_byte")
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
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("txrx_exchange")
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
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("rx_ready_without_pop")
    await uart_cdc_wait(dut)

    for i in range(UART_TX_FIFO_DEPTH + 8):
        await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, i))
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_tx_full(out)
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("tx_full_status")
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
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("rx_overflow_status")
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 30)
    await uart_send_byte(dut, 0, stop_high=False)
    await uart_cdc_wait(dut, 50)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert uart_frame_err(out)
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("frame_error_status")
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 30)
    out = await dr_scan_32(dut, uart_cmd(UART_CMD_NOP, 0))
    assert not uart_rx_overflow(out)
    assert not uart_frame_err(out)
    assert not uart_tx_full(out)
    assert not uart_rx_ready(out)
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("reset_clears_status")
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
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("loopback_order")
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_TX_PUSH, 0xFF))
    while int(dut.uart_txd.value) == 1:
        await dut.uart_txd.value_change
    await Timer(UART_BIT_PERIOD_NS * 10, unit="ns")
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
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("tx_free_accounting")
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
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("rx_fifo_order")
    await uart_cdc_wait(dut)

    await dr_scan_32(dut, uart_cmd(UART_CMD_RESET, 0))
    await uart_cdc_wait(dut, 20)
    for _ in range(UART_BAUD_DIV * 12 * 4):
        await RisingEdge(dut.uart_clk)

    bridge_on = True

    async def bridge_txd_to_rxd() -> None:
        dut.uart_rxd.value = int(dut.uart_txd.value)
        while bridge_on:
            await dut.uart_txd.value_change
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
    EJTAG_UART_FUNCTIONAL_COVERAGE.hit("bridge_loopback_stress")
    bridge_on = False
    bridge_task.cancel()
    dut.uart_rxd.value = 1
