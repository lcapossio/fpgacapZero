# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""cocotb bench for fcapz_axi_mon (AXI monitor, P1).

Drives a single-cycle AXI4-Lite write on the passive tap and proves the monitor
(a) reports the AM identity + geometry, (b) triggers on the write address, and
(c) flattens the captured channels at the documented bit offsets. The DUT is the
portable core fcapz_axi_mon driven over its raw jtag register bus, mirroring
ela_core_test.py.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

# Set by the runner per target: 0 = P1 raw layout, 1 = P2 decode (events at LSB).
DECODE = int(os.environ.get("AXIMON_DECODE", "0"))

ADDR_VERSION = 0x0000
ADDR_CTRL = 0x0004
ADDR_STATUS = 0x0008
ADDR_SAMPLE_W = 0x000C
ADDR_PRETRIG = 0x0014
ADDR_POSTTRIG = 0x0018
ADDR_TRIG_MODE = 0x0020
ADDR_TRIG_VALUE = 0x0024
ADDR_TRIG_MASK = 0x0028
ADDR_AXI_MON_ID = 0x00E8
ADDR_AXI_GEOM = 0x00EC
ADDR_DATA_BASE = 0x0100

AXI_SIGNALS = [
    "AWADDR", "AWPROT", "AWVALID", "AWREADY",
    "WDATA", "WSTRB", "WVALID", "WREADY",
    "BRESP", "BVALID", "BREADY",
    "ARADDR", "ARPROT", "ARVALID", "ARREADY",
    "RDATA", "RRESP", "RVALID", "RREADY",
]


