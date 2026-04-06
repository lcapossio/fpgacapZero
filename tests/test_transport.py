# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Tests for Transport ABC contracts and failure modes.

All tests here use mocks or deliberately broken transports — no real
hardware or network connection required.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from host.fcapz.transport import OpenOcdTransport, Transport, XilinxHwServerTransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ConcreteTransport(Transport):
    """Minimal concrete Transport for ABC contract tests."""

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def read_reg(self, addr: int) -> int:
        return 0

    def write_reg(self, addr: int, value: int) -> None:
        pass

    def read_block(self, addr: int, words: int):
        return [0] * words


# ---------------------------------------------------------------------------
# Transport ABC contract
# ---------------------------------------------------------------------------

class TransportAbcTests(unittest.TestCase):
    """Verify that Transport ABC exposes the expected interface."""

    def test_abstract_methods_present(self):
        """Transport cannot be instantiated directly (ABC)."""
        with self.assertRaises(TypeError):
            Transport()

    def test_concrete_subclass_instantiates(self):
        t = ConcreteTransport()
        self.assertIsInstance(t, Transport)

    def test_select_chain_raises_not_implemented(self):
        """select_chain() on base class raises NotImplementedError."""
        t = ConcreteTransport()
        with self.assertRaises(NotImplementedError):
            t.select_chain(1)

    def test_raw_dr_scan_raises_not_implemented(self):
        """raw_dr_scan() on base class raises NotImplementedError."""
        t = ConcreteTransport()
        with self.assertRaises(NotImplementedError):
            t.raw_dr_scan(0, 8)

    def test_raw_dr_scan_batch_default_calls_raw_dr_scan(self):
        """raw_dr_scan_batch() default impl calls raw_dr_scan per entry."""
        call_log: list[tuple[int, int]] = []

        class TracingTransport(ConcreteTransport):
            def raw_dr_scan(self, bits, width, *, chain=None):
                call_log.append((bits, width))
                return bits

        t = TracingTransport()
        results = t.raw_dr_scan_batch([(0xAA, 8), (0xBB, 16)])
        self.assertEqual(results, [0xAA, 0xBB])
        self.assertEqual(call_log, [(0xAA, 8), (0xBB, 16)])


# ---------------------------------------------------------------------------
# OpenOcdTransport failure modes
# ---------------------------------------------------------------------------

