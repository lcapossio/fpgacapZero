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
from cocotb.triggers import RisingEdge


ADDR_CTRL = 0x0004
ADDR_STATUS = 0x0008
ADDR_SAMPLE_W = 0x000C
ADDR_DEPTH = 0x0010
ADDR_PRETRIG = 0x0014
ADDR_POSTTRIG = 0x0018
ADDR_CAPTURE_LEN = 0x001C
ADDR_TRIG_MODE = 0x0020
ADDR_TRIG_VALUE = 0x0024
ADDR_TRIG_MASK = 0x0028
ADDR_BURST_PTR = 0x002C
ADDR_SQ_MODE = 0x0030
ADDR_SQ_VALUE = 0x0034
ADDR_SQ_MASK = 0x0038
ADDR_FEATURES = 0x003C
ADDR_SEQ_BASE = 0x0040
ADDR_CHAN_SEL = 0x00A0
ADDR_NUM_CHAN = 0x00A4
ADDR_PROBE_SEL = 0x00AC
ADDR_DECIM = 0x00B0
ADDR_TRIG_EXT = 0x00B4
ADDR_NUM_SEGMENTS = 0x00B8
ADDR_SEG_STATUS = 0x00BC
ADDR_SEG_SEL = 0x00C0
ADDR_TIMESTAMP_W = 0x00C4
ADDR_PROBE_MUX_W = 0x00D0
ADDR_TRIG_DELAY = 0x00D4
ADDR_STARTUP_ARM = 0x00D8
ADDR_TRIG_HOLDOFF = 0x00DC
ADDR_COMPARE_CAPS = 0x00E0
ADDR_DATA_BASE = 0x0100


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)), 0)


SAMPLE_W = env_int("ELA_PARAM_SAMPLE_W", 8)
DEPTH = env_int("ELA_PARAM_DEPTH", 16)
TIMESTAMP_W = env_int("ELA_PARAM_TIMESTAMP_W", 0)
WORDS_PER_SAMPLE = (SAMPLE_W + 31) // 32
TS_WORDS = (TIMESTAMP_W + 31) // 32 if TIMESTAMP_W > 0 else 0
ADDR_TS_DATA_BASE = ADDR_DATA_BASE + DEPTH * WORDS_PER_SAMPLE * 4


class ElaFunctionalCoverage:
    def __init__(self) -> None:
        self.bins = {
            "version": 0,
            "identity": 0,
            "features": 0,
            "register_roundtrip": 0,
            "reset": 0,
            "arm": 0,
            "value_trigger": 0,
            "edge_trigger": 0,
            "overflow": 0,
            "decim_zero": 0,
            "decim_every4": 0,
            "decimation": 0,
            "external_trigger_disabled": 0,
            "external_trigger_or": 0,
            "external_trigger_and": 0,
            "trigger_out": 0,
            "timestamp": 0,
            "timestamp_decim": 0,
            "timestamp_48": 0,
            "segments": 0,
            "segmented_single_pulse_stall": 0,
            "segmented_rearm_pulses": 0,
            "probe_mux": 0,
            "probe_mux_slice0": 0,
            "trigger_delay": 0,
            "trigger_delay_zero": 0,
            "startup_arm": 0,
            "trigger_holdoff": 0,
            "input_pipe": 0,
            "input_pipe_holdoff_ext": 0,
            "full_depth": 0,
            "early_pretrigger": 0,
            "wide_sample": 0,
            "sequencer": 0,
            "user1_disabled": 0,
            "rel_compare": 0,
            "storage_qualifier": 0,
            "burst_start": 0,
            "rolling_prehistory": 0,
            "rolling_rearm_history": 0,
            "randomized_value_capture": 0,
        }

    def hit(self, name: str) -> None:
        self.bins[name] += 1

    def write(self) -> None:
        path = os.environ.get("ELA_COCOTB_COVERAGE_JSON")
        if not path:
            return
        covered = sum(1 for count in self.bins.values() if count)
        payload = {
            "run": os.environ.get("ELA_COCOTB_RUN", "manual"),
            "covered_bins": covered,
            "total_bins": len(self.bins),
            "percent": round((covered / len(self.bins)) * 100.0, 2),
            "bins": self.bins,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, indent=2) + "\n")


