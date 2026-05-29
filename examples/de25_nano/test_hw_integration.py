# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Integration tests for fpgacapZero on real hardware (Terasic DE25-Nano).

These tests require:
  - A DE25-Nano physically connected through the onboard USB-Blaster III
  - Quartus command-line tools on PATH
  - The DE25-Nano example bitstream built and programmed

Environment variables
---------------------
FPGACAP_SKIP_HW=1
    Skip all hardware tests.
FPGACAP_QUARTUS_HARDWARE=<name>
    Quartus cable name, for example ``DE25-Nano [USB-1]``.
FPGACAP_QUARTUS_DEVICE=<name>
    Optional Quartus device name. Defaults to ``auto``.
FPGACAP_QUARTUS_STP=<path>
    Optional path to quartus_stp.

Run:
    python -m pytest examples/de25_nano/test_hw_integration.py -v
"""

from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path

_SKIP = os.environ.get("FPGACAP_SKIP_HW", "")

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_DIR = Path(__file__).resolve().parent
BITFILE = str(_EXAMPLE_DIR / "output_files" / "de25_nano_fcapz.sof")
_HARDWARE = os.environ.get("FPGACAP_QUARTUS_HARDWARE")
_DEVICE_ENV = os.environ.get("FPGACAP_QUARTUS_DEVICE", "auto")
_DEVICE = None if _DEVICE_ENV.lower() in ("", "auto") else _DEVICE_ENV
_QUARTUS_STP = os.environ.get("FPGACAP_QUARTUS_STP") or None

ELA_CHAIN = 1
EIO_CHAIN = 3
AXI_CHAIN = 4
SAMPLE_CLOCK_HZ = 50_000_000
TRIGGER_DECISION_LATENCY = 1

_BITSTREAM_SOURCES = [
    _ROOT / "rtl" / "fcapz_version.vh",
    _ROOT / "rtl" / "reset_sync.v",
    _ROOT / "rtl" / "dpram.v",
    _ROOT / "rtl" / "trig_compare.v",
    _ROOT / "rtl" / "fcapz_ela.v",
    _ROOT / "rtl" / "fcapz_ela_intel.v",
    _ROOT / "rtl" / "fcapz_async_fifo.v",
    _ROOT / "rtl" / "fcapz_ejtagaxi.v",
    _ROOT / "rtl" / "fcapz_ejtagaxi_intel.v",
    _ROOT / "rtl" / "fcapz_eio.v",
    _ROOT / "rtl" / "fcapz_eio_intel.v",
    _ROOT / "rtl" / "jtag_reg_iface.v",
    _ROOT / "rtl" / "jtag_burst_read.v",
    _ROOT / "rtl" / "jtag_tap" / "jtag_tap_intel.v",
    _ROOT / "tb" / "axi4_test_slave.v",
    _EXAMPLE_DIR / "de25_nano_top.v",
    _EXAMPLE_DIR / "de25_nano.qsf",
    _EXAMPLE_DIR / "de25_nano.sdc",
    _EXAMPLE_DIR / "build_de25_nano.tcl",
]


def _check_bitstream_freshness() -> str | None:
    bitpath = Path(BITFILE)
    if not bitpath.exists():
        return f"bitfile not found: {BITFILE}"
    bit_mtime = bitpath.stat().st_mtime
    stale = [
        src.name
        for src in _BITSTREAM_SOURCES
        if src.exists() and src.stat().st_mtime > bit_mtime
    ]
    if stale:
        return (
            f"bitstream is stale; these sources are newer than {bitpath.name}: "
            f"{', '.join(stale)}. Re-run: python examples/de25_nano/build.py"
        )
    return None


_STALE_MSG = _check_bitstream_freshness()
if _STALE_MSG and not _SKIP:
    raise RuntimeError(_STALE_MSG)


def _make_transport():
    from fcapz.transport import QuartusStpTransport

    return QuartusStpTransport(
        hardware_name=_HARDWARE,
        device_name=_DEVICE,
        quartus_stp_path=_QUARTUS_STP,
    )


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestProbe(unittest.TestCase):
    """Basic connectivity: read identity registers."""

    def test_probe_returns_valid_identity(self):
        from fcapz import _version_tuple
        from fcapz.analyzer import Analyzer, ELA_CORE_ID

        a = Analyzer(_make_transport(), chain=ELA_CHAIN)
        try:
            a.connect()
            info = a.probe()
            major, minor, _patch = _version_tuple()
            self.assertEqual(info["version_major"], major)
            self.assertEqual(info["version_minor"], minor)
            self.assertEqual(info["core_id"], ELA_CORE_ID)
            self.assertEqual(info["sample_width"], 8)
            self.assertEqual(info["depth"], 1024)
            self.assertTrue(info["has_decimation"])
            self.assertTrue(info["has_ext_trigger"])
            self.assertEqual(info["timestamp_width"], 32)
            self.assertEqual(info["num_segments"], 4)
        finally:
            a.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestRegisterRoundTrip(unittest.TestCase):
    """Write/read-back on writable ELA registers."""

    def setUp(self):
        self.t = _make_transport()
        self.t.connect()
        self.t.select_chain(ELA_CHAIN)

    def tearDown(self):
        self.t.close()

    def test_trig_mask_roundtrip(self):
        for val in [0x00000000, 0xA5A5A5A5, 0x5A5A5A5A, 0xFFFFFFFF]:
            with self.subTest(val=f"0x{val:08X}"):
                self.t.write_reg(0x0028, val)
                self.assertEqual(self.t.read_reg(0x0028), val)

    def test_trig_value_roundtrip(self):
        for val in [0x00000000, 0x12345678, 0x000000FF, 0xCAFEBABE]:
            with self.subTest(val=f"0x{val:08X}"):
                self.t.write_reg(0x0024, val)
                self.assertEqual(self.t.read_reg(0x0024), val)

    def test_pretrig_posttrig_roundtrip(self):
        self.t.write_reg(0x0014, 42)
        self.t.write_reg(0x0018, 99)
        self.assertEqual(self.t.read_reg(0x0014), 42)
        self.assertEqual(self.t.read_reg(0x0018), 99)

    def test_trig_mode_roundtrip(self):
        for mode in [1, 2, 3]:
            with self.subTest(mode=mode):
                self.t.write_reg(0x0020, mode)
                self.assertEqual(self.t.read_reg(0x0020), mode)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestCapture(unittest.TestCase):
    """End-to-end capture with various configurations."""

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.a = Analyzer(_make_transport(), chain=ELA_CHAIN)
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
            sample_clock_hz=SAMPLE_CLOCK_HZ,
        )
        self.a.configure(cfg)
        self.a.arm()
        return self.a.capture(timeout=5.0)

    def test_basic_capture_value_match(self):
        result = self._capture(pretrig=4, posttrig=8)
        self.assertEqual(len(result.samples), 13)
        self.assertFalse(result.overflow)

    def test_trigger_delay_shifts_window(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=2,
            posttrigger=3,
            trigger=TriggerConfig(mode="value_match", value=0x10, mask=0xFF),
            sample_width=8,
            depth=1024,
            sample_clock_hz=SAMPLE_CLOCK_HZ,
            trigger_delay=4,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertEqual(len(result.samples), 6)
        self.assertIn(result.samples[2] & 0xFF, (0x14, 0x15))

    def test_minimal_capture(self):
        result = self._capture(pretrig=0, posttrig=0)
        self.assertGreaterEqual(len(result.samples), 1)

    def test_segment_depth_capture_pre8_post247(self):
        result = self._capture(pretrig=8, posttrig=247)
        self.assertEqual(len(result.samples), 256)
        self.assertFalse(result.overflow)

    def test_trigger_on_specific_value(self):
        result = self._capture(pretrig=2, posttrig=4, trig_val=42, trig_mask=0xFF)
        self.assertEqual(len(result.samples), 7)
        self.assertIn(42, [s & 0xFF for s in result.samples])

    def test_edge_detect_trigger(self):
        result = self._capture(
            pretrig=2,
            posttrig=4,
            trig_val=0,
            trig_mask=0x01,
            mode="edge_detect",
        )
        self.assertEqual(len(result.samples), 7)
        self.assertFalse(result.overflow)

    def test_both_trigger_modes(self):
        result = self._capture(
            pretrig=2,
            posttrig=4,
            trig_val=0,
            trig_mask=0xFF,
            mode="both",
        )
        self.assertEqual(len(result.samples), 7)

    def test_samples_are_counter_values(self):
        result = self._capture(pretrig=4, posttrig=8)
        samples = [s & 0xFF for s in result.samples]
        errors = [
            (i - 1, samples[i - 1], samples[i])
            for i in range(1, len(samples))
            if ((samples[i] - samples[i - 1]) & 0xFF) != 1
        ]
        self.assertEqual(errors, [], f"counter step errors in samples={samples}")


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestStartupArmAndHoldoff(unittest.TestCase):
    """Hardware validation for startup-arm and holdoff controls."""

    def setUp(self):
        from fcapz.analyzer import Analyzer
        from fcapz.eio import EioController

        self.t = _make_transport()
        self.a = Analyzer(self.t, chain=ELA_CHAIN)
        self.a.connect()
        self.eio = EioController(self.t, chain=EIO_CHAIN)
        self.eio.attach()
        self._set_eio_outputs(0)
        self.t.select_chain(ELA_CHAIN)

    def tearDown(self):
        try:
            self._set_eio_outputs(0)
        finally:
            self.a.close()

    def _set_eio_outputs(self, value: int) -> None:
        self.eio.write_outputs(value)
        self.assertEqual(self.eio.read_outputs(), value & 0xFF)
        time.sleep(0.001)

    def test_register_roundtrip(self):
        self.t.write_reg(0x00D8, 1)
        self.t.write_reg(0x00DC, 23)
        self.assertEqual(self.t.read_reg(0x00D8) & 0x1, 1)
        self.assertEqual(self.t.read_reg(0x00DC) & 0xFFFF, 23)
        self.t.write_reg(0x00D8, 0)
        self.t.write_reg(0x00DC, 0)

    def test_startup_arm_reset_rearms_deterministically(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0),
            sample_width=8,
            depth=1024,
            startup_arm=True,
            ext_trigger_mode=2,
        )
        self.a.configure(cfg)
        self.a.reset()

        status = self.t.read_reg(0x0008)
        self.assertTrue(status & 0x1, f"expected armed after RESET: 0x{status:08X}")
        self.assertFalse(status & 0x2, f"unexpected triggered: 0x{status:08X}")
        self.assertFalse(status & 0x4, f"unexpected done: 0x{status:08X}")

    def test_reset_without_startup_arm_stays_idle(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0),
            sample_width=8,
            depth=1024,
            startup_arm=False,
            ext_trigger_mode=2,
        )
        self.a.configure(cfg)
        self.a.reset()

        status = self.t.read_reg(0x0008)
        self.assertFalse(status & 0x1, f"expected idle after RESET: 0x{status:08X}")
        self.assertFalse(status & 0x2, f"unexpected triggered: 0x{status:08X}")
        self.assertFalse(status & 0x4, f"unexpected done: 0x{status:08X}")

    def test_trigger_holdoff_blocks_early_armed_edge_pulse(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0),
            sample_width=8,
            depth=1024,
            startup_arm=False,
            trigger_holdoff=4,
            ext_trigger_mode=2,
        )
        self.a.configure(cfg)
        self.a.reset()
        self._set_eio_outputs(1 << 5)
        self.t.select_chain(ELA_CHAIN)
        self.a.arm()

        self.assertFalse(self.a.wait_done(timeout=0.2, poll_interval=0.01))
        status = self.t.read_reg(0x0008)
        self.assertTrue(status & 0x1, f"expected still armed: 0x{status:08X}")
        self.assertFalse(status & 0x2, f"unexpected triggered: 0x{status:08X}")
        self.assertFalse(status & 0x4, f"unexpected done: 0x{status:08X}")

    def test_trigger_holdoff_allows_late_armed_edge_pulse(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0),
            sample_width=8,
            depth=1024,
            startup_arm=False,
            trigger_holdoff=4,
            ext_trigger_mode=2,
        )
        self.a.configure(cfg)
        self.a.reset()
        self._set_eio_outputs(1 << 6)
        self.t.select_chain(ELA_CHAIN)
        self.a.arm()

        result = self.a.capture(timeout=5.0)
        self.assertEqual(len(result.samples), 3)
        self.assertFalse(result.overflow)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestExportFormats(unittest.TestCase):
    """Capture and export to JSON, CSV, and VCD."""

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.a = Analyzer(_make_transport(), chain=ELA_CHAIN)
        self.a.connect()

    def tearDown(self):
        self.a.close()

    def _result(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            sample_width=8,
            depth=1024,
            sample_clock_hz=SAMPLE_CLOCK_HZ,
            pretrigger=2,
            posttrigger=3,
            trigger=TriggerConfig(mode="value_match", value=0x20, mask=0xFF),
        )
        self.a.configure(cfg)
        self.a.arm()
        return self.a.capture(timeout=5.0)

    def test_json_export(self):
        result = self._result()
        exported = self.a.export_json(result)
        self.assertEqual(exported["sample_width"], 8)
        self.assertEqual(len(exported["samples"]), len(result.samples))
        json.dumps(exported)

    def test_csv_export(self):
        text = self.a.export_csv_text(self._result())
        self.assertIn("index,value", text)

    def test_vcd_export(self):
        text = self.a.export_vcd_text(self._result())
        self.assertIn("$timescale", text)
        self.assertIn("$enddefinitions", text)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestDecimation(unittest.TestCase):
    """ELA decimation: stored samples advance by decimation+1."""

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.a = Analyzer(_make_transport(), chain=ELA_CHAIN)
        self.a.connect()

    def tearDown(self):
        self.a.close()

    def test_decim_3_stores_every_fourth_sample(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            sample_width=8,
            depth=1024,
            sample_clock_hz=SAMPLE_CLOCK_HZ,
            pretrigger=1,
            posttrigger=4,
            trigger=TriggerConfig(mode="value_match", value=0x40, mask=0xFF),
            decimation=3,
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertGreaterEqual(len(result.samples), 6)
        post = [s & 0xFF for s in result.samples[2:]]
        gaps = [(post[i] - post[i - 1]) & 0xFF for i in range(1, len(post))]
        self.assertTrue(all(g == 4 for g in gaps), result.samples)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestTimestamps(unittest.TestCase):
    """ELA timestamps: verify monotonic timestamp capture."""

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.a = Analyzer(_make_transport(), chain=ELA_CHAIN)
        self.a.connect()

    def tearDown(self):
        self.a.close()

    def test_timestamps_present(self):
        info = self.a.probe()
        self.assertEqual(info.get("timestamp_width", 0), 32)

    def test_timestamps_monotonic(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            sample_width=8,
            depth=1024,
            sample_clock_hz=SAMPLE_CLOCK_HZ,
            pretrigger=2,
            posttrigger=5,
            trigger=TriggerConfig(mode="value_match", value=0x30, mask=0xFF),
        )
        self.a.configure(cfg)
        self.a.arm()
        result = self.a.capture(timeout=5.0)
        self.assertGreater(len(result.timestamps), 0)
        self.assertEqual(len(result.timestamps), len(result.samples))
        for i in range(1, len(result.timestamps)):
            self.assertGreater(result.timestamps[i], result.timestamps[i - 1])


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestSegmentedCapture(unittest.TestCase):
    """ELA segmented memory: verify four-segment auto-rearm capture."""

    def setUp(self):
        from fcapz.analyzer import Analyzer

        self.a = Analyzer(_make_transport(), chain=ELA_CHAIN)
        self.a.connect()

    def tearDown(self):
        self.a.close()

    def test_num_segments_reported(self):
        info = self.a.probe()
        self.assertEqual(info.get("num_segments", 1), 4)

    def test_four_segments_captured(self):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            sample_width=8,
            depth=1024,
            sample_clock_hz=SAMPLE_CLOCK_HZ,
            pretrigger=2,
            posttrigger=3,
            trigger=TriggerConfig(mode="value_match", value=0x00, mask=0xFF),
        )
        self.a.configure(cfg)
        self.a.arm()
        self.assertTrue(self.a.wait_all_segments_done(timeout=10.0))

        expected_anchor = TRIGGER_DECISION_LATENCY & 0xFF
        for seg in range(4):
            result = self.a.capture_segment(seg, timeout=5.0)
            self.assertEqual(len(result.samples), 6)
            self.assertIn(expected_anchor, [s & 0xFF for s in result.samples])


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEioProbe(unittest.TestCase):
    """EIO: probe identity and widths through direct instance 3."""

    def test_eio_probe(self):
        from fcapz.eio import EioController

        eio = EioController(_make_transport(), chain=EIO_CHAIN)
        try:
            eio.connect()
            self.assertEqual(eio.in_w, 8)
            self.assertEqual(eio.out_w, 8)
        finally:
            eio.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEioReadWrite(unittest.TestCase):
    """EIO: read inputs and write outputs."""

    def setUp(self):
        from fcapz.eio import EioController

        self.eio = EioController(_make_transport(), chain=EIO_CHAIN)
        self.eio.connect()

    def tearDown(self):
        self.eio.close()

    def test_read_counter_bits(self):
        start = self.eio.read_inputs() & 0x03
        deadline = time.time() + 1.0
        seen = [start]
        while time.time() < deadline:
            time.sleep(0.05)
            cur = self.eio.read_inputs() & 0x03
            seen.append(cur)
            if cur != start:
                return
        self.fail(f"EIO counter bits did not advance: samples={seen}")

    def test_write_read_outputs(self):
        self.eio.write_outputs(0xA5)
        self.assertEqual(self.eio.read_outputs(), 0xA5)

    def test_write_zero_outputs(self):
        self.eio.write_outputs(0x00)
        self.assertEqual(self.eio.read_outputs(), 0x00)

    def test_set_clear_bit(self):
        self.eio.write_outputs(0x00)
        self.eio.set_bit(3, 1)
        self.assertEqual(self.eio.read_outputs() & 0x08, 0x08)
        self.assertEqual(self.eio.read_outputs() & 0x04, 0x00)
        self.eio.set_bit(3, 0)
        self.assertEqual(self.eio.read_outputs() & 0x08, 0x00)

    def test_output_roundtrip_all_bits(self):
        for bit in range(8):
            val = 1 << bit
            self.eio.write_outputs(val)
            self.assertEqual(self.eio.read_outputs(), val)
        self.eio.write_outputs(0x00)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagAxiProbe(unittest.TestCase):
    """EJTAG-AXI bridge: probe identity on direct instance 4."""

    def test_bridge_probe(self):
        from fcapz import _version_tuple
        from fcapz.ejtagaxi import _BRIDGE_CORE_ID, EjtagAxiController

        bridge = EjtagAxiController(_make_transport(), chain=AXI_CHAIN)
        try:
            info = bridge.connect()
            major, minor, _patch = _version_tuple()
            self.assertEqual(info["bridge_id"], _BRIDGE_CORE_ID)
            self.assertEqual(info["core_id"], _BRIDGE_CORE_ID)
            self.assertEqual(info["version_major"], major)
            self.assertEqual(info["version_minor"], minor)
            self.assertGreater(info["addr_w"], 0)
            self.assertGreater(info["data_w"], 0)
        finally:
            bridge.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagAxiReadWrite(unittest.TestCase):
    """EJTAG-AXI bridge: single and block read/write via test slave."""

    def setUp(self):
        from fcapz.ejtagaxi import EjtagAxiController

        self.bridge = EjtagAxiController(_make_transport(), chain=AXI_CHAIN)
        self.bridge.connect()

    def tearDown(self):
        self.bridge.close()

    def test_single_write_read_roundtrip(self):
        for val in [0x00000000, 0xFFFFFFFF, 0xA5A5A5A5, 0x12345678]:
            with self.subTest(val=f"0x{val:08X}"):
                self.bridge.axi_write(0x00, val)
                self.assertEqual(self.bridge.axi_read(0x00), val)

    def test_write_strobe_partial(self):
        self.bridge.axi_write(0x04, 0x11223344)
        self.bridge.axi_write(0x04, 0xAABBCCDD, wstrb=0x03)
        self.assertEqual(self.bridge.axi_read(0x04), 0x1122CCDD)

    def test_write_block_read_block(self):
        data = [0x1000 + i for i in range(16)]
        self.bridge.write_block(0x00, data)
        self.assertEqual(self.bridge.read_block(0x00, 16), data)

    def test_burst_write_read(self):
        data = [0xBEEF0000 + i for i in range(8)]
        self.bridge.burst_write(0x00, data)
        self.assertEqual(self.bridge.burst_read(0x00, 8), data)

    def test_error_on_error_addr(self):
        from fcapz.ejtagaxi import AXIError

        with self.assertRaises(AXIError):
            self.bridge.axi_write(0xFFFFFFFC, 0x1234)

    def test_throughput(self):
        data = [i for i in range(256)]
        t0 = time.perf_counter()
        self.bridge.write_block(0x00, data)
        elapsed = time.perf_counter() - t0
        kb_per_s = (256 * 4) / 1024 / elapsed if elapsed > 0 else 0
        print(f"\n  write_block 256 words: {elapsed:.3f}s = {kb_per_s:.1f} KB/s")
        self.assertGreater(kb_per_s, 0.3)


if __name__ == "__main__":
    unittest.main()
