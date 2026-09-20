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
from fcapz.mcp_server import (
    _ERROR_ACTIONS,
    _with_progress,
    _coded_error,
    _error_code,
    CaptureConfigDict,
    FcapzMcpError,
    SessionStatus,
    _CommandState,
    _HardwareCommand,
    FcapzMcpSession,
    McpCapabilities,
    McpWatchdogTimeout,
    main,
)


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

    def _drain_owner(self, session, rpc, timeout=2.0):
        """Let a blocked owner finish so its recovery runs before teardown."""
        rpc.release.set()
        owner = session._owner
        if owner is not None:
            owner.join(timeout=timeout)

    def test_rpc_timeout_poisons_the_session_until_it_reconciles(self):
        # No cancel hook (the production case): the watchdog cannot stop the
        # call, so the session refuses work rather than pretending it is fine.
        rpc = BlockingRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01, rpc_cancel_grace_sec=0.01),
        )

        try:
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                session.connect()
            self.assertEqual(session.status()["session_state"], "poisoned")
            with self.assertRaisesRegex(FcapzMcpError, "recovering from an abandoned"):
                session.probe()
        finally:
            self._drain_owner(session, rpc)

    def test_abandoned_command_is_reconciled_not_committed(self):
        # The abandoned connect eventually succeeds inside the RPC layer. Its
        # commit must NOT land: the wrapper tears the board session down and
        # reports disconnected rather than silently going connected later.
        rpc = BlockingRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01, rpc_cancel_grace_sec=0.01),
        )
        with self.assertRaises(McpWatchdogTimeout):
            session.connect()

        rpc.release.set()
        deadline = time.time() + 2.0
        while session.status()["session_state"] != "ready" and time.time() < deadline:
            time.sleep(0.01)

        status = session.status()
        self.assertEqual(status["session_state"], "ready")
        self.assertFalse(status["connected"], "abandoned connect must not commit")
        self.assertIsNone(status["active_rpc_cmd"])
        # And the session takes work again once it has reconciled.
        session.rpc = FakeRpc()
        self.assertEqual(session.probe()["probe"]["sample_width"], 8)

    def test_rpc_timeout_cancels_backend_and_allows_next_call(self):
        rpc = CancellableBlockingRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01),
        )

        with self.assertRaisesRegex(TimeoutError, "was cancelled after"):
            session.connect()

        self.assertTrue(rpc.cancelled)
        self.assertFalse(session.status()["connected"])
        self.assertEqual(session.status()["last_capture_size_bytes"], None)
        self.assertEqual(session.status()["session_state"], "ready")

        rpc.handle = FakeRpc().handle  # type: ignore[method-assign]
        self.assertEqual(session.probe()["probe"]["sample_width"], 8)

    def test_late_worker_result_is_salvaged_not_discarded(self):
        # A completed call that overran the watchdog (no cancel hook, finishes
        # within the grace window) must return its result, not raise a spurious
        # TimeoutError and wipe session state.
        rpc = SlowRpc(delay=0.06)
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01, rpc_cancel_grace_sec=1.0),
        )

        result = session.probe()
        self.assertEqual(result["probe"]["sample_width"], 8)
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(session.status()["session_state"], "ready")
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
            with self.assertRaisesRegex(FcapzMcpError, "recovering from an abandoned"):
                session.probe()
        finally:
            self._drain_owner(session, rpc)

    def test_session_stays_poisoned_while_cancelled_call_does_not_exit(self):
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
            self.assertEqual(session.status()["session_state"], "poisoned")
            with self.assertRaisesRegex(FcapzMcpError, "recovering from an abandoned"):
                session.probe()
        finally:
            self._drain_owner(session, rpc)

    def test_close_is_not_lost_while_a_connect_is_in_flight(self):
        # The close guard reads connection flags, which describe the
        # pre-command world while a connect is still running. It must not
        # conclude there is nothing to close and silently drop the request.
        class SlowConnectRpc:
            def __init__(self):
                self.log = []

            def handle(self, req):
                self.log.append(req["cmd"])
                if req["cmd"] == "connect":
                    time.sleep(0.15)
                return {"ok": True, "schema_version": "test"}

        rpc = SlowConnectRpc()
        session = FcapzMcpSession(
            rpc=rpc, capabilities=McpCapabilities(rpc_timeout_sec=5.0)
        )
        worker = threading.Thread(target=session.connect, daemon=True)
        worker.start()
        try:
            time.sleep(0.05)
            with self.assertRaisesRegex(FcapzMcpError, "busy running 'connect'"):
                session.close()
        finally:
            worker.join(timeout=2.0)

        self.assertTrue(session.connected)
        self.assertEqual(rpc.log, ["connect"])
        # Retrying actually reaches the hardware.
        session.close()
        self.assertFalse(session.connected)
        self.assertEqual(rpc.log, ["connect", "close"])

    def test_uart_close_commits_through_the_owner(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)
        session.uart_connect()
        self.assertTrue(session.uart_connected)

        session.uart_close()

        self.assertFalse(session.uart_connected)
        self.assertIn("uart_close", [r["cmd"] for r in rpc.requests])

    def test_concurrent_call_is_refused_while_hardware_is_busy(self):
        # The JTAG wire takes one command at a time; a second caller must be
        # told so rather than queued behind a minutes-long capture.
        rpc = BlockingRpc()
        session = FcapzMcpSession(
            rpc=rpc, capabilities=McpCapabilities(rpc_timeout_sec=5.0)
        )
        first = threading.Thread(target=lambda: session.connect(), daemon=True)
        first.start()
        try:
            deadline = time.time() + 2.0
            while not session.status()["rpc_busy"] and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(session.status()["session_state"], "busy")
            with self.assertRaisesRegex(FcapzMcpError, "busy running 'connect'"):
                session.probe()
        finally:
            rpc.release.set()
            first.join(timeout=2.0)
        self.assertEqual(session.status()["session_state"], "ready")

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_disabled_tools_are_not_advertised(self):
        # A tool that can only answer PermissionError is worse than absent:
        # the agent plans around it and pays for its schema every request.
        from fcapz.mcp_server import build_mcp_server

        def names(**caps):
            server = build_mcp_server(
                FcapzMcpSession(rpc=FakeRpc(), capabilities=McpCapabilities(**caps))
            )
            return {tool.name for tool in asyncio.run(server.list_tools())}

        writes = {
            "fcapz_eio_write",
            "fcapz_axi_write",
            "fcapz_axi_write_block",
            "fcapz_uart_send",
        }
        capture = {
            "fcapz_capture",
            "fcapz_capture_wait",
            "fcapz_configure",
            "fcapz_arm",
            "fcapz_disarm",
        }

        default = names()
        self.assertFalse(writes & default, "write tools are off by default")
        self.assertTrue(capture <= default, "capture is on by default")

        read_only = names(allow_capture=False)
        self.assertFalse((writes | capture) & read_only)
        # Read-only still exposes the read side.
        self.assertIn("fcapz_probe", read_only)
        self.assertIn("fcapz_axi_read", read_only)
        self.assertIn("fcapz_capture_status", read_only)

        self.assertTrue(writes <= names(
            allow_eio_write=True, allow_axi_write=True, allow_uart_send=True
        ))

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_gating_does_not_replace_enforcement(self):
        # The session must still refuse a disabled operation even if some
        # caller reaches it directly.
        session = FcapzMcpSession(rpc=FakeRpc(), capabilities=McpCapabilities())
        with self.assertRaises(PermissionError):
            session.eio_write(1)
        with self.assertRaises(PermissionError):
            session.axi_write(0, 1)
        with self.assertRaises(PermissionError):
            session.uart_send(text="x")

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_build_mcp_server_registers_tools_when_sdk_available(self):
        from fcapz.mcp_server import build_mcp_server

        # Every write capability on, so the full surface is advertised.
        server = build_mcp_server(
            FcapzMcpSession(
                rpc=FakeRpc(),
                capabilities=McpCapabilities(
                    allow_eio_write=True,
                    allow_axi_write=True,
                    allow_uart_send=True,
                ),
            )
        )
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
                "fcapz_axi_transactions",
                "fcapz_get_capture_samples",
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


