# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

from fcapz import axi_layout
from fcapz.axi_decode import REQUIRED_FIELDS, decode_axi, looks_like_axi


class _Trace:
    """Build a packed AXI4-Lite bus trace from the real probe map."""

    def __init__(self, decode: bool = True, addr_w: int = 32, data_w: int = 32):
        self.probes = axi_layout.axi_probes(addr_w, data_w, decode)
        self._by_name = {p.name: p for p in self.probes}
        self.samples: list[int] = []

    def cycle(self, **fields: int) -> "_Trace":
        packed = 0
        for name, value in fields.items():
            probe = self._by_name[name]
            packed |= (value & ((1 << probe.width) - 1)) << probe.lsb
        self.samples.append(packed)
        return self

    def idle(self, count: int = 1) -> "_Trace":
        for _ in range(count):
            self.cycle()
        return self

    def write(self, addr: int, data: int, strb: int = 0xF, resp: int = 0, gap: int = 1):
        self.cycle(awvalid=1, awready=1, awaddr=addr)
        self.cycle(wvalid=1, wready=1, wdata=data, wstrb=strb)
        self.idle(gap)
        self.cycle(bvalid=1, bready=1, bresp=resp)
        return self

    def read(self, addr: int, data: int, resp: int = 0, gap: int = 1):
        self.cycle(arvalid=1, arready=1, araddr=addr)
        self.idle(gap)
        self.cycle(rvalid=1, rready=1, rdata=data, rresp=resp)
        return self

    def decode(self):
        return decode_axi(self.samples, self.probes)


class LooksLikeAxiTests(unittest.TestCase):
    def test_accepts_both_monitor_builds(self):
        for decode in (False, True):
            probes = axi_layout.axi_probes(32, 32, decode)
            self.assertTrue(
                looks_like_axi(p.name for p in probes),
                f"decode={decode} probe map should be recognised",
            )

    def test_rejects_a_non_axi_probe_map(self):
        self.assertFalse(looks_like_axi(["clk", "reset", "counter"]))

    def test_decode_axi_names_the_missing_fields(self):
        with self.assertRaisesRegex(ValueError, "awvalid"):
            decode_axi([0, 0], [])


class TransactionReassemblyTests(unittest.TestCase):
    def test_reassembles_a_clean_write_and_read(self):
        out = _Trace().idle().write(0x1000, 0xCAFEBABE).read(0x2000, 0xDEADBEEF).decode()

        self.assertEqual(out["transaction_count"], 2)
        self.assertEqual(out["write_count"], 1)
        self.assertEqual(out["read_count"], 1)
        self.assertEqual(out["anomaly_count"], 0)

        write, read = out["transactions"]
        self.assertEqual(write["kind"], "write")
        self.assertEqual(write["addr"], "0x00001000")
        self.assertEqual(write["data"], "0xcafebabe")
        self.assertEqual(write["strb"], "0xf")
        self.assertEqual(write["resp"], "OKAY")
        self.assertNotIn("flags", write)
        self.assertEqual(read["kind"], "read")
        self.assertEqual(read["addr"], "0x00002000")
        self.assertEqual(read["data"], "0xdeadbeef")

    def test_beats_are_correlated_across_cycles_and_channels(self):
        # The point of the decoder: AW, W and B land on different cycles.
        out = _Trace().idle(3).write(0x40, 0x11, gap=5).decode()
        txn = out["transactions"][0]

        self.assertEqual(txn["cycles"]["addr"], 3)
        self.assertEqual(txn["cycles"]["data"], 4)
        self.assertEqual(txn["cycles"]["resp"], 10)
        self.assertEqual(txn["latency"], 7)
        self.assertEqual(out["max_latency"], 7)

    def test_interleaved_transactions_pair_up_in_order(self):
        # AXI4-Lite has no IDs, so two outstanding writes pair by order.
        trace = _Trace()
        trace.cycle(awvalid=1, awready=1, awaddr=0xA0)
        trace.cycle(awvalid=1, awready=1, awaddr=0xB0)
        trace.cycle(wvalid=1, wready=1, wdata=0xAA, wstrb=0xF)
        trace.cycle(wvalid=1, wready=1, wdata=0xBB, wstrb=0xF)
        trace.cycle(bvalid=1, bready=1, bresp=0)
        trace.cycle(bvalid=1, bready=1, bresp=2)
        out = trace.decode()

        first, second = out["transactions"]
        self.assertEqual((first["addr"], first["data"], first["resp"]),
                         ("0x000000a0", "0x000000aa", "OKAY"))
        self.assertEqual((second["addr"], second["data"], second["resp"]),
                         ("0x000000b0", "0x000000bb", "SLVERR"))

    def test_counts_stall_cycles_before_each_handshake(self):
        trace = _Trace()
        trace.cycle(awvalid=1, awready=0, awaddr=0x10)
        trace.cycle(awvalid=1, awready=0, awaddr=0x10)
        trace.cycle(awvalid=1, awready=1, awaddr=0x10)
        trace.cycle(wvalid=1, wready=1, wdata=0x1, wstrb=0xF)
        trace.cycle(bvalid=1, bready=1, bresp=0)
        txn = trace.decode()["transactions"][0]

        self.assertEqual(txn["stall_cycles"]["addr"], 2)


