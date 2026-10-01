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
ADDR_WIDE_SEL = 0x00E4
ADDR_WIDE_DATA = 0x00F0
ADDR_DATA_BASE = 0x0100


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)), 0)


SAMPLE_W = env_int("ELA_PARAM_SAMPLE_W", 8)
DEPTH = env_int("ELA_PARAM_DEPTH", 16)
INPUT_PIPE = env_int("ELA_PARAM_INPUT_PIPE", 0)
TRIG_STAGES = env_int("ELA_PARAM_TRIG_STAGES", 1)
DUAL_COMPARE = env_int("ELA_PARAM_DUAL_COMPARE", 1)
DECIM_EN = env_int("ELA_PARAM_DECIM_EN", 0)
STOR_QUAL = env_int("ELA_PARAM_STOR_QUAL", 0)
EXT_TRIG_EN = env_int("ELA_PARAM_EXT_TRIG_EN", 0)
# An external trigger_in pulse marks the probe sample driven alongside it: the
# core matches trigger_in to the probe path, and builds one input stage when
# INPUT_PIPE = 0 so that path is as long as the 2-FF synchronizer.
EXT_TRIG_MARK_OFFSET = 0
# Probe-path register stages the core actually builds (see PROBE_PIPE in RTL).
PROBE_PIPE = INPUT_PIPE if INPUT_PIPE or not EXT_TRIG_EN else 1
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
            "oversize_length": 0,
            "oversize_length_sum": 0,
            "posttrigger_at_depth": 0,
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
            "wide_trigger": 0,
            "sequencer": 0,
            "user1_disabled": 0,
            "rel_compare": 0,
            "storage_qualifier": 0,
            "burst_start": 0,
            "burst_blocks_user1": 0,
            "rolling_prehistory": 0,
            "rolling_rearm_history": 0,
            "randomized_value_capture": 0,
            "trigger_alignment": 0,
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

    async def start(self, *, sample_period_ns: int = 10) -> None:
        cocotb.start_soon(Clock(self.dut.sample_clk, sample_period_ns, unit="ns").start())
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


async def setup(dut, *, sample_period_ns: int = 10) -> ElaDriver:
    ela = ElaDriver(dut)
    await ela.start(sample_period_ns=sample_period_ns)
    return ela


async def free_running_counter(dut, *, start: int = 0) -> None:
    """Drive probe_in with a counter that advances every sample clock, so any
    captured window must count up by exactly one per stored sample."""
    value = start
    while True:
        dut.probe_in.value = value & 0xFF
        await RisingEdge(dut.sample_clk)
        value += 1


def counter_steps(window: list[int]) -> list[int]:
    return [(window[i] - window[i - 1]) & 0xFF for i in range(1, len(window))]


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
async def burst_active_blocks_user1_data_window(dut):
    ela = await setup(dut)
    await ela.configure_value_capture(pre=0, post=1, value=9)
    await ela.arm()
    await ela.drive_counter(16)
    assert await ela.wait_done() & 0x4

    normal = await ela.read(ADDR_DATA_BASE)
    assert (normal & 0xFF) == 9

    ela.dut.burst_rd_active.value = 1
    ela.dut.burst_rd_addr.value = 0
    blocked = await ela.read(ADDR_DATA_BASE)
    assert blocked == 0

    ela.dut.burst_rd_active.value = 0
    unblocked = await ela.read(ADDR_DATA_BASE)
    assert (unblocked & 0xFF) == 9
    FUNCTIONAL_COVERAGE.hit("burst_blocks_user1")


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
async def oversize_length_is_reported_not_truncated(dut):
    """A length of DEPTH must raise overflow, not wrap around.

    The host rejects pre+post+1 > depth, so this is only reachable by a JTAG
    master writing the register directly -- which is exactly what the overflow
    flag is for.  DEPTH is the first value that needs more bits than a sample
    pointer, so a core that narrows the length to pointer width sees 0 here,
    computes a small capture_len and reports no overflow at all.

    Scoped deliberately to DEPTH rather than "DEPTH or more": a value at or
    above 2**LEN_W exceeds the length field in *both* cores and wraps in both,
    so that is agreed behaviour rather than a defect.
    """
    ela = await setup(dut)
    await ela.reset_core()
    await ela.write(ADDR_PRETRIG, DEPTH)
    await ela.write(ADDR_POSTTRIG, 0)
    assert await ela.read(ADDR_PRETRIG) == DEPTH, "register readback must keep the full write"
    await ela.arm()
    # overflow latches in the arm block from pretrig_len_sync2, so poll rather
    # than assume the CDC has settled by any particular sample -- the sibling
    # overflow_and_reset test polls for the same reason.
    status = 0
    for _ in range(120):
        await ela.wait_sample(1)
        status = await ela.read(ADDR_STATUS)
        if status & 0x8:
            break
    assert status & 0x8, (
        f"pretrigger={DEPTH} with depth={DEPTH} must set overflow, got 0x{status:08x}"
    )
    FUNCTIONAL_COVERAGE.hit("oversize_length")


