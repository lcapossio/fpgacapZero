# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""The ``cancel`` command (BUG-292): RpcServer, the stdin line protocol and
the web gateway interrupt a command in flight without waiting on it."""

from __future__ import annotations

import contextlib
import io
import json
import threading
import time
import unittest
from unittest import mock

from fcapz import rpc
from fcapz.analyzer import expected_ela_version_reg
from fcapz.rpc import RequestCancelled, RpcServer
from fcapz.transport import Transport

try:  # fcapz.web loads fastapi, an optional extra
    from fcapz.web.gateway import RpcGateway
except ImportError:  # pragma: no cover - depends on env
    RpcGateway = None

_CONNECT = {"cmd": "connect", "backend": "hw_server", "chain": 1}


class BlockingTransport(Transport):
    """An ELA whose connect() blocks until cancel(), as a hung hw_server
    connect does, then fails the way a closed link fails."""

    def __init__(self, *, block: bool = True) -> None:
        self.block = block
        self.entered = threading.Event()
        self.cancelled = threading.Event()
        self.regs = {
            0x0000: expected_ela_version_reg(),
            0x0008: 0x4,
            0x000C: 8,
            0x0010: 64,
            0x00A4: 2,
        }

    def connect(self) -> None:
        self.entered.set()
        if self.block and not self.cancelled.wait(10):
            raise AssertionError("never cancelled")
        if self.cancelled.is_set():
            raise ConnectionError("transport cancelled")

    def cancel(self) -> None:
        self.cancelled.set()

    def close(self) -> None:
        pass

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


def _in_thread(fn, *args):
    """Run *fn* on a thread; return (thread, result box)."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - recorded for the check
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    return thread, box


class RpcServerCancelTests(unittest.TestCase):
    def _server(self, transport: BlockingTransport) -> RpcServer:
        server = RpcServer()
        server._build_transport = lambda req, **_: transport  # type: ignore[method-assign]
        return server

    def test_cancel_when_idle_does_nothing(self):
        server = self._server(BlockingTransport(block=False))
        resp = server.handle({"cmd": "cancel"})
        self.assertIs(resp["ok"], True)
        self.assertIs(resp["cancelled"], False)
        self.assertEqual(resp["reason"], "idle")

    def test_cancel_interrupts_a_blocked_connect(self):
        transport = BlockingTransport()
        server = self._server(transport)
        thread, box = _in_thread(server.handle, {**_CONNECT, "request_id": "c1"})
        self.assertTrue(transport.entered.wait(5))
        resp = server.handle({"cmd": "cancel", "target": "c1", "request_id": "x1"})
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertIs(resp["cancelled"], True)
        self.assertEqual(resp["request_id"], "x1")
        self.assertIn("error", box)
        self.assertIsInstance(box["error"], ConnectionError)

    def test_cancel_names_a_request_that_already_finished(self):
        server = self._server(BlockingTransport(block=False))
        server.handle({**_CONNECT, "request_id": "c1"})
        resp = server.handle({"cmd": "cancel", "target": "c1"})
        self.assertIs(resp["cancelled"], False)
        self.assertEqual(resp["reason"], "request not running")
        # The session it would have ended is untouched.
        self.assertIs(server.handle({"cmd": "probe"})["ok"], True)

    def test_a_request_cancelled_before_it_starts_is_refused(self):
        server = self._server(BlockingTransport(block=False))
        server.handle({"cmd": "cancel", "target": "later"})
        with self.assertRaises(RequestCancelled):
            server.handle({**_CONNECT, "request_id": "later"})
        # Remembered once: a request that reuses the id later runs.
        self.assertIs(server.handle({**_CONNECT, "request_id": "later"})["ok"], True)

    def test_cancel_for_an_ended_session_does_nothing(self):
        server = self._server(BlockingTransport(block=False))
        epoch = server.handle(_CONNECT)["session_epoch"]
        server.handle({"cmd": "close"})
        resp = server.handle({"cmd": "cancel", "session_epoch": epoch})
        self.assertIs(resp["cancelled"], False)
        self.assertEqual(resp["reason"], "session ended")

    def test_a_cancel_while_the_transport_is_built_stops_its_registration(self):
        transport = BlockingTransport(block=False)
        server = RpcServer()
        building = threading.Event()
        go_on = threading.Event()

        def slow_build(req, **_):
            building.set()  # the cancel arrives before the transport registers
            go_on.wait(5)
            return transport

        server._build_transport = slow_build  # type: ignore[method-assign]
        thread, box = _in_thread(server.handle, _CONNECT)
        self.assertTrue(building.wait(5))
        resp = server.handle({"cmd": "cancel"})
        go_on.set()
        thread.join(5)
        self.assertIs(resp["cancelled"], True)
        self.assertIsInstance(box.get("error"), RequestCancelled)
        self.assertTrue(transport.cancelled.is_set())
        self.assertIsNone(server._analyzer)

    def test_replies_carry_request_id_and_session_epoch(self):
        server = self._server(BlockingTransport(block=False))
        before = server.session_epoch
        resp = server.handle({**_CONNECT, "request_id": 7})
        self.assertEqual(resp["request_id"], 7)
        self.assertEqual(resp["session_epoch"], before + 1)


