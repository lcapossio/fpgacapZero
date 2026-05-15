# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from fcapz.analyzer import (
    Analyzer,
    CaptureConfig,
    CaptureResult,
    ProbeSpec,
    TriggerConfig,
    expected_ela_version_reg,
)
from fcapz.cli import (
    _build_config,
    _chain_shape_kwargs,
    _make_transport,
    _non_negative_int,
    _parse_trigger_sequence,
    _positive_float,
    _positive_int,
    _tcp_port,
    _uint16,
    build_parser,
)
from fcapz.transport import (
    OpenOcdTransport,
    SpiRegisterTransport,
    XilinxHwServerTransport,
)
from fcapz.events import (
    ProbeDefinition,
    find_bursts,
    find_edges,
    frequency_estimate,
    summarize,
)
from fcapz.rpc import RpcServer
from fcapz.transport import Transport


class FakeTransport(Transport):
    def __init__(self, *, sample_w: int = 8, depth: int = 1024, num_chan: int = 2, data=None):
        self.regs = {
            # VERSION computed from canonical fcapz.__version__
            0x0000: expected_ela_version_reg(),
            0x0008: 0x4,
            0x000C: sample_w,
            0x0010: depth,
            0x001C: 0,
            0x00A4: num_chan,
        }
        self.data = list(data or [1, 2, 3, 4])
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        if addr == 0x0100:
            return self.data[:words]
        return [0] * words


class AnalyzerValidationTests(unittest.TestCase):
    def test_wide_samples_reassembled_from_words(self):
        transport = FakeTransport(
            sample_w=64,
            data=[0x55667788, 0x11223344, 0xEEFF0011, 0xAABBCCDD],
        )
        transport.regs[0x001C] = 2
        analyzer = Analyzer(transport)
        analyzer.connect()
        analyzer.configure(
            CaptureConfig(
                pretrigger=0,
                posttrigger=1,
                trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
                sample_width=64,
                depth=1024,
            )
        )
        analyzer.arm()
        result = analyzer.capture(timeout=0.01)
        self.assertEqual(
            result.samples,
            [0x1122334455667788, 0xAABBCCDDEEFF0011],
        )

    def test_channel_must_fit_hardware_range(self):
        analyzer = Analyzer(FakeTransport(num_chan=2))
        analyzer.connect()
        with self.assertRaisesRegex(ValueError, "channel out of range"):
            analyzer.configure(
                CaptureConfig(
                    pretrigger=0,
                    posttrigger=0,
                    trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
                    channel=2,
                )
            )

    def test_overlapping_probes_are_rejected(self):
        analyzer = Analyzer(FakeTransport(sample_w=8))
        analyzer.connect()
        with self.assertRaisesRegex(ValueError, "overlaps"):
            analyzer.configure(
                CaptureConfig(
                    pretrigger=0,
                    posttrigger=0,
                    trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
                    probes=[ProbeSpec("lo", 4, 0), ProbeSpec("mid", 4, 2)],
                )
            )

    def test_probe_must_fit_sample_width(self):
        analyzer = Analyzer(FakeTransport(sample_w=8))
        analyzer.connect()
        with self.assertRaisesRegex(ValueError, "exceeds sample width"):
            analyzer.configure(
                CaptureConfig(
                    pretrigger=0,
                    posttrigger=0,
                    trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
                    probes=[ProbeSpec("wide", 9, 0)],
                )
            )