class CloseAllRpc(FakeRpc):
    """Models the real RpcServer: `close` is _close_all(), not an ELA-only close."""

    def __init__(self):
        super().__init__()
        self.open = {"ela": False, "eio": False, "axi": False, "uart": False}

    def handle(self, req):
        cmd = req["cmd"]
        if cmd == "connect":
            self.open["ela"] = True
        elif cmd == "eio_connect":
            self.open["eio"] = True
        elif cmd == "axi_connect":
            self.open["axi"] = True
        elif cmd == "uart_connect":
            self.open["uart"] = True
        elif cmd == "close":
            self.open.update(ela=False, eio=False, axi=False, uart=False)
        return super().handle(req)


class RegressionTests(unittest.TestCase):
    """Bugs found in review; each asserts the specific failure that was fixed."""

    _WIDE = 0xDEADBEEF_CAFEBABE_12345678_9ABCDEF0_11223344  # 160-bit AXI sample

    def test_wide_sample_values_survive_a_json_number_client(self):
        # JS MCP clients parse JSON numbers as doubles, rounding above 2**53-1.
        session = FcapzMcpSession(rpc=FakeRpc())
        session._store_capture({
            "ok": True,
            "format": "json",
            "result": {
                "sample_width": 160,
                "trigger": {"mode": 1, "value": self._WIDE, "mask": self._WIDE},
                "samples": [{"index": 0, "value": self._WIDE}, {"index": 1, "value": 7}],
            },
        })
        payload = session.last_capture

        self.assertEqual(payload["value_encoding"], "hex")
        samples = payload["result"]["samples"]
        # All-or-nothing per list: no mixing ints and hex strings.
        self.assertEqual(samples[0]["value"], hex(self._WIDE))
        self.assertEqual(samples[1]["value"], "0x7")
        self.assertEqual(payload["result"]["trigger"]["value"], hex(self._WIDE))
        # The value is exact after a real JSON round-trip.
        reparsed = json.loads(json.dumps(payload))
        self.assertEqual(int(reparsed["result"]["samples"][0]["value"], 16), self._WIDE)

    def test_narrow_capture_encoding_is_unchanged(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        samples = [{"index": 0, "value": 123}, {"index": 1, "value": (1 << 53) - 1}]
        session._store_capture({"ok": True, "result": {"samples": list(samples)}})
        payload = session.last_capture

        self.assertEqual(payload["result"]["samples"], samples)
        self.assertNotIn("value_encoding", payload)

    def test_close_clears_every_subsystem_flag(self):
        # RPC close tears down EIO/AXI/UART too, so the wrapper must not keep
        # advertising them as connected.
        rpc = CloseAllRpc()
        session = FcapzMcpSession(rpc=rpc)
        session.connect()
        session.eio_connect()
        session.axi_connect()

        session.close()

        self.assertFalse(any(rpc.open.values()))
        self.assertFalse(session.connected)
        self.assertFalse(session.eio_connected)
        self.assertFalse(session.axi_connected)
        self.assertFalse(session.uart_connected)

    def test_close_releases_a_side_only_session(self):
        # Without an ELA connection, close used to short-circuit and leave the
        # EIO controller open on the board.
        rpc = CloseAllRpc()
        session = FcapzMcpSession(rpc=rpc)
        session.eio_connect()
        self.assertTrue(rpc.open["eio"])

        session.close()

        self.assertFalse(rpc.open["eio"])
        self.assertFalse(session.eio_connected)

    def test_chunk_rejects_a_window_too_small_for_one_character(self):
        # Returning next_offset == offset here loops the caller forever.
        session = FcapzMcpSession(rpc=FakeRpc())
        session._store_capture({"ok": True, "note": "µs"})
        offset = session._capture_cache.json_bytes.index("µ".encode())

        with self.assertRaisesRegex(ValueError, "max_bytes >= 4"):
            session.get_last_capture_chunk(offset=offset, max_bytes=1)

        # A window that can hold the character still works and advances.
        chunk = session.get_last_capture_chunk(offset=offset, max_bytes=4)
        self.assertTrue(chunk["chunk"].startswith("µ"))
        self.assertNotEqual(chunk["next_offset"], offset)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_tool_annotations_match_real_behavior(self):
        from fcapz.mcp_server import build_mcp_server

        def tools_for(**caps):
            server = build_mcp_server(
                FcapzMcpSession(rpc=FakeRpc(), capabilities=McpCapabilities(**caps))
            )
            return {tool.name: tool for tool in asyncio.run(server.list_tools())}

        # Receiving drains the UART RX FIFO, so it is not read-only.
        self.assertFalse(tools_for()["fcapz_uart_recv"].annotations.readOnlyHint)
        # connect is destructive exactly when `program=` can reflash the part.
        self.assertFalse(tools_for()["fcapz_connect"].annotations.destructiveHint)
        self.assertTrue(
            tools_for(allow_program=True)["fcapz_connect"].annotations.destructiveHint
        )


def _axi_capture_payload(count=5, anomalies=(1, 3)):
    """A capture payload shaped like one the RPC layer decodes."""
    txns = []
    for i in range(count):
        txn = {
            "index": i,
            "kind": "write" if i % 2 == 0 else "read",
            "addr": f"0x{0x1000 + i * 4:08x}",
            "data": f"0x{0xAA00 + i:08x}",
            "resp": "SLVERR" if i in anomalies else "OKAY",
            "cycles": {"resp": i * 4},
        }
        if i in anomalies:
            txn["flags"] = ["error_response"]
        txns.append(txn)
    return {
        "ok": True,
        "format": "json",
        "sample_count": 64,
        "result": {"samples": [{"index": 0, "value": 0}]},
        "axi": {
            "protocol": "axi4lite",
            "addr_width": 32,
            "data_width": 32,
            "transaction_count": count,
            "write_count": sum(1 for t in txns if t["kind"] == "write"),
            "read_count": sum(1 for t in txns if t["kind"] == "read"),
            "error_count": len(anomalies),
            "anomaly_count": len(anomalies),
            "max_latency": 7,
            "transactions": txns,
        },
    }


def _sample_capture(count=6, width=9, pretrigger=2, probes=True):
    payload = {
        "ok": True,
        "format": "json",
        "result": {
            "sample_width": width,
            "pretrigger": pretrigger,
            "posttrigger": max(count - pretrigger - 1, 0),
            "samples": [
                {"index": i, "value": (i & 0xFF) | ((i % 2) << 8)} for i in range(count)
            ],
        },
    }
    if probes:
        payload["probes"] = [
            {"name": "addr", "width": 8, "lsb": 0},
            {"name": "flag", "width": 1, "lsb": 8},
        ]
    return payload


class SegmentedCaptureTests(unittest.TestCase):
    """A segmented core must not be silently reduced to segment 0."""

    @staticmethod
    def _payload():
        probes = [
            {"name": "addr", "width": 8, "lsb": 0},
            {"name": "flag", "width": 1, "lsb": 8},
        ]
        def _seg(tag, base):
            return {
                "segment": tag,
                "probes": probes,
                "samples": [
                    {"index": i, "value": base + i} for i in range(3)
                ],
            }
        return {
            "ok": True,
            "format": "json",
            "segments": [_seg(0, 0x00), _seg(1, 0x10)],
            "result": {
                "segments": [
                    {"samples": [{"index": i, "value": 0x00 + i} for i in range(3)]},
                    {"samples": [{"index": i, "value": 0x10 + i} for i in range(3)]},
                ]
            },
        }

    def test_capture_can_ask_for_every_segment(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session.capture(segments=True)
        self.assertTrue(session.rpc.requests[-1]["segments"])

        session.capture()
        self.assertNotIn("segments", session.rpc.requests[-1])

    def test_capture_wait_can_ask_for_every_segment(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session.capture_wait(segments=True)
        self.assertTrue(session.rpc.requests[-1]["segments"])

    def test_named_fields_resolve_against_a_per_segment_probe_map(self):
        # A segmented payload has no top-level `probes`; reading only there
        # made named fields disappear on exactly these captures.
        session = FcapzMcpSession(rpc=FakeRpc())
        session._store_capture(self._payload())

        page = session.capture_samples(start=0, count=6, fields=["addr"])

        self.assertEqual(page["total"], 6)
        self.assertEqual([s["segment"] for s in page["samples"]], [0, 0, 0, 1, 1, 1])
        self.assertEqual(page["samples"][3]["addr"], "0x10")

    def test_the_summary_does_not_inline_every_segment(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        summary = session._store_capture(self._payload())

        # Neither the per-segment serializations nor the raw sample lists.
        self.assertNotIn("segments", summary)
        self.assertNotIn("result", summary)


class WideEioValueTests(unittest.TestCase):
    """EIO vectors can be wider than a JSON number, in both directions."""

    class _WideEioRpc(FakeRpc):
        def handle(self, req):
            self.requests.append(dict(req))
            if req["cmd"] == "eio_read":
                value = (1 << 80) | 0x1234
                return {"ok": True, "value": value, "value_hex": hex(value)}
            return {"ok": True}

    def test_a_wide_read_is_handed_over_exactly(self):
        session = FcapzMcpSession(rpc=self._WideEioRpc())
        out = session.eio_read()

        self.assertEqual(out["value_encoding"], "hex")
        self.assertEqual(int(out["value"], 16), (1 << 80) | 0x1234)
        # The number and the hex string must not disagree after a JS client
        # has rounded one of them.
        self.assertEqual(int(out["value"], 16), int(out["value_hex"], 16))

    def test_a_narrow_read_stays_a_number(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session.eio_connect()
        out = session.eio_read()
        self.assertNotIn("value_encoding", out)

    def test_a_wide_write_can_be_expressed_as_a_string(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(), capabilities=McpCapabilities(allow_eio_write=True)
        )
        session.eio_write("0x1" + "0" * 20)
        self.assertEqual(session.rpc.requests[-1]["value"], "0x1" + "0" * 20)

    def test_a_write_string_must_actually_be_a_number(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(), capabilities=McpCapabilities(allow_eio_write=True)
        )
        with self.assertRaisesRegex(ValueError, "base-prefixed"):
            session.eio_write("wide")


class NonFiniteTimeoutTests(unittest.TestCase):
    """NaN slips past every ordered comparison and then never expires."""

    def test_a_nan_tool_timeout_is_rejected(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        with self.assertRaisesRegex(ValueError, "finite"):
            session.capture(timeout=float("nan"))

    def test_an_infinite_tool_timeout_is_rejected(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        with self.assertRaises(ValueError):
            session.capture(timeout=float("inf"))


class OwnerRecoveryRaceTests(unittest.TestCase):
    """The watchdog and the owner's recovery race for the same session."""

    def test_a_late_poison_does_not_wedge_a_reconciled_session(self):
        # done.wait() can miss its deadline by a hair while recovery is
        # finishing. Poisoning unconditionally after that leaves a flag with
        # nothing left to clear it, and every later call is refused forever.
        session = FcapzMcpSession(rpc=FakeRpc())
        cmd = _HardwareCommand(req={"cmd": "connect"}, commit=lambda r: r)
        cmd.state = _CommandState.RECONCILED

        with self.assertRaisesRegex(McpWatchdogTimeout, "torn down"):
            session._poison(cmd, "connect", 0.01)

        self.assertFalse(session._poisoned)
        session.connect()
        self.assertTrue(session.connected)

    def test_a_cancelled_call_always_leaves_the_session_usable(self):
        # Zero grace makes done.wait() give up while recovery is still in
        # flight -- the exact interleaving that used to poison permanently.
        rpc = CancellableBlockingRpc()
        session = FcapzMcpSession(
            rpc=rpc,
            capabilities=McpCapabilities(rpc_timeout_sec=0.01, rpc_cancel_grace_sec=0.0),
        )
        with self.assertRaises(McpWatchdogTimeout):
            session.connect()

        owner = session._owner
        if owner is not None:
            owner.join(timeout=2.0)
        self.assertFalse(session._poisoned)
        self.assertFalse(session.connected)

    def test_a_local_close_resets_while_it_still_holds_the_lock(self):
        # Deciding "nothing is open" and then acting on it in a second hold
        # let a connect commit in between, leaving the board connected and
        # the wrapper saying otherwise.
        session = FcapzMcpSession(rpc=FakeRpc())
        held = []

        settled = session._closed_locally(
            "connected", reset=lambda: held.append(session._rpc_lock._is_owned())
        )

        self.assertTrue(settled)
        self.assertEqual(held, [True])

    def test_a_local_close_defers_to_a_command_in_flight(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session._active_rpc_cmd = "connect"
        called = []
        try:
            self.assertFalse(
                session._closed_locally("connected", reset=lambda: called.append(1))
            )
        finally:
            session._active_rpc_cmd = None
        self.assertEqual(called, [])


class TypedToolSchemaTests(unittest.TestCase):
    """Closed value sets belong in the schema, not only in the error path."""

    def test_the_accepted_config_keys_come_from_the_published_schema(self):
        # Two hand-maintained lists would drift, and the drift would show up
        # as a field the schema advertises and the session rejects.
        self.assertEqual(
            FcapzMcpSession._CAPTURE_CONFIG_KEYS,
            frozenset(CaptureConfigDict.__annotations__),
        )

    def test_an_unknown_config_field_is_still_refused(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        with self.assertRaisesRegex(ValueError, "unsupported capture config"):
            session.capture(config={"nonsense": 1})

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_enums_reach_the_client_as_enums(self):
        from fcapz.mcp_server import build_mcp_server

        server = build_mcp_server(FcapzMcpSession(rpc=FakeRpc()))
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

        connect = tools["fcapz_connect"].inputSchema["properties"]["backend"]
        self.assertEqual(connect["enum"], ["hw_server", "openocd", "usb_blaster"])

        capture = tools["fcapz_capture"].inputSchema
        self.assertEqual(
            capture["properties"]["format"]["enum"], ["json", "csv", "vcd"]
        )
        config = capture["$defs"]["CaptureConfigDict"]["properties"]
        self.assertEqual(
            config["trigger_mode"]["enum"], ["value_match", "edge_detect", "both"]
        )
        # Bit vectors must still accept a base-prefixed string: a value wider
        # than 53 bits cannot survive a JSON number.
        self.assertIn(
            {"type": "string"}, config["trigger_value"]["anyOf"]
        )

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_the_config_schema_names_every_accepted_field(self):
        from fcapz.mcp_server import build_mcp_server

        server = build_mcp_server(FcapzMcpSession(rpc=FakeRpc()))
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        config = tools["fcapz_capture"].inputSchema["$defs"]["CaptureConfigDict"]

        self.assertEqual(
            set(config["properties"]), FcapzMcpSession._CAPTURE_CONFIG_KEYS
        )


class OutputSchemaTests(unittest.TestCase):
    """A declared outputSchema deletes whatever it does not name."""

    @staticmethod
    def _loaded_session():
        session = FcapzMcpSession(rpc=FakeRpc())
        session._store_capture({
            "ok": True,
            "format": "json",
            "probes": [{"name": "awaddr", "width": 8, "lsb": 0}],
            "result": {
                "sample_width": 9,
                "pretrigger": 1,
                "posttrigger": 1,
                "samples": [{"index": i, "value": i} for i in range(3)],
            },
            "axi": {
                "transactions": [
                    {"index": 0, "kind": "write", "addr": "0x4", "flags": []}
                ]
            },
        })
        return session

    def test_status_reports_exactly_what_its_schema_declares(self):
        # Add a status field without adding it here and FastMCP would drop it
        # from structuredContent, silently, for every client.
        session = FcapzMcpSession(rpc=FakeRpc())
        self.assertEqual(
            set(session.status()), set(SessionStatus.__annotations__)
        )

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_typed_tools_lose_nothing_on_the_way_out(self):
        from fcapz.mcp_server import build_mcp_server

        app = build_mcp_server(self._loaded_session())
        calls = [
            ("fcapz_get_capture_samples", {"count": 2}),
            ("fcapz_get_capture_samples", {"count": 2, "fields": ["awaddr"]}),
            ("fcapz_axi_transactions", {}),
            ("fcapz_get_last_capture_chunk", {"max_bytes": 40}),
            ("fcapz_status", {}),
        ]
        for name, args in calls:
            with self.subTest(tool=name, args=args):
                content, structured = asyncio.run(app.call_tool(name, args))
                self.assertEqual(json.loads(content[0].text), structured)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_the_empty_shapes_survive_too(self):
        from fcapz.mcp_server import build_mcp_server

        # Nothing cached: these return {"available": false} alone.
        app = build_mcp_server(FcapzMcpSession(rpc=FakeRpc()))
        for name in (
            "fcapz_get_capture_samples",
            "fcapz_axi_transactions",
            "fcapz_get_last_capture_chunk",
        ):
            with self.subTest(tool=name):
                content, structured = asyncio.run(app.call_tool(name, {}))
                self.assertEqual(json.loads(content[0].text), structured)
                self.assertIs(structured["available"], False)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_rpc_passthrough_tools_stay_open(self):
        from fcapz.mcp_server import build_mcp_server

        # Their keys vary with backend and core revision. Naming a subset
        # would delete the rest from structuredContent, so they must not be
        # narrowed -- this guards against someone "finishing the job".
        app = build_mcp_server(FcapzMcpSession(rpc=FakeRpc()))
        tools = {tool.name: tool for tool in asyncio.run(app.list_tools())}
        typed = {
            "fcapz_get_capture_samples",
            "fcapz_axi_transactions",
            "fcapz_get_last_capture_chunk",
            "fcapz_status",
        }
        for name, tool in tools.items():
            if name in typed:
                self.assertNotIn("additionalProperties", tool.outputSchema, name)
            else:
                self.assertTrue(
                    tool.outputSchema.get("additionalProperties"), name
                )


class ErrorCodeTests(unittest.TestCase):
    """MCP has no structured error channel, so the text has to carry it."""

    class _FailingRpc:
        def __init__(self, error):
            self.error = error
            self.requests = []

        def handle(self, req):
            self.requests.append(dict(req))
            return {"ok": False, "error": self.error}

    def test_every_code_says_whether_a_retry_could_help(self):
        for code, (retryable, action) in _ERROR_ACTIONS.items():
            with self.subTest(code=code):
                self.assertIsInstance(retryable, bool)
                self.assertTrue(action.strip())

    def test_failures_are_classified(self):
        cases = [
            (PermissionError("nope"), "not_permitted"),
            (FileNotFoundError("gone"), "not_found"),
            (McpWatchdogTimeout("abandoned"), "watchdog_timeout"),
            (TimeoutError("slow"), "timeout"),
            (ValueError("bad arg"), "invalid_argument"),
            (FcapzMcpError("ela not connected"), "not_connected"),
            (FcapzMcpError("readback mismatch"), "hardware_error"),
            (FcapzMcpError("busy", code="busy"), "busy"),
            (KeyError("oops"), "internal"),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__, expected=expected):
                self.assertEqual(_error_code(exc), expected)

    def test_a_watchdog_timeout_is_not_just_a_timeout(self):
        # They need different remedies: one says retry, the other says
        # reconnect first because the session was torn down.
        self.assertNotEqual(
            _ERROR_ACTIONS["timeout"], _ERROR_ACTIONS["watchdog_timeout"]
        )

    def test_the_rendered_error_is_one_json_object(self):
        body = json.loads(str(_coded_error(PermissionError("EIO writes are disabled"))))

        self.assertEqual(body["code"], "not_permitted")
        self.assertEqual(body["message"], "EIO writes are disabled")
        self.assertFalse(body["retryable"])
        self.assertIn("restart", body["action"])

    def test_the_rendered_error_keeps_its_exception_type(self):
        # Callers inside the process still branch on the type; only the text
        # changes shape.
        self.assertIsInstance(_coded_error(PermissionError("x")), PermissionError)
        self.assertIsInstance(_coded_error(McpWatchdogTimeout("x")), TimeoutError)

    def test_an_rpc_refusal_keeps_its_sentence_and_its_detail(self):
        session = FcapzMcpSession(
            rpc=self._FailingRpc({"type": "RuntimeError", "message": "eio not connected"})
        )
        with self.assertRaises(FcapzMcpError) as caught:
            session.eio_read()
        body = json.loads(str(_coded_error(caught.exception)))

        self.assertEqual(body["code"], "not_connected")
        self.assertEqual(body["message"], "eio not connected")
        self.assertEqual(body["detail"]["type"], "RuntimeError")
        self.assertTrue(body["retryable"])

    def test_busy_and_recovering_are_not_matched_by_prose(self):
        # Both are FcapzMcpError; their codes are set at the raise site so a
        # reworded message cannot silently reclassify them.
        session = FcapzMcpSession(rpc=FakeRpc())
        session._active_rpc_cmd = "capture"
        try:
            with self.assertRaises(FcapzMcpError) as caught:
                session.probe()
        finally:
            session._active_rpc_cmd = None
        self.assertEqual(_error_code(caught.exception), "busy")
        self.assertTrue(json.loads(str(_coded_error(caught.exception)))["retryable"])

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_a_tool_failure_reaches_the_client_coded(self):
        from fcapz.mcp_server import build_mcp_server

        app = build_mcp_server(
            FcapzMcpSession(
                rpc=self._FailingRpc({"type": "RuntimeError", "message": "no such tap"})
            )
        )
        with self.assertRaises(Exception) as caught:
            asyncio.run(app.call_tool("fcapz_connect", {}))

        text = str(caught.exception)
        body = json.loads(text[text.index("{"):])
        self.assertEqual(body["code"], "hardware_error")
        self.assertEqual(body["message"], "no such tap")
        self.assertIn("action", body)


class ProgressTests(unittest.TestCase):
    """A long capture must not silence the server, nor look like a hang."""

    class _Recorder:
        def __init__(self):
            self.calls = []

        async def report_progress(self, progress, total, message):
            self.calls.append((progress, total, message))

    class _Hostile:
        async def report_progress(self, *args):
            raise RuntimeError("no progress token")

    def test_progress_ticks_while_the_call_runs(self):
        ctx = self._Recorder()

        result = asyncio.run(
            _with_progress(ctx, "capture", lambda: time.sleep(2.2) or "done", 10.0)
        )

        self.assertEqual(result, "done")
        self.assertGreaterEqual(len(ctx.calls), 2)
        progress, total, message = ctx.calls[0]
        self.assertEqual(total, 10.0)
        self.assertLessEqual(progress, total)
        self.assertIn("capture", message)

    def test_a_quick_call_reports_nothing(self):
        ctx = self._Recorder()
        self.assertEqual(asyncio.run(_with_progress(ctx, "capture", lambda: 7, 10.0)), 7)
        self.assertEqual(ctx.calls, [])

    def test_progress_never_reports_past_the_budget(self):
        ctx = self._Recorder()
        # Timeout smaller than the call: elapsed must clamp, not overshoot.
        asyncio.run(_with_progress(ctx, "capture", lambda: time.sleep(2.2), 1.0))
        self.assertTrue(all(p <= t for p, t, _ in ctx.calls), ctx.calls)

    def test_the_failure_is_the_call_s_own(self):
        # The task group must not turn it into an ExceptionGroup, or the
        # error-code layer would classify every failure as "internal".
        with self.assertRaisesRegex(ValueError, "bad"):
            asyncio.run(
                _with_progress(
                    self._Recorder(), "capture", self._raise_value_error, 1.0
                )
            )

    @staticmethod
    def _raise_value_error():
        raise ValueError("bad")

    def test_a_client_that_refuses_progress_still_gets_its_capture(self):
        result = asyncio.run(
            _with_progress(self._Hostile(), "capture", lambda: time.sleep(1.2) or 5, 9.0)
        )
        self.assertEqual(result, 5)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_a_blocking_tool_does_not_freeze_the_server(self):
        from fcapz.mcp_server import build_mcp_server

        class SlowRpc:
            def handle(self, req):
                time.sleep(0.6)
                return {"ok": True}

        app = build_mcp_server(FcapzMcpSession(rpc=SlowRpc()))

        async def go():
            ticks = []

            async def heartbeat():
                while True:
                    await asyncio.sleep(0.05)
                    ticks.append(1)

            beat = asyncio.create_task(heartbeat())
            await app.call_tool("fcapz_probe", {})
            beat.cancel()
            return ticks

        # FastMCP awaits a sync tool on the event loop, so without the
        # offload every JTAG round trip stopped the server answering
        # anything at all -- a 300 s capture for five minutes.
        self.assertGreater(len(asyncio.run(go())), 2)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK not installed")
    def test_the_progress_context_is_not_an_argument_the_agent_sees(self):
        from fcapz.mcp_server import build_mcp_server

        app = build_mcp_server(FcapzMcpSession(rpc=FakeRpc()))
        tools = {tool.name: tool for tool in asyncio.run(app.list_tools())}
        for name in ("fcapz_capture", "fcapz_capture_wait"):
            with self.subTest(tool=name):
                self.assertNotIn("ctx", tools[name].inputSchema["properties"])


class HostAllowlistTests(unittest.TestCase):
    """`host` reaches a network client, so it must not be wide open."""

    def test_defaults_to_loopback(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        session.connect(backend="hw_server")
        self.assertEqual(session.rpc.requests[-1]["host"], "127.0.0.1")

    def test_loopback_spellings_are_accepted(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        for host in ("127.0.0.1", "localhost", "::1"):
            self.assertEqual(session._validated_host(host), host)

    def test_other_hosts_are_refused(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        with self.assertRaisesRegex(PermissionError, "loopback only"):
            session.connect(backend="hw_server", host="192.168.1.50")

    def test_an_allowlisted_host_is_permitted(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(),
            capabilities=McpCapabilities(allowed_hosts=("192.168.1.50",)),
        )
        session.connect(backend="hw_server", host="192.168.1.50")
        self.assertEqual(session.rpc.requests[-1]["host"], "192.168.1.50")

    def test_status_reports_the_allowlist(self):
        session = FcapzMcpSession(
            rpc=FakeRpc(), capabilities=McpCapabilities(allowed_hosts=("h1",))
        )
        self.assertEqual(session.status()["capabilities"]["allowed_hosts"], ["h1"])


class ProbeFileRootTests(unittest.TestCase):
    """`probe_file` opens a path on the server, so it needs a root."""

    PROBE_JSON = json.dumps({
        "format": "fpgacapzero.probes.v1",
        "sample_width": 12,
        "sample_clock_hz": 50_000_000,
        "probes": [
            {"name": "addr", "width": 8, "lsb": 0},
            {"name": "flag", "width": 1, "lsb": 8},
        ],
    })

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.probe = self.root / "axi.prob"
        self.probe.write_text(self.PROBE_JSON, encoding="utf-8")
        self.addCleanup(self._dir.cleanup)

    def _session(self, **caps):
        return FcapzMcpSession(rpc=FakeRpc(), capabilities=McpCapabilities(**caps))

    def test_rejected_without_a_root(self):
        with self.assertRaisesRegex(PermissionError, "--probe-root"):
            self._session().capture(config={"probe_file": str(self.probe)})

    def test_the_probe_map_is_sent_inline_not_as_a_path(self):
        # RPC used to re-open the path a queue hop later, so what was checked
        # here and what was loaded there could differ.
        session = self._session(probe_root=self.root)
        session.capture(config={"probe_file": "axi.prob"})
        req = session.rpc.requests[-1]

        self.assertNotIn("probe_file", req)
        self.assertEqual(
            req["probes"],
            [
                {"name": "addr", "width": 8, "lsb": 0},
                {"name": "flag", "width": 1, "lsb": 8},
            ],
        )
        self.assertEqual(req["sample_width"], 12)
        self.assertEqual(req["sample_clock_hz"], 50_000_000)

    def test_the_caller_still_overrides_the_file(self):
        session = self._session(probe_root=self.root)
        session.capture(config={"probe_file": "axi.prob", "sample_width": 16})
        self.assertEqual(session.rpc.requests[-1]["sample_width"], 16)

    def test_probes_and_probe_file_cannot_both_be_given(self):
        session = self._session(probe_root=self.root)
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            session.capture(config={
                "probe_file": "axi.prob",
                "probes": [{"name": "a", "width": 1, "lsb": 0}],
            })

    def test_a_file_that_is_not_a_probe_map_is_refused_here(self):
        (self.root / "junk.prob").write_text("{}", encoding="utf-8")
        session = self._session(probe_root=self.root)
        with self.assertRaisesRegex(ValueError, "unsupported probe file format"):
            session.capture(config={"probe_file": "junk.prob"})

    def test_escaping_the_root_is_refused(self):
        session = self._session(probe_root=self.root)
        with self.assertRaises(PermissionError):
            session.capture(config={"probe_file": "../outside.prob"})

    def test_a_missing_file_is_reported_clearly(self):
        session = self._session(probe_root=self.root)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            session.capture(config={"probe_file": "nope.prob"})

    def test_configure_is_guarded_too(self):
        with self.assertRaisesRegex(PermissionError, "--probe-root"):
            self._session().configure(config={"probe_file": str(self.probe)})

    def test_captures_without_a_probe_file_are_unaffected(self):
        session = self._session()
        session.capture(config={"pretrigger": 8})
        self.assertEqual(session.rpc.requests[-1]["pretrigger"], 8)


class CaptureSamplePagingTests(unittest.TestCase):
    def _session(self, payload=None):
        session = FcapzMcpSession(rpc=FakeRpc())
        session._store_capture(payload if payload is not None else _sample_capture())
        return session

    def test_page_carries_the_context_needed_to_read_it(self):
        page = self._session().capture_samples(start=0, count=3)

        self.assertTrue(page["available"])
        self.assertEqual(page["total"], 6)
        self.assertEqual(page["count"], 3)
        self.assertEqual(page["trigger_index"], 2)
        self.assertEqual(page["sample_width"], 9)
        self.assertEqual(page["next_start"], 3)
        # Valid JSON on its own - the whole point versus byte chunks.
        self.assertEqual(json.loads(json.dumps(page))["count"], 3)

    def test_trigger_index_is_withheld_for_a_short_capture(self):
        # The analyzer takes the real length from hardware CAPTURE_LEN, which
        # can be shorter than pretrigger+posttrigger+1; the pretrigger count
        # then no longer locates the trigger, so reporting it would point at
        # the wrong sample.
        full = self._session(_sample_capture(count=6, pretrigger=2))
        self.assertEqual(full.capture_samples(count=1)["trigger_index"], 2)

        payload = _sample_capture(count=6, pretrigger=2)
        payload["result"]["posttrigger"] = 99  # length no longer consistent
        short = self._session(payload)
        self.assertIsNone(short.capture_samples(count=1)["trigger_index"])

    def test_trigger_index_is_null_without_the_window_fields(self):
        payload = _sample_capture()
        payload["result"].pop("posttrigger", None)
        session = self._session(payload)
        self.assertIsNone(session.capture_samples(count=1)["trigger_index"])

    def test_cursor_terminates_at_the_end(self):
        page = self._session().capture_samples(start=4, count=10)
        self.assertEqual(page["count"], 2)
        self.assertIsNone(page["next_start"])

    def test_named_fields_come_from_the_probe_map(self):
        session = self._session()
        page = session.capture_samples(count=2)

        self.assertEqual(page["fields"], ["addr", "flag"])
        self.assertEqual(page["samples"][1], {"index": 1, "addr": "0x1", "flag": "0x1"})

    def test_fields_can_be_narrowed(self):
        page = self._session().capture_samples(count=2, fields=["flag"])
        self.assertEqual(page["fields"], ["flag"])
        self.assertEqual(page["samples"][1], {"index": 1, "flag": "0x1"})

    def test_empty_fields_returns_the_packed_value(self):
        page = self._session().capture_samples(count=1, fields=[])
        self.assertEqual(page["samples"][0], {"index": 0, "value": "0x0"})
        self.assertIsNone(page["fields"])

    def test_unknown_field_names_are_rejected_with_the_available_set(self):
        with self.assertRaisesRegex(ValueError, "unknown field.*nope"):
            self._session().capture_samples(fields=["nope"])

    def test_named_fields_without_a_probe_map_explain_themselves(self):
        session = self._session(_sample_capture(probes=False))
        with self.assertRaisesRegex(ValueError, "no probe map"):
            session.capture_samples(fields=["addr"])
        # But raw values still page fine.
        self.assertEqual(session.capture_samples(count=1)["samples"][0]["value"], "0x0")

    def test_radix_int_is_honoured_but_never_for_wide_values(self):
        session = self._session()
        self.assertEqual(
            session.capture_samples(count=1, fields=[], radix="int")["samples"][0],
            {"index": 0, "value": 0},
        )
        wide = (1 << 60) | 1
        session._store_capture({
            "ok": True,
            "result": {"sample_width": 64, "pretrigger": 0,
                       "samples": [{"index": 0, "value": wide}]},
        })
        # Requested int, but an exact JSON number is impossible here.
        self.assertEqual(
            session.capture_samples(count=1, radix="int")["samples"][0]["value"],
            hex(wide),
        )

    def test_rejects_nonsense_arguments(self):
        session = self._session()
        with self.assertRaisesRegex(ValueError, "radix must be"):
            session.capture_samples(radix="octal")
        with self.assertRaisesRegex(ValueError, "start must be >= 0"):
            session.capture_samples(start=-1)
        with self.assertRaisesRegex(ValueError, "count must be > 0"):
            session.capture_samples(count=0)

    def test_page_size_is_capped(self):
        session = self._session(_sample_capture(count=2000))
        self.assertEqual(
            session.capture_samples(count=10_000)["count"],
            FcapzMcpSession._SAMPLES_MAX_PAGE,
        )

    def test_reports_unavailable_without_a_capture(self):
        self.assertEqual(
            FcapzMcpSession(rpc=FakeRpc()).capture_samples(),
            {
                "available": False,
                "reason": None,
                "total": 0,
                "start": 0,
                "count": 0,
                "next_start": None,
                "radix": "hex",
                "sample_width": None,
                "trigger_index": None,
                "samples": [],
                "segments": None,
                "fields": None,
            },
        )

    def test_explains_itself_for_a_non_json_capture(self):
        session = self._session({"ok": True, "format": "csv", "content": "1,2"})
        result = session.capture_samples()

        self.assertFalse(result["available"])
        self.assertIn('format="json"', result["reason"])

    def test_segmented_captures_page_every_segment(self):
        # Reading only segment 0 would silently hide the rest of the capture.
        def seg(index, base):
            return {
                "segment": index,
                "sample_width": 8,
                "pretrigger": 0,
                "posttrigger": 1,
                "samples": [{"index": i, "value": base + i} for i in range(2)],
            }

        session = self._session({
            "ok": True,
            "result": {"segments": [seg(0, 0x10), seg(1, 0x20)]},
        })
        page = session.capture_samples(count=10)

        self.assertEqual(page["total"], 4)
        self.assertEqual(page["segments"], 2)
        self.assertEqual([s["segment"] for s in page["samples"]], [0, 0, 1, 1])
        self.assertEqual(
            [s["value"] for s in page["samples"]],
            ["0x10", "0x11", "0x20", "0x21"],
        )
        # A concatenated index cannot locate the trigger.
        self.assertIsNone(page["trigger_index"])

    def test_reads_hex_encoded_wide_samples_back(self):
        # _store_capture hex-encodes wide values; paging must still slice them.
        wide = 0xDEADBEEF_CAFEBABE_12345678_9ABCDEF0_11223344
        session = self._session({
            "ok": True,
            "probes": [{"name": "low", "width": 32, "lsb": 0}],
            "result": {"sample_width": 160, "pretrigger": 0,
                       "samples": [{"index": 0, "value": wide}]},
        })
        page = session.capture_samples(count=1)

        self.assertEqual(page["samples"][0]["low"], "0x11223344")


class AxiTransactionToolTests(unittest.TestCase):
    def _session(self, payload=None):
        session = FcapzMcpSession(rpc=FakeRpc())
        session._store_capture(payload if payload is not None else _axi_capture_payload())
        return session

    def test_capture_summary_keeps_only_the_axi_headline(self):
        session = self._session()
        summary = session._capture_cache.summary

        self.assertNotIn("transactions", summary["axi"])
        self.assertEqual(summary["axi"]["transaction_count"], 5)
        self.assertEqual(summary["axi"]["error_count"], 2)
        self.assertIn("fcapz_axi_transactions", summary["axi"]["hint"])
        # The full decode is still cached for the paging tool.
        self.assertEqual(len(session.last_capture["axi"]["transactions"]), 5)

    def test_pages_transactions_with_a_cursor(self):
        session = self._session()

        first = session.axi_transactions(start=0, count=2)
        self.assertTrue(first["available"])
        self.assertEqual(first["total"], 5)
        self.assertEqual([t["index"] for t in first["transactions"]], [0, 1])
        self.assertEqual(first["next_start"], 2)

        last = session.axi_transactions(start=4, count=2)
        self.assertEqual([t["index"] for t in last["transactions"]], [4])
        self.assertIsNone(last["next_start"], "cursor must terminate")

    def test_each_page_is_valid_json_on_its_own(self):
        # The point of paging transactions rather than bytes.
        page = self._session().axi_transactions(start=1, count=2)
        self.assertEqual(json.loads(json.dumps(page))["count"], 2)

    def test_only_anomalies_filters_to_flagged_transactions(self):
        page = self._session().axi_transactions(only_anomalies=True)

        self.assertEqual(page["total"], 2)
        self.assertEqual([t["index"] for t in page["transactions"]], [1, 3])
        self.assertTrue(all(t["flags"] for t in page["transactions"]))

    def test_kind_filters_reads_and_writes(self):
        session = self._session()
        self.assertEqual(session.axi_transactions(kind="write")["total"], 3)
        self.assertEqual(session.axi_transactions(kind="read")["total"], 2)
        with self.assertRaisesRegex(ValueError, "kind must be"):
            session.axi_transactions(kind="burst")

    def test_page_size_is_capped(self):
        payload = _axi_capture_payload(count=400, anomalies=())
        page = self._session(payload).axi_transactions(count=10_000)
        self.assertEqual(page["count"], FcapzMcpSession._AXI_MAX_PAGE)

    def test_rejects_nonsense_paging_arguments(self):
        session = self._session()
        with self.assertRaisesRegex(ValueError, "start must be >= 0"):
            session.axi_transactions(start=-1)
        with self.assertRaisesRegex(ValueError, "count must be > 0"):
            session.axi_transactions(count=0)

    def test_reports_unavailable_without_a_capture(self):
        session = FcapzMcpSession(rpc=FakeRpc())
        self.assertEqual(
            session.axi_transactions(),
            {
                "available": False,
                "reason": None,
                "total": 0,
                "start": 0,
                "count": 0,
                "next_start": None,
                "filters": None,
                "transactions": [],
            },
        )

    def test_explains_itself_when_the_capture_is_not_axi(self):
        session = self._session({"ok": True, "result": {"samples": []}})
        result = session.axi_transactions()

        self.assertFalse(result["available"])
        self.assertIn("AXI monitor probe map", result["reason"])

    def test_segmented_captures_are_merged_and_tagged(self):
        payload = {
            "ok": True,
            "segments": [
                {"segment": 0, "axi": _axi_capture_payload(2, ())["axi"]},
                {"segment": 1, "axi": _axi_capture_payload(2, ())["axi"]},
            ],
        }
        page = self._session(payload).axi_transactions()

        self.assertEqual(page["total"], 4)
        self.assertEqual([t["segment"] for t in page["transactions"]], [0, 0, 1, 1])

    def test_capture_requests_the_decode_from_rpc(self):
        rpc = FakeRpc()
        FcapzMcpSession(rpc=rpc).capture()
        self.assertTrue(rpc.requests[-1]["decode_axi"])


if __name__ == "__main__":
    unittest.main()
