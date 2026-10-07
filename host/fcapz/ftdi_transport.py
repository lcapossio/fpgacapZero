# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Native JTAG over an FTDI MPSSE adapter, through FTDI's D2XX driver.

:class:`FtdiMpsseTransport` drives an FT2232H / FT4232H JTAG channel
directly: no OpenOCD, no vendor tool.  It uses the D2XX library
(``ftd2xx.dll`` on Windows, ``libftd2xx.so`` / ``libftd2xx.dylib``
elsewhere), which is the driver Microchip's FlashPro and Digilent's
adapters already use on Windows, so it coexists with Libero / Vivado: the
transport holds the adapter only while connected.

Scope: one device on the JTAG chain.  At connect the transport reads the
IDCODE chain, measures the IR length, and picks the IR table from the
IDCODE manufacturer unless one is given.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from typing import List, NamedTuple

from .transport import (
    BurstIntegrityError,
    ScanOp,
    Transport,
    _ScanBurstMixin,
    check_data_window,
)

# -- D2XX ------------------------------------------------------------------

_FT_OK = 0
_FT_FLAGS_OPENED = 0x1
_lib = None
_lib_lock = threading.Lock()


def _load_d2xx():
    """Load the D2XX library once.  ``$FCAPZ_D2XX_LIBRARY`` overrides the
    platform default name."""
    global _lib
    with _lib_lock:
        if _lib is not None:
            return _lib
        name = os.environ.get("FCAPZ_D2XX_LIBRARY")
        if not name:
            if sys.platform == "win32":
                name = "ftd2xx.dll"
            elif sys.platform == "darwin":
                name = "libftd2xx.dylib"
            else:
                name = "libftd2xx.so"
        try:
            if sys.platform == "win32":
                _lib = ctypes.WinDLL(name)
            else:
                _lib = ctypes.CDLL(name)
        except OSError as exc:
            raise RuntimeError(
                f"FTDI D2XX library {name!r} not found ({exc}). Install FTDI's "
                "D2XX driver (on Windows it ships with the FTDI, Microchip "
                "FlashPro and Digilent drivers; on Linux unbind ftdi_sio from "
                "the adapter), or set FCAPZ_D2XX_LIBRARY to its path."
            ) from exc
        return _lib


class FtdiDevice(NamedTuple):
    """One FTDI channel as D2XX enumerates it."""

    index: int
    description: str
    serial: str
    usb_id: int  # VID << 16 | PID
    opened: bool


def list_ftdi_devices() -> list[FtdiDevice]:
    """Return every FTDI channel the D2XX driver sees."""
    lib = _load_d2xx()
    count = ctypes.c_ulong()
    if lib.FT_CreateDeviceInfoList(ctypes.byref(count)) != _FT_OK:
        raise RuntimeError("FT_CreateDeviceInfoList failed")
    devices: list[FtdiDevice] = []
    for i in range(count.value):
        flags, typ, usb_id, loc = (ctypes.c_ulong() for _ in range(4))
        serial = ctypes.create_string_buffer(64)
        desc = ctypes.create_string_buffer(64)
        handle = ctypes.c_void_p()
        status = lib.FT_GetDeviceInfoDetail(
            i, ctypes.byref(flags), ctypes.byref(typ), ctypes.byref(usb_id),
            ctypes.byref(loc), serial, desc, ctypes.byref(handle),
        )
        if status != _FT_OK:
            continue
        devices.append(
            FtdiDevice(
                index=i,
                description=desc.value.decode("ascii", errors="replace"),
                serial=serial.value.decode("ascii", errors="replace"),
                usb_id=usb_id.value,
                opened=bool(flags.value & _FT_FLAGS_OPENED),
            )
        )
    return devices


