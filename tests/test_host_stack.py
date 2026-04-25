# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import json
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from fcapz import _version_tuple
from fcapz.analyzer import (
    Analyzer,
    CaptureConfig,
    CaptureResult,
    ELA_CORE_ID,
    SequencerStage,
    TriggerConfig,
    expected_ela_version_reg,
)
from fcapz.eio import EIO_CORE_ID, EioController
from fcapz.transport import Transport


def _expected_eio_version_reg() -> int:
    """Compute EIO VERSION constant from canonical fcapz.__version__.

    Mirrors the ELA helper but for the EIO core_id ('IO' = 0x494F).
    Tests use this so the FakeVioTransport stays coupled to whatever
    the VERSION file says, just like the RTL is via fcapz_version.vh.
    """
    major, minor, _patch = _version_tuple()
    return (
        ((major & 0xFF) << 24)
        | ((minor & 0xFF) << 16)
        | (EIO_CORE_ID & 0xFFFF)
    )


class FakeTransport(Transport):
    def __init__(self):
        # Per-chain register banks; chain=None is the default (chain 1)
        self._chain_regs: dict[int, dict[int, int]] = {
            1: {
                # VERSION computed from canonical fcapz.__version__ so this
                # fake stays in sync when VERSION is bumped.
                0x0000: expected_ela_version_reg(),
                0x000C: 8,            # SAMPLE_W
                0x0010: 1024,         # DEPTH
                0x0008: 0x4,          # STATUS done
                0x00A4: 1,            # NUM_CHAN
                0x003C: 0x0001_0164,  # FEATURES: TRIG_STAGES=4, HAS_DECIM=1, HAS_EXT=1
                0x00C4: 0,            # TIMESTAMP_W
                0x00B8: 1,            # NUM_SEGMENTS
                0x00E0: 0x3_01FF,     # COMPARE_CAPS: all modes + dual compare
            },
        }
        self._active_chain: int = 1
        self.data = [1, 2, 3, 4]

    @property
    def regs(self) -> dict[int, int]:
        """Return the register bank for the active chain."""
        return self._chain_regs.setdefault(self._active_chain, {})

    @regs.setter
    def regs(self, value: dict[int, int]) -> None:
        self._chain_regs[self._active_chain] = value

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def select_chain(self, chain: int) -> None:
        self._active_chain = chain

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        return bits  # simple echo

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def read_regs_pipelined_user1(self, addrs: list[int]) -> list[int]:
        """Match Xilinx batched probe path (:meth:`Analyzer.probe`)."""
        out = [self.read_reg(a) for a in addrs]
        self.read_reg(0x0000)
        return out

    def write_reg(self, addr: int, value: int) -> None:
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        if addr == 0x0100:
            return self.data[:words]
        return [0] * words


