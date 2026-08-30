# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import asyncio
import io
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import fcapz.mcp_server as mcp_server
from fcapz.mcp_server import FcapzMcpSession, McpCapabilities, main


class FakeRpc:
    def __init__(self):
        self.requests = []

    def handle(self, req):
        self.requests.append(dict(req))
        cmd = req["cmd"]
        if cmd == "connect":
            return {"ok": True, "schema_version": "test"}
        if cmd == "close":
            return {"ok": True, "schema_version": "test"}
        if cmd == "probe":
            return {
                "ok": True,
                "schema_version": "test",
                "probe": {"sample_width": 8, "depth": 1024},
            }
        if cmd == "capture":
            return {
                "ok": True,
                "schema_version": "test",
                "format": req.get("format", "json"),
                "sample_count": 2,
                "overflow": False,
                "channel": req.get("channel", 0),
                "trigger_index": 1,
                "result": {"samples": [1, 2]},
            }
        if cmd == "capture_wait":
            return {
                "ok": True,
                "schema_version": "test",
                "format": req.get("format", "json"),
                "sample_count": 2,
                "overflow": False,
                "channel": 0,
                "trigger_index": 1,
                "result": {"samples": [3, 4]},
            }
        if cmd == "capture_status":
            return {"ok": True, "schema_version": "test", "state": "waiting", "triggered": False}
        if cmd == "configure":
            return {"ok": True, "schema_version": "test"}
        if cmd == "arm":
            return {"ok": True, "schema_version": "test"}
        if cmd == "disarm":
            return {"ok": True, "schema_version": "test"}
        if cmd == "list_cores":
            return {
                "ok": True,
                "schema_version": "test",
                "cores": [{"type": "ela", "chain": 1, "core_id": "0x454C"}],
            }
        if cmd == "eio_connect":
            return {
                "ok": True,
                "schema_version": "test",
                "in_w": 4,
                "out_w": 2,
                "chain": req["chain"],
            }
        if cmd == "eio_close":
            return {"ok": True, "schema_version": "test"}
        if cmd == "eio_read":
            return {"ok": True, "schema_version": "test", "value": 5}
        if cmd == "eio_write":
            return {"ok": True, "schema_version": "test"}
        if cmd == "axi_connect":
            return {"ok": True, "schema_version": "test", "data_width": 32, "chain": req["chain"]}
        if cmd == "axi_close":
            return {"ok": True, "schema_version": "test"}
        if cmd == "axi_read":
            return {"ok": True, "schema_version": "test", "value": "0x12345678"}
        if cmd == "axi_write":
            return {"ok": True, "schema_version": "test", "resp": "OKAY"}
        if cmd == "axi_write_block":
            return {"ok": True, "schema_version": "test", "count": len(req["data"])}
        if cmd == "axi_dump":
            return {"ok": True, "schema_version": "test", "words": ["0x00000001"]}
        if cmd == "uart_connect":
            return {"ok": True, "schema_version": "test", "chain": req["chain"]}
        if cmd == "uart_close":
            return {"ok": True, "schema_version": "test"}
        if cmd == "uart_send":
            return {"ok": True, "schema_version": "test", "bytes_sent": 2}
        if cmd == "uart_recv":
            return {"ok": True, "schema_version": "test", "data": "aGk=", "bytes_received": 2}
        if cmd == "uart_status":
            return {"ok": True, "schema_version": "test", "rx_count": 1, "tx_space": 2}
        raise AssertionError(f"unexpected cmd {cmd}")


class BlockingRpc:
    def __init__(self):
        self.release = threading.Event()

    def handle(self, req):
        self.release.wait()
        return {"ok": True, "schema_version": "test"}


class CancellableBlockingRpc(BlockingRpc):
    def __init__(self):
        super().__init__()
        self.cancelled = False

    def cancel_active(self):
        self.cancelled = True
        self.release.set()


class FailingCancelRpc(BlockingRpc):
    def cancel_active(self):
        raise RuntimeError("cancel bad")


class StubbornCancelRpc(BlockingRpc):
    def __init__(self):
        super().__init__()
        self.cancelled = False

    def cancel_active(self):
        self.cancelled = True


class SlowRpc:
    """Finishes a little after the watchdog fires, with no cancel_active hook.

    Models the real RpcServer (no cancellation) on a call whose readback
    overran the watchdog but completes within the grace window.
    """

    def __init__(self, delay=0.06):
        self.delay = delay
        self.calls = 0

    def handle(self, req):
        self.calls += 1
        time.sleep(self.delay)
        return {
            "ok": True,
            "schema_version": "test",
            "probe": {"sample_width": 8, "depth": 1024},
        }