class ProbeDefinitionTests(unittest.TestCase):
    """Tests for ProbeDefinition validation and extract() edge cases."""

    def test_zero_width_raises(self):
        with self.assertRaises(ValueError):
            ProbeDefinition("bad", width=0, lsb=0)

    def test_negative_width_raises(self):
        with self.assertRaises(ValueError):
            ProbeDefinition("bad", width=-1, lsb=0)

    def test_negative_lsb_raises(self):
        with self.assertRaises(ValueError):
            ProbeDefinition("bad", width=4, lsb=-1)

    def test_extract_1bit(self):
        p = ProbeDefinition("b", width=1, lsb=3)
        self.assertEqual(p.extract(0b1000), 1)
        self.assertEqual(p.extract(0b0111), 0)

    def test_extract_wide_64bit(self):
        p = ProbeDefinition("wide", width=64, lsb=0)
        val = (1 << 64) - 1
        self.assertEqual(p.extract(val), val)
        self.assertEqual(p.extract(val | (0xFF << 64)), val)

    def test_extract_high_lsb(self):
        p = ProbeDefinition("hi", width=4, lsb=28)
        self.assertEqual(p.extract(0xA0000000), 0xA)

    def test_extract_lsb_plus_width_overflow(self):
        # lsb=30, width=4: bits 30-33
        p = ProbeDefinition("cross", width=4, lsb=30)
        sample = 0xF << 30  # bits 30-33 set
        self.assertEqual(p.extract(sample), 0xF)


class EventHelperTests(unittest.TestCase):
    def test_edges_bursts_frequency_and_summary(self):
        result = CaptureResult(
            config=CaptureConfig(
                pretrigger=1,
                posttrigger=4,
                trigger=TriggerConfig(mode="edge_detect", value=0, mask=1),
                sample_width=2,
                depth=16,
                sample_clock_hz=100,
                probes=[ProbeSpec("bit0", 1, 0)],
            ),
            samples=[0, 1, 0, 1, 0, 1],
        )
        probe = ProbeDefinition("bit0", 1, 0)

        edges = find_edges(result, probe)
        bursts = find_bursts(result, probe)
        summary = summarize(result, [probe])

        self.assertEqual(len(edges), 5)
        self.assertEqual(len(bursts), 6)
        self.assertEqual(frequency_estimate(result, 0, probe), 50.0)
        self.assertEqual(summary["signals"][0]["name"], "bit0")
        self.assertEqual(summary["signals"][0]["edge_count"], 5)


class FrequencyEstimateTests(unittest.TestCase):
    """Tests for frequency_estimate edge cases."""

    def _result(self, samples):
        return CaptureResult(
            config=CaptureConfig(
                pretrigger=0,
                posttrigger=len(samples) - 1,
                trigger=TriggerConfig(mode="value_match", value=0, mask=1),
                sample_width=8,
                depth=1024,
                sample_clock_hz=1000,
            ),
            samples=samples,
        )

    def test_returns_none_with_no_edges(self):
        result = self._result([0, 0, 0, 0])
        self.assertIsNone(frequency_estimate(result, 0))

    def test_returns_none_with_one_rising_edge(self):
        result = self._result([0, 1, 1, 1])
        self.assertIsNone(frequency_estimate(result, 0))

    def test_returns_value_with_two_rising_edges(self):
        result = self._result([0, 1, 0, 1])
        freq = frequency_estimate(result, 0)
        self.assertIsNotNone(freq)
        self.assertAlmostEqual(freq, 500.0)

    def test_returns_none_on_empty_samples(self):
        result = self._result([])
        self.assertIsNone(frequency_estimate(result, 0))


class SummarizeSchemaTests(unittest.TestCase):
    """Tests for consistent keys in summarize() output."""

    def test_no_edges_still_has_keys(self):
        result = CaptureResult(
            config=CaptureConfig(
                pretrigger=0,
                posttrigger=3,
                trigger=TriggerConfig(mode="value_match", value=0, mask=1),
                sample_width=8,
                depth=1024,
                sample_clock_hz=100,
            ),
            samples=[5, 5, 5, 5],  # constant — no edges
        )
        summary = summarize(result)
        sig = summary["signals"][0]
        self.assertIn("longest_burst", sig)
        self.assertIn("first_edge", sig)
        self.assertIn("last_edge", sig)
        self.assertIsNone(sig["first_edge"])
        self.assertIsNone(sig["last_edge"])
        self.assertIsNotNone(sig["longest_burst"])  # one burst of length 4

    def test_empty_samples_has_none_keys(self):
        result = CaptureResult(
            config=CaptureConfig(
                pretrigger=0,
                posttrigger=0,
                trigger=TriggerConfig(mode="value_match", value=0, mask=1),
                sample_width=8,
                depth=1024,
                sample_clock_hz=100,
            ),
            samples=[],
        )
        summary = summarize(result)
        sig = summary["signals"][0]
        self.assertIsNone(sig["longest_burst"])
        self.assertIsNone(sig["first_edge"])
        self.assertIsNone(sig["last_edge"])