@cocotb.test()
async def oversize_length_sum_still_reports_overflow(dut):
    """pre=DEPTH, post=DEPTH-1 overflows the *sum*, not just one field.

    pre+post+1 is 2*DEPTH here, which needs one bit more than a length field
    holds. A core that computes the overflow comparison at length width wraps
    that sum to 0 and clears overflow -- reporting the request as fine. The
    sibling test above uses post=0 and cannot catch this.
    """
    ela = await setup(dut)
    await ela.reset_core()
    await ela.write(ADDR_PRETRIG, DEPTH)
    await ela.write(ADDR_POSTTRIG, DEPTH - 1)
    await ela.arm()
    status = 0
    for _ in range(120):
        await ela.wait_sample(1)
        status = await ela.read(ADDR_STATUS)
        if status & 0x8:
            break
    assert status & 0x8, (
        f"pre={DEPTH} post={DEPTH - 1} (sum {2 * DEPTH}) must set overflow, "
        f"got 0x{status:08x}"
    )
    FUNCTIONAL_COVERAGE.hit("oversize_length_sum")


@cocotb.test()
async def posttrigger_at_depth_still_completes(dut):
    """A posttrigger of DEPTH must still terminate the capture.

    post_count is compared against posttrig_len, so it needs the same width as
    a length. One bit narrower and it wraps one short of DEPTH, so `done` never
    asserts and the capture hangs rather than completing (overflowed).
    """
    ela = await setup(dut)
    await ela.reset_core()
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, DEPTH)
    await ela.write(ADDR_TRIG_MODE, 1)
    await ela.write(ADDR_TRIG_VALUE, 0)
    await ela.write(ADDR_TRIG_MASK, 0)
    await ela.arm()
    await ela.drive_counter(4 * DEPTH + 16)
    status = 0
    for _ in range(4 * DEPTH + 120):
        await ela.wait_sample(1)
        status = await ela.read(ADDR_STATUS)
        if status & 0x4:
            break
    assert status & 0x4, (
        f"posttrigger={DEPTH} never completed, last status=0x{status:08x}"
    )
    FUNCTIONAL_COVERAGE.hit("posttrigger_at_depth")


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
    # Holdoff counts cycles at the comparator; the probe pipeline lets earlier
    # counter values reach it after the window, so pick one still inside.
    await ela.configure_value_capture(pre=0, post=2, value=3 - PROBE_PIPE)
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
async def wide_trigger_upper_bit(dut):
    """WIDE_TRIG: program comparator A above bit 31 through the WIDE window and
    prove the trigger fires on a high bit the 32-bit register path can't reach.

    Runs against both the Verilog and VHDL ELA (HDL parity for WIDE_TRIG)."""
    ela = await setup(dut)
    caps = await ela.read(ADDR_COMPARE_CAPS)
    assert caps & (1 << 18), f"WIDE_TRIG not advertised: caps=0x{caps:08x}"

    bit = 35                      # word 1, offset 3 — unreachable via the 32-bit path
    word, off = bit // 32, bit % 32
    assert bit < SAMPLE_W and word < WORDS_PER_SAMPLE
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 0)
    await ela.write(ADDR_TRIG_MODE, 1)
    await ela.write(ADDR_TRIG_VALUE, 0)          # low 32 bits: value 0 …
    await ela.write(ADDR_TRIG_MASK, 0)           # … masked out (don't care)
    await ela.write(ADDR_WIDE_SEL, word << 4)    # word 1, value slot
    await ela.write(ADDR_WIDE_DATA, 1 << off)
    await ela.write(ADDR_WIDE_SEL, (word << 4) | 1)  # word 1, mask slot
    await ela.write(ADDR_WIDE_DATA, 1 << off)
    assert await ela.read(ADDR_WIDE_SEL) == ((word << 4) | 1)

    # Control: every low bit set but the trigger bit clear -> must not fire.
    await ela.arm()
    ela.dut.probe_in.value = (1 << 32) - 1
    await ela.wait_sample(12)
    status = await ela.read(ADDR_STATUS)
    assert not (status & 0x4), f"false trigger with bit {bit} clear: 0x{status:08x}"

    # Assert the high bit -> must fire (still armed from above).
    ela.dut.probe_in.value = 1 << bit
    assert await ela.wait_done() & 0x4
    FUNCTIONAL_COVERAGE.hit("wide_trigger")


