# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import sys
import time
import subprocess
import threading
from abc import ABC, abstractmethod

from typing import List

# Character whitelist for the JTAG target filter (XSDB `jtag targets -set
# -filter {name =~ "..."}`).  This value is interpolated inside a
# double-quoted TCL string, so we reject every character that could end the
# string or trigger substitution: " [ ] { } $ ; \ <newline> <tab>.
_TCL_NAME_RE = re.compile(r'^[A-Za-z0-9._:/*\- ]+$')

# Character whitelist for bitfile paths (XSDB `fpga -file {...}`).  The path
# is wrapped in TCL braces which disable substitution, so the only unsafe
# characters are unbalanced braces and characters that could terminate the
# brace group.  We accept typical Windows/Unix path characters including
# backslash.  Anything outside this set is rejected outright.
_TCL_PATH_RE = re.compile(r'^[A-Za-z0-9._:/*\-\\ ]+$')

_hw_log = logging.getLogger("fcapz.transport.hw_server")


def connect_timing_logs_enabled() -> bool:
    """If true, log connect phase durations (hw_server + GUI worker).

    Set environment variable ``FCAPZ_LOG_CONNECT_TIMING`` to ``1``, ``true``,
    or ``yes``.
    """
    return os.environ.get("FCAPZ_LOG_CONNECT_TIMING", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


class Transport(ABC):
    """Abstract base class for all fpgacapZero JTAG transports.

    Implementations must override the five abstract methods below.
    Two optional extension points (``select_chain`` and ``raw_dr_scan``)
    can be overridden to support multi-chain and raw DR access respectively.

    Exception contract
    ------------------
    All methods should raise:

    * ``RuntimeError``  — if called before :meth:`connect` or after
      :meth:`close`, or if the underlying transport encounters an I/O
      error (e.g. XSDB process exits, socket closed by peer).
    * ``ConnectionError`` — when the remote endpoint closes the connection
      unexpectedly mid-transaction (subclass of ``OSError``).
    * ``ValueError`` — for invalid arguments (e.g. unsupported chain index).
    * ``OSError`` / ``TimeoutError`` — for network or process-level errors
      during :meth:`connect`.
    """

    @abstractmethod
    def connect(self) -> None:
        """Open the transport connection.

        Raises ``RuntimeError`` if the backend cannot be reached (e.g. xsdb
        not on PATH, OpenOCD port not listening).  Raises ``OSError`` or
        ``TimeoutError`` for socket-level failures.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close the transport.  Must be idempotent — safe to call multiple times."""
        raise NotImplementedError

    @abstractmethod
    def read_reg(self, addr: int) -> int:
        """Read a 32-bit register at *addr*.

        Raises ``RuntimeError`` if not connected or if the underlying I/O
        fails.  Returns the raw 32-bit value (unsigned).
        """
        raise NotImplementedError

    @abstractmethod
    def write_reg(self, addr: int, value: int) -> None:
        """Write *value* (32-bit) to the register at *addr*.

        Raises ``RuntimeError`` if not connected or if the underlying I/O
        fails.
        """
        raise NotImplementedError

    @abstractmethod
    def read_block(self, addr: int, words: int) -> List[int]:
        """Read *words* consecutive 32-bit registers starting at *addr*.

        Returns a list of *words* unsigned 32-bit integers.  Raises
        ``RuntimeError`` if not connected or on I/O failure.
        """
        raise NotImplementedError

    def select_chain(self, chain: int) -> None:
        """Select the BSCANE2 USER chain for subsequent register accesses.

        Subclasses that support multi-chain access must override this.
        Raises ``ValueError`` if *chain* is not in the transport's IR table.
        Raises ``NotImplementedError`` on transports that only support a
        single fixed chain.
        """
        raise NotImplementedError

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        """Perform a raw DR scan of *width* bits, shifting in *bits*.

        Returns the captured TDO value as an unsigned integer.  If *chain*
        is given it overrides the active chain for this scan only.

        Subclasses that expose raw JTAG DR access must override this.
        Raises ``NotImplementedError`` on transports that do not support it.
        Raises ``RuntimeError`` if not connected or on I/O failure.
        """
        raise NotImplementedError

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        """Perform multiple raw DR scans and return all captured TDO values.

        *scans* is a list of ``(bits, width)`` tuples.  Returns a list of
        captured values in the same order.

        Default implementation calls :meth:`raw_dr_scan` in a loop.
        Override for transports that support batched transfers (e.g. a
        single ``jtag sequence`` round-trip in XSDB).
        """
        return [self.raw_dr_scan(bits, width, chain=chain) for bits, width in scans]


class OpenOcdTransport(Transport):
    """
    Drives the fpgacapZero BSCANE2 USER register interface via the OpenOCD
    TCL socket (default port 6666).

    Socket reads and writes are serialized with a lock so concurrent use
    (e.g. multiple GUI workers) cannot corrupt the byte stream.

    Protocol recap (49-bit DR, LSB-first):
        bits[31:0]  = wdata / rdata
        bits[47:32] = addr[15:0]
        bits[48]    = rnw (1=write, 0=read)

    A read requires two DR scans: one to issue the read command and one (after
    idle TCK cycles for CDC) to clock out the returned data.
    """

    # Default BSCANE2 IR codes for Xilinx 7-series.
    # USER1 (0x02) and USER2 (0x03) are verified.
    # Verified on xc7a100t (Arty A7): USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.
    DEFAULT_IR_TABLE: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

    # Named IR-table presets for the Xilinx families this transport
    # supports out of the box.  Pass via the ``ir_table`` constructor
    # argument or assign one of these to ``ir_table`` after construction.
    # The 7-series preset is the default and matches DEFAULT_IR_TABLE
    # above; the UltraScale preset is documented in UG570 / UG574 and
    # used by the rtl/jtag_tap_xilinxus.v wrapper instantiations.
    IR_TABLE_XILINX7: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}
    IR_TABLE_XILINX_ULTRASCALE: dict[int, int] = {
        1: 0x24, 2: 0x25, 3: 0x26, 4: 0x27,
    }
    # Zynq UltraScale+ MPSoC PL TAP opcodes.  OpenOCD's TCL listener
    # delegates chain walking (IR padding for the ARM DAP + DR BYPASS
    # bits) to the openocd config file rather than to host code, so this
    # preset is only useful when your openocd.cfg already declares the
    # xck26 / xczu* chain correctly.  Values parallel
    # ``XilinxHwServerTransport.IR_TABLE_XILINX_ZYNQUS`` for symmetry.
    # **Not yet hardware-validated via OpenOCD** — ship with caution.
    IR_TABLE_XILINX_ZYNQUS: dict[int, int] = {
        1: 0x024, 2: 0x025, 3: 0x026, 4: 0x027,
    }
    # Alias so callers can write IR_TABLE_US for brevity.
    IR_TABLE_US = IR_TABLE_XILINX_ULTRASCALE

    USER1_IR = 0x02
    READ_IDLE_CYCLES = 20

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6666,
        tap: str = "xc7a100t.tap",
        ir_table: dict[int, int] | None = None,
        *,
        connect_timeout_sec: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.tap = tap
        self.ir_table = dict(ir_table) if ir_table else dict(self.DEFAULT_IR_TABLE)
        self._connect_timeout_sec = float(connect_timeout_sec)
        self._active_chain: int = 1
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()

    def connect(self) -> None:
        self._sock = socket.create_connection(
            (self.host, self.port),
            timeout=self._connect_timeout_sec,
        )
        self._sock.settimeout(0.2)
        try:
            self._sock.recv(4096)
        except OSError:
            pass
        self._sock.settimeout(5)

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _cmd(self, tcl: str) -> str:
        if not self._sock:
            raise RuntimeError("not connected — call connect() first")
        with self._sock_lock:
            self._sock.sendall((tcl + "\x1a").encode())
            buf = b""
            while not buf.endswith(b"\x1a"):
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise ConnectionError("OpenOCD closed the connection")
                buf += chunk
            return buf[:-1].decode().strip()

    def select_chain(self, chain: int) -> None:
        """Select BSCANE2 USER chain for subsequent register accesses."""
        if chain not in self.ir_table:
            raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
        self._active_chain = chain

    def _select_ir(self, chain: int | None = None) -> None:
        ir = self.ir_table[chain if chain is not None else self._active_chain]
        self._cmd(f"irscan {self.tap} {ir}")

    def _dr_scan(self, value: int) -> int:
        hex_in = f"0x{value:013x}"
        result = self._cmd(f"drscan {self.tap} 49 {hex_in}")
        return int(result.split()[0], 16)

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        """Perform a raw DR scan via irscan + drscan on the OpenOCD socket."""
        self._select_ir(chain)
        hex_width = (width + 3) // 4
        hex_in = f"0x{bits:0{hex_width}x}"
        result = self._cmd(f"drscan {self.tap} {width} {hex_in}")
        return int(result.split()[0], 16)

    def write_reg(self, addr: int, value: int) -> None:
        frame = (1 << 48) | ((addr & 0xFFFF) << 32) | (value & 0xFFFFFFFF)
        self._select_ir()
        self._dr_scan(frame)

    def read_reg(self, addr: int) -> int:
        read_frame = ((addr & 0xFFFF) << 32)
        self._select_ir()
        self._dr_scan(read_frame)
        self._cmd(f"runtest {self.READ_IDLE_CYCLES}")
        self._select_ir()
        shifted_out = self._dr_scan(read_frame)
        return shifted_out & 0xFFFFFFFF

    def read_block(self, addr: int, words: int) -> List[int]:
        return [self.read_reg(addr + i * 4) for i in range(words)]


