# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Hardware integration tests for the Kria KV260 reference design.

Requires a KV260 reachable through hw_server (the board's on-module JTAG,
Zynq UltraScale+ MPSoC ``xck26``) and ``examples/kv260/kv260_top.bit``.

The bitstream is programmed once, through the same RPC ``connect`` the web
UI and MCP server use, so the hw_server PS TAP programming path and the
MPSoC chain shape (xsdb ``-register userN``) are both on the tested path.

Environment:

FPGACAP_SKIP_HW=1                  skip every hardware test
FPGACAP_BITFILE=<path>             override the bitstream
FPGACAP_HW_SERVER_PORT=<port>      hw_server port (default 3121)

Run:

    python -m pytest examples/kv260/test_hw_integration.py -v
"""

from __future__ import annotations

import base64
import os
import time
import unittest
from pathlib import Path

_SKIP = os.environ.get("FPGACAP_SKIP_HW", "")

_ROOT = Path(__file__).resolve().parents[2]
BITFILE = os.environ.get(
    "FPGACAP_BITFILE", str(_ROOT / "examples" / "kv260" / "kv260_top.bit"),
)
PORT = int(os.environ.get("FPGACAP_HW_SERVER_PORT", "3121"))
FPGA = "xck26"

# The PS IP constrains pl_clk0 at this rate; the clock actually runs at
# whatever the boot firmware programmed, which the tests measure.
CONSTRAINED_CLOCK_HZ = 200_000_000

# RTL and design sources that feed the bitstream (must match build_kv260.tcl)
_BITSTREAM_SOURCES = [
    _ROOT / "rtl" / name
    for name in (
        "fcapz_version.vh", "reset_sync.v", "dpram.v", "trig_compare.v",
        "fcapz_ela.v", "fcapz_core_manager.v", "fcapz_debug_multi_xilinx7.v",
        "jtag_reg_iface.v", "jtag_pipe_iface.v", "jtag_burst_read.v",
        "jtag_tap/jtag_tap_xilinx7.v", "fcapz_async_fifo.v",
        "fcapz_ejtagaxi.v", "fcapz_ejtagaxi_xilinx7.v",
        "fcapz_ejtagaxi_xilinxus.v", "fcapz_ejtaguart.v",
        "fcapz_ejtaguart_xilinx7.v", "fcapz_ejtaguart_xilinxus.v",
        "fcapz_axi_mon.v", "fcapz_axi_mon_xilinx7.v", "fcapz_eio.v",
        "fcapz_eio_xilinx7.v",
    )
] + [
    _ROOT / "tb" / "axi4_test_slave.v",
    _ROOT / "examples" / "kv260" / "kv260_top.v",
    _ROOT / "examples" / "kv260" / "kv260.xdc",
    _ROOT / "examples" / "kv260" / "create_ps_bd.tcl",
    _ROOT / "examples" / "kv260" / "build_kv260.tcl",
]

STATUS = 0x0008  # bit0 armed, bit1 triggered, bit2 done


def _check_bitstream_freshness() -> str | None:
    bitpath = Path(BITFILE)
    if not bitpath.exists():
        return f"bitfile not found: {BITFILE}"
    bit_mtime = bitpath.stat().st_mtime
    stale = [s.name for s in _BITSTREAM_SOURCES if s.stat().st_mtime > bit_mtime]
    if stale:
        return (
            f"these sources are newer than {bitpath.name}: {', '.join(stale)}. "
            "Re-run: python examples/kv260/build.py"
        )
    return None


_STALE_MSG = None if _SKIP else _check_bitstream_freshness()
if _STALE_MSG:
    raise RuntimeError(_STALE_MSG)


def _make_transport():
    from fcapz.transport import (
        XilinxHwServerTransport,
        hw_server_chain_shape_kwargs,
    )

    return XilinxHwServerTransport(
        port=PORT, fpga_name=FPGA, **hw_server_chain_shape_kwargs(FPGA),
    )


def _rpc_req(cmd: str, **extra) -> dict:
    return {"cmd": cmd, "backend": "hw_server", "host": "127.0.0.1",
            "port": PORT, "tap": FPGA, **extra}


def setUpModule():
    if _SKIP:
        return
    # Program once through RPC; every later transport attaches to the loaded
    # design.  connect() itself waits until USER1 answers.
    from fcapz.rpc import RpcServer

    srv = RpcServer()
    try:
        r = srv.handle(_rpc_req("connect", program=BITFILE))
        if not r.get("ok"):
            raise RuntimeError(f"RPC connect/program failed: {r}")
    finally:
        srv.handle({"cmd": "close"})


def _measure_clock_hz(eio, interval: float = 1.0) -> float:
    """pl_clk0 rate from EIO slot 3's free-running 32-bit counter."""
    c0 = eio.read_inputs()
    t0 = time.perf_counter()
    time.sleep(interval)
    c1 = eio.read_inputs()
    t1 = time.perf_counter()
    return ((c1 - c0) & 0xFFFF_FFFF) / (t1 - t0)