@cocotb.test()
async def config_minimal(dut):
    ela = await setup(dut)
    assert await ela.read(ADDR_FEATURES) == 0x0001_0101
    assert await ela.read(ADDR_COMPARE_CAPS) == 0x000A_01C3
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
    assert await ela.read(ADDR_COMPARE_CAPS) == 0x000A_01FF
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
    assert await ela.read(ADDR_COMPARE_CAPS) == 0x000B_01FF
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
    # The pulse spans probe values 27..29; the pre-trigger window has only
    # filled by 29, the last of them, so that is the marked sample.
    assert first[8] & 0xFF == 29
    assert first[9] & 0xFF == 30
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
    # Writes were frozen for the whole readout of the first capture, so the
    # rolling history has a hole in it.  The core must re-earn pretrig_len
    # fresh samples before a trigger can commit, which makes the second
    # window one contiguous run holding nothing from before the re-arm.
    second = await ela.read_samples(11)
    window = [s & 0xFF for s in second]
    # The probe is only advanced by the loop below, so it sits at 86 for the
    # few sample clocks the JTAG arm write takes: a held value is faithful
    # data, not a seam.  A splice shows up as a *gap* -- a step of neither 0
    # nor 1 -- so that is what to forbid.
    steps = [(window[i] - window[i - 1]) & 0xFF for i in range(1, len(window))]
    assert all(d in (0, 1) for d in steps), (
        f"second capture window is spliced: {window} (steps {steps})"
    )
    # drive_counter(6, start=80) leaves the probe at 86 when arm() is issued,
    # so the floor is 86: a floor of 80 would admit the pre-arm samples 80..85
    # this is meant to exclude, and the pre-fix window started at ~31.
    assert window[0] >= 86, (
        f"second capture window reaches back before the re-arm: {window} "
        f"(first capture ended at {first[9] & 0xFF})"
    )
    FUNCTIONAL_COVERAGE.hit("rolling_rearm_history")


# -- Verilog/VHDL parity regressions ------------------------------------------
# Each of these checks the captured window itself, not just completion: the
# divergences they cover all completed normally and returned the wrong data.


@cocotb.test()
async def segmented_windows_are_contiguous(dut):
    """Arming must restart segment 0 at address 0 even while idle prefill is
    storing; otherwise segment 0 mixes pre-arm samples into its window."""
    ela = await setup(dut)
    await ela.configure_value_capture(pre=2, post=1, value=0, mask=0)
    counter = cocotb.start_soon(free_running_counter(dut))
    await ela.wait_sample(30)
    await ela.arm()
    assert await ela.wait_done(300) & 0x4
    counter.cancel()
    for seg in range(4):
        await ela.write(ADDR_SEG_SEL, seg)
        window = [s & 0xFF for s in await ela.read_samples(4)]
        assert counter_steps(window) == [1, 1, 1], f"segment {seg} window {window}"
    FUNCTIONAL_COVERAGE.hit("segments")


