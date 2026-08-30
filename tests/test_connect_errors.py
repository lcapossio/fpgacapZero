# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import errno
import socket
import unittest

from fcapz.gui.connect_errors import format_connect_error
from fcapz.gui.settings import ConnectionSettings


class TestFormatConnectError(unittest.TestCase):
    def setUp(self) -> None:
        self._conn = ConnectionSettings(
            backend="openocd",
            host="127.0.0.1",
            port=6666,
            tap="x.tap",
            connect_timeout_sec=30.0,
        )

    def test_timeout_error(self) -> None:
        msg = format_connect_error(TimeoutError(), self._conn)
        self.assertIn("Timed out", msg)
        self.assertIn("OpenOCD", msg)

    def test_socket_timeout(self) -> None:
        msg = format_connect_error(socket.timeout(), self._conn)
        self.assertIn("Timed out", msg)
        self.assertIn("30", msg)

    def test_connection_refused(self) -> None:
        msg = format_connect_error(ConnectionRefusedError(), self._conn)
        self.assertIn("refused", msg.lower())

    def test_fpga_ready_connection_error(self) -> None:
        exc = ConnectionError(
            "FPGA did not become ready within 2s after program() (probe addr=0x0000",
        )
        msg = format_connect_error(exc, self._conn)
        self.assertIn("FPGA did not become ready", msg)
        self.assertIn("HW ready timeout", msg)

    def test_errno_unreachable(self) -> None:
        e = OSError(errno.EHOSTUNREACH, "No route")
        msg = format_connect_error(e, self._conn)
        self.assertIn("unreachable", msg.lower())

    def test_usb_blaster_endpoint_label_uses_friendly_auto_names(self) -> None:
        conn = ConnectionSettings(backend="usb_blaster", tap="auto")

        msg = format_connect_error(Exception("boom"), conn)

        self.assertIn("boom", msg)
        self.assertIn("first available Quartus cable", msg)
        self.assertIn("first @1 device", msg)

    def test_usb_blaster_timeout_mentions_quartus_not_tcp(self) -> None:
        conn = ConnectionSettings(backend="usb_blaster", tap="auto")

        msg = format_connect_error(TimeoutError(), conn)

        self.assertIn("Quartus", msg)
        self.assertIn("FCAPZ_QUARTUS_TIMEOUT", msg)
        self.assertNotIn("TCP/socket", msg)


if __name__ == "__main__":
    unittest.main()
