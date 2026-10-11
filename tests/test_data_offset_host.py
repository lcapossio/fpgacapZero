# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host side of the ELA's DATA_OFFSET: window reads past the 16-bit address
space (or the core manager's 0xF000) are paged."""

from __future__ import annotations

import unittest

from fcapz import _version_tuple
from fcapz.analyzer import CORE_MANAGER_CORE_ID, Analyzer, CaptureConfig, TriggerConfig
from fcapz.transport import DataWindowError, Transport, check_data_window

_DATA_OFFSET = 0x00F4
_CAP_DATA_OFFSET = 1 << 20


class ElaWindowTransport(Transport):
    """An ELA whose DATA / timestamp windows are modelled word by word.

    Window word ``k`` (DATA words first, then timestamp words) reads as
    ``0x1000_0000 + k``.  DATA_OFFSET moves every window read by its value,
    as the RTL does.
    """

    def __init__(self, *, sample_w, depth, timestamp_w=0, data_offset=True,
                 managed=False, burst=False):
        self.sample_w, self.depth, self.timestamp_w = sample_w, depth, timestamp_w
        self.words_per_sample = (sample_w + 31) // 32
        self.ts_words = (timestamp_w + 31) // 32
        self.total_words = depth * (self.words_per_sample + self.ts_words)
        caps = 0x3_01FF | (1 << 19) | (_CAP_DATA_OFFSET if data_offset else 0)
        self.regs = {
            0x0000: ((_version_tuple()[0] & 0xFF) << 24)
            | ((_version_tuple()[1] & 0xFF) << 16) | 0x4C41,
            0x0008: 0x4,  # STATUS: done
            0x000C: sample_w,
            0x0010: depth,
            0x001C: depth,  # CAPTURE_LEN
            0x003C: 0x0001_0164,
            0x00A4: 1,
            0x00B8: 1,
            0x00C4: timestamp_w,
            0x00E0: caps,
        }
        self.manager = {}
        if managed:
            self.manager = {
                0xF000: ((_version_tuple()[0] & 0xFF) << 24)
                | ((_version_tuple()[1] & 0xFF) << 16) | CORE_MANAGER_CORE_ID,
                0xF004: 1, 0xF008: 0, 0xF00C: 0, 0xF010: 0x3, 0xF014: 0,
                0xF01C: int(burst),  # DESC_CAPS
            }
        self.offset = 0
        self.offsets_written: list[int] = []
        self.window_reads: list[tuple[int, int]] = []
        self.burst_reads = 0

    def connect(self):
        return None

    def close(self):
        return None

    def select_chain(self, chain):
        return None

    def raw_dr_scan(self, bits, width, *, chain=None):
        return bits

    def _window_word(self, addr: int) -> int:
        k = (addr - 0x0100) // 4 + self.offset
        return 0x1000_0000 + k if k < self.total_words else 0

    def read_reg(self, addr):
        if addr in self.manager:
            return self.manager[addr]
        if addr == _DATA_OFFSET:
            return self.offset
        if addr >= 0x0100:
            return self._window_word(addr)
        return self.regs.get(addr, 0)

    def write_reg(self, addr, value):
        if addr in self.manager:
            self.manager[addr] = value
        elif addr == _DATA_OFFSET:
            if self.regs[0x00E0] & _CAP_DATA_OFFSET:
                self.offset = value
                self.offsets_written.append(value)
        elif addr < 0x0100:
            self.regs[addr] = value

    def read_block(self, addr, words):
        if addr == 0x0100:  # a burst on the real transports: no window limit
            self.burst_reads += 1
            return [self._window_word(addr + 4 * i) for i in range(words)]
        return self.read_window_block(addr, words)

    def read_window_block(self, addr, words):
        check_data_window(addr, words, self.data_window_end)
        self.window_reads.append((addr, words))
        return [self._window_word(addr + 4 * i) for i in range(words)]


def capture(transport, *, instance=None):
    analyzer = Analyzer(transport, instance=instance)
    analyzer.connect()
    analyzer.configure(CaptureConfig(
        pretrigger=1, posttrigger=transport.depth - 2,
        trigger=TriggerConfig(mode="value_match", value=7, mask=0xFF),
        sample_width=transport.sample_w, depth=transport.depth,
    ))
    return analyzer.capture(timeout=0.01)


class DataOffsetTests(unittest.TestCase):
    def test_managed_slot_past_manager_block_is_paged(self):
        """8-bit x 16384 behind a manager, no burst: the window would end at
        0x10100, past 0xF000.  Each page sets DATA_OFFSET; it ends at 0."""
        t = ElaWindowTransport(sample_w=8, depth=16384, managed=True)
        result = capture(t, instance=0)
        page = (0xF000 - 0x0100) // 4
        self.assertEqual(result.samples, [(0x1000_0000 + k) & 0xFF for k in range(16384)])
        self.assertEqual(t.offsets_written, [0, 0, page, 0])  # configure, pages, restore
        self.assertEqual(t.offset, 0)

    def test_window_that_fits_is_not_paged(self):
        t = ElaWindowTransport(sample_w=8, depth=1024, managed=True)
        capture(t, instance=0)
        self.assertEqual(t.offsets_written, [0])  # configure only

    def test_core_without_data_offset_still_refuses(self):
        t = ElaWindowTransport(sample_w=8, depth=16384, managed=True, data_offset=False)
        with self.assertRaises(DataWindowError):
            capture(t, instance=0)
        self.assertEqual(t.offsets_written, [])

    def test_wide_managed_window_pages_through_the_window_reader(self):
        """256-bit samples read with read_window_block, never read_block(0x0100)."""
        t = ElaWindowTransport(sample_w=256, depth=2048, managed=True)
        result = capture(t, instance=0)
        self.assertEqual(len(result.samples), 2048)
        self.assertEqual(result.samples[-1] & 0xFFFF_FFFF, 0x1000_0000 + 2047 * 8)
        self.assertTrue(all(addr == 0x0100 for addr, _ in t.window_reads))
        self.assertEqual(t.burst_reads, 0)
        self.assertEqual(t.offset, 0)

    def test_timestamps_past_the_manager_block_are_paged(self):
        """8-bit x 16384 with 32-bit timestamps behind a manager, no burst: the
        timestamp window starts at 0x10100, which no 16-bit address reaches."""
        t = ElaWindowTransport(sample_w=8, depth=16384, timestamp_w=32, managed=True)
        result = capture(t, instance=0)
        self.assertEqual(result.timestamps[:2], [0x1000_0000 + 16384, 0x1000_0000 + 16385])
        self.assertEqual(result.timestamps[-1], 0x1000_0000 + 2 * 16384 - 1)
        page = (0xF000 - 0x0100) // 4
        self.assertIn(16384, t.offsets_written)
        self.assertIn(16384 + page, t.offsets_written)
        self.assertEqual(t.offset, 0)
        self.assertEqual(t.burst_reads, 0)

    def test_offset_restored_when_a_page_fails(self):
        t = ElaWindowTransport(sample_w=256, depth=2048, managed=True)

        def broken(addr, words):
            raise RuntimeError("cable unplugged")

        t.read_window_block = broken  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            capture(t, instance=0)
        self.assertEqual(t.offset, 0)


if __name__ == "__main__":
    unittest.main()