class LineProtocolCancelTests(unittest.TestCase):
    def test_a_cancel_line_interrupts_the_request_in_flight(self):
        transport = BlockingTransport()

        def lines():
            yield json.dumps({**_CONNECT, "request_id": "c1"})
            if not transport.entered.wait(5):
                raise AssertionError("connect never started")
            yield json.dumps({"cmd": "cancel", "target": "c1", "request_id": "x1"})

        feed = lines()

        def fake_input():
            try:
                return next(feed)
            except StopIteration:
                raise EOFError from None

        out = io.StringIO()
        with mock.patch.object(
            RpcServer, "_build_transport", lambda self, req, **_: transport
        ), mock.patch("builtins.input", fake_input), contextlib.redirect_stdout(out):
            self.assertEqual(rpc.main(), 0)
        replies = {r["request_id"]: r for r in map(json.loads, out.getvalue().splitlines())}
        self.assertIs(replies["x1"]["cancelled"], True)
        self.assertIs(replies["c1"]["ok"], False)
        self.assertEqual(replies["c1"]["type"], "ConnectionError")


@unittest.skipIf(RpcGateway is None, "needs the [web] extra (fastapi)")
class GatewayCancelTests(unittest.TestCase):
    def _gateway(self, transport: BlockingTransport) -> RpcGateway:
        server = RpcServer()
        server._build_transport = lambda req, **_: transport  # type: ignore[method-assign]
        return RpcGateway(server)

    def test_cancel_does_not_wait_for_the_lock(self):
        transport = BlockingTransport()
        gateway = self._gateway(transport)
        thread, box = _in_thread(gateway.call, {**_CONNECT, "request_id": "c1"})
        self.assertTrue(transport.entered.wait(5))
        t0 = time.monotonic()
        resp = gateway.call({"cmd": "cancel", "target": "c1"})
        self.assertLess(time.monotonic() - t0, 2)
        thread.join(5)
        self.assertIs(resp["cancelled"], True)
        self.assertIs(box["value"]["ok"], False)
        self.assertEqual(box["value"]["request_id"], "c1")

    def test_close_while_busy_interrupts_then_closes(self):
        transport = BlockingTransport()
        gateway = self._gateway(transport)
        thread, box = _in_thread(gateway.call, _CONNECT)
        self.assertTrue(transport.entered.wait(5))
        resp = gateway.call({"cmd": "close"})
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertIs(resp["ok"], True)
        self.assertIs(box["value"]["ok"], False)


if __name__ == "__main__":
    unittest.main()