class AnalyzerTests(unittest.TestCase):
    def _make_cfg(self) -> CaptureConfig:
        return CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=7, mask=0xFF),
            sample_width=8,
            depth=1024,
            sample_clock_hz=100_000_000,
        )

    def test_immediate_variant_sequencer_vs_simple(self):
        analyzer = Analyzer(FakeTransport())
        analyzer.connect()
        base = replace(
            self._make_cfg(),
            ext_trigger_mode=2,
            sequence=[SequencerStage(mask_a=0xFF, is_final=True)],
        )
        imm = analyzer.immediate_variant(base)
        self.assertEqual(imm.trigger.mask, 0)
        self.assertEqual(imm.ext_trigger_mode, 0)
        self.assertIsNotNone(imm.sequence)
        self.assertEqual(len(imm.sequence), 1)
        self.assertTrue(imm.sequence[0].is_final)

        t2 = FakeTransport()
        t2.regs[0x003C] = (int(t2.regs[0x003C]) & ~0xF) | 1
        a2 = Analyzer(t2)
        a2.connect()
        imm2 = a2.immediate_variant(self._make_cfg())
        self.assertIsNone(imm2.sequence)
        self.assertEqual(imm2.trigger.mask, 0)

    def test_capture_and_export_json(self):
        analyzer = Analyzer(FakeTransport())
        analyzer.connect()
        cfg = self._make_cfg()
        analyzer.configure(cfg)
        analyzer.arm()
        result = analyzer.capture(timeout=0.01)
        data = analyzer.export_json(result)
        self.assertEqual(len(result.samples), 4)
        self.assertEqual(data["trigger"]["value"], 7)
        self.assertEqual(data["sample_width"], 8)

    def test_capture_reads_32_bit_timestamps_via_burst_block(self):
        """32-bit timestamp capture uses the transport-level timestamp burst path."""

        class TimestampBurstTransport(FakeTransport):
            def __init__(self):
                super().__init__()
                self.regs[0x001C] = 3       # CAPTURE_LEN
                self.regs[0x00C4] = 32      # TIMESTAMP_W
                self.data = [10, 11, 12]
                self.timestamp_burst_args: tuple[int, int, int] | None = None

            def read_timestamp_block(
                self,
                addr: int,
                words: int,
                timestamp_width: int,
            ) -> list[int]:
                self.timestamp_burst_args = (addr, words, timestamp_width)
                return [100, 101, 102][:words]

        transport = TimestampBurstTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()
        analyzer.configure(self._make_cfg())
        analyzer.arm()

        result = analyzer.capture(timeout=0.01)

        self.assertEqual(result.timestamps, [100, 101, 102])
        self.assertEqual(transport.timestamp_burst_args, (0x1100, 3, 32))

    def test_vcd_shifts_hw_timestamps_to_zero(self) -> None:
        """Continuous / live reload: VCD # times must not use raw counter offsets."""
        from fcapz.analyzer import vcd_simulation_times
        from fcapz.transport import VendorStubTransport

        cfg = self._make_cfg()
        r = CaptureResult(
            config=cfg,
            samples=[1, 2, 3],
            timestamps=[1_000_000, 1_000_001, 1_000_005],
        )
        self.assertEqual(vcd_simulation_times(r), [0, 1, 5])
        text = Analyzer(VendorStubTransport("export")).export_vcd_text(r)
        self.assertRegex(text, r"(?m)^#0$")
        self.assertRegex(text, r"(?m)^#5$")
        self.assertNotRegex(text, r"(?m)^#1000000$")

    def test_export_files(self):
        analyzer = Analyzer(FakeTransport())
        analyzer.connect()
        cfg = self._make_cfg()
        analyzer.configure(cfg)
        analyzer.arm()
        result = analyzer.capture(timeout=0.01)

        tmp_root = Path("tests/_tmp") / f"run_{uuid.uuid4().hex}"
        tmp_root.mkdir(parents=True, exist_ok=True)
        try:
            out_json = tmp_root / "cap.json"
            out_csv = tmp_root / "cap.csv"
            out_vcd = tmp_root / "cap.vcd"

            analyzer.write_json(result, str(out_json))
            analyzer.write_csv(result, str(out_csv))
            analyzer.write_vcd(result, str(out_vcd))

            self.assertTrue(out_json.exists())
            self.assertTrue(out_csv.exists())
            self.assertTrue(out_vcd.exists())

            obj = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(obj["samples"][0]["value"], 1)
            self.assertIn("index,value", out_csv.read_text(encoding="ascii"))
            self.assertIn("$enddefinitions $end", out_vcd.read_text(encoding="ascii"))
        finally:
            for p in sorted(tmp_root.glob("*"), reverse=True):
                p.unlink(missing_ok=True)
            tmp_root.rmdir()

    def test_probe_reports_storage_qualification_flag(self):
        """FEATURES[4] is exposed as has_storage_qualification."""
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()
        transport.regs[0x003C] = int(transport.regs[0x003C]) | (1 << 4)
        self.assertTrue(analyzer.probe()["has_storage_qualification"])
        transport.regs[0x003C] = int(transport.regs[0x003C]) & ~(1 << 4)
        self.assertFalse(analyzer.probe()["has_storage_qualification"])

    def test_probe_reports_compare_caps(self):
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()
        transport.regs[0x00E0] = 0x1C3
        info = analyzer.probe()
        self.assertEqual(info["compare_caps"], 0x1C3)
        self.assertEqual(info["compare_modes"], [0, 1, 6, 7, 8])
        self.assertTrue(info["has_dual_compare"])  # Legacy caps imply dual compare.

        transport.regs[0x00E0] = 0x2_01C3
        info = analyzer.probe()
        self.assertFalse(info["has_dual_compare"])