#: Pin layouts of known JTAG adapters, matched by a substring of the D2XX
#: description: (ADBUS initial value, ADBUS direction).  ADBUS0..3 are
#: TCK / TDI / TDO / TMS on every MPSSE JTAG adapter.
ADAPTER_LAYOUTS: tuple[tuple[str, int, int], ...] = (
    # Microchip FlashPro5 (embedded or standalone): ADBUS4 is nTRST.
    ("FlashPro", 0x18, 0x1B),
    # Digilent adapters (Arty, HS1/HS2-style): ADBUS7 enables the JTAG buffer.
    ("Digilent", 0x88, 0x8B),
)
#: Layout for adapters not listed above: TMS high, TCK/TDI/TMS outputs.
DEFAULT_LAYOUT = (0x08, 0x0B)


def _layout_for(description: str) -> tuple[int, int] | None:
    for key, value, direction in ADAPTER_LAYOUTS:
        if key.lower() in description.lower():
            return value, direction
    return None


def _pick_device(devices: list[FtdiDevice], device: str | None) -> FtdiDevice:
    """Pick the adapter channel: by exact description or serial, or the
    single known JTAG adapter's channel A."""
    listing = ", ".join(repr(d.description) for d in devices) or "none"
    if device:
        for d in devices:
            if device in (d.description, d.serial):
                return d
        raise RuntimeError(
            f"no FTDI channel with description or serial {device!r}; found: {listing}"
        )
    known = [
        d for d in devices
        if d.description.endswith(" A") and _layout_for(d.description) is not None
    ]
    if len(known) == 1:
        return known[0]
    if not known:
        busy = sum(1 for d in devices if d.opened)
        hint = (
            f" {busy} FTDI channel(s) are open in another program (Libero, "
            "FlashPro Express, hw_server, OpenOCD) and cannot be named; close it."
            if busy else ""
        )
        raise RuntimeError(
            "no known FTDI JTAG adapter found (FlashPro, Digilent); name the "
            f"channel with device=... (--hardware). Found: {listing}.{hint}"
        )
    raise RuntimeError(
        "several FTDI JTAG adapters found; pick one with device=... "
        f"(--hardware): {', '.join(repr(d.description) for d in known)}"
    )


def _release(lib, handle: ctypes.c_void_p) -> None:
    """Leave MPSSE mode and close a D2XX handle."""
    try:
        lib.FT_SetBitMode(handle, 0, 0)
    finally:
        lib.FT_Close(handle)


# -- MPSSE JTAG batches ----------------------------------------------------

# MPSSE opcodes (FTDI AN_108).  JTAG: TDI changes on the falling TCK edge,
# TDO is sampled on the rising edge, data LSB first.
_DATA_BYTES_OUT = 0x19
_DATA_BYTES_INOUT = 0x39
_DATA_BITS_OUT = 0x1B
_DATA_BITS_INOUT = 0x3B
_TMS_OUT = 0x4B
_TMS_INOUT = 0x6B
_SEND_IMMEDIATE = 0x87

# TAP paths from Run-Test/Idle.
_IDLE_TO_SHIFT_IR = (1, 1, 0, 0)
_IDLE_TO_SHIFT_DR = (1, 0, 0)
# The last data bit leaves Shift-xR (TMS=1), then Update-xR, then Idle.
_LAST_BIT_TO_IDLE = (1, 1, 0)


