# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host-side controller for the fcapz_ejtaguart JTAG-to-UART bridge core.

The bridge has **no** ELA-style word-indexed register file: one **32-bit DR**
per scan carries a command and optional data.  Identity and build parameters
are read with ``CMD_CONFIG`` over byte addresses ``0x0``–``0xF`` (see
``docs/specs/register_map.md``, section **EJTAG-UART**).

Uses a 32-bit pipelined DR — each scan shifts in a command + tx_byte and
shifts out status + rx_byte + tx_free.

DR format (32 bits, LSB first):
  Shift-in:  [7:0]=tx_byte, [27:8]=reserved, [31:28]=cmd
  Shift-out: [7:0]=rx_byte, [15:8]=tx_free, [23:16]=rsvd,
             [24]=RX_READY, [28]=RX_VALID, [29]=TX_FULL,
             [30]=RX_OVERFLOW, [31]=FRAME_ERR
"""

from __future__ import annotations

import time

from .transport import Transport

# Command codes
CMD_NOP     = 0x0
CMD_TX_PUSH = 0x1
CMD_RX_POP  = 0x2
CMD_TXRX    = 0x3
CMD_CONFIG  = 0xE
CMD_RESET   = 0xF

DR_WIDTH = 32

_UART_ID = 0x454A5552  # ASCII "EJUR"


class EjtagUartController:
    """Controller for the fcapz_ejtaguart JTAG-to-UART bridge."""

    UART_ID     = _UART_ID
    CMD_NOP     = CMD_NOP
    CMD_TX_PUSH = CMD_TX_PUSH
    CMD_RX_POP  = CMD_RX_POP
    CMD_TXRX    = CMD_TXRX
    CMD_CONFIG  = CMD_CONFIG
    CMD_RESET   = CMD_RESET

    def __init__(self, transport: Transport, chain: int = 4):
        self._transport = transport
        self._chain = chain

    def connect(self) -> dict:
        """Open transport, select chain, probe identity.

        Probe is 10 scans: 5 for UART_ID + 5 for VERSION.

        Returns:
            dict with keys:

            * ``"id"`` (int) — bridge identity word; always ``0x454A5552``
              (ASCII ``"EJUR"``) for a valid core.
            * ``"version"`` (int) — packed version register
              ``{major[15:0], minor[15:0]}``.

        Raises:
            RuntimeError: If the identity word does not match (wrong chain,
                wrong bitstream, or core not loaded).
            RuntimeError: If the transport cannot connect.
        """
        self._transport.select_chain(self._chain)
        old_ready_probe_addr = getattr(self._transport, "ready_probe_addr", None)
        if hasattr(self._transport, "ready_probe_addr"):
            # The generic hw_server ready probe uses the 49-bit ELA/EIO
            # register protocol. EJTAG-UART uses a 32-bit streaming DR, so
            # readiness must be checked with CMD_CONFIG after connect().
            self._transport.ready_probe_addr = None
        try:
            self._transport.connect()
        finally:
            if hasattr(self._transport, "ready_probe_addr"):
                self._transport.ready_probe_addr = old_ready_probe_addr
        self._transport.select_chain(self._chain)
        try:
            deadline = time.monotonic() + float(
                getattr(self._transport, "ready_probe_timeout", 2.0)
            )
            while True:
                uid = self._config_read_u32(0x00)
                if uid == self.UART_ID or time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
            if uid != self.UART_ID:
                # XSDB can occasionally return one stale DR result right
                # after a fresh session/chain selection. Flush a couple of
                # harmless NOP scans and retry the identity probe once.
                self._scan(cmd=self.CMD_NOP)
                self._scan(cmd=self.CMD_NOP)
                uid = self._config_read_u32(0x00)
            if uid != self.UART_ID:
                raise RuntimeError(f"Bad UART ID: 0x{uid:08X}")
            version = self._config_read_u32(0x04)
            return {"id": uid, "version": version}
        except Exception:
            self._transport.close()
            raise

    def attach(self) -> dict:
        """Like :meth:`connect` but assume the transport is already open.

        Restores JTAG chain 1 before returning. Does not close the transport on
        failure.
        """
        self._transport.select_chain(self._chain)
        try:
            uid = self._config_read_u32(0x00)
            if uid != self.UART_ID:
                self._scan(cmd=self.CMD_NOP)
                self._scan(cmd=self.CMD_NOP)
                uid = self._config_read_u32(0x00)
            if uid != self.UART_ID:
                raise RuntimeError(f"Bad UART ID: 0x{uid:08X}")
            version = self._config_read_u32(0x04)
            return {"id": uid, "version": version}
        finally:
            self._transport.select_chain(1)

    def close(self) -> None:
        """Reset bridge, drain to ensure reset completes, close transport.

        The FIFO reset counter runs on TCK, so we must send follow-up
        scans to clock it down.  4 NOP scans guarantees the 4-cycle
        fifo_rst hold period has elapsed.
        """
        self._scan(cmd=self.CMD_RESET)
        for _ in range(4):
            self._scan(cmd=self.CMD_NOP)
        self._transport.close()

    def send(self, data: bytes, timeout: float = 30.0) -> None:
        """Send bytes to UART TX. Blocks until all accepted or timeout.

        Uses tx_free (conservative lower bound of TX FIFO free space)
        to batch scans safely.  tx_free may undercount by a few entries
        due to CDC synchronizer delay, so this never overflows the FIFO.

        Raises TimeoutError if the TX FIFO stays full for longer than
        *timeout* seconds (default 30s).
        """
        offset = 0
        deadline = time.monotonic() + timeout
        while offset < len(data):
            status, tx_free, _ = self._scan(cmd=self.CMD_NOP)
            self._check_errors(status)
            if tx_free == 0:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"UART TX stalled: {offset}/{len(data)} bytes sent"
                    )
                time.sleep(0.001)
                continue
            # Reset deadline on progress
            deadline = time.monotonic() + timeout
            # Send up to tx_free bytes, one per scan
            batch_size = min(tx_free, len(data) - offset)
            scans = []
            for i in range(batch_size):
                bits = (self.CMD_TX_PUSH << 28) | data[offset + i]
                scans.append((bits, DR_WIDTH))
            self._transport.raw_dr_scan_batch(scans, chain=self._chain)
            offset += batch_size

    def recv(self, count: int = 0, timeout: float = 1.0) -> bytes:
        """Receive bytes from UART RX using pipelined RX_POP.

        count=0 means return all currently available bytes.
        Raises RuntimeError on RX_OVERFLOW or FRAME_ERR.

        Timeout is an idle timeout: the deadline resets each time a
        byte is successfully received.  A slow-but-steady stream will
        not time out mid-message.

        Pipelined: each RX_POP scan returns the result of the
        previous pop, so back-to-back pops achieve 1 byte per scan
        (~1.5 KB/s) instead of 2 scans per byte.
        """
        result = bytearray()
        deadline = time.monotonic() + timeout
        popping = False  # True if we have an outstanding RX_POP
        while True:
            if not popping:
                # Prime: issue first RX_POP
                self._scan(cmd=self.CMD_RX_POP)
                popping = True
                continue

            # Pipeline: issue next RX_POP (or NOP to drain) while
            # reading the result of the previous pop
            need_more = (count == 0) or (len(result) < count - 1)
            next_cmd = self.CMD_RX_POP if need_more else self.CMD_NOP
            status, _, rx_byte = self._scan(cmd=next_cmd)
            self._check_errors(status)

            if status & 0x10:  # RX_VALID
                result.append(rx_byte)
                deadline = time.monotonic() + timeout  # reset on progress
                if count > 0 and len(result) >= count:
                    return bytes(result[:count])
            else:
                # FIFO was empty on the previous pop
                popping = False
                if count == 0:
                    return bytes(result)
                if time.monotonic() >= deadline:
                    return bytes(result)
                time.sleep(0.001)

    def recv_line(self, timeout: float = 1.0) -> str:
        """Receive until newline or timeout (idle timeout).

        Uses non-pipelined RX_POP+NOP (2 scans/byte) to avoid
        consuming the byte after the newline.  Deadline resets on
        each successful byte.

        Raises RuntimeError on RX_OVERFLOW or FRAME_ERR.
        """
        result = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._scan(cmd=self.CMD_RX_POP)
            status, _, rx_byte = self._scan(cmd=self.CMD_NOP)
            self._check_errors(status)
            if status & 0x10:  # RX_VALID
                result.append(rx_byte)
                deadline = time.monotonic() + timeout  # reset on progress
                if rx_byte == ord('\n'):
                    return result.decode("utf-8", errors="replace")
            else:
                time.sleep(0.001)
        return result.decode("utf-8", errors="replace")

    def status(self) -> dict:
        """Non-destructive status poll. Does not consume RX data.

        rx_ready: True if RX FIFO has data waiting (use this for polling).
        tx_free:  conservative lower bound of TX FIFO free space.
        """
        st, tx_free, _ = self._scan(cmd=self.CMD_NOP)
        return {
            "rx_ready":    bool(st & 0x01),        # bit 24: FIFO has data
            "tx_full":     bool(st & 0x20),         # bit 29
            "rx_overflow": bool(st & 0x40),         # bit 30: sticky
            "frame_error": bool(st & 0x80),         # bit 31: sticky
            "tx_free":     tx_free,
        }

    # -- internal --

    @staticmethod
    def _check_errors(status: int) -> None:
        """Raise if sticky UART errors are set in status byte."""
        if status & 0x40:
            raise RuntimeError("UART RX FIFO overflow (data lost)")
        if status & 0x80:
            raise RuntimeError("UART framing/parity error")

    def _scan(self, cmd: int = 0, tx_byte: int = 0) -> tuple[int, int, int]:
        """One 32-bit DR scan. Returns (status_8bit, tx_free, rx_byte)."""
        bits = ((cmd & 0xF) << 28) | (tx_byte & 0xFF)
        out = self._transport.raw_dr_scan(bits, DR_WIDTH, chain=self._chain)
        rx_byte = out & 0xFF
        tx_free = (out >> 8) & 0xFF
        status  = (out >> 24) & 0xFF
        return status, tx_free, rx_byte

    def _config_read_u32(self, base_addr: int) -> int:
        """Read 32-bit config register (4 CONFIG scans + 1 NOP drain).

        Pipelined: CONFIG[i] returns byte from CONFIG[i-1].
        Scan 1: CONFIG addr+0 -> no result
        Scan 2: CONFIG addr+1 -> byte 0
        Scan 3: CONFIG addr+2 -> byte 1
        Scan 4: CONFIG addr+3 -> byte 2
        Scan 5: NOP            -> byte 3
        """
        self._scan(cmd=self.CMD_CONFIG, tx_byte=base_addr + 0)  # prime
        _, _, b0 = self._scan(cmd=self.CMD_CONFIG, tx_byte=base_addr + 1)
        _, _, b1 = self._scan(cmd=self.CMD_CONFIG, tx_byte=base_addr + 2)
        _, _, b2 = self._scan(cmd=self.CMD_CONFIG, tx_byte=base_addr + 3)
        _, _, b3 = self._scan(cmd=self.CMD_NOP)  # drain
        return b0 | (b1 << 8) | (b2 << 16) | (b3 << 24)
