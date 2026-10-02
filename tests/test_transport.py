# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Tests for Transport ABC contracts and failure modes.

All tests here use mocks or deliberately broken transports — no real
hardware or network connection required.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fcapz.transport import (
    BurstIntegrityError,
    DataWindowError,
    check_data_window,
    find_quartus_stp,
    list_xilinx_hw_server_targets,
    OpenOcdTransport,
    QuartusStpTransport,
    Transport,
    XilinxHwServerTransport,
    _StpSession,
    parse_xsdb_jtag_targets,
)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _install_session(t, proc, out=None):
    """Publish a mocked ``quartus_stp`` session on *t*, as connect() would."""
    session = _StpSession(proc)
    if out is not None:
        session.out = out
    t._session = session
    return session


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

    def test_parse_jtag_targets_keeps_the_selected_fpga(self) -> None:
        # xsdb's real output once xc7a100t is selected: the marker follows
        # the number.  Dropping it hid the selected board from connect().
        raw = """
          1  Digilent Arty A7-100T 210319B26DC2A
             2* xc7a100t (idcode 13631093 irlen 6 fpga)
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

class DataWindowCheckTests(unittest.TestCase):
    def test_limits(self):
        check_data_window(0x0100, (0xF000 - 0x0100) // 4, 0xF000)  # ends at 0xEFFC
        with self.assertRaises(DataWindowError):
            check_data_window(0x0100, (0xF000 - 0x0100) // 4 + 1, 0xF000)
        check_data_window(0x0100, (0x10000 - 0x0100) // 4)  # ends at 0xFFFC
        with self.assertRaises(DataWindowError):
            check_data_window(0x0100, (0x10000 - 0x0100) // 4 + 1)
        # A read starting at or past the end is refused too; an empty one is not.
        with self.assertRaises(DataWindowError):
            check_data_window(0xF000, 8, 0xF000)
        with self.assertRaises(DataWindowError):
            check_data_window(0x0100, 1, 0x0100)
        check_data_window(0x0100, 0, 0x0100)


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

    def test_read_reg_stable_base_default_reads_once(self):
        """The base stable-read hook is opt-in and does not add extra scans."""
        calls: list[int] = []

        class TracingTransport(ConcreteTransport):
            def read_reg(self, addr: int) -> int:
                calls.append(addr)
                return 0x1234

        t = TracingTransport()
        self.assertEqual(t.read_reg_stable(0x000C), 0x1234)
        self.assertEqual(calls, [0x000C])

    def test_xsdb_read_reg_stable_reads_once(self):
        """hw_server reads commit with UPDATE-DR and clock idle TCKs, so a
        stable read needs no discarded warmup scan."""
        calls: list[int] = []
        t = XilinxHwServerTransport()

        def fake_read_reg(addr: int) -> int:
            calls.append(addr)
            return 0x20

        t.read_reg = fake_read_reg  # type: ignore[method-assign]
        self.assertEqual(t.read_reg_stable(0x000C), 0x20)
        self.assertEqual(calls, [0x000C])


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

    def test_list_taps_parses_jtag_names(self):
        """list_taps() splits OpenOCD 'jtag names' output."""
        t = OpenOcdTransport()
        with patch.object(t, "_cmd", return_value="GW1NR-9C.tap"):
            self.assertEqual(t.list_taps(), ["GW1NR-9C.tap"])

    def test_connect_resolves_auto_tap_to_first(self):
        """tap='auto' is resolved to the first tap OpenOCD reports on connect."""
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""
        with patch("socket.create_connection", return_value=mock_sock), patch.object(
            OpenOcdTransport, "list_taps", return_value=["GW1NR-9C.tap", "other.tap"]
        ):
            t = OpenOcdTransport(tap="auto")
            t.connect()
            self.assertEqual(t.tap, "GW1NR-9C.tap")

    def test_connect_keeps_explicit_tap(self):
        """A concrete tap name is left untouched (no auto-resolution)."""
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""
        with patch("socket.create_connection", return_value=mock_sock), patch.object(
            OpenOcdTransport, "list_taps"
        ) as list_taps:
            t = OpenOcdTransport(tap="GW1NR-9C.tap")
            t.connect()
            self.assertEqual(t.tap, "GW1NR-9C.tap")
            list_taps.assert_not_called()

    def test_resolve_auto_tap_raises_when_no_taps(self):
        """tap='auto' against an OpenOCD with no taps gives a clear error."""
        t = OpenOcdTransport(tap="auto")
        with patch.object(t, "list_taps", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "no JTAG taps"):
                t._resolve_auto_tap()

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


class QuartusStpTransportTests(unittest.TestCase):
    """Intel/Altera USB-Blaster transport helpers."""

    @staticmethod
    def _quartus_burst_token(values: list[int], element_width: int = 8) -> str:
        packed = 0
        mask = (1 << element_width) - 1
        for idx, value in enumerate(values):
            packed |= (value & mask) << (idx * element_width)
        return f"{packed:0256b}"

    def test_find_quartus_stp_explicit_passthrough(self):
        self.assertEqual(find_quartus_stp("/x/quartus_stp"), "/x/quartus_stp")

    def test_find_quartus_stp_prefers_shell_over_windowed(self):
        # Auto-detect must return the quartus_stp Tcl shell, never the
        # quartus_stpw windowed SignalTap GUI that sits beside it in bin/.
        import os
        import tempfile

        suffix = ".exe" if os.name == "nt" else ""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp) / "quartus" / "bin64"
            bindir.mkdir(parents=True)
            (bindir / f"quartus_stpw{suffix}").write_text("")  # GUI decoy
            (bindir / f"quartus_stp{suffix}").write_text("")
            with patch("fcapz.transport.shutil.which", return_value=None), patch.dict(
                os.environ, {"QUARTUS_ROOTDIR": str(Path(tmp) / "quartus")}
            ):
                got = find_quartus_stp()
            self.assertIsNotNone(got)
            self.assertTrue(got.lower().endswith(f"quartus_stp{suffix}".lower()))
            self.assertNotIn("stpw", got.lower())

    def test_shift_string_is_fixed_width_binary_value(self):
        self.assertEqual(QuartusStpTransport._int_to_shift_string(0b0101, 4), "0101")
        self.assertEqual(QuartusStpTransport._shift_string_to_int("0101", 4), 0b0101)

    def test_shift_string_rejects_non_binary_output(self):
        with self.assertRaisesRegex(RuntimeError, "non-binary"):
            QuartusStpTransport._shift_string_to_int("0x5", 4)

    def test_select_chain_accepts_rtl_chain_instance_indices(self):
        t = QuartusStpTransport()
        self.assertEqual(t._active_chain, 1)
        t.select_chain(1)
        self.assertEqual(t._active_chain, 1)
        t.select_chain(3)
        self.assertEqual(t._active_chain, 3)
        with self.assertRaises(ValueError):
            t.select_chain(0)

    def test_raw_dr_scan_emits_unlock_outside_inner_catch(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return "0" * 49

        t = FakeQuartus()
        t.raw_dr_scan(0, 49)
        script = scripts[0]
        self.assertIn("set __fcapz_scan_status [catch {", script)
        self.assertLess(script.index("device_virtual_ir_shift"), script.index("device_unlock"))
        self.assertLess(script.index("} __fcapz_scan_error]"), script.index("device_unlock"))
        self.assertIn("if {$__fcapz_scan_status}", script)

    def test_read_sample_block_single_chain_burst(self):
        # Three 160-bit samples, each five distinct 32-bit words (little-endian).
        samples = []
        for i in range(3):
            words = [0x10 * i + j + 1 for j in range(5)]  # distinct, nonzero
            val = 0
            for j, w in enumerate(words):
                val |= (w & 0xFFFFFFFF) << (32 * j)
            samples.append((val, words))
        # The burst returns one 256-bit scan per sample (low 160 bits = sample);
        # the first (prime) scan flushes staging and is discarded.
        tokens = ["0" * 256] + [f"{val:0256b}" for val, _ in samples]
        payload = " ".join(tokens)

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                self.last_script = script
                return payload

        t = FakeQuartus()
        t.select_chain(5)  # the monitor's single BSCAN instance
        out = t.read_sample_block(0x0100, len(samples), 160)

        expected = [w for _, words in samples for w in words]
        self.assertEqual(out, expected)
        # Burst scans must target the active control chain, not the ELA's chain 2.
        self.assertIn("-instance_index 5", t.last_script)
        self.assertNotIn("-instance_index 2", t.last_script)
        # One 256-bit DR scan per sample plus one prime scan; one 49-bit BURST_PTR write.
        self.assertEqual(t.last_script.count("-length 256"), len(samples) + 1)
        self.assertEqual(t.last_script.count("-length 49"), 1)

    def test_read_timestamp_block_single_chain_sets_timestamp_bit(self):
        # Four 32-bit timestamps pack into one 256-bit scan (8 per scan), plus
        # one discarded prime scan -- read on the active chain, not the ELA's.
        ts = [10, 21, 33, 48]
        val = 0
        for i, v in enumerate(ts):
            val |= (v & 0xFFFFFFFF) << (32 * i)
        payload = " ".join(["0" * 256, f"{val:0256b}"])

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                self.last_script = script
                return payload

        t = FakeQuartus()
        t.select_chain(5)  # the monitor's single BSCAN instance
        out = t.read_timestamp_block_single_chain(0x1100, len(ts), 32)

        self.assertEqual(out, ts)
        # Burst pointer must assert the timestamp-select bit (0x80000000), unlike
        # the sample burst which starts at sample 0.
        ts_frame = (1 << 48) | (t.ADDR_BURST_PTR << 32) | 0x80000000
        sample_frame = (1 << 48) | (t.ADDR_BURST_PTR << 32)
        self.assertIn(f"{ts_frame:049b}", t.last_script)
        self.assertNotIn(f"{sample_frame:049b}", t.last_script)
        # Same single-chain routing as the sample burst: active chain, not chain 2.
        self.assertIn("-instance_index 5", t.last_script)
        self.assertNotIn("-instance_index 2", t.last_script)

    def test_send_times_out_waiting_for_sentinel(self):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.poll.return_value = None
        proc.kill = MagicMock()
        t = QuartusStpTransport(read_timeout_sec=0.01)
        _install_session(t, proc)
        with self.assertRaises(TimeoutError):
            t._send("puts hello")
        proc.kill.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "reconnect|not connected"):
            t._send("puts again")

    def test_send_raises_runtime_error_on_tcl_error(self):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=0.01)
        session = _install_session(t, proc)
        session.out.put("ERROR: virtual dr failed\n")
        session.out.put(f"{QuartusStpTransport._SENTINEL}\n")
        with self.assertRaisesRegex(RuntimeError, "virtual dr failed"):
            t._send("device_virtual_dr_shift")

    def test_send_strips_quartus_prompt_prefixes(self):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=0.01)
        session = _install_session(t, proc)
        session.out.put("tcl> tcl> 0001\n")
        session.out.put(f"tcl> {QuartusStpTransport._SENTINEL}\n")
        self.assertEqual(t._send("device_virtual_dr_shift"), "0001")

    def test_send_strips_quartus_continuation_prompts_and_raises_error(self):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=0.01)
        session = _install_session(t, proc)
        session.out.put("> > > 1\n")
        session.out.put("> > ERROR: virtual dr shift failed\n")
        session.out.put("> >     while executing device_virtual_dr_shift\n")
        session.out.put(f"> {QuartusStpTransport._SENTINEL}\n")
        with self.assertRaisesRegex(RuntimeError, "while executing"):
            t._send("device_virtual_dr_shift")

    def test_prettify_device_name_strips_position_prefix(self):
        pretty = QuartusStpTransport._prettify_device_name
        # quartus_stp echoes "@N: <device>" -- @N is the chain position, not part
        # of the device; strip it and collapse whitespace.
        self.assertEqual(
            pretty("@1: A5EB013BB23BCS  (0x4362C0DD)"),
            "A5EB013BB23BCS (0x4362C0DD)",
        )
        self.assertEqual(pretty("EP4CE6 (0x020F10DD)"), "EP4CE6 (0x020F10DD)")
        # Empty / whitespace -> None so the UI omits the device rather than
        # showing a blank.
        self.assertIsNone(pretty(""))
        self.assertIsNone(pretty("   "))

    def test_send_translates_missing_instance_to_no_cores(self):
        # quartus_stp reports "virtual JTAG instance cannot be found" only when
        # the FPGA carries no fpgacapZero cores -- surface that plainly, and do
        # not leak JTAG/cable-fault wording (the connection is fine).
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=0.01)
        session = _install_session(t, proc)
        session.out.put("ERROR: The specified virtual JTAG instance cannot be found.\n")
        session.out.put(f"{QuartusStpTransport._SENTINEL}\n")
        with self.assertRaisesRegex(RuntimeError, "No fpgacapZero-compatible cores") as ctx:
            t._send("device_virtual_dr_shift")
        msg = str(ctx.exception)
        self.assertNotIn("JTAG", msg)
        self.assertNotIn("virtual JTAG instance", msg)

    def test_send_rejects_sentinel_collision(self):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport()
        _install_session(t, proc)
        with self.assertRaises(ValueError):
            t._send(f"puts {QuartusStpTransport._SENTINEL}")

    def test_write_reg_uses_virtual_dr_scan(self):
        calls: list[tuple[int, int, int | None]] = []

        class FakeQuartus(QuartusStpTransport):
            def raw_dr_scan(self, bits, width, *, chain=None):
                calls.append((bits, width, chain))
                return 0

        t = FakeQuartus()
        t.write_reg(0x1234, 0xDEADBEEF)
        expected = (1 << 48) | (0x1234 << 32) | 0xDEADBEEF
        self.assertEqual(calls, [(expected, 49, None)])

    def test_open_device_auto_script_errors_on_multiple_quartus_cables(self):
        script = QuartusStpTransport()._open_device_script()
        self.assertIn("get_hardware_names", script)
        self.assertIn("multiple Quartus JTAG cables found; pass --hardware", script)
        self.assertIn('string match "@1*"', script)

    def test_read_reg_choreography(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return f"{0x12345678:049b}"

        t = FakeQuartus()
        self.assertEqual(t.read_reg(0x20), 0x12345678)
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0].count("device_lock"), 1)
        self.assertEqual(scripts[0].count("device_unlock"), 1)
        self.assertEqual(scripts[0].count("device_virtual_ir_shift"), 1)
        self.assertEqual(scripts[0].count("device_virtual_dr_shift"), 2)
        self.assertIn("device_run_test_idle", scripts[0])

    def test_raw_dr_scan_batch_uses_one_lock_window(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return "0001 0010"

        t = FakeQuartus()
        self.assertEqual(t.raw_dr_scan_batch([(1, 4), (2, 4)]), [1, 2])
        self.assertEqual(scripts[0].count("device_lock"), 1)
        self.assertEqual(scripts[0].count("device_unlock"), 1)
        self.assertEqual(scripts[0].count("device_virtual_ir_shift"), 1)
        self.assertEqual(scripts[0].count("device_virtual_dr_shift"), 2)

    def test_raw_dr_scan_batch_empty_is_noop(self):
        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                raise AssertionError("empty raw_dr_scan_batch should not send Tcl")

        self.assertEqual(FakeQuartus().raw_dr_scan_batch([]), [])

    def test_raw_scan_chain_override_does_not_mutate_active_chain(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return "0" * 49

        t = FakeQuartus()
        t.select_chain(1)
        t.raw_dr_scan(0, 49, chain=5)
        self.assertIn("-instance_index 5", scripts[-1])
        self.assertEqual(t._active_chain, 1)

    def test_raw_scan_batch_chain_override_does_not_mutate_active_chain(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return "0000"

        t = FakeQuartus()
        t.select_chain(1)
        t.raw_dr_scan_batch([(0, 4)], chain=3)
        self.assertIn("-instance_index 3", scripts[-1])
        self.assertEqual(t._active_chain, 1)

    def test_read_reg_uses_configurable_lock_timeout_and_idle_cycles(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return f"{0x12345678:049b}"

        t = FakeQuartus(lock_timeout_ms=5000, read_idle_cycles=42)
        t.read_reg(0x20)
        self.assertIn("device_lock -timeout 5000", scripts[0])
        self.assertIn("device_run_test_idle -num_clocks 42", scripts[0])

    def test_virtual_ir_result_is_discarded(self):
        script = QuartusStpTransport()._virtual_ir_tcl(1)
        self.assertIn("set __fcapz_ir_discard [device_virtual_ir_shift", script)
        self.assertIn("-no_captured_ir_value]", script)

    def test_send_returns_final_non_error_result_line(self):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=0.01)
        session = _install_session(t, proc)
        session.out.put("tcl> 0\n")
        session.out.put("tcl> 0001\n")
        session.out.put(f"tcl> {QuartusStpTransport._SENTINEL}\n")
        self.assertEqual(t._send("device_virtual_dr_shift"), "0001")

    def test_read_block_uses_one_lock_window(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return f"{0x11111111:049b} {0x22222222:049b}"

        t = FakeQuartus()
        self.assertEqual(t.read_block(0x20, 2), [0x11111111, 0x22222222])
        self.assertEqual(scripts[0].count("device_lock"), 1)
        self.assertEqual(scripts[0].count("device_unlock"), 1)
        self.assertEqual(scripts[0].count("device_virtual_ir_shift"), 1)
        self.assertEqual(scripts[0].count("device_virtual_dr_shift"), 4)

    def test_read_block_data_window_uses_burst_data_chain(self):
        scripts: list[str] = []
        packed = sum(value << (idx * 8) for idx, value in enumerate([1, 2, 3, 4, 5]))
        sample_width_reads: list[int] = []

        class FakeQuartus(QuartusStpTransport):
            def read_reg(self, addr):
                sample_width_reads.append(addr)
                return 8

            def _send(self, script):
                scripts.append(script)
                return f"{0:0256b} {packed:0256b}"

        t = FakeQuartus(burst_data_chain=7, burst_prefill_idle_cycles=123)
        t.select_chain(5)
        self.assertEqual(t.read_block(0x0100, 5), [1, 2, 3, 4, 5])
        self.assertEqual(sample_width_reads, [0x000C])
        self.assertEqual(len(scripts), 1)
        self.assertIn("-instance_index 5", scripts[0])
        self.assertIn("-instance_index 7", scripts[0])
        self.assertIn("device_run_test_idle -num_clocks 123", scripts[0])
        self.assertIn("-length 256", scripts[0])

    def test_quartus_burst_primes_data_chain_before_returned_scans(self):
        scripts: list[str] = []
        stale = self._quartus_burst_token([0xEE] * 32)
        fresh0 = self._quartus_burst_token(list(range(32)))
        fresh1 = self._quartus_burst_token(list(range(32, 64)))

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return f"{stale} {fresh0} {fresh1}"

        t = FakeQuartus()
        t._cached_sps = 32
        self.assertEqual(t._read_block_burst(33), list(range(33)))
        self.assertEqual(len(scripts), 1)  # one pass, no repeat
        self.assertEqual(scripts[0].count("-length 256"), 3)

    def test_quartus_timestamp_burst_primes_and_selects_timestamp_stream(self):
        scripts: list[str] = []
        stale = self._quartus_burst_token([0xEE] * 8, element_width=32)
        fresh = self._quartus_burst_token(list(range(8)), element_width=32)

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return f"{stale} {fresh}"

        t = FakeQuartus()
        self.assertEqual(
            t._read_block_burst(8, timestamp=True, element_width=32),
            list(range(8)),
        )
        timestamp_frame = (1 << 48) | (t.ADDR_BURST_PTR << 32) | 0x80000000
        self.assertIn(t._int_to_shift_string(timestamp_frame, t.DR_BITS), scripts[0])
        self.assertEqual(scripts[0].count("-length 256"), 2)

    def test_quartus_read_block_falls_back_and_disables_failed_burst(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return f"{1:049b} {2:049b}"

        t = FakeQuartus()
        t._read_block_burst = MagicMock(side_effect=RuntimeError("DATA_CHAIN missing"))  # type: ignore[method-assign]

        with self.assertLogs("fcapz.transport.quartus_stp", level="WARNING") as logs:
            self.assertEqual(t.read_block(0x0100, 2), [1, 2])
        self.assertIn("falling back", "\n".join(logs.output))
        self.assertFalse(t._burst_available)

        self.assertEqual(t.read_block(0x0100, 2), [1, 2])
        t._read_block_burst.assert_called_once_with(2)
        self.assertEqual(len(scripts), 2)

    def test_quartus_timestamp_block_falls_back_and_disables_failed_burst(self):
        scripts: list[str] = []

        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                scripts.append(script)
                return f"{4:049b} {5:049b}"

        t = FakeQuartus()
        t._read_block_burst = MagicMock(side_effect=RuntimeError("timestamp missing"))  # type: ignore[method-assign]

        with self.assertLogs("fcapz.transport.quartus_stp", level="WARNING") as logs:
            self.assertEqual(t.read_timestamp_block(0x1100, 2, 32), [4, 5])
        self.assertIn("timestamp burst readback failed", "\n".join(logs.output))
        self.assertFalse(t._burst_available)
        t._read_block_burst.assert_called_once_with(
            2,
            timestamp=True,
            element_width=32,
        )
        self.assertEqual(len(scripts), 1)

    def test_read_block_zero_words_is_noop(self):
        class FakeQuartus(QuartusStpTransport):
            def _send(self, script):
                raise AssertionError("zero-word read_block should not send Tcl")

        self.assertEqual(FakeQuartus().read_block(0x20, 0), [])

    def test_locked_script_rejects_empty_body(self):
        with self.assertRaises(ValueError):
            QuartusStpTransport()._locked_script(
                body=[],
                status="__status",
                error="__error",
            )

    def test_connect_send_close_with_fake_quartus_stp(self):
        fake_stp = ROOT / "tests" / "fixtures" / "fake_quartus_stp.py"
        t = QuartusStpTransport(
            quartus_stp_argv=[sys.executable, str(fake_stp), "-s"],
            read_timeout_sec=2.0,
        )
        t.connect()
        try:
            wide_frame = (1 << 48) | (1 << 47) | 1
            self.assertEqual(t.raw_dr_scan(wide_frame, 49), wide_frame)
            self.assertEqual(t.read_reg(0x20), 0x12345678)
            self.assertEqual(t.read_block(0x20, 2), [1, 2])
            self.assertEqual(t.raw_dr_scan_batch([(0x11, 49), (0x22, 49)]), [0x11, 0x22])
        finally:
            t.close()

    # -- close() must not return while quartus_stp still holds the cable -----

    @staticmethod
    def _fake_quartus(name="fake_quartus_stp.py", **kwargs):
        return QuartusStpTransport(
            quartus_stp_argv=[sys.executable, str(ROOT / "tests" / "fixtures" / name), "-s"],
            read_timeout_sec=5.0,
            **kwargs,
        )

    def test_quartus_close_waits_for_the_process_to_exit(self):
        """A second connection cannot open the USB-Blaster while the first
        quartus_stp is alive, so close() must not return before it is gone."""
        t = self._fake_quartus()
        t.connect()
        proc = t._proc
        self.assertIsNotNone(proc)
        t.close()
        self.assertIsNotNone(proc.poll(), "close() returned with quartus_stp still running")
        self.assertIsNone(t._proc)
        t.close()  # idempotent, per the Transport contract

    def test_quartus_close_actually_sends_close_device(self):
        """close() must run Quartus' own teardown, not just kill the process.

        _send refuses to talk to a poisoned transport, so marking the session
        closed before the teardown silently skips close_device and leaves the
        cable to be freed by process exit alone -- with the failure swallowed
        by close()'s own except.
        """
        sent = []

        class Spy(QuartusStpTransport):
            def _send(self, script, **kwargs):
                try:
                    out = super()._send(script, **kwargs)
                except Exception as exc:
                    sent.append((type(exc).__name__, script))
                    raise
                sent.append(("OK", script))
                return out

        t = Spy(
            quartus_stp_argv=[
                sys.executable,
                str(ROOT / "tests" / "fixtures" / "fake_quartus_stp.py"),
                "-s",
            ],
            read_timeout_sec=5.0,
        )
        t.connect()
        t.close()
        teardown = [(kind, s) for kind, s in sent if "close_device" in s]
        self.assertEqual(len(teardown), 1, f"close_device not attempted: {sent}")
        self.assertEqual(
            teardown[0][0], "OK", f"close_device was attempted but failed: {teardown}"
        )

    def test_quartus_close_kills_a_process_that_ignores_exit(self):
        t = self._fake_quartus("fake_quartus_stp_stubborn.py")
        t.CLOSE_GRACE_SEC = 0.3
        t.CLOSE_TERM_SEC = 0.3
        t.CLOSE_KILL_SEC = 2.0
        t.connect()
        proc = t._proc
        t.close()
        self.assertIsNotNone(proc.poll(), "close() left an unkillable quartus_stp running")

    def test_quartus_close_then_connect_starts_a_clean_session(self):
        """The reconnect path a script takes when it opens a second session."""
        t = self._fake_quartus()
        t.connect()
        first = t._proc
        t.close()
        t.connect()
        try:
            self.assertIsNot(t._proc, first)
            self.assertEqual(t.read_reg(0x20), 0x12345678)
        finally:
            t.close()

    def test_quartus_close_is_bounded_while_another_request_holds_the_io_lock(self):
        """A stalled request elsewhere must not stop close() reaching kill.

        The graceful teardown needs the I/O lock; if another thread's request
        is stuck holding it, close() has to give up on that and escalate
        rather than wait for the lock forever.
        """
        t = self._fake_quartus()
        t.CLOSE_GRACE_SEC = 0.3
        t.CLOSE_TERM_SEC = 0.5
        t.CLOSE_KILL_SEC = 1.0
        t.connect()
        proc = t._proc
        t._stp_io_lock.acquire()  # a request on another thread, stalled
        try:
            closer = threading.Thread(target=t.close, daemon=True)
            closer.start()
            closer.join(timeout=5)
            self.assertFalse(closer.is_alive(), "close() blocked on the I/O lock")
            self.assertIsNotNone(proc.poll(), "close() returned with quartus_stp alive")
        finally:
            t._stp_io_lock.release()

    def test_quartus_send_deadline_is_not_reset_by_chatter(self):
        """With a timeout, output that never contains the sentinel must not
        keep a request alive: the deadline covers the whole response."""
        proc = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=30.0)
        session = _install_session(t, proc)
        stop = threading.Event()

        def chatter():
            while not stop.is_set():
                session.out.put("tcl> still working\n")
                stop.wait(0.01)

        feeder = threading.Thread(target=chatter, daemon=True)
        feeder.start()
        outcome = []

        def request():
            try:
                t._send("puts hello", timeout=0.2)
                outcome.append("returned")
            except TimeoutError:
                outcome.append("timeout")

        try:
            worker = threading.Thread(target=request, daemon=True)
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive(), "chatter kept resetting the deadline")
            self.assertEqual(outcome, ["timeout"])
        finally:
            stop.set()
            feeder.join(timeout=2)

    def test_quartus_stale_timeout_does_not_kill_the_replacement_session(self):
        """A request that times out on the old session must retire THAT
        session only, and reap it, even if connect() has already installed a
        new one on the transport."""
        old = MagicMock()
        old.poll.return_value = None
        new = MagicMock()
        new.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=0.3)
        _install_session(t, old)
        sent = threading.Event()
        old.stdin.flush.side_effect = lambda: sent.set()
        outcome = []

        def request():
            try:
                t._send("puts hello")
                outcome.append("returned")
            except TimeoutError:
                outcome.append("timeout")

        worker = threading.Thread(target=request, daemon=True)
        worker.start()
        self.assertTrue(sent.wait(timeout=5), "request never reached the old session")
        # What connect() does while that request is still waiting.
        replacement = _install_session(t, new)
        worker.join(timeout=5)

        self.assertEqual(outcome, ["timeout"])
        old.kill.assert_called()
        new.kill.assert_not_called()
        self.assertIs(t._session, replacement, "the stale timeout detached the new session")
        self.assertFalse(replacement.dead, "the stale timeout marked the new session dead")
        old.wait.assert_called()  # reaped, not just signalled
        old.stdout.close.assert_called()

    def test_quartus_connect_retires_a_session_still_open(self):
        """connect() on an open transport must not leak the previous process,
        which would otherwise keep holding the cable with nothing to close it."""
        t = self._fake_quartus()
        t.connect()
        first = t._proc
        t.connect()
        try:
            self.assertIsNotNone(first.poll(), "the replaced quartus_stp is still running")
            self.assertEqual(t.read_reg(0x20), 0x12345678)
        finally:
            t.close()

    def test_quartus_connect_failure_does_not_orphan_the_process(self):
        """A failed open must not leave quartus_stp holding the cable."""
        leaked = []

        class FailingOpen(QuartusStpTransport):
            def _open_device_script(self):
                leaked.append(self._proc)
                raise RuntimeError("cable busy")

        t = FailingOpen(
            quartus_stp_argv=[
                sys.executable,
                str(ROOT / "tests" / "fixtures" / "fake_quartus_stp.py"),
                "-s",
            ],
            read_timeout_sec=5.0,
        )
        with self.assertRaises(RuntimeError):
            t.connect()
        self.assertIsNone(t._proc)
        self.assertEqual(len(leaked), 1)
        self.assertIsNotNone(leaked[0].poll(), "connect() failure orphaned quartus_stp")

    # -- review repros: each failed against the previous lifecycle design ----

    def test_quartus_late_response_is_not_read_as_the_next_request(self):
        """A request that times out may still get its answer later.  The next
        request must refuse the session rather than take that answer as its
        own -- it would return another register's value."""
        retiring = threading.Event()

        class Spy(QuartusStpTransport):
            def _retire_session(self, *args):
                retiring.set()
                super()._retire_session(*args)

        proc = MagicMock()
        proc.poll.return_value = None
        t = Spy(read_timeout_sec=5.0)
        session = _install_session(t, proc)
        outcome = []

        def request_a():
            try:
                t._send("puts A", timeout=0.2)
                outcome.append("returned")
            except TimeoutError:
                outcome.append("timeout")

        # Holding the lifecycle lock stalls A between releasing the I/O lock
        # and retiring its session: the window in which B can get in.
        t._life_lock.acquire()
        try:
            a = threading.Thread(target=request_a, daemon=True)
            a.start()
            self.assertTrue(retiring.wait(timeout=5), "request A never timed out")
            session.out.put(f"tcl> {0x11111111:049b}\n")  # A's late answer
            session.out.put(f"tcl> {QuartusStpTransport._SENTINEL}\n")
            with self.assertRaisesRegex(RuntimeError, "reconnect"):
                t._send("puts B")
        finally:
            t._life_lock.release()
        a.join(timeout=5)
        self.assertEqual(outcome, ["timeout"])

    def test_quartus_close_cancels_a_connect_stuck_in_its_handshake(self):
        """The GUI cancels a connect by calling close() from another thread.
        An open_device that keeps printing without ever finishing must not
        make that close() wait for the connect to give up by itself."""
        t = self._fake_quartus("fake_quartus_stp_chatty.py")
        t.read_timeout_sec = 30.0
        t.CLOSE_GRACE_SEC = 0.3
        t.CLOSE_TERM_SEC = 0.3
        t.CLOSE_KILL_SEC = 1.0
        outcome = []

        def connect():
            try:
                t.connect()
                outcome.append("connected")
            except Exception as exc:
                outcome.append(type(exc).__name__)

        connector = threading.Thread(target=connect, daemon=True)
        connector.start()
        deadline = time.monotonic() + 5
        while t._proc is None and time.monotonic() < deadline:
            time.sleep(0.01)
        proc = t._proc
        self.assertIsNotNone(proc, "connect() never started quartus_stp")
        self.addCleanup(proc.kill)
        closer = threading.Thread(target=t.close, daemon=True)
        closer.start()
        closer.join(timeout=5)
        self.assertFalse(closer.is_alive(), "close() waited on the stuck connect()")
        connector.join(timeout=5)
        self.assertFalse(connector.is_alive(), "connect() never unwound")
        self.assertEqual(len(outcome), 1)
        self.assertNotEqual(outcome, ["connected"])
        self.assertIsNotNone(proc.poll(), "the cancelled quartus_stp is still running")
        self.assertIsNone(t._proc)

    def test_quartus_concurrent_closes_both_return_and_reap(self):
        """A second close() arriving while the first is still tearing down
        waits its turn or kills the session; either way both return and the
        process is gone."""
        t = self._fake_quartus("fake_quartus_stp_stubborn.py")
        t.CLOSE_GRACE_SEC = 1.5
        t.CLOSE_TERM_SEC = 0.3
        t.CLOSE_KILL_SEC = 1.0
        t.connect()
        proc = t._proc
        self.addCleanup(proc.kill)
        first = threading.Thread(target=t.close, daemon=True)
        second = threading.Thread(target=t.close, daemon=True)
        first.start()
        time.sleep(0.1)
        second.start()
        first.join(timeout=10)
        second.join(timeout=10)
        self.assertFalse(first.is_alive() or second.is_alive(), "a close() never returned")
        self.assertIsNotNone(proc.poll(), "quartus_stp survived two closes")
        self.assertIsNone(t._proc)

    def test_quartus_close_returns_while_a_child_holds_the_output_pipes(self):
        """If quartus_stp leaves a child holding its stdout/stderr, the drain
        threads never see EOF.  Closing a pipe one of them is still reading
        blocks, so close() must leave that pipe open rather than hang."""
        pid_file = Path(tempfile.mkdtemp()) / "child.pid"
        t = QuartusStpTransport(
            quartus_stp_argv=[
                sys.executable,
                str(ROOT / "tests" / "fixtures" / "fake_quartus_stp_spawner.py"),
                str(pid_file),
            ],
            read_timeout_sec=5.0,
        )
        t.CLOSE_JOIN_SEC = 0.2
        t.connect()
        child = int(pid_file.read_text())
        self.addCleanup(os.kill, child, signal.SIGTERM)
        proc = t._proc
        closer = threading.Thread(target=t.close, daemon=True)
        closer.start()
        closer.join(timeout=10)
        self.assertFalse(closer.is_alive(), "close() blocked on a pipe still being read")
        self.assertIsNotNone(proc.poll())
        self.assertIsNone(t._proc)

    def test_quartus_failed_drain_thread_start_does_not_leak_the_process(self):
        """The session is not published until its threads run, so a failure
        starting them must reap the process itself: no close() can find it."""
        real_start = threading.Thread.start
        real_popen = subprocess.Popen
        starts = []
        spawned = []

        def flaky_start(thread):
            starts.append(thread)
            if len(starts) == 2:
                raise RuntimeError("can't start new thread")
            real_start(thread)

        def recording_popen(*args, **kwargs):
            spawned.append(real_popen(*args, **kwargs))
            return spawned[-1]

        t = self._fake_quartus("fake_quartus_stp_stubborn.py")
        with patch.object(threading.Thread, "start", flaky_start), patch.object(
            subprocess, "Popen", recording_popen
        ):
            with self.assertRaisesRegex(RuntimeError, "can't start new thread"):
                t.connect()
        self.assertEqual(len(spawned), 1)
        self.addCleanup(spawned[0].kill)
        self.assertIsNotNone(spawned[0].poll(), "the unpublished quartus_stp is still running")
        self.assertIsNone(t._proc)

    def test_quartus_interrupted_request_leaves_no_answer_for_the_next(self):
        """A request interrupted after sending (Ctrl+C) may still get its
        answer.  The next request must refuse the session, not read it."""

        class Interrupting:
            def __init__(self):
                self.q = queue.Queue()
                self.interrupted = False

            def put(self, item):
                self.q.put(item)

            def get(self, timeout=None):
                if not self.interrupted:
                    self.interrupted = True
                    raise KeyboardInterrupt
                return self.q.get(timeout=timeout)

        proc = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=1.0)
        out = Interrupting()
        _install_session(t, proc, out=out)
        with self.assertRaises(KeyboardInterrupt):
            t._send("puts A")
        out.put(f"tcl> {0x11111111:049b}\n")  # A's answer, arriving late
        out.put(f"tcl> {QuartusStpTransport._SENTINEL}\n")
        with self.assertRaisesRegex(RuntimeError, "reconnect"):
            t._send("puts B")

    def test_quartus_request_during_reconnect_sees_one_whole_session(self):
        """A request that arrives the instant a reconnect makes its session
        visible must get the new process together with the new output queue,
        never the new process with the old queue."""
        raced = []

        class Racing(QuartusStpTransport):
            armed = False

            def __setattr__(self, name, value):
                super().__setattr__(name, value)
                if self.armed and name == "_session" and value is not None:
                    self.armed = False
                    worker = threading.Thread(target=self._race, daemon=True)
                    worker.start()
                    worker.join(timeout=10)

            def _race(self):
                try:
                    raced.append(self.read_reg(0x20))
                except Exception as exc:
                    raced.append(exc)

        t = Racing(
            quartus_stp_argv=[
                sys.executable,
                str(ROOT / "tests" / "fixtures" / "fake_quartus_stp.py"),
                "-s",
            ],
            read_timeout_sec=5.0,
        )
        t.connect()
        try:
            t.armed = True
            t.connect()  # retires the first session, then publishes a new one
            self.assertEqual(len(raced), 1, "the racing request never ran")
            self.assertNotIsInstance(raced[0], ConnectionError, repr(raced[0]))
            self.assertEqual(t.opened_device, "FAKE_FPGA")
            self.assertEqual(t.read_reg(0x20), 0x12345678)
        finally:
            t.close()

    def test_quartus_send_deadline_holds_while_output_is_queued(self):
        """Queue.get(timeout=0) still returns a queued line, so a deadline
        enforced only through get() never fires while output is backed up."""

        class Endless:
            """An output queue that is never empty and never has the sentinel."""

            def get(self, timeout=None):
                time.sleep(0.001)
                return "tcl> still working\n"

        proc = MagicMock()
        proc.poll.return_value = None
        t = QuartusStpTransport(read_timeout_sec=30.0)
        _install_session(t, proc, out=Endless())
        outcome = []

        def request():
            try:
                t._send("puts hello", timeout=0.2)
                outcome.append("returned")
            except TimeoutError:
                outcome.append("timeout")

        worker = threading.Thread(target=request, daemon=True)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), "queued output kept the request past its deadline")
        self.assertEqual(outcome, ["timeout"])
        proc.kill.assert_called()


