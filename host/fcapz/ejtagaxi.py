# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host-side controller for the fcapz_ejtagaxi JTAG-to-AXI4 bridge core.

Uses a 72-bit pipelined streaming DR — each scan shifts in a command and
shifts out the previous result. One AXI transaction per scan.

DR format (72 bits, LSB first):
  Shift-in:  [31:0]=addr, [63:32]=payload, [67:64]=wstrb, [71:68]=cmd
  Shift-out: [31:0]=rdata, [63:32]=info, [65:64]=resp, [67:66]=rsvd, [71:68]=status
"""

from __future__ import annotations

import warnings

from .transport import Transport

# Command codes
CMD_NOP          = 0x0
CMD_WRITE        = 0x1
CMD_READ         = 0x2
CMD_WRITE_INC    = 0x3
CMD_READ_INC     = 0x4
CMD_SET_ADDR     = 0x5
CMD_BURST_SETUP  = 0x6
CMD_BURST_WDATA  = 0x7
CMD_BURST_RDATA  = 0x8
CMD_BURST_RSTART = 0x9
CMD_CONFIG       = 0xE
CMD_RESET        = 0xF

DR_WIDTH = 72

_BRIDGE_ID = 0x454A4158  # ASCII "EJAX"


class AXIError(Exception):
    """Raised when an AXI transaction fails."""


class EjtagAxiController:
    """Controller for the fcapz_ejtagaxi JTAG-to-AXI4 bridge."""

    # Status bit masks
    _PREV_VALID    = 0x1
    _BUSY          = 0x2
    _ERROR         = 0x4
    _FIFO_NOTEMPTY = 0x8

    _MAX_BUSY_RETRIES = 16

    def __init__(self, transport: Transport, chain: int = 4):
        self._transport = transport
        self._chain = chain
        self._fifo_depth: int = 0  # populated by connect() from FEATURES

    def _encode(self, cmd: int, addr: int = 0, payload: int = 0,
                wstrb: int = 0xF) -> int:
        """Build a 72-bit shift-in value."""
        return (
            (addr & 0xFFFFFFFF)
            | ((payload & 0xFFFFFFFF) << 32)
            | ((wstrb & 0xF) << 64)
            | ((cmd & 0xF) << 68)
        )

    @staticmethod
    def _decode(bits_out: int) -> tuple[int, int, int, int]:
        """Parse a 72-bit shift-out into (status, resp, rdata, info)."""
        rdata  = bits_out & 0xFFFFFFFF
        info   = (bits_out >> 32) & 0xFFFFFFFF
        resp   = (bits_out >> 64) & 0x3
        status = (bits_out >> 68) & 0xF
        return status, resp, rdata, info

    def _scan(self, cmd: int, addr: int = 0, payload: int = 0,
              wstrb: int = 0xF) -> tuple[int, int, int, int]:
        """Single 72-bit DR scan. Returns (status, resp, rdata, info)."""
        bits_out = self._transport.raw_dr_scan(
            self._encode(cmd, addr, payload, wstrb),
            DR_WIDTH, chain=self._chain,
        )
        return self._decode(bits_out)

    def _check_error(self, status: int, resp: int, context: str) -> None:
        if status & self._ERROR:
            raise AXIError(f"{context}: resp={resp}")

    def _wait_valid(self, context: str) -> tuple[int, int, int, int]:
        """Send NOPs until prev_valid=1 or error."""
        for _ in range(self._MAX_BUSY_RETRIES):
            status, resp, rdata, info = self._scan(CMD_NOP)
            self._check_error(status, resp, context)
            if status & self._PREV_VALID:
                return status, resp, rdata, info
            if not (status & self._BUSY):
                raise AXIError(
                    f"{context}: bridge returned status=0x{status:X} "
                    f"(not valid, not busy, not error)"
                )
        raise AXIError(f"{context}: bridge still busy after "
                       f"{self._MAX_BUSY_RETRIES} polls")

    def _wait_fifo_data(self, context: str) -> tuple[int, int, int, int]:
        """Send BURST_RDATA scans until prev_valid=1 (data captured from FIFO)."""
        for _ in range(self._MAX_BUSY_RETRIES):
            status, resp, rdata, info = self._scan(CMD_BURST_RDATA)
            self._check_error(status, resp, context)
            if status & self._PREV_VALID:
                return status, resp, rdata, info
        raise AXIError(f"{context}: read FIFO empty after "
                       f"{self._MAX_BUSY_RETRIES} polls")

    def connect(self) -> dict:
        """Open transport, select chain, and probe bridge identity.

        Owns the transport lifecycle (matching Analyzer.connect and
        EioController.connect): connect() opens, close() closes.

        4 scans: 3 CONFIG + 1 NOP drain.
        """
        self._transport.connect()
        self._transport.select_chain(self._chain)
        self._scan(CMD_CONFIG, addr=0x0000)
        _, _, bridge_id, _ = self._scan(CMD_CONFIG, addr=0x0004)
        _, _, version, _   = self._scan(CMD_CONFIG, addr=0x002C)
        _, _, features, _  = self._scan(CMD_NOP)
        if bridge_id != _BRIDGE_ID:
            raise RuntimeError(f"Bad BRIDGE_ID: 0x{bridge_id:08X}")
        # FEATURES[23:16] = (FIFO_DEPTH - 1), AXI4 awlen convention.
        # Add 1 back to recover the true depth (max supported burst beats).
        self._fifo_depth = ((features >> 16) & 0xFF) + 1
        return {
            "bridge_id": bridge_id,
            "version_major": version >> 16,
            "version_minor": version & 0xFFFF,
            "addr_w": features & 0xFF,
            "data_w": (features >> 8) & 0xFF,
            "fifo_depth": self._fifo_depth,
        }

    def attach(self) -> dict:
        """Like :meth:`connect` but assume the transport is already open.

        Restores JTAG chain 1 (ELA) before returning so a shared session can
        continue using USER1 register access.
        """
        self._transport.select_chain(self._chain)
        try:
            self._scan(CMD_CONFIG, addr=0x0000)
            _, _, bridge_id, _ = self._scan(CMD_CONFIG, addr=0x0004)
            _, _, version, _ = self._scan(CMD_CONFIG, addr=0x002C)
            _, _, features, _ = self._scan(CMD_NOP)
            if bridge_id != _BRIDGE_ID:
                raise RuntimeError(f"Bad BRIDGE_ID: 0x{bridge_id:08X}")
            self._fifo_depth = ((features >> 16) & 0xFF) + 1
            return {
                "bridge_id": bridge_id,
                "version_major": version >> 16,
                "version_minor": version & 0xFFFF,
                "addr_w": features & 0xFF,
                "data_w": (features >> 8) & 0xFF,
                "fifo_depth": self._fifo_depth,
            }
        finally:
            self._transport.select_chain(1)

    def axi_write(self, addr: int, data: int, wstrb: int = 0xF) -> int:
        """Single AXI write. 2 scans. Returns resp code."""
        self._scan(CMD_WRITE, addr=addr, payload=data, wstrb=wstrb)
        status, resp, _, _ = self._wait_valid(f"Write to 0x{addr:08X}")
        return resp

    def axi_read(self, addr: int) -> int:
        """Single AXI read. 2 scans. Returns 32-bit data."""
        self._scan(CMD_READ, addr=addr)
        _, _, rdata, _ = self._wait_valid(f"Read from 0x{addr:08X}")
        return rdata

    def write_block(self, base_addr: int, data: list[int],
                    wstrb: int = 0xF) -> None:
        """Sequential writes using auto-increment.

        Uses raw_dr_scan_batch to combine SET_ADDR + N×WRITE_INC + NOP
        into a single JTAG sequence for maximum throughput.
        """
        scans = [
            (self._encode(CMD_SET_ADDR, addr=base_addr), DR_WIDTH),
        ]
        for word in data:
            scans.append(
                (self._encode(CMD_WRITE_INC, payload=word, wstrb=wstrb),
                 DR_WIDTH))
        scans.append((self._encode(CMD_NOP), DR_WIDTH))  # drain

        results = self._transport.raw_dr_scan_batch(
            scans, chain=self._chain)

        # Check responses: result[i+1] has status for scan[i]'s command.
        # Skip result[0] (SET_ADDR output) and result[1] (first WRITE_INC
        # output = SET_ADDR's result).  From result[2] onward, each has
        # the previous write's status.
        for i in range(2, len(results)):
            status, resp, _, _ = self._decode(results[i])
            self._check_error(status, resp,
                f"Block write failed at word {i-2}")

    def read_block(self, base_addr: int, count: int) -> list[int]:
        """Sequential reads using auto-increment.

        Uses raw_dr_scan_batch to combine SET_ADDR + prime READ_INC +
        (N-1)×READ_INC + NOP drain into a single JTAG sequence.
        """
        scans = [
            (self._encode(CMD_SET_ADDR, addr=base_addr), DR_WIDTH),
            (self._encode(CMD_READ_INC), DR_WIDTH),  # prime
        ]
        for _ in range(count - 1):
            scans.append((self._encode(CMD_READ_INC), DR_WIDTH))
        scans.append((self._encode(CMD_NOP), DR_WIDTH))  # drain

        results = self._transport.raw_dr_scan_batch(
            scans, chain=self._chain)

        # results[0] = SET_ADDR output (useless)
        # results[1] = prime READ_INC output (useless)
        # results[2] = first read's data (prev_valid from prime)
        # ...
        # results[count+1] = last read's data (drain NOP)
        out = []
        for i in range(2, count + 2):
            status, resp, rdata, _ = self._decode(results[i])
            self._check_error(status, resp,
                f"Block read failed at word {i-2}")
            out.append(rdata)
        return out

    def burst_write(self, base_addr: int, data: list[int],
                    wstrb: int = 0xF) -> None:
        """AXI4 burst write. N+2 scans.

        Raises:
            ValueError: If ``len(data)`` is 0, exceeds 256 (AXI4 max burst),
                or exceeds the bridge's FIFO_DEPTH reported in FEATURES.
        """
        n = len(data)
        if n == 0:
            raise ValueError("burst_write: data must not be empty")
        if n > 256:
            raise ValueError(f"burst_write: count {n} exceeds AXI4 max burst (256)")
        if self._fifo_depth and n > self._fifo_depth:
            raise ValueError(
                f"burst_write: count {n} exceeds bridge FIFO_DEPTH "
                f"({self._fifo_depth}); rebuild bitstream with larger FIFO_DEPTH"
            )
        burst_len = n - 1
        config = (burst_len & 0xFF) | (0b010 << 8) | (0b01 << 12)
        self._scan(CMD_BURST_SETUP, addr=base_addr, payload=config)
        for i, word in enumerate(data):
            status, resp, _, _ = self._scan(
                CMD_BURST_WDATA, payload=word, wstrb=wstrb)
            if i > 0:
                self._check_error(status, resp,
                    f"Burst write failed at beat {i-1}")
        self._wait_valid("Burst write drain")

    def burst_read(self, base_addr: int, count: int) -> list[int]:
        """AXI4 burst read. N+3 scans.

        The FIFO read has a 1-scan pipeline delay: the first BURST_RDATA
        scan sets last_cmd but doesn't capture FIFO data (because last_cmd
        was still BURST_RSTART at CAPTURE time). The second scan captures
        fifo[0]. So we need a priming scan before the data scans.

        Raises:
            ValueError: If ``count`` is <=0, exceeds 256 (AXI4 max burst),
                or exceeds the bridge's FIFO_DEPTH reported in FEATURES.
                The bridge cannot buffer more beats than its FIFO holds —
                rebuild the bitstream with a larger FIFO_DEPTH parameter
                if longer bursts are required.
        """
        if count <= 0:
            raise ValueError(f"burst_read: count must be > 0, got {count}")
        if count > 256:
            raise ValueError(f"burst_read: count {count} exceeds AXI4 max burst (256)")
        if self._fifo_depth and count > self._fifo_depth:
            raise ValueError(
                f"burst_read: count {count} exceeds bridge FIFO_DEPTH "
                f"({self._fifo_depth}); rebuild bitstream with larger FIFO_DEPTH"
            )
        burst_len = count - 1
        config = (burst_len & 0xFF) | (0b010 << 8) | (0b01 << 12)
        self._scan(CMD_BURST_SETUP, addr=base_addr, payload=config)
        self._scan(CMD_BURST_RSTART)
        # Prime: sets last_cmd to BURST_RDATA so next scan captures fifo[0]
        self._scan(CMD_BURST_RDATA)
        results = []
        for i in range(count):
            status, resp, rdata, _ = self._wait_fifo_data(
                f"Burst read beat {i}")
            results.append(rdata)
        return results

    def close(self) -> None:
        """Wait for idle, send CMD_RESET to bridge, then close transport.

        If the bridge is busy (AXI transaction in flight), RESET only
        clears tck-side state but does not propagate to the AXI domain.
        We poll until busy clears, then re-issue RESET so it reaches
        the AXI FSM and clears fifo_wptr / resp state.
        """
        try:
            # First attempt — may not propagate if bridge is busy
            self._scan(CMD_RESET)
            # Poll until not busy (in-flight AXI op completes)
            for _ in range(self._MAX_BUSY_RETRIES):
                status, _, _, _ = self._scan(CMD_NOP)
                if not (status & self._BUSY):
                    break
            # Re-issue RESET now that we're idle — this one propagates
            self._scan(CMD_RESET)
        except Exception as exc:
            warnings.warn(
                f"EjtagAxiController.close(): reset failed ({exc}); "
                "transport may be in an unknown state",
                RuntimeWarning,
                stacklevel=2,
            )
        self._transport.close()