@cocotb.test()
async def sequencer_final_stage_counts_to_target(dut):
    """A final stage with count target 2 triggers on its second hit."""
    ela = await setup(dut)
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 0)
    await ela.write(ADDR_SEQ_BASE + 0, (2 << 16) | 0x1000)  # final, target 2, EQ
    await ela.write(ADDR_SEQ_BASE + 4, 3)
    await ela.write(ADDR_SEQ_BASE + 8, 0x03)
    await ela.arm()
    await ela.drive_counter(32)
    assert await ela.wait_done() & 0x4
    # Hits at 3 and 7; the second one is the trigger sample.
    assert await ela.read(ADDR_DATA_BASE) & 0xFF == 7
    FUNCTIONAL_COVERAGE.hit("sequencer")


async def _final_stage_hits_after_holdoff(ela, target: int, hits: tuple[int, ...]) -> int | None:
    """Arm a final stage matching low nibble 3 behind an 8-cycle holdoff and put
    its hits at the given sample cycles after arm.  Every sample carries its
    cycle number in the high nibble; returns that of the trigger sample, or
    None if the capture never triggered."""
    dut = ela.dut
    await ela.reset_core()
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 0)
    await ela.write(ADDR_SEQ_BASE + 0, (target << 16) | 0x1000)  # final, EQ
    await ela.write(ADDR_SEQ_BASE + 4, 3)
    await ela.write(ADDR_SEQ_BASE + 8, 0x0F)
    await ela.write(ADDR_TRIG_HOLDOFF, 8)
    dut.probe_in.value = 0
    await ela.arm()
    for cycle in range(40):
        dut.probe_in.value = ((cycle & 0xF) << 4) | (3 if cycle in hits else 0)
        await RisingEdge(dut.sample_clk)
    dut.probe_in.value = 0
    if not await ela.read(ADDR_STATUS) & 0x4:
        return None
    return (await ela.read(ADDR_DATA_BASE) & 0xFF) >> 4


@cocotb.test()
async def sequencer_next_stage_ignores_previous_stage_match(dut):
    """Stage 0 matches 5 and advances to stage 1, which matches 7.  A second 5
    straight after the first is a stage-0 match only; it must not fire the
    final stage."""
    ela = await setup(dut)
    await ela.write(ADDR_PRETRIG, 0)
    await ela.write(ADDR_POSTTRIG, 0)
    await ela.write(ADDR_SEQ_BASE + 0, 1 << 10)  # EQ, next stage 1
    await ela.write(ADDR_SEQ_BASE + 4, 5)
    await ela.write(ADDR_SEQ_BASE + 8, 0xFF)
    await ela.write(ADDR_SEQ_BASE + 20, 0x1000)  # EQ, final
    await ela.write(ADDR_SEQ_BASE + 24, 7)
    await ela.write(ADDR_SEQ_BASE + 28, 0xFF)
    dut.probe_in.value = 0
    await ela.arm()
    for cycle in range(40):
        dut.probe_in.value = 5 if cycle in (10, 11) else 0
        await RisingEdge(dut.sample_clk)
    await ela.wait_sample(8)
    assert not await ela.read(ADDR_STATUS) & 0x6, "a stage-0 match fired stage 1"
    for cycle in range(8):
        dut.probe_in.value = 7 if cycle == 2 else 0
        await RisingEdge(dut.sample_clk)
    assert await ela.wait_done() & 0x4
    assert await ela.read(ADDR_DATA_BASE) & 0xFF == 7
    FUNCTIONAL_COVERAGE.hit("sequencer")