class _Batch:
    """MPSSE command bytes for a run of JTAG scans, plus how to decode the
    bytes they return."""

    def __init__(self) -> None:
        self.cmd = bytearray()
        self.read_bytes = 0
        # Per captured scan: (width, whole data bytes, leftover bits).
        self.captures: list[tuple[int, int, int]] = []

    def tms(self, bits, tdi: int = 0) -> None:
        bits = list(bits)
        while bits:
            chunk, bits = bits[:7], bits[7:]
            value = sum(b << i for i, b in enumerate(chunk)) | ((tdi & 1) << 7)
            self.cmd += bytes((_TMS_OUT, len(chunk) - 1, value))

    def idle(self, n: int) -> None:
        self.tms([0] * max(0, int(n)))

    def reset(self) -> None:
        self.tms((1, 1, 1, 1, 1, 0))

    def scan(self, ir: bool, value: int, width: int, capture: bool) -> None:
        """One IR or DR scan from Run-Test/Idle back to Run-Test/Idle."""
        if width < 1:
            raise ValueError(f"scan width must be >= 1, got {width}")
        self.tms(_IDLE_TO_SHIFT_IR if ir else _IDLE_TO_SHIFT_DR)
        body = width - 1
        nbytes, rem = divmod(body, 8)
        if nbytes:
            # 64 KiB per data command.
            done = 0
            while done < nbytes:
                n = min(nbytes - done, 0x10000)
                chunk = (value >> (done * 8)) & ((1 << (n * 8)) - 1)
                op = _DATA_BYTES_INOUT if capture else _DATA_BYTES_OUT
                self.cmd += bytes((op, (n - 1) & 0xFF, (n - 1) >> 8))
                self.cmd += chunk.to_bytes(n, "little")
                done += n
        if rem:
            op = _DATA_BITS_INOUT if capture else _DATA_BITS_OUT
            bits = (value >> (nbytes * 8)) & ((1 << rem) - 1)
            self.cmd += bytes((op, rem - 1, bits))
        last = (value >> (width - 1)) & 1
        tms_value = sum(b << i for i, b in enumerate(_LAST_BIT_TO_IDLE)) | (last << 7)
        self.cmd += bytes(
            (_TMS_INOUT if capture else _TMS_OUT, len(_LAST_BIT_TO_IDLE) - 1, tms_value)
        )
        if capture:
            self.captures.append((width, nbytes, rem))
            self.read_bytes += nbytes + (1 if rem else 0) + 1

    def decode(self, rx: bytes) -> list[int]:
        values: list[int] = []
        pos = 0
        for width, nbytes, rem in self.captures:
            value = int.from_bytes(rx[pos:pos + nbytes], "little")
            pos += nbytes
            if rem:
                # Bit-mode reads shift in from the MSB: the first bit lands
                # at bit (8 - rem).
                value |= (rx[pos] >> (8 - rem)) << (nbytes * 8)
                pos += 1
            # The last data bit is the first of the TMS read's clocks.
            last = (rx[pos] >> (8 - len(_LAST_BIT_TO_IDLE))) & 1
            pos += 1
            values.append(value | (last << (width - 1)))
        return values


# -- IDCODE families -------------------------------------------------------

_MFG_XILINX = 0x049
_MFG_MICROCHIP = 0x0E7  # Microsemi / Actel (JEDEC "GateField")
_MFG_GOWIN = 0x40D

_FAMILY_IR_TABLES: dict[str, dict[int, int]] = {
    "xilinx7": {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23},
    "polarfire": {1: 0x20, 2: 0x21},
    "gowin": {1: 0x42, 2: 0x43},
}
#: Whether each family's wrappers build a burst path by default.
_FAMILY_BURST: dict[str, bool] = {"xilinx7": True, "polarfire": True, "gowin": False}


def family_from_idcode(idcode: int, ir_length: int) -> str | None:
    """Return the IR-table family for *idcode*, or ``None`` if unknown."""
    mfg = (idcode >> 1) & 0x7FF
    if mfg == _MFG_MICROCHIP and ir_length == 8:
        return "polarfire"
    if mfg == _MFG_XILINX and ir_length == 6:
        return "xilinx7"
    if mfg == _MFG_GOWIN and ir_length == 8:
        return "gowin"
    return None


class _OpenChannel:
    """One D2XX handle, shared by every transport on that channel in this
    process: D2XX opens a channel exclusively, and the ELA, EIO and bridge
    sessions of one server each hold their own transport.  Every scan batch
    starts with its own IR scan, so instances interleave safely under
    ``lock``."""

    def __init__(self, lib, handle: ctypes.c_void_p, adapter: FtdiDevice) -> None:
        self.lib = lib
        self.handle = handle
        self.adapter = adapter
        self.lock = threading.RLock()
        self.users = 0
        self.idcode: int | None = None
        self.ir_length: int | None = None
        self.family: str | None = None
        self.actual_tck_hz: float | None = None


