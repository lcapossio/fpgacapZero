# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

from fcapz.gui.settings import ConnectionSettings
from fcapz.gui.transport_from_settings import transport_from_connection
from fcapz.transport import OpenOcdTransport, XilinxHwServerTransport


class TestTransportFromSettings(unittest.TestCase):
    def test_openocd_ultrascale_ir(self) -> None:
        c = ConnectionSettings(
            backend="openocd",
            host="10.0.0.1",
            port=7777,
            tap="foo.tap",
            ir_table="ultrascale",
        )
        t = transport_from_connection(c)
        self.assertIsInstance(t, OpenOcdTransport)
        self.assertEqual(t.host, "10.0.0.1")
        self.assertEqual(t.port, 7777)
        self.assertEqual(t.tap, "foo.tap")
        self.assertEqual(t.ir_table, OpenOcdTransport.IR_TABLE_US)

    def test_hw_server_port_remap_and_fpga_name(self) -> None:
        c = ConnectionSettings(
            backend="hw_server",
            host="127.0.0.1",
            port=6666,
            tap="xc7a35t.tap",
            program=None,
            ir_table="xilinx7",
        )
        t = transport_from_connection(c)
        self.assertIsInstance(t, XilinxHwServerTransport)
        self.assertEqual(t.port, 3121)
        self.assertEqual(t.fpga_name, "xc7a35t")

    def test_hw_server_tap_without_suffix(self) -> None:
        c = ConnectionSettings(backend="hw_server", tap="myfpga")
        t = transport_from_connection(c)
        self.assertIsInstance(t, XilinxHwServerTransport)
        self.assertEqual(t.fpga_name, "myfpga")

    def test_unknown_backend(self) -> None:
        c = ConnectionSettings(backend="nope")
        with self.assertRaises(ValueError):
            transport_from_connection(c)


if __name__ == "__main__":
    unittest.main()