def _seq_reference(stages: list[dict], symbols: list[int]) -> int | None:
    """Cycle reference for the trigger sequencer on EQ predicates.

    Each sample is checked against the stage active when that sample is
    decided.  Returns the index of the sample that fires the final stage, or
    None.  Mirrors the RTL priority: a final stage's hit with its count
    reached triggers; a non-final one advances (count reset); any other stage
    hit only counts; a miss keeps the count.
    """
    state = 0
    counter = 0
    for i, sym in enumerate(symbols):
        st = stages[state]
        a = sym == st["va"]
        b = sym == st["vb"] if DUAL_COMPARE else False
        hit = (a, b, a and b, a or b)[st["combine"] if DUAL_COMPARE else 0]
        if not hit:
            continue
        reached = st["count"] == 0 or counter + 1 >= st["count"]
        if st["final"] and reached:
            return i
        if reached:
            state, counter = st["next"], 0
        else:
            counter += 1
    return None


@cocotb.test()
async def sequencer_matches_cycle_reference(dut):
    """Random sequencer programs against the cycle reference: adjacent-stage
    matches, identical adjacent predicates, backward jumps, self-loops, counts
    and A/B combine.  Symbols 1..3 sit in the low nibble (EQ, mask 0x0F); the
    high nibble carries the sample index so the stored trigger sample names
    the sample that fired."""
    ela = await setup(dut)
    rng = random.Random(0x5E9 + INPUT_PIPE * 31 + TRIG_STAGES)
    lead = 8 + INPUT_PIPE
    fired = 0
    for trial in range(30):
        stages = []
        for idx in range(TRIG_STAGES):
            stages.append({
                "va": rng.randint(1, 3),
                "vb": rng.randint(1, 3),
                "combine": rng.randint(0, 3),
                "next": rng.randrange(TRIG_STAGES),
                "final": rng.random() < (0.5 if idx else 0.15),
                "count": rng.choice((0, 1, 1, 2, 3)),
            })
        if not any(st["final"] for st in stages):
            stages[rng.randrange(TRIG_STAGES)]["final"] = True
        symbols = [rng.choice((0, 1, 2, 3)) for _ in range(24)]
        expected = _seq_reference(stages, symbols)

        await ela.reset_core()
        await ela.write(ADDR_PRETRIG, 0)
        await ela.write(ADDR_POSTTRIG, 0)
        for idx, st in enumerate(stages):
            cfg = ((st["combine"] << 8) | (st["next"] << 10)  # modes A/B = 0 (EQ)
                   | (int(st["final"]) << 12) | (st["count"] << 16))
            base = ADDR_SEQ_BASE + idx * 20
            await ela.write(base + 0, cfg)
            await ela.write(base + 4, st["va"])
            await ela.write(base + 8, 0x0F)
            await ela.write(base + 12, st["vb"])
            await ela.write(base + 16, 0x0F)
        dut.probe_in.value = 0
        await ela.arm()
        for _ in range(lead):
            await RisingEdge(dut.sample_clk)
        for i, sym in enumerate(symbols):
            dut.probe_in.value = ((i & 0xF) << 4) | sym
            await RisingEdge(dut.sample_clk)
        dut.probe_in.value = 0
        await ela.wait_sample(8 + INPUT_PIPE)
        status = await ela.read(ADDR_STATUS)
        program = (stages, symbols)
        if expected is None:
            assert not status & 0x6, f"trial {trial}: fired, reference did not: {program}"
            continue
        fired += 1
        assert status & 0x4, f"trial {trial}: reference fires at {expected}: {program}"
        got = await ela.read(ADDR_DATA_BASE) & 0xFF
        want = ((expected & 0xF) << 4) | symbols[expected]
        assert got == want, f"trial {trial}: stored 0x{got:02x}, want 0x{want:02x}: {program}"
    assert fired >= 8, f"only {fired} of 30 random programs fired"
    FUNCTIONAL_COVERAGE.hit("sequencer")