FUNCTIONAL_COVERAGE = ElaFunctionalCoverage()
atexit.register(FUNCTIONAL_COVERAGE.write)


class ElaDriver:
    def __init__(self, dut) -> None:
        self.dut = dut

    async def start(self) -> None:
        cocotb.start_soon(Clock(self.dut.sample_clk, 10, unit="ns").start())
        cocotb.start_soon(Clock(self.dut.jtag_clk, 14, unit="ns").start())
        self.dut.sample_rst.value = 1
        self.dut.jtag_rst.value = 1
        self.dut.probe_in.value = 0
        self.dut.trigger_in.value = 0
        self.dut.jtag_wr_en.value = 0
        self.dut.jtag_rd_en.value = 0
        self.dut.jtag_addr.value = 0
        self.dut.jtag_wdata.value = 0
        if hasattr(self.dut, "burst_rd_active"):
            self.dut.burst_rd_active.value = 0
        self.dut.burst_rd_addr.value = 0
        await self.wait_sample(4)
        self.dut.sample_rst.value = 0
        await self.wait_jtag(2)
        self.dut.jtag_rst.value = 0
        await self.wait_jtag(4)

    async def wait_sample(self, cycles: int) -> None:
        for _ in range(cycles):
            await RisingEdge(self.dut.sample_clk)

    async def wait_jtag(self, cycles: int) -> None:
        for _ in range(cycles):
            await RisingEdge(self.dut.jtag_clk)

    async def write(self, addr: int, data: int) -> None:
        await RisingEdge(self.dut.jtag_clk)
        self.dut.jtag_addr.value = addr
        self.dut.jtag_wdata.value = data
        self.dut.jtag_wr_en.value = 1
        await RisingEdge(self.dut.jtag_clk)
        self.dut.jtag_wr_en.value = 0

    async def read(self, addr: int) -> int:
        await RisingEdge(self.dut.jtag_clk)
        self.dut.jtag_addr.value = addr
        self.dut.jtag_rd_en.value = 1
        await RisingEdge(self.dut.jtag_clk)
        self.dut.jtag_rd_en.value = 0
        await self.wait_jtag(8)
        return int(self.dut.jtag_rdata.value)

    async def reset_core(self) -> None:
        await self.write(ADDR_CTRL, 0x2)
        await self.wait_sample(10)

    async def arm(self) -> None:
        await self.write(ADDR_CTRL, 0x1)
        await self.wait_armed()
        FUNCTIONAL_COVERAGE.hit("arm")

    async def wait_armed(self, timeout_cycles: int = 80) -> None:
        for _ in range(timeout_cycles):
            await self.wait_sample(1)
            if int(self.dut.armed_out.value):
                return
        status = await self.read(ADDR_STATUS)
        raise AssertionError(f"arm did not reach sample domain, status=0x{status:08x}")

    async def wait_done(self, timeout_cycles: int = 200) -> int:
        status = 0
        for _ in range(timeout_cycles):
            await self.wait_sample(1)
            status = await self.read(ADDR_STATUS)
            if status & 0x4:
                return status
        raise AssertionError(f"capture did not complete, last status=0x{status:08x}")

    async def drive_counter(self, cycles: int, *, start: int = 0, mask: int | None = None) -> None:
        if mask is None:
            mask = (1 << min(SAMPLE_W, 32)) - 1
        value = start & mask
        self.dut.probe_in.value = value
        for _ in range(cycles):
            await RisingEdge(self.dut.sample_clk)
            value = (value + 1) & mask
            self.dut.probe_in.value = value

    async def configure_value_capture(
        self,
        *,
        pre: int,
        post: int,
        value: int,
        mask: int = 0xFF,
    ) -> None:
        await self.write(ADDR_PRETRIG, pre)
        await self.write(ADDR_POSTTRIG, post)
        await self.write(ADDR_TRIG_MODE, 1)
        await self.write(ADDR_TRIG_VALUE, value)
        await self.write(ADDR_TRIG_MASK, mask)

    async def read_samples(self, count: int, *, base: int = ADDR_DATA_BASE) -> list[int]:
        return [await self.read(base + i * 4) for i in range(count)]


async def setup(dut) -> ElaDriver:
    ela = ElaDriver(dut)
    await ela.start()
    return ela


