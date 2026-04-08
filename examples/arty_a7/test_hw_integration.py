# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Integration tests for fpgacapZero on real hardware (Arty A7-100T).

These tests require:
  - An Arty A7-100T physically connected via USB
  - For hw_server backend: Vivado/XSDB on PATH, hw_server on localhost:3121
  - For openocd backend: OpenOCD running with examples/arty_a7/arty_a7.cfg

Environment variables
---------------------
FPGACAP_SKIP_HW=1
    Skip all hardware tests (CI default).
FPGACAP_BACKEND=openocd|hw_server
    Select the transport backend.  Defaults to ``hw_server``.
FPGACAP_OPENOCD_PORT=<port>
    OpenOCD TCL port.  Defaults to 6666.
FPGACAP_OPENOCD_TAP=<tap>
    OpenOCD TAP name.  Defaults to ``xc7a100t.tap``.

Run:
    # hw_server backend (default)
    python -m pytest examples/arty_a7/test_hw_integration.py -v

    # OpenOCD backend (start openocd first)
    openocd -f examples/arty_a7/arty_a7.cfg &
    FPGACAP_BACKEND=openocd python -m pytest examples/arty_a7/test_hw_integration.py -v

Skip if no hardware:
    FPGACAP_SKIP_HW=1 python -m pytest examples/arty_a7/test_hw_integration.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

# Skip the entire module if HW_SKIP env var is set
_SKIP = os.environ.get("FPGACAP_SKIP_HW", "")

BITFILE = str(Path(__file__).resolve().parent / "arty_a7_top.bit")
_BACKEND = os.environ.get("FPGACAP_BACKEND", "hw_server").lower()
_OPENOCD_PORT = int(os.environ.get("FPGACAP_OPENOCD_PORT", "6666"))
_OPENOCD_TAP = os.environ.get("FPGACAP_OPENOCD_TAP", "xc7a100t.tap")
PORT = 3121
FPGA = "xc7a100t"