@cocotb.test()
async def sequencer_counts_first_hit_after_holdoff(dut):
    """A hit that can trigger a count-1 final stage is also counted by a
    count-2 one.  With INPUT_PIPE >= 1 the hit that first clears the holdoff
    was compared while the holdoff still ran; the count must follow the
    registered hit, as the trigger does."""
    ela = await setup(dut)
    # Find the first cycle after arm at which a single hit triggers.
    for first in range(24):
        anchor = await _final_stage_hits_after_holdoff(ela, 1, (first,))
        if anchor is not None:
            break
    else:
        raise AssertionError("no single hit triggered within 24 cycles of arm")
    assert first > 0, "the holdoff did not hold off the first hit"
    latency = (anchor - first) & 0xF
    # Count 2 with its first hit on that cycle: the second hit triggers.
    second = first + 5
    anchor = await _final_stage_hits_after_holdoff(ela, 2, (first, second))
    assert anchor is not None, f"hit at cycle {first} was not counted"
    assert anchor == (second + latency) & 0xF, (first, second, latency, anchor)
    FUNCTIONAL_COVERAGE.hit("sequencer")


@cocotb.test()
async def input_pipe_depth_sets_capture_latency(dut):
    """An external pulse marks the probe sample driven alongside it at every
    INPUT_PIPE depth, including 0."""
    ela = await setup(dut)
    await ela.write(ADDR_TRIG_EXT, 1)  # OR: the external pulse alone triggers
    await ela.configure_value_capture(pre=0, post=3, value=0xFF, mask=0xFF)
    dut.trigger_in.value = 0
    await ela.arm()
    pulse_at = 40
    for cycle in range(64):
        dut.probe_in.value = cycle
        dut.trigger_in.value = 1 if cycle == pulse_at else 0
        await RisingEdge(dut.sample_clk)
    dut.trigger_in.value = 0
    assert await ela.wait_done() & 0x4
    window = [s & 0xFF for s in await ela.read_samples(4)]
    dut._log.info("INPUT_PIPE=%d pulse at %d window %s", INPUT_PIPE, pulse_at, window)
    assert counter_steps(window) == [1, 1, 1], window
    assert window[0] == pulse_at + EXT_TRIG_MARK_OFFSET, window


@cocotb.test()
async def input_pipe_keeps_the_write_queued_at_arm(dut):
    """The input pipe is a delay, not a filter: the sample queued for the RAM
    on the arm edge must still be written, as it is with INPUT_PIPE=0, or the
    pre-trigger history keeps a stale word where it should have gone."""
    ela = await setup(dut)
    await ela.write(ADDR_PRETRIG, 10)
    await ela.write(ADDR_POSTTRIG, 2)
    await ela.write(ADDR_TRIG_MODE, 1)
    await ela.write(ADDR_TRIG_VALUE, 0xFF)
    await ela.write(ADDR_TRIG_MASK, 0xFF)
    await ela.write(ADDR_TRIG_EXT, 1)
    counter = cocotb.start_soon(free_running_counter(dut))
    # pretrig_len is latched on arm, so idle prefill only builds usable history
    # once an earlier arm has latched it: capture once, soft-reset, then let
    # the idle core refill the pre-trigger window from before the next arm.
    dut.trigger_in.value = 1
    await ela.arm()
    assert await ela.wait_done() & 0x4
    dut.trigger_in.value = 0
    await ela.reset_core()
    await ela.wait_sample(30)
    # Held across the arm so the trigger commits within a few samples of it,
    # which puts the arm edge inside the pre-trigger window.
    dut.trigger_in.value = 1
    await ela.arm()
    await ela.wait_sample(4)
    dut.trigger_in.value = 0
    assert await ela.wait_done() & 0x4
    counter.cancel()
    window = [s & 0xFF for s in await ela.read_samples(13)]
    assert counter_steps(window) == [1] * 12, f"window has a stale word: {window}"


async def _counter_window(ela, *, pre: int, post: int, value: int, cycles: int = 120) -> list[int]:
    """Capture a free-running 8-bit counter triggered on ``value``."""
    await ela.configure_value_capture(pre=pre, post=post, value=value)
    await ela.arm()
    await ela.drive_counter(cycles)
    assert await ela.wait_done() & 0x4
    return [s & 0xFF for s in await ela.read_samples(pre + post + 1)]