class SequencerTests(unittest.TestCase):
    """Tests for trigger sequencer register writes via configure()."""

    def test_two_stage_sequence_writes_registers(self):
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()

        stage0 = SequencerStage(
            cmp_mode_a=0,     # EQ
            cmp_mode_b=1,     # NEQ
            combine=2,        # AND
            next_state=1,
            is_final=False,
            count_target=3,
            value_a=0x55,
            mask_a=0xFF,
            value_b=0xAA,
            mask_b=0xF0,
        )
        stage1 = SequencerStage(
            cmp_mode_a=6,     # RISING
            cmp_mode_b=0,
            combine=0,        # A_only
            next_state=0,
            is_final=True,
            count_target=1,
            value_a=0x80,
            mask_a=0x80,
            value_b=0,
            mask_b=0xFFFFFFFF,
        )

        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            sequence=[stage0, stage1],
        )
        analyzer.configure(cfg)

        regs = transport.regs

        # Stage 0: SEQ_BASE=0x0040, stride=20
        # SEQ_CFG = cmp_a(0) | cmp_b(1)<<4 | combine(2)<<8
        #         | next(1)<<10 | final(0)<<12 | count(3)<<16
        expected_cfg0 = (
            (0 & 0xF) | ((1 & 0xF) << 4) | ((2 & 0x3) << 8)
            | ((1 & 0x3) << 10) | (0 << 12) | (3 << 16)
        )
        self.assertEqual(regs[0x0040], expected_cfg0)
        self.assertEqual(regs[0x0044], 0x55)      # value_a
        self.assertEqual(regs[0x0048], 0xFF)       # mask_a
        self.assertEqual(regs[0x004C], 0xAA)       # value_b
        self.assertEqual(regs[0x0050], 0xF0)       # mask_b

        # Stage 1: base = 0x0040 + 20 = 0x0054
        expected_cfg1 = (
            (6 & 0xF) | ((0 & 0xF) << 4) | ((0 & 0x3) << 8)
            | ((0 & 0x3) << 10) | (1 << 12) | (1 << 16)
        )
        self.assertEqual(regs[0x0054], expected_cfg1)
        self.assertEqual(regs[0x0058], 0x80)       # value_a
        self.assertEqual(regs[0x005C], 0x80)       # mask_a
        self.assertEqual(regs[0x0060], 0)          # value_b
        self.assertEqual(regs[0x0064], 0xFFFFFFFF) # mask_b

    def test_relational_sequence_mode_requires_compare_capability(self):
        transport = FakeTransport()
        transport.regs[0x00E0] = 0x1C3
        analyzer = Analyzer(transport)
        analyzer.connect()

        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            sequence=[
                SequencerStage(
                    cmp_mode_a=3,
                    combine=0,
                    is_final=True,
                    count_target=1,
                    value_a=0x80,
                    mask_a=0xFF,
                ),
            ],
        )
        with self.assertRaisesRegex(ValueError, "REL_COMPARE=1"):
            analyzer.configure(cfg)

    def test_b_combine_requires_dual_compare_capability(self):
        transport = FakeTransport()
        transport.regs[0x00E0] = 0x2_01C3
        analyzer = Analyzer(transport)
        analyzer.connect()

        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            sequence=[
                SequencerStage(
                    cmp_mode_a=0,
                    cmp_mode_b=1,
                    combine=2,
                    is_final=True,
                    count_target=1,
                    value_a=0x80,
                    mask_a=0xFF,
                    value_b=0x40,
                    mask_b=0xFF,
                ),
            ],
        )
        with self.assertRaisesRegex(ValueError, "DUAL_COMPARE=0"):
            analyzer.configure(cfg)

    def test_probe_sel_written(self):
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()

        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            probe_sel=3,
        )
        analyzer.configure(cfg)
        self.assertEqual(transport.regs[0x00AC], 3)

    def test_probe_reports_probe_mux_w(self):
        transport = FakeTransport()
        transport.regs[0x00D0] = 32  # PROBE_MUX_W
        analyzer = Analyzer(transport)
        analyzer.connect()
        info = analyzer.probe()
        self.assertEqual(info["probe_mux_w"], 32)

    def test_probe_reports_trig_stages(self):
        """FEATURES[3:0] is exposed as trig_stages for GUI / tooling."""
        transport = FakeTransport()
        transport.regs[0x003C] = (transport.regs[0x003C] & ~0xF) | 7
        analyzer = Analyzer(transport)
        analyzer.connect()
        self.assertEqual(analyzer.probe()["trig_stages"], 7)

    def test_probe_decodes_version_fields(self):
        """probe() splits VERSION into 8-bit major, 8-bit minor, 16-bit core_id."""
        transport = FakeTransport()
        # Set major=0x12, minor=0x34, core_id="LA"=0x4C41 → 0x12344C41
        transport._chain_regs[1][0x0000] = 0x1234_4C41
        analyzer = Analyzer(transport)
        analyzer.connect()
        info = analyzer.probe()
        self.assertEqual(info["version_major"], 0x12)
        self.assertEqual(info["version_minor"], 0x34)
        self.assertEqual(info["core_id"], 0x4C41)

    def test_probe_rejects_wrong_core_id(self):
        """probe() raises RuntimeError if VERSION[15:0] is not 'LA'."""
        transport = FakeTransport()
        # Wrong magic: keep major/minor but corrupt core_id
        transport._chain_regs[1][0x0000] = 0x0002_DEAD
        analyzer = Analyzer(transport)
        analyzer.connect()
        with self.assertRaisesRegex(RuntimeError, "core identity"):
            analyzer.probe()

    def test_probe_optional_none_when_no_ela(self):
        """probe_optional() returns None when USER1 is not an fcapz ELA."""
        transport = FakeTransport()
        transport._chain_regs[1][0x0000] = 0x0002_DEAD
        analyzer = Analyzer(transport)
        analyzer.connect()
        self.assertIsNone(analyzer.probe_optional())

    def test_probe_optional_matches_probe_when_ela_present(self):
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()
        opt = analyzer.probe_optional()
        self.assertIsNotNone(opt)
        self.assertEqual(opt, analyzer.probe())

    def test_probe_rejects_zero_version(self):
        """probe() raises RuntimeError if VERSION reads as 0 (unprogrammed FPGA)."""
        transport = FakeTransport()
        transport._chain_regs[1][0x0000] = 0x0000_0000
        analyzer = Analyzer(transport)
        analyzer.connect()
        with self.assertRaisesRegex(RuntimeError, "core identity"):
            analyzer.probe()

    def test_probe_matches_canonical_version(self):
        """probe() returns the major/minor from fcapz.__version__.

        This is the regression guard for option-B drift: if VERSION is
        bumped but tools/sync_version.py was not re-run, the RTL header
        and the Python __version__ will disagree, the FakeTransport's
        expected_ela_version_reg() will return one value, and the test
        will tell you exactly which two sources are out of step.
        """
        major, minor, _patch = _version_tuple()
        analyzer = Analyzer(FakeTransport())
        analyzer.connect()
        info = analyzer.probe()
        self.assertEqual(info["version_major"], major)
        self.assertEqual(info["version_minor"], minor)
        self.assertEqual(info["core_id"], ELA_CORE_ID)

    def test_trigger_delay_written(self):
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            trigger_delay=42,
        )
        analyzer.configure(cfg)
        self.assertEqual(transport.regs[0x00D4], 42)

    def test_trigger_holdoff_and_startup_arm_written(self):
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            startup_arm=True,
            trigger_holdoff=17,
        )
        analyzer.configure(cfg)
        self.assertEqual(transport.regs[0x00D8], 1)
        self.assertEqual(transport.regs[0x00DC], 17)

    def test_trigger_delay_default_zero_written(self):
        transport = FakeTransport()
        analyzer = Analyzer(transport)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
        )
        analyzer.configure(cfg)
        # Even when not specified, the register is unconditionally written
        # to 0 so a previous run cannot leak in.
        self.assertEqual(transport.regs.get(0x00D4, None), 0)
        self.assertEqual(transport.regs.get(0x00D8, None), 0)
        self.assertEqual(transport.regs.get(0x00DC, None), 0)

    def test_trigger_delay_out_of_range_rejected(self):
        analyzer = Analyzer(FakeTransport())
        analyzer.connect()
        for bad in (-1, 0x10000, 0x7FFFFFFF):
            cfg = CaptureConfig(
                pretrigger=1,
                posttrigger=2,
                trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
                sample_width=8,
                depth=1024,
                trigger_delay=bad,
            )
            with self.assertRaises(ValueError):
                analyzer.configure(cfg)

    def test_trigger_holdoff_out_of_range_rejected(self):
        analyzer = Analyzer(FakeTransport())
        analyzer.connect()
        for bad in (-1, 0x10000, 0x7FFFFFFF):
            cfg = CaptureConfig(
                pretrigger=1,
                posttrigger=2,
                trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
                sample_width=8,
                depth=1024,
                trigger_holdoff=bad,
            )
            with self.assertRaises(ValueError):
                analyzer.configure(cfg)


