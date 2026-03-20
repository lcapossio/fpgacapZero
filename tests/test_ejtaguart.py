# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest
from typing import List

from host.fcapz.ejtaguart import (
    CMD_CONFIG,
    CMD_NOP,
    CMD_RESET,
    CMD_RX_POP,
    CMD_TX_PUSH,
    CMD_TXRX,
    DR_WIDTH,
    EjtagUartController,
    _UART_ID,
)
from host.fcapz.transport import Transport


# Config register byte map (matches RTL)
_UART_ID_BYTES = [
    (_UART_ID >>  0) & 0xFF,
    (_UART_ID >>  8) & 0xFF,
    (_UART_ID >> 16) & 0xFF,
    (_UART_ID >> 24) & 0xFF,
]

_VERSION = 0x0001_0000
_VERSION_BYTES = [
    (_VERSION >>  0) & 0xFF,
    (_VERSION >>  8) & 0xFF,
    (_VERSION >> 16) & 0xFF,
    (_VERSION >> 24) & 0xFF,
]


class FakeUartTransport(Transport):
    """Simulates the 32-bit pipelined protocol used by fcapz_ejtaguart.

    Internal TX/RX byte buffers simulate UART loopback: bytes pushed via
    TX_PUSH go into tx_buf (visible to external inspection). Bytes placed
    in rx_buf simulate external UART data arriving at RX.
    """

    TX_FIFO_DEPTH = 16

    def __init__(self):
        self.tx_buf: bytearray = bytearray()  # bytes sent via TX_PUSH
        self.rx_buf: bytearray = bytearray()  # bytes available for RX_POP
        self._active_chain: int = 1
        self._prev_rx_byte: int = 0
        self._prev_rx_valid: bool = False
        self._prev_config_byte: int = 0
        self._prev_config_valid: bool = False
        self._rx_overflow: bool = False
        self._frame_err: bool = False

    # --- Config register map ---
    _CONFIG_MAP: dict[int, int] = {}

    @classmethod
    def _init_config(cls):
        if cls._CONFIG_MAP:
            return
        # UART_ID at 0x00..0x03
        for i in range(4):
            cls._CONFIG_MAP[i] = _UART_ID_BYTES[i]
        # VERSION at 0x04..0x07
        for i in range(4):
            cls._CONFIG_MAP[4 + i] = _VERSION_BYTES[i]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    # --- Transport ABC implementation ---

    def connect(self) -> None:
        self._init_config()

    def close(self) -> None:
        pass

    def read_reg(self, addr: int) -> int:
        raise NotImplementedError("not used by UART controller")

    def write_reg(self, addr: int, value: int) -> None:
        raise NotImplementedError("not used by UART controller")

    def read_block(self, addr: int, words: int) -> List[int]:
        raise NotImplementedError("not used by UART controller")

    def select_chain(self, chain: int) -> None:
        self._active_chain = chain

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        assert width == DR_WIDTH

        # Decode shift-in
        tx_byte = bits & 0xFF
        cmd     = (bits >> 28) & 0xF

        # Build output from PREVIOUS result (pipelined)
        rx_byte_out = 0
        rx_valid_out = False

        if self._prev_config_valid:
            rx_byte_out = self._prev_config_byte
            rx_valid_out = True
        elif self._prev_rx_valid:
            rx_byte_out = self._prev_rx_byte
            rx_valid_out = True

        tx_free = max(0, self.TX_FIFO_DEPTH - len(self.tx_buf))
        if tx_free > 255:
            tx_free = 255

        rx_ready = len(self.rx_buf) > 0

        status_byte = (
            (int(rx_ready) << 0) |        # bit 24: RX_READY
            (int(rx_valid_out) << 4) |      # bit 28: RX_VALID
            (int(tx_free == 0) << 5) |      # bit 29: TX_FULL
            (int(self._rx_overflow) << 6) | # bit 30: RX_OVERFLOW
            (int(self._frame_err) << 7)     # bit 31: FRAME_ERR
        )

        out = (rx_byte_out & 0xFF) | ((tx_free & 0xFF) << 8) | ((status_byte & 0xFF) << 24)

        # Execute current command
        self._prev_rx_valid = False
        self._prev_config_valid = False

        if cmd == CMD_NOP:
            pass

        elif cmd == CMD_TX_PUSH:
            if len(self.tx_buf) < self.TX_FIFO_DEPTH:
                self.tx_buf.append(tx_byte)

        elif cmd == CMD_RX_POP:
            if self.rx_buf:
                self._prev_rx_byte = self.rx_buf.pop(0)
                self._prev_rx_valid = True

        elif cmd == CMD_TXRX:
            if len(self.tx_buf) < self.TX_FIFO_DEPTH:
                self.tx_buf.append(tx_byte)
            if self.rx_buf:
                self._prev_rx_byte = self.rx_buf.pop(0)
                self._prev_rx_valid = True

        elif cmd == CMD_CONFIG:
            self._init_config()
            addr = tx_byte & 0xFF
            self._prev_config_byte = self._CONFIG_MAP.get(addr, 0)
            self._prev_config_valid = True

        elif cmd == CMD_RESET:
            self.tx_buf.clear()
            self.rx_buf.clear()
            self._rx_overflow = False
            self._frame_err = False
            self._prev_rx_valid = False
            self._prev_config_valid = False

        return out

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        return [self.raw_dr_scan(bits, width, chain=chain) for bits, width in scans]