class MonDriver:
    def __init__(self, dut) -> None:
        self.dut = dut

    async def start(self) -> None:
        cocotb.start_soon(Clock(self.dut.ACLK, 10, unit="ns").start())
        cocotb.start_soon(Clock(self.dut.jtag_clk, 14, unit="ns").start())
        for sig in AXI_SIGNALS:
            getattr(self.dut, sig).value = 0
        self.dut.ARESETN.value = 0
        self.dut.jtag_rst.value = 1
        self.dut.trigger_in.value = 0
        self.dut.jtag_wr_en.value = 0
        self.dut.jtag_rd_en.value = 0
        self.dut.jtag_addr.value = 0
        self.dut.jtag_wdata.value = 0
        if hasattr(self.dut, "burst_rd_active"):
            self.dut.burst_rd_active.value = 0
        self.dut.burst_rd_addr.value = 0
        await self.wait_aclk(4)
        self.dut.ARESETN.value = 1
        await self.wait_jtag(2)
        self.dut.jtag_rst.value = 0
        await self.wait_jtag(4)

    async def wait_aclk(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(self.dut.ACLK)

    async def wait_jtag(self, n: int) -> None:
        for _ in range(n):
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

    async def arm(self) -> None:
        await self.write(ADDR_CTRL, 0x1)
        for _ in range(80):
            await self.wait_aclk(1)
            if int(self.dut.armed_out.value):
                return
        raise AssertionError("arm did not reach the sample domain")

    async def wait_done(self, timeout: int = 300) -> int:
        status = 0
        for _ in range(timeout):
            await self.wait_aclk(1)
            status = await self.read(ADDR_STATUS)
            if status & 0x4:
                return status
        raise AssertionError(f"capture did not complete, status=0x{status:08x}")

    async def axi_write(self, addr: int, data: int) -> None:
        """One-cycle AW+W handshake then B; the monitor passively observes."""
        await RisingEdge(self.dut.ACLK)
        self.dut.AWADDR.value = addr
        self.dut.AWVALID.value = 1
        self.dut.AWREADY.value = 1
        self.dut.WDATA.value = data
        self.dut.WSTRB.value = 0xF
        self.dut.WVALID.value = 1
        self.dut.WREADY.value = 1
        await RisingEdge(self.dut.ACLK)
        self.dut.AWADDR.value = 0
        self.dut.AWVALID.value = 0
        self.dut.AWREADY.value = 0
        self.dut.WVALID.value = 0
        self.dut.WREADY.value = 0
        self.dut.BRESP.value = 0
        self.dut.BVALID.value = 1
        self.dut.BREADY.value = 1
        await RisingEdge(self.dut.ACLK)
        self.dut.BVALID.value = 0
        self.dut.BREADY.value = 0

    async def axi_write_error(self, addr: int, data: int) -> None:
        """Like axi_write but the write response is SLVERR (BRESP=2'b10)."""
        await RisingEdge(self.dut.ACLK)
        self.dut.AWADDR.value = addr
        self.dut.AWVALID.value = 1
        self.dut.AWREADY.value = 1
        self.dut.WDATA.value = data
        self.dut.WSTRB.value = 0xF
        self.dut.WVALID.value = 1
        self.dut.WREADY.value = 1
        await RisingEdge(self.dut.ACLK)
        self.dut.AWVALID.value = 0
        self.dut.AWREADY.value = 0
        self.dut.WVALID.value = 0
        self.dut.WREADY.value = 0
        self.dut.BRESP.value = 0b10  # SLVERR -> b_err / any_err
        self.dut.BVALID.value = 1
        self.dut.BREADY.value = 1
        await RisingEdge(self.dut.ACLK)
        self.dut.BVALID.value = 0
        self.dut.BREADY.value = 0
        self.dut.BRESP.value = 0


async def setup(dut) -> MonDriver:
    d = MonDriver(dut)
    await d.start()
    return d


@cocotb.test()
async def identity_and_geometry(dut):
    d = await setup(dut)
    # The embedded ELA reports "LA"; the AM identity is at 0x00E8.
    assert (await d.read(ADDR_VERSION)) & 0xFFFF == 0x4C41
    # Flatten width: 152 raw, +8 events word when the decode layer is enabled.
    assert (await d.read(ADDR_SAMPLE_W)) == (160 if DECODE else 152)

    amid = await d.read(ADDR_AXI_MON_ID)
    assert (amid >> 16) == 0x414D, f"AM id 0x{amid:08x}"   # "AM"
    assert ((amid >> 8) & 0xFF) == 1                        # PROTO = AXI4-Lite
    assert (amid & 0x1) == DECODE                           # CAP_FLAGS bit0 = DECODE_EN

    geom = await d.read(ADDR_AXI_GEOM)
    assert (geom & 0xFF) == 32                              # ADDR_W
    assert ((geom >> 8) & 0xFF) == 32                       # DATA_W


@cocotb.test()
async def captures_error_event(dut):
    """Decode layer: trigger on the any_err event bit and capture an SLVERR."""
    d = await setup(dut)
    pre, post = 2, 3
    await d.write(ADDR_PRETRIG, pre)
    await d.write(ADDR_POSTTRIG, post)
    await d.write(ADDR_TRIG_MODE, 1)            # value match
    await d.write(ADDR_TRIG_VALUE, 0x80)        # any_err = events bit 7 (low byte)
    await d.write(ADDR_TRIG_MASK, 0x80)
    await d.arm()

    await d.wait_aclk(3)
    await d.axi_write_error(0x4000_0000, 0xDEAD_BEEF)
    await d.wait_aclk(8)
    assert (await d.wait_done()) & 0x4

    words = ((await d.read(ADDR_SAMPLE_W)) + 31) // 32
    # Trigger sample sits at buffer index `pre`; its low byte is the events word.
    events = (await d.read(ADDR_DATA_BASE + (pre * words) * 4)) & 0xFF
    assert (events >> 7) & 1 == 1, f"any_err not set: events=0x{events:02x}"
    assert (events >> 5) & 1 == 1, f"b_err not set: events=0x{events:02x}"
    assert (events >> 2) & 1 == 1, f"b_hs not set: events=0x{events:02x}"


@cocotb.test()
async def captures_axi_write_address(dut):
    d = await setup(dut)
    pre, post = 2, 3
    await d.write(ADDR_PRETRIG, pre)
    await d.write(ADDR_POSTTRIG, post)
    await d.write(ADDR_TRIG_MODE, 1)                # value match
    await d.write(ADDR_TRIG_VALUE, 0x4000_0000)     # awaddr occupies sample[31:0]
    await d.write(ADDR_TRIG_MASK, 0xFFFF_FFFF)
    await d.arm()

    await d.wait_aclk(3)
    await d.axi_write(0x4000_0000, 0xDEAD_BEEF)
    await d.wait_aclk(8)
    assert (await d.wait_done()) & 0x4

    words = ((await d.read(ADDR_SAMPLE_W)) + 31) // 32
    # Trigger sample sits at buffer index `pre`; word 0 is awaddr, awvalid is
    # bit 35 (= word 1, bit 3).
    base = ADDR_DATA_BASE + (pre * words) * 4
    awaddr = await d.read(base)
    word1 = await d.read(base + 4)
    assert awaddr == 0x4000_0000, f"captured awaddr 0x{awaddr:08x}"
    assert (word1 >> 3) & 1 == 1, "awvalid not set in the trigger sample"
