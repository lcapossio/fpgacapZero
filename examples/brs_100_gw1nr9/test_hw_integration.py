# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""
Integration tests for fpgacapZero on the Brisbane Silicon BRS-100-GW1NR9
(Gowin GW1NR-9C) board, driven over OpenOCD.

Unlike the Arty hw_server flow, the OpenOCD transport does **not** program the
FPGA, so before running you must have the board configured and OpenOCD up:

  1. Build and load the bitstream (SRAM is fine; it is volatile):
       python examples/brs_100_gw1nr9/build.py
       # then program out/fcapz_brs_100_gw1nr9.fs with your Gowin flow
  2. Start OpenOCD with the checked-in board config:
       openocd -f examples/brs_100_gw1nr9/brs_100_gw1nr9.cfg

The reference design instantiates an 8-bit / 64-deep / 6-channel ELA and a
shared-chain EIO (2 inputs = user buttons, 6 outputs = LEDs) muxed onto the ELA
chain at offset 0x8000.  Channel 0 of the ELA is a free-running 8-bit counter.

Environment variables
---------------------
FPGACAP_SKIP_HW=1          Skip all hardware tests (CI default).
FPGACAP_OPENOCD_PORT=<n>   OpenOCD TCL port.  Defaults to 6666.
FPGACAP_OPENOCD_TAP=<tap>  TAP name.  Defaults to ``GW1NR-9C.tap``; ``auto``
                           also works (resolves via ``jtag names``).

Run:
    openocd -f examples/brs_100_gw1nr9/brs_100_gw1nr9.cfg &
    python -m pytest examples/brs_100_gw1nr9/test_hw_integration.py -v

Skip if no hardware:
    FPGACAP_SKIP_HW=1 python -m pytest examples/brs_100_gw1nr9/test_hw_integration.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

_SKIP = os.environ.get("FPGACAP_SKIP_HW", "")
_PORT = int(os.environ.get("FPGACAP_OPENOCD_PORT", "6666"))
_TAP = os.environ.get("FPGACAP_OPENOCD_TAP", "GW1NR-9C.tap")

# Shape of the BRS-100-GW1NR9 reference design.
SAMPLE_W = 8
DEPTH = 64
NUM_CHANNELS = 6
COUNTER_CHANNEL = 0          # free-running 8-bit counter
EIO_CHAIN = 1                # EIO shares the ELA chain (ER1)
EIO_BASE = 0x8000            # register-bus mux offset for the shared-chain EIO
EIO_IN_W = 2                 # user buttons
EIO_OUT_W = 6                # board LEDs


def _make_transport():
    from fcapz.transport import OpenOcdTransport

    return OpenOcdTransport(
        host="127.0.0.1",
        port=_PORT,
        tap=_TAP,
        ir_table=OpenOcdTransport.IR_TABLE_GOWIN,
    )