def _steps(samples, mask=0xFF):
    return [((samples[i] - samples[i - 1]) & mask) for i in range(1, len(samples))]


class _Hw(unittest.TestCase):
    """One open transport per test, with the design already programmed."""

    def setUp(self):
        self.t = _make_transport()
        self.t.connect()

    def tearDown(self):
        self.t.close()

    def _ela(self, instance: int):
        from fcapz.analyzer import Analyzer

        a = Analyzer(self.t, instance=instance)
        a.select_instance(instance)
        return a

    def _eio(self, instance: int):
        from fcapz.eio import EioController

        eio = EioController(self.t, chain=1, instance=instance)
        eio.attach()
        return eio


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestClockAndIdentity(_Hw):
    """The PS clock runs, the POR released, and every USER chain answers."""

    def test_pl_clk0_is_running_and_within_constraint(self):
        eio = self._eio(3)
        self.assertEqual((eio.in_w, eio.out_w), (32, 8))
        hz = _measure_clock_hz(eio)
        print(f"\n  pl_clk0 measured: {hz / 1e6:.2f} MHz")
        self.assertGreater(hz, 1e6, "pl_clk0 is not running (boot firmware?)")
        self.assertLessEqual(
            hz, CONSTRAINED_CLOCK_HZ * 1.02,
            "pl_clk0 runs faster than the design's timing constraint",
        )

    def test_manager_enumerates_two_elas_and_two_eios(self):
        from fcapz.analyzer import CORE_MANAGER_CORE_ID, ELA_CORE_ID, ElaManager

        manager = ElaManager(self.t)
        self.assertEqual(manager.probe()["core_id"], CORE_MANAGER_CORE_ID)
        self.assertEqual(
            [manager.slot_info(i)["core_id"] for i in range(4)],
            [ELA_CORE_ID, ELA_CORE_ID, 0x494F, 0x494F],
        )
        slots = manager.probe_all()
        self.assertEqual([s["instance"] for s in slots], [0, 1])
        self.assertEqual([s["num_channels"] for s in slots], [1, 2])

    def test_slot_features(self):
        a0 = self._ela(0)
        info0 = a0.probe()
        self.assertEqual((info0["sample_width"], info0["depth"]), (8, 1024))
        a1 = self._ela(1)
        info1 = a1.probe()
        self.assertEqual(info1["num_channels"], 2)
        self.assertEqual(info1["trig_stages"], 4)
        self.assertTrue(info1["has_storage_qualification"])
        self.assertEqual(info0["trig_stages"], 1)
        self.assertFalse(info0["has_storage_qualification"])

    def test_all_four_user_chains_identify(self):
        """USER2-4 are reachable: the MPSoC register-IR chain select works."""
        from fcapz.analyzer import Analyzer
        from fcapz.axi_monitor import AxiMonitor
        from fcapz.ejtagaxi import _BRIDGE_CORE_ID, EjtagAxiController
        from fcapz.ejtaguart import EjtagUartController

        mon = AxiMonitor(Analyzer(self.t, chain=2))
        self.assertTrue(mon.present, "AXI monitor not found on USER2")
        uart = EjtagUartController(self.t, chain=3).attach()
        self.assertEqual(uart["core_id"], 0x4A55)
        bridge = EjtagAxiController(self.t, chain=4)
        info = bridge.attach()
        self.assertEqual(info["core_id"], _BRIDGE_CORE_ID)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEla0(_Hw):
    """Slot 0: plain 8-bit counter, burst readback, timestamps, decimation."""

    def _capture(self, **cfg_kw):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        a = self._ela(0)
        cfg = CaptureConfig(
            pretrigger=cfg_kw.pop("pretrigger", 8),
            posttrigger=cfg_kw.pop("posttrigger", 55),
            trigger=cfg_kw.pop(
                "trigger", TriggerConfig(mode="value_match", value=0x40, mask=0xFF),
            ),
            sample_width=8,
            depth=1024,
            **cfg_kw,
        )
        a.configure(cfg)
        a.arm()
        return a.capture(timeout=5.0)

    def test_counter_capture_is_contiguous(self):
        r = self._capture()
        samples = [s & 0xFF for s in r.samples]
        self.assertEqual(len(samples), 64)
        self.assertEqual(set(_steps(samples)), {1}, samples)
        self.assertEqual(samples[8], 0x40)
        self.assertEqual(set(_steps(r.timestamps, 0xFFFF_FFFF)), {1}, r.timestamps)

    def test_full_segment_capture(self):
        # NUM_SEGMENTS=4: a capture holds at most DEPTH/4 = 256 samples.
        r = self._capture(pretrigger=100, posttrigger=155)
        samples = [s & 0xFF for s in r.samples]
        self.assertEqual(len(samples), 256)
        self.assertEqual(set(_steps(samples)), {1})

    def test_decimation_stores_every_fourth_sample(self):
        # The trigger sample is stored even between decimation ticks, so the
        # gap after it can be shorter; the rest keep the /4 cadence.
        r = self._capture(decimation=3, pretrigger=0, posttrigger=31)
        samples = [s & 0xFF for s in r.samples]
        self.assertEqual(samples[0], 0x40)
        self.assertIn(_steps(samples)[0], range(1, 5), samples)
        self.assertEqual(set(_steps(samples)[1:]), {4}, samples)
        self.assertEqual(set(_steps(r.timestamps, 0xFFFF_FFFF)[1:]), {4})

    def test_external_trigger_from_eio(self):
        """ext AND an always-true compare: fires only once EIO raises out[4]."""
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        eio = self._eio(2)
        eio.write_outputs(0)
        a = self._ela(0)
        a.configure(CaptureConfig(
            pretrigger=4, posttrigger=11,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0),
            sample_width=8, depth=1024, ext_trigger_mode=2,
        ))
        a.arm()
        time.sleep(0.2)
        a.select_instance(0)
        self.assertFalse(self.t.read_reg(STATUS) & 0x2, "fired without ext trigger")
        eio.write_outputs(1 << 4)
        try:
            a.select_instance(0)
            r = a.capture(timeout=5.0)
            self.assertEqual(len(r.samples), 16)
        finally:
            eio.write_outputs(0)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEla1Sequencer(_Hw):
    """Slot 1: channel mux, multi-stage sequencer, relational compares,
    storage qualification.

    Channel 0 is ``counter_b[7:0] ^ 0xA5``; channel 1 is ``counter_b[15:8]``,
    which holds each value for exactly 256 sample clocks.  A held value makes
    a count_target observable: the trigger sample is the Nth cycle of it.
    """

    def _config(self, **kw):
        from fcapz.analyzer import CaptureConfig, TriggerConfig

        kw.setdefault(
            "trigger", TriggerConfig(mode="value_match", value=0, mask=0),
        )
        return CaptureConfig(sample_width=8, depth=1024, **kw)

    def _run(self, cfg):
        a = self._ela(1)
        a.configure(cfg)
        a.arm()
        return [s & 0xFF for s in a.capture(timeout=5.0).samples]

    def test_channel_1_is_the_held_high_byte(self):
        # An edge trigger fires on the next high-byte step.  A segment holds
        # 256 samples (NUM_SEGMENTS=4): the step and 252 cycles of the hold.
        from fcapz.analyzer import TriggerConfig

        pre = 4
        samples = self._run(self._config(
            channel=1, pretrigger=pre, posttrigger=251,
            trigger=TriggerConfig(mode="edge_detect", value=0, mask=0xFF),
        ))
        before = samples[0]
        self.assertEqual(samples[:pre], [before] * pre, samples[:8])
        self.assertEqual(samples[pre:], [(before + 1) & 0xFF] * 252, samples[:8])

    def test_channel_0_is_the_xored_low_byte(self):
        from fcapz.analyzer import TriggerConfig

        samples = self._run(self._config(
            channel=0, pretrigger=4, posttrigger=27,
            trigger=TriggerConfig(mode="value_match", value=0xA5, mask=0xFF),
        ))
        decoded = [s ^ 0xA5 for s in samples]
        self.assertEqual(set(_steps(decoded)), {1}, samples)
        self.assertEqual(samples[4], 0xA5)

    def test_multi_stage_sequence_with_count_targets(self):
        """0x40 -> 0x41 (x3) -> GEQ 0x42 AND LEQ 0x42 (x100, final).

        Stage 2's count makes the trigger the 100th cycle of 0x42, so exactly
        99 earlier 0x42 samples sit in the pre-trigger window, after 0x41.
        A sequencer that skipped to the final stage, or ignored the count,
        would fire on the first 0x42 cycle instead.
        """
        from fcapz.analyzer import SequencerStage

        EQ, GEQ, LEQ = 0, 5, 4
        seq = [
            SequencerStage(cmp_mode_a=EQ, value_a=0x40, mask_a=0xFF,
                           next_state=1, count_target=1),
            SequencerStage(cmp_mode_a=EQ, value_a=0x41, mask_a=0xFF,
                           next_state=2, count_target=3),
            SequencerStage(cmp_mode_a=GEQ, value_a=0x42, mask_a=0xFF,
                           cmp_mode_b=LEQ, value_b=0x42, mask_b=0xFF,
                           combine=2, is_final=True, count_target=100),
        ]
        pre = 128
        samples = self._run(self._config(
            channel=1, pretrigger=pre, posttrigger=31, sequence=seq,
        ))
        self.assertEqual(samples[pre], 0x42)
        run = 0
        while samples[pre - 1 - run] == 0x42:
            run += 1
        self.assertEqual(run, 99, f"0x42 cycles before the trigger: {run}")
        self.assertEqual(samples[pre - 1 - run], 0x41)

    def test_relational_compare_greater_than(self):
        """Single-stage GT on channel 1 fires on the first value above 0xF0."""
        from fcapz.analyzer import SequencerStage

        GT = 3
        pre = 8
        samples = self._run(self._config(
            channel=1, pretrigger=pre, posttrigger=7,
            sequence=[SequencerStage(cmp_mode_a=GT, value_a=0xF0, mask_a=0xFF,
                                     is_final=True)],
        ))
        # Armed at an arbitrary point: the trigger is a value above 0xF0 and,
        # unless arming landed inside the 0xF1..0xFF span, the first one.
        self.assertGreater(samples[pre], 0xF0)
        if samples[pre - 1] <= 0xF0:
            self.assertEqual(samples[pre], 0xF1)

    def test_storage_qualification_keeps_only_matching_samples(self):
        """Mode 1 stores raw channel-0 samples whose bit 0 is set."""
        from fcapz.analyzer import TriggerConfig

        samples = self._run(self._config(
            channel=0, pretrigger=8, posttrigger=23,
            trigger=TriggerConfig(mode="value_match", value=0x01, mask=0x01),
            stor_qual_mode=1, stor_qual_value=0x01, stor_qual_mask=0x01,
        ))
        self.assertTrue(all(s & 1 for s in samples), samples)
        # Raw samples are counter ^ 0xA5; bit 0 of the counter is inverted,
        # so the stored samples are every other count.
        decoded = [s ^ 0xA5 for s in samples]
        self.assertEqual(set(_steps(decoded)), {2}, samples)

    def test_storage_qualification_mode_2_keeps_non_matching(self):
        from fcapz.analyzer import TriggerConfig

        samples = self._run(self._config(
            channel=0, pretrigger=8, posttrigger=23,
            trigger=TriggerConfig(mode="value_match", value=0x00, mask=0x01),
            stor_qual_mode=2, stor_qual_value=0x01, stor_qual_mask=0x01,
        ))
        self.assertFalse(any(s & 1 for s in samples), samples)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEio(_Hw):
    def test_eio_output_roundtrip(self):
        eio = self._eio(2)
        self.assertEqual((eio.in_w, eio.out_w), (8, 8))
        for value in (0x00, 0xA5, 0x5A, 0xEF):
            eio.write_outputs(value)
            self.assertEqual(eio.read_outputs(), value)
        eio.write_outputs(0)

    def test_accesses_survive_another_client_moving_the_slot(self):
        """A second hw_server client (another program on the cable) moves
        MGR_ACTIVE before every operation; EIO writes still land in the EIO
        and an ELA capture still reads the ELA."""
        from fcapz.analyzer import CaptureConfig, CoreManager, TriggerConfig

        other = _make_transport()
        other.connect()
        try:
            intruder = CoreManager(other)
            eio = self._eio(2)
            ela = self._ela(0)
            for value in (0xA5, 0x5A):
                intruder.select_raw(0)
                eio.write_outputs(value)
                intruder.select_raw(1)
                self.assertEqual(eio.read_outputs(), value)
            intruder.select_raw(2)
            ela.configure(CaptureConfig(
                pretrigger=8, posttrigger=55, sample_width=8, depth=1024,
                trigger=TriggerConfig(mode="value_match", value=0x40, mask=0xFF),
            ))
            intruder.select_raw(3)
            ela.arm()
            intruder.select_raw(2)
            r = ela.capture(timeout=5.0)
            samples = [s & 0xFF for s in r.samples]
            self.assertEqual(len(samples), 64)
            self.assertEqual(set(_steps(samples)), {1}, samples)
            intruder.select_raw(0)
            eio.write_outputs(0)
            self.assertEqual(eio.read_outputs(), 0)
        finally:
            other.close()

    def test_eio_reads_slow_counter(self):
        eio = self._eio(2)
        seen = set()
        for _ in range(12):
            seen.add(eio.read_inputs() & 0xF)
            time.sleep(0.05)
        self.assertGreater(len(seen), 1, "slow counter never moved")


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagAxi(_Hw):
    """USER4 fcapz_ejtagaxi_xilinxus driving the AXI4 test slave."""

    def setUp(self):
        super().setUp()
        from fcapz.ejtagaxi import EjtagAxiController

        self.bridge = EjtagAxiController(self.t, chain=4)
        self.bridge.attach()

    def test_single_write_read(self):
        self.bridge.axi_write(0x10, 0xCAFEBABE)
        self.assertEqual(self.bridge.axi_read(0x10), 0xCAFEBABE)

    def test_partial_strobe(self):
        self.bridge.axi_write(0x14, 0x11223344)
        self.bridge.axi_write(0x14, 0xAABBCCDD, wstrb=0x5)
        self.assertEqual(self.bridge.axi_read(0x14), 0x11BB33DD)

    def test_burst_write_read(self):
        data = [0x1000_0000 + i * 0x0101 for i in range(8)]
        self.bridge.burst_write(0x0, data)
        self.assertEqual(self.bridge.burst_read(0x0, 8), data)

    def test_burst_write_full_fifo_depth(self):
        data = [0x2000_0000 + i for i in range(16)]
        self.bridge.burst_write(0x0, data)
        self.assertEqual(self.bridge.read_block(0x0, 16), data)

    def test_burst_read_full_fifo_depth(self):
        """A FIFO_DEPTH-beat burst read.

        The XPM async FIFO reports full after FIFO_DEPTH - 1 writes, so the
        last beat waits for the host to pop one.  A registered ``rready``
        used to accept that beat in the cycle the FIFO filled and drop it:
        16 beats failed with SLVERR while 15 passed.
        """
        data = [0x3000_0000 + i for i in range(16)]
        self.bridge.write_block(0x0, data)
        self.assertEqual(self.bridge.burst_read(0x0, 16), data)

    def test_error_then_recovery(self):
        from fcapz.ejtagaxi import AXIError

        with self.assertRaises(AXIError):
            self.bridge.axi_write(0xFFFFFFFC, 0xDEADBEEF)
        self.bridge.axi_write(0x18, 0x600DF00D)
        self.assertEqual(self.bridge.axi_read(0x18), 0x600DF00D)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestAxiMonitor(_Hw):
    """USER2 monitor captures the bridge's traffic and decodes it."""

    def setUp(self):
        super().setUp()
        from fcapz.analyzer import Analyzer
        from fcapz.axi_monitor import AxiMonitor
        from fcapz.ejtagaxi import EjtagAxiController

        self.bridge = EjtagAxiController(self.t, chain=4)
        self.bridge.attach()
        self.an = Analyzer(self.t, chain=2)
        self.mon = AxiMonitor(self.an)

    def _arm(self, *events):
        self.an.configure(self.mon.event_capture_config(
            *events, pretrigger=2, posttrigger=24, depth=256,
        ))
        self.an.arm()

    def _field_set(self, samples, field, valid):
        out = set()
        for s in samples:
            d = self.mon.decode_sample(s)
            if d.get(valid):
                out.add(d[field])
        return out

    def test_write_capture_decodes_address_and_data(self):
        self._arm("aw_hs")
        self.bridge.axi_write(0x24, 0x5EED1234)
        samples = self.an.capture(timeout=5.0).samples
        self.assertIn(0x24, self._field_set(samples, "awaddr", "awvalid"))
        self.assertIn(0x5EED1234, self._field_set(samples, "wdata", "wvalid"))

    def test_triggers_on_slverr_only(self):
        from fcapz.ejtagaxi import AXIError

        self._arm("any_err")
        self.bridge.axi_write(0x24, 0x1)
        self.t.select_chain(2)
        self.assertFalse(self.t.read_reg(STATUS) & 0x2, "false trigger on OKAY")
        with self.assertRaises(AXIError):
            self.bridge.axi_write(0xFFFFFFFC, 0x2)
        self.t.select_chain(2)
        self.assertTrue(self.t.read_reg(STATUS) & 0x4, "no capture on SLVERR")


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestEjtagUart(_Hw):
    """USER3 fcapz_ejtaguart_xilinxus with TX wired to RX."""

    def _loopback(self, payload: bytes) -> bytes:
        from fcapz.ejtaguart import EjtagUartController

        uart = EjtagUartController(self.t, chain=3)
        uart.attach()
        uart.recv(timeout=0.2)  # drain anything left from an earlier run
        uart.send(payload)
        got = b""
        deadline = time.monotonic() + 5.0
        while len(got) < len(payload) and time.monotonic() < deadline:
            got += uart.recv(timeout=0.5)
        return got

    def test_loopback(self):
        payload = b"KV260\n"
        self.assertEqual(self._loopback(payload), payload)

    def test_loopback_stress(self):
        """Back-to-back frames, repeated.  Updates the host does not issue
        reach this chain between host scans on the MPSoC; before RX pops
        were batched with their readout they lost 9 of 15 32-byte messages."""
        payload = bytes(range(32, 127))
        for _ in range(5):
            self.assertEqual(self._loopback(payload), payload)