_OPEN_CHANNELS: list[_OpenChannel] = []
_OPEN_CHANNELS_LOCK = threading.Lock()


def _find_open_channel(device: str | None) -> _OpenChannel | None:
    if device is None:
        return _OPEN_CHANNELS[0] if len(_OPEN_CHANNELS) == 1 else None
    for ch in _OPEN_CHANNELS:
        if device in (ch.adapter.description, ch.adapter.serial):
            return ch
    return None


class FtdiMpsseTransport(_ScanBurstMixin, Transport):
    """fcapz JTAG transport on an FTDI MPSSE adapter (D2XX driver).

    ``device`` names the adapter channel by its D2XX description (for
    example ``"Embedded FlashPro5 A"``) or serial; by default the single
    known JTAG adapter's channel A is used.  ``ir_table`` defaults to the
    family read from the device IDCODE: PolarFire (``0x20`` / ``0x21``),
    AMD/Xilinx 7-series (``0x02`` / ``0x03`` / ``0x22`` / ``0x23``; pass the
    UltraScale table explicitly) or Gowin.  ``burst`` defaults to that
    family's wrapper default (on for PolarFire and AMD/Xilinx, off for
    Gowin).  ``layout`` overrides the adapter's ``(ADBUS value, direction)``.

    Transports on the same channel in one process share its handle (the
    first one's clock and layout apply); the channel closes with the last.
    """

    READ_IDLE_CYCLES = 20
    WRITE_IDLE_CYCLES = 8
    RAW_DR_IDLE_CYCLES = 8
    USER1_PIPE_PRIME_READS = 3
    MAX_DEVICES = 8
    #: Flush a batch to the adapter at this many command or reply bytes.
    _FLUSH_CMD_BYTES = 0xF000
    _FLUSH_READ_BYTES = 0x8000

    def __init__(
        self,
        device: str | None = None,
        *,
        ir_table: dict[int, int] | None = None,
        tck_hz: float = 6_000_000,
        burst: bool | None = None,
        single_chain_burst: bool = True,
        burst_data_chain: int = 2,
        layout: tuple[int, int] | None = None,
        timeout_ms: int = 2000,
    ):
        if not 1_000 <= tck_hz <= 30_000_000:
            raise ValueError(f"tck_hz must be 1 kHz..30 MHz, got {tck_hz}")
        self.device = device
        self.ir_table = dict(ir_table) if ir_table else {}
        self._ir_table_given = bool(ir_table)
        self.tck_hz = float(tck_hz)
        self._burst_arg = burst
        self.burst = bool(burst) if burst is not None else False
        self.single_chain_burst = bool(single_chain_burst)
        self.burst_data_chain = int(burst_data_chain)
        self.layout = layout
        self.timeout_ms = int(timeout_ms)
        self._active_chain = 1
        self._handle: ctypes.c_void_p | None = None
        self._lib = None
        self._channel: _OpenChannel | None = None
        self._io_lock = threading.RLock()
        #: Filled by :meth:`connect`.
        self.adapter: FtdiDevice | None = None
        self.idcode: int | None = None
        self.ir_length: int | None = None
        self.family: str | None = None
        self.actual_tck_hz: float | None = None

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        with _OPEN_CHANNELS_LOCK:
            if self._channel is not None:
                return
            ch = _find_open_channel(self.device)
            if ch is None:
                ch = self._open_channel()
                _OPEN_CHANNELS.append(ch)
            ch.users += 1
            self._channel = ch
            self._lib, self._handle, self.adapter = ch.lib, ch.handle, ch.adapter
            self._io_lock = ch.lock
            self.idcode, self.ir_length = ch.idcode, ch.ir_length
            self.family, self.actual_tck_hz = ch.family, ch.actual_tck_hz
        try:
            self._apply_family_defaults()
        except Exception:
            self.close()
            raise

    def _open_channel(self) -> _OpenChannel:
        """Open, set up and identify a channel no transport holds yet."""
        lib = _load_d2xx()
        dev = _pick_device(list_ftdi_devices(), self.device)
        layout = self.layout or _layout_for(dev.description) or DEFAULT_LAYOUT
        handle = ctypes.c_void_p()
        status = lib.FT_Open(dev.index, ctypes.byref(handle))
        if status != _FT_OK:
            busy = " (in use by another program?)" if dev.opened else ""
            raise RuntimeError(
                f"cannot open FTDI channel {dev.description!r}{busy}: D2XX status {status}"
            )
        self._lib, self._handle = lib, handle
        try:
            self._setup_mpsse(layout)
            self._identify()
        except Exception:
            self._handle = None
            _release(lib, handle)
            raise
        ch = _OpenChannel(lib, handle, dev)
        ch.idcode, ch.ir_length = self.idcode, self.ir_length
        ch.family, ch.actual_tck_hz = self.family, self.actual_tck_hz
        return ch

    def close(self) -> None:
        with _OPEN_CHANNELS_LOCK:
            ch, self._channel = self._channel, None
            self._handle = None
            if ch is None:
                return
            ch.users -= 1
            if ch.users > 0:
                return
            _OPEN_CHANNELS.remove(ch)
            with ch.lock:
                _release(ch.lib, ch.handle)

    @property
    def opened_device(self) -> str | None:
        """The connected device, for session labels: IDCODE and family."""
        if self.idcode is None:
            return None
        family = f" ({self.family})" if self.family else ""
        return f"IDCODE 0x{self.idcode:08x}{family}"

    def __enter__(self) -> "FtdiMpsseTransport":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _call(self, name: str, *args) -> None:
        status = getattr(self._lib, name)(self._handle, *args)
        if status != _FT_OK:
            raise RuntimeError(f"{name} failed: D2XX status {status}")

    def _setup_mpsse(self, layout: tuple[int, int]) -> None:
        self._call("FT_ResetDevice")
        self._call("FT_SetUSBParameters", 65536, 65536)
        self._call("FT_SetChars", 0, 0, 0, 0)
        self._call("FT_SetTimeouts", self.timeout_ms, self.timeout_ms)
        self._call("FT_SetLatencyTimer", 1)
        self._call("FT_SetFlowControl", 0x0100, 0, 0)  # RTS/CTS, per AN_135
        self._call("FT_SetBitMode", 0, 0)
        self._call("FT_SetBitMode", 0, 2)  # MPSSE
        self._call("FT_Purge", 3)
        # An invalid opcode must come back as 0xFA <opcode>: MPSSE is in sync.
        self._write(bytes((0xAA, _SEND_IMMEDIATE)))
        echo = self._read(2)
        if echo != b"\xfa\xaa":
            raise RuntimeError(f"MPSSE did not sync (got {echo.hex()})")
        divisor = max(0, min(0xFFFF, round(30e6 / self.tck_hz) - 1))
        self.actual_tck_hz = 30e6 / (divisor + 1)
        value, direction = layout
        self._write(bytes((
            0x8A, 0x97, 0x8D,                       # 60 MHz base, no adaptive / 3-phase
            0x86, divisor & 0xFF, divisor >> 8,     # TCK = 30 MHz / (divisor + 1)
            0x80, value & 0xFF, direction & 0xFF,   # ADBUS value / direction
            0x85,                                   # loopback off
        )))

    def _write(self, data: bytes) -> None:
        written = ctypes.c_ulong()
        self._call("FT_Write", data, len(data), ctypes.byref(written))
        if written.value != len(data):
            raise RuntimeError(f"FTDI write short: {written.value} of {len(data)} bytes")

    def _read(self, n: int) -> bytes:
        if n == 0:
            return b""
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_ulong()
        self._call("FT_Read", buf, n, ctypes.byref(got))
        if got.value != n:
            raise RuntimeError(
                f"FTDI read timed out: {got.value} of {n} bytes (adapter unplugged "
                "or held by another program?)"
            )
        return buf.raw[:n]

    def _flush(self, batch: _Batch) -> list[int]:
        if not batch.cmd:
            return []
        if self._handle is None:
            raise RuntimeError("not connected — call connect() first")
        self._write(bytes(batch.cmd) + bytes((_SEND_IMMEDIATE,)))
        return batch.decode(self._read(batch.read_bytes))

    # -- chain discovery -----------------------------------------------------

    def _identify(self) -> None:
        batch = _Batch()
        batch.reset()
        width = 32 * (self.MAX_DEVICES + 1)
        batch.scan(False, (1 << width) - 1, width, True)
        (chain,) = self._flush(batch)
        idcodes = self._parse_idcodes(chain, width)
        if len(idcodes) != 1:
            found = ", ".join(
                f"0x{c:08x}" if c is not None else "BYPASS" for c in idcodes
            )
            raise RuntimeError(
                f"FtdiMpsseTransport supports one device on the JTAG chain; "
                f"found {len(idcodes)}: {found}"
            )
        self.idcode = idcodes[0]
        self.ir_length = self._measure_ir_length()
        batch = _Batch()
        batch.reset()  # back to IDCODE / BYPASS after the IR probe
        self._flush(batch)
        self.family = (
            family_from_idcode(self.idcode, self.ir_length)
            if self.idcode is not None else None
        )

    def _apply_family_defaults(self) -> None:
        """IR table and burst default from the detected family, unless given."""
        if not self._ir_table_given:
            if self.family is None:
                code = f"0x{self.idcode:08x}" if self.idcode is not None else "none"
                raise RuntimeError(
                    f"unknown JTAG device (IDCODE {code}, IR length "
                    f"{self.ir_length}); pass ir_table=..."
                )
            self.ir_table = dict(_FAMILY_IR_TABLES[self.family])
        if self._burst_arg is None:
            self.burst = _FAMILY_BURST.get(self.family or "", False)

    @staticmethod
    def _parse_idcodes(chain: int, width: int) -> list[int | None]:
        """Split the DR chain read after reset into IDCODEs (``None`` for a
        device in BYPASS); the all-ones fill marks the end."""
        if chain == 0:
            raise RuntimeError("JTAG TDO reads all zeros: no device or TDO stuck low")
        codes: list[int | None] = []
        i = 0
        while i < width:
            if (chain >> i) & 1:
                if i + 32 > width:
                    break
                code = (chain >> i) & 0xFFFFFFFF
                if code == 0xFFFFFFFF:
                    break
                codes.append(code)
                i += 32
            else:
                codes.append(None)
                i += 1
        if not codes:
            raise RuntimeError("JTAG TDO reads all ones: no device or TDO stuck high")
        return codes

    def _measure_ir_length(self) -> int:
        """Fill the IR with ones, then time a single zero through it."""
        width, mark = 256, 128
        pattern = ((1 << width) - 1) & ~(1 << mark)
        batch = _Batch()
        batch.scan(True, pattern, width, True)
        (out,) = self._flush(batch)
        for j in range(mark + 1, width):
            if not (out >> j) & 1:
                return j - mark
        raise RuntimeError("could not measure the JTAG IR length")

    # -- scans -----------------------------------------------------------------

    def _run_scans(self, ops: list[ScanOp]) -> list[int]:
        if self.ir_length is None:
            raise RuntimeError("not connected — call connect() first")
        out: list[int] = []
        with self._io_lock:
            batch = _Batch()
            for op in ops:
                kind = op[0]
                if kind == "ir":
                    chain = op[1]
                    if chain not in self.ir_table:
                        raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
                    batch.scan(True, self.ir_table[chain], self.ir_length, False)
                elif kind == "dr":
                    _, value, width, capture = op
                    batch.scan(False, value, width, capture)
                elif kind == "idle":
                    batch.idle(op[1])
                else:
                    raise ValueError(f"unknown scan op {op!r}")
                if (
                    len(batch.cmd) >= self._FLUSH_CMD_BYTES
                    or batch.read_bytes >= self._FLUSH_READ_BYTES
                ):
                    out.extend(self._flush(batch))
                    batch = _Batch()
            out.extend(self._flush(batch))
        return out

    # -- Transport API -----------------------------------------------------------

    def select_chain(self, chain: int) -> None:
        if self.ir_table and chain not in self.ir_table:
            raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
        self._active_chain = chain

    @staticmethod
    def _frame(addr: int, data: int, write: bool) -> int:
        return (int(write) << 48) | ((addr & 0xFFFF) << 32) | (data & 0xFFFFFFFF)

    def read_reg(self, addr: int) -> int:
        frame = self._frame(addr, 0, False)
        (value,) = self._run_scans([
            ("ir", self._active_chain),
            ("dr", frame, self.DR_BITS, False),
            ("idle", self.READ_IDLE_CYCLES),
            ("dr", frame, self.DR_BITS, True),
        ])
        return value & 0xFFFFFFFF

    def write_reg(self, addr: int, value: int) -> None:
        self._run_scans([
            ("ir", self._active_chain),
            ("dr", self._frame(addr, value, True), self.DR_BITS, False),
            ("idle", self.WRITE_IDLE_CYCLES),
        ])

    def read_block(self, addr: int, words: int) -> List[int]:
        """Read *words* registers; the DATA window of a narrow core goes
        through the burst DR when ``burst`` is on."""
        burst = self._burst_block_or_none(addr, words)
        if burst is not None:
            return burst
        return self.read_window_block(addr, words)

    def read_window_block(self, addr: int, words: int) -> List[int]:
        """Pipelined register-window read, one batch per 512 words.

        Each scan captures the previous read's data and issues the next
        address; ``USER1_PIPE_PRIME_READS`` leading captures are discarded,
        as in :class:`~fcapz.transport.XilinxHwServerTransport`.
        """
        if words <= 0:
            return []
        check_data_window(addr, words, self.data_window_end)
        prime = self.USER1_PIPE_PRIME_READS
        results: List[int] = []
        for start in range(0, words, 512):
            count = min(512, words - start)
            frames = [self._frame(addr + (start + i) * 4, 0, False) for i in range(count)]
            ops: list[ScanOp] = [
                ("ir", self._active_chain),
                ("dr", frames[0], self.DR_BITS, False),
                ("idle", self.READ_IDLE_CYCLES),
            ]
            for _ in range(prime):
                ops += [("dr", frames[0], self.DR_BITS, True), ("idle", self.READ_IDLE_CYCLES)]
            for frame in frames[1:]:
                ops += [("dr", frame, self.DR_BITS, True), ("idle", self.READ_IDLE_CYCLES)]
            ops.append(("dr", self._frame(0, 0, False), self.DR_BITS, True))
            captured = self._run_scans(ops)
            if len(captured) != count + prime:
                raise BurstIntegrityError(
                    f"window read returned {len(captured)} words, expected {count + prime}"
                )
            results.extend(v & 0xFFFFFFFF for v in captured[prime:])
        return results

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        (value,) = self.raw_dr_scan_batch([(bits, width)], chain=chain)
        return value

    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        ops: list[ScanOp] = [("ir", self._active_chain if chain is None else chain)]
        for bits, width in scans:
            ops += [("dr", bits, width, True), ("idle", self.RAW_DR_IDLE_CYCLES)]
        return self._run_scans(ops)