class FakeVioTransport(Transport):
    """Fake transport simulating a fcapz_eio with IN_W=8, OUT_W=8."""

    def __init__(self, probe_in: int = 0xAB):
        self._probe_in = probe_in
        self._active_chain: int = 1
        self.regs = {
            # VERSION computed from canonical fcapz.__version__ so this
            # fake stays in sync when VERSION is bumped.
            0x0000: _expected_eio_version_reg(),
            0x0004: 8,   # IN_W
            0x0008: 8,   # OUT_W
            0x0010: probe_in & 0xFF,  # IN[0]
        }

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def select_chain(self, chain: int) -> None:
        self._active_chain = chain

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        return bits

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


class EioControllerTests(unittest.TestCase):
    def _make_eio(self, probe_in: int = 0xAB) -> EioController:
        eio = EioController(FakeVioTransport(probe_in))
        eio.connect()
        return eio

    def test_connect_reads_widths(self):
        eio = self._make_eio()
        self.assertEqual(eio.in_w, 8)
        self.assertEqual(eio.out_w, 8)

    def test_read_inputs(self):
        eio = self._make_eio(probe_in=0xAB)
        self.assertEqual(eio.read_inputs(), 0xAB)

    def test_write_and_read_outputs(self):
        eio = self._make_eio()
        eio.write_outputs(0x42)
        self.assertEqual(eio.read_outputs(), 0x42)

    def test_write_outputs_masked(self):
        eio = self._make_eio()
        eio.write_outputs(0x1FF)   # 9 bits but OUT_W=8
        self.assertEqual(eio.read_outputs(), 0xFF)

    def test_set_bit_and_get_bit(self):
        eio = self._make_eio(probe_in=0b0101_1010)
        # Output bit manipulation
        eio.write_outputs(0x00)
        eio.set_bit(3, 1)
        self.assertEqual(eio.read_outputs(), 0x08)
        eio.set_bit(3, 0)
        self.assertEqual(eio.read_outputs(), 0x00)
        # Input bit read
        self.assertEqual(eio.get_bit(1), 1)   # 0b...1010 bit1=1
        self.assertEqual(eio.get_bit(2), 0)   # bit2=0

    def test_bad_id_raises(self):
        """Wrong VERSION[15:0] magic must be rejected."""
        transport = FakeVioTransport()
        transport.regs[0x0000] = 0xDEAD_BEEF  # core_id=0xBEEF, not 0x494F
        eio = EioController(transport)
        with self.assertRaisesRegex(RuntimeError, "core identity"):
            eio.connect()

    def test_zero_version_rejected(self):
        """Unprogrammed FPGA reads zeros — must be rejected, not accepted."""
        transport = FakeVioTransport()
        transport.regs[0x0000] = 0x0000_0000
        eio = EioController(transport)
        with self.assertRaisesRegex(RuntimeError, "core identity"):
            eio.connect()

    def test_connect_decodes_version_fields(self):
        """connect() exposes version_major / version_minor / core_id from VERSION."""
        major, minor, _patch = _version_tuple()
        eio = self._make_eio()
        self.assertEqual(eio.version_major, major)
        self.assertEqual(eio.version_minor, minor)
        self.assertEqual(eio.core_id, EIO_CORE_ID)

    def test_repr(self):
        eio = self._make_eio()
        self.assertIn("in_w=8", repr(eio))

    def test_base_addr_offsets_every_register_access(self):
        """EIO muxed on ELA's chain (base_addr=0x8000) routes reads/writes via bit 15."""
        t = FakeVioTransport()
        # Seed VERSION and widths at the EIO's OWN view (0x0000-base) so the
        # fake transport responds even without the mux; then assert the
        # transport saw 0x8000-OR'd addresses on the wire.
        eio = EioController(t, chain=1, base_addr=0x8000)
        # Trace reads so we can assert every address had bit 15 set.
        seen_reads: list[int] = []
        orig_read = t.read_reg
        def traced_read(addr: int) -> int:
            seen_reads.append(addr)
            # Respond as if bit 15 were stripped (the on-chip regbus_mux does this).
            return orig_read(addr & 0x7FFF)
        t.read_reg = traced_read  # type: ignore[method-assign]

        seen_writes: list[int] = []
        orig_write = t.write_reg
        def traced_write(addr: int, value: int) -> None:
            seen_writes.append(addr)
            orig_write(addr & 0x7FFF, value)
        t.write_reg = traced_write  # type: ignore[method-assign]

        eio.connect()
        eio.read_inputs()
        eio.write_outputs(0xAB)

        self.assertTrue(seen_reads, "no reads observed")
        self.assertTrue(seen_writes, "no writes observed")
        for addr in seen_reads + seen_writes:
            self.assertTrue(
                addr & 0x8000,
                f"address 0x{addr:04X} is missing base_addr bit 15",
            )

    def test_base_addr_default_zero_keeps_backward_compat(self):
        """Without base_addr, addresses remain the core's native 0x0000-based map."""
        t = FakeVioTransport()
        eio = EioController(t, chain=3)
        seen_reads: list[int] = []
        orig_read = t.read_reg
        def traced_read(addr: int) -> int:
            seen_reads.append(addr)
            return orig_read(addr)
        t.read_reg = traced_read  # type: ignore[method-assign]
        eio.connect()
        for addr in seen_reads:
            self.assertFalse(addr & 0x8000, f"unexpected bit 15 on 0x{addr:04X}")

    def test_attach_restores_default_chain(self):
        """attach() must not leave the transport on the EIO USER chain."""
        t = FakeVioTransport()
        self.assertEqual(t._active_chain, 1)
        eio = EioController(t, chain=3)
        eio.attach()
        self.assertEqual(t._active_chain, 1)
        self.assertEqual(eio.in_w, 8)
        self.assertEqual(eio.bscan_chain, 3)