def _connect_analyzer_or_skip():
    """Return a connected, identity-verified Analyzer, or raise SkipTest.

    Skips (rather than fails) when OpenOCD is not running or the board is not
    configured with the fcapz design, so the suite is a no-op without hardware.
    """
    from fcapz.analyzer import Analyzer

    a = Analyzer(_make_transport(), chain=1)
    try:
        a.connect()
        a.probe()  # raises RuntimeError if the ELA identity magic is wrong
    except OSError as exc:
        a.close()
        raise unittest.SkipTest(
            f"OpenOCD not reachable on port {_PORT} ({exc}); "
            f"start: openocd -f examples/brs_100_gw1nr9/brs_100_gw1nr9.cfg"
        )
    except RuntimeError as exc:
        a.close()
        raise unittest.SkipTest(
            f"fcapz ELA not found on the board ({exc}); "
            f"load out/fcapz_brs_100_gw1nr9.fs first"
        )
    return a


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestProbe(unittest.TestCase):
    """Basic connectivity: read ELA identity registers."""

    def test_probe_returns_valid_identity(self):
        from fcapz import _version_tuple
        from fcapz.analyzer import ELA_CORE_ID

        a = _connect_analyzer_or_skip()
        try:
            info = a.probe()
            major, minor, _patch = _version_tuple()
            self.assertEqual(info["version_major"], major)
            self.assertEqual(info["version_minor"], minor)
            self.assertEqual(info["core_id"], ELA_CORE_ID)
            self.assertEqual(info["sample_width"], SAMPLE_W)
            self.assertEqual(info["depth"], DEPTH)
            self.assertEqual(info["num_channels"], NUM_CHANNELS)
        finally:
            a.close()


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestCapture(unittest.TestCase):
    """End-to-end ELA capture over the Gowin register-path readback."""

    def setUp(self):
        self.a = _connect_analyzer_or_skip()
        self.t = self.a.transport

    def tearDown(self):
        self.a.close()

    def _capture(self, pretrig, posttrig, channel=COUNTER_CHANNEL,
                 trig_val=0, trig_mask=0xFF, mode="value_match"):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        cfg = CaptureConfig(
            pretrigger=pretrig,
            posttrigger=posttrig,
            trigger=TriggerConfig(mode=mode, value=trig_val, mask=trig_mask),
            sample_width=SAMPLE_W,
            depth=DEPTH,
            channel=channel,
        )
        self.a.configure(cfg)
        self.a.arm()
        return self.a.capture(timeout=5.0)

    def test_basic_capture_value_match(self):
        """Trigger on value=0, capture 4 + 1 + 8 samples."""
        result = self._capture(pretrig=4, posttrig=8)
        self.assertEqual(len(result.samples), 4 + 1 + 8)
        self.assertFalse(result.overflow)

    def test_counter_channel_increments(self):
        """Channel 0 is a free-running 8-bit counter; adjacent samples differ by +1."""
        result = self._capture(pretrig=4, posttrig=16, channel=COUNTER_CHANNEL)
        samples = [s & 0xFF for s in result.samples]
        errors = [
            (i - 1, samples[i - 1], samples[i])
            for i in range(1, len(samples))
            if ((samples[i] - samples[i - 1]) & 0xFF) != 1
        ]
        self.assertEqual(errors, [], f"counter errors in samples={samples}")

    def test_trigger_value_is_captured(self):
        """value_match on 0x20 — the committed window contains 0x20."""
        result = self._capture(pretrig=4, posttrig=8, trig_val=0x20, trig_mask=0xFF)
        self.assertIn(0x20, [s & 0xFF for s in result.samples])

    def test_register_roundtrip(self):
        """PRETRIG_LEN read/writes back on silicon."""
        self.t.write_reg(0x0014, 7)
        self.assertEqual(self.t.read_reg(0x0014) & 0xFFFF, 7)
        self.t.write_reg(0x0014, 0)

    def test_json_export(self):
        result = self._capture(pretrig=4, posttrig=8)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.a.write_json(result, path)
            obj = json.loads(Path(path).read_text())
            self.assertEqual(obj["sample_width"], SAMPLE_W)
            self.assertEqual(len(obj["samples"]), len(result.samples))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_vcd_export(self):
        result = self._capture(pretrig=4, posttrig=8)
        with tempfile.NamedTemporaryFile(suffix=".vcd", delete=False) as f:
            path = f.name
        try:
            self.a.write_vcd(result, path)
            self.assertIn("$enddefinitions", Path(path).read_text())
        finally:
            Path(path).unlink(missing_ok=True)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEio(unittest.TestCase):
    """EIO on the shared Gowin chain (chain 1, mux offset 0x8000)."""

    def setUp(self):
        from fcapz.eio import EioController

        self.a = _connect_analyzer_or_skip()
        self.t = self.a.transport
        self.eio = EioController(self.t, chain=EIO_CHAIN, base_addr=EIO_BASE)
        try:
            self.eio.attach()
        except RuntimeError as exc:
            self.a.close()
            raise unittest.SkipTest(
                f"shared-chain EIO not found at chain {EIO_CHAIN}/0x{EIO_BASE:04X} "
                f"({exc}); is the EIO-enabled bitstream loaded?"
            )

    def tearDown(self):
        self.eio.write_outputs(0)  # leave the LEDs off
        self.a.close()

    def test_identity_and_widths(self):
        from fcapz.eio import EIO_CORE_ID

        self.assertEqual(self.eio.core_id, EIO_CORE_ID)
        self.assertEqual(self.eio.in_w, EIO_IN_W)
        self.assertEqual(self.eio.out_w, EIO_OUT_W)

    def test_discovery_finds_shared_chain(self):
        """discover_eio locates the EIO without being told the chain/offset."""
        from fcapz.eio import discover_eio

        found = discover_eio(self.t, chains=(1, 2))
        self.assertIsNotNone(found)
        self.assertEqual(found.bscan_chain, EIO_CHAIN)
        self.assertEqual(found._base_addr, EIO_BASE)  # noqa: SLF001 - asserting discovered location

    def test_output_roundtrip(self):
        """Driving probe_out (the LEDs) reads back exactly."""
        for pat in (0x00, 0x3F, 0x15, 0x2A, 0x01, 0x20):
            self.eio.write_outputs(pat)
            self.assertEqual(
                self.eio.read_outputs(), pat, f"LED readback mismatch for 0x{pat:02X}"
            )

    def test_read_inputs_in_range(self):
        """probe_in (the 2 buttons) reads without error and within IN_W bits."""
        value = self.eio.read_inputs()
        self.assertEqual(value, value & ((1 << EIO_IN_W) - 1))


if __name__ == "__main__":
    unittest.main()
