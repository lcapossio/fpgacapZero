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
        self.assertEqual(resp["reason"], "request finished")
        # The session it would have ended is untouched, and the id is not
        # remembered: reusing it runs.
        self.assertIs(server.handle({"cmd": "probe"})["ok"], True)
        self.assertIs(server.handle({**_CONNECT, "request_id": "c1"})["ok"], True)

    def test_two_cancels_for_a_queued_request_are_remembered_once(self):
        server = self._server(BlockingTransport(block=False))
        server.handle({"cmd": "cancel", "target": "q"})
        server.handle({"cmd": "cancel", "target": "q"})
        with self.assertRaises(RequestCancelled):
            server.handle({**_CONNECT, "request_id": "q"})
        self.assertIs(server.handle({**_CONNECT, "request_id": "q"})["ok"], True)

    def test_cancel_snapshots_the_transports_under_the_lock(self):
        """No command can start between the checks and the snapshot, so a
        cancel never reaches a session opened after it."""
        transport = BlockingTransport()
        server = self._server(transport)
        held = []
        resolve = server._resolve

        def spy(holders):
            held.append(server._opening_lock.locked())
            return resolve(holders)

        server._resolve = spy  # type: ignore[method-assign]
        thread, _ = _in_thread(server.handle, _CONNECT)
        self.assertTrue(transport.entered.wait(5))
        held.clear()
        server.handle({"cmd": "cancel"})
        thread.join(5)
        self.assertTrue(held)
        self.assertIs(held[0], True)

    def test_a_cancel_the_transport_ignored_still_ends_the_session(self):
        """A cancel that reaches a transport before its connect does not stop
        that connect; the command then fails and the session is cancelled."""
        go_on = threading.Event()

        class Unstoppable(BlockingTransport):
            closed = False

            def connect(self) -> None:
                self.entered.set()
                go_on.wait(5)

            def cancel(self) -> None:
                pass  # too early: the connect does not notice

            def close(self) -> None:
                Unstoppable.closed = True

        transport = Unstoppable()
        server = self._server(transport)
        thread, box = _in_thread(server.handle, _CONNECT)
        self.assertTrue(transport.entered.wait(5))
        self.assertIs(server.handle({"cmd": "cancel"})["cancelled"], True)
        go_on.set()
        thread.join(5)
        self.assertIsInstance(box.get("error"), RequestCancelled)
        self.assertTrue(Unstoppable.closed)
        self.assertIsNone(server._analyzer)

    def test_an_interrupted_session_command_tears_the_session_down(self):
        transport = BlockingTransport()
        server = self._server(transport)
        epoch = server.session_epoch
        thread, box = _in_thread(server.handle, _CONNECT)
        self.assertTrue(transport.entered.wait(5))
        server.handle({"cmd": "cancel"})
        thread.join(5)
        self.assertIsInstance(box.get("error"), ConnectionError)
        self.assertIsNone(server._analyzer)
        self.assertGreater(server.session_epoch, epoch)

    def test_cancel_of_a_connect_in_flight_with_the_last_known_epoch(self):
        """The epoch moves when connect finishes, so a client can still name
        the epoch it knows while the connect runs."""
        transport = BlockingTransport()
        server = self._server(transport)
        epoch = server.session_epoch
        thread, _ = _in_thread(server.handle, _CONNECT)
        self.assertTrue(transport.entered.wait(5))
        resp = server.handle({"cmd": "cancel", "session_epoch": epoch})
        thread.join(5)
        self.assertIs(resp["cancelled"], True)

    def test_side_connects_move_the_epoch(self):
        server = self._server(BlockingTransport(block=False))
        with mock.patch.object(server, "_handle", return_value={"ok": True}):
            before = server.session_epoch
            server.handle({"cmd": "axi_connect"})
            self.assertEqual(server.session_epoch, before + 1)

    def test_cancelling_a_scan_leaves_the_session_alone(self):
        transport = BlockingTransport(block=False)
        server = self._server(transport)
        server.handle(_CONNECT)
        scan_handle = BlockingTransport(block=False)
        started, go_on = threading.Event(), threading.Event()

        def scan(req):
            server._register_opening(scan_handle)
            started.set()
            go_on.wait(5)
            return {"ok": True}

        with mock.patch.object(server, "_handle", side_effect=scan):
            thread, box = _in_thread(server.handle, {"cmd": "scan_targets", "request_id": "s"})
            self.assertTrue(started.wait(5))
            resp = server.handle({"cmd": "cancel", "target": "s"})
            go_on.set()
            thread.join(5)
        self.assertIs(resp["cancelled"], True)
        self.assertTrue(scan_handle.cancelled.is_set())
        self.assertFalse(transport.cancelled.is_set())
        self.assertIsNotNone(server._analyzer)
        # The scan's I/O finished, but it was cancelled: it does not succeed.
        self.assertIsInstance(box.get("error"), RequestCancelled)

    def test_an_untargeted_cancel_reaches_a_running_scan(self):
        server = self._server(BlockingTransport(block=False))
        started, go_on = threading.Event(), threading.Event()

        def scan(req):
            started.set()
            go_on.wait(5)
            return {"ok": True}

        with mock.patch.object(server, "_handle", side_effect=scan):
            thread, box = _in_thread(server.handle, {"cmd": "scan_targets"})
            self.assertTrue(started.wait(5))
            resp = server.handle({"cmd": "cancel"})
            go_on.set()
            thread.join(5)
        self.assertIs(resp["cancelled"], True)
        self.assertIsInstance(box.get("error"), RequestCancelled)

    def test_malformed_cmd_and_request_id_are_refused(self):
        server = self._server(BlockingTransport(block=False))
        for req in ({"cmd": []}, {"cmd": "probe", "request_id": [1]},
                    {"cmd": "cancel", "target": {"id": 1}}):
            with self.assertRaises(ValueError):
                server.handle(req)

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
        self.assertIn("session_epoch", replies["c1"])

    def test_a_null_line_is_answered_and_does_not_stop_the_worker(self):
        feed = iter(["null", json.dumps({"cmd": "cancel", "request_id": "x"}),
                     json.dumps({"cmd": "close", "request_id": "after"})])

        def fake_input():
            try:
                return next(feed)
            except StopIteration:
                raise EOFError from None

        out = io.StringIO()
        with mock.patch("builtins.input", fake_input), contextlib.redirect_stdout(out):
            self.assertEqual(rpc.main(), 0)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(replies), 3)
        self.assertTrue(any(r.get("request_id") == "after" for r in replies))


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

    def test_remote_cancel_cannot_end_a_serial_connect_still_opening(self):
        transport = BlockingTransport()
        transport.transport_kind = "bytestream"
        gateway = self._gateway(transport)
        thread, box = _in_thread(gateway.call, {**_CONNECT, "request_id": "c1"})
        self.assertTrue(transport.entered.wait(5))
        resp = gateway.call({"cmd": "cancel", "request_id": "r"}, serial_allowed=False)
        self.assertEqual(resp["type"], "PermissionError")
        self.assertEqual(resp["request_id"], "r")
        self.assertIn("session_epoch", resp)
        self.assertFalse(transport.cancelled.is_set())
        gateway.call({"cmd": "cancel"})  # the local client may
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_remote_cancel_cannot_end_a_serial_connect_before_it_registers(self):
        transport = BlockingTransport(block=False)
        gateway = self._gateway(transport)
        building, go_on = threading.Event(), threading.Event()

        def slow_build(req, **_):
            building.set()
            go_on.wait(5)
            return transport

        gateway._server._build_transport = slow_build  # type: ignore[method-assign]
        listed = mock.patch("fcapz.web.gateway.resolve_serial_port", lambda name: name)
        listed.start()
        self.addCleanup(listed.stop)
        serial = {**_CONNECT, "backend": "serial", "serial_port": "COM_TEST"}
        thread, box = _in_thread(gateway.call, serial)
        self.assertTrue(building.wait(5))
        resp = gateway.call({"cmd": "cancel"}, serial_allowed=False)
        go_on.set()
        thread.join(5)
        self.assertEqual(resp["type"], "PermissionError")
        self.assertIs(box["value"]["ok"], True)

    def test_a_close_cancelled_before_it_runs_interrupts_nothing(self):
        transport = BlockingTransport()
        gateway = self._gateway(transport)
        thread, _ = _in_thread(gateway.call, _CONNECT)
        self.assertTrue(transport.entered.wait(5))
        gateway.call({"cmd": "cancel", "target": "z"})
        gateway.interrupt_if_busy({"cmd": "close", "request_id": "z"})
        self.assertFalse(transport.cancelled.is_set())
        gateway.interrupt_if_busy({"cmd": "close", "request_id": []})
        self.assertFalse(transport.cancelled.is_set())
        gateway.call({"cmd": "cancel"})
        thread.join(5)


if __name__ == "__main__":
    unittest.main()