@cocotb.test()
async def identity_registers(dut):
    ela = await setup(dut)
    version = await ela.read(0x0000)
    assert version & 0xFFFF == 0x4C41
    FUNCTIONAL_COVERAGE.hit("version")
    assert await ela.read(ADDR_SAMPLE_W) == SAMPLE_W
    assert await ela.read(ADDR_DEPTH) == DEPTH
    FUNCTIONAL_COVERAGE.hit("identity")


@cocotb.test()
async def features_registers(dut):
    ela = await setup(dut)
    features = await ela.read(ADDR_FEATURES)
    assert ((features >> 16) & 0xFF) == env_int("ELA_PARAM_NUM_SEGMENTS", 1)
    assert bool(features & 0x20) == bool(env_int("ELA_PARAM_DECIM_EN", 0))
    assert bool(features & 0x40) == bool(env_int("ELA_PARAM_EXT_TRIG_EN", 0))
    assert bool(features & 0x80) == bool(TIMESTAMP_W)
    FUNCTIONAL_COVERAGE.hit("features")


@cocotb.test()
async def register_roundtrip(dut):
    ela = await setup(dut)
    await ela.write(ADDR_TRIG_VALUE, 0xDEAD_BEEF)
    assert await ela.read(ADDR_TRIG_VALUE) == 0xDEAD_BEEF
    await ela.write(ADDR_TRIG_MASK, 0x5A5A_5A5A)
    assert await ela.read(ADDR_TRIG_MASK) == 0x5A5A_5A5A
    FUNCTIONAL_COVERAGE.hit("register_roundtrip")


@cocotb.test()
async def value_capture(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=2, post=3, value=8)
    await ela.arm()
    await ela.drive_counter(13)
    status = await ela.wait_done()
    assert status & 0x2 and status & 0x4 and not (status & 0x9)
    assert await ela.read(ADDR_CAPTURE_LEN) == 6
    assert (await ela.read(ADDR_DATA_BASE + 2 * 4)) & 0xFF == 8
    FUNCTIONAL_COVERAGE.hit("value_trigger")


