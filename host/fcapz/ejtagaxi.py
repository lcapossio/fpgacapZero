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

import time
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

_BRIDGE_CORE_ID = 0x4A58  # ASCII "JX"
_BRIDGE_ID = _BRIDGE_CORE_ID  # compatibility alias for older tests/imports
_LEGACY_BRIDGE_ID = 0x454A4158  # ASCII "EJAX"
_legacy_bridge_id_warned = False


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
                wstrb: int = 0x0) -> int:
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
              wstrb: int = 0x0) -> tuple[int, int, int, int]:
        """Single 72-bit DR scan. Returns (status, resp, rdata, info)."""
        bits_out = self._transport.raw_dr_scan(
            self._encode(cmd, addr, payload, wstrb),
            DR_WIDTH, chain=self._chain,
        )
        return self._decode(bits_out)

    def _scan_batch(
        self,
        scans: list[tuple[int, int, int, int]],
    ) -> list[tuple[int, int, int, int]]:
        """Run multiple DR scans in one transport batch."""
        if not scans:
            return []
        raw = self._transport.raw_dr_scan_batch(
            [
                (self._encode(cmd, addr, payload, wstrb), DR_WIDTH)
                for cmd, addr, payload, wstrb in scans
            ],
            chain=self._chain,
        )
        return [self._decode(bits_out) for bits_out in raw]

    def _wait_for_valid_from_batch(
        self,
        initial: list[tuple[int, int, int, int]],
        *,
        wait_cmd: int,
        context: str,
    ) -> tuple[int, int, int, int]:
        """Run *initial* followed by wait scans; return the first valid result."""
        decoded = self._scan_batch(
            initial + [(wait_cmd, 0, 0, 0)] * self._MAX_BUSY_RETRIES
        )
        for status, resp, rdata, info in decoded[1:]:
            self._check_error(status, resp, context)
            if status & self._PREV_VALID:
                return status, resp, rdata, info
            if status == 0:
                continue
            if status & self._FIFO_NOTEMPTY:
                continue
            if not (status & self._BUSY):
                raise AXIError(
                    f"{context}: bridge returned status=0x{status:X} "
                    f"(not valid, not busy, not error)"
                )
        raise AXIError(
            f"{context}: bridge still busy/unresolved after "
            f"{self._MAX_BUSY_RETRIES} polls"
        )

    def _collect_valids_from_batch(
        self,
        initial: list[tuple[int, int, int, int]],
        *,
        wait_cmd: int,
        needed: int,
        context: str,
    ) -> list[tuple[int, int, int, int]]:
        """Collect *needed* valid responses from a single batched transfer."""
        if needed <= 0:
            return []
        decoded = self._scan_batch(
            initial + [(wait_cmd, 0, 0, 0)] * (needed + self._MAX_BUSY_RETRIES)
        )
        out: list[tuple[int, int, int, int]] = []
        for status, resp, rdata, info in decoded[1:]:
            self._check_error(status, resp, context)
            if status & self._PREV_VALID:
                out.append((status, resp, rdata, info))
                if len(out) == needed:
                    return out
                continue
            if status == 0:
                continue
            if status & self._FIFO_NOTEMPTY:
                continue
            if not (status & self._BUSY):
                raise AXIError(
                    f"{context}: stalled after {len(out)}/{needed} "
                    f"responses: status=0x{status:X}"
                )
        raise AXIError(
            f"{context}: still unresolved after {len(out)}/{needed} responses"
        )

    def _check_error(self, status: int, resp: int, context: str) -> None:
        if status & self._ERROR:
            raise AXIError(f"{context}: resp={resp}")

    def _wait_valid(self, context: str) -> tuple[int, int, int, int]:
        """Send NOPs until prev_valid=1 or error.

        Hardware traces show that the bridge can occasionally report
        status=0x0 for one or more scans even though recent read responses are
        still flowing through the AXI->respq->TCK path. Treat that state as an
        indeterminate presentation gap and keep polling until either prev_valid
        arrives, an error appears, or the retry budget is exhausted.
        """
        last_status = 0
        for _ in range(self._MAX_BUSY_RETRIES):
            status, resp, rdata, info = self._scan(CMD_NOP)
            last_status = status
            self._check_error(status, resp, context)
            if status & self._PREV_VALID:
                return status, resp, rdata, info
            # status=0x0 has been observed transiently on hardware even when
            # surrounding scans show valid bridge activity. Keep polling.
            if status == 0:
                continue
            if not (status & self._BUSY):
                raise AXIError(
                    f"{context}: bridge returned status=0x{status:X} "
                    f"(not valid, not busy, not error)"
                )
        raise AXIError(f"{context}: bridge still unresolved after "
                       f"{self._MAX_BUSY_RETRIES} polls (last_status=0x{last_status:X})")

    def _wait_fifo_data(self, context: str) -> tuple[int, int, int, int]:
        """Send BURST_RDATA scans until prev_valid=1 (data captured from FIFO)."""
        for _ in range(self._MAX_BUSY_RETRIES):
            status, resp, rdata, info = self._scan(CMD_BURST_RDATA)
            self._check_error(status, resp, context)
            if status & self._PREV_VALID:
                return status, resp, rdata, info
        raise AXIError(f"{context}: read FIFO empty after "
                       f"{self._MAX_BUSY_RETRIES} polls")

    def _prime_cdc(self) -> None:
        """Issue CMD_RESET + drain so the first real command starts from idle.

        Even with the async FIFO RTL in place, hardware has shown that the
        first post-connect command can still behave differently from steady
        state. Priming with RESET forces one known-good round trip through the
        bridge before user traffic begins.
        """
        decoded = self._scan_batch(
            [(CMD_RESET, 0, 0, 0)] + [(CMD_NOP, 0, 0, 0)] * self._MAX_BUSY_RETRIES
        )
        for status, _, _, _ in decoded[1:]:
            if not (status & self._BUSY):
                return
        raise RuntimeError(
            "EjtagAxiController._prime_cdc: bridge still busy after "
            f"RESET + {self._MAX_BUSY_RETRIES} NOP polls"
        )

    @staticmethod
    def _decode_config(
        identity_or_version: int,
        legacy_version: int,
        features: int,
    ) -> dict:
        core_id = identity_or_version & 0xFFFF
        legacy = identity_or_version == _LEGACY_BRIDGE_ID
        if legacy:
            global _legacy_bridge_id_warned
            if not _legacy_bridge_id_warned:
                warnings.warn(
                    "EJTAG-AXI bridge reports legacy BRIDGE_ID 0x454A4158 "
                    "('EJAX'); rebuild the bitstream to expose VERSION[15:0] "
                    "as 0x4A58 ('JX'). Legacy IDs are accepted for now.",
                    RuntimeWarning,
                    stacklevel=3,
                )
                _legacy_bridge_id_warned = True
            version = legacy_version
            return {
                "bridge_id": _BRIDGE_CORE_ID,
                "core_id": _BRIDGE_CORE_ID,
                "legacy_id": True,
                "legacy_raw_id": identity_or_version,
                "version": version,
                "version_major": version >> 16,
                "version_minor": version & 0xFFFF,
                "addr_w": features & 0xFF,
                "data_w": (features >> 8) & 0xFF,
                "fifo_depth": ((features >> 16) & 0xFF) + 1,
            }
        if core_id != _BRIDGE_CORE_ID:
            raise RuntimeError(f"Bad EJTAG-AXI VERSION[15:0]: 0x{core_id:04X}")
        version = identity_or_version
        return {
            "bridge_id": core_id,
            "core_id": core_id,
            "legacy_id": False,
            "legacy_raw_id": None,
            "version": version,
            "version_major": (version >> 24) & 0xFF,
            "version_minor": (version >> 16) & 0xFF,
            "addr_w": features & 0xFF,
            "data_w": (features >> 8) & 0xFF,
            "fifo_depth": ((features >> 16) & 0xFF) + 1,
        }

    def connect(self) -> dict:
        """Open transport, select chain, and probe bridge identity.

        Owns the transport lifecycle (matching Analyzer.connect and
        EioController.connect): connect() opens, close() closes.

        4 scans (3 CONFIG + 1 NOP drain) to read identity, then prime the
        bridge with RESET + NOP drain so the first real command starts from a
        fully-idle state.
        """
        self._transport.select_chain(self._chain)
        old_ready_probe_addr = getattr(self._transport, "ready_probe_addr", None)
        if hasattr(self._transport, "ready_probe_addr"):
            # The generic hw_server ready probe uses the 49-bit ELA/EIO
            # register protocol. EJTAG-AXI uses a 72-bit streaming DR, so
            # readiness must be checked with CMD_CONFIG after connect().
            self._transport.ready_probe_addr = None
        try:
            self._transport.connect()
        finally:
            if hasattr(self._transport, "ready_probe_addr"):
                self._transport.ready_probe_addr = old_ready_probe_addr
        self._transport.select_chain(self._chain)
        deadline = time.monotonic() + float(
            getattr(self._transport, "ready_probe_timeout", 2.0)
        )
        decoded = []
        while True:
            decoded = self._scan_batch(
                [
                    (CMD_CONFIG, 0x0000, 0, 0),
                    (CMD_CONFIG, 0x0004, 0, 0),
                    (CMD_CONFIG, 0x002C, 0, 0),
                    (CMD_NOP, 0, 0, 0),
                ]
            )
            _, _, identity_or_version, _ = decoded[1]
            core_id = identity_or_version & 0xFFFF
            if (
                core_id == _BRIDGE_CORE_ID
                or identity_or_version == _LEGACY_BRIDGE_ID
                or time.monotonic() >= deadline
            ):
                break
            time.sleep(0.02)
        _, _, identity_or_version, _ = decoded[1]
        _, _, legacy_version, _ = decoded[2]
        _, _, features, _ = decoded[3]
        info = self._decode_config(identity_or_version, legacy_version, features)
        # FEATURES[23:16] = (FIFO_DEPTH - 1), AXI4 awlen convention.
        # Add 1 back to recover the true depth (max supported burst beats).
        self._fifo_depth = int(info["fifo_depth"])
        self._prime_cdc()
        return info

    def attach(self) -> dict:
        """Like :meth:`connect` but assume the transport is already open.

        Restores JTAG chain 1 (ELA) before returning so a shared
        session can continue using USER1 register access. Also primes the
        bridge before any subsequent command traffic.
        """
        self._transport.select_chain(self._chain)
        try:
            decoded = self._scan_batch(
                [
                    (CMD_CONFIG, 0x0000, 0, 0),
                    (CMD_CONFIG, 0x0004, 0, 0),
                    (CMD_CONFIG, 0x002C, 0, 0),
                    (CMD_NOP, 0, 0, 0),
                ]
            )
            _, _, identity_or_version, _ = decoded[1]
            _, _, legacy_version, _ = decoded[2]
            _, _, features, _ = decoded[3]
            info = self._decode_config(identity_or_version, legacy_version, features)
            self._fifo_depth = int(info["fifo_depth"])
            self._prime_cdc()
            return info
        finally:
            self._transport.select_chain(1)

    def axi_write(self, addr: int, data: int, wstrb: int = 0xF) -> int:
        """Single AXI write. 2 scans. Returns resp code."""
        status, resp, _, _ = self._wait_for_valid_from_batch(
            [(CMD_WRITE, addr, data, wstrb)],
            wait_cmd=CMD_NOP,
            context=f"Write to 0x{addr:08X}",
        )
        return resp

    def axi_read(self, addr: int) -> int:
        """Single AXI read. 2 scans. Returns 32-bit data."""
        _, _, rdata, _ = self._wait_for_valid_from_batch(
            [(CMD_READ, addr, 0, 0)],
            wait_cmd=CMD_NOP,
            context=f"Read from 0x{addr:08X}",
        )
        return rdata

    def write_block(self, base_addr: int, data: list[int],
                    wstrb: int = 0xF) -> None:
        """Sequential writes using auto-increment.

        Uses raw_dr_scan_batch to combine SET_ADDR + N×WRITE_INC + NOP
        into a single JTAG sequence for maximum throughput, then drains
        completion responses.  The RTL command FIFO can queue writes faster
        than AXI completes them, so one trailing NOP is not enough to prove
        the whole block committed.
        """
        scans = [(CMD_SET_ADDR, base_addr, 0, 0)]
        for word in data:
            scans.append((CMD_WRITE_INC, 0, word, wstrb))
        self._collect_valids_from_batch(
            scans,
            wait_cmd=CMD_NOP,
            needed=len(data),
            context="Block write",
        )

    def read_block(self, base_addr: int, count: int) -> list[int]:
        """Sequential reads using auto-increment.

        Uses raw_dr_scan_batch to combine SET_ADDR + prime READ_INC +
        (N-1)×READ_INC + NOP drain into a single JTAG sequence, then
        drains until all queued read completions have arrived.
        """
        scans = [
            (CMD_SET_ADDR, base_addr, 0, 0),
            (CMD_READ_INC, 0, 0, 0),
        ]
        for _ in range(count - 1):
            scans.append((CMD_READ_INC, 0, 0, 0))
        results = self._collect_valids_from_batch(
            scans,
            wait_cmd=CMD_NOP,
            needed=count,
            context="Block read",
        )
        return [rdata for _, _, rdata, _ in results]

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
        scans = [(CMD_BURST_SETUP, base_addr, config, 0)]
        scans.extend((CMD_BURST_WDATA, 0, word, wstrb) for word in data)
        decoded = self._scan_batch(
            scans + [(CMD_NOP, 0, 0, 0)] * (len(data) + self._MAX_BUSY_RETRIES)
        )
        valid_positions: list[int] = []
        for idx, (status, resp, _, _) in enumerate(decoded[1:], start=1):
            self._check_error(status, resp, "Burst write")
            if status & self._PREV_VALID:
                valid_positions.append(idx)
                continue
            if status == 0 or (status & self._FIFO_NOTEMPTY):
                continue
            if valid_positions and not (status & self._BUSY):
                raise AXIError(
                    f"Burst write stalled after {len(valid_positions)}/{len(data)} beats: "
                    f"status=0x{status:X}"
                )
        setup_responded = bool(valid_positions and valid_positions[0] == 1)
        expected = len(data) + (1 if setup_responded else 0)
        if len(valid_positions) < expected:
            raise AXIError(
                f"Burst write still unresolved after "
                f"{len(valid_positions)}/{expected} responses"
            )

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
        scans = [
            (CMD_BURST_SETUP, base_addr, config, 0),
            (CMD_BURST_RSTART, 0, 0, 0),
        ]
        scans.extend((CMD_BURST_RDATA, 0, 0, 0) for _ in range(count + 2 + self._MAX_BUSY_RETRIES))
        decoded = self._scan_batch(scans)
        out: list[int] = []
        for idx, (status, resp, rdata, _) in enumerate(decoded[1:], start=1):
            self._check_error(status, resp, "Burst read")
            if status & self._PREV_VALID:
                if idx <= 2:
                    continue
                out.append(rdata)
                if len(out) == count:
                    return out
                continue
            if status == 0 or (status & self._FIFO_NOTEMPTY):
                continue
            if out and not (status & self._BUSY):
                raise AXIError(
                    f"Burst read stalled after {len(out)}/{count} beats: "
                    f"status=0x{status:X}"
                )
        raise AXIError(
            f"Burst read still unresolved after {len(out)}/{count} beats"
        )

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