# ---------------------------------------------------------------------------
# XilinxHwServerTransport failure modes
# ---------------------------------------------------------------------------

class _FakeXsdbProc:
    """Minimal stand-in for the piped xsdb process.

    ``_send`` only needs a stdin to write to and a stdout to read lines from,
    so a canned list of reply lines is enough to exercise the framing and the
    ``check=True`` error path without launching Vivado.
    """

    def __init__(self, reply_lines):
        self.written = []
        self._replies = list(reply_lines)
        self.stdin = self
        self.stdout = self

    # stdin side
    def write(self, data):
        self.written.append(data)

    def flush(self):
        return None

    # stdout side
    def readline(self):
        if not self._replies:
            return ""
        return self._replies.pop(0) + "\n"


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

    # -- fpga -file target selection (debug-target namespace) ----------------
    #
    # Ground truth for these comes from a real chain with an Arty A7 (xc7a100t),
    # a KV260 (xck26) and a ZCU-class board (xczu7) attached at once, xsdb
    # 2025.2.  `targets` there is:
    #     1  xc7a100t                <- standalone FPGA: named for the part
    #     2  PS TAP  / 3 PMU / 4 PL  <- xck26
    #     5  PSU / 6 RPU / 9 APU ...
    #    14  PS TAP  / 15 PMU / 16 PL <- xczu7
    # There is no node named `xck26` anywhere in it.

    def _fake_mpsoc_send(self, calls, part="xck26"):
        """A _send that accepts only the MPSoC-shaped configuration filter."""

        def fake_send(tcl: str, *, check: bool = False) -> str:
            calls.append(tcl)
            if tcl.startswith("targets -set -filter"):
                ok = f'jtag_device_name =~ "{part}"' in tcl and 'name =~ "PS TAP"' in tcl
                if not ok:
                    raise RuntimeError(f'xsdb rejected {tcl!r}: no targets found')
            return ""

        return fake_send

    def test_config_target_on_mpsoc_selects_ps_tap_not_the_part_name(self):
        """On MPSoC the part name matches no debug target; PS TAP is the one.

        Regression: program() used to filter `targets` by the part name, which
        matches nothing on ZynqMP.  xsdb printed an error, _send swallowed it,
        `fpga -file` then programmed nothing, and the session carried on
        against whatever was already in the FPGA -- wrong data, no error.
        """
        t = XilinxHwServerTransport(fpga_name="xck26")
        calls: list[str] = []
        t._send = self._fake_mpsoc_send(calls)  # type: ignore[method-assign]
        t._select_config_target()
        sel = [c for c in calls if c.startswith("targets -set -filter")]
        self.assertTrue(sel)
        self.assertIn('name =~ "PS TAP"', sel[-1])
        # Scoped to the board: two MPSoC boards each contribute a "PS TAP".
        self.assertIn('jtag_device_name =~ "xck26"', sel[-1])

    def test_config_target_on_standalone_fpga_uses_the_part_name(self):
        """7-series/UltraScale: the device node IS named for the part."""
        t = XilinxHwServerTransport(fpga_name="xc7a100t")
        calls: list[str] = []

        def fake_send(tcl: str, *, check: bool = False) -> str:
            calls.append(tcl)
            if tcl.startswith("targets -set -filter") and 'name =~ "PS TAP"' in tcl:
                raise RuntimeError("xsdb rejected: no targets found")
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        t._select_config_target()
        sel = [c for c in calls if c.startswith("targets -set -filter")]
        # Tried the MPSoC shape first, then fell back to the part name.
        self.assertEqual(len(sel), 2)
        self.assertIn('name =~ "xc7a100t"', sel[-1])

    def test_config_target_absent_raises_instead_of_programming_nothing(self):
        """No match on either shape must fail loudly, never silently."""
        t = XilinxHwServerTransport(fpga_name="xcvu9p")

        def fake_send(tcl: str, *, check: bool = False) -> str:
            if tcl.startswith("targets -set -filter"):
                raise RuntimeError("xsdb rejected: no targets found")
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        with self.assertRaises(ConnectionError) as caught:
            t._select_config_target()
        self.assertIn("nothing", str(caught.exception))
        self.assertIn("xcvu9p", str(caught.exception))

    def test_program_checks_both_the_selection_and_the_load(self):
        """program() must run its two xsdb commands with check=True.

        Both fail by *printing* a message; unchecked, a bad bitstream looks
        exactly like a good one.
        """
        t = XilinxHwServerTransport(fpga_name="xck26")
        seen: list[tuple[str, bool]] = []

        def fake_send(tcl: str, *, check: bool = False) -> str:
            seen.append((tcl, check))
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        t.program("C:/tmp/design.bit")
        checked = {tcl: chk for tcl, chk in seen}
        self.assertTrue(
            all(chk for tcl, chk in seen if tcl.startswith(("targets -set", "fpga -file")))
        )
        self.assertIn("fpga -file {C:/tmp/design.bit}", checked)

    def test_send_check_raises_on_an_xsdb_error_line(self):
        """check=True turns a printed xsdb error into an exception."""
        t = XilinxHwServerTransport()
        t._proc = _FakeXsdbProc(
            [f"{t._ERR_MARKER} no targets found", t._SENTINEL]
        )
        with self.assertRaises(RuntimeError) as caught:
            t._send("targets -set -filter {name =~ \"nope\"}", check=True)
        self.assertIn("no targets found", str(caught.exception))

    def test_send_check_is_quiet_on_success(self):
        """A successful checked command returns empty and raises nothing."""
        t = XilinxHwServerTransport()
        t._proc = _FakeXsdbProc([t._SENTINEL])
        self.assertEqual(t._send("targets -set -filter {x}", check=True), "")

    def test_send_without_check_keeps_swallowing(self):
        """Default behaviour is unchanged: output is returned, not inspected."""
        t = XilinxHwServerTransport()
        t._proc = _FakeXsdbProc(["some output", t._SENTINEL])
        self.assertEqual(t._send("puts [jtag targets]"), "some output")

    def test_select_fpga_target_selects_present_target(self):
        """_select_fpga_target() sets the filter when the target is present."""
        t = XilinxHwServerTransport(fpga_name="xc7a100t")
        calls: list[str] = []

        def fake_send(tcl: str, check: bool = False) -> str:
            calls.append(tcl)
            return "  1  xc7a100t\n  2  xck26\n" if tcl == "puts [jtag targets]" else ""

        t._send = fake_send  # type: ignore[method-assign]
        t._select_fpga_target()
        self.assertTrue(
            any("jtag targets -set -filter" in c and "xc7a100t" in c for c in calls)
        )
        # The selected node is confirmed with a scan before it is used.
        self.assertEqual(calls[-1], t._NODE_CHECK_TCL)

    def test_select_fpga_target_waits_out_empty_chain(self):
        """A transiently empty chain is polled until the target appears."""
        t = XilinxHwServerTransport(fpga_name="xc7a100t", target_wait_timeout=2.0)
        listings = iter(["", "", "  1  xc7a100t\n"])  # empty, empty, then present
        polls = {"n": 0}

        def fake_send(tcl: str, check: bool = False) -> str:
            if tcl == "puts [jtag targets]":
                polls["n"] += 1
                return next(listings, "  1  xc7a100t\n")
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        with patch("fcapz.transport.time.sleep"):
            t._select_fpga_target()
        self.assertGreaterEqual(polls["n"], 3)  # rode out the empty window

    def test_default_target_wait_outlasts_a_cable_rescan(self):
        """The default deadline outlasts the 6.2 s worst cable rescan seen."""
        self.assertGreaterEqual(XilinxHwServerTransport().target_wait_timeout, 8.0)

    def test_select_fpga_target_retries_node_not_accessible(self):
        """A target listed from a stale cable is retried until its scans work."""
        t = XilinxHwServerTransport(fpga_name="xczu7", target_wait_timeout=5.0)
        checks = {"n": 0}

        def fake_send(tcl: str, check: bool = False) -> str:
            if tcl == "puts [jtag targets]":
                return "  1  xczu7\n"
            if tcl == t._NODE_CHECK_TCL:
                checks["n"] += 1
                if checks["n"] <= 2:
                    raise RuntimeError("xsdb rejected: JTAG node is not accessible")
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        with patch("fcapz.transport.time.sleep"):
            t._select_fpga_target()
        self.assertEqual(checks["n"], 3)

    def test_select_fpga_target_retries_a_target_that_vanished(self):
        """A select that finds the target gone again is part of the rescan."""
        t = XilinxHwServerTransport(fpga_name="xczu7", target_wait_timeout=5.0)
        selects = {"n": 0}

        def fake_send(tcl: str, check: bool = False) -> str:
            if tcl == "puts [jtag targets]":
                return "  1  xczu7\n"
            if tcl.startswith("jtag targets -set"):
                selects["n"] += 1
                if selects["n"] == 1:
                    raise RuntimeError("xsdb rejected: no targets found")
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        with patch("fcapz.transport.time.sleep"):
            t._select_fpga_target()
        self.assertEqual(selects["n"], 2)

    def test_select_fpga_target_raises_other_scan_errors_at_once(self):
        """Only the rescan's signature is retried; other scan errors surface."""
        t = XilinxHwServerTransport(fpga_name="xczu7", target_wait_timeout=5.0)
        checks = {"n": 0}

        def fake_send(tcl: str, check: bool = False) -> str:
            if tcl == "puts [jtag targets]":
                return "  1  xczu7\n"
            if tcl == t._NODE_CHECK_TCL:
                checks["n"] += 1
                raise RuntimeError("xsdb rejected: invalid register name")
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        with patch("fcapz.transport.time.sleep"):
            with self.assertRaises(RuntimeError):
                t._select_fpga_target()
        self.assertEqual(checks["n"], 1)

    def test_select_fpga_target_reports_a_node_that_never_answers(self):
        """The deadline error names the last scan error."""
        t = XilinxHwServerTransport(fpga_name="xczu7", target_wait_timeout=0.05)

        def fake_send(tcl: str, check: bool = False) -> str:
            if tcl == "puts [jtag targets]":
                return "  1  xczu7\n"
            if tcl == t._NODE_CHECK_TCL:
                raise RuntimeError("xsdb rejected: JTAG node is not accessible")
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        with self.assertRaises(ConnectionError) as cm:
            t._select_fpga_target()
        self.assertIn("not accessible", str(cm.exception))

    def test_select_fpga_target_times_out_with_clear_error(self):
        """A never-appearing target fails with a message naming what is visible."""
        t = XilinxHwServerTransport(fpga_name="xc7a100t", target_wait_timeout=0.05)

        def fake_send(tcl: str, check: bool = False) -> str:
            return "  1  xck26\n" if tcl == "puts [jtag targets]" else ""  # never the Arty

        t._send = fake_send  # type: ignore[method-assign]
        with patch("fcapz.transport.time.sleep"):
            with self.assertRaises(ConnectionError) as cm:
                t._select_fpga_target()
        self.assertIn("xc7a100t", str(cm.exception))
        self.assertIn("xck26", str(cm.exception))

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

        def fake_send(tcl: str, check: bool = False) -> str:
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

        def fake_send(tcl: str, check: bool = False) -> str:
            sent.append(tcl)
            return f"{stale} {fresh}"

        t._send = fake_send  # type: ignore[method-assign]

        vals = t._read_block_burst(8)

        self.assertEqual(vals, list(range(8)))
        self.assertIn("-hex 6 03", sent[0])
        self.assertNotIn("-hex 6 02", sent[0])
        self.assertIn("-bits 256", sent[0])

    def test_two_chain_burst_can_be_selected_for_legacy_builds(self):
        """Legacy two-chain burst keeps 256-bit scans on USER2."""
        t = XilinxHwServerTransport(single_chain_burst=False)
        t._cached_sps = 32
        sent: list[str] = []
        stale = self._burst_token([0xEE] * 32)
        fresh = self._burst_token(list(range(32)))

        def fake_send(tcl: str, check: bool = False) -> str:
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

    def _fake_xsdb_sequence(self, tokens: list[str], sent: list[str]):
        """xsdb stand-in: a ``jtag sequence`` collects scans across sends and
        prints one token per captured scan only when it is run."""
        state = {"captures": 0}

        def fake_send(tcl: str, check: bool = False) -> str:
            sent.append(tcl)
            if "[jtag sequence]" in tcl:
                state["captures"] = 0
            state["captures"] += tcl.count("-capture")
            if "run -bits" not in tcl:
                return ""
            n = state["captures"]
            state["captures"] = 0
            return " ".join(tokens[:n])

        return fake_send

    def test_read_sample_block_builds_deep_burst_over_several_sends(self):
        """A deep wide-sample burst is added to the sequence over several xsdb
        sends (the BURST_PTR write in the first) and run once, and the words
        come back little-endian per sample."""
        t = XilinxHwServerTransport()
        n = 600  # + 1 prime scan = 601 scans -> 256 + 256 + 89
        tokens = [self._burst_token([0xDEAD], 256)] + [
            self._burst_token([(s << 224) | (0xA5 << 32) | s], 256) for s in range(n)
        ]
        sent: list[str] = []
        t._send = self._fake_xsdb_sequence(tokens, sent)  # type: ignore[method-assign]
        words = t.read_sample_block(0x0100, n, 256)

        self.assertEqual(len(sent), 3)  # one pass, no repeat
        self.assertIn("-bits 49", sent[0])  # BURST_PTR write in the first send
        self.assertNotIn("-bits 49", sent[1])
        self.assertEqual(len(words), n * 8)
        self.assertEqual(words[8 * 5:8 * 6], [5, 0xA5, 0, 0, 0, 0, 0, 5 << 0])
        self.assertEqual(words[8 * 599 + 7], 599)

    def test_burst_is_one_jtag_sequence_from_write_to_last_scan(self):
        """No other scan may reach the chain between the BURST_PTR write and
        the last burst scan: on the MPSoC hw_server can scan the PL between
        two sequence runs, and the pipe then decodes that scan as a register
        command and leaves burst mode.  So each pass creates one sequence and
        runs it once, in its last send, after every scan was added.  The
        burst is read in that single pass, not repeated."""
        for register_ir in (False, True):
            with self.subTest(use_register_ir=register_ir):
                t = XilinxHwServerTransport(use_register_ir=register_ir)
                n = 600
                tokens = [self._burst_token([s], 256) for s in range(n + 1)]
                sent: list[str] = []
                t._send = self._fake_xsdb_sequence(tokens, sent)  # type: ignore[method-assign]
                t.read_sample_block(0x0100, n, 256)

                self.assertEqual(len(sent), 3)
                body = "; ".join(sent)
                self.assertEqual(body.count("[jtag sequence]"), 1)
                self.assertEqual(body.count(" run"), 1)
                self.assertNotIn(" delete", "; ".join(sent[:-1]))
                self.assertIn("run -bits", sent[-1])
                self.assertLess(body.index("-bits 49"), body.index("-capture"))
                self.assertEqual(body.count("-capture"), n + 1)

    def test_read_sample_block_rejects_short_stream(self):
        t = XilinxHwServerTransport()
        t._read_block_burst = MagicMock(return_value=[1, 2])  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            t.read_sample_block(0x0100, 3, 256)

    def test_narrow_burst_one_scan_short_is_raised(self):
        """A narrow-core burst that comes back a scan short is a readout
        defect: it is raised, not hidden behind a DATA-window re-read."""
        t = XilinxHwServerTransport()
        t._cached_sps = 32
        t._burst_sample_ok = MagicMock(return_value=True)  # type: ignore[method-assign]
        stale = self._burst_token([0xEE] * 32)
        fresh = self._burst_token(list(range(32)))
        # 33 samples need 2 scans + 1 prime; only 2 tokens come back.
        t._send = MagicMock(return_value=f"{stale} {fresh}")  # type: ignore[method-assign]
        t._read_block_user1 = MagicMock(return_value=list(range(33)))  # type: ignore[method-assign]
        with self.assertRaises(BurstIntegrityError):
            t.read_block(0x0100, 33)
        t._read_block_user1.assert_not_called()
        self.assertTrue(t._has_burst)  # the capability is not in question

    def test_short_timestamp_burst_is_raised(self):
        t = XilinxHwServerTransport()
        stale = self._burst_token([0xEE] * 8, sample_w=32)
        t._send = MagicMock(return_value=stale)  # type: ignore[method-assign]
        t._read_block_user1 = MagicMock(return_value=[0] * 8)  # type: ignore[method-assign]
        with self.assertRaises(BurstIntegrityError):
            t.read_timestamp_block(0x2100, 8, 32)  # 1 scan + 1 prime expected
        t._read_block_user1.assert_not_called()

    def test_burst_with_extra_scans_is_refused(self):
        """More scans than were queued means the output is not this burst."""
        t = XilinxHwServerTransport()
        t._cached_sps = 32
        tok = self._burst_token(list(range(32)))
        t._send = MagicMock(return_value=" ".join([tok] * 3))  # type: ignore[method-assign]
        with self.assertRaises(BurstIntegrityError):
            t._read_block_burst(8)  # 1 scan + 1 prime expected

    def test_deep_burst_checks_every_send(self):
        """An error while an early send builds the sequence is raised, not
        hidden behind the last send's partial run."""
        t = XilinxHwServerTransport()
        n = 600
        tokens = [self._burst_token([s], 256) for s in range(n + 1)]
        sent: list[str] = []
        inner = self._fake_xsdb_sequence(tokens, sent)
        checks: list[bool] = []

        def fake_send(tcl: str, check: bool = False) -> str:
            checks.append(check)
            if len(sent) == 1:  # the second send fails; xsdb only prints it
                sent.append(tcl)
                if check:
                    raise RuntimeError("xsdb rejected: JTAG node is not accessible")
                return ""  # its scans never joined the sequence
            return inner(tcl)

        t._send = fake_send  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            t._read_block_burst(n, element_width=256)
        self.assertEqual(checks, [True, True])

    def test_window_read_past_address_space_is_refused(self):
        """The pipelined DATA-window path must not wrap a read past 0x10000."""
        t = XilinxHwServerTransport()
        t._send = MagicMock(return_value="")  # type: ignore[method-assign]
        with self.assertRaises(DataWindowError):
            t._read_block_user1(0x0100, 16384)
        t._send.assert_not_called()

    def test_wide_sample_core_skips_burst_readback(self):
        """SAMPLE_W>32 (e.g. the 160-bit AXI monitor) must NOT use the
        sample-packing burst DR: it treats capture()'s 32-bit *word* count as a
        *sample* count, building a 5x-oversized single-line TCL that xsdb never
        finishes — hanging the read. Wide cores take the 32-bit word path."""
        t = XilinxHwServerTransport()
        t.read_reg_stable = MagicMock(return_value=160)  # ADDR_SAMPLE_W (0x000C)
        t._read_block_burst = MagicMock(return_value=[])  # must not be reached
        t._read_block_user1 = MagicMock(return_value=[1, 2, 3, 4, 5])

        self.assertEqual(t.read_block(0x0100, 5), [1, 2, 3, 4, 5])
        t._read_block_burst.assert_not_called()
        t._read_block_user1.assert_called_once_with(0x0100, 5)

    def test_narrow_sample_core_still_uses_burst_readback(self):
        """SAMPLE_W<=32 keeps the fast burst path (one 32-bit word per sample)."""
        t = XilinxHwServerTransport()
        t.read_reg_stable = MagicMock(return_value=8)
        t._read_block_burst = MagicMock(return_value=[9, 9])
        t._read_block_user1 = MagicMock(return_value=[0])

        self.assertEqual(t.read_block(0x0100, 2), [9, 9])
        t._read_block_burst.assert_called_once_with(2)
        t._read_block_user1.assert_not_called()

    def test_burst_read_tcl_targets_active_chain(self):
        """The pipelined DATA reader must shift IR on the ACTIVE chain, not a
        hardcoded USER1 -- otherwise a wide core on USER2 (the AXI monitor) reads
        USER1's data window instead of its own."""
        t = XilinxHwServerTransport()
        t._active_chain = 1
        tcl_c1 = t._burst_read_tcl(0x0100, 0, 4)
        t._active_chain = 2
        tcl_c2 = t._burst_read_tcl(0x0100, 0, 4)
        self.assertNotEqual(tcl_c1, tcl_c2)  # IR shift follows the active chain

    def test_read_block_user1_uses_pipelined_path_for_data(self):
        """DATA-window reads go through one pipelined sequence per chunk (not a
        per-word round trip), so a wide readback is a handful of _send calls."""
        t = XilinxHwServerTransport()
        sent: list[str] = []

        def fake_send(tcl: str, check: bool = False) -> str:
            sent.append(tcl)
            return ""

        t._send = fake_send  # type: ignore[method-assign]
        t._parse_block_bits = MagicMock(return_value=[0] * 8)  # isolate call shape
        t.read_reg = MagicMock(return_value=0)  # the trailing pipeline flush
        t._read_block_user1(0x0100, 8)
        # 8 words fit one _BLOCK_CHUNK -> a single pipelined _send, not 8+.
        self.assertEqual(len(sent), 1)

    def test_burst_sample_gate_defaults_open_when_width_unreadable(self):
        """If SAMPLE_W can't be read, keep the prior fast-path behavior."""
        t = XilinxHwServerTransport()

        def boom():
            raise RuntimeError("not connected")

        t.read_reg_stable = MagicMock(side_effect=lambda addr: boom())
        self.assertTrue(t._burst_sample_ok())

    def test_single_chain_burst_fallback_logs_migration_hint(self):
        """Default single-chain failure should point legacy users at two-chain mode."""
        t = XilinxHwServerTransport()

        def fail_burst(*args, **kwargs):
            raise RuntimeError("single-chain burst readback failed")

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

        def fake_send(tcl: str, check: bool = False) -> str:
            sent.append(tcl)
            return f"{stale} {first}"

        t._send = fake_send  # type: ignore[method-assign]

        vals = t._read_block_burst(8, timestamp=True, element_width=32)

        self.assertEqual(vals, list(range(8)))
        self.assertEqual(sent[0].count("drshift -state DRUPDATE -capture"), 2)

    def test_user1_block_read_has_idle_before_each_capture(self):
        """USER1 pipelined reads clock idle TCKs before every captured word."""
        t = XilinxHwServerTransport()

        tcl = t._burst_read_tcl(0x0100, 0, 4)

        self.assertEqual(
            tcl.count(f"state IDLE {t.READ_IDLE_CYCLES}"),
            1 + t.USER1_PIPE_PRIME_READS + 3,
        )
        # `delay` only waits; it clocks no TCK, so the TCK-domain core would
        # get no time from it.
        self.assertNotIn(" delay ", tcl)
        # Every address-bearing scan fires an explicit UPDATE-DR (the
        # -state IDLE shortcut is unreliable through MPSoC -register IR);
        # the final flush scan has no trailing idle.
        self.assertNotIn("-state IDLE -", tcl)
        self.assertEqual(
            tcl.count("drshift -state DRUPDATE -capture"),
            t.USER1_PIPE_PRIME_READS + 3 + 1,
        )
        self.assertEqual(tcl.count("drshift -state DRUPDATE -bits"), 1)

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
        """Writes in register mode use -state DRUPDATE then idle TCKs."""
        t = XilinxHwServerTransport(use_register_ir=True)
        t._active_chain = 1
        tcl = t._write_reg_tcl(t._frame_bits(0x14, 0xCAFE, True))
        self.assertIn("-register user1", tcl)
        self.assertIn("-state DRUPDATE", tcl)
        self.assertIn(f"state IDLE {t.WRITE_IDLE_CYCLES_REGISTER}", tcl)
        self.assertNotIn(" delay ", tcl)

    def test_register_read_clocks_idle_after_explicit_update(self):
        """A register read commits its command with UPDATE-DR and gives the
        core real TCKs (``state IDLE n``), not a clockless ``delay``."""
        for register_ir in (False, True):
            t = XilinxHwServerTransport(use_register_ir=register_ir)
            t._active_chain = 1
            tcl = t._read_reg_tcl(t._frame_bits(addr=0x10, data=0, write=False))
            cmd, capture = tcl.split(f"state IDLE {t.READ_IDLE_CYCLES}")
            self.assertIn("drshift -state DRUPDATE -bits", cmd)
            self.assertIn("-capture", capture)
            self.assertNotIn(" delay ", tcl)

    def test_every_command_scan_fires_explicit_update(self):
        """Raw scans, the burst BURST_PTR write and pipelined register reads
        end each command scan in DRUPDATE and then clock idle TCKs; the
        -state IDLE shortcut is unreliable through MPSoC -register IR."""
        for register_ir in (False, True):
            t = XilinxHwServerTransport(use_register_ir=register_ir)
            t._active_chain = 1
            scripts: list[str] = []

            def send(tcl, scripts=scripts, t=t, check=False):
                scripts.append(tcl)
                return " ".join(["0" * t._user_dr_bits(t.BURST_DR_BITS)] * 4)

            t._send = send  # type: ignore[method-assign]
            t.raw_dr_scan(0, 49)
            t.raw_dr_scan_batch([(0, 49), (1, 49)])
            t._parse_burst_bits = MagicMock(return_value=[0])  # type: ignore[method-assign]
            t._read_block_burst(1, element_width=32)
            t._parse_block_bits = MagicMock(return_value=[0, 0])  # type: ignore[method-assign]
            t.read_reg = MagicMock(return_value=0)  # type: ignore[method-assign]
            t.read_regs_pipelined_user1([0x0, 0x4])
            for tcl in scripts:
                self.assertNotIn("-state IDLE -", tcl)
                self.assertNotIn(" delay ", tcl)
            raw, batch, burst, piped = scripts
            self.assertIn(f"state IDLE {t.RAW_DR_IDLE_CYCLES}", raw)
            self.assertEqual(batch.count(f"state IDLE {t.RAW_DR_IDLE_CYCLES}"), 2)
            head, scans = burst.split("state IDLE", 1)
            self.assertIn("drshift -state DRUPDATE -bits", head)
            self.assertIn("-capture", scans)
            self.assertEqual(piped.count(f"state IDLE {t.READ_IDLE_CYCLES}"), 2)

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


class TestOpenOcdTapValidation(unittest.TestCase):
    """The OpenOCD tap is interpolated into TCL, so unsafe names are rejected."""

    def test_rejects_injection_chars(self):
        for bad in ("foo; exec calc", "foo\nshutdown", "a b", "x$y", "a[b]"):
            with self.assertRaises(ValueError):
                OpenOcdTransport(tap=bad)

    def test_accepts_real_taps_and_sentinels(self):
        for good in ("GW1NR-9C.tap", "xc7a100t.tap", "auto", ""):
            OpenOcdTransport(tap=good)  # must not raise


if __name__ == "__main__":
    unittest.main()