@cocotb.test()
async def randomized_value_capture(dut):
    ela = await setup(dut)
    rng = random.Random((SAMPLE_W << 16) | DEPTH)
    sample_mask = (1 << min(SAMPLE_W, 32)) - 1

    for _ in range(6):
        await ela.reset_core()
        pre = rng.randint(0, min(4, DEPTH // 2))
        post = rng.randint(0, min(4, DEPTH - pre - 1))
        start = rng.randint(0, 9)
        trigger_offset = rng.randint(pre + 1, pre + 8)
        value = (start + trigger_offset) & sample_mask

        await ela.configure_value_capture(pre=pre, post=post, value=value, mask=sample_mask)
        await ela.arm()
        await ela.drive_counter(trigger_offset + post + 8, start=start, mask=sample_mask)
        assert await ela.wait_done(250) & 0x4

        capture_len = pre + post + 1
        assert await ela.read(ADDR_CAPTURE_LEN) == capture_len
        expected = [((value - pre + i) & sample_mask) for i in range(capture_len)]
        got = [(word & sample_mask) for word in await ela.read_samples(capture_len)]
        assert got == expected

    FUNCTIONAL_COVERAGE.hit("randomized_value_capture")


@cocotb.test()
async def edge_capture(dut):
    ela = await setup(dut)
    await ela.reset_core()
    await ela.write(ADDR_PRETRIG, 1)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_TRIG_MODE, 2)
    await ela.write(ADDR_TRIG_VALUE, 0)
    await ela.write(ADDR_TRIG_MASK, 0x01)
    await ela.arm()
    ela.dut.probe_in.value = 0
    await ela.wait_sample(3)
    ela.dut.probe_in.value = 1
    await ela.wait_sample(1)
    ela.dut.probe_in.value = 3
    await ela.wait_sample(1)
    assert await ela.wait_done() & 0x6 == 0x6
    FUNCTIONAL_COVERAGE.hit("edge_trigger")


@cocotb.test()
async def overflow_and_reset(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=8, post=8, value=5)
    await ela.arm()
    await ela.drive_counter(20)
    status = 0
    for _ in range(120):
        await ela.wait_sample(1)
        status = await ela.read(ADDR_STATUS)
        if status & 0x8:
            break
    assert status & 0x8, f"overflow bit did not set: 0x{status:08x}"
    FUNCTIONAL_COVERAGE.hit("overflow")
    await ela.reset_core()
    status = await ela.read(ADDR_STATUS)
    assert status == 0
    FUNCTIONAL_COVERAGE.hit("reset")


@cocotb.test()
async def decimation_and_external_trigger(dut):
    ela = await setup(dut)
    await ela.write(ADDR_DECIM, 3)
    assert await ela.read(ADDR_DECIM) == 3
    await ela.configure_value_capture(pre=0, post=3, value=8)
    await ela.arm()
    await ela.drive_counter(32)
    assert await ela.wait_done(250) & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 4
    FUNCTIONAL_COVERAGE.hit("decimation")

    await ela.reset_core()
    await ela.write(ADDR_TRIG_EXT, 1)
    await ela.configure_value_capture(pre=0, post=2, value=0xEE)
    await ela.arm()
    await ela.wait_sample(5)
    ela.dut.trigger_in.value = 1
    await ela.wait_sample(1)
    ela.dut.trigger_in.value = 0
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("external_trigger_or")

    await ela.reset_core()
    await ela.write(ADDR_TRIG_EXT, 2)
    await ela.configure_value_capture(pre=0, post=2, value=3)
    await ela.arm()
    await ela.drive_counter(8)
    assert not (await ela.read(ADDR_STATUS) & 0x2)
    ela.dut.probe_in.value = 3
    ela.dut.trigger_in.value = 1
    await ela.wait_sample(1)
    ela.dut.trigger_in.value = 0
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("external_trigger_and")


@cocotb.test()
async def decimation_zero_and_every4(dut):
    ela = await setup(dut)
    await ela.write(ADDR_DECIM, 0)
    await ela.configure_value_capture(pre=0, post=3, value=3)
    await ela.arm()
    await ela.drive_counter(16)
    assert await ela.wait_done() & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 4
    assert await ela.read(ADDR_DATA_BASE) & 0xFF == 3
    FUNCTIONAL_COVERAGE.hit("decim_zero")

    await ela.reset_core()
    await ela.write(ADDR_DECIM, 3)
    await ela.configure_value_capture(pre=0, post=2, value=8)
    await ela.arm()
    await ela.drive_counter(40)
    assert await ela.wait_done(250) & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 3
    FUNCTIONAL_COVERAGE.hit("decim_every4")


@cocotb.test()
async def external_trigger_disabled(dut):
    ela = await setup(dut)
    await ela.write(ADDR_TRIG_EXT, 0)
    assert await ela.read(ADDR_TRIG_EXT) == 0
    await ela.configure_value_capture(pre=0, post=2, value=0xEE)
    await ela.arm()
    ela.dut.trigger_in.value = 1
    await ela.wait_sample(12)
    ela.dut.trigger_in.value = 0
    status = await ela.read(ADDR_STATUS)
    assert not (status & 0x6)
    FUNCTIONAL_COVERAGE.hit("external_trigger_disabled")


@cocotb.test()
async def trigger_out_pulse(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=0, post=1, value=3)
    await ela.arm()
    seen = 0
    for i in range(20):
        await RisingEdge(ela.dut.sample_clk)
        ela.dut.probe_in.value = i
        if int(ela.dut.trigger_out.value):
            seen += 1
    assert seen == 1
    FUNCTIONAL_COVERAGE.hit("trigger_out")


@cocotb.test()
async def timestamp_capture(dut):
    ela = await setup(dut)
    assert await ela.read(ADDR_TIMESTAMP_W) == TIMESTAMP_W
    await ela.configure_value_capture(pre=1, post=2, value=8)
    await ela.arm()
    await ela.drive_counter(30)
    assert await ela.wait_done(250) & 0x4
    ts0 = await ela.read(ADDR_TS_DATA_BASE)
    ts1 = await ela.read(ADDR_TS_DATA_BASE + 4)
    assert ts1 > ts0
    FUNCTIONAL_COVERAGE.hit("timestamp")


@cocotb.test()
async def timestamp_decimation_gap(dut):
    ela = await setup(dut)
    await ela.write(ADDR_DECIM, 1)
    await ela.configure_value_capture(pre=1, post=2, value=7)
    await ela.arm()
    await ela.drive_counter(30)
    assert await ela.wait_done(250) & 0x4
    ts0 = await ela.read(ADDR_TS_DATA_BASE)
    ts1 = await ela.read(ADDR_TS_DATA_BASE + 4)
    assert ts1 - ts0 >= 2
    FUNCTIONAL_COVERAGE.hit("timestamp_decim")


@cocotb.test()
async def timestamp_48_upper_word(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=1, post=2, value=8)
    await ela.arm()
    await ela.drive_counter(30, start=0)
    assert await ela.wait_done(250) & 0x4
    low = await ela.read(ADDR_TS_DATA_BASE)
    high = await ela.read(ADDR_TS_DATA_BASE + 4)
    assert low != 0
    assert high == 0
    FUNCTIONAL_COVERAGE.hit("timestamp_48")


@cocotb.test()
async def segmented_capture(dut):
    ela = await setup(dut)
    assert await ela.read(ADDR_NUM_SEGMENTS) == 4
    await ela.write(ADDR_DECIM, 0)
    await ela.configure_value_capture(pre=0, post=3, value=3, mask=0x03)
    await ela.arm()
    await ela.drive_counter(80)
    status = await ela.wait_done(300)
    seg_status = await ela.read(ADDR_SEG_STATUS)
    assert status & 0x4
    assert seg_status & 0x8000_0000
    FUNCTIONAL_COVERAGE.hit("segments")


@cocotb.test()
async def probe_mux_slice_selection(dut):
    ela = await setup(dut)
    assert await ela.read(ADDR_PROBE_MUX_W) == 32
    await ela.write(ADDR_PROBE_SEL, 0)
    await ela.configure_value_capture(pre=0, post=2, value=0xAA)
    await ela.arm()
    ela.dut.probe_in.value = 0x33_22_11_00
    await ela.wait_sample(3)
    ela.dut.probe_in.value = 0x33_22_11_AA
    await ela.wait_sample(4)
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("probe_mux_slice0")

    await ela.reset_core()
    await ela.write(ADDR_PROBE_SEL, 2)
    assert await ela.read(ADDR_PROBE_SEL) == 2
    await ela.configure_value_capture(pre=0, post=2, value=0xFF)
    await ela.arm()
    ela.dut.probe_in.value = 0x33_00_11_AA
    await ela.wait_sample(3)
    ela.dut.probe_in.value = 0x33_FF_11_AA
    await ela.wait_sample(4)
    assert await ela.wait_done() & 0x4
    assert await ela.read(ADDR_DATA_BASE) & 0xFF == 0xFF
    await ela.write(ADDR_PROBE_SEL, 3)
    assert await ela.read(ADDR_PROBE_SEL) == 3
    FUNCTIONAL_COVERAGE.hit("probe_mux")


@cocotb.test()
async def trigger_delay_startup_and_holdoff(dut):
    ela = await setup(dut)
    await ela.write(ADDR_TRIG_DELAY, 0)
    await ela.configure_value_capture(pre=2, post=3, value=8)
    await ela.arm()
    await ela.drive_counter(20)
    assert await ela.wait_done() & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 6
    assert await ela.read(ADDR_DATA_BASE + 2 * 4) & 0xFF == 8
    FUNCTIONAL_COVERAGE.hit("trigger_delay_zero")

    await ela.reset_core()
    await ela.write(ADDR_TRIG_DELAY, 4)
    assert await ela.read(ADDR_TRIG_DELAY) == 4
    await ela.configure_value_capture(pre=2, post=3, value=8)
    await ela.arm()
    await ela.drive_counter(24)
    assert await ela.wait_done() & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 6
    assert await ela.read(ADDR_DATA_BASE + 2 * 4) & 0xFF == 12
    FUNCTIONAL_COVERAGE.hit("trigger_delay")

    await ela.write(ADDR_STARTUP_ARM, 1)
    await ela.reset_core()
    await ela.wait_sample(12)
    assert await ela.read(ADDR_STATUS) & 0x1
    ela.dut.probe_in.value = 0
    await ela.drive_counter(12)
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("startup_arm")

    await ela.write(ADDR_TRIG_HOLDOFF, 4)
    assert await ela.read(ADDR_TRIG_HOLDOFF) == 4
    await ela.reset_core()
    await ela.configure_value_capture(pre=0, post=2, value=3)
    await ela.arm()
    await ela.drive_counter(16)
    status = await ela.read(ADDR_STATUS)
    assert not (status & 0x6)
    await ela.reset_core()
    await ela.configure_value_capture(pre=0, post=2, value=6)
    await ela.arm()
    await ela.drive_counter(20)
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("trigger_holdoff")


@cocotb.test()
async def input_pipe_captures(dut):
    ela = await setup(dut)
    await ela.write(ADDR_DECIM, 0)
    await ela.configure_value_capture(pre=0, post=0, value=0)
    await ela.arm()
    await ela.drive_counter(1200)
    assert await ela.wait_done(400) & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 1
    assert await ela.read(ADDR_SEG_STATUS) & 0x8000_0000

    await ela.reset_core()
    await ela.configure_value_capture(pre=50, post=100, value=64)
    await ela.arm()
    await ela.drive_counter(1400)
    assert await ela.wait_done(500) & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 151
    FUNCTIONAL_COVERAGE.hit("input_pipe")


@cocotb.test()
async def input_pipe_holdoff_late_ext_pulse(dut):
    ela = await setup(dut)
    await ela.reset_core()
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_TRIG_MODE, 1)
    await ela.write(ADDR_TRIG_VALUE, 0)
    await ela.write(ADDR_TRIG_MASK, 0)
    await ela.write(ADDR_TRIG_EXT, 2)
    await ela.write(ADDR_TRIG_HOLDOFF, 4)
    await ela.wait_sample(12)
    await ela.arm()
    ela.dut.trigger_in.value = 0
    for cycle in range(320):
        ela.dut.probe_in.value = cycle & 0xFF
        in_pulse = any(start <= cycle <= start + 15 for start in (20, 90, 160, 230))
        ela.dut.trigger_in.value = 1 if in_pulse else 0
        await RisingEdge(ela.dut.sample_clk)
    ela.dut.trigger_in.value = 0
    assert await ela.wait_done() & 0x4
    assert await ela.read(ADDR_CAPTURE_LEN) == 3
    assert await ela.read(ADDR_SEG_STATUS) & 0x8000_0000
    FUNCTIONAL_COVERAGE.hit("input_pipe_holdoff_ext")


