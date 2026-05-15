# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import asyncio
import io
import importlib.util
import threading
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
                "result": {"samples": [1, 2]},
            }
        if cmd == "configure":
            return {"ok": True, "schema_version": "test"}
        if cmd == "arm":
            return {"ok": True, "schema_version": "test"}
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


class SparseCaptureRpc(FakeRpc):
    def handle(self, req):
        self.requests.append(dict(req))
        if req["cmd"] == "capture":
            return {"ok": True, "schema_version": "test"}
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

    def test_connect_forwards_future_backend_options(self):
        rpc = FakeRpc()
        session = FcapzMcpSession(rpc=rpc)

        session.connect(
            backend="spi",
            spi_url="ftdi://ftdi:232h/1",
            spi_frequency=2_000_000,
            spi_cs=1,
            spi_timeout=3.5,
        )
        session.connect(
            backend="usb_blaster",
            hardware="USB-Blaster",
            quartus_stp="quartus_stp",
        )

        self.assertEqual(rpc.requests[0]["backend"], "spi")
        self.assertNotIn("host", rpc.requests[0])
        self.assertNotIn("tap", rpc.requests[0])
        self.assertEqual(rpc.requests[0]["spi_url"], "ftdi://ftdi:232h/1")
        self.assertEqual(rpc.requests[0]["spi_frequency"], 2_000_000.0)
        self.assertEqual(rpc.requests[0]["spi_cs"], 1)
        self.assertEqual(rpc.requests[0]["spi_timeout"], 3.5)
        self.assertEqual(rpc.requests[2]["backend"], "usb_blaster")
        self.assertNotIn("host", rpc.requests[2])
        self.assertNotIn("tap", rpc.requests[2])
        self.assertEqual(rpc.requests[2]["hardware"], "USB-Blaster")
        self.assertEqual(rpc.requests[2]["quartus_stp"], "quartus_stp")

    def test_connect_rejects_backend_irrelevant_options(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        with self.assertRaisesRegex(ValueError, "spi_url not supported"):
            session.connect(backend="hw_server", spi_url="ftdi://ftdi:232h/1")
        with self.assertRaisesRegex(ValueError, "tap not supported"):
            session.connect(backend="spi", tap="xc7a100t.tap")
        with self.assertRaisesRegex(ValueError, "hardware not supported"):
            session.eio_connect(backend="spi", hardware="USB-Blaster")

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
        self.assertEqual(session.last_capture["result"], {"samples": [1, 2]})

    def test_capture_summary_always_reports_success(self):
        session = FcapzMcpSession(rpc=SparseCaptureRpc())

        response = session.capture()

        self.assertEqual(response, {"ok": True})
        self.assertEqual(session.status()["last_capture_summary"], {"ok": True})

    def test_drop_last_capture_releases_cached_payload(self):
        session = FcapzMcpSession(rpc=FakeRpc())

        session.capture()
        self.assertIsNotNone(session.last_capture)
        self.assertEqual(session.drop_last_capture(), {"ok": True})

        self.assertIsNone(session.last_capture)
        self.assertIsNone(session.status()["last_capture_summary"])

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
        session.eio_connect(backend="spi")

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
        self.assertEqual(session.axi_read("0x10")["value"], "0x12345678")
        self.assertEqual(session.axi_write("0x10", "0xCAFE")["resp"], "OKAY")
        self.assertEqual(session.axi_write_block(0x20, [1, "0x2"])["count"], 2)
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

    def test_program_requires_bitfile_under_root(self):
        rpc = FakeRpc()
        root = Path.cwd() / "virtual-bitfiles" / "allowed"
        bitfile = root / "design.bit"
        other = root.parent / "other.bit"
        with patch.object(Path, "is_file", return_value=True):
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
                "fcapz_capture",
                "fcapz_drop_last_capture",
                "fcapz_configure",
                "fcapz_arm",
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


if __name__ == "__main__":
    unittest.main()