@cocotb.test()
async def trigger_marks_the_matched_sample(dut):
    """samples[pretrig] is the sample the trigger compare matched, at every
    INPUT_PIPE depth, with trigger delay, storage qualification, decimation
    and the external trigger in AND mode."""
    ela = await setup(dut)
    await ela.write(ADDR_DECIM, 0)

    window = await _counter_window(ela, pre=4, post=3, value=0x40)
    assert window[4] == 0x40 and counter_steps(window) == [1] * 7, window

    await ela.reset_core()
    await ela.write(ADDR_TRIG_DELAY, 3)
    window = await _counter_window(ela, pre=4, post=3, value=0x40)
    assert window[4] == 0x43 and counter_steps(window) == [1] * 7, window
    await ela.write(ADDR_TRIG_DELAY, 0)

    if STOR_QUAL:
        # Store odd samples only (NEQ against bit 0 clear).
        await ela.reset_core()
        await ela.write(ADDR_SQ_MODE, 1)
        await ela.write(ADDR_SQ_VALUE, 0)
        await ela.write(ADDR_SQ_MASK, 1)
        window = await _counter_window(ela, pre=3, post=3, value=0x41)
        assert window[3] == 0x41 and counter_steps(window) == [2] * 6, window
        await ela.write(ADDR_SQ_MODE, 0)
        FUNCTIONAL_COVERAGE.hit("storage_qualifier")

    if DECIM_EN:
        # The commit force-stores the anchor whatever phase the divider has.
        await ela.reset_core()
        await ela.write(ADDR_DECIM, 3)
        window = await _counter_window(ela, pre=2, post=2, value=0x41)
        assert window[2] == 0x41, window
        await ela.write(ADDR_DECIM, 0)
        FUNCTIONAL_COVERAGE.hit("decimation")

    if EXT_TRIG_EN:
        # AND: the compare matches 0x30..0x3F; the pulse picks one of them.
        await ela.reset_core()
        await ela.write(ADDR_TRIG_EXT, 2)
        await ela.configure_value_capture(pre=2, post=2, value=0x30, mask=0xF0)
        dut.trigger_in.value = 0
        await ela.arm()
        pulse_at = 0x36 - EXT_TRIG_MARK_OFFSET
        for cycle in range(96):
            dut.probe_in.value = cycle
            dut.trigger_in.value = 1 if cycle == pulse_at else 0
            await RisingEdge(dut.sample_clk)
        dut.trigger_in.value = 0
        assert await ela.wait_done() & 0x4
        window = [s & 0xFF for s in await ela.read_samples(5)]
        assert window[2] == 0x36 and counter_steps(window) == [1] * 4, window
        await ela.write(ADDR_TRIG_EXT, 0)
        FUNCTIONAL_COVERAGE.hit("external_trigger_and")

    FUNCTIONAL_COVERAGE.hit("trigger_alignment")


@cocotb.test()
async def config_written_after_arm_does_not_reach_armed_capture(dut):
    """Arm latches decimation and trigger mode from their synchronised copies.
    With the sample clock slower than JTAG, a write landing just after ARM is
    still unsynchronised when arm takes effect and must not apply to it."""
    ela = await setup(dut, sample_period_ns=30)
    await ela.write(ADDR_TRIG_EXT, 0)
    await ela.write(ADDR_DECIM, 0)
    await ela.configure_value_capture(pre=0, post=2, value=0, mask=0)
    dut.trigger_in.value = 0

    if DECIM_EN:
        await ela.wait_sample(4)
        await ela.write(ADDR_CTRL, 0x1)  # ARM
        await ela.write(ADDR_DECIM, 3)  # would store every 4th sample
        await ela.drive_counter(20)
        assert await ela.wait_done() & 0x4
        window = [s & 0xFF for s in await ela.read_samples(3)]
        assert counter_steps(window) == [1, 1], f"late decimation applied: {window}"
        await ela.write(ADDR_DECIM, 0)
        await ela.reset_core()

    await ela.wait_sample(4)
    await ela.write(ADDR_CTRL, 0x1)  # ARM
    await ela.write(ADDR_TRIG_EXT, 2)  # AND with trigger_in, which stays low
    await ela.drive_counter(20)
    assert await ela.wait_done() & 0x4, "late external-trigger mode applied"
    assert await ela.read(ADDR_TRIG_EXT) == 2