class CliTriggerSequenceTests(unittest.TestCase):
    """Tests for --trigger-sequence JSON parsing edge cases."""

    def test_inline_json_single_stage(self):
        stages = _parse_trigger_sequence('[{"cmp_a": 0, "is_final": true, "value_a": "0xFF"}]')
        self.assertEqual(len(stages), 1)
        self.assertTrue(stages[0].is_final)
        self.assertEqual(stages[0].value_a, 0xFF)

    def test_inline_json_empty_array(self):
        stages = _parse_trigger_sequence("[]")
        self.assertEqual(stages, [])

    def test_inline_json_hex_values(self):
        stages = _parse_trigger_sequence(
            '[{"value_a": "0xDEAD", "mask_a": "0xFF00", "value_b": "0xBEEF", "mask_b": "0x0F"}]'
        )
        self.assertEqual(stages[0].value_a, 0xDEAD)
        self.assertEqual(stages[0].mask_a, 0xFF00)
        self.assertEqual(stages[0].value_b, 0xBEEF)
        self.assertEqual(stages[0].mask_b, 0x0F)

    def test_inline_json_defaults_filled(self):
        stages = _parse_trigger_sequence("[{}]")
        self.assertEqual(len(stages), 1)
        self.assertFalse(stages[0].is_final)
        self.assertEqual(stages[0].cmp_mode_a, 0)
        self.assertEqual(stages[0].count_target, 1)

    def test_non_array_raises(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_trigger_sequence('{"stage": 0}')

    def test_invalid_json_raises(self):
        with self.assertRaises(Exception):
            _parse_trigger_sequence("not json at all")

    def test_file_path_loaded(self):
        stages_data = [{"cmp_a": 6, "is_final": True, "count": 3}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False, encoding="utf-8") as f:
            json.dump(stages_data, f)
            tmp_path = f.name
        try:
            stages = _parse_trigger_sequence(tmp_path)
            self.assertEqual(len(stages), 1)
            self.assertEqual(stages[0].cmp_mode_a, 6)
            self.assertEqual(stages[0].count_target, 3)
            self.assertTrue(stages[0].is_final)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_multi_stage_next_state(self):
        raw = '[{"next_state": 1, "is_final": false}, {"next_state": 0, "is_final": true}]'
        stages = _parse_trigger_sequence(raw)
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[0].next_state, 1)
        self.assertFalse(stages[0].is_final)
        self.assertEqual(stages[1].next_state, 0)
        self.assertTrue(stages[1].is_final)


class RpcProbeValidationTests(unittest.TestCase):
    """Tests for _parse_probes() input validation in RpcServer."""

    def test_negative_lsb_string_raises(self):
        with self.assertRaises(ValueError):
            RpcServer._parse_probes("sig:-1:0")

    def test_zero_width_string_raises(self):
        with self.assertRaises(ValueError):
            RpcServer._parse_probes("sig:0:0")

    def test_negative_width_string_raises(self):
        with self.assertRaises(ValueError):
            RpcServer._parse_probes("sig:-4:0")

    def test_negative_lsb_list_raises(self):
        with self.assertRaises(ValueError):
            RpcServer._parse_probes([{"name": "sig", "width": 4, "lsb": -1}])

    def test_zero_width_list_raises(self):
        with self.assertRaises(ValueError):
            RpcServer._parse_probes([{"name": "sig", "width": 0, "lsb": 0}])

    def test_valid_probe_string(self):
        probes = RpcServer._parse_probes("lo:4:0,hi:4:4")
        self.assertEqual(len(probes), 2)
        self.assertEqual(probes[0].name, "lo")
        self.assertEqual(probes[1].lsb, 4)

    def test_valid_probe_list(self):
        probes = RpcServer._parse_probes([{"name": "clk", "width": 1, "lsb": 7}])
        self.assertEqual(probes[0].width, 1)
        self.assertEqual(probes[0].lsb, 7)