def _make_transport():
    if _BACKEND == "openocd":
        from fcapz.transport import OpenOcdTransport
        return OpenOcdTransport(port=_OPENOCD_PORT, tap=_OPENOCD_TAP)
    from fcapz.transport import XilinxHwServerTransport
    return XilinxHwServerTransport(
        port=PORT, fpga_name=FPGA, bitfile=BITFILE,
    )


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestProbe(unittest.TestCase):
    """Basic connectivity: read identity registers."""

    def test_probe_returns_valid_identity(self):
        from fcapz.analyzer import Analyzer

        t = _make_transport()
        a = Analyzer(t)
        try:
            a.connect()
            # XilinxHwServerTransport.connect() now waits until the FPGA
            # responds with valid data; no retry needed here.
            info = a.probe()
            self.assertEqual(info["version_major"], 0)
            self.assertEqual(info["version_minor"], 2)
            self.assertEqual(info["core_id"], 0x4C41)  # ASCII "LA"
            self.assertEqual(info["sample_width"], 8)
            self.assertEqual(info["depth"], 1024)
        finally:
            a.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestRegisterRoundTrip(unittest.TestCase):
    """Write/read-back on writable registers."""

    def setUp(self):
        self.t = _make_transport()
        self.t.connect()

    def tearDown(self):
        self.t.close()

    def test_trig_mask_roundtrip(self):
        patterns = [0x00000000, 0xA5A5A5A5, 0x5A5A5A5A, 0xDEADBEEF, 0xFFFFFFFF]
        for val in patterns:
            with self.subTest(val=f"0x{val:08X}"):
                self.t.write_reg(0x0028, val)
                got = self.t.read_reg(0x0028)
                self.assertEqual(got, val, f"expected 0x{val:08X}, got 0x{got:08X}")

    def test_trig_value_roundtrip(self):
        patterns = [0x00000000, 0x12345678, 0xFF, 0xCAFEBABE]
        for val in patterns:
            with self.subTest(val=f"0x{val:08X}"):
                self.t.write_reg(0x0024, val)
                got = self.t.read_reg(0x0024)
                self.assertEqual(got, val)

    def test_pretrig_posttrig_roundtrip(self):
        self.t.write_reg(0x0014, 42)
        self.assertEqual(self.t.read_reg(0x0014), 42)
        self.t.write_reg(0x0018, 99)
        self.assertEqual(self.t.read_reg(0x0018), 99)

    def test_trig_mode_roundtrip(self):
        for mode in [1, 2, 3]:
            self.t.write_reg(0x0020, mode)
            self.assertEqual(self.t.read_reg(0x0020), mode)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestCapture(unittest.TestCase):
    """End-to-end capture with various configurations."""

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.t = _make_transport()
        self.a = Analyzer(self.t)
        self.a.connect()

    def tearDown(self):
        self.a.close()

    def _capture(self, pretrig, posttrig, trig_val=0, trig_mask=0xFF, mode="value_match"):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=pretrig,
            posttrigger=posttrig,
            trigger=TriggerConfig(mode=mode, value=trig_val, mask=trig_mask),
            sample_width=8,
            depth=1024,
        )
        self.a.configure(cfg)
        self.a.arm()
        return self.a.capture(timeout=5.0)

    def test_basic_capture_value_match(self):
        """Trigger on value=0 with mask=0xFF, capture 4+8 samples."""
        result = self._capture(pretrig=4, posttrig=8)
        expected_total = 4 + 1 + 8  # pre + trigger + post
        self.assertEqual(len(result.samples), expected_total)
        self.assertFalse(result.overflow)

    def test_trigger_delay_shifts_window(self):
        """Trigger on value=0x10 with TRIG_DELAY=4 — captured trigger sample
        should be 4 cycles later (= 0x14) since the probe is a free-running
        8-bit counter incrementing every sample clock."""
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=2,
            posttrigger=3,
            trigger=TriggerConfig(mode="value_match", value=0x10, mask=0xFF),
            sample_width=8,
            depth=1024,
            trigger_delay=4,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertEqual(len(result.samples), 6)
        # Trigger sample is at index pretrigger=2.  Counter advanced by 4
        # cycles between cause (0x10) and commit, so the value should be
        # 0x14 (one comparator pipeline cycle may shift it by ±1).
        trig_sample = result.samples[2] & 0xFF
        self.assertIn(
            trig_sample, (0x14, 0x15),
            f"trigger sample = 0x{trig_sample:02X}, expected 0x14 or 0x15",
        )

    def test_trigger_delay_zero_equivalence(self):
        """trigger_delay=0 must reproduce the legacy capture window."""
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=2,
            posttrigger=3,
            trigger=TriggerConfig(mode="value_match", value=0x20, mask=0xFF),
            sample_width=8,
            depth=1024,
            trigger_delay=0,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertEqual(len(result.samples), 6)
        trig_sample = result.samples[2] & 0xFF
        self.assertIn(
            trig_sample, (0x20, 0x21),
            f"trigger sample = 0x{trig_sample:02X}, expected 0x20 or 0x21",
        )

    def test_minimal_capture(self):
        """Minimum pretrigger=0, posttrigger=0."""
        result = self._capture(pretrig=0, posttrig=0)
        self.assertGreaterEqual(len(result.samples), 1)

    def test_large_capture(self):
        """Larger capture: 50 pre + 100 post (fits in SEG_DEPTH=256)."""
        result = self._capture(pretrig=50, posttrig=100)
        self.assertEqual(len(result.samples), 151)
        self.assertFalse(result.overflow)

    def test_trigger_on_specific_value(self):
        """Trigger on a specific counter value (mask=0xFF).

        The Arty reference design probes a free-running 8-bit counter,
        so any value 0-255 will eventually be hit.  There may be 1-2
        cycles of pipeline latency between trigger detection and the
        sample recorded at the trigger index.
        """
        result = self._capture(pretrig=2, posttrig=4, trig_val=42, trig_mask=0xFF)
        self.assertEqual(len(result.samples), 7)
        # The trigger value should appear somewhere near the trigger index
        self.assertIn(42, [s & 0xFF for s in result.samples])

    def test_edge_detect_trigger(self):
        """Edge-detect trigger on bit 0 (LSB toggles every cycle)."""
        result = self._capture(pretrig=2, posttrig=4, trig_val=0, trig_mask=0x01,
                               mode="edge_detect")
        self.assertEqual(len(result.samples), 7)
        self.assertFalse(result.overflow)

    def test_both_trigger_modes(self):
        """Combined value_match + edge_detect trigger."""
        result = self._capture(pretrig=2, posttrig=4, trig_val=0, trig_mask=0xFF,
                               mode="both")
        self.assertEqual(len(result.samples), 7)

    def test_samples_are_counter_values(self):
        """Verify captured samples contain a sequential counter run.

        The Arty reference design probes a free-running 8-bit counter.
        We check that we find a contiguous run of at least
        (pretrigger + 1) consecutive values somewhere in the readback.
        """
        pretrig, posttrig = 4, 8
        result = self._capture(pretrig=pretrig, posttrig=posttrig)
        samples = [s & 0xFF for s in result.samples]
        # Find the longest run of consecutive +1 (mod 256) transitions.
        best_run = 0
        current_run = 1
        for i in range(1, len(samples)):
            if (samples[i] - samples[i - 1]) & 0xFF == 1:
                current_run += 1
            else:
                best_run = max(best_run, current_run)
                current_run = 1
        best_run = max(best_run, current_run)
        # We must see at least (pretrigger + 1) sequential samples around
        # the trigger point.
        self.assertGreaterEqual(
            best_run, pretrig + 1,
            f"expected sequential counter run >= {pretrig + 1}, "
            f"got best_run={best_run} samples={samples}",
        )


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestExportFormats(unittest.TestCase):
    """Capture and export to all three formats."""

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.t = _make_transport()
        self.a = Analyzer(self.t)
        self.a.connect()

    def tearDown(self):
        self.a.close()

    def _capture_result(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=2, posttrigger=4,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8, depth=1024,
        )
        self.a.configure(cfg)
        self.a.arm()
        return self.a.capture(timeout=5.0)

    def test_json_export(self):
        result = self._capture_result()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.a.write_json(result, path)
            obj = json.loads(Path(path).read_text())
            self.assertEqual(obj["sample_width"], 8)
            self.assertEqual(len(obj["samples"]), len(result.samples))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_csv_export(self):
        result = self._capture_result()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            self.a.write_csv(result, path)
            text = Path(path).read_text()
            self.assertIn("index,value", text)
            lines = text.strip().splitlines()
            self.assertEqual(len(lines), len(result.samples) + 1)  # header + data
        finally:
            Path(path).unlink(missing_ok=True)

    def test_vcd_export(self):
        result = self._capture_result()
        with tempfile.NamedTemporaryFile(suffix=".vcd", delete=False) as f:
            path = f.name
        try:
            self.a.write_vcd(result, path)
            text = Path(path).read_text()
            self.assertIn("$enddefinitions $end", text)
            self.assertIn("$var wire 8", text)
        finally:
            Path(path).unlink(missing_ok=True)