class MultiSegmentTests(unittest.TestCase):
    """Unit tests for capture_segment() with a multi-segment fake transport."""

    def _make_4seg_transport(self) -> FakeTransport:
        t = FakeTransport()
        # Override identity registers for 4-segment core
        t._chain_regs[1][0x00B8] = 4     # NUM_SEGMENTS = 4
        t._chain_regs[1][0x003C] = (
            (4 << 16) |   # NUM_SEGMENTS field in FEATURES[23:16]
            (1 << 8)  |   # NUM_CHANNELS field in FEATURES[15:8]
            0x64          # TRIG_STAGES=4, HAS_EXT=1, HAS_DECIM=1
        )
        # Pre-fill data memory with distinct per-segment patterns
        # capture_segment() reads from ADDR_DATA_BASE (0x0100)
        # We use one sample per segment so data = [seg_value]
        t.data = [0xA0, 0xA1, 0xA2, 0xA3]
        return t

    def test_capture_segment_returns_correct_segment_index(self):
        t = self._make_4seg_transport()
        analyzer = Analyzer(t)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=0,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
        )
        analyzer.configure(cfg)
        analyzer.arm()

        for seg in range(4):
            result = analyzer.capture_segment(seg)
            self.assertEqual(result.segment, seg,
                             f"Expected segment={seg}, got {result.segment}")

    def test_capture_segment_writes_seg_sel_register(self):
        t = self._make_4seg_transport()
        analyzer = Analyzer(t)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=0,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
        )
        analyzer.configure(cfg)
        analyzer.arm()

        analyzer.capture_segment(2)
        self.assertEqual(t.regs.get(0x00C0, -1), 2,
                         "ADDR_SEG_SEL (0x00C0) should be written with seg_idx=2")

    def test_capture_segment_raises_without_configure(self):
        t = self._make_4seg_transport()
        analyzer = Analyzer(t)
        analyzer.connect()
        with self.assertRaises(RuntimeError):
            analyzer.capture_segment(0)

    def test_capture_segment_returns_samples(self):
        t = self._make_4seg_transport()
        analyzer = Analyzer(t)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=0,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
        )
        analyzer.configure(cfg)
        analyzer.arm()

        result = analyzer.capture_segment(0)
        # FakeTransport.read_block returns self.data[:words]; STATUS has done bit.
        self.assertGreater(len(result.samples), 0)

    def test_wait_all_segments_done_returns_true_when_done(self):
        t = self._make_4seg_transport()
        # STATUS already has done bit (0x4) set in the default FakeTransport
        analyzer = Analyzer(t)
        analyzer.connect()
        done = analyzer.wait_all_segments_done(timeout=0.05)
        self.assertTrue(done)