class XilinxHwServerTransport(Transport):
    """
    Xilinx hw_server transport using a persistent XSDB session.

    Keeps an ``xsdb`` process alive and sends TCL commands over stdin.
    This avoids the overhead of spawning a new process per register access
    and enables efficient batched ``read_block`` operations.
    A mutex serializes :meth:`_send` so concurrent threads (e.g. GUI EIO
    polling and ELA capture) cannot interleave on the single process.

    Uses the ``-bits`` format for ``drshift`` which provides standard JTAG
    bit ordering (``-hex`` has a non-standard byte/nibble mapping in XSDB).

    49-bit DR frame (bit string, position k = sr[k]):
        bits[31:0]  = wdata / rdata
        bits[47:32] = addr[15:0]
        bits[48]    = rnw  (1 = write, 0 = read)
    """

    # Default BSCANE2 IR codes for Xilinx 7-series.
    # USER1 (0x02) and USER2 (0x03) are verified.
    # Verified on xc7a100t (Arty A7): USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.
    DEFAULT_IR_TABLE: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

    # Named IR-table presets for the Xilinx families this transport
    # supports out of the box.  Pass via the ``ir_table`` constructor
    # argument or assign one of these to ``ir_table`` after construction.
    # The 7-series preset is the default and matches DEFAULT_IR_TABLE
    # above; the UltraScale preset is documented in UG570 / UG574 and
    # used by the rtl/jtag_tap_xilinxus.v wrapper instantiations.
    IR_TABLE_XILINX7: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}
    IR_TABLE_XILINX_ULTRASCALE: dict[int, int] = {
        1: 0x24, 2: 0x25, 3: 0x26, 4: 0x27,
    }
    # Zynq UltraScale+ MPSoC PL TAP (xck26 / xczu*).  xsdb at the PL-TAP
    # target level auto-handles the ARM DAP's **IR** (pads with BYPASS)
    # but does NOT pad the **DR** — the ARM DAP's 1-bit BYPASS register
    # still sits in series with the PL's DR.  Chain order on MPSoC is
    # ``TDI → ARM DAP → PL TAP → TDO``, so the DAP BYPASS bit lands on
    # the TDI-side end of the 50-bit DR scan.  The host must therefore
    # pair this table with three constructor args:
    #   ``ir_length=12``  — PL TAP IR width (no DAP bits; xsdb adds those).
    #   ``dr_extra_bits=1`` — one DAP BYPASS bit on every DR scan.
    #   ``dr_extra_position="tdi"`` — BYPASS sits at the TDI end; the
    #       captured token has the fcapz 49-bit response at offset 0 and
    #       the BYPASS bit trailing, so the parser skips nothing up front.
    # The PL BSCANE2 USER1..USER4 instructions share the 7-series opcode
    # pattern but in the 12-bit IR land at 0x024, 0x025, 0x026, 0x027.
    # Verified on xck26 / KV260 by TDO trace.
    IR_TABLE_XILINX_ZYNQUS: dict[int, int] = {
        1: 0x024, 2: 0x025, 3: 0x026, 4: 0x027,
    }
    # Alias so callers can write IR_TABLE_US for brevity.
    IR_TABLE_US = IR_TABLE_XILINX_ULTRASCALE

    USER1_IR = 0x02
    USER2_IR = 0x03
    DR_BITS = 49
    BURST_DR_BITS = 256
    ADDR_BURST_PTR = 0x002C
    READ_IDLE_CYCLES = 20
    RAW_DR_IDLE_CYCLES = 8
    _SENTINEL = "<<XSDB_DONE>>"

    # Default chain shape: single-device 6-bit IR (Xilinx 7-series, standalone
    # UltraScale / UltraScale+).  Override per-instance for chains with extra
    # TAPs in series — e.g. Zynq UltraScale+ MPSoC, where the PL TAP shares
    # the boundary scan chain with the ARM DAP and every IR/DR scan must
    # account for the DAP's IR length and BYPASS bit.  The values stored
    # in ``ir_table`` are shifted **as-is** for ``ir_length`` bits, so the
    # caller is responsible for OR-ing in any other-TAP BYPASS opcodes
    # (typically all-ones in the appropriate bit positions).
    DEFAULT_IR_LENGTH = 6
    DEFAULT_DR_EXTRA_BITS = 0
    DEFAULT_DR_EXTRA_POSITION = "tdo"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3121,
        fpga_name: str = "xc7a100t",
        xsdb_path: str | None = None,
        bitfile: str | None = None,
        ir_table: dict[int, int] | None = None,
        ready_probe_addr: int | None = 0x0000,
        ready_probe_timeout: float = 2.0,
        *,
        post_program_delay_ms: int = 200,
        ready_poll_interval_sec: float = 0.02,
        ir_length: int = DEFAULT_IR_LENGTH,
        dr_extra_bits: int = DEFAULT_DR_EXTRA_BITS,
        dr_extra_position: str = DEFAULT_DR_EXTRA_POSITION,
        use_register_ir: bool = False,
        single_chain_burst: bool = True,
    ):
        if not _TCL_NAME_RE.match(fpga_name):
            raise ValueError(
                f"fpga_name contains unsafe characters for TCL: {fpga_name!r}"
            )
        if bitfile and not _TCL_PATH_RE.match(bitfile):
            raise ValueError(
                f"bitfile path contains unsafe characters for TCL: {bitfile!r}"
            )
        self.host = host
        self.port = port
        self.fpga_name = fpga_name
        self.bitfile = bitfile
        self._xsdb_path = xsdb_path
        self.ir_table = dict(ir_table) if ir_table else dict(self.DEFAULT_IR_TABLE)
        self.ready_probe_addr = ready_probe_addr
        self.ready_probe_timeout = ready_probe_timeout
        self.post_program_delay_ms = int(max(0, min(30_000, post_program_delay_ms)))
        self.ready_poll_interval_sec = float(
            max(0.005, min(0.5, ready_poll_interval_sec))
        )
        self._active_chain: int = 1
        self._proc: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._xsdb_io_lock = threading.Lock()
        # Chain-shape parameters.  All TCL emission and bit-string parsing
        # use these — never the literal 6 / 49 / 256 — so a Zynq US+ MPSoC
        # session (ir_length=16, dr_extra_bits=1) and a 7-series session
        # (ir_length=6, dr_extra_bits=0) share one code path.
        if ir_length < 1 or ir_length > 64:
            raise ValueError(f"ir_length must be 1..64, got {ir_length}")
        if dr_extra_bits < 0 or dr_extra_bits > 32:
            raise ValueError(f"dr_extra_bits must be 0..32, got {dr_extra_bits}")
        if dr_extra_position not in ("tdo", "tdi"):
            raise ValueError(
                f"dr_extra_position must be 'tdo' or 'tdi', got {dr_extra_position!r}"
            )
        self.use_register_ir = bool(use_register_ir)
        self.single_chain_burst = bool(single_chain_burst)
        if self.use_register_ir:
            # In -register mode xsdb handles both IR routing and DR BYPASS
            # padding for multi-TAP chains (e.g. Zynq US+ MPSoC ARM DAP).
            # Override chain-shape params to avoid double-padding.
            ir_length = 6
            dr_extra_bits = 0
        self.ir_length = int(ir_length)
        self.dr_extra_bits = int(dr_extra_bits)
        self.dr_extra_position = dr_extra_position
        self._ir_hex_digits = (self.ir_length + 3) // 4

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        timing = connect_timing_logs_enabled()
        marks: list[tuple[str, float]] = [("start", time.monotonic())]

        def mark(label: str) -> None:
            marks.append((label, time.monotonic()))

        xsdb = self._xsdb_path or shutil.which("xsdb") or shutil.which("xsdb.bat")
        if not xsdb:
            raise RuntimeError(
                "xsdb not found. Add Vivado bin to PATH or pass xsdb_path=."
            )

        self._proc = subprocess.Popen(
            [xsdb],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_thread.start()
        mark("xsdb_spawned")

        self._send(f"connect -url tcp:{self.host}:{self.port}")
        # Widen hw_server's BSCAN switch mask so USER2-USER4 irshifts
        # reach the right BSCANE2 instead of collapsing onto USER1.
        # Defaults to 0x1 (USER1 only) on Zynq US+ MPSoC.
        self._send("configparams bscan-switch-user-mask 0xF")
        self._send("configparams xsdb-user-bscan 1,2,3,4")
        mark("hw_server_tcp")

        if self.bitfile:
            _hw_log.info(
                "Programming FPGA from bitfile (fpga -file): %s",
                self.bitfile,
            )
            self.program(self.bitfile)
            mark("fpga_file_done")
        else:
            _hw_log.info(
                "Skipping fpga -file — using the configuration already in the FPGA. "
                "Uncheck 'Program on connect' or clear the bitfile path in Connection "
                "when you do not want to reprogram.",
            )
            mark("fpga_skipped")

        self._send(
            f'jtag targets -set -filter {{name =~ "{self.fpga_name}"}}'
        )
        mark("jtag_target_set")

        # Wait for the JTAG chain to respond with valid (non-zero) data on
        # the configured probe register.  After fpga -file the bitstream is
        # uploaded but the FPGA's startup sequence (DONE assertion, BSCAN
        # bring-up, internal config logic settling) can run a few hundred
        # ms longer.  Reading too early returns all-zero scans.  Polling
        # here pushes the entire "is the chain alive yet?" concern into the
        # transport, so callers can rely on connect() returning a working
        # session.  Pass ready_probe_addr=None to skip (e.g. when the
        # bitstream cannot guarantee a non-zero response at any address).
        if self.ready_probe_addr is not None and self.bitfile:
            _hw_log.info(
                "Waiting for FPGA ready (probe register 0x%04X, timeout %.1fs)",
                self.ready_probe_addr,
                self.ready_probe_timeout,
            )
            attempts = self._wait_until_ready()
            mark("fpga_ready")
            _hw_log.info("FPGA ready probe succeeded.")
            if timing:
                _hw_log.info(
                    "hw_server connect: ready_poll attempts=%d (see fpga_ready delta)",
                    attempts,
                )
        else:
            mark("ready_skipped")

        mark("connect_done")
        if timing and len(marks) >= 2:
            parts = []
            for i in range(1, len(marks)):
                label, t = marks[i]
                dt = t - marks[i - 1][1]
                parts.append(f"{label}={dt:.3f}s")
            total = marks[-1][1] - marks[0][1]
            _hw_log.info(
                "hw_server connect timing (FCAPZ_LOG_CONNECT_TIMING): %s | total=%.3fs",
                " ".join(parts),
                total,
            )

    def _wait_until_ready(self) -> int:
        """Poll the configured probe register until it returns non-zero.

        Raises ConnectionError if the deadline elapses.  Uses the chain
        currently active (default chain 1 / USER1).

        Returns:
            Number of probe read attempts (including the successful one).
        """
        deadline = time.monotonic() + self.ready_probe_timeout
        attempts = 0
        last_value = 0
        while time.monotonic() < deadline:
            try:
                last_value = self.read_reg(self.ready_probe_addr)
            except Exception:
                last_value = 0
            attempts += 1
            if last_value != 0:
                return attempts
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.ready_poll_interval_sec, remaining))
        raise ConnectionError(
            f"FPGA did not become ready within {self.ready_probe_timeout}s "
            f"after program() (probe addr=0x{self.ready_probe_addr:04X}, "
            f"last_value=0x{last_value:08X}, attempts={attempts}). "
            "Either the bitstream failed to load, the wrong fpga_name was "
            "selected, or the probe register address is wrong for this design."
        )

    def program(self, bitfile: str) -> None:
        """Program the FPGA with *bitfile* using the current XSDB session."""
        if not _TCL_PATH_RE.match(bitfile):
            raise ValueError(
                f"bitfile path contains unsafe characters for TCL: {bitfile!r}"
            )
        self._send(f'targets -set -filter {{name =~ "{self.fpga_name}"}}')
        self._send(f"fpga -file {{{bitfile}}}")
        self._send(f"after {int(self.post_program_delay_ms)}")

    def close(self) -> None:
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write("exit\n")
                self._proc.stdin.flush()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def close_fast(self) -> None:
        """Kill ``xsdb`` quickly for console interrupt; normal :meth:`close` may wait 5s."""
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.write("exit\n")
                    proc.stdin.flush()
                except OSError:
                    pass
        except (OSError, ValueError):
            pass
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        self._proc = None

    # -- chain selection -----------------------------------------------------

    def select_chain(self, chain: int) -> None:
        """Select BSCANE2 USER chain for subsequent register accesses."""
        if self.use_register_ir:
            if not (1 <= chain <= 4):
                raise ValueError(f"chain must be 1..4, got {chain}")
        elif chain not in self.ir_table:
            raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
        self._active_chain = chain

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        """Perform a raw DR scan via XSDB jtag sequence (irscan + drscan)."""
        ch = chain if chain is not None else self._active_chain
        bit_str = "".join("1" if (bits >> i) & 1 else "0" for i in range(width))
        padded = self._pad_dr(bit_str)
        total = self._user_dr_bits(width)
        tcl = (
            f"set _rd [jtag sequence]; "
            f"{self._irshift_tcl('_rd', ch)}; "
            f"$_rd drshift -state IDLE -capture -bits {total} {padded}; "
            f"$_rd delay {self.RAW_DR_IDLE_CYCLES}; "
            f"puts [$_rd run -bits]; $_rd delete"
        )
        out = self._send(tcl)
        return self._parse_scan_bits(out, width, total)

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        """Perform multiple raw DR scans in one XSDB jtag sequence."""
        if not scans:
            return []
        ch = chain if chain is not None else self._active_chain
        parts = ["set _rdb [jtag sequence]"]
        totals: list[int] = []
        widths: list[int] = []
        for bits, width in scans:
            bit_str = "".join("1" if (bits >> i) & 1 else "0" for i in range(width))
            padded = self._pad_dr(bit_str)
            total = self._user_dr_bits(width)
            parts.append(
                f"{self._irshift_tcl('_rdb', ch)}; "
                f"$_rdb drshift -state IDLE -capture -bits {total} {padded}; "
                f"$_rdb delay {self.RAW_DR_IDLE_CYCLES}"
            )
            totals.append(total)
            widths.append(width)
        parts.append("puts [$_rdb run -bits]; $_rdb delete")
        out = self._send("; ".join(parts))
        return self._parse_scan_bits_list(out, widths, totals)

    # -- register access -----------------------------------------------------

    def read_reg(self, addr: int) -> int:
        frame = self._frame_bits(addr=addr, data=0, write=False)
        tcl = self._read_reg_tcl(frame)
        raw = self._send(tcl)
        return self._parse_bits_u32(raw)

    def read_reg_verified(self, addr: int) -> int:
        """Read a register twice and return the second value.

        Works around a JTAG pipeline stale-data issue where the first read
        after a session change may return data from the previous address.
        """
        self.read_reg(addr)
        return self.read_reg(addr)

    def write_reg(self, addr: int, value: int) -> None:
        frame = self._frame_bits(addr=addr, data=value, write=True)
        tcl = self._write_reg_tcl(frame)
        self._send(tcl)

    _BLOCK_CHUNK = 512  # max reads per single jtag sequence

    def read_block(self, addr: int, words: int) -> List[int]:
        """Read *words* consecutive 32-bit registers starting at *addr*.

        If *addr* is the DATA window base (0x0100) and burst mode is
        available, uses the wide USER2 DR for ~10x faster throughput.
        Otherwise falls back to single-sequence pipelined reads on USER1.
        """
        if words <= 0:
            return []
        if addr == 0x0100 and self._burst_available:
            try:
                return self._read_block_burst(words)
            except (ConnectionError, RuntimeError):
                self._has_burst = False
        # Non-burst path needs flush to reset USER1 pipeline
        return self._read_block_user1(addr, words)

    @property
    def _burst_available(self) -> bool:
        """True if the bitstream has a fast burst interface."""
        if not hasattr(self, "_has_burst"):
            # Do not probe by writing BURST_PTR here: that register is a
            # side-effecting start toggle for the burst engine.
            self._has_burst = True
        return self._has_burst

    @property
    def _burst_samples_per_scan(self) -> int:
        """Samples per 256-bit burst scan, based on hardware SAMPLE_W."""
        if not hasattr(self, "_cached_sps"):
            sw = self.read_reg_verified(0x000C)  # ADDR_SAMPLE_W
            if sw < 1:
                sw = 8
            self._cached_sps = max(1, self.BURST_DR_BITS // sw)
        return self._cached_sps

    def _read_block_burst(
        self,
        words: int,
        *,
        timestamp: bool = False,
        element_width: int | None = None,
    ) -> List[int]:
        """Read *words* samples via the 256-bit burst DR.

        Packs everything into a **single** ``jtag sequence``:
        USER1 write to BURST_PTR → idle for staging fill → IR switch
        to USER2 → N consecutive 256-bit DR scans.  One round-trip.
        """
        if timestamp:
            if element_width is None:
                element_width = 32
            sps = max(1, self.BURST_DR_BITS // element_width)
        else:
            sps = self._burst_samples_per_scan
            element_width = self.BURST_DR_BITS // sps
        n_scans = (words + sps - 1) // sps
        prime_scans = 1

        dr_bits = self.BURST_DR_BITS
        burst_total = self._user_dr_bits(dr_bits)
        burst_zeros = self._pad_dr("0" * dr_bits)

        burst_frame = self._pad_dr(
            self._frame_bits(
                addr=self.ADDR_BURST_PTR,
                data=(0x80000000 if timestamp else 0),
                write=True,
            )
        )
        user_total = self._user_dr_bits(self.DR_BITS)
        ir1_cmd = self._irshift_tcl("_bq", chain=1)
        burst_chain = 1 if self.single_chain_burst else 2
        ir_burst_cmd = self._irshift_tcl("_bq", chain=burst_chain)

        if self.use_register_ir:
            # Register mode: BURST_PTR write needs DRUPDATE + split-
            # sequence IDLE/delay (same pattern as _write_reg_tcl).
            # Burst scans go in a separate sequence afterwards.
            write_idle = max(self.WRITE_IDLE_CYCLES_REGISTER, self.BURST_PREFILL_IDLE_CYCLES)
            parts_w = [
                "set _bq [jtag sequence]",
                f"{ir1_cmd}; "
                f"$_bq drshift -state DRUPDATE -bits {user_total} {burst_frame}",
                "$_bq run; $_bq delete",
                "set _bqd [jtag sequence]",
                "$_bqd state IDLE",
                f"$_bqd delay {write_idle}",
                "$_bqd run; $_bqd delete",
            ]
            parts_r = ["set _bq [jtag sequence]"]
            for _ in range(n_scans + prime_scans):
                parts_r.append(
                    f"{ir_burst_cmd}; "
                    f"$_bq drshift -state DRUPDATE -capture -bits {burst_total} {burst_zeros}"
                )
            parts_r.append("puts [$_bq run -bits]; $_bq delete")
            tcl = "; ".join(parts_w + parts_r)
        else:
            parts_w = [
                "set _bq [jtag sequence]",
                # Write BURST_PTR via USER1 (triggers start_ptr load)
                # End in IDLE so the subsequent delay is valid on xsdb 2025.2.
                f"{ir1_cmd}; "
                f"$_bq drshift -state IDLE -bits {user_total} {burst_frame}",
                # Idle so the USER1 BURST_PTR update crosses into the burst
                # reader and the first 256-bit staging word fills before
                # USER2 CAPTURE samples it. Real BSCAN/XSDB timing needs
                # more margin than the raw ~33 TCK memory-fill latency.
                f"$_bq delay {self.BURST_PREFILL_IDLE_CYCLES}",
                "$_bq run; $_bq delete",
            ]
            parts_r = ["set _bq [jtag sequence]"]
            # The first wide scan primes/fills staging and is discarded.
            for _ in range(n_scans + prime_scans):
                parts_r.append(
                    f"{ir_burst_cmd}; "
                    f"$_bq drshift -state DRUPDATE -capture -bits {burst_total} {burst_zeros}"
                )
            parts_r.append("puts [$_bq run -bits]; $_bq delete")
            tcl = "; ".join(parts_w + parts_r)

        def run_once() -> List[int]:
            out = self._send(tcl)
            return self._parse_burst_bits(
                out,
                words,
                skip_scans=prime_scans,
                element_width=element_width,
            )

        first = run_once()
        if not self.single_chain_burst:
            return first

        # Single-chain burst shares one USER chain between 49-bit register
        # frames and 256-bit burst frames.  Once STATUS.done is observed, the
        # capture RAM is read-only until the next ARM/RESET, so repeating the
        # same BURST_PTR transaction must return identical data.  Real
        # hw_server/BSCANE2 sessions can return one stale first transaction
        # immediately after rapid re-arm; require a stable pair and fail loudly
        # if the stream does not converge instead of silently accepting a
        # one-off retry result.
        previous = first
        for _attempt in range(3):
            current = run_once()
            if current == previous:
                return current
            previous = current
        raise RuntimeError("single-chain burst readback did not stabilize")

    def read_timestamp_block(self, addr: int, words: int, timestamp_width: int) -> List[int]:
        """Read timestamp words through the configured burst mode when available."""
        if words <= 0:
            return []
        if self._burst_available and timestamp_width > 0:
            try:
                return self._read_block_burst(
                    words,
                    timestamp=True,
                    element_width=timestamp_width,
                )
            except (ConnectionError, RuntimeError):
                self._has_burst = False
        return self._read_block_user1(addr, words)

    def _parse_burst_bits(
        self,
        output: str,
        total_words: int,
        *,
        skip_scans: int = 0,
        element_width: int | None = None,
    ) -> List[int]:
        """Parse burst DR output: each token is a 256-bit string packing
        samples (SAMPLE_W bits each, LSB first).
        """
        if element_width is None:
            sps = self._burst_samples_per_scan
            sw = self.BURST_DR_BITS // sps  # bits per sample
        else:
            sw = element_width
            sps = max(1, self.BURST_DR_BITS // sw)
        values: list[int] = []
        scan_idx = 0
        burst_offset = self._dr_data_offset()
        min_len = burst_offset + self.BURST_DR_BITS
        for token in output.replace("{", " ").replace("}", " ").split():
            token = token.strip()
            if not token or len(token) < min_len:
                continue
            if set(token) - {"0", "1"}:
                continue
            if scan_idx < skip_scans:
                scan_idx += 1
                continue
            scan_idx += 1
            for s in range(sps):
                if len(values) >= total_words:
                    break
                offset = burst_offset + s * sw
                val = self._bits_to_int(token, offset, sw)
                values.append(val)
        return values[:total_words]

    def _read_block_user1(self, addr: int, words: int) -> List[int]:
        """Fallback: single-sequence pipelined reads via USER1 49-bit DR."""
        results: list[int] = []
        for start in range(0, words, self._BLOCK_CHUNK):
            end = min(start + self._BLOCK_CHUNK, words)
            chunk_size = end - start
            tcl = self._burst_read_tcl(addr, start, chunk_size)
            out = self._send(tcl)
            results.extend(self._parse_block_bits(out, chunk_size, skip_words=1))
        # Flush JTAG pipeline
        self.read_reg(0x0000)
        return results

    def _burst_read_tcl(self, base_addr: int, offset: int, count: int) -> str:
        """Generate TCL for burst block read using a single jtag sequence.

        All scans go into one sequence object: one address setup, one
        discarded priming capture, then N returned captures.  A short idle
        follows each address update before the next capture so the
        fabric-domain read request can cross, read RAM, and resynchronize
        before CAPTURE samples jtag_rdata.
        """
        n = self._user_dr_bits(self.DR_BITS)
        idle = self.READ_IDLE_CYCLES
        ir_cmd = self._irshift_tcl("_q", chain=1)
        frames: list[str] = []
        for i in range(count):
            frames.append(
                self._pad_dr(
                    self._frame_bits(addr=base_addr + (offset + i) * 4, data=0, write=False)
                )
            )

        parts: list[str] = [
            "set _q [jtag sequence]",
            # Scan 0: set first address, no capture
            f"{ir_cmd}; "
            f"$_q drshift -state IDLE -bits {n} {frames[0]}",
            f"$_q delay {idle}",
            # Prime capture: discard this word.  Hardware/XSDB can leave the
            # first captured USER1 word stale after a previous pipelined read.
            f"{ir_cmd}; "
            f"$_q drshift -state IDLE -capture -bits {n} {frames[0]}",
            f"$_q delay {idle}",
        ]
        # Scans 1..N-1: capture previous AND set next address.
        # End in IDLE so the subsequent delay is valid on xsdb 2025.2.
        for i in range(1, count):
            parts.append(
                f"{ir_cmd}; "
                f"$_q drshift -state IDLE -capture -bits {n} {frames[i]}"
            )
            parts.append(f"$_q delay {idle}")
        # Final scan: capture last result
        parts.append(
            f"{ir_cmd}; "
            f"$_q drshift -state DRUPDATE -capture -bits {n} {frames[-1]}"
        )
        parts.append("puts [$_q run -bits]; $_q delete")
        return "; ".join(parts)

    def read_regs_pipelined_user1(self, addrs: List[int]) -> List[int]:
        """Read several CSR addresses in one ``jtag sequence`` / :meth:`_send` round-trip.

        Uses the same USER1 pipelined capture pattern as :meth:`_burst_read_tcl`
        (IR+DR per step; capture carries the previous address's data).  A final
        :meth:`read_reg` to VERSION flushes the JTAG pipeline for later accesses.
        """
        if not addrs:
            return []
        n = self._user_dr_bits(self.DR_BITS)
        ir_cmd = self._irshift_tcl("_pq")
        frames = [
            self._pad_dr(self._frame_bits(addr=a, data=0, write=False))
            for a in addrs
        ]
        count = len(frames)
        parts: list[str] = [
            "set _pq [jtag sequence]",
            f"{ir_cmd}; "
            f"$_pq drshift -state DRUPDATE -bits {n} {frames[0]}",
        ]
        for i in range(1, count):
            parts.append(
                f"{ir_cmd}; "
                f"$_pq drshift -state DRUPDATE -capture -bits {n} {frames[i]}"
            )
        parts.append(
            f"{ir_cmd}; "
            f"$_pq drshift -state DRUPDATE -capture -bits {n} {frames[-1]}"
        )
        parts.append("puts [$_pq run -bits]; $_pq delete")
        tcl = "; ".join(parts)
        out = self._send(tcl)
        vals = self._parse_block_bits(out, count)
        self.read_reg(0x0000)
        return vals


    # -- chain shape helpers -------------------------------------------------

    # Write delay: on MPSoC in -register mode, writes need a longer settling
    # delay (~100 TCK) and an explicit state-IDLE transition to reliably
    # commit the UPDATE-DR event.  On 7-series READ_IDLE_CYCLES (20) suffices.
    WRITE_IDLE_CYCLES_REGISTER = 100
    BURST_PREFILL_IDLE_CYCLES = 160

    def _ir_hex(self, value: int) -> str:
        """Format an IR opcode as the right-width hex string for ``-hex N``."""
        return f"{value:0{self._ir_hex_digits}x}"

    def _irshift_tcl(self, seq_var: str, chain: int | None = None) -> str:
        """Return the ``irshift`` TCL fragment for *seq_var* targeting *chain*.

        In ``use_register_ir`` mode, emits ``-register user{chain}`` which
        lets xsdb handle the multi-TAP IR routing internally (needed on
        Zynq US+ MPSoC).  Otherwise emits ``-hex {ir_length} {opcode}``
        using the chain's entry in ``ir_table``.
        """
        ch = chain if chain is not None else self._active_chain
        if self.use_register_ir:
            return f"${seq_var} irshift -state IRUPDATE -register user{ch}"
        ir = self._ir_hex(self.ir_table[ch])
        return f"${seq_var} irshift -state IRUPDATE -hex {self.ir_length} {ir}"

    def _user_dr_bits(self, frame_bits: int) -> int:
        """Total bits to shift on a DR scan whose fcapz portion is *frame_bits*."""
        return frame_bits + self.dr_extra_bits

    def _pad_dr(self, frame: str) -> str:
        """Add BYPASS bits to *frame* so the chain-total DR width is correct.

        ``dr_extra_position == "tdo"`` puts BYPASS bits at the LSB end (shifted
        out first, i.e. the bypass TAP is closer to TDO than the fcapz TAP).
        ``"tdi"`` puts them at the MSB end.  The values are zeros — BYPASS
        just relays, so the shift-in bits are don't-care.
        """
        if self.dr_extra_bits == 0:
            return frame
        bypass = "0" * self.dr_extra_bits
        if self.dr_extra_position == "tdo":
            return bypass + frame
        return frame + bypass

    def _dr_data_offset(self) -> int:
        """Index into a captured DR token where the fcapz frame begins."""
        return self.dr_extra_bits if self.dr_extra_position == "tdo" else 0

    # -- frame helpers -------------------------------------------------------

    @staticmethod
    def _frame_bits(addr: int, data: int, write: bool) -> str:
        """Build 49-char '0'/'1' string: bits[31:0]=data, [47:32]=addr, [48]=rnw."""
        chars: list[str] = []
        for i in range(32):
            chars.append("1" if (data >> i) & 1 else "0")
        for i in range(16):
            chars.append("1" if (addr >> i) & 1 else "0")
        chars.append("1" if write else "0")
        return "".join(chars)

    # -- TCL generation ------------------------------------------------------

    def _read_reg_tcl(self, frame: str, var_suffix: str = "") -> str:
        """Return TCL that performs one register read and returns the bit string.

        Uses a SINGLE jtag sequence for all operations (IR+DR+idle+IR+DR)
        to eliminate inter-sequence timing gaps that cause stale reads.

        Note: drshift ends in state IDLE (not DRUPDATE) because xsdb 2025.2
        requires delay to be in RESET/IDLE/PAUSE — DRUPDATE→delay errors.
        """
        v = f"_s{var_suffix}"
        n = self._user_dr_bits(self.DR_BITS)
        idle = self.READ_IDLE_CYCLES
        padded = self._pad_dr(frame)
        ir_cmd = self._irshift_tcl(v)
        return (
            f"set {v} [jtag sequence]; "
            f"{ir_cmd}; "
            f"${v} drshift -state IDLE -bits {n} {padded}; "
            f"${v} delay {idle}; "
            f"{ir_cmd}; "
            f"${v} drshift -state IDLE -capture -bits {n} {padded}; "
            f"puts [${v} run -bits]; ${v} delete"
        )

    def _write_reg_tcl(self, frame: str) -> str:
        n = self._user_dr_bits(self.DR_BITS)
        padded = self._pad_dr(frame)
        ir_cmd = self._irshift_tcl("_w")
        if self.use_register_ir:
            # On MPSoC in -register mode, writes need explicit DRUPDATE
            # state (the -state IDLE shortcut doesn't reliably fire the
            # UPDATE-DR event through the named-register path) and a
            # longer settling delay (~100 TCK).  The delay runs in a
            # separate sequence after an explicit state-IDLE transition.
            idle = self.WRITE_IDLE_CYCLES_REGISTER
            return (
                f"set _w [jtag sequence]; "
                f"{ir_cmd}; "
                f"$_w drshift -state DRUPDATE -bits {n} {padded}; "
                f"$_w run; $_w delete; "
                f"set _wd [jtag sequence]; "
                f"$_wd state IDLE; "
                f"$_wd delay {idle}; "
                f"$_wd run; $_wd delete"
            )
        idle = self.READ_IDLE_CYCLES
        return (
            f"set _w [jtag sequence]; "
            f"{ir_cmd}; "
            f"$_w drshift -state IDLE -bits {n} {padded}; "
            f"$_w run; $_w delete; "
            f"set _wd [jtag sequence]; "
            f"$_wd delay {idle}; "
            f"$_wd run; $_wd delete"
        )

    # -- output parsing ------------------------------------------------------

    @staticmethod
    def _bits_to_int(bits: str, offset: int, length: int) -> int:
        result = 0
        for i in range(length):
            if bits[offset + i] == "1":
                result |= 1 << i
        return result

    def _parse_bits_u32(self, output: str) -> int:
        """Extract a 32-bit value from the last bit-string line in *output*."""
        offset = self._dr_data_offset()
        min_len = offset + 32
        for line in reversed(output.strip().splitlines()):
            line = line.strip()
            if line and set(line) <= {"0", "1"} and len(line) >= min_len:
                return self._bits_to_int(line, offset, 32)
        raise RuntimeError(
            "xsdb: no bit string in output. "
            f"stdout={output!r}; "
            f"recent stderr={self._stderr_lines[-10:]!r}"
        )

    def _parse_block_bits(
        self,
        output: str,
        expected: int,
        *,
        skip_words: int = 0,
    ) -> List[int]:
        """Extract *expected* 32-bit values from bit-string tokens."""
        values: list[int] = []
        seen = 0
        offset = self._dr_data_offset()
        min_len = offset + 32
        # Split on whitespace and braces (TCL list elements)
        for token in output.replace("{", " ").replace("}", " ").split():
            token = token.strip()
            if token and set(token) <= {"0", "1"} and len(token) >= min_len:
                if seen < skip_words:
                    seen += 1
                    continue
                seen += 1
                values.append(self._bits_to_int(token, offset, 32))
        if len(values) < expected:
            raise RuntimeError(
                f"xsdb: expected {expected} results, got {len(values)}. "
                f"stdout={output[:500]!r}; "
                f"recent stderr={self._stderr_lines[-10:]!r}"
            )
        return values[:expected]

    def _parse_scan_bits(self, output: str, width: int, total: int) -> int:
        """Extract one raw DR scan result of *width* bits from XSDB output."""
        results = self._parse_scan_bits_list(output, [width], [total])
        return results[0]

    def _parse_scan_bits_list(
        self,
        output: str,
        widths: List[int],
        totals: List[int],
    ) -> List[int]:
        """Extract raw DR scan results with per-scan widths from XSDB output."""
        tokens: list[str] = []
        for token in output.replace("{", " ").replace("}", " ").split():
            token = token.strip()
            if token and set(token) <= {"0", "1"}:
                tokens.append(token)
        offset = self._dr_data_offset()
        out: list[int] = []
        token_idx = 0
        for width, total in zip(widths, totals):
            min_len = max(total, offset + width)
            while token_idx < len(tokens) and len(tokens[token_idx]) < min_len:
                token_idx += 1
            if token_idx >= len(tokens):
                raise RuntimeError(
                    f"xsdb: expected {len(widths)} raw scan results, got {len(out)}. "
                    f"stdout={output[:500]!r}; "
                    f"recent stderr={self._stderr_lines[-10:]!r}"
                )
            out.append(self._bits_to_int(tokens[token_idx], offset, width))
            token_idx += 1
        return out

    # -- process I/O ---------------------------------------------------------

    def _send(self, tcl: str) -> str:
        """Send *tcl* to the persistent xsdb process and return output.

        Set environment variable ``FCAPZ_LOG_XSDB=1`` to log every TCL
        request and every xsdb response to ``stderr`` — use this for
        wire-level debugging on unusual chains (e.g. investigating why a
        read returns wrong data on Zynq US+ MPSoC).  The output is noisy
        but decodable: one ``tcl>`` line per request, one ``tdo>`` line
        per response.
        """
        log = os.environ.get("FCAPZ_LOG_XSDB") == "1"
        with self._xsdb_io_lock:
            if not self._proc or not self._proc.stdin or not self._proc.stdout:
                raise RuntimeError("not connected — call connect() first")
            if log:
                sys.stderr.write(f"[fcapz xsdb] tcl> {tcl}\n")
                sys.stderr.flush()
            self._proc.stdin.write(tcl + "\n")
            self._proc.stdin.write(f'puts "{self._SENTINEL}"\n')
            self._proc.stdin.flush()

            lines: list[str] = []
            while True:
                raw = self._proc.stdout.readline()
                if not raw:
                    stderr = "\n".join(self._stderr_lines[-20:])
                    raise ConnectionError(
                        f"xsdb process exited unexpectedly. stderr:\n{stderr}"
                    )
                line = raw.rstrip("\n\r")
                if line.strip() == self._SENTINEL:
                    break
                lines.append(line)
            out = "\n".join(lines)
            if log:
                sys.stderr.write(f"[fcapz xsdb] tdo> {out!r}\n")
                sys.stderr.flush()
            return out

    def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            raise RuntimeError("xsdb process not initialized")
        for raw in self._proc.stderr:
            self._stderr_lines.append(raw.rstrip("\n\r"))


class VendorStubTransport(Transport):
    """Placeholder adapter for future non-Xilinx backends."""

    def __init__(self, vendor: str):
        self.vendor = vendor

    def connect(self) -> None:
        raise NotImplementedError(f"{self.vendor} transport not implemented")

    def close(self) -> None:
        return None

    def read_reg(self, addr: int) -> int:
        raise NotImplementedError

    def write_reg(self, addr: int, value: int) -> None:
        raise NotImplementedError

    def read_block(self, addr: int, words: int) -> List[int]:
        raise NotImplementedError