@cocotb.test()
async def full_depth_capture(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=2, post=5, value=4)
    await ela.arm()
    await ela.drive_counter(20)
    await ela.wait_sample(40)
    assert await ela.read(ADDR_STATUS) & 0x4
    data = await ela.read_samples(3)
    assert data[0] & 0xFF == 2
    assert data[2] & 0xFF == 4
    FUNCTIONAL_COVERAGE.hit("full_depth")


@cocotb.test()
async def decimated_trigger_anchor(dut):
    ela = await setup(dut)
    await ela.write(ADDR_DECIM, 3)
    await ela.configure_value_capture(pre=0, post=1, value=0x13)
    await ela.arm()
    await ela.drive_counter(40)
    assert await ela.wait_done(250) & 0x4
    assert await ela.read(ADDR_DATA_BASE) & 0xFF == 0x13
    FUNCTIONAL_COVERAGE.hit("decimation")


@cocotb.test()
async def early_pretrigger_waits_for_fill(dut):
    ela = await setup(dut)
    await ela.write(ADDR_DECIM, 3)
    await ela.configure_value_capture(pre=2, post=2, value=1)
    await ela.arm()
    await ela.drive_counter(290)
    await ela.wait_sample(40)
    assert await ela.read(ADDR_STATUS) & 0x4
    data = await ela.read_samples(3)
    assert data[0] & 0xFF == 251
    assert data[1] & 0xFF == 255
    assert data[2] & 0xFF == 1
    FUNCTIONAL_COVERAGE.hit("early_pretrigger")