class WideSampleCaptureTests(unittest.TestCase):
    """Tests for capture() sample reassembly at edge SAMPLE_W values."""

    def _make_transport(self, sample_w: int, data: list) -> FakeTransport:
        t = FakeTransport()
        t._chain_regs[1][0x000C] = sample_w   # SAMPLE_W
        t._chain_regs[1][0x0010] = 1024        # DEPTH
        t._chain_regs[1][0x001C] = len(data) // max(1, (sample_w + 31) // 32)
        t.data = list(data)
        return t

    def _configure_and_capture(self, transport, sample_w: int, n_samples: int):
        analyzer = Analyzer(transport)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=n_samples - 1,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0x1),
            sample_width=sample_w,
            depth=1024,
        )
        analyzer.configure(cfg)
        analyzer.arm()
        return analyzer.capture(timeout=0.01)

    def test_sample_w1_masks_to_1_bit(self):
        # 1-bit samples: each word contributes one sample, masked to 1 bit
        transport = self._make_transport(sample_w=1, data=[1, 0, 1, 0])
        result = self._configure_and_capture(transport, sample_w=1, n_samples=4)
        self.assertEqual(result.samples, [1, 0, 1, 0])

    def test_sample_w1_high_bits_discarded(self):
        # Words with garbage high bits — only bit 0 should survive
        transport = self._make_transport(sample_w=1, data=[0xFF, 0xFE, 0xFD, 0xFC])
        result = self._configure_and_capture(transport, sample_w=1, n_samples=4)
        self.assertEqual(result.samples, [1, 0, 1, 0])

    def test_sample_w256_reassembles_from_8_words(self):
        # 256-bit sample: 8 × 32-bit words, little-endian
        # Build one known sample value
        words = [0x11111111, 0x22222222, 0x33333333, 0x44444444,
                 0x55555555, 0x66666666, 0x77777777, 0x88888888]
        expected = 0
        for i, w in enumerate(words):
            expected |= (w & 0xFFFF_FFFF) << (i * 32)
        expected &= (1 << 256) - 1

        transport = self._make_transport(sample_w=256, data=words)
        transport._chain_regs[1][0x001C] = 1  # CAPTURE_LEN = 1 sample
        result = self._configure_and_capture(transport, sample_w=256, n_samples=1)
        self.assertEqual(len(result.samples), 1)
        self.assertEqual(result.samples[0], expected)

    def test_sample_w256_two_samples(self):
        # 2 × 256-bit samples = 16 words
        w0 = [0xA0 + i for i in range(8)]  # sample 0
        w1 = [0xB0 + i for i in range(8)]  # sample 1
        transport = self._make_transport(sample_w=256, data=w0 + w1)
        transport._chain_regs[1][0x001C] = 2
        result = self._configure_and_capture(transport, sample_w=256, n_samples=2)
        self.assertEqual(len(result.samples), 2)
        expected0 = sum((w0[i] & 0xFFFF_FFFF) << (i * 32) for i in range(8))
        expected1 = sum((w1[i] & 0xFFFF_FFFF) << (i * 32) for i in range(8))
        self.assertEqual(result.samples[0], expected0 & ((1 << 256) - 1))
        self.assertEqual(result.samples[1], expected1 & ((1 << 256) - 1))


