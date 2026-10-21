# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""fcapz openocd-bridge: OpenOCD remote_bitbang onto MPSSE pin commands.
No hardware: the adapter is a fake pin port."""

from __future__ import annotations

import socket
import sys
import threading
import unittest
from unittest import mock

from fcapz import cli
from fcapz.rbb_bridge import TCK, TDI, TDO, TMS, openocd_config, serve, tdo_reply, translate

FLASHPRO5 = (0x18, 0x1B)  # ADBUS value / direction
DIGILENT = (0x88, 0x8B)   # ADBUS7 enables the JTAG buffer


class TranslateTests(unittest.TestCase):
    def test_each_bit_pattern_drives_tck_tms_tdi(self):
        value, direction = FLASHPRO5
        base = value & ~(TCK | TDI | TMS)
        cmd, reads, quit_ = translate(b"01234567", value, direction)
        expected = bytearray()
        for v in range(8):
            pins = base | (TCK if v & 4 else 0) | (TMS if v & 2 else 0) | (TDI if v & 1 else 0)
            expected += bytes((0x80, pins, direction))
        self.assertEqual(cmd, bytes(expected))
        self.assertEqual((reads, quit_), (0, False))

    def test_non_jtag_pins_keep_their_level(self):
        cmd, _, _ = translate(b"0", *DIGILENT)
        self.assertEqual(cmd, bytes((0x80, 0x80, 0x8B)))  # buffer enable stays on

    def test_reads_sample_tdo_and_flush(self):
        cmd, reads, _ = translate(b"2R6R", *FLASHPRO5)
        self.assertEqual(reads, 2)
        self.assertEqual(cmd.count(0x81), 2)
        self.assertEqual(cmd[-1], 0x87)  # send immediate after reads

    def test_quit_stops_and_drops_the_rest(self):
        cmd, reads, quit_ = translate(b"4RQ5R", *FLASHPRO5)
        self.assertTrue(quit_)
        self.assertEqual(reads, 1)
        self.assertEqual(cmd.count(0x80), 1)

    def test_resets_and_led_are_ignored(self):
        self.assertEqual(translate(b"BbrstuZz", *FLASHPRO5), (b"", 0, False))

    def test_tdo_reply(self):
        self.assertEqual(tdo_reply(bytes((0x00, TDO, 0xFF & ~TDO, 0xFF))), b"0101")


class FakePins:
    """Answers every pin read with the next TDO level in *tdo*."""

    def __init__(self, tdo=()):
        self.tdo = list(tdo)
        self.commands = []

    def exchange(self, commands, reply_bytes):
        self.commands.append(commands)
        return bytes(TDO if self.tdo.pop(0) else 0 for _ in range(reply_bytes))


class ServeTests(unittest.TestCase):
    def _start(self, pins, **kw):
        bound = []
        ready = threading.Event()

        def on_ready(port):
            bound.append(port)
            ready.set()

        thread = threading.Thread(
            target=serve, args=(pins, FLASHPRO5),
            kwargs={"port": 0, "ready": on_ready, "log": lambda m: None, **kw},
            daemon=True,
        )
        thread.start()
        self.assertTrue(ready.wait(5))
        return thread, bound[0]

    def test_reads_are_answered_in_order(self):
        pins = FakePins(tdo=[1, 0, 1])
        thread, port = self._start(pins, once=True)
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(b"0R4R0R")
            got = b""
            while len(got) < 3:
                got += c.recv(16)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(got, b"101")

    def test_quit_ends_the_server(self):
        pins = FakePins(tdo=[1])
        thread, port = self._start(pins)  # not once: only Q ends it
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(b"6RQ")
            self.assertEqual(c.recv(16), b"1")
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_listens_on_loopback_only(self):
        pins = FakePins()
        thread, port = self._start(pins, once=True)
        with socket.create_connection(("127.0.0.1", port)) as c:
            self.assertEqual(c.getpeername()[0], "127.0.0.1")
        thread.join(5)

    def test_openocd_config(self):
        self.assertEqual(
            openocd_config(3335),
            "adapter driver remote_bitbang\nremote_bitbang host 127.0.0.1\n"
            "remote_bitbang port 3335\ntransport select jtag\n",
        )


class CliTests(unittest.TestCase):
    def _run(self, *argv):
        with mock.patch.object(sys, "argv", ["fcapz", *argv]):
            return cli.main()

    def test_opens_the_named_adapter_serves_and_releases_it(self):
        pins = mock.MagicMock()
        pins.open_pins.return_value = FLASHPRO5
        pins.adapter.description = "Embedded FlashPro5 A"
        with mock.patch("fcapz.ftdi_transport.FtdiMpsseTransport",
                        return_value=pins) as ctor, \
                mock.patch("fcapz.rbb_bridge.serve") as serve_:
            rc = self._run("--hardware", "Embedded FlashPro5 A", "openocd-bridge",
                           "--listen-port", "4444", "--once")
        self.assertEqual(rc, 0)
        ctor.assert_called_once_with(device="Embedded FlashPro5 A")
        args, kwargs = serve_.call_args
        self.assertEqual(args, (pins, FLASHPRO5))
        self.assertEqual((kwargs["port"], kwargs["once"]), (4444, True))
        pins.close.assert_called_once()

    def test_port_in_use_reports_and_releases(self):
        pins = mock.MagicMock()
        pins.open_pins.return_value = FLASHPRO5
        with mock.patch("fcapz.ftdi_transport.FtdiMpsseTransport", return_value=pins), \
                mock.patch("fcapz.rbb_bridge.serve", side_effect=OSError("in use")):
            rc = self._run("openocd-bridge")
        self.assertEqual(rc, 1)
        pins.close.assert_called_once()

    def test_bad_listen_port_is_refused_before_opening(self):
        with mock.patch("fcapz.ftdi_transport.FtdiMpsseTransport") as ctor:
            rc = self._run("openocd-bridge", "--listen-port", "70000")
        self.assertEqual(rc, 2)
        ctor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
