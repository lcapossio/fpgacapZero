# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Tests for Transport ABC contracts and failure modes.

All tests here use mocks or deliberately broken transports — no real
hardware or network connection required.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fcapz.transport import (
    list_xilinx_hw_server_targets,
    OpenOcdTransport,
    SpiRegisterTransport,
    Transport,
    XilinxHwServerTransport,
    parse_xsdb_jtag_targets,
)


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


class XsdbTargetParserTests(unittest.TestCase):
    def test_parse_jtag_targets_output(self) -> None:
        raw = """
          1  jsn-JTAG-HS3-210299
             2  arm_dap
          *  3  xck26
             4  xc7a100t
        """
        self.assertEqual(
            parse_xsdb_jtag_targets(raw),
            ["jsn-JTAG-HS3-210299", "arm_dap", "xck26", "xc7a100t"],
        )

    def test_parse_jtag_targets_prefers_fpga_device_names(self) -> None:
        raw = """
          1  Digilent Arty A7-100T 210319B26DC2A
             2  xc7a100t (idcode 13631093 irlen 6 fpga)
          3  Xilinx X-MLCC-01 XFL11Y1YXRV0A
             4  xck26 (idcode 04724093 irlen 12 fpga)
             5  arm_dap (idcode 5ba00477 irlen 4)
        """
        self.assertEqual(parse_xsdb_jtag_targets(raw), ["xc7a100t", "xck26"])

    def test_parse_jtag_targets_deduplicates_names(self) -> None:
        raw = """
          1  xck26
        * 2  xck26
          note: not a target line
        """
        self.assertEqual(parse_xsdb_jtag_targets(raw), ["xck26"])

    @patch("shutil.which", return_value="xsdb")
    @patch("subprocess.run")
    def test_list_jtag_targets_uses_minimal_scan_script(
        self,
        run_mock: MagicMock,
        _which_mock: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "  1  jsn-JTAG-HS3-210299\n* 2  xck26\n"
        proc.stderr = ""
        run_mock.return_value = proc

        self.assertEqual(
            list_xilinx_hw_server_targets(host="localhost", port=3121),
            ["jsn-JTAG-HS3-210299", "xck26"],
        )

        script = run_mock.call_args.kwargs["input"]
        self.assertIn("connect -url tcp:localhost:3121", script)
        self.assertIn("puts [jtag targets]", script)
        self.assertNotIn("configparams", script)

    @patch("shutil.which", return_value="xsdb")
    @patch("subprocess.run")
    def test_list_jtag_targets_rejects_autolaunch_without_target_output(
        self,
        run_mock: MagicMock,
        _which_mock: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "INFO: To connect to this hw_server instance use url: TCP:127.0.0.1:3121\n"
        proc.stderr = ""
        run_mock.return_value = proc

        with self.assertRaisesRegex(RuntimeError, "launched hw_server"):
            list_xilinx_hw_server_targets(host="localhost", port=3121)

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

    def test_ir_table_xilinx7_default(self):
        """Default ir_table matches the Xilinx 7-series preset."""
        t = OpenOcdTransport()
        self.assertEqual(t.ir_table, OpenOcdTransport.IR_TABLE_XILINX7)

    def test_ir_table_ultrascale_preset(self):
        """Constructing with the UltraScale preset switches the IR codes."""
        t = OpenOcdTransport(ir_table=OpenOcdTransport.IR_TABLE_US)
        self.assertEqual(t.ir_table[1], 0x24)  # USER1
        self.assertEqual(t.ir_table[2], 0x25)  # USER2
        self.assertEqual(t.ir_table[3], 0x26)  # USER3
        self.assertEqual(t.ir_table[4], 0x27)  # USER4

    def test_ir_table_gowin_preset(self):
        """Gowin GW_JTAG ER1/ER2 have their own IR opcodes."""
        t = OpenOcdTransport(ir_table=OpenOcdTransport.IR_TABLE_GOWIN)
        self.assertEqual(t.ir_table, {1: 0x42, 2: 0x43})

    def test_ir_table_alias(self):
        """IR_TABLE_US is the same dict as IR_TABLE_XILINX_ULTRASCALE."""
        self.assertIs(
            OpenOcdTransport.IR_TABLE_US,
            OpenOcdTransport.IR_TABLE_XILINX_ULTRASCALE,
        )

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

    def test_drscan_non_hex_response_raises_runtime_error(self):
        """OpenOCD errors should not leak raw int(..., 16) ValueError text."""
        t = OpenOcdTransport(tap="GW1NR-9C.tap")
        t._cmd = MagicMock(return_value="Tap 'GW1NR-9C.tap' not found")  # type: ignore[method-assign]

        with self.assertRaisesRegex(
            RuntimeError,
            r"OpenOCD drscan failed.*GW1NR-9C\.tap.*Tap 'GW1NR-9C\.tap' not found",
        ):
            t.raw_dr_scan(0, 49)


class FakeSpiPort:
    def __init__(self) -> None:
        self.regs: dict[int, int] = {}
        self.frames: list[bytes] = []

    def exchange(self, data: bytes, duplex: bool = True) -> bytes:
        self.frames.append(bytes(data))
        if data[0] == SpiRegisterTransport.CMD_READ:
            addr = (data[1] << 8) | data[2]
            value = self.regs.get(addr, 0)
            return bytes([0, 0, 0, 0]) + value.to_bytes(4, "big")
        if data[0] == SpiRegisterTransport.CMD_WRITE:
            addr = (data[1] << 8) | data[2]
            self.regs[addr] = int.from_bytes(data[3:7], "big")
            return bytes(len(data))
        return bytes(len(data))


class SpiRegisterTransportTests(unittest.TestCase):
    def test_read_reg_uses_spi_read_frame(self) -> None:
        spi = FakeSpiPort()
        spi.regs[0x0010] = 0x1234_ABCD
        t = SpiRegisterTransport(spi=spi)

        self.assertEqual(t.read_reg(0x0010), 0x1234_ABCD)
        self.assertEqual(spi.frames[-1], bytes([0x00, 0x00, 0x10, 0, 0, 0, 0, 0]))

    def test_write_reg_uses_spi_write_frame(self) -> None:
        spi = FakeSpiPort()
        t = SpiRegisterTransport(spi=spi)

        t.write_reg(0x0028, 0xDEAD_BEEF)

        self.assertEqual(spi.regs[0x0028], 0xDEAD_BEEF)
        self.assertEqual(
            spi.frames[-1],
            bytes([0x80, 0x00, 0x28, 0xDE, 0xAD, 0xBE, 0xEF, 0x00]),
        )

    def test_read_block_reads_consecutive_words(self) -> None:
        spi = FakeSpiPort()
        spi.regs[0x0100] = 1
        spi.regs[0x0104] = 2
        spi.regs[0x0108] = 3
        t = SpiRegisterTransport(spi=spi)

        self.assertEqual(t.read_block(0x0100, 3), [1, 2, 3])

    def test_read_before_connect_raises(self) -> None:
        t = SpiRegisterTransport()
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            t.read_reg(0)


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

    def test_ir_table_xilinx7_default(self):
        """Default ir_table matches the Xilinx 7-series preset."""
        t = XilinxHwServerTransport()
        self.assertEqual(t.ir_table, XilinxHwServerTransport.IR_TABLE_XILINX7)

    def test_ir_table_ultrascale_preset(self):
        """Constructing with the UltraScale preset switches the IR codes."""
        t = XilinxHwServerTransport(
            ir_table=XilinxHwServerTransport.IR_TABLE_US,
        )
        self.assertEqual(t.ir_table[1], 0x24)
        self.assertEqual(t.ir_table[2], 0x25)
        self.assertEqual(t.ir_table[3], 0x26)
        self.assertEqual(t.ir_table[4], 0x27)

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

    def test_parse_block_bits_can_skip_priming_word(self):
        """USER1 block parsing can discard a stale priming capture."""
        t = XilinxHwServerTransport()
        tokens = []
        for value in [0xDEAD_BEEF, 1, 2, 3]:
            tokens.append("".join("1" if (value >> i) & 1 else "0" for i in range(32)))

        self.assertEqual(
            t._parse_block_bits(" ".join(tokens), 3, skip_words=1),
            [1, 2, 3],
        )

    @staticmethod
    def _burst_token(values: list[int], sample_w: int = 8) -> str:
        """Pack values into one LSB-first 256-bit burst token."""
        bits = ["0"] * XilinxHwServerTransport.BURST_DR_BITS
        for sample_idx, value in enumerate(values):
            base = sample_idx * sample_w
            for bit_idx in range(sample_w):
                bits[base + bit_idx] = "1" if (value >> bit_idx) & 1 else "0"
        return "".join(bits)

    def test_parse_burst_bits_can_skip_priming_scan(self):
        """Burst parsing discards the priming scan when requested."""
        t = XilinxHwServerTransport()
        t._cached_sps = 32
        stale = self._burst_token([0xEE] * 32)
        fresh = self._burst_token(list(range(32)))

        vals = t._parse_burst_bits(f"{stale} {fresh}", 13, skip_scans=1)

        self.assertEqual(vals, list(range(13)))

    def test_read_block_burst_primes_user2_before_returned_scans(self):
        """Burst reads discard the first USER2 scan while staging fills."""
        t = XilinxHwServerTransport(single_chain_burst=False)
        t._cached_sps = 32
        sent: list[str] = []
        stale = self._burst_token([0xEE] * 32)
        fresh0 = self._burst_token(list(range(32)))
        fresh1 = self._burst_token(list(range(32, 64)))

        def fake_send(tcl: str) -> str:
            sent.append(tcl)
            return f"{stale} {fresh0} {fresh1}"

        t._send = fake_send  # type: ignore[method-assign]

        vals = t._read_block_burst(33)

        self.assertEqual(vals, list(range(33)))
        self.assertEqual(sent[0].count("drshift -state DRUPDATE -capture"), 3)

    def test_single_chain_burst_uses_active_chain_for_wide_scans(self):
        """Single-chain burst keeps BURST_PTR and 256-bit scans on the ELA chain."""
        t = XilinxHwServerTransport()
        t.select_chain(2)
        t._cached_sps = 32
        sent: list[str] = []
        stale = self._burst_token([0xEE] * 32)
        fresh = self._burst_token(list(range(32)))

        def fake_send(tcl: str) -> str:
            sent.append(tcl)
            return f"{stale} {fresh}"

        t._send = fake_send  # type: ignore[method-assign]

        vals = t._read_block_burst(8)

        self.assertEqual(vals, list(range(8)))
        self.assertIn("-hex 6 03", sent[0])
        self.assertNotIn("-hex 6 02", sent[0])
        self.assertIn("-bits 256", sent[0])

    def test_single_chain_burst_requires_stable_repeated_readback(self):
        """Single-chain retry rejects streams that never produce a stable pair."""
        t = XilinxHwServerTransport()
        t._cached_sps = 32
        prime = self._burst_token([0xAA] * 32)
        responses = [
            f"{prime} {self._burst_token([0x10] * 32)}",
            f"{prime} {self._burst_token([0x20] * 32)}",
            f"{prime} {self._burst_token([0x30] * 32)}",
            f"{prime} {self._burst_token([0x40] * 32)}",
        ]

        def fake_send(_tcl: str) -> str:
            return responses.pop(0)

        t._send = fake_send  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "did not stabilize"):
            t._read_block_burst(8)

    def test_single_chain_burst_accepts_first_stale_then_stable_pair(self):
        """A one-transaction stale read is tolerated only after stability."""
        t = XilinxHwServerTransport()
        t._cached_sps = 32
        prime = self._burst_token([0xAA] * 32)
        stale = f"{prime} {self._burst_token([0xEE] * 32)}"
        fresh = f"{prime} {self._burst_token(list(range(32)))}"
        responses = [stale, fresh, fresh]

        def fake_send(_tcl: str) -> str:
            return responses.pop(0)

        t._send = fake_send  # type: ignore[method-assign]

        vals = t._read_block_burst(8)

        self.assertEqual(vals, list(range(8)))
        self.assertEqual(responses, [])

    def test_two_chain_burst_can_be_selected_for_legacy_builds(self):
        """Legacy two-chain burst keeps 256-bit scans on USER2."""
        t = XilinxHwServerTransport(single_chain_burst=False)
        t._cached_sps = 32
        sent: list[str] = []
        stale = self._burst_token([0xEE] * 32)
        fresh = self._burst_token(list(range(32)))

        def fake_send(tcl: str) -> str:
            sent.append(tcl)
            return f"{stale} {fresh}"

        t._send = fake_send  # type: ignore[method-assign]

        vals = t._read_block_burst(8)

        self.assertEqual(vals, list(range(8)))
        self.assertIn("-hex 6 03", sent[0])
        self.assertIn("-bits 256", sent[0])

    def test_read_block_falls_back_when_user2_burst_missing(self):
        """Single-chain ELA builds can fall back to the USER1 DATA window."""
        t = XilinxHwServerTransport()

        def fail_burst(*args, **kwargs):
            raise RuntimeError("USER2 unavailable")

        t._read_block_burst = fail_burst  # type: ignore[method-assign]
        t._read_block_user1 = MagicMock(return_value=[1, 2, 3])  # type: ignore[method-assign]

        self.assertEqual(t.read_block(0x0100, 3), [1, 2, 3])
        self.assertFalse(t._has_burst)
        t._read_block_user1.assert_called_once_with(0x0100, 3)

    def test_single_chain_burst_fallback_logs_migration_hint(self):
        """Default single-chain failure should point legacy users at two-chain mode."""
        t = XilinxHwServerTransport()

        def fail_burst(*args, **kwargs):
            raise RuntimeError("single-chain burst readback did not stabilize")

        t._read_block_burst = fail_burst  # type: ignore[method-assign]
        t._read_block_user1 = MagicMock(return_value=[1, 2, 3])  # type: ignore[method-assign]

        with self.assertLogs("fcapz.transport.hw_server", level="WARNING") as logs:
            self.assertEqual(t.read_block(0x0100, 3), [1, 2, 3])

        text = "\n".join(logs.output)
        self.assertIn("SINGLE_CHAIN_BURST=0", text)
        self.assertIn("--two-chain-burst", text)

    def test_timestamp_block_falls_back_when_burst_missing(self):
        """Timestamp burst failures also disable fast burst reads."""
        t = XilinxHwServerTransport()

        def fail_burst(*args, **kwargs):
            raise RuntimeError("burst unavailable")

        t._read_block_burst = fail_burst  # type: ignore[method-assign]
        t._read_block_user1 = MagicMock(return_value=[4, 5])  # type: ignore[method-assign]

        self.assertEqual(t.read_timestamp_block(0x2100, 2, 32), [4, 5])
        self.assertFalse(t._has_burst)
        t._read_block_user1.assert_called_once_with(0x2100, 2)

    def test_timestamp_burst_primes_before_returned_scan(self):
        """Timestamp burst reads also discard the first fill scan."""
        t = XilinxHwServerTransport()
        sent: list[str] = []
        stale = self._burst_token([0xEE] * 8, sample_w=32)
        first = self._burst_token(list(range(8)), sample_w=32)

        def fake_send(tcl: str) -> str:
            sent.append(tcl)
            return f"{stale} {first}"

        t._send = fake_send  # type: ignore[method-assign]

        vals = t._read_block_burst(8, timestamp=True, element_width=32)

        self.assertEqual(vals, list(range(8)))
        self.assertEqual(sent[0].count("drshift -state DRUPDATE -capture"), 2)

    def test_user1_block_read_has_idle_before_each_capture(self):
        """USER1 pipelined reads leave CDC time before every captured word."""
        t = XilinxHwServerTransport()

        tcl = t._burst_read_tcl(0x0100, 0, 4)

        self.assertEqual(tcl.count(f"delay {t.READ_IDLE_CYCLES}"), 5)
        # xsdb 2025.2 requires `delay` to follow IDLE/PAUSE/RESET, so every
        # capture-and-delay pair parks the TAP in IDLE. The final scan has no
        # trailing delay and stays in DRUPDATE.
        self.assertEqual(tcl.count("drshift -state IDLE -capture"), 4)
        self.assertEqual(tcl.count("drshift -state DRUPDATE -capture"), 1)

    def test_default_chain_shape_emits_6bit_ir_and_49bit_dr(self):
        """Default (7-series single-device) chain stays at -hex 6 / -bits 49."""
        t = XilinxHwServerTransport()
        self.assertEqual(t.ir_length, 6)
        self.assertEqual(t.dr_extra_bits, 0)
        tcl = t._read_reg_tcl(t._frame_bits(addr=0x10, data=0, write=False))
        self.assertIn("-hex 6 02", tcl)
        self.assertIn("-bits 49", tcl)
        self.assertNotIn("-bits 50", tcl)

    def test_zynq_us_plus_chain_shape_emits_16bit_ir_and_50bit_dr(self):
        """Zynq US+ MPSoC: 16-bit chain IR + 1 BYPASS bit = -hex 16 / -bits 50."""
        t = XilinxHwServerTransport(
            ir_length=16,
            dr_extra_bits=1,
            dr_extra_position="tdo",
            ir_table={1: 0x824F, 2: 0x825F, 3: 0x826F, 4: 0x827F},
        )
        tcl = t._read_reg_tcl(t._frame_bits(addr=0x10, data=0, write=False))
        # IR = 16 bits, opcode formatted as 4 hex digits (0x824F = USER1+BYPASS).
        self.assertIn("-hex 16 824f", tcl)
        # DR = fcapz 49 + 1 BYPASS = 50 bits; 50-char payload.
        self.assertIn("-bits 50", tcl)
        # The padded frame ("0" + 49-char fcapz) must appear in both drshifts.
        padded_frame = "0" + t._frame_bits(addr=0x10, data=0, write=False)
        self.assertEqual(len(padded_frame), 50)
        self.assertEqual(tcl.count(padded_frame), 2)

    def test_chain_shape_parser_strips_bypass_bit(self):
        """_parse_bits_u32 reads from offset dr_extra_bits when bypass is TDO-side."""
        t = XilinxHwServerTransport(
            ir_length=16, dr_extra_bits=1, dr_extra_position="tdo",
            ir_table={1: 0x824F},
        )
        # Build a 50-bit captured token: 1 BYPASS bit + 32-bit value 0xDEADBEEF
        # padded to fill the 49-bit fcapz frame width.
        value = 0xDEADBEEF
        data_bits = "".join("1" if (value >> i) & 1 else "0" for i in range(32))
        token = "1" + data_bits + ("0" * 17)  # bypass + data + addr/rnw filler
        self.assertEqual(len(token), 50)
        parsed = t._parse_bits_u32(token)
        self.assertEqual(parsed, value)

    def test_register_ir_mode_emits_named_irshift(self):
        """use_register_ir=True emits '-register user{N}' instead of '-hex'."""
        t = XilinxHwServerTransport(use_register_ir=True)
        t._active_chain = 1
        tcl = t._read_reg_tcl(t._frame_bits(0x10, 0, False))
        self.assertIn("-register user1", tcl)
        self.assertNotIn("-hex", tcl)
        # DR should be standard 49 bits (no extra)
        self.assertIn("-bits 49", tcl)
        self.assertNotIn("-bits 50", tcl)

    def test_register_ir_write_uses_drupdate(self):
        """Writes in register mode use -state DRUPDATE + split sequence."""
        t = XilinxHwServerTransport(use_register_ir=True)
        t._active_chain = 1
        tcl = t._write_reg_tcl(t._frame_bits(0x14, 0xCAFE, True))
        self.assertIn("-register user1", tcl)
        self.assertIn("-state DRUPDATE", tcl)
        self.assertIn("state IDLE", tcl)
        self.assertIn(f"delay {t.WRITE_IDLE_CYCLES_REGISTER}", tcl)

    def test_register_ir_forces_dr_extra_bits_zero(self):
        """use_register_ir overrides dr_extra_bits to 0."""
        t = XilinxHwServerTransport(
            use_register_ir=True, dr_extra_bits=1, dr_extra_position="tdi",
        )
        self.assertEqual(t.dr_extra_bits, 0)
        self.assertTrue(t.use_register_ir)

    def test_register_ir_select_chain_accepts_1_to_4(self):
        t = XilinxHwServerTransport(use_register_ir=True)
        for ch in (1, 2, 3, 4):
            t.select_chain(ch)
            self.assertEqual(t._active_chain, ch)
        with self.assertRaises(ValueError):
            t.select_chain(5)

    def test_chain_shape_validation(self):
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(ir_length=0)
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(dr_extra_bits=-1)
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(dr_extra_position="middle")

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

    def test_bitfile_with_brace_rejected(self):
        # Unbalanced braces would terminate the TCL {path} group early.
        with self.assertRaises(ValueError):
            XilinxHwServerTransport(fpga_name="xc7a100t", bitfile="C:/evil}.bit")

    def test_windows_bitfile_accepted(self):
        # Backslashes are part of legitimate Windows paths and must be allowed
        # (the path is interpolated inside TCL braces which disable substitution).
        t = XilinxHwServerTransport(
            fpga_name="xc7a100t",
            bitfile=r"C:\Projects\fpgacapZero\examples\arty_a7\arty_a7_top.bit",
        )
        self.assertIn("\\", t.bitfile)

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