@cocotb.test()
async def sequencer_count_target_one(dut):
    ela = await setup(dut)
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 0)
    await ela.write(ADDR_SEQ_BASE + 0, 0x0000_1000)
    await ela.write(ADDR_SEQ_BASE + 4, 7)
    await ela.write(ADDR_SEQ_BASE + 8, 0xFF)
    await ela.arm()
    await ela.drive_counter(16)
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("sequencer")


@cocotb.test()
async def wide_sample_readback(dut):
    ela = await setup(dut)
    sample = 0x1111_2222_3333
    await ela.configure_value_capture(pre=0, post=0, value=0x33, mask=0xFF)
    await ela.arm()
    ela.dut.probe_in.value = sample
    await ela.wait_sample(8)
    assert await ela.wait_done() & 0x4
    low = await ela.read(ADDR_DATA_BASE)
    high = await ela.read(ADDR_DATA_BASE + 4)
    assert low == 0x2222_3333
    assert high == 0x0000_1111
    FUNCTIONAL_COVERAGE.hit("wide_sample")


@cocotb.test()
async def config_minimal(dut):
    ela = await setup(dut)
    assert await ela.read(ADDR_FEATURES) == 0x0001_0101
    assert await ela.read(ADDR_COMPARE_CAPS) == 0x0002_01C3
    disabled_regs = (
        ADDR_SQ_MODE, ADDR_SQ_VALUE, ADDR_SQ_MASK,
        ADDR_CHAN_SEL, ADDR_DECIM, ADDR_TRIG_EXT,
        ADDR_SEG_SEL, ADDR_PROBE_SEL,
    )
    for addr in disabled_regs:
        await ela.write(addr, 0xFFFF)
        assert await ela.read(addr) == 0
    assert await ela.read(ADDR_SEG_STATUS) == 0x8000_0000
    FUNCTIONAL_COVERAGE.hit("identity")


