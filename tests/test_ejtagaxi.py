# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest
from typing import List

from fcapz.ejtagaxi import (
    AXIError,
    CMD_BURST_RDATA,
    CMD_BURST_RSTART,
    CMD_BURST_SETUP,
    CMD_BURST_WDATA,
    CMD_CONFIG,
    CMD_NOP,
    CMD_READ,
    CMD_READ_INC,
    CMD_RESET,
    CMD_SET_ADDR,
    CMD_WRITE,
    CMD_WRITE_INC,
    DR_WIDTH,
    EjtagAxiController,
    _BRIDGE_ID,
)
from fcapz.transport import Transport


# AXI response codes
RESP_OKAY   = 0b00
RESP_SLVERR = 0b10


class FakeBridgeTransport(Transport):
    """Simulates the 72-bit pipelined DR protocol used by fcapz_ejtagaxi."""

    # Config register map (read via CMD_CONFIG)
    _CONFIG_REGS = {
        0x0000: _BRIDGE_ID,     # BRIDGE_ID
        0x0004: 0x0001_0002,    # version: major=1, minor=2
        # features: addr_w=32, data_w=32, fifo_depth=16 (encoded as 15 in [23:16])
        0x002C: (0x0F << 16) | 0x2020,
    }

    def __init__(self):
        self.regs: list[int] = [0] * 16
        self.auto_inc_addr: int = 0
        self.prev_valid: bool = False
        self.prev_rdata: int = 0
        self.prev_resp: int = RESP_OKAY
        self.error_sticky: bool = False
        self.error_addr: int = 0xFFFFFFFC
        self.fifo: list[int] = []
        self.burst_config: dict = {}
        self.busy_count: int = 0
        self.fifo_stall_count: int = 0
        self._active_chain: int = 1
        self._config_regs: dict[int, int] = dict(self._CONFIG_REGS)
        self._last_cmd: int = CMD_NOP  # track last command for FIFO priming
        self.scan_log: list[int] = []

    # --- Transport ABC implementation ---

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def read_reg(self, addr: int) -> int:
        raise NotImplementedError("not used by bridge")

    def write_reg(self, addr: int, value: int) -> None:
        raise NotImplementedError("not used by bridge")

    def read_block(self, addr: int, words: int) -> List[int]:
        raise NotImplementedError("not used by bridge")

    def select_chain(self, chain: int) -> None:
        self._active_chain = chain

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        assert width == DR_WIDTH

        # Decode shift-in
        addr    = bits & 0xFFFFFFFF
        payload = (bits >> 32) & 0xFFFFFFFF
        wstrb   = (bits >> 64) & 0xF
        cmd     = (bits >> 68) & 0xF
        self.scan_log.append(cmd)

        # All commands are pipelined — build output from *previous* result,
        # then execute current command.
        #
        # BURST_RDATA pipeline: the first BURST_RDATA after BURST_RSTART
        # is a priming scan (last_cmd != BURST_RDATA), so no FIFO pop.
        # Subsequent BURST_RDATA scans pop the FIFO.

        status = 0
        if self.busy_count > 0:
            self.busy_count -= 1
            status |= 0x2  # BUSY
        else:
            if self.prev_valid:
                status |= 0x1  # PREV_VALID
        if self.error_sticky:
            status |= 0x4  # ERROR
        if self.fifo:
            status |= 0x8  # FIFO_NOTEMPTY

        out = self._encode_out(self.prev_rdata, 0, self.prev_resp, status)

        # Execute current command (always accepted by bridge).
        # For NOP during busy: skip exec to preserve prev_valid from
        # the real command that is still being processed.
        if cmd != CMD_NOP or not (status & 0x2):
            self._exec(cmd, addr, payload, wstrb)

        self._last_cmd = cmd
        return out

    # --- Internals ---

    def _encode_out(self, rdata: int, info: int, resp: int, status: int) -> int:
        return (
            (rdata & 0xFFFFFFFF)
            | ((info & 0xFFFFFFFF) << 32)
            | ((resp & 0x3) << 64)
            | ((status & 0xF) << 68)
        )

    def _addr_to_idx(self, addr: int) -> int:
        return (addr >> 2) & 0xF

    def _is_error_addr(self, addr: int) -> bool:
        return (addr & 0xFFFFFFFF) == (self.error_addr & 0xFFFFFFFF)

    def _exec(self, cmd: int, addr: int, payload: int, wstrb: int) -> None:
        if cmd == CMD_NOP:
            # After returning previous result, clear prev_valid
            self.prev_valid = False

        elif cmd == CMD_WRITE:
            if self._is_error_addr(addr):
                self.error_sticky = True
                self.prev_resp = RESP_SLVERR
            else:
                idx = self._addr_to_idx(addr)
                self.regs[idx] = payload & 0xFFFFFFFF
                self.prev_resp = RESP_OKAY
            self.prev_valid = True
            self.prev_rdata = 0

        elif cmd == CMD_READ:
            if self._is_error_addr(addr):
                self.error_sticky = True
                self.prev_resp = RESP_SLVERR
                self.prev_rdata = 0xDEADDEAD
            else:
                idx = self._addr_to_idx(addr)
                self.prev_rdata = self.regs[idx]
                self.prev_resp = RESP_OKAY
            self.prev_valid = True

        elif cmd == CMD_WRITE_INC:
            a = self.auto_inc_addr
            if self._is_error_addr(a):
                self.error_sticky = True
                self.prev_resp = RESP_SLVERR
            else:
                idx = self._addr_to_idx(a)
                self.regs[idx] = payload & 0xFFFFFFFF
                self.prev_resp = RESP_OKAY
            self.auto_inc_addr = (a + 4) & 0xFFFFFFFF
            self.prev_valid = True
            self.prev_rdata = 0

        elif cmd == CMD_READ_INC:
            a = self.auto_inc_addr
            if self._is_error_addr(a):
                self.error_sticky = True
                self.prev_resp = RESP_SLVERR
                self.prev_rdata = 0xDEADDEAD
            else:
                idx = self._addr_to_idx(a)
                self.prev_rdata = self.regs[idx]
                self.prev_resp = RESP_OKAY
            self.auto_inc_addr = (a + 4) & 0xFFFFFFFF
            self.prev_valid = True

        elif cmd == CMD_SET_ADDR:
            self.auto_inc_addr = addr & 0xFFFFFFFF
            self.prev_valid = False

        elif cmd == CMD_CONFIG:
            # Return config register value; pipelined so sets prev_rdata
            self.prev_rdata = self._config_regs.get(addr, 0)
            self.prev_valid = True
            self.prev_resp = RESP_OKAY

        elif cmd == CMD_BURST_SETUP:
            burst_len = payload & 0xFF
            size = (payload >> 8) & 0x7
            burst = (payload >> 12) & 0x3
            self.burst_config = {
                "addr": addr,
                "len": burst_len,
                "size": size,
                "burst": burst,
            }
            self.prev_valid = True
            self.prev_rdata = 0
            self.prev_resp = RESP_OKAY

        elif cmd == CMD_BURST_RSTART:
            cfg = self.burst_config
            base = cfg.get("addr", 0)
            count = cfg.get("len", 0) + 1
            self.fifo = []
            for i in range(count):
                a = base + i * 4
                idx = self._addr_to_idx(a)
                self.fifo.append(self.regs[idx])
            self.prev_valid = True
            self.prev_rdata = 0
            self.prev_resp = RESP_OKAY

        elif cmd == CMD_BURST_RDATA:
            if self.fifo_stall_count > 0:
                self.fifo_stall_count -= 1
                self.prev_valid = False
                self.prev_rdata = 0
                return
            # FIFO read pipeline: only pop if last_cmd was BURST_RDATA
            # (primed). First BURST_RDATA after anything else is a prime.
            if self._last_cmd == CMD_BURST_RDATA:
                if self.fifo:
                    self.prev_rdata = self.fifo.pop(0)
                    self.prev_valid = True
                    self.prev_resp = RESP_OKAY
                else:
                    self.prev_valid = False
                    self.prev_rdata = 0
            else:
                # Priming scan — no pop, just mark valid for status
                self.prev_valid = False
                self.prev_rdata = 0

        elif cmd == CMD_BURST_WDATA:
            cfg = self.burst_config
            base = cfg.get("addr", 0)
            beat = cfg.get("_wbeat", 0)
            a = base + beat * 4
            if self._is_error_addr(a):
                self.error_sticky = True
                self.prev_resp = RESP_SLVERR
            else:
                idx = self._addr_to_idx(a)
                self.regs[idx] = payload & 0xFFFFFFFF
                self.prev_resp = RESP_OKAY
            cfg["_wbeat"] = beat + 1
            self.prev_valid = True
            self.prev_rdata = 0

        elif cmd == CMD_RESET:
            self.error_sticky = False
            self.fifo = []
            self.prev_valid = False
            self.prev_rdata = 0
            self.prev_resp = RESP_OKAY

    # --- Helper for fifo stall ---
    # Override raw_dr_scan to handle fifo stall at the output level
    # (fifo_stall_count is handled inside _exec for BURST_RDATA)