class SequencerBoundsTests(unittest.TestCase):
    """Tests for TRIG_STAGES bounds enforcement in configure()."""

    def _make_transport_with_stages(self, trig_stages: int) -> FakeTransport:
        t = FakeTransport()
        features = t._chain_regs[1][0x003C]
        t._chain_regs[1][0x003C] = (features & ~0xF) | (trig_stages & 0xF)
        return t

    def test_sequence_exceeds_hw_stages_raises(self):
        transport = self._make_transport_with_stages(2)
        analyzer = Analyzer(transport)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=1,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            sequence=[SequencerStage(), SequencerStage(), SequencerStage()],  # 3 > 2
        )
        with self.assertRaises(ValueError):
            analyzer.configure(cfg)

    def test_sequence_absent_hw_stages_zero_raises(self):
        transport = self._make_transport_with_stages(0)
        analyzer = Analyzer(transport)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=1,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            sequence=[SequencerStage()],
        )
        with self.assertRaises(ValueError):
            analyzer.configure(cfg)

    def test_sequence_within_hw_stages_succeeds(self):
        transport = self._make_transport_with_stages(4)
        analyzer = Analyzer(transport)
        analyzer.connect()
        cfg = CaptureConfig(
            pretrigger=0,
            posttrigger=1,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
            sample_width=8,
            depth=1024,
            sequence=[SequencerStage(is_final=True), SequencerStage()],  # 2 <= 4
        )
        analyzer.configure(cfg)  # must not raise