class SparseCaptureRpc(FakeRpc):
    def handle(self, req):
        self.requests.append(dict(req))
        if req["cmd"] == "capture":
            return {"ok": True, "schema_version": "test"}
        return super().handle(req)


class UnicodeCaptureRpc(FakeRpc):
    def handle(self, req):
        self.requests.append(dict(req))
        if req["cmd"] == "capture":
            return {
                "ok": True,
                "schema_version": "test",
                "format": "json",
                "sample_count": 1,
                "result": {"samples": [1], "probe": "信号"},
            }
        return super().handle(req)


class FcapzMcpSessionTests(unittest.TestCase):
    def test_connect_probe_and_status_track_session_state(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        session.connect(backend="openocd", port=6666, tap="GW1NR-9C.tap")
        probe = session.probe()

        self.assertTrue(session.status()["connected"])
        self.assertEqual(session.status()["rpc_schema_version"], "test")
        self.assertIsNotNone(session.status()["mcp_server_version"])
        self.assertEqual(probe["probe"]["sample_width"], 8)
        self.assertEqual(session.status()["last_probe"]["depth"], 1024)
        self.assertEqual(rpc.requests[0]["backend"], "openocd")
        self.assertEqual(rpc.requests[0]["port"], 6666)
        self.assertEqual(rpc.requests[0]["tap"], "GW1NR-9C.tap")

    def test_connect_defaults_tap_by_backend_and_reconnects_cleanly(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        session.connect(backend="hw_server")
        session.connect(backend="openocd")

        self.assertEqual(rpc.requests[0]["tap"], "xc7a100t")
        self.assertEqual(rpc.requests[1], {"cmd": "close"})
        self.assertEqual(rpc.requests[2]["tap"], "xc7a100t.tap")

    def test_close_is_idempotent_without_rpc_call_when_disconnected(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        self.assertEqual(session.close(), {"ok": True})
        self.assertEqual(session.eio_close(), {"ok": True})
        self.assertEqual(rpc.requests, [])

    def test_connect_forwards_usb_blaster_options(self):
        rpc = FakeRpc()
        # A caller-supplied quartus_stp executable requires --allow-program.
        session = FcapzMcpSession(
            rpc=rpc, capabilities=McpCapabilities(allow_program=True)
        )

        session.connect(
            backend="usb_blaster",
            hardware="USB-Blaster",
            quartus_stp="quartus_stp",
        )

        self.assertEqual(rpc.requests[0]["backend"], "usb_blaster")
        self.assertNotIn("host", rpc.requests[0])
        self.assertNotIn("tap", rpc.requests[0])
        self.assertEqual(rpc.requests[0]["hardware"], "USB-Blaster")
        self.assertEqual(rpc.requests[0]["quartus_stp"], "quartus_stp")

    def test_usb_blaster_hardware_forwards_without_allow_program(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        # hardware is a cable selector, not an executable: no gate.
        session.connect(backend="usb_blaster", hardware="USB-Blaster")
        self.assertEqual(rpc.requests[0]["hardware"], "USB-Blaster")

    def test_caller_quartus_stp_requires_allow_program(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(PermissionError, "quartus_stp"):
            session.connect(backend="usb_blaster", quartus_stp="/tmp/evil")
        # Also gated on the bridge connects.
        with self.assertRaisesRegex(PermissionError, "quartus_stp"):
            session.eio_connect(backend="usb_blaster", quartus_stp="/tmp/evil")

    def test_connect_forwards_explicit_chain(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        session.connect(backend="hw_server", chain=5)
        self.assertEqual(rpc.requests[0]["chain"], 5)

    def test_connect_rejects_out_of_range_port(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(ValueError, "port must be in 1..65535"):
            session.connect(backend="hw_server", port=70000)

    def test_connect_rejects_spi_backend(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(ValueError, "unknown backend: spi"):
            session.connect(backend="spi")

    def test_connect_rejects_backend_irrelevant_options(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(ValueError, "hardware not supported"):
            session.connect(backend="hw_server", hardware="USB-Blaster")
        with self.assertRaisesRegex(ValueError, "tap not supported"):
            session.connect(backend="usb_blaster", tap="xc7a100t.tap")
        with self.assertRaisesRegex(ValueError, "host not supported"):
            session.connect(backend="usb_blaster", host="127.0.0.1")
        with self.assertRaisesRegex(ValueError, "quartus_stp not supported"):
            session.eio_connect(backend="openocd", quartus_stp="quartus_stp")

    def test_capture_merges_config_and_records_summary(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        response = session.capture(
            config={"pretrigger": 4, "posttrigger": 8, "channel": 1},
            timeout=2.5,
            fmt="json",
        )

        self.assertEqual(response["sample_count"], 2)
        self.assertNotIn("result", response)
        self.assertEqual(rpc.requests[-1]["pretrigger"], 4)
        self.assertEqual(rpc.requests[-1]["timeout"], 2.5)
        self.assertEqual(session.status()["last_capture_summary"]["sample_count"], 2)
        self.assertGreater(session.status()["last_capture_size_bytes"], 0)
        self.assertEqual(session.status()["last_capture_summary"]["trigger_index"], 1)
        self.assertEqual(session.last_capture["result"], {"samples": [1, 2]})

    def test_capture_immediate_sets_flag(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        session.capture(immediate=True)
        self.assertTrue(rpc.requests[-1]["immediate"])

    def test_capture_rejects_bad_format(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(ValueError, "format must be one of"):
            session.capture(fmt="vcdd")

    def test_capture_wait_reads_out_without_rearming(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        summary = session.capture_wait(timeout=3.0)
        self.assertEqual(rpc.requests[-1]["cmd"], "capture_wait")
        self.assertEqual(rpc.requests[-1]["timeout"], 3.0)
        self.assertEqual(summary["sample_count"], 2)
        # capture_wait populates the same cache as capture.
        self.assertEqual(session.last_capture["result"], {"samples": [3, 4]})
        # No configure/arm was issued by capture_wait.
        self.assertNotIn("configure", [r["cmd"] for r in rpc.requests])

    def test_capture_status_and_disarm(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        self.assertEqual(session.capture_status()["state"], "waiting")
        self.assertEqual(session.disarm(), {"ok": True, "schema_version": "test"})
        self.assertEqual(rpc.requests[-1]["cmd"], "disarm")

    def test_capture_flow_tools_gated_by_read_only(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(), capabilities=McpCapabilities(allow_capture=False)
        )
        with self.assertRaisesRegex(PermissionError, "capture tools are disabled"):
            session.capture_wait()
        with self.assertRaisesRegex(PermissionError, "disarm tools are disabled"):
            session.disarm()

    def test_list_cores_forwards(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        cores = session.list_cores()["cores"]
        self.assertEqual(rpc.requests[-1]["cmd"], "list_cores")
        self.assertEqual(cores[0]["chain"], 1)

    def test_uart_recv_rejects_negative_count(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        with self.assertRaisesRegex(ValueError, "count must be >= 0"):
            session.uart_recv(-1)

    def test_axi_dump_rejects_negative_count(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        with self.assertRaisesRegex(ValueError, "count must be >= 0"):
            session.axi_dump(0x1000, -5)

    def test_capture_rejects_timeout_over_cap(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        with self.assertRaisesRegex(ValueError, r"timeout must be <= 300"):
            session.capture(timeout=3600)
        with self.assertRaisesRegex(ValueError, r"timeout must be <= 300"):
            session.capture_wait(timeout=3600)
        with self.assertRaisesRegex(ValueError, r"timeout must be <= 300"):
            session.uart_recv(4, timeout=3600)

    def test_capture_wait_timeout_returns_still_armed(self):
        class ArmedWaitingRpc:
            def handle(self, req):
                # The RPC-side wait expired but returned control cleanly.
                raise TimeoutError("capture did not complete within timeout")

        session = FcapzMcpSession(rpc=ArmedWaitingRpc())
        result = session.capture_wait(timeout=0.5)
        self.assertEqual(
            result, {"ok": True, "triggered": False, "still_armed": True}
        )

    def test_uart_send_rejects_invalid_base64(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(), capabilities=McpCapabilities(allow_uart_send=True)
        )
        with self.assertRaisesRegex(ValueError, "not valid base64"):
            session.uart_send(data_base64="@@@not-base64@@@")
        # A well-formed payload still goes through.
        session.uart_send(data_base64="aGk=")

    def test_capture_cache_is_a_consistent_snapshot(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session.capture()

        cache = session._capture_cache
        self.assertIsNotNone(cache)
        # Every derived view agrees — the invariant a concurrent reader relies on.
        self.assertEqual(cache.size_bytes, len(cache.json_bytes))
        self.assertEqual(cache.json_bytes, cache.json_text.encode("utf-8"))
        self.assertEqual(session.last_capture, cache.payload)
        # drop clears the whole snapshot atomically.
        session.drop_last_capture()
        self.assertIsNone(session._capture_cache)
        self.assertIsNone(session.last_capture)

    def test_axi_block_ops_reject_over_word_limit(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(), capabilities=McpCapabilities(allow_axi_write=True)
        )
        with self.assertRaisesRegex(ValueError, "per-call limit"):
            session.axi_dump(0x1000, mcp_server._MAX_AXI_WORDS + 1)
        with self.assertRaisesRegex(ValueError, "per-call limit"):
            session.axi_write_block(0x1000, [0] * (mcp_server._MAX_AXI_WORDS + 1))
        # At the limit it still goes through.
        session.axi_dump(0x1000, mcp_server._MAX_AXI_WORDS)

    def test_worker_join_timeout_outlasts_capture_timeout(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(), capabilities=McpCapabilities(rpc_timeout_sec=30.0)
        )
        # No wait-bearing field: plain base window.
        self.assertEqual(session._worker_join_timeout({"cmd": "probe"}), 30.0)
        self.assertEqual(
            session._worker_join_timeout({"cmd": "capture", "timeout": 0.0}), 30.0
        )
        # The caller's timeout gets a full base window of readback headroom on
        # top, so the watchdog never trips mid-readout of a completed capture.
        self.assertEqual(
            session._worker_join_timeout({"cmd": "capture", "timeout": 5.0}), 35.0
        )
        self.assertEqual(
            session._worker_join_timeout({"cmd": "capture", "timeout": 60.0}), 90.0
        )

    def test_capture_summary_always_reports_success(self):
        session = FcapzMcpSession(rpc=SparseCaptureRpc())

        response = session.capture()

        self.assertEqual(response, {"ok": True, "schema_version": "test"})
        self.assertEqual(
            session.status()["last_capture_summary"],
            {"ok": True, "schema_version": "test"},
        )

    def test_status_reports_rpc_schema_before_first_rpc(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        self.assertIsInstance(session.status()["rpc_schema_version"], str)
        self.assertIsNotNone(session.status()["rpc_schema_version"])

    def test_drop_last_capture_releases_cached_payload(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        session.capture()
        self.assertIsNotNone(session.last_capture)
        full = session.get_last_capture()
        self.assertFalse(full["truncated"])
        self.assertGreater(full["size_bytes"], 0)
        self.assertEqual(full["result"], {"samples": [1, 2]})
        self.assertEqual(session.drop_last_capture(), {"ok": True, "had_capture": True})

        self.assertIsNone(session.last_capture)
        self.assertIsNone(session.status()["last_capture_summary"])
        self.assertEqual(session.get_last_capture(), {"available": False})
        self.assertEqual(session.drop_last_capture(), {"ok": True, "had_capture": False})

    def test_get_last_capture_truncates_large_tool_result(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        session.capture()
        response = session.get_last_capture(max_bytes=16)

        self.assertTrue(response["available"])
        self.assertTrue(response["truncated"])
        self.assertGreater(response["size_bytes"], 16)
        self.assertEqual(response["summary"]["sample_count"], 2)
        self.assertIn("fcapz_get_last_capture_chunk", response["message"])
        self.assertEqual(session.get_last_capture(max_bytes=None)["result"], {"samples": [1, 2]})
        with self.assertRaisesRegex(ValueError, "max_bytes"):
            session.get_last_capture(max_bytes=-1)

    def test_get_last_capture_chunk_pages_compact_json(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        session.capture()
        first = session.get_last_capture_chunk(offset=0, max_bytes=24)
        second = session.get_last_capture_chunk(offset=first["next_offset"], max_bytes=1000)
        payload = json.loads(first["chunk"] + second["chunk"])

        self.assertTrue(first["available"])
        self.assertEqual(first["encoding"], "json-utf8")
        self.assertEqual(first["offset"], 0)
        self.assertFalse(first["eof"])
        self.assertTrue(second["eof"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual(payload["result"], {"samples": [1, 2]})

    def test_get_last_capture_chunk_uses_utf8_byte_offsets(self):
        session = FcapzMcpSession(rpc=UnicodeCaptureRpc())

        session.capture()
        chunks = []
        offset = 0
        while offset is not None:
            page = session.get_last_capture_chunk(offset=offset, max_bytes=17)
            self.assertLessEqual(len(page["chunk"].encode("utf-8")), 17)
            chunks.append(page["chunk"])
            offset = page["next_offset"]
        payload = json.loads("".join(chunks))

        self.assertEqual(payload["result"]["probe"], "信号")
        self.assertEqual(
            session.status()["last_capture_size_bytes"],
            len(session.last_capture_json_text().encode("utf-8")),
        )

    def test_get_last_capture_chunk_rejects_mid_utf8_offset(self):
        session = FcapzMcpSession(rpc=UnicodeCaptureRpc())

        session.capture()
        session.last_capture_json = json.dumps(
            session.last_capture,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        session.last_capture_json_bytes = session.last_capture_json.encode("utf-8")
        session.last_capture_size_bytes = len(session.last_capture_json_bytes)
        payload = session.last_capture_json_text().encode("utf-8")
        mid_char_offset = next(
            idx for idx, byte in enumerate(payload) if byte & 0xC0 == 0x80
        )

        with self.assertRaisesRegex(ValueError, "UTF-8 character boundary"):
            session.get_last_capture_chunk(offset=mid_char_offset, max_bytes=16)

    def test_get_last_capture_chunk_rejects_invalid_utf8_start_offset(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        json_bytes = b'{"bad":"\xff"}'
        session._capture_cache = mcp_server._CaptureCache(
            payload={"ok": True},
            json_text=json_bytes.decode("latin-1"),
            json_bytes=json_bytes,
            size_bytes=len(json_bytes),
            summary={"ok": True},
        )

        with self.assertRaisesRegex(ValueError, "UTF-8 character boundary"):
            session.get_last_capture_chunk(offset=8, max_bytes=16)

    def test_get_last_capture_bounds_large_summary(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        json_text = '{"ok":true,"result":"' + ("x" * 200) + '"}'
        json_bytes = json_text.encode("utf-8")
        session._capture_cache = mcp_server._CaptureCache(
            payload={"ok": True},
            json_text=json_text,
            json_bytes=json_bytes,
            size_bytes=len(json_bytes),
            summary={"ok": True, "events": ["x" * 9000]},
        )

        response = session.get_last_capture(max_bytes=16)

        self.assertTrue(response["truncated"])
        self.assertEqual(
            response["summary"]["summary_status"]["truncated"],
            True,
        )
        self.assertNotIn("events", response["summary"])

    def test_get_last_capture_chunk_validates_bounds(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session.capture()

        with self.assertRaisesRegex(ValueError, "offset"):
            session.get_last_capture_chunk(offset=-1)
        with self.assertRaisesRegex(ValueError, "max_bytes"):
            session.get_last_capture_chunk(max_bytes=0)

    def test_configure_and_arm_are_separate_rpc_commands(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        session.configure({"pretrigger": 1, "posttrigger": 2})
        session.arm()

        self.assertEqual(rpc.requests[0], {"cmd": "configure", "pretrigger": 1, "posttrigger": 2})
        self.assertEqual(rpc.requests[1], {"cmd": "arm"})

    def test_capture_rejects_unknown_config_keys(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(ValueError, "unsupported capture config"):
            session.capture(config={"cmd": "close"})
        with self.assertRaisesRegex(ValueError, "unsupported capture config"):
            session.capture(config={"timeout": 0.001, "format": "vcd"})

    def test_read_only_blocks_capture_and_eio_write(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(),
            capabilities=McpCapabilities(allow_capture=False, allow_eio_write=False),
        )

        with self.assertRaises(PermissionError):
            session.capture()
        with self.assertRaises(PermissionError):
            session.eio_write(1)
        with self.assertRaises(PermissionError):
            session.axi_write(0, 1)
        with self.assertRaises(PermissionError):
            session.uart_send(text="hi")
        with self.assertRaises(PermissionError):
            session.configure({})
        with self.assertRaises(PermissionError):
            session.arm()
        with self.assertRaises(PermissionError):
            session.connect(program="design.bit")

    def test_eio_write_requires_explicit_capability(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(allow_capture=True, allow_eio_write=True),
        )

        session.eio_connect(chain=3)
        session.eio_write(2)
        self.assertEqual(rpc.requests[-1], {"cmd": "eio_write", "value": 2})
        self.assertTrue(session.status()["eio_connected"])

    def test_eio_read_is_cached_and_cleared_on_close(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        self.assertEqual(session.eio_read()["value"], 5)
        self.assertEqual(session.status()["last_eio_read"]["value"], 5)
        session.eio_close()

        self.assertIsNone(session.status()["last_eio_read"])

    def test_eio_connect_defaults_chain_by_backend(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        session.eio_connect(backend="hw_server")
        session.eio_connect(backend="usb_blaster")

        self.assertEqual(rpc.requests[0]["chain"], 3)
        self.assertEqual(rpc.requests[1], {"cmd": "eio_close"})
        self.assertEqual(rpc.requests[2]["chain"], 0)

    def test_axi_tools_route_through_rpc_and_gate_writes(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(allow_axi_write=True),
        )

        session.axi_connect(backend="openocd", port=6666)
        self.assertEqual(rpc.requests[-1]["cmd"], "axi_connect")
        self.assertEqual(rpc.requests[-1]["chain"], 4)
        self.assertEqual(rpc.requests[-1]["tap"], "xc7a100t.tap")
        self.assertEqual(session.axi_read(0x10)["value"], "0x12345678")
        self.assertEqual(session.axi_write(0x10, 0xCAFE)["resp"], "OKAY")
        self.assertEqual(rpc.requests[-1]["wstrb"], 0xF)
        self.assertEqual(session.axi_write_block(0x20, [1, 0x2])["count"], 2)
        self.assertEqual(session.axi_dump(0x20, 1)["words"], ["0x00000001"])
        session.axi_close()
        self.assertFalse(session.status()["axi_connected"])

    def test_axi_write_requires_explicit_capability(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaises(PermissionError):
            session.axi_write(0, 1)
        with self.assertRaises(PermissionError):
            session.axi_write_block(0, [1])

    def test_uart_tools_route_through_rpc_and_gate_sends(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(allow_uart_send=True),
        )

        session.uart_connect(backend="hw_server")
        self.assertEqual(rpc.requests[-1]["cmd"], "uart_connect")
        self.assertEqual(rpc.requests[-1]["chain"], 4)
        self.assertEqual(session.uart_send(text="hi")["bytes_sent"], 2)
        self.assertEqual(rpc.requests[-1]["data"], "aGk=")
        self.assertEqual(session.uart_recv(16, timeout=0.25)["bytes_received"], 2)
        self.assertEqual(session.uart_status()["rx_count"], 1)
        session.uart_close()
        self.assertFalse(session.status()["uart_connected"])

    def test_uart_send_requires_explicit_capability(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaises(PermissionError):
            session.uart_send(text="hi")

    def test_uart_send_rejects_ambiguous_payload_sources(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(),
            capabilities=McpCapabilities(allow_uart_send=True),
        )

        with self.assertRaisesRegex(ValueError, "only one"):
            session.uart_send(data_base64="aGk=", text="hi")

    def test_program_requires_explicit_capability(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaises(PermissionError):
            session.connect(program="design.bit")

    def test_program_is_hw_server_only(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(),
            capabilities=McpCapabilities(allow_program=True),
        )

        with self.assertRaisesRegex(ValueError, "only supported for backend 'hw_server'"):
            session.connect(backend="openocd", program="design.bit")

    def test_program_permission_is_checked_before_backend_specificity(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(PermissionError, "programming is disabled"):
            session.connect(backend="openocd", program="design.bit")

    def test_program_requires_bitfile_under_root(self):
        rpc = FakeRpc()
        # Keep files under the repo workspace so Windows path/drive resolution
        # cannot affect Path.parents checks.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir) / "allowed"
            root.mkdir()
            bitfile = root / "design.bit"
            bitfile.write_bytes(b"bit")
            other = root.parent / "other.bit"
            other.write_bytes(b"bit")
            session = FcapzMcpSession(
                rpc=rpc,
                capabilities=McpCapabilities(
                    allow_capture=True,
                    allow_program=True,
                    bitfile_root=root,
                ),
            )
            session.connect(program=str(bitfile))
            self.assertEqual(rpc.requests[-1]["program"], str(bitfile.resolve()))
            with self.assertRaisesRegex(ValueError, "outside allowed root"):
                session.connect(program=str(other))

    def test_main_rejects_conflicting_safety_flags(self):
        with self.assertRaises(SystemExit):
            main(["--read-only", "--allow-eio-write"])
        with self.assertRaises(SystemExit):
            main(["--read-only", "--allow-axi-write"])
        with self.assertRaises(SystemExit):
            main(["--read-only", "--allow-uart-send"])
        with self.assertRaises(SystemExit):
            main(["--read-only", "--allow-program"])
        with self.assertRaises(SystemExit):
            main(["--bitfile-root", "."])
        with self.assertRaises(SystemExit):
            main(["--rpc-cancel-grace", "-1"])
        with self.assertRaises(SystemExit):
            main(["--rpc-cancel-grace", "0"])
        with self.assertRaises(SystemExit):
            main(["--rpc-timeout", "0"])

    def test_parser_accepts_rpc_timeout_and_cancel_grace(self):
        args = mcp_server.build_parser().parse_args(
            ["--rpc-timeout", "12.5", "--rpc-cancel-grace", "2.5"]
        )
        self.assertEqual(args.rpc_timeout, 12.5)
        self.assertEqual(args.rpc_cancel_grace, 2.5)

    def test_main_prints_traceback_on_startup_error(self):
        class BrokenServer:
            def run(self, **kwargs):
                raise RuntimeError("schema exploded")

        stderr = io.StringIO()
        with patch.object(mcp_server, "build_mcp_server", return_value=BrokenServer()):
            with redirect_stderr(stderr):
                self.assertEqual(main([]), 1)

        text = stderr.getvalue()
        self.assertIn("fcapz-mcp: schema exploded", text)
        self.assertIn("Traceback", text)

    def test_main_shuts_down_session_when_run_returns(self):
        class DoneServer:
            def run(self, **kwargs):
                return None

        with patch.object(mcp_server, "build_mcp_server", return_value=DoneServer()):
            with patch.object(FcapzMcpSession, "shutdown") as shutdown:
                self.assertEqual(main([]), 0)

        shutdown.assert_called_once()

    def test_shutdown_reports_json_summary_for_close_errors(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        stderr = io.StringIO()

        with patch.object(session, "close", side_effect=RuntimeError("ela bad")):
            with patch.object(session, "eio_close", side_effect=RuntimeError("eio bad")):
                with redirect_stderr(stderr):
                    session.shutdown()

        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["event"], "shutdown_errors")
        self.assertEqual(payload["errors"][0]["step"], "close")
        self.assertEqual(payload["errors"][0]["type"], "RuntimeError")
        self.assertEqual(payload["errors"][0]["message"], "ela bad")
        self.assertNotIn("traceback", payload["errors"][0])

    def test_shutdown_includes_traceback_when_env_set(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        stderr = io.StringIO()

        with patch.dict("os.environ", {"FCAPZ_MCP_DEBUG_SHUTDOWN": "YES"}):
            with patch.object(session, "close", side_effect=RuntimeError("ela bad")):
                with redirect_stderr(stderr):
                    session.shutdown()

        payload = json.loads(stderr.getvalue())
        self.assertIn("Traceback", payload["errors"][0]["traceback"])

    def test_status_returns_copies(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session.probe()

        status = session.status()
        status["last_probe"]["depth"] = 1
        self.assertEqual(session.last_probe["depth"], 1024)

    def test_rpc_timeout_reports_clean_error(self):
        rpc = BlockingRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01),
        )

        try:
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                session.connect()
            with self.assertRaisesRegex(RuntimeError, "previous fcapz RPC call"):
                session.probe()
        finally:
            rpc.release.set()
            worker = session._active_rpc_worker
            if worker is not None:
                worker.join(timeout=1.0)

    def test_rpc_timeout_cancels_backend_and_allows_next_call(self):
        rpc = CancellableBlockingRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01),
        )

        with self.assertRaisesRegex(TimeoutError, "was cancelled after"):
            session.connect()

        self.assertTrue(rpc.cancelled)
        self.assertIsNone(session._active_rpc_worker)
        self.assertFalse(session.status()["connected"])
        self.assertEqual(session.status()["last_capture_size_bytes"], None)

        rpc.handle = FakeRpc().handle  # type: ignore[method-assign]
        self.assertEqual(session.probe()["probe"]["sample_width"], 8)

    def test_late_worker_result_is_salvaged_not_discarded(self):
        # A completed call that overran the watchdog (no cancel hook, finishes
        # within the grace window) must return its result, not raise a spurious
        # TimeoutError and wipe session state — the finding-1 regression.
        rpc = SlowRpc(delay=0.06)
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01, rpc_cancel_grace_sec=1.0),
        )

        result = session.probe()
        self.assertEqual(result["probe"]["sample_width"], 8)
        self.assertEqual(rpc.calls, 1)
        # Slot reclaimed and no desync reset fired: the next call proceeds.
        self.assertIsNone(session._active_rpc_worker)
        self.assertFalse(session.status()["rpc_busy"])
        self.assertEqual(session.probe()["probe"]["depth"], 1024)

    def test_rpc_timeout_reports_cancel_failure(self):
        rpc = FailingCancelRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(
                rpc_timeout_sec=0.01,
                rpc_cancel_grace_sec=0.01,
            ),
        )
        stderr = io.StringIO()

        try:
            with redirect_stderr(stderr):
                with self.assertRaisesRegex(TimeoutError, "still running"):
                    session.connect()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["event"], "rpc_cancel_error")
            self.assertEqual(payload["errors"][0]["step"], "cancel_active")
            self.assertEqual(payload["errors"][0]["cmd"], "connect")
            self.assertEqual(payload["errors"][0]["type"], "RuntimeError")
            self.assertEqual(payload["errors"][0]["message"], "cancel bad")
            with self.assertRaisesRegex(RuntimeError, "previous fcapz RPC call"):
                session.probe()
        finally:
            rpc.release.set()
            worker = session._active_rpc_worker
            if worker is not None:
                worker.join(timeout=1.0)

    def test_rpc_timeout_keeps_slot_when_cancelled_worker_does_not_exit(self):
        rpc = StubbornCancelRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(
                rpc_timeout_sec=0.01,
                rpc_cancel_grace_sec=0.01,
            ),
        )

        try:
            with self.assertRaisesRegex(TimeoutError, "still running"):
                session.connect()
            self.assertTrue(rpc.cancelled)
            self.assertIsNotNone(session._active_rpc_worker)
            with self.assertRaisesRegex(RuntimeError, "previous fcapz RPC call"):
                session.probe()
        finally:
            rpc.release.set()
            worker = session._active_rpc_worker
            if worker is not None:
                worker.join(timeout=1.0)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_build_mcp_server_registers_tools_when_sdk_available(self):
        from fcapz.mcp_server import build_mcp_server

        server = build_mcp_server(FcapzMcpSession(rpc=FakeRpc()))
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        self.assertEqual(
            set(tools),
            {
                "fcapz_connect",
                "fcapz_close",
                "fcapz_probe",
                "fcapz_list_cores",
                "fcapz_capture",
                "fcapz_drop_last_capture",
                "fcapz_get_last_capture",
                "fcapz_get_last_capture_chunk",
                "fcapz_configure",
                "fcapz_arm",
                "fcapz_capture_wait",
                "fcapz_capture_status",
                "fcapz_disarm",
                "fcapz_eio_connect",
                "fcapz_eio_close",
                "fcapz_eio_read",
                "fcapz_eio_write",
                "fcapz_axi_connect",
                "fcapz_axi_close",
                "fcapz_axi_read",
                "fcapz_axi_write",
                "fcapz_axi_write_block",
                "fcapz_axi_dump",
                "fcapz_uart_connect",
                "fcapz_uart_close",
                "fcapz_uart_send",
                "fcapz_uart_recv",
                "fcapz_uart_status",
                "fcapz_status",
            },
        )
        self.assertTrue(tools["fcapz_probe"].annotations.readOnlyHint)
        self.assertTrue(tools["fcapz_eio_write"].annotations.destructiveHint)
        self.assertTrue(tools["fcapz_axi_write"].annotations.destructiveHint)
        self.assertTrue(tools["fcapz_uart_send"].annotations.destructiveHint)
        # capture_wait consumes the armed capture and is capability-gated, so it
        # must not advertise itself as read-only; disarm mutates FSM state.
        self.assertFalse(tools["fcapz_capture_wait"].annotations.readOnlyHint)
        self.assertTrue(tools["fcapz_disarm"].annotations.destructiveHint)
        self.assertTrue(tools["fcapz_list_cores"].annotations.readOnlyHint)
        self.assertEqual(
            tools["fcapz_axi_read"].inputSchema["properties"]["addr"]["type"],
            "integer",
        )
        self.assertEqual(
            tools["fcapz_axi_write"].inputSchema["properties"]["wstrb"]["default"],
            15,
        )

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_resources_are_compact_and_report_unavailable_when_empty(self):
        from fcapz.mcp_server import build_mcp_server

        server = build_mcp_server(FcapzMcpSession(rpc=FakeRpc()))
        resources = {
            str(resource.uri): resource
            for resource in asyncio.run(server.list_resources())
        }

        self.assertIn("fcapz://last-probe", resources)
        self.assertEqual(str(resources["fcapz://last-probe"].uri), "fcapz://last-probe")
        body = asyncio.run(server.read_resource("fcapz://last-probe"))
        self.assertEqual(body[0].content, '{"available":false}')


if __name__ == "__main__":
    unittest.main()