@cocotb.test()
async def config_user1_disabled(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=1, post=2, value=5)
    await ela.arm()
    await ela.drive_counter(20)
    assert await ela.wait_done() & 0x4
    assert await ela.read(ADDR_DATA_BASE) == 0
    FUNCTIONAL_COVERAGE.hit("user1_disabled")


@cocotb.test()
async def config_rel_compare(dut):
    ela = await setup(dut)
    assert await ela.read(ADDR_COMPARE_CAPS) == 0x0002_01FF
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_SEQ_BASE + 0, 0x0000_1002)
    await ela.write(ADDR_SEQ_BASE + 4, 10)
    await ela.write(ADDR_SEQ_BASE + 8, 0xFF)
    await ela.arm()
    ela.dut.probe_in.value = 0x20
    for _ in range(40):
        await RisingEdge(ela.dut.sample_clk)
        if int(ela.dut.probe_in.value) > 0:
            ela.dut.probe_in.value = int(ela.dut.probe_in.value) - 1
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("rel_compare")


@cocotb.test()
async def config_combo_sq_segments(dut):
    ela = await setup(dut)
    features = await ela.read(ADDR_FEATURES)
    assert features & 0x10
    assert ((features >> 16) & 0xFF) == 4
    assert await ela.read(ADDR_COMPARE_CAPS) == 0x0003_01FF
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_SQ_MODE, 1)
    await ela.write(ADDR_SQ_VALUE, 0)
    await ela.write(ADDR_SQ_MASK, 1)
    await ela.write(ADDR_SEQ_BASE + 0, 0x0000_1306)
    await ela.write(ADDR_SEQ_BASE + 4, 0)
    await ela.write(ADDR_SEQ_BASE + 8, 0xFF)
    await ela.write(ADDR_SEQ_BASE + 12, 0)
    await ela.write(ADDR_SEQ_BASE + 16, 0xFF)
    await ela.arm()
    await ela.drive_counter(80)
    assert await ela.read(ADDR_CAPTURE_LEN) == 3
    assert await ela.read(ADDR_SEG_STATUS) & 0x1
    FUNCTIONAL_COVERAGE.hit("storage_qualifier")
    FUNCTIONAL_COVERAGE.hit("segments")


@cocotb.test()
async def burst_start_register(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=0, post=1, value=3)
    await ela.arm()
    await ela.drive_counter(12)
    assert await ela.wait_done() & 0x4
    before = int(ela.dut.burst_start.value)
    await ela.write(ADDR_BURST_PTR, 0)
    await ela.wait_jtag(1)
    after = int(ela.dut.burst_start.value)
    assert before != after
    FUNCTIONAL_COVERAGE.hit("burst_start")