class ChainSelectionTests(unittest.TestCase):
    """Tests for multi-chain support in Transport and EioController."""

    def test_select_chain_changes_register_bank(self):
        t = FakeTransport()
        # Write to chain 1
        t.select_chain(1)
        t.write_reg(0x0000, 0xAAAA)
        # Switch to chain 3 and write different value
        t.select_chain(3)
        t.write_reg(0x0000, 0xBBBB)
        # Chain 1 still has its value
        t.select_chain(1)
        self.assertEqual(t.read_reg(0x0000), 0xAAAA)
        # Chain 3 has its own value
        t.select_chain(3)
        self.assertEqual(t.read_reg(0x0000), 0xBBBB)

    def test_eio_connect_calls_select_chain_3(self):
        transport = FakeVioTransport()
        eio = EioController(transport, chain=3)
        eio.connect()
        self.assertEqual(transport._active_chain, 3)

    def test_eio_custom_chain(self):
        transport = FakeVioTransport()
        eio = EioController(transport, chain=4)
        eio.connect()
        self.assertEqual(transport._active_chain, 4)

    def test_raw_dr_scan_returns_bits(self):
        t = FakeTransport()
        result = t.raw_dr_scan(0xDEAD, 16)
        self.assertEqual(result, 0xDEAD)

    def test_raw_dr_scan_batch(self):
        t = FakeTransport()
        results = t.raw_dr_scan_batch([(0xAA, 8), (0xBB, 8)])
        self.assertEqual(results, [0xAA, 0xBB])

    def test_analyzer_default_chain_unchanged(self):
        """Existing Analyzer tests work without chain selection (chain=1 default)."""
        t = FakeTransport()
        self.assertEqual(t._active_chain, 1)
        analyzer = Analyzer(t)
        analyzer.connect()
        # Analyzer reads registers on chain 1 by default
        info = analyzer.probe()
        self.assertIn("version_major", info)


if __name__ == "__main__":
    unittest.main()