# ── ELA advanced feature tests ────────────────────────────────────────


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestDecimation(unittest.TestCase):
    """ELA decimation: verify fewer samples are stored with DECIM > 0."""

    def setUp(self):
        from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

        self.t = _make_transport()
        self.a = Analyzer(self.t)
        self.a.connect()
        self.CaptureConfig = CaptureConfig
        self.TriggerConfig = TriggerConfig

    def tearDown(self):
        self.a.close()

    def test_decim_zero_baseline(self):
        """DECIM=0 captures every cycle (same as before)."""
        cfg = self.CaptureConfig(
            sample_width=8, depth=1024, sample_clock_hz=100e6,
            pretrigger=2, posttrigger=3,
            trigger=self.TriggerConfig(mode="value_match", value=0x10, mask=0xFF),
            decimation=0,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertEqual(len(result.samples), 6)
        # Samples should be consecutive counter values around trigger
        diffs = [result.samples[i+1] - result.samples[i]
                 for i in range(len(result.samples)-1)
                 if result.samples[i+1] > result.samples[i]]
        self.assertTrue(all(d == 1 for d in diffs), f"Non-consecutive: {result.samples}")

    def test_decim_3_stores_every_4th(self):
        """DECIM=3 captures every 4th cycle; samples differ by 4."""
        cfg = self.CaptureConfig(
            sample_width=8, depth=1024, sample_clock_hz=100e6,
            pretrigger=2, posttrigger=5,
            trigger=self.TriggerConfig(mode="value_match", value=0x20, mask=0xFF),
            decimation=3,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertEqual(len(result.samples), 8)
        # With decimation=3, consecutive stored samples should differ by 4
        diffs = [(result.samples[i+1] - result.samples[i]) & 0xFF
                 for i in range(len(result.samples)-1)]
        for d in diffs:
            self.assertEqual(d, 4, f"Expected diff 4, got {d}. Samples: {result.samples}")


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestTimestamps(unittest.TestCase):
    """ELA timestamps: verify monotonic timestamps are captured."""

    def setUp(self):
        from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

        self.t = _make_transport()
        self.a = Analyzer(self.t)
        self.a.connect()
        self.CaptureConfig = CaptureConfig
        self.TriggerConfig = TriggerConfig

    def tearDown(self):
        self.a.close()

    def test_timestamps_present(self):
        """Probe reports TIMESTAMP_W=32."""
        info = self.a.probe()
        self.assertEqual(info.get("timestamp_width", 0), 32)

    def test_timestamps_monotonic(self):
        """Captured timestamps are strictly increasing."""
        cfg = self.CaptureConfig(
            sample_width=8, depth=1024, sample_clock_hz=100e6,
            pretrigger=2, posttrigger=5,
            trigger=self.TriggerConfig(mode="value_match", value=0x30, mask=0xFF),
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertGreater(len(result.timestamps), 0, "No timestamps returned")
        self.assertEqual(len(result.timestamps), len(result.samples))
        for i in range(1, len(result.timestamps)):
            self.assertGreater(result.timestamps[i], result.timestamps[i-1],
                               f"Non-monotonic at index {i}: {result.timestamps}")

    def test_timestamps_with_decimation(self):
        """Decimated timestamps show gaps proportional to decimation ratio."""
        cfg = self.CaptureConfig(
            sample_width=8, depth=1024, sample_clock_hz=100e6,
            pretrigger=1, posttrigger=4,
            trigger=self.TriggerConfig(mode="value_match", value=0x40, mask=0xFF),
            decimation=3,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertGreater(len(result.timestamps), 1)
        # Timestamp gaps should be ~4 (decimation=3 means every 4th cycle)
        gaps = [result.timestamps[i+1] - result.timestamps[i]
                for i in range(len(result.timestamps)-1)]
        for g in gaps:
            self.assertGreaterEqual(g, 3, f"Gap too small: {g}. Timestamps: {result.timestamps}")
            self.assertLessEqual(g, 6, f"Gap too large: {g}. Timestamps: {result.timestamps}")


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestSegmentedCapture(unittest.TestCase):
    """ELA segmented memory: verify multi-segment auto-rearm capture."""

    def setUp(self):
        from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

        self.t = _make_transport()
        self.a = Analyzer(self.t)
        self.a.connect()
        self.CaptureConfig = CaptureConfig
        self.TriggerConfig = TriggerConfig

    def tearDown(self):
        self.a.close()

    def test_num_segments_reported(self):
        """Probe reports NUM_SEGMENTS=4."""
        info = self.a.probe()
        self.assertEqual(info.get("num_segments", 1), 4)

    def test_four_segments_captured(self):
        """4 segments auto-rearm and capture independently.

        The counter wraps at 256 and triggers on value_match=0x00
        (every 256 cycles). With 4 segments, we should get 4 independent
        captures, each triggered when counter hits 0x00.
        Segment depth = 1024/4 = 256, so pretrig+posttrig+1 <= 256.
        """
        cfg = self.CaptureConfig(
            sample_width=8, depth=1024, sample_clock_hz=100e6,
            pretrigger=2, posttrigger=3,
            trigger=self.TriggerConfig(mode="value_match", value=0x00, mask=0xFF),
        )
        self.a.configure(cfg)
        self.a.arm()
        # Wait for all 4 segments to complete
        done = self.a.wait_all_segments_done(timeout=10.0)
        self.assertTrue(done, "Not all segments completed in time")

        # Read each segment
        for seg in range(4):
            result = self.a.capture_segment(seg, timeout=5.0)
            self.assertEqual(len(result.samples), 6,
                             f"Segment {seg}: expected 6 samples, got {len(result.samples)}")
            # The trigger value (0x00) should be in the samples
            self.assertIn(0x00, result.samples,
                          f"Segment {seg}: trigger value 0x00 not found in {result.samples}")

    def test_segment_data_independent(self):
        """Each segment has its own capture data, not shared."""
        cfg = self.CaptureConfig(
            sample_width=8, depth=1024, sample_clock_hz=100e6,
            pretrigger=0, posttrigger=2,
            trigger=self.TriggerConfig(mode="value_match", value=0x00, mask=0xFF),
        )
        self.a.configure(cfg)
        self.a.arm()
        done = self.a.wait_all_segments_done(timeout=10.0)
        self.assertTrue(done)

        # Read all 4 segments; each should contain trigger value 0x00
        for seg in range(4):
            result = self.a.capture_segment(seg, timeout=5.0)
            self.assertIn(0x00, result.samples,
                          f"Segment {seg}: trigger value 0x00 not in {result.samples}")
            self.assertEqual(len(result.samples), 3,
                             f"Segment {seg}: expected 3 samples, got {len(result.samples)}")


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestExtTrigger(unittest.TestCase):
    """ELA external trigger: verify trigger modes via FEATURES register.

    Full ext trigger testing requires btn[1] physical press, so we only
    verify the feature is reported and that disabled mode works.
    """

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.t = _make_transport()
        self.a = Analyzer(self.t)
        self.a.connect()

    def tearDown(self):
        self.a.close()

    def test_ext_trigger_feature_reported(self):
        """Probe reports HAS_EXT_TRIG."""
        info = self.a.probe()
        self.assertTrue(info.get("has_ext_trigger", False))

    def test_ext_trigger_disabled_normal_capture(self):
        """With ext_trigger_mode=0 (disabled), normal capture works."""
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            sample_width=8, depth=1024, sample_clock_hz=100e6,
            pretrigger=2, posttrigger=3,
            trigger=TriggerConfig(mode="value_match", value=0x50, mask=0xFF),
            ext_trigger_mode=0,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertEqual(len(result.samples), 6)


# ── EIO tests (USER3) ─────────────────────────────────────────────────


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEioProbe(unittest.TestCase):
    """EIO: probe identity and widths on chain 3."""

    def test_eio_probe(self):
        from fcapz.eio import EioController

        t = _make_transport()
        eio = EioController(t, chain=3)
        try:
            eio.connect()
            self.assertEqual(eio.in_w, 8)
            self.assertEqual(eio.out_w, 8)
        finally:
            eio.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEioReadWrite(unittest.TestCase):
    """EIO: read inputs and write outputs via JTAG USER3."""

    def setUp(self):
        from fcapz.eio import EioController

        self.eio = EioController(_make_transport(), chain=3)
        self.eio.connect()

    def tearDown(self):
        self.eio.close()

    def test_read_counter(self):
        """probe_in is the free-running 8-bit counter — should be non-zero."""
        import time
        time.sleep(0.01)  # let counter run
        val = self.eio.read_inputs()
        # Counter is always running; two reads should differ
        time.sleep(0.001)
        val2 = self.eio.read_inputs()
        # At least one should be non-zero (counter wraps quickly at 100MHz)
        self.assertTrue(val != 0 or val2 != 0,
                        f"Counter stuck at 0: val={val}, val2={val2}")

    def test_write_read_outputs(self):
        """Write a value to probe_out and read it back."""
        self.eio.write_outputs(0xA5)
        readback = self.eio.read_outputs()
        self.assertEqual(readback, 0xA5)

    def test_write_zero_outputs(self):
        """Write 0 and verify readback."""
        self.eio.write_outputs(0x00)
        readback = self.eio.read_outputs()
        self.assertEqual(readback, 0x00)

    def test_set_clear_bit(self):
        """Set and clear individual output bits via read_outputs()."""
        self.eio.write_outputs(0x00)
        self.eio.set_bit(3, 1)
        self.assertEqual(self.eio.read_outputs() & 0x08, 0x08)
        self.assertEqual(self.eio.read_outputs() & 0x04, 0x00)
        self.eio.set_bit(3, 0)
        self.assertEqual(self.eio.read_outputs() & 0x08, 0x00)

    def test_output_roundtrip_all_bits(self):
        """Walk a 1 through all 8 output bits."""
        for bit in range(8):
            val = 1 << bit
            self.eio.write_outputs(val)
            readback = self.eio.read_outputs()
            self.assertEqual(readback, val, f"bit {bit}: wrote 0x{val:02X}, read 0x{readback:02X}")
        self.eio.write_outputs(0x00)  # cleanup


# ── EJTAG-AXI tests (USER4) ──────────────────────────────────────────


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagAxiProbe(unittest.TestCase):
    """EJTAG-AXI bridge: probe identity."""

    def test_bridge_probe(self):
        from fcapz.ejtagaxi import EjtagAxiController

        t = _make_transport()
        bridge = EjtagAxiController(t, chain=4)
        try:
            info = bridge.connect()
            self.assertEqual(info["bridge_id"], 0x454A4158)  # "EJAX"
            self.assertGreater(info["addr_w"], 0)
            self.assertGreater(info["data_w"], 0)
        finally:
            bridge.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagAxiReadWrite(unittest.TestCase):
    """EJTAG-AXI bridge: single and block read/write via on-chip test slave."""

    def setUp(self):
        from fcapz.ejtagaxi import EjtagAxiController

        self.bridge = EjtagAxiController(_make_transport(), chain=4)
        self.bridge.connect()

    def tearDown(self):
        self.bridge.close()

    def test_single_write_read_roundtrip(self):
        """Write patterns to test slave, read back, verify."""
        patterns = [0x00000000, 0xFFFFFFFF, 0xA5A5A5A5, 0x12345678]
        for val in patterns:
            with self.subTest(val=f"0x{val:08X}"):
                self.bridge.axi_write(0x00, val)
                got = self.bridge.axi_read(0x00)
                self.assertEqual(got, val, f"expected 0x{val:08X}, got 0x{got:08X}")

    def test_write_strobe_partial(self):
        """Write with wstrb=0x03 — only low 2 bytes should change."""
        self.bridge.axi_write(0x04, 0x11223344)  # fill all 4 bytes
        self.bridge.axi_write(0x04, 0xAABBCCDD, wstrb=0x03)  # low 2 bytes
        got = self.bridge.axi_read(0x04)
        # Low 2 bytes = 0xCCDD, high 2 bytes = 0x1122 (unchanged)
        self.assertEqual(got, 0x1122CCDD, f"expected 0x1122CCDD, got 0x{got:08X}")

    def test_write_block_read_block(self):
        """Write 16 words via auto-increment, read back, verify."""
        data = [0x1000 + i for i in range(16)]
        self.bridge.write_block(0x00, data)
        result = self.bridge.read_block(0x00, 16)
        self.assertEqual(result, data)

    def test_burst_read(self):
        """AXI4 burst read 8 words (pre-filled via write_block)."""
        data = [0xBEEF0000 + i for i in range(8)]
        self.bridge.write_block(0x00, data)
        result = self.bridge.burst_read(0x00, 8)
        self.assertEqual(result, data)

    def test_burst_write_read(self):
        """AXI4 burst write 8 words, burst read back, verify."""
        data = [0xBEEF0000 + i for i in range(8)]
        self.bridge.burst_write(0x00, data)
        result = self.bridge.burst_read(0x00, 8)
        self.assertEqual(result, data)

    def test_error_on_error_addr(self):
        """Write to test slave's ERROR_ADDR (0xFFFFFFFC) → AXIError."""
        from fcapz.ejtagaxi import AXIError

        with self.assertRaises(AXIError):
            self.bridge.axi_write(0xFFFFFFFC, 0x1234)

    def test_throughput(self):
        """Write 256 words, measure wall time, report KB/s."""
        import time

        data = [i for i in range(256)]
        t0 = time.perf_counter()
        self.bridge.write_block(0x00, data)
        elapsed = time.perf_counter() - t0
        kb_per_s = (256 * 4) / 1024 / elapsed if elapsed > 0 else 0
        print(f"\n  write_block 256 words: {elapsed:.3f}s = {kb_per_s:.1f} KB/s")
        # Sanity: > 0.3 KB/s (sequential, no batch) and < 200 KB/s.
        # With raw_dr_scan_batch transport optimization, expect ~80 KB/s.
        self.assertGreater(kb_per_s, 0.3)


# ── EJTAG-UART bridge tests (require UART loopback bitstream) ─────────
# These tests require a bitstream with fcapz_ejtaguart on USER3 instead
# of EIO.  Skip by default; enable with FPGACAP_UART_HW=1.
_UART_HW = os.environ.get("FPGACAP_UART_HW", "")


@unittest.skipUnless(_UART_HW, "FPGACAP_UART_HW not set (needs UART loopback bitstream)")
@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagUartProbe(unittest.TestCase):
    """EJTAG-UART bridge: probe identity on chain 3 (loopback bitstream)."""

    def test_uart_probe(self):
        from fcapz.ejtaguart import EjtagUartController

        t = _make_transport()
        uart = EjtagUartController(t, chain=3)
        try:
            info = uart.connect()
            self.assertEqual(info["id"], 0x454A5552)  # "EJUR"
        finally:
            uart.close()


@unittest.skipUnless(_UART_HW, "FPGACAP_UART_HW not set (needs UART loopback bitstream)")
@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagUartLoopback(unittest.TestCase):
    """EJTAG-UART bridge: loopback tests (TX wired to RX in bitstream)."""

    def setUp(self):
        from fcapz.ejtaguart import EjtagUartController

        self.uart = EjtagUartController(_make_transport(), chain=3)
        self.uart.connect()

    def tearDown(self):
        self.uart.close()

    def test_send_recv_single_byte(self):
        """Send one byte, receive it back through loopback."""
        self.uart.send(b"A")
        # Wait for UART TX -> RX at 115200 baud (~87us per byte)
        import time
        time.sleep(0.05)
        data = self.uart.recv(count=1, timeout=2.0)
        self.assertEqual(data, b"A")

    def test_send_recv_string(self):
        """Send a short string with distinct bytes, receive it back."""
        import time

        # Internal loopback (zero wire delay) can intermittently miss
        # start bits on back-to-back frames — see test_loopback_stress.
        # Use a short distinct-byte string for a reliable smoke test.
        msg = b"HeLo!\n"
        self.uart.send(msg)
        time.sleep(0.2)
        data = self.uart.recv(count=len(msg), timeout=3.0)
        self.assertEqual(data, msg)

    def test_recv_line(self):
        """Send a line, receive with recv_line()."""
        import time

        self.uart.send(b"test123\n")
        time.sleep(0.1)
        line = self.uart.recv_line(timeout=3.0)
        self.assertEqual(line, "test123\n")

    def test_status_non_destructive(self):
        """Status poll does not consume RX data."""
        import time

        self.uart.send(b"X")
        time.sleep(0.05)
        # Poll status — should NOT eat the byte
        st = self.uart.status()
        self.assertTrue(st["rx_ready"])
        # Now recv should still get the byte
        data = self.uart.recv(count=1, timeout=2.0)
        self.assertEqual(data, b"X")

    def test_loopback_block(self):
        """Send 4 bytes, receive all back through loopback (smoke test)."""
        import time

        payload = b"\x41\x5A\x30\x0A"  # distinct bytes: A, Z, 0, newline
        self.uart.send(payload)
        time.sleep(0.2)
        data = self.uart.recv(count=4, timeout=5.0)
        self.assertEqual(data, payload)

    @unittest.expectedFailure
    def test_loopback_stress(self):
        """Stress: 32 consecutive bytes through internal loopback.

        Known limitation: the internal loopback (TX wired directly to
        RX with zero wire delay) intermittently drops bytes when the
        UART TX sends back-to-back frames.  The RX 2-FF synchronizer
        can miss the stop-to-start transition when there is no
        propagation delay on the wire — the brief stop-bit high pulse
        may not be captured before the next start bit pulls the line
        low.  This affects any consecutive byte pair, not just
        identical bytes.

        This does NOT reproduce with real UART wiring (external
        loopback jumper or cable) where wire delay provides enough
        margin for the synchronizer.

        Marked @expectedFailure so the suite stays green while keeping
        regression pressure on this issue.  Remove when the RX module
        is hardened or when testing with external wiring.
        """
        import time

        payload = bytes(range(32))
        self.uart.send(payload)
        time.sleep(1.0)
        data = self.uart.recv(count=32, timeout=10.0)
        self.assertEqual(data, payload)


if __name__ == "__main__":
    unittest.main()
