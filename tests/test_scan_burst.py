# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Burst readout over raw scan batches (``_ScanBurstMixin``) and its
OpenOCD Tcl rendering.  No hardware: the burst engine is modelled in Python.
"""

from __future__ import annotations

import re
import unittest

from fcapz.transport import (
    BurstIntegrityError,
    BurstUnavailableError,
    OpenOcdTransport,
    Transport,
    _ScanBurstMixin,
)


class _BurstEngineModel:
    """Python model of the ELA burst engine seen through raw scans.

    A ``BURST_PTR`` write (49-bit frame to 0x002C) arms the engine; the first
    256-bit capture after it is the priming scan and returns junk, each later
    capture returns the next packed group of elements.
    """

    def __init__(self, samples, timestamps=(), sample_w=8, ts_w=32):
        self.samples = list(samples)
        self.timestamps = list(timestamps)
        self.sample_w = sample_w
        self.ts_w = ts_w
        self.ptr_writes: list[int] = []
        self.irs: list[int] = []
        self._pos = None
        self._ts = False

    def run(self, ops):
        out = []
        for op in ops:
            if op[0] == "ir":
                self.irs.append(op[1])
            elif op[0] == "dr":
                _, value, width, capture = op
                if width == 49 and value >> 48 == 1 and (value >> 32) & 0xFFFF == 0x2C:
                    self.ptr_writes.append(value & 0xFFFFFFFF)
                    self._ts = bool(value & 0x80000000)
                    self._pos = -1  # next capture primes
                    continue
                if width == 256 and self._pos is not None:
                    if self._pos < 0:
                        word = (1 << 256) - 1  # priming junk
                        self._pos = 0
                    else:
                        word = self._pack()
                    if capture:
                        out.append(word)
        return out

    def _pack(self):
        data, w = (self.timestamps, self.ts_w) if self._ts else (self.samples, self.sample_w)
        per = 256 // w
        word = 0
        for i in range(per):
            idx = self._pos + i
            if idx < len(data):
                word |= (data[idx] & ((1 << w) - 1)) << (i * w)
        self._pos += per
        return word


class _FakeScanTransport(_ScanBurstMixin, Transport):
    def __init__(self, model, *, burst=True, single_chain=True, sample_w=8):
        self.model = model
        self.burst = burst
        self.single_chain_burst = single_chain
        self.burst_data_chain = 2
        self._active_chain = 1
        self.sample_w = sample_w
        self.window_reads: list[tuple[int, int]] = []

    def connect(self):
        pass

    def close(self):
        pass

    def read_reg(self, addr):
        return self.sample_w if addr == 0x000C else 0

    def write_reg(self, addr, value):
        pass

    def read_block(self, addr, words):
        burst = self._burst_block_or_none(addr, words)
        if burst is not None:
            return burst
        return self.read_window_block(addr, words)

    def read_window_block(self, addr, words):
        self.window_reads.append((addr, words))
        return [0] * words

    def _run_scans(self, ops):
        return self.model.run(ops)


class ScanBurstMixinTests(unittest.TestCase):
    def test_narrow_burst_unpacks_samples_in_order(self):
        samples = [(i * 7) & 0xFF for i in range(100)]
        t = _FakeScanTransport(_BurstEngineModel(samples))
        self.assertEqual(t.read_block(0x0100, 100), samples)
        self.assertEqual(t.model.ptr_writes, [0])

    def test_odd_sample_width_packs_without_gaps(self):
        samples = [(i * 37) & 0x7F for i in range(80)]
        model = _BurstEngineModel(samples, sample_w=7)
        t = _FakeScanTransport(model, sample_w=7)
        self.assertEqual(t.read_block(0x0100, 80), samples)

    def test_burst_off_reads_the_window(self):
        t = _FakeScanTransport(_BurstEngineModel([1, 2, 3]), burst=False)
        t.read_block(0x0100, 3)
        self.assertEqual(t.window_reads, [(0x0100, 3)])
        self.assertEqual(t.model.ptr_writes, [])

    def test_wide_core_leaves_read_block_to_the_window(self):
        t = _FakeScanTransport(_BurstEngineModel([1]), sample_w=64)
        t.read_block(0x0100, 4)
        self.assertEqual(t.window_reads, [(0x0100, 4)])

    def test_non_data_address_reads_the_window(self):
        t = _FakeScanTransport(_BurstEngineModel([1]))
        t.read_block(0x0000, 2)
        self.assertEqual(t.window_reads, [(0x0000, 2)])

    def test_wide_sample_block_splits_words(self):
        samples = [(0xA5 << 40) | i for i in range(10)]
        model = _BurstEngineModel(samples, sample_w=48)
        t = _FakeScanTransport(model, sample_w=48)
        words = t.read_sample_block(0x0100, 10, 48)
        self.assertEqual(len(words), 20)
        self.assertEqual(words[0], 0)
        self.assertEqual(words[1], 0xA500)
        self.assertEqual(words[2], 1)

    def test_sample_block_unavailable_without_burst(self):
        t = _FakeScanTransport(_BurstEngineModel([1]), burst=False)
        with self.assertRaises(BurstUnavailableError):
            t.read_sample_block(0x0100, 1, 64)
        with self.assertRaises(BurstUnavailableError):
            _FakeScanTransport(_BurstEngineModel([1])).read_sample_block(0x0200, 1, 64)

    def test_timestamp_burst_sets_ptr_bit31(self):
        ts = [1000 + i for i in range(12)]
        t = _FakeScanTransport(_BurstEngineModel([], timestamps=ts, ts_w=48))
        self.assertEqual(t.read_timestamp_block(0x0500, 12, 48), ts)
        self.assertEqual(t.model.ptr_writes, [0x80000000])
        self.assertEqual(t.read_timestamp_block_single_chain(0x0500, 12, 48), ts)

    def test_timestamp_without_burst_reads_the_window(self):
        t = _FakeScanTransport(_BurstEngineModel([]), burst=False)
        t.read_timestamp_block(0x0500, 4, 32)
        self.assertEqual(t.window_reads, [(0x0500, 4)])

    def test_two_chain_burst_scans_on_data_chain(self):
        t = _FakeScanTransport(_BurstEngineModel(list(range(40))), single_chain=False)
        t.read_block(0x0100, 40)
        self.assertEqual(t.model.irs, [1, 2])

    def test_single_chain_burst_stays_on_control_chain(self):
        t = _FakeScanTransport(_BurstEngineModel(list(range(40))))
        t.read_block(0x0100, 40)
        self.assertEqual(t.model.irs, [1, 1])

    def test_burst_start_sync_writes_ptr_twice(self):
        t = _FakeScanTransport(_BurstEngineModel(list(range(10))))
        t.burst_start_sync = True
        self.assertEqual(t.read_block(0x0100, 10), list(range(10)))
        self.assertEqual(t.model.ptr_writes, [0, 0])

    def test_short_burst_raises_integrity_error(self):
        t = _FakeScanTransport(_BurstEngineModel(list(range(64))))
        t._run_scans = lambda ops: [0]  # type: ignore[method-assign]
        with self.assertRaises(BurstIntegrityError):
            t.read_block(0x0100, 64)

    def test_failed_burst_names_the_build_options(self):
        t = _FakeScanTransport(_BurstEngineModel([1]))

        def boom(ops):
            raise RuntimeError("scan failed")

        t._run_scans = boom  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "--two-chain-burst.*--no-burst"):
            t.read_block(0x0100, 1)


class OpenOcdBurstTests(unittest.TestCase):
    """The Tcl that OpenOcdTransport sends for a burst."""

    def _transport(self, model, **kw):
        t = OpenOcdTransport(
            tap="MPFS095T.tap", ir_table=OpenOcdTransport.IR_TABLE_POLARFIRE, **kw
        )
        t.read_reg_stable = lambda addr: model.sample_w  # type: ignore[method-assign]
        scripts: list[str] = []

        def fake_cmd(tcl: str) -> str:
            scripts.append(tcl)
            ops = []
            for part in tcl.split("; "):
                m = re.fullmatch(r"irscan \S+ (\d+)", part)
                if m:
                    ir = int(m.group(1))
                    chain = {v: k for k, v in t.ir_table.items()}[ir]
                    ops.append(("ir", chain))
                    continue
                m = re.fullmatch(r"(lappend __fcapz_r \[)?drscan \S+ (\d+) 0x([0-9a-f]+)\]?", part)
                if m:
                    ops.append(("dr", int(m.group(3), 16), int(m.group(2)), bool(m.group(1))))
            return " ".join(f"{v:064x}" for v in model.run(ops))

        t._cmd = fake_cmd  # type: ignore[method-assign]
        return t, scripts

    def test_burst_is_off_by_default(self):
        self.assertFalse(OpenOcdTransport().burst)

    def test_burst_runs_as_one_script(self):
        samples = [(i * 3) & 0xFF for i in range(64)]
        model = _BurstEngineModel(samples)
        t, scripts = self._transport(model, burst=True)
        self.assertEqual(t.read_block(0x0100, 64), samples)
        self.assertEqual(len(scripts), 1)
        script = scripts[0]
        self.assertTrue(script.startswith("set __fcapz_r {}; irscan MPFS095T.tap 32; "))
        self.assertIn("drscan MPFS095T.tap 49 0x1002c00000000", script)
        self.assertIn("runtest 160", script)
        self.assertEqual(script.count("lappend __fcapz_r [drscan MPFS095T.tap 256 "), 3)
        self.assertTrue(script.endswith("set __fcapz_r"))

    def test_deep_burst_is_split_but_complete(self):
        samples = [i & 0xFF for i in range(1024 * 10)]
        model = _BurstEngineModel(samples)
        t, scripts = self._transport(model, burst=True)
        t._SCANS_PER_SCRIPT = 100
        self.assertEqual(t.read_block(0x0100, len(samples)), samples)
        self.assertGreater(len(scripts), 1)
        self.assertEqual(sum(s.count("lappend") for s in scripts), 321)

    def test_two_chain_burst_selects_user2(self):
        model = _BurstEngineModel(list(range(32)))
        t, scripts = self._transport(model, burst=True, single_chain_burst=False)
        t.read_block(0x0100, 32)
        self.assertIn("irscan MPFS095T.tap 33", scripts[0])

    def test_tcl_error_is_a_runtime_error_with_hint(self):
        t = OpenOcdTransport(tap="MPFS095T.tap", burst=True)
        t.read_reg_stable = lambda addr: 8  # type: ignore[method-assign]
        t._cmd = lambda tcl: "invalid command name"  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "OpenOCD scan batch failed.*--no-burst"):
            t.read_block(0x0100, 8)


if __name__ == "__main__":
    unittest.main()