@unittest.skipIf(_SKIP, "FPGACAP_SKIP_HW is set")
class TestRpcPath(unittest.TestCase):
    """The RPC handlers the web UI and MCP server use, on the MPSoC chain."""

    def setUp(self):
        from fcapz.rpc import RpcServer

        self.srv = RpcServer()
        r = self.srv.handle(_rpc_req("connect"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["chain"], 1)

    def tearDown(self):
        self.srv.handle({"cmd": "close"})

    def _ok(self, req):
        r = self.srv.handle(req)
        self.assertTrue(r.get("ok"), r)
        return r

    def test_capture(self):
        r = self._ok({"cmd": "capture", "pretrigger": 4, "posttrigger": 11,
                      "trigger_value": 0x40, "trigger_mask": 0xFF})
        self.assertEqual(r["sample_count"], 16)
        samples = [e["value"] & 0xFF for e in r["result"]["samples"]]
        self.assertEqual(samples[4], 0x40)
        self.assertEqual(set(_steps(samples)), {1}, samples)

    def test_bridge_autodetect_and_monitor_rebind(self):
        ej = self._ok({"cmd": "ejtag_axi_probe"})
        self.assertTrue(ej["present"])
        self.assertEqual(ej["chain"], 4)
        am = self._ok({"cmd": "axi_mon_probe"})
        self.assertTrue(am["present"])
        self.assertEqual(am["chain"], 2)
        self.assertEqual(self._ok({"cmd": "rebind", "chain": 2})["chain"], 2)
        self.assertEqual(self._ok({"cmd": "rebind", "chain": 1})["chain"], 1)

    def test_eio_side_session_on_a_managed_slot(self):
        self._ok(_rpc_req("eio_connect", chain=1, instance=2))
        self._ok({"cmd": "eio_write", "value": "0x3C"})
        r = self._ok({"cmd": "eio_read"})
        self.assertIn("value", r)
        self._ok({"cmd": "eio_write", "value": 0})

    def test_slotless_eio_sessions_bind_their_managed_slot(self):
        # Discovery while the EIO slot is active, and a connect without
        # instance, must both come back bound to EIO slot 2: an unbound
        # controller followed the ELA session's slot and wrote into the ELA.
        self._ok(_rpc_req("eio_connect", chain=1, instance=2))
        r = self._ok(_rpc_req("eio_discover", chains=[1]))
        self.assertEqual((r["chain"], r["instance"]), (1, 2))
        self._ok({"cmd": "probe"})
        self._ok({"cmd": "eio_write", "value": 0})
        r = self._ok(_rpc_req("eio_connect", chain=1))
        self.assertEqual(r["instance"], 2)
        self._ok({"cmd": "probe"})
        self.assertIn("value", self._ok({"cmd": "eio_read"}))

    def test_axi_side_session(self):
        self._ok(_rpc_req("axi_connect", chain=4))
        self._ok({"cmd": "axi_write", "addr": "0x1C", "data": "0x0BADCAFE"})
        r = self._ok({"cmd": "axi_read", "addr": "0x1C"})
        self.assertEqual(r["value"], "0x0BADCAFE")

    def test_uart_side_session_loopback(self):
        self._ok(_rpc_req("uart_connect", chain=3))
        self._ok({"cmd": "uart_recv", "timeout": 0.2})
        self._ok({"cmd": "uart_send",
                  "data": base64.b64encode(b"kv260\n").decode("ascii")})
        got = b""
        deadline = time.monotonic() + 5.0
        while len(got) < 6 and time.monotonic() < deadline:
            r = self._ok({"cmd": "uart_recv", "timeout": 0.5})
            got += base64.b64decode(r["data"])
        self.assertEqual(got, b"kv260\n")


if __name__ == "__main__":
    unittest.main()