class BatchOnlyBridgeTransport(FakeBridgeTransport):
    """Simulate hardware where isolated USER4 scans return zeros.

    This matches the Arty/hw_server behavior we observed on chain 4:
    a single raw USER4 DR scan comes back as all zeros, but the same scans
    work correctly when kept inside one batched raw_dr_scan_batch sequence.
    """

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        assert width == DR_WIDTH
        cmd = (bits >> 68) & 0xF
        self.scan_log.append(cmd)
        return 0

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        out: list[int] = []
        for bits, width in scans:
            out.append(FakeBridgeTransport.raw_dr_scan(self, bits, width, chain=chain))
        return out


class EjtagAxiTests(unittest.TestCase):

    def _make_ctrl(
        self, transport: FakeBridgeTransport | None = None
    ) -> tuple[EjtagAxiController, FakeBridgeTransport]:
        t = transport or FakeBridgeTransport()
        ctrl = EjtagAxiController(t, chain=4)
        ctrl.connect()
        return ctrl, t

    def test_connect_reads_bridge_id(self):
        ctrl, t = self._make_ctrl()
        # connect() already called by _make_ctrl — call again to check return
        t2 = FakeBridgeTransport()
        ctrl2 = EjtagAxiController(t2, chain=4)
        info = ctrl2.connect()
        self.assertEqual(info["bridge_id"], _BRIDGE_ID)
        self.assertEqual(info["version_major"], 1)
        self.assertEqual(info["version_minor"], 2)
        self.assertEqual(info["addr_w"], 0x20)
        self.assertEqual(info["data_w"], 0x20)

    def test_connect_primes_bridge_with_reset(self):
        t = FakeBridgeTransport()
        ctrl = EjtagAxiController(t, chain=4)
        ctrl.connect()
        self.assertGreaterEqual(len(t.scan_log), 6)
        self.assertEqual(t.scan_log[:4], [CMD_CONFIG, CMD_CONFIG, CMD_CONFIG, CMD_NOP])
        self.assertEqual(t.scan_log[4], CMD_RESET)
        self.assertEqual(t.scan_log[5], CMD_NOP)

    def test_connect_bad_id_raises(self):
        t = FakeBridgeTransport()
        t._config_regs[0x0000] = 0xDEADBEEF
        ctrl = EjtagAxiController(t, chain=4)
        with self.assertRaises(RuntimeError):
            ctrl.connect()

    def test_axi_write_single(self):
        ctrl, t = self._make_ctrl()
        ctrl.axi_write(0x0008, 0xCAFEBABE)
        self.assertEqual(t.regs[2], 0xCAFEBABE)

    def test_axi_read_single(self):
        ctrl, t = self._make_ctrl()
        t.regs[3] = 0x12345678
        val = ctrl.axi_read(0x000C)
        self.assertEqual(val, 0x12345678)

    def test_write_read_roundtrip(self):
        ctrl, t = self._make_ctrl()
        ctrl.axi_write(0x0010, 0xA5A5A5A5)
        val = ctrl.axi_read(0x0010)
        self.assertEqual(val, 0xA5A5A5A5)

    def test_write_block(self):
        ctrl, t = self._make_ctrl()
        data = [0x100 + i for i in range(8)]
        ctrl.write_block(0x0000, data)
        for i in range(8):
            self.assertEqual(t.regs[i], 0x100 + i)

    def test_read_block(self):
        ctrl, t = self._make_ctrl()
        for i in range(8):
            t.regs[i] = 0x200 + i
        result = ctrl.read_block(0x0000, 8)
        self.assertEqual(result, [0x200 + i for i in range(8)])

    def test_burst_write(self):
        ctrl, t = self._make_ctrl()
        data = [0xAA00 + i for i in range(4)]
        ctrl.burst_write(0x0000, data)
        for i in range(4):
            self.assertEqual(t.regs[i], 0xAA00 + i)

    def test_burst_read(self):
        ctrl, t = self._make_ctrl()
        for i in range(4):
            t.regs[i] = 0xBB00 + i
        result = ctrl.burst_read(0x0000, 4)
        self.assertEqual(result, [0xBB00 + i for i in range(4)])

    def test_connect_caches_fifo_depth(self):
        ctrl, _ = self._make_ctrl()
        self.assertEqual(ctrl._fifo_depth, 16)

    def test_burst_read_rejects_count_exceeding_fifo_depth(self):
        ctrl, _ = self._make_ctrl()
        with self.assertRaisesRegex(ValueError, "FIFO_DEPTH"):
            ctrl.burst_read(0x0000, 17)  # FIFO_DEPTH=16

    def test_burst_read_rejects_count_exceeding_axi_max(self):
        ctrl, _ = self._make_ctrl()
        # Even if we patch fifo_depth, AXI4 max is 256 — but the FIFO check
        # fires first.  Patch fifo_depth high to test the AXI4 check.
        ctrl._fifo_depth = 512
        with self.assertRaisesRegex(ValueError, "AXI4 max burst"):
            ctrl.burst_read(0x0000, 257)

    def test_burst_read_rejects_zero_count(self):
        ctrl, _ = self._make_ctrl()
        with self.assertRaisesRegex(ValueError, "count must be > 0"):
            ctrl.burst_read(0x0000, 0)

    def test_burst_write_rejects_empty_data(self):
        ctrl, _ = self._make_ctrl()
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            ctrl.burst_write(0x0000, [])

    def test_burst_write_rejects_count_exceeding_fifo_depth(self):
        ctrl, _ = self._make_ctrl()
        with self.assertRaisesRegex(ValueError, "FIFO_DEPTH"):
            ctrl.burst_write(0x0000, [0] * 17)

    def test_error_raises_axi_error(self):
        ctrl, t = self._make_ctrl()
        with self.assertRaises(AXIError):
            ctrl.axi_write(t.error_addr, 0x1234)

    def test_read_error_raises(self):
        ctrl, t = self._make_ctrl()
        with self.assertRaises(AXIError):
            ctrl.axi_read(t.error_addr)

    def test_busy_retries_then_succeeds(self):
        ctrl, t = self._make_ctrl()
        t.busy_count = 3
        ctrl.axi_write(0x0004, 0xDEAD)
        self.assertEqual(t.regs[1], 0xDEAD)

    def test_busy_exceeded_raises(self):
        ctrl, t = self._make_ctrl()
        t.busy_count = 20  # > MAX_BUSY_RETRIES (16)
        with self.assertRaises(AXIError) as cm:
            ctrl.axi_write(0x0004, 0x1111)
        self.assertIn("busy", str(cm.exception).lower())

    def test_fifo_stall_retries(self):
        ctrl, t = self._make_ctrl()
        for i in range(4):
            t.regs[i] = 0xCC00 + i
        t.fifo_stall_count = 2
        result = ctrl.burst_read(0x0000, 4)
        self.assertEqual(result, [0xCC00 + i for i in range(4)])

    def test_reset_clears_error(self):
        ctrl, t = self._make_ctrl()
        # Trigger error
        t.error_sticky = True
        # close() sends CMD_RESET
        ctrl.close()
        self.assertFalse(t.error_sticky)

    def test_chain_selection(self):
        t = FakeBridgeTransport()
        ctrl = EjtagAxiController(t, chain=4)
        ctrl.connect()
        self.assertEqual(t._active_chain, 4)

    def test_batch_only_transport_still_connects_and_moves_data(self):
        ctrl, t = self._make_ctrl(BatchOnlyBridgeTransport())
        ctrl.axi_write(0x0000, 0xCAFEBABE)
        self.assertEqual(ctrl.axi_read(0x0000), 0xCAFEBABE)
        ctrl.write_block(0x0004, [0x11, 0x22, 0x33, 0x44])
        self.assertEqual(ctrl.read_block(0x0004, 4), [0x11, 0x22, 0x33, 0x44])


if __name__ == "__main__":
    unittest.main()