class OpenOcdConnectFailureTests(unittest.TestCase):
    """OpenOCD transport failure modes — socket-level mocks."""

    def test_connect_refused_raises(self):
        """connect() raises if OpenOCD is not listening."""
        t = OpenOcdTransport(host="127.0.0.1", port=19999)
        with self.assertRaises(OSError):
            t.connect()

    def test_connect_timeout_raises(self):
        """connect() with unreachable host raises OSError/TimeoutError."""
        # 240.0.0.1 is an unroutable TEST-NET address — connect will timeout
        # quickly because it's refused rather than timing out on loopback.
        # We patch create_connection to simulate a timeout cleanly.
        with patch("socket.create_connection", side_effect=TimeoutError("timed out")):
            t = OpenOcdTransport(host="240.0.0.1", port=6666)
            with self.assertRaises((OSError, TimeoutError)):
                t.connect()

    def test_send_raises_if_not_connected(self):
        """_cmd() raises RuntimeError if called before connect()."""
        t = OpenOcdTransport()
        with self.assertRaises(RuntimeError):
            t._cmd("version")

    def test_connection_closed_mid_read_raises(self):
        """ConnectionError raised when OpenOCD closes the socket unexpectedly."""
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""  # empty = connection closed
        mock_sock.sendall = MagicMock()

        t = OpenOcdTransport()
        t._sock = mock_sock

        with self.assertRaises(ConnectionError):
            t._cmd("version")

    def test_close_when_not_connected_is_safe(self):
        """close() is idempotent when called before connect()."""
        t = OpenOcdTransport()
        t.close()  # must not raise

    def test_select_chain_unknown_raises_value_error(self):
        """select_chain() with a chain not in ir_table raises ValueError."""
        t = OpenOcdTransport()
        with self.assertRaises(ValueError):
            t.select_chain(99)

    def test_select_chain_valid_updates_active(self):
        """select_chain() updates the active chain."""
        t = OpenOcdTransport()
        t.select_chain(2)
        self.assertEqual(t._active_chain, 2)

    def test_read_reg_sends_two_scans(self):
        """read_reg() issues irscan + drscan + runtest + irscan + drscan."""
        cmds: list[str] = []

        def fake_cmd(tcl: str) -> str:
            cmds.append(tcl)
            # Return a plausible hex word for drscan responses
            return "0x000000000000"

        t = OpenOcdTransport()
        t._cmd = fake_cmd  # type: ignore[method-assign]
        t.read_reg(0x0000)

        # Expect: irscan, drscan (issue), runtest, irscan, drscan (capture)
        self.assertEqual(len(cmds), 5)
        self.assertTrue(any("irscan" in c for c in cmds))
        self.assertTrue(any("runtest" in c for c in cmds))

    def test_write_reg_sends_one_scan_pair(self):
        """write_reg() issues irscan + drscan (write-only, no runtest loop)."""
        cmds: list[str] = []

        def fake_cmd(tcl: str) -> str:
            cmds.append(tcl)
            return "0x000000000000"

        t = OpenOcdTransport()
        t._cmd = fake_cmd  # type: ignore[method-assign]
        t.write_reg(0x0028, 0xDEADBEEF)

        self.assertEqual(len(cmds), 2)
        self.assertTrue(any("irscan" in c for c in cmds))
        self.assertFalse(any("runtest" in c for c in cmds))


# ---------------------------------------------------------------------------
# XilinxHwServerTransport failure modes
# ---------------------------------------------------------------------------