class AnomalyTests(unittest.TestCase):
    def test_flags_an_error_response(self):
        out = _Trace().idle().write(0x1000, 0x1, resp=2).decode()
        txn = out["transactions"][0]

        self.assertEqual(txn["resp"], "SLVERR")
        self.assertIn("error_response", txn["flags"])
        self.assertEqual(out["error_count"], 1)

    def test_flags_a_half_formed_write(self):
        # An AW with no W is what a dropped or scrambled command leaves behind.
        trace = _Trace().idle()
        trace.cycle(awvalid=1, awready=1, awaddr=0x1000)
        trace.idle(3)
        out = trace.decode()
        txn = out["transactions"][0]

        self.assertEqual(txn["addr"], "0x00001000")
        self.assertNotIn("data", txn)
        self.assertIn("write_missing_data", txn["flags"])
        self.assertIn("no_response_in_window", txn["flags"])

    def test_flags_partial_and_zero_byte_strobes(self):
        out = _Trace().idle().write(0x10, 0xFF, strb=0x3).decode()
        self.assertIn("partial_write", out["transactions"][0]["flags"])

        out = _Trace().idle().write(0x10, 0xFF, strb=0x0).decode()
        self.assertIn("write_strobe_zero", out["transactions"][0]["flags"])

    def test_flags_data_arriving_before_its_address(self):
        trace = _Trace().idle()
        trace.cycle(wvalid=1, wready=1, wdata=0x5, wstrb=0xF)
        trace.cycle(awvalid=1, awready=1, awaddr=0x20)
        trace.cycle(bvalid=1, bready=1, bresp=0)
        txn = trace.decode()["transactions"][0]

        self.assertIn("data_before_address", txn["flags"])

    def test_flags_an_unaligned_address(self):
        out = _Trace().idle().write(0x1002, 0x1).decode()
        self.assertIn("unaligned_address", out["transactions"][0]["flags"])

    def test_a_response_at_the_window_start_is_not_called_a_violation(self):
        # The request happened before the capture opened; that is the window's
        # fault, not the bus's, and must not be reported as an error.
        trace = _Trace()
        trace.cycle(bvalid=1, bready=1, bresp=0)
        txn = trace.decode()["transactions"][0]

        self.assertIn("request_before_window", txn["flags"])
        self.assertNotIn("unmatched_response", txn["flags"])

    def test_a_response_mid_capture_with_no_request_is_a_violation(self):
        trace = _Trace().idle(20)
        trace.cycle(bvalid=1, bready=1, bresp=0)
        txn = trace.decode()["transactions"][0]

        self.assertIn("unmatched_response", txn["flags"])

    def test_clean_traffic_produces_no_anomalies(self):
        trace = _Trace().idle()
        for i in range(8):
            trace.write(0x1000 + i * 4, 0x1000 + i)
            trace.read(0x2000 + i * 4, 0x2000 + i)
        out = trace.decode()

        self.assertEqual(out["transaction_count"], 16)
        self.assertEqual(out["anomaly_count"], 0, out["transactions"])


class EncodingTests(unittest.TestCase):
    def test_wide_addresses_and_data_are_hex_strings(self):
        # 64-bit data would round in a JS client if emitted as a JSON number.
        trace = _Trace(addr_w=64, data_w=64)
        trace.idle().write(0x1_0000_0000, 0xDEAD_BEEF_CAFE_BABE, strb=0xFF)
        out = trace.decode()
        txn = out["transactions"][0]

        self.assertEqual(out["data_width"], 64)
        self.assertEqual(txn["addr"], "0x0000000100000000")
        self.assertEqual(txn["data"], "0xdeadbeefcafebabe")

    def test_required_fields_cover_every_channel(self):
        self.assertEqual(len(REQUIRED_FIELDS), 10)


class _StubAnalyzer:
    """Enough of an Analyzer for the serializer's export step."""

    @staticmethod
    def export_csv_text(result):
        return ""


class RpcIntegrationTests(unittest.TestCase):
    """The decode has to reach callers through the real serializer."""

    def _capture(self, decode_axi_txns: bool):
        from fcapz.analyzer import CaptureConfig, CaptureResult, TriggerConfig
        from fcapz.rpc import RpcServer

        trace = _Trace().idle().write(0x1000, 0xCAFEBABE, resp=2)
        config = CaptureConfig(
            pretrigger=0,
            posttrigger=len(trace.samples),
            trigger=TriggerConfig(mode=0, value=0, mask=0),
            sample_width=160,
            depth=len(trace.samples),
            probes=list(trace.probes),
        )
        result = CaptureResult(config=config, samples=list(trace.samples))
        return RpcServer()._serialize_capture(
            analyzer=_StubAnalyzer(),
            config=config,
            result=result,
            fmt="csv",
            include_summary=False,
            decode_axi_txns=decode_axi_txns,
        )

    def test_serializer_attaches_the_decode_when_asked(self):
        payload = self._capture(True)

        self.assertIn("axi", payload)
        self.assertEqual(payload["axi"]["transaction_count"], 1)
        self.assertEqual(payload["axi"]["error_count"], 1)

    def test_serializer_omits_the_decode_by_default(self):
        self.assertNotIn("axi", self._capture(False))

    def test_non_axi_capture_is_left_alone(self):
        from fcapz.analyzer import CaptureConfig, CaptureResult, TriggerConfig
        from fcapz.rpc import RpcServer

        config = CaptureConfig(
            pretrigger=0,
            posttrigger=4,
            trigger=TriggerConfig(mode=0, value=0, mask=0),
            sample_width=8,
            depth=4,
        )
        payload = RpcServer()._serialize_capture(
            analyzer=_StubAnalyzer(),
            config=config,
            result=CaptureResult(config=config, samples=[1, 2, 3, 4]),
            fmt="csv",
            include_summary=False,
            decode_axi_txns=True,
        )

        self.assertNotIn("axi", payload)


if __name__ == "__main__":
    unittest.main()
