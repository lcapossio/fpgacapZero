# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

from fcapz.ejtagaxi import (
    AXIError,
    CMD_STREAM_RSTART,
    DR_WIDTH,
    STREAM_SLOT_W,
    EjtagAxiController,
)
from fcapz.transport import XilinxHwServerTransport

from test_ejtagaxi import RESP_OKAY, RESP_SLVERR, FakeBridgeTransport


def mem_word(addr: int) -> int:
    return ((addr >> 2) * 0x9E3779B1 ^ 0xA5A50000) & 0xFFFFFFFF


class StreamBridgeTransport(FakeBridgeTransport):
    """FakeBridgeTransport plus the streaming read of fcapz_ejtagaxi.

    Models the TCK-side contract: slot 0 of a stream scan is the header
    (valid=0, words still owed), a word counts as delivered only when its
    whole slot is shifted out, any TDI 1 in stream mode is a CMD_RESET, and
    the range response is presented on the first normal scan after the
    stream ends.  Stream mode ends at the UPDATE of a scan whose header
    read 0.
    """

    def __init__(self, *, stream: bool = True, **kw):
        super().__init__(**kw)
        if stream:
            self._config_regs[0x002C] |= 1 << 24
        self.stream_mode = False
        self.stream_left = 0
        self.stream_addr = 0
        self.stream_resp = RESP_OKAY
        self.latency_slots = 0      # empty slots at the start of every stream
        self._latency_left = 0
        self.drop_words: list[int] = []   # stream word indexes lost once
        self.phantom_once = False   # one empty slot reads as a word
        self.rstart_log: list[tuple[int, int]] = []
        self.capture_widths: list[int] = []

    def _stream_word(self, addr: int) -> int:
        return 0 if self._is_error_addr(addr) else mem_word(addr)

    def _abort(self) -> None:
        self.stream_mode = False
        self._exec(0xF, 0, 0, 0)  # CMD_RESET

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        if self.stream_mode:
            assert width == DR_WIDTH
            out = (self.stream_left & 0xFFFFFFFF) << 1
            if bits:
                self._abort()
            elif self.stream_left == 0:
                self._end_stream()
            return out
        cmd = (bits >> 68) & 0xF
        if cmd == CMD_STREAM_RSTART:
            out = self._encode_out(self.prev_rdata, 0, self.prev_resp,
                                   0x1 if self.prev_valid else 0)
            self.scan_log.append(cmd)
            addr = bits & 0xFFFFFFFC
            count = (bits >> 32) & 0xFFFFFFFF
            self.rstart_log.append((addr, count))
            self.prev_valid = False
            self.stream_mode = count != 0
            self.stream_left = count
            self.stream_addr = addr
            self._latency_left = self.latency_slots
            bad = any(self._is_error_addr(addr + 4 * i) for i in range(count))
            self.stream_resp = RESP_SLVERR if bad else RESP_OKAY
            if count == 0:
                self.prev_valid = True
                self.prev_resp = RESP_OKAY
            return out
        return super().raw_dr_scan(bits, width, chain=chain)

    def _end_stream(self) -> None:
        self.stream_mode = False
        self.prev_valid = True
        self.prev_rdata = 0
        self.prev_resp = self.stream_resp
        if self.stream_resp != RESP_OKAY:
            self.error_sticky = True

    def raw_dr_capture(self, width: int, *, chain: int | None = None, tdi: int = 0) -> int:
        self.capture_widths.append(width)
        if not self.stream_mode:
            return 0
        out = (self.stream_left & 0xFFFFFFFF) << 1
        hdr_zero = self.stream_left == 0
        for k in range(1, width // STREAM_SLOT_W):
            if self._latency_left:
                self._latency_left -= 1
                if self.phantom_once:
                    self.phantom_once = False
                    out |= ((0x12345678 << 1) | 1) << (k * STREAM_SLOT_W)
                continue
            if not self.stream_left:
                continue
            index = (self.stream_addr - self.rstart_log[-1][0]) // 4
            word = self._stream_word(self.stream_addr)
            self.stream_addr += 4
            self.stream_left -= 1
            if index in self.drop_words:
                # Delivered by the bridge, lost on the way: the next header
                # shows one word fewer than the host expects.
                self.drop_words.remove(index)
                continue
            out |= ((word << 1) | 1) << (k * STREAM_SLOT_W)
        if tdi:
            self._abort()
        elif hdr_zero:
            self._end_stream()
        return out


class StreamReadTests(unittest.TestCase):

    def _make(self, **kw) -> tuple[EjtagAxiController, StreamBridgeTransport]:
        t = StreamBridgeTransport(**kw)
        ctrl = EjtagAxiController(t, chain=4)
        info = ctrl.connect()
        self.assertEqual(info["stream"], kw.get("stream", True))
        return ctrl, t

    def test_reads_a_range_over_several_scans(self):
        ctrl, t = self._make()
        words = ctrl.stream_read(0x1000, 5000, slots_per_scan=1000)
        self.assertEqual(words, [mem_word(0x1000 + 4 * i) for i in range(5000)])
        self.assertEqual(t.rstart_log, [(0x1000, 5000)])
        self.assertGreaterEqual(len(t.capture_widths), 6)
        self.assertTrue(all(w % STREAM_SLOT_W == 0 for w in t.capture_widths))

    def test_last_scan_is_sized_to_the_words_left(self):
        ctrl, t = self._make()
        ctrl.stream_read(0x0, 10)
        # One scan for the words, then the header-only scan that confirms them.
        self.assertEqual(t.capture_widths,
                         [(10 + 1 + ctrl._STREAM_SLACK) * STREAM_SLOT_W, STREAM_SLOT_W])

    def test_empty_slots_while_the_axi_side_catches_up(self):
        ctrl, t = self._make()
        t.latency_slots = 2500
        words = ctrl.stream_read(0x200, 3000, slots_per_scan=1000)
        self.assertEqual(words, [mem_word(0x200 + 4 * i) for i in range(3000)])

    def test_a_lost_word_rereads_the_whole_range(self):
        # The aborted stream's AXI response was never read, so none of its
        # words are trusted: the retry starts at the base address again.
        ctrl, t = self._make()
        t.drop_words = [1234]
        words = ctrl.stream_read(0x4000, 3000, slots_per_scan=1000)
        self.assertEqual(words, [mem_word(0x4000 + 4 * i) for i in range(3000)])
        self.assertEqual(t.rstart_log, [(0x4000, 3000), (0x4000, 3000)])

    def test_error_before_a_lost_word_is_not_lost_by_the_retry(self):
        # Word 2 has an AXI error and is confirmed before word 25 is lost;
        # restarting after word 2 would never report the error.
        ctrl, t = self._make()
        t.error_addr = 0x8
        t.drop_words = [25]
        with self.assertRaises(AXIError):
            ctrl.stream_read(0x0, 50, slots_per_scan=10)

    def test_lost_final_response_is_not_success(self):
        # All words confirmed, then the scan that should carry the range's
        # (error) response fails on the transport: retry, never return.
        ctrl, t = self._make()
        t.error_addr = 0x10
        state = {"armed": True}
        real_scan = t.raw_dr_scan

        def flaky_scan(bits, width, *, chain=None):
            ended = not t.stream_mode and t.rstart_log
            if ended and state["armed"] and t.prev_valid:
                state["armed"] = False
                raise OSError("injected: response scan lost")
            return real_scan(bits, width, chain=chain)

        t.raw_dr_scan = flaky_scan
        with self.assertRaises(AXIError):
            ctrl.stream_read(0x0, 10)
        self.assertFalse(state["armed"])

    def test_exhausted_retries_leave_the_bridge_in_normal_mode(self):
        ctrl, t = self._make()

        def always_lose(*a, **kw):
            t.drop_words = [0]
            return StreamBridgeTransport.raw_dr_capture(t, *a, **kw)

        t.raw_dr_capture = always_lose
        with self.assertRaises(AXIError):
            ctrl.stream_read(0x0, 100, slots_per_scan=10, retries=1)
        self.assertFalse(t.stream_mode)
        # Left in stream mode, SET_ADDR would act as an abort and the reads
        # would start at address 0 (regs 0..3) instead of 0x10.
        t.regs = [0x1000 + i for i in range(16)]
        self.assertEqual(ctrl.read_block(0x10, 4), [0x1004, 0x1005, 0x1006, 0x1007])

    def test_a_lost_word_in_the_last_scan_is_caught(self):
        ctrl, t = self._make()
        t.drop_words = [9]
        words = ctrl.stream_read(0x0, 10)
        self.assertEqual(words, [mem_word(4 * i) for i in range(10)])
        self.assertEqual(len(t.rstart_log), 2)

    def test_a_phantom_word_restarts_the_stream(self):
        ctrl, t = self._make()
        t.latency_slots = 5
        t.phantom_once = True
        words = ctrl.stream_read(0x800, 2000, slots_per_scan=500)
        self.assertEqual(words, [mem_word(0x800 + 4 * i) for i in range(2000)])
        self.assertEqual(len(t.rstart_log), 2)

    def test_gives_up_after_the_retry_budget(self):
        ctrl, t = self._make()
        t.drop_words = [10]
        t.latency_slots = 0

        def always_lose(*a, **kw):
            t.drop_words = [0]
            return StreamBridgeTransport.raw_dr_capture(t, *a, **kw)

        t.raw_dr_capture = always_lose
        with self.assertRaises(AXIError):
            ctrl.stream_read(0x0, 100, retries=2)
        self.assertEqual(len(t.rstart_log), 3)

    def test_error_response_in_the_range_raises(self):
        ctrl, t = self._make()
        t.error_addr = 0x108
        with self.assertRaises(AXIError):
            ctrl.stream_read(0x100, 8)
        # Usable again afterwards.
        self.assertEqual(ctrl.stream_read(0x200, 4),
                         [mem_word(0x200 + 4 * i) for i in range(4)])

    def test_bridge_without_streaming_is_rejected(self):
        ctrl, _ = self._make(stream=False)
        self.assertFalse(ctrl.has_stream)
        with self.assertRaises(RuntimeError):
            ctrl.stream_read(0x0, 4)

    def test_argument_checks(self):
        ctrl, _ = self._make()
        with self.assertRaises(ValueError):
            ctrl.stream_read(0x2, 4)
        with self.assertRaises(ValueError):
            ctrl.stream_read(0x0, 0)
        with self.assertRaises(ValueError):
            ctrl.stream_read(0xFFFF_FFF0, 8)


class HwServerCaptureParseTests(unittest.TestCase):
    """XilinxHwServerTransport.raw_dr_capture: xsdb ``run -hex`` is
    little-endian bytes, two hex digits each (checked on silicon through
    BYPASS: bits 6 and 39 of a 40-bit capture print as 4000000080)."""

    def _transport(self, reply: str, extra_bits: int = 0, position: str = "tdo"):
        t = XilinxHwServerTransport.__new__(XilinxHwServerTransport)
        t._active_chain = 4
        t.use_register_ir = True
        t.dr_extra_bits = extra_bits
        t.dr_extra_position = position
        t._stderr_lines = []
        t.sent = []

        def send(tcl, **kw):
            t.sent.append(tcl)
            return reply

        t._send = send
        return t

    def test_hex_reply_is_little_endian_bytes(self):
        t = self._transport("4000000080\n")
        self.assertEqual(t.raw_dr_capture(40), (1 << 39) | (1 << 6))
        self.assertIn("drshift -state DRUPDATE -capture -tdi 0 40", t.sent[0])
        self.assertIn("-register user4", t.sent[0])

    def test_tdi_one_and_bypass_padding(self):
        # One BYPASS bit on the TDO side: 41 bits shifted, the first dropped.
        t = self._transport("000000000001 0001\n", extra_bits=1)
        self.assertEqual(t.raw_dr_capture(40, tdi=1), 1 << 39)
        self.assertIn("-tdi 1 41", t.sent[0])

    def test_missing_reply_raises(self):
        t = self._transport("error: no target\n")
        with self.assertRaises(RuntimeError):
            t.raw_dr_capture(40)


if __name__ == "__main__":
    unittest.main()