class EjtagUartTests(unittest.TestCase):

    def _make_ctrl(
        self, transport: FakeUartTransport | None = None
    ) -> tuple[EjtagUartController, FakeUartTransport]:
        t = transport or FakeUartTransport()
        ctrl = EjtagUartController(t, chain=4)
        ctrl.connect()
        return ctrl, t

    def test_probe_identity(self):
        t = FakeUartTransport()
        ctrl = EjtagUartController(t, chain=4)
        info = ctrl.connect()
        self.assertEqual(info["id"], _UART_ID)
        self.assertEqual(info["version"], _VERSION)

    def test_probe_bad_id_raises(self):
        t = FakeUartTransport()
        t._CONFIG_MAP = dict(t._CONFIG_MAP)
        # Corrupt byte 0
        t._CONFIG_MAP[0] = 0xFF
        t._CONFIG_MAP[1] = 0xFF
        t._CONFIG_MAP[2] = 0xFF
        t._CONFIG_MAP[3] = 0xFF
        ctrl = EjtagUartController(t, chain=4)
        with self.assertRaises(RuntimeError):
            ctrl.connect()

    def test_probe_retries_once_on_stale_uart_id(self):
        t = FakeUartTransport()
        ctrl = EjtagUartController(t, chain=4)
        vals = iter([0x004A5552, _UART_ID, _VERSION])
        ctrl._config_read_u32 = lambda addr: next(vals)
        info = ctrl.connect()
        self.assertEqual(info["id"], _UART_ID)
        self.assertEqual(info["version"], _VERSION)


    def test_send_single_byte(self):
        ctrl, t = self._make_ctrl()
        ctrl.send(b"\x42")
        self.assertIn(0x42, t.tx_buf)

    def test_recv_single_byte(self):
        ctrl, t = self._make_ctrl()
        t.rx_buf.extend(b"\x99")
        data = ctrl.recv(count=1, timeout=0.1)
        self.assertEqual(data, b"\x99")

    def test_nop_does_not_consume_rx(self):
        ctrl, t = self._make_ctrl()
        t.rx_buf.extend(b"\xAA\xBB")
        # Status poll (NOP) should not consume RX
        st = ctrl.status()
        self.assertTrue(st["rx_ready"])
        # RX buffer still has data
        self.assertEqual(len(t.rx_buf), 2)

    def test_tx_full_rejection(self):
        ctrl, t = self._make_ctrl()
        # Fill beyond capacity
        t.tx_buf.extend(bytes(t.TX_FIFO_DEPTH))
        st = ctrl.status()
        self.assertTrue(st["tx_full"])

    def test_tx_free_count(self):
        ctrl, t = self._make_ctrl()
        st = ctrl.status()
        self.assertEqual(st["tx_free"], t.TX_FIFO_DEPTH)
        # Push some bytes
        ctrl.send(b"\x01\x02\x03")
        st = ctrl.status()
        self.assertEqual(st["tx_free"], t.TX_FIFO_DEPTH - 3)

    def test_send_batch_respects_credit(self):
        ctrl, t = self._make_ctrl()
        data = bytes(range(10))
        ctrl.send(data)
        # All bytes should have been pushed
        self.assertEqual(len(t.tx_buf), 10)
        for i in range(10):
            self.assertEqual(t.tx_buf[i], i)

    def test_recv_line(self):
        ctrl, t = self._make_ctrl()
        t.rx_buf.extend(b"Hello\n")
        line = ctrl.recv_line(timeout=0.1)
        self.assertEqual(line, "Hello\n")

    def test_recv_timeout(self):
        ctrl, t = self._make_ctrl()
        t.rx_buf.extend(b"partial")
        data = ctrl.recv(count=100, timeout=0.05)
        self.assertEqual(data, b"partial")

    def test_reset_clears_errors(self):
        ctrl, t = self._make_ctrl()
        t._rx_overflow = True
        t._frame_err = True
        st = ctrl.status()
        self.assertTrue(st["rx_overflow"])
        self.assertTrue(st["frame_error"])
        # Close sends RESET
        ctrl.close()
        # Reconnect and check
        ctrl2 = EjtagUartController(t, chain=4)
        ctrl2.connect()
        st = ctrl2.status()
        self.assertFalse(st["rx_overflow"])
        self.assertFalse(st["frame_error"])

    def test_pipelined_rx_pop(self):
        ctrl, t = self._make_ctrl()
        t.rx_buf.extend(b"\xD1\xD2\xD3")
        # Pipelined: RX_POP, RX_POP, RX_POP, NOP
        ctrl._scan(cmd=CMD_RX_POP)
        _, _, b0 = ctrl._scan(cmd=CMD_RX_POP)
        _, _, b1 = ctrl._scan(cmd=CMD_RX_POP)
        _, _, b2 = ctrl._scan(cmd=CMD_NOP)
        self.assertEqual(b0, 0xD1)
        self.assertEqual(b1, 0xD2)
        self.assertEqual(b2, 0xD3)

    def test_chain_selection(self):
        t = FakeUartTransport()
        ctrl = EjtagUartController(t, chain=4)
        ctrl.connect()
        self.assertEqual(t._active_chain, 4)

    def test_connect_failure_closes_transport(self):
        """connect() must close the transport if ID check fails."""
        t = FakeUartTransport()
        # Corrupt the config map so ID check fails
        orig = dict(FakeUartTransport._CONFIG_MAP)
        FakeUartTransport._CONFIG_MAP[0] = 0xFF  # bad byte
        closed = []
        real_close = t.close
        t.close = lambda: (closed.append(True), real_close())
        try:
            ctrl = EjtagUartController(t, chain=4)
            with self.assertRaises(RuntimeError):
                ctrl.connect()
            self.assertTrue(closed, "transport.close() not called on probe failure")
        finally:
            FakeUartTransport._CONFIG_MAP.update(orig)

    def test_send_timeout_raises(self):
        """send() raises TimeoutError when TX FIFO stays full."""
        ctrl, t = self._make_ctrl()
        # Fill the TX FIFO
        t.tx_buf = bytearray(b'\x00' * FakeUartTransport.TX_FIFO_DEPTH)
        with self.assertRaises(TimeoutError):
            ctrl.send(b"X", timeout=0.05)

    def test_send_raises_on_uart_error(self):
        """send() raises RuntimeError on sticky UART errors."""
        ctrl, t = self._make_ctrl()
        t._frame_err = True
        with self.assertRaises(RuntimeError):
            ctrl.send(b"X")

    def test_recv_raises_on_uart_error(self):
        """recv() raises RuntimeError on sticky UART errors."""
        ctrl, t = self._make_ctrl()
        t.rx_buf = bytearray(b"A")
        t._rx_overflow = True
        with self.assertRaises(RuntimeError):
            ctrl.recv(count=1, timeout=0.1)

    def test_recv_idle_timeout_resets_on_progress(self):
        """recv() idle timeout resets on each received byte.

        Fake clock advances 0.006 per call, timeout=0.01.
        Original deadline = 0.016.  A arrives at ~0.012, resetting
        deadline to 0.022.  B is injected at fake_time >= 0.018
        (past 0.016 but before 0.022).  Without idle-reset the
        original deadline would expire before B; with it, B arrives
        in time.
        """
        from unittest.mock import patch

        ctrl, t = self._make_ctrl()
        t.rx_buf = bytearray(b"A")

        fake_time = [0.0]
        def fake_monotonic():
            fake_time[0] += 0.006
            return fake_time[0]

        # Inject B when fake clock passes 0.018 (after original
        # deadline 0.016 but before reset deadline 0.022)
        orig_scan = t.raw_dr_scan
        def injecting_scan(bits, width, *, chain=None):
            if fake_time[0] >= 0.018 and not t.rx_buf:
                t.rx_buf.extend(b"B")
            return orig_scan(bits, width, chain=chain)
        t.raw_dr_scan = injecting_scan

        with patch("host.fcapz.ejtaguart.time.monotonic", fake_monotonic), \
             patch("host.fcapz.ejtaguart.time.sleep"):
            data = ctrl.recv(count=2, timeout=0.01)

        self.assertEqual(data, b"AB")

    def test_close_drains_reset(self):
        """close() sends RESET + 4 NOP drain scans (5 scans total)."""
        scan_log: list[int] = []
        ctrl, t = self._make_ctrl()
        t.rx_buf = bytearray(b"leftover")

        # Spy on raw_dr_scan to count commands
        orig_scan = t.raw_dr_scan
        def logging_scan(bits, width, *, chain=None):
            cmd = (bits >> 28) & 0xF
            scan_log.append(cmd)
            return orig_scan(bits, width, chain=chain)
        t.raw_dr_scan = logging_scan

        ctrl.close()
        # Expect: 1 RESET (0xF) + 4 NOPs (0x0)
        self.assertEqual(scan_log[0], CMD_RESET)
        self.assertEqual(scan_log[1:], [CMD_NOP] * 4)
        self.assertEqual(len(scan_log), 5)


if __name__ == "__main__":
    unittest.main()
