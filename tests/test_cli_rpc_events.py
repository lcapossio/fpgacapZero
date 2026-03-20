# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

from host.fcapz.analyzer import Analyzer, CaptureConfig, CaptureResult, ProbeSpec, TriggerConfig
from host.fcapz.cli import _build_config, build_parser
from host.fcapz.events import ProbeDefinition, find_bursts, find_edges, frequency_estimate, summarize
from host.fcapz.rpc import RpcServer
from host.fcapz.transport import Transport


class FakeTransport(Transport):
    def __init__(self, *, sample_w: int = 8, depth: int = 1024, num_chan: int = 2, data=None):
        self.regs = {
            0x0000: 0x0001_0001,
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


if __name__ == "__main__":
    unittest.main()