@cocotb.test()
async def segmented_single_pulse_stalls(dut):
    ela = await setup(dut)
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_TRIG_MODE, 1)
    await ela.write(ADDR_TRIG_VALUE, 0)
    await ela.write(ADDR_TRIG_MASK, 0)
    await ela.write(ADDR_TRIG_EXT, 2)
    await ela.write(ADDR_TRIG_HOLDOFF, 4)
    await ela.wait_sample(12)
    await ela.arm()
    ela.dut.trigger_in.value = 0
    for cycle in range(220):
        ela.dut.probe_in.value = cycle & 0xFF
        ela.dut.trigger_in.value = 1 if 8 <= cycle <= 11 else 0
        await RisingEdge(ela.dut.sample_clk)
    ela.dut.trigger_in.value = 0
    await ela.wait_sample(40)
    status = await ela.read(ADDR_STATUS)
    seg_status = await ela.read(ADDR_SEG_STATUS)
    assert not (status & 0x4)
    assert not (seg_status & 0x8000_0000)
    assert seg_status & 0x3 == 1
    FUNCTIONAL_COVERAGE.hit("segmented_single_pulse_stall")


@cocotb.test()
async def segmented_rearm_pulses_complete(dut):
    ela = await setup(dut)
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_TRIG_MODE, 1)
    await ela.write(ADDR_TRIG_VALUE, 0)
    await ela.write(ADDR_TRIG_MASK, 0)
    await ela.write(ADDR_TRIG_EXT, 2)
    await ela.write(ADDR_TRIG_HOLDOFF, 4)
    await ela.wait_sample(12)
    await ela.arm()
    ela.dut.trigger_in.value = 0
    for cycle in range(320):
        ela.dut.probe_in.value = cycle & 0xFF
        in_pulse = any(start <= cycle <= start + 3 for start in (8, 80, 152, 224))
        ela.dut.trigger_in.value = 1 if in_pulse else 0
        await RisingEdge(ela.dut.sample_clk)
    ela.dut.trigger_in.value = 0
    assert await ela.wait_done() & 0x4
    seg_status = await ela.read(ADDR_SEG_STATUS)
    assert seg_status & 0x8000_0000
    FUNCTIONAL_COVERAGE.hit("segmented_rearm_pulses")


@cocotb.test()
async def rolling_prehistory_and_rearm(dut):
    ela = await setup(dut)
    await ela.write(ADDR_PRETRIG, 8)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_TRIG_MODE, 1)
    await ela.write(ADDR_TRIG_VALUE, 255)
    await ela.write(ADDR_TRIG_MASK, 0xFF)
    await ela.write(ADDR_TRIG_EXT, 1)
    ela.dut.probe_in.value = 0
    await ela.drive_counter(24)
    await ela.arm()
    ela.dut.trigger_in.value = 0
    for cycle in range(40):
        await RisingEdge(ela.dut.sample_clk)
        ela.dut.probe_in.value = (int(ela.dut.probe_in.value) + 1) & 0xFF
        ela.dut.trigger_in.value = 1 if 2 <= cycle <= 4 else 0
    await ela.wait_sample(40)
    assert await ela.read(ADDR_STATUS) & 0x4
    first = await ela.read_samples(10)
    assert first[0] & 0xFF == 24
    assert first[8] & 0xFF == 30
    assert first[9] & 0xFF == 31
    FUNCTIONAL_COVERAGE.hit("rolling_prehistory")

    ela.dut.probe_in.value = 80
    ela.dut.trigger_in.value = 0
    await ela.drive_counter(6, start=80)
    await ela.arm()
    for cycle in range(40):
        await RisingEdge(ela.dut.sample_clk)
        ela.dut.probe_in.value = (int(ela.dut.probe_in.value) + 1) & 0xFF
        ela.dut.trigger_in.value = 1 if 2 <= cycle <= 4 else 0
    await ela.wait_sample(40)
    assert await ela.read(ADDR_STATUS) & 0x4
    second = await ela.read_samples(10)
    assert (second[0] & 0xFF) == (first[9] & 0xFF)
    assert second[8] & 0xFF >= 88
    assert second[9] & 0xFF == ((second[8] & 0xFF) + 1) & 0xFF
    FUNCTIONAL_COVERAGE.hit("rolling_rearm_history")