class XilinxHwServerConnectFailureTests(unittest.TestCase):
    """XilinxHwServerTransport failure modes — subprocess mocks."""

    def test_connect_raises_if_xsdb_not_found(self):
        """connect() raises RuntimeError when xsdb is not on PATH."""
        with patch("shutil.which", return_value=None):
            t = XilinxHwServerTransport()
            with self.assertRaises(RuntimeError, msg="xsdb not found"):
                t.connect()

    def test_send_raises_if_not_connected(self):
        """_send() raises RuntimeError before connect()."""
        t = XilinxHwServerTransport()
        with self.assertRaises(RuntimeError):
            t._send("puts hello")

    def test_process_exit_mid_send_raises_connection_error(self):
        """_send() raises ConnectionError when xsdb exits unexpectedly."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline.return_value = ""  # EOF = process exited

        t = XilinxHwServerTransport()
        t._proc = mock_proc
        t._stderr_lines = ["error: hw_server unreachable"]

        with self.assertRaises(ConnectionError):
            t._send("puts hello")

    def test_close_when_not_connected_is_safe(self):
        """close() is idempotent when called before connect()."""
        t = XilinxHwServerTransport()
        t.close()  # must not raise

    def test_select_chain_unknown_raises_value_error(self):
        """select_chain() raises ValueError for unknown chain."""
        t = XilinxHwServerTransport()
        with self.assertRaises(ValueError):
            t.select_chain(99)

    def test_select_chain_valid_updates_active(self):
        """select_chain() stores the active chain."""
        t = XilinxHwServerTransport()
        t.select_chain(3)
        self.assertEqual(t._active_chain, 3)

    def test_parse_bits_u32_raises_on_no_bit_string(self):
        """_parse_bits_u32() raises RuntimeError on malformed xsdb output."""
        t = XilinxHwServerTransport()
        with self.assertRaises(RuntimeError):
            t._parse_bits_u32("some garbage output without bit string")

    def test_parse_bits_u32_extracts_value(self):
        """_parse_bits_u32() correctly decodes a 32-bit value from LSB-first string."""
        t = XilinxHwServerTransport()
        # LSB-first: "10000000000000000000000000000000" = bit0=1 = value 1
        bits = "1" + "0" * 31  # bit[0]=1, rest=0 → value=1
        self.assertEqual(t._parse_bits_u32(bits), 1)

        # 0xA5A5A5A5 = 1010_0101_1010_0101_1010_0101_1010_0101 LSB-first
        val = 0xA5A5A5A5
        bit_str = "".join("1" if (val >> i) & 1 else "0" for i in range(32))
        self.assertEqual(t._parse_bits_u32(bit_str), val)

    def test_parse_block_bits_raises_on_too_few(self):
        """_parse_block_bits() raises when fewer results than expected."""
        t = XilinxHwServerTransport()
        # Only one 32-bit token but we expect 4
        bit_str = "0" * 32
        with self.assertRaises(RuntimeError):
            t._parse_block_bits(bit_str, 4)

    def test_frame_bits_write_flag(self):
        """_frame_bits() sets bit 48 (write flag) correctly."""
        frame = XilinxHwServerTransport._frame_bits(addr=0, data=0, write=True)
        self.assertEqual(frame[48], "1")

        frame_r = XilinxHwServerTransport._frame_bits(addr=0, data=0, write=False)
        self.assertEqual(frame_r[48], "0")

    def test_frame_bits_encodes_addr_and_data(self):
        """_frame_bits() encodes addr at bits[47:32] and data at bits[31:0]."""
        addr = 0x0028
        data = 0xDEADBEEF
        frame = XilinxHwServerTransport._frame_bits(addr=addr, data=data, write=True)

        # Decode data (bits 0-31)
        decoded_data = sum(int(frame[i]) << i for i in range(32))
        self.assertEqual(decoded_data, data)

        # Decode addr (bits 32-47)
        decoded_addr = sum(int(frame[32 + i]) << i for i in range(16))
        self.assertEqual(decoded_addr, addr)


class TclInjectionTests(unittest.TestCase):
    """Tests for TCL command injection prevention in XilinxHwServerTransport."""

    def test_fpga_name_with_quotes_rejected(self):
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(fpga_name='xc7a100t"; puts "pwned')

    def test_fpga_name_with_brackets_rejected(self):
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(fpga_name="xc7a[exec rm -rf /]")

    def test_fpga_name_with_semicolon_rejected(self):
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(fpga_name="xc7a; exec rm -rf /")

    def test_bitfile_with_brackets_rejected(self):
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(fpga_name="xc7a100t", bitfile="[exec evil_cmd]")

    def test_bitfile_with_backslash_rejected(self):
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(fpga_name="xc7a100t", bitfile="C:\\evil\\path.bit")

    def test_bitfile_validated_at_program_time(self):
        t = XilinxHwServerTransport(fpga_name="xc7a100t")
        with self.assertRaises(ValueError):
            t.program("[exec evil_cmd]")

    def test_safe_fpga_name_accepted(self):
        """Normal FPGA target names pass validation."""
        t = XilinxHwServerTransport(fpga_name="xc7a100t")
        self.assertEqual(t.fpga_name, "xc7a100t")

        t2 = XilinxHwServerTransport(fpga_name="xczu9eg")
        self.assertEqual(t2.fpga_name, "xczu9eg")

    def test_safe_bitfile_path_accepted(self):
        t = XilinxHwServerTransport(
            fpga_name="xc7a100t",
            bitfile="/home/user/build/top.bit",
        )
        self.assertEqual(t.bitfile, "/home/user/build/top.bit")

        t2 = XilinxHwServerTransport(
            fpga_name="xc7a100t",
            bitfile="path/with spaces/file.bit",
        )
        self.assertEqual(t2.bitfile, "path/with spaces/file.bit")


if __name__ == "__main__":
    unittest.main()
