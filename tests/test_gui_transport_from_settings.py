# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

import pytest
from fcapz.gui.settings import ConnectionSettings
from fcapz.gui.transport_from_settings import transport_from_connection
from fcapz.transport import OpenOcdTransport, XilinxHwServerTransport

pytestmark = pytest.mark.gui


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
        self.assertEqual(t._connect_timeout_sec, 60.0)

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
        self.assertEqual(t.ready_probe_timeout, 2.0)

    def test_hw_server_tap_without_suffix(self) -> None:
        c = ConnectionSettings(backend="hw_server", tap="myfpga")
        t = transport_from_connection(c)
        self.assertIsInstance(t, XilinxHwServerTransport)
        self.assertEqual(t.fpga_name, "myfpga")

    def test_hw_server_ready_timeout_when_program_set(self) -> None:
        c = ConnectionSettings(
            backend="hw_server",
            tap="xc7a100t",
            program="/tmp/x.bit",
            program_on_connect=True,
            hw_ready_timeout_sec=90.0,
        )
        t = transport_from_connection(c)
        self.assertIsInstance(t, XilinxHwServerTransport)
        self.assertEqual(t.ready_probe_timeout, 90.0)

    def test_hw_server_program_disabled_skips_bitfile(self) -> None:
        c = ConnectionSettings(
            backend="hw_server",
            tap="xc7a100t",
            program="/tmp/x.bit",
            program_on_connect=False,
            hw_ready_timeout_sec=90.0,
        )
        t = transport_from_connection(c)
        self.assertIsInstance(t, XilinxHwServerTransport)
        self.assertIsNone(t.bitfile)
        self.assertEqual(t.ready_probe_timeout, 2.0)

    def test_hw_server_post_program_and_poll_from_settings(self) -> None:
        c = ConnectionSettings(
            backend="hw_server",
            tap="xc7a100t",
            program="/tmp/x.bit",
            hw_post_program_delay_ms=350,
            hw_ready_poll_interval_ms=40,
        )
        t = transport_from_connection(c)
        self.assertIsInstance(t, XilinxHwServerTransport)
        self.assertEqual(t.post_program_delay_ms, 350)
        self.assertAlmostEqual(t.ready_poll_interval_sec, 0.04)

    def test_unknown_backend(self) -> None:
        c = ConnectionSettings(backend="nope")
        with self.assertRaises(ValueError):
            transport_from_connection(c)


if __name__ == "__main__":
    unittest.main()