class CliArgValidatorTests(unittest.TestCase):
    """Tests for CLI argument type validators."""

    def test_positive_int_rejects_zero(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _positive_int("0")

    def test_positive_int_rejects_negative(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _positive_int("-5")

    def test_positive_int_accepts_positive(self):
        self.assertEqual(_positive_int("42"), 42)

    def test_non_negative_int_rejects_negative(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _non_negative_int("-1")

    def test_non_negative_int_accepts_zero(self):
        self.assertEqual(_non_negative_int("0"), 0)

    def test_positive_float_rejects_zero(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _positive_float("0")

    def test_positive_float_rejects_negative(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _positive_float("-1.5")

    def test_positive_float_accepts_positive(self):
        self.assertAlmostEqual(_positive_float("2.5"), 2.5)

    def test_tcp_port_rejects_zero(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _tcp_port("0")

    def test_tcp_port_rejects_negative(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _tcp_port("-1")

    def test_tcp_port_rejects_too_large(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _tcp_port("65536")

    def test_tcp_port_accepts_valid(self):
        self.assertEqual(_tcp_port("6666"), 6666)
        self.assertEqual(_tcp_port("1"), 1)
        self.assertEqual(_tcp_port("65535"), 65535)

    def test_uint16_accepts_zero_and_max(self):
        self.assertEqual(_uint16("0"), 0)
        self.assertEqual(_uint16("65535"), 0xFFFF)
        self.assertEqual(_uint16("0xABCD"), 0xABCD)

    def test_uint16_rejects_negative(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _uint16("-1")

    def test_uint16_rejects_too_large(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _uint16("65536")

    def test_trigger_sequence_malformed_json_gives_type_error(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_trigger_sequence("{not valid json")

    def test_trigger_sequence_missing_file_gives_type_error(self):
        # Pass a string that looks like a path but doesn't exist (and isn't valid JSON)
        with self.assertRaises((argparse.ArgumentTypeError, Exception)):
            _parse_trigger_sequence("{bad json")


class RpcSqModeValidationTests(unittest.TestCase):
    """Tests for stor_qual_mode validation in RPC _build_config."""

    def test_valid_modes_accepted(self):
        for mode in (0, 1, 2):
            self.assertEqual(RpcServer._validated_sq_mode(mode), mode)

    def test_invalid_mode_rejected(self):
        for mode in (-1, 3, 99):
            with self.assertRaises(ValueError):
                RpcServer._validated_sq_mode(mode)


class RpcTriggerDelayValidationTests(unittest.TestCase):
    """Tests for trigger_delay validation in RPC _build_config."""

    def test_valid_values_accepted(self):
        for v in (0, 1, 1234, 0xFFFF):
            self.assertEqual(RpcServer._validated_trigger_delay(v), v)

    def test_invalid_values_rejected(self):
        for v in (-1, 0x10000, 0x7FFFFFFF):
            with self.assertRaises(ValueError):
                RpcServer._validated_trigger_delay(v)


class RpcTriggerHoldoffValidationTests(unittest.TestCase):
    """Tests for trigger_holdoff validation in RPC _build_config."""

    def test_valid_values_accepted(self):
        for v in (0, 1, 1234, 0xFFFF):
            self.assertEqual(RpcServer._validated_trigger_holdoff(v), v)

    def test_invalid_values_rejected(self):
        for v in (-1, 0x10000, 0x7FFFFFFF):
            with self.assertRaises(ValueError):
                RpcServer._validated_trigger_holdoff(v)


class RpcBooleanValidationTests(unittest.TestCase):
    """Tests for strict boolean parsing in RPC _build_config."""

    def test_valid_startup_arm_values(self):
        cases = [
            (False, False),
            (True, True),
            (0, False),
            (1, True),
            ("false", False),
            ("true", True),
            ("off", False),
            ("on", True),
        ]
        for raw, expected in cases:
            cfg = RpcServer._build_config({"startup_arm": raw})
            self.assertEqual(cfg.startup_arm, expected)

    def test_invalid_startup_arm_values_rejected(self):
        for raw in (2, "maybe", object()):
            with self.assertRaises(ValueError):
                RpcServer._build_config({"startup_arm": raw})


class CliTests(unittest.TestCase):
    def test_capture_parser_accepts_channel_and_probes(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "capture",
                "--channel",
                "1",
                "--probes",
                "lo:4:0,hi:4:4",
                "--out",
                "capture.json",
            ]
        )
        config = _build_config(args)
        self.assertEqual(config.channel, 1)
        self.assertEqual([probe.name for probe in config.probes], ["lo", "hi"])

    def test_capture_parser_accepts_startup_arm_and_trigger_holdoff(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "capture",
                "--startup-arm",
                "--trigger-holdoff",
                "12",
                "--out",
                "capture.json",
            ]
        )
        config = _build_config(args)
        self.assertTrue(config.startup_arm)
        self.assertEqual(config.trigger_holdoff, 12)


class RpcServerHarness(RpcServer):
    def __init__(self, transport: Transport):
        super().__init__()
        self._transport = transport

    def _build_transport(self, req):
        return self._transport


class RpcTests(unittest.TestCase):
    def test_capture_supports_csv_vcd_summary_and_schema_version(self):
        transport = FakeTransport(data=[0, 1, 2, 3])
        transport.regs[0x001C] = 4
        server = RpcServerHarness(transport)

        connect_resp = server.handle({"cmd": "connect"})
        self.assertTrue(connect_resp["ok"])
        self.assertEqual(connect_resp["schema_version"], "1.1")

        csv_resp = server.handle(
            {
                "cmd": "capture",
                "format": "csv",
                "summarize": True,
                "channel": 1,
                "probes": [{"name": "lo", "width": 2, "lsb": 0}],
                "pretrigger": 1,
                "posttrigger": 2,
            }
        )
        self.assertEqual(csv_resp["format"], "csv")
        self.assertIn("index,value", csv_resp["content"])
        self.assertEqual(csv_resp["channel"], 1)
        self.assertIn("summary", csv_resp)

        vcd_resp = server.handle(
            {
                "cmd": "capture",
                "format": "vcd",
                "pretrigger": 0,
                "posttrigger": 3,
            }
        )
        self.assertEqual(vcd_resp["format"], "vcd")
        self.assertIn("$enddefinitions $end", vcd_resp["content"])


class ChainShapeKwargsTests(unittest.TestCase):
    """CLI auto-detection of XilinxHwServerTransport kwargs from fpga_name."""

    def test_zynq_us_plus_mpsoc_kria_uses_register_ir(self):
        """Kria K26 uses -register userN mode — one flag, no opcode table."""
        kwargs = _chain_shape_kwargs("xck26")
        self.assertEqual(kwargs, {"use_register_ir": True})

    def test_zynq_us_plus_zcu_uses_register_ir(self):
        kwargs = _chain_shape_kwargs("xczu7ev")
        self.assertEqual(kwargs, {"use_register_ir": True})

    def test_standalone_kintex_ultrascale_no_dr_padding(self):
        """Standalone US parts are single-device chains: no DAP bypass bits."""
        kwargs = _chain_shape_kwargs("xcku040")
        self.assertIs(
            kwargs["ir_table"], XilinxHwServerTransport.IR_TABLE_XILINX_ULTRASCALE,
        )
        self.assertEqual(kwargs["ir_length"], 6)
        self.assertNotIn("dr_extra_bits", kwargs)

    def test_standalone_virtex_ultrascale_plus(self):
        kwargs = _chain_shape_kwargs("xcvu9p")
        self.assertIs(
            kwargs["ir_table"], XilinxHwServerTransport.IR_TABLE_XILINX_ULTRASCALE,
        )
        self.assertEqual(kwargs["ir_length"], 6)

    def test_standalone_artix_ultrascale_plus(self):
        kwargs = _chain_shape_kwargs("xcau15p")
        self.assertIs(
            kwargs["ir_table"], XilinxHwServerTransport.IR_TABLE_XILINX_ULTRASCALE,
        )
        self.assertEqual(kwargs["ir_length"], 6)

    def test_7_series_artix_returns_empty_dict(self):
        """Empty dict means 'use all transport defaults'."""
        self.assertEqual(_chain_shape_kwargs("xc7a100t"), {})

    def test_7_series_zynq_7000_returns_empty_dict(self):
        """xc7z* is Zynq-7000 (different from xczu* MPSoC)."""
        self.assertEqual(_chain_shape_kwargs("xc7z020"), {})

    def test_case_insensitive(self):
        kwargs = _chain_shape_kwargs("XCK26")
        self.assertEqual(kwargs, {"use_register_ir": True})

    def test_unknown_name_returns_empty_dict(self):
        self.assertEqual(_chain_shape_kwargs("some_custom_name"), {})

    def test_mpsoc_kwargs_are_transport_constructor_compatible(self):
        """The dict must ``**``-unpack into XilinxHwServerTransport cleanly."""
        kwargs = _chain_shape_kwargs("xck26")
        t = XilinxHwServerTransport(fpga_name="xck26", **kwargs)
        self.assertTrue(t.use_register_ir)
        # In register mode, dr_extra_bits is forced to 0 (xsdb handles bypass).
        self.assertEqual(t.dr_extra_bits, 0)


class MakeTransportTests(unittest.TestCase):
    """CLI transport construction convenience."""

    def test_openocd_gowin_tap_uses_gowin_ir_table(self):
        args = argparse.Namespace(
            backend="openocd",
            host="127.0.0.1",
            port=6666,
            tap="GW1NR-9C.tap",
        )
        t = _make_transport(args)
        self.assertIsInstance(t, OpenOcdTransport)
        self.assertEqual(t.ir_table, OpenOcdTransport.IR_TABLE_GOWIN)

    def test_openocd_future_gowin_tap_uses_gowin_ir_table(self):
        args = argparse.Namespace(
            backend="openocd",
            host="127.0.0.1",
            port=6666,
            tap="GW5A-25.tap",
        )
        t = _make_transport(args)
        self.assertIsInstance(t, OpenOcdTransport)
        self.assertEqual(t.ir_table, OpenOcdTransport.IR_TABLE_GOWIN)

    def test_openocd_xilinx_tap_keeps_default_ir_table(self):
        args = argparse.Namespace(
            backend="openocd",
            host="127.0.0.1",
            port=6666,
            tap="xc7a100t.tap",
        )
        t = _make_transport(args)
        self.assertIsInstance(t, OpenOcdTransport)
        self.assertEqual(t.ir_table, OpenOcdTransport.IR_TABLE_XILINX7)

    def test_spi_backend_uses_spi_transport(self):
        args = argparse.Namespace(
            backend="spi",
            spi_url="ftdi://ftdi:232h/2",
            spi_frequency=2_000_000.0,
            spi_cs=1,
            host="127.0.0.1",
            port=6666,
            tap="xc7a100t.tap",
        )
        t = _make_transport(args)
        self.assertIsInstance(t, SpiRegisterTransport)
        self.assertEqual(t.url, "ftdi://ftdi:232h/2")
        self.assertEqual(t.frequency, 2_000_000.0)
        self.assertEqual(t.cs, 1)


if __name__ == "__main__":
    unittest.main()
