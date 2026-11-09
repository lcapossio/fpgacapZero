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
IDCODE manufacturer unless one is given.  It can also configure an
AMD/Xilinx 7-series FPGA (:meth:`FtdiMpsseTransport.program`).
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import os
import sys
import threading
import time
from typing import Any, List, NamedTuple

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
#: Active-low nTRST pin of known adapters, by the same description match.
ADAPTER_TRST: tuple[tuple[str, int], ...] = (("FlashPro", 0x10),)


def trst_pin_for(description: str) -> int:
    """The adapter's nTRST ADBUS mask, or 0 when it has none we know of."""
    for key, mask in ADAPTER_TRST:
        if key in description:
            return mask
    return 0


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
_READ_PINS = 0x81  # ADBUS low byte
# Not an opcode: its rejection (0xFA 0xAB) marks the end of setup replies.
_SYNC_MARK = 0xAB
# ADBUS bits of the JTAG pins (TDO is ADBUS2).
_PIN_TCK, _PIN_TDI, _PIN_TMS = 0x01, 0x02, 0x08
# Read opcode bit 2 samples TDO on the falling edge instead: a full TCK
# period after the target drove it, for cables whose TDO round trip is longer
# than half a period (the Arty A7's onboard FT2232H at 30 MHz).
_READ_FALLING = 0x04
#: Above this TCK, TDO is sampled on the falling edge unless told otherwise.
_FALLING_EDGE_ABOVE_HZ = 15_000_000

# TAP paths from Run-Test/Idle.
_IDLE_TO_SHIFT_IR = (1, 1, 0, 0)
_IDLE_TO_SHIFT_DR = (1, 0, 0)
# The last data bit leaves Shift-xR (TMS=1), then Update-xR, then Idle.
_LAST_BIT_TO_IDLE = (1, 1, 0)


class _Batch:
    """MPSSE command bytes for a run of JTAG scans, plus how to decode the
    bytes they return."""

    def __init__(self, sample_falling: bool = False) -> None:
        self.cmd = bytearray()
        self.read_bytes = 0
        # Per captured scan: (width, whole data bytes, leftover bits).
        self.captures: list[tuple[int, int, int]] = []
        edge = _READ_FALLING if sample_falling else 0
        self._bytes_inout = _DATA_BYTES_INOUT | edge
        self._bits_inout = _DATA_BITS_INOUT | edge
        self._tms_inout = _TMS_INOUT | edge

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
                op = self._bytes_inout if capture else _DATA_BYTES_OUT
                self.cmd += bytes((op, (n - 1) & 0xFF, (n - 1) >> 8))
                self.cmd += chunk.to_bytes(n, "little")
                done += n
        if rem:
            op = self._bits_inout if capture else _DATA_BITS_OUT
            bits = (value >> (nbytes * 8)) & ((1 << rem) - 1)
            self.cmd += bytes((op, rem - 1, bits))
        last = (value >> (width - 1)) & 1
        tms_value = sum(b << i for i, b in enumerate(_LAST_BIT_TO_IDLE)) | (last << 7)
        self.cmd += bytes(
            (self._tms_inout if capture else _TMS_OUT, len(_LAST_BIT_TO_IDLE) - 1, tms_value)
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


# -- AMD/Xilinx JTAG configuration -------------------------------------------

# Configuration instructions of 7-series and single-die UltraScale (UG470,
# UG570), and the status bits their IR capture carries.
_XC_CFG_IN = 0x05
_XC_JPROGRAM = 0x0B
_XC_JSTART = 0x0C
_XC_BYPASS = 0x3F
_XC_IR_INIT = 0x10  # INIT_COMPLETE: housecleaning finished
_XC_IR_DONE = 0x20
_XC_SYNC = b"\xaa\x99\x55\x66"
_XC_WRITE_IDCODE = b"\x30\x01\x80\x01"  # type-1 packet: write 1 word to IDCODE
#: Bytes with their bit order reversed: configuration data is shifted MSB first.
_BIT_REVERSE = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


class _ConfigFailed(RuntimeError):
    """Configuration did not complete, but every scan went out whole, so
    the adapter and TAP are in a known state."""


def read_xilinx_bitstream(path: str) -> tuple[bytes, str | None]:
    """Return the configuration data of a ``.bit`` or raw ``.bin`` file and
    the part the ``.bit`` header names (``None`` for ``.bin``)."""
    with open(path, "rb") as f:
        raw = f.read()
    data, part = raw, None
    if raw[:2] == b"\x00\x09":
        # .bit: a 9-byte magic field, 0x0001, then keyed fields; 'e' holds the
        # configuration data with a 4-byte length, the others a 2-byte one.
        pos = 2 + 9 + 2
        fields: dict[str, bytes] = {}
        while pos < len(raw):
            key = chr(raw[pos])
            if key == "e":
                n = int.from_bytes(raw[pos + 1:pos + 5], "big")
                data = raw[pos + 5:pos + 5 + n]
                if len(data) != n:
                    raise ValueError(f"{path}: bitstream truncated ({len(data)} of {n} bytes)")
                break
            n = int.from_bytes(raw[pos + 1:pos + 3], "big")
            fields[key] = raw[pos + 3:pos + 3 + n]
            pos += 3 + n
        else:
            raise ValueError(f"{path}: .bit header has no configuration data field")
        if "b" in fields:
            part = fields["b"].rstrip(b"\0").decode("ascii", errors="replace")
    if _XC_SYNC not in data[:1024]:
        raise ValueError(
            f"{path}: no AMD/Xilinx sync word (0xAA995566) near the start; not a "
            ".bit or a raw, unswapped .bin bitstream"
        )
    return data, part


def bitstream_idcode(data: bytes) -> int | None:
    """The IDCODE a bitstream checks the device against, or ``None``."""
    i = data.find(_XC_WRITE_IDCODE, data.find(_XC_SYNC))
    if i < 0 or i + 8 > len(data):
        return None
    return int.from_bytes(data[i + 4:i + 8], "big")


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
        self.sample_falling = False


_OPEN_CHANNELS: list[_OpenChannel] = []
_OPEN_CHANNELS_LOCK = threading.Lock()


def _find_open_channel(device: str | None) -> _OpenChannel | None:
    if device is None:
        return _OPEN_CHANNELS[0] if len(_OPEN_CHANNELS) == 1 else None
    for ch in _OPEN_CHANNELS:
        if device in (ch.adapter.description, ch.adapter.serial):
            return ch
    return None


def _in_one_session(method):
    """Bind a top-level transport call to the session it started under.

    A call that runs several batches (a window read, a burst after its
    ``SAMPLE_W`` read in :meth:`read_block`) must not finish on a session that :meth:`connect`
    started after a :meth:`~FtdiMpsseTransport.cancel` while it sat between
    batches: it fails at its next write instead.  Nested calls keep the
    outermost call's session.
    """

    @functools.wraps(method)
    def call(self, *args, **kwargs):
        local = self._call_local
        if getattr(local, "session", None) is not None:
            return method(self, *args, **kwargs)
        local.session = self._session_count
        try:
            return method(self, *args, **kwargs)
        finally:
            local.session = None

    return call


class FtdiMpsseTransport(_ScanBurstMixin, Transport):
    """fcapz JTAG transport on an FTDI MPSSE adapter (D2XX driver).

    ``device`` names the adapter channel by its D2XX description (for
    example ``"Embedded FlashPro5 A"``) or serial; by default the single
    known JTAG adapter's channel A is used.  ``ir_table`` defaults to the
    family read from the device IDCODE: PolarFire (``0x20`` / ``0x21``),
    AMD/Xilinx 7-series and single-die UltraScale (``0x02`` / ``0x03`` /
    ``0x22`` / ``0x23``) or Gowin.  ``burst`` defaults to that
    family's wrapper default (on for PolarFire and AMD/Xilinx, off for
    Gowin).  ``layout`` overrides the adapter's ``(ADBUS value, direction)``.
    ``tdo_sample_edge`` is ``"rising"`` or ``"falling"``; by default TDO is
    sampled on the rising edge up to 15 MHz and on the falling edge above,
    where a cable's TDO round trip can exceed half a TCK period (the Arty
    A7 reads a shifted IDCODE at 30 MHz on the rising edge).

    ``bitfile`` programs an AMD/Xilinx 7-series FPGA with that ``.bit`` or
    ``.bin`` at connect (see :meth:`program`), only when this transport opens
    the channel: one joining a channel another transport holds never
    reprograms the FPGA under it.

    Transports on the same channel in one process share its handle (the
    first one's clock, layout and sample edge apply); the channel closes
    with the last.
    """

    READ_IDLE_CYCLES = 20
    WRITE_IDLE_CYCLES = 8
    RAW_DR_IDLE_CYCLES = 8
    USER1_PIPE_PRIME_READS = 3
    MAX_DEVICES = 8
    #: TCKs in Run-Test/Idle after JSTART, for the startup sequence (UG470
    #: asks for at least 2000).
    STARTUP_IDLE_CYCLES = 4000
    #: TCKs in Run-Test/Idle between configuration status polls.
    STATUS_POLL_IDLE_CYCLES = 1000
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
        tdo_sample_edge: str | None = None,
        bitfile: str | None = None,
    ):
        if not 1_000 <= tck_hz <= 30_000_000:
            raise ValueError(f"tck_hz must be 1 kHz..30 MHz, got {tck_hz}")
        if tdo_sample_edge not in (None, "rising", "falling"):
            raise ValueError(
                f"tdo_sample_edge must be 'rising' or 'falling', got {tdo_sample_edge!r}"
            )
        self.tdo_sample_edge = tdo_sample_edge
        #: Set from the clock by connect(), or taken from a shared channel.
        self.sample_falling = False
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
        self.bitfile = bitfile
        #: :meth:`cancel` counts up; a session started at another count is
        #: cancelled.
        self._cancel_count = 0
        self._session_count = 0
        #: The session count a thread's top-level call started under (see
        #: :func:`_in_one_session`).
        self._call_local = threading.local()
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
        #: ``(ADBUS value, direction)`` set up by :meth:`open_pins`.
        self.pin_layout: tuple[int, int] | None = None
        #: Set by :meth:`open_pins`: whether the MPSSE pin commands work
        #: (``0x80`` write, ``0x81`` read).  False on FT2232-compatible
        #: adapters that implement only the clocked commands.
        self.gpio: bool | None = None

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        with self._new_session():
            self._connect()

    def _connect(self) -> None:
        count = self._cancel_count  # a cancel() while this waits cancels it
        with _OPEN_CHANNELS_LOCK:
            if self._channel is not None:
                if not self._cancelled:
                    return
                # A cancelled session: let its call in flight end (it fails
                # at its next write; a read already waiting ends within the
                # D2XX timeout, as close() may wait), then start a new one.
                with self._io_lock:
                    self._detach(retire=False)  # already cancelled
            self._session_count = count
            ch = _find_open_channel(self.device)
            opened = ch is None
            if opened:
                ch = self._open_channel()
            ch.users += 1
            self._channel = ch
            self._lib, self._handle, self.adapter = ch.lib, ch.handle, ch.adapter
            self._io_lock = ch.lock
            self.idcode, self.ir_length = ch.idcode, ch.ir_length
            self.family, self.actual_tck_hz = ch.family, ch.actual_tck_hz
            self.sample_falling = ch.sample_falling
            # The FPGA may hold another bitstream than on a past connection.
            self._forget_hub_state()
            try:
                self._apply_family_defaults()
                if opened and self.bitfile:
                    # Before the channel is published: no transport joins
                    # while the FPGA is being configured.
                    self._program(self._load_bitstream(self.bitfile), self.bitfile)
                if self._cancelled:
                    raise RuntimeError("FTDI transport cancelled; reconnect")
            except BaseException:
                self._channel = self._handle = None
                ch.users -= 1
                if opened:
                    _release(ch.lib, ch.handle)
                raise
            if opened:
                _OPEN_CHANNELS.append(ch)

    def _open_mpsse(self) -> tuple[Any, ctypes.c_void_p, FtdiDevice, tuple[int, int]]:
        """Open the device and put it in MPSSE mode: ``(lib, handle, device,
        layout)``, with ``_lib``/``_handle`` set.  Released again on failure."""
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
        except Exception:
            self._handle = None
            _release(lib, handle)
            raise
        return lib, handle, dev, layout

    def _open_channel(self) -> _OpenChannel:
        """Open, set up and identify a channel no transport holds yet."""
        lib, handle, dev, _layout = self._open_mpsse()
        try:
            self._identify()
        except Exception:
            self._handle = None
            _release(lib, handle)
            raise
        ch = _OpenChannel(lib, handle, dev)
        ch.idcode, ch.ir_length = self.idcode, self.ir_length
        ch.family, ch.actual_tck_hz = self.family, self.actual_tck_hz
        ch.sample_falling = self.sample_falling
        return ch

    def open_pins(self) -> tuple[int, int]:
        """Open the channel for code that drives the JTAG pins itself.

        Sets up MPSSE like :meth:`connect` but does not scan the chain, so any
        chain works, and the channel is not shared: no transport in this
        process can join it.  Drive it with :meth:`exchange`; :meth:`close`
        releases it.  Returns the ``(ADBUS value, direction)`` layout in
        force, and sets :attr:`gpio`.  For ``fcapz openocd-bridge``.
        """
        with self._new_session():
            return self._open_pins()

    def _open_pins(self) -> tuple[int, int]:
        count = self._cancel_count  # a cancel() while this waits cancels it
        with _OPEN_CHANNELS_LOCK:
            if self._channel is not None:
                raise RuntimeError("this transport already holds its channel")
            self._session_count = count
            # A pin session reaches no core: nothing to claim or release.
            self._forget_hub_state()
            lib, handle, dev, layout = self._open_mpsse()
            ch = _OpenChannel(lib, handle, dev)
            ch.users = 1
            self._channel, self.adapter = ch, dev
            self._io_lock = ch.lock
            self.pin_layout = layout
        try:
            self.gpio = self._gpio_works(layout)
        except Exception:
            self.close()
            raise
        return layout

    @_in_one_session
    def exchange(self, commands: bytes, reply_bytes: int) -> bytes:
        """Send raw MPSSE *commands*, then read *reply_bytes* bytes of reply.

        For a channel opened with :meth:`open_pins`; *commands* must end with
        a send-immediate (``0x87``) when a reply is expected.
        """
        lock = self._io_lock
        with lock:
            if lock is not self._io_lock:
                # Waited on a channel that a reopen has since replaced.
                raise RuntimeError("FTDI transport reconnected; call again")
            if commands:
                self._write(commands)
            return self._read(reply_bytes)

    def close(self) -> None:
        ch = self._channel
        if ch is not None and not self._cancelled:
            # Clear this session's MGR_OWNER token, as the other backends do.
            # Under the channel lock, so the owner check and the clear are one
            # unit against a peer's claim and against program(), which
            # forgets the claims it voids.  Bounded: a close does not wait
            # out a hung call.
            if ch.lock.acquire(timeout=max(1.0, self.timeout_ms / 1000)):
                try:
                    if self._channel is ch:
                        self._release_ownership_on_close()
                finally:
                    ch.lock.release()
        else:
            # A cancelled session can no longer write: its token stays.
            self.__dict__.pop("_fcapz_owned_managers", None)
        with _OPEN_CHANNELS_LOCK:
            self._detach()

    def _detach(self, *, retire: bool = True) -> None:
        """:meth:`close`, with ``_OPEN_CHANNELS_LOCK`` held.

        With *retire* the session ends too, in the same locked step: a call
        in flight on another thread fails at its next write instead of
        carrying on after a later :meth:`connect` (which takes the same
        lock).  Waits for the channel lock before the handle goes, so a
        write/read pair in flight ends first: a reply left unread would be
        taken by the next transport on the channel.
        """
        if retire:
            self._cancel_count += 1
        ch = self._channel
        if ch is None:
            self._handle = None
            return
        with ch.lock:
            self._channel = None
            self._handle = None
            ch.users -= 1
            if ch.users > 0:
                return
            if ch in _OPEN_CHANNELS:  # an open_pins() channel never is
                _OPEN_CHANNELS.remove(ch)
            _release(ch.lib, ch.handle)

    def cancel(self) -> None:
        """Abort the call in flight from another thread, without a lock.

        The call stops at its next USB write (a read already waiting ends
        within the D2XX timeout), with nothing half sent, so other
        transports on the channel carry on.  Programming stops within
        about a quarter second of TCK and closes the channel.  This
        transport then refuses I/O until :meth:`close` or :meth:`connect`.
        """
        self._cancel_count += 1

    @contextlib.contextmanager
    def _new_session(self):
        """Run a connect outside any call of the calling thread bound by
        :func:`_in_one_session`: its I/O belongs to the session it starts."""
        local = self._call_local
        outer = getattr(local, "session", None)
        local.session = None
        try:
            yield
        finally:
            local.session = outer

    @property
    def _cancelled(self) -> bool:
        """Whether the current session has been cancelled."""
        return self._session_count != self._cancel_count

    @property
    def _call_cancelled(self) -> bool:
        """Whether the session the calling thread's top-level call started
        under (see :func:`_in_one_session`) has been cancelled; outside such
        a call, :attr:`_cancelled`."""
        count = getattr(self._call_local, "session", None)
        if count is None:
            count = self._session_count
        return count != self._cancel_count

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
        # 60 MHz base, no adaptive clocking, no 3-phase: H-series opcodes.  A
        # full-speed FT2232C/D rejects each one (0xFA <opcode>) and clocks
        # from 6 MHz.  Read their replies up to a marker opcode, so none is
        # left to be taken for a scan's data.
        self._write(bytes((0x8A, 0x97, 0x8D, _SYNC_MARK, _SEND_IMMEDIATE)))
        rejected = self._read_rejections(_SYNC_MARK, limit=3)
        base_hz = 6e6 if 0x8A in rejected else 30e6
        divisor = max(0, min(0xFFFF, round(base_hz / self.tck_hz) - 1))
        # The TCK the divisor programs.  An FT2232-compatible clone can
        # accept the opcodes and still run a clock of its own.
        self.actual_tck_hz = base_hz / (divisor + 1)
        if self.tdo_sample_edge is None:
            self.sample_falling = self.actual_tck_hz > _FALLING_EDGE_ABOVE_HZ
        else:
            self.sample_falling = self.tdo_sample_edge == "falling"
        value, direction = layout
        self._write(bytes((
            0x86, divisor & 0xFF, divisor >> 8,     # TCK = base / (divisor + 1)
            0x80, value & 0xFF, direction & 0xFF,   # ADBUS value / direction
            0x85,                                   # loopback off
        )))

    def _read_rejections(self, mark: int, limit: int) -> list[int]:
        """Read ``0xFA <opcode>`` replies up to the one for *mark*; return
        the other rejected opcodes (at most *limit* of them)."""
        rejected: list[int] = []
        while True:
            echo = self._read(2)
            if echo[0] != 0xFA or (echo[1] != mark and len(rejected) == limit):
                raise RuntimeError(f"unexpected MPSSE setup reply {echo.hex()}")
            if echo[1] == mark:
                return rejected
            rejected.append(echo[1])

    def _gpio_works(self, layout: tuple[int, int]) -> bool:
        """Whether ADBUS reads (0x81) return the levels ADBUS writes (0x80)
        drive.

        Some FT2232-compatible adapters ignore the writes and answer the
        reads with a constant.  This drives TMS and TDI both ways with TCK
        held low, so the TAP sees no clock, then restores the layout's
        levels.
        """
        value, direction = layout
        idle = value & ~(_PIN_TCK | _PIN_TDI | _PIN_TMS) & 0xFF
        both = _PIN_TDI | _PIN_TMS
        reply = self.exchange(bytes((
            0x80, idle | both, direction, 0x81,
            0x80, idle, direction, 0x81,
            0x80, value & 0xFF, direction, _SEND_IMMEDIATE,
        )), 2)
        mask = _PIN_TCK | both
        return reply[0] & mask == both and reply[1] & mask == 0

    def _write(self, data: bytes) -> None:
        if self._call_cancelled:
            raise RuntimeError("FTDI transport cancelled; reconnect")
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
        batch = _Batch(self.sample_falling)
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
        batch = _Batch(self.sample_falling)
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
        batch = _Batch(self.sample_falling)
        batch.scan(True, pattern, width, True)
        (out,) = self._flush(batch)
        for j in range(mark + 1, width):
            if not (out >> j) & 1:
                return j - mark
        raise RuntimeError("could not measure the JTAG IR length")

    # -- scans -----------------------------------------------------------------

    @_in_one_session
    def _run_scans(self, ops: list[ScanOp]) -> list[int]:
        if self.ir_length is None:
            raise RuntimeError("not connected — call connect() first")
        out: list[int] = []
        lock = self._io_lock
        with lock:
            if lock is not self._io_lock:
                # Waited on a channel that a reconnect has since replaced.
                raise RuntimeError("FTDI transport reconnected; call again")
            batch = _Batch(self.sample_falling)
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
                    batch = _Batch(self.sample_falling)
            out.extend(self._flush(batch))
        return out

    # -- configuration -----------------------------------------------------------

    @_in_one_session
    def program(self, bitfile: str, *, timeout_s: float = 2.0) -> None:
        """Configure an AMD/Xilinx 7-series FPGA with *bitfile* over JTAG.

        Takes a Vivado ``.bit`` or a raw ``.bin``.  Follows UG470's JTAG
        sequence: JPROGRAM, wait for housecleaning (INIT_COMPLETE), shift
        the bitstream through CFG_IN, JSTART, then wait for DONE.  A
        bitstream built for another part is refused before the FPGA is
        cleared.  Every core on the FPGA is lost, so this is refused while
        other transports share the channel.  If a USB transfer fails
        partway, the adapter may be left mid-command, so the channel is
        closed: connect again.  :meth:`cancel` from another thread stops it
        within about a quarter second of TCK, closing the channel too.
        *timeout_s* bounds each of the two waits.
        Single-die UltraScale shares the IR table and this sequence (UG570)
        but is not hardware-validated.
        """
        ch = self._channel
        if self._handle is None or ch is None or self.ir_length is None:
            raise RuntimeError("not connected — call connect() first")
        data = self._load_bitstream(bitfile)  # checked against this channel's device
        with _OPEN_CHANNELS_LOCK:  # no transport joins while it runs
            if self._channel is not ch or self._handle is None:
                raise RuntimeError(
                    "the transport disconnected or reconnected while the "
                    "bitstream loaded; call program() again"
                )
            if self._call_cancelled:
                raise RuntimeError("FTDI transport cancelled; reconnect")
            if ch.users > 1:
                raise RuntimeError(
                    f"cannot program: {ch.users - 1} other transport(s) share "
                    "this FTDI channel and would lose their cores; close them first"
                )
            try:
                self._program(data, bitfile, timeout_s)
            except _ConfigFailed:
                raise
            except BaseException:
                # MPSSE may be mid-command: closed before the lock goes, so
                # no transport joins it.  A cancel already ended the session;
                # retiring it again would cancel the connect() that waits to
                # recover it.
                self._detach(retire=not self._cancelled)
                raise

    def _load_bitstream(self, bitfile: str) -> bytes:
        """*bitfile*'s configuration data, checked against the device."""
        if self.family != "xilinx7":
            raise RuntimeError(
                "programming over FTDI supports AMD/Xilinx 7-series only; this "
                f"device is {self.opened_device}"
            )
        data, part = read_xilinx_bitstream(bitfile)
        want = bitstream_idcode(data)
        if want is not None and self.idcode is not None and (want ^ self.idcode) & 0x0FFFFFFF:
            built = f" ({part})" if part else ""
            raise RuntimeError(
                f"{bitfile} is built for IDCODE 0x{want:08x}{built}; the device "
                f"reads 0x{self.idcode:08x}"
            )
        return data

    def _program(self, data: bytes, bitfile: str, timeout_s: float = 2.0) -> None:
        """The UG470 sequence for :meth:`program`.  The FPGA not clearing or
        DONE staying low raises :class:`_ConfigFailed` with the TAP reset;
        any other exception may leave MPSSE mid-command."""
        with self._io_lock:
            try:
                batch = _Batch(self.sample_falling)
                batch.reset()
                batch.scan(True, _XC_JPROGRAM, self.ir_length, False)
                self._flush(batch)
                self._wait_config_status(
                    lambda s: s & _XC_IR_INIT and not s & _XC_IR_DONE,
                    timeout_s,
                    "the FPGA did not finish clearing after JPROGRAM (INIT_COMPLETE "
                    "stayed low)",
                )
                batch = _Batch(self.sample_falling)
                batch.scan(True, _XC_CFG_IN, self.ir_length, False)
                self._flush(batch)
                self._shift_dr_bytes(data.translate(_BIT_REVERSE))
                batch = _Batch(self.sample_falling)
                batch.scan(True, _XC_JSTART, self.ir_length, False)
                self._flush(batch)
                self._idle(self.STARTUP_IDLE_CYCLES)
                self._wait_config_status(
                    lambda s: s & _XC_IR_DONE,
                    timeout_s,
                    f"{bitfile} did not configure the FPGA: DONE stayed low after "
                    "JSTART (a corrupt bitstream fails its CRC this way)",
                )
            except _ConfigFailed:
                self._reset_tap()
                raise
            finally:
                # The old bitstream's cores are gone: what was learned is void.
                self._forget_hub_state()
            self._reset_tap()

    def _reset_tap(self) -> None:
        batch = _Batch(self.sample_falling)
        batch.reset()  # back to IDCODE / BYPASS
        self._flush(batch)

    def _idle(self, cycles: int) -> None:
        """Clock *cycles* TCK in Run-Test/Idle, in pieces of about a quarter
        second of TCK, each waited for (see :meth:`_write_paced`)."""
        piece = max(7, int(self.actual_tck_hz * 0.25))
        for done in range(0, cycles, piece):
            batch = _Batch(self.sample_falling)
            batch.idle(min(piece, cycles - done))
            self._write_paced(bytes(batch.cmd))

    def _write_paced(self, cmd: bytes) -> None:
        """Write *cmd*, then wait until MPSSE has run it: a pin read behind
        it answers only then.  Commands that read nothing return as soon as
        the adapter buffers them, and its buffer holds seconds of clocks at
        a slow TCK, enough to delay the next read past the D2XX timeout."""
        self._write(cmd + bytes((_READ_PINS, _SEND_IMMEDIATE)))
        self._read(1)

    def _config_status(self) -> int:
        """The IR capture: configuration status bits over the fixed ``01``."""
        batch = _Batch(self.sample_falling)
        batch.scan(True, _XC_BYPASS, self.ir_length, True)
        (status,) = self._flush(batch)
        if status & 0b11 != 0b01:
            raise RuntimeError(f"IR capture 0x{status:02x} lacks the fixed 01 bits")
        return status

    def _wait_config_status(self, ready, timeout_s: float, failure: str) -> int:
        deadline = time.monotonic() + timeout_s
        while True:
            self._idle(self.STATUS_POLL_IDLE_CYCLES)
            status = self._config_status()
            if ready(status):
                return status
            if time.monotonic() > deadline:
                raise _ConfigFailed(f"{failure} (IR status 0x{status:02x})")

    def _shift_dr_bytes(self, data: bytes) -> None:
        """Shift *data* through the selected DR, each byte LSB first, from
        Run-Test/Idle back to Run-Test/Idle, without reading TDO.

        Written in pieces of about a quarter second of TCK, each waited
        for, so no write or read outlasts the D2XX timeout at a slow clock.
        """
        if not data:
            raise ValueError("no data to shift")
        piece = max(1, min(0x10000, int(self.actual_tck_hz * 0.25) // 8))
        batch = _Batch(self.sample_falling)
        batch.tms(_IDLE_TO_SHIFT_DR)
        self._write(bytes(batch.cmd))
        body, last = data[:-1], data[-1]
        for pos in range(0, len(body), piece):
            chunk = body[pos:pos + piece]
            n = len(chunk) - 1
            self._write_paced(bytes((_DATA_BYTES_OUT, n & 0xFF, n >> 8)) + chunk)
        # The last byte's top bit leaves Shift-DR with TMS.
        tms_value = sum(b << i for i, b in enumerate(_LAST_BIT_TO_IDLE)) | ((last >> 7) << 7)
        self._write(bytes((
            _DATA_BITS_OUT, 6, last & 0x7F,
            _TMS_OUT, len(_LAST_BIT_TO_IDLE) - 1, tms_value,
        )))

    # -- Transport API -----------------------------------------------------------

    def select_chain(self, chain: int) -> None:
        if self.ir_table and chain not in self.ir_table:
            raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
        self._active_chain = chain

    @staticmethod
    def _frame(addr: int, data: int, write: bool) -> int:
        return (int(write) << 48) | ((addr & 0xFFFF) << 32) | (data & 0xFFFFFFFF)

    @_in_one_session
    def read_reg(self, addr: int) -> int:
        frame = self._frame(addr, 0, False)
        (value,) = self._run_scans([
            ("ir", self._active_chain),
            ("dr", frame, self.DR_BITS, False),
            ("idle", self.READ_IDLE_CYCLES),
            ("dr", frame, self.DR_BITS, True),
        ])
        return value & 0xFFFFFFFF

    @_in_one_session
    def write_reg(self, addr: int, value: int) -> None:
        self._run_scans([
            ("ir", self._active_chain),
            ("dr", self._frame(addr, value, True), self.DR_BITS, False),
            ("idle", self.WRITE_IDLE_CYCLES),
        ])

    @_in_one_session
    def read_regs_after_write(
        self, write_addr: int, value: int, addrs: List[int]
    ) -> List[int]:
        """The write and the reads run as one scan batch."""
        # The chain is read under the transaction lock, as the base
        # implementation does: another controller may hold it with another
        # chain selected.
        with self.transaction_lock():
            ops: list[ScanOp] = [
                ("ir", self._active_chain),
                ("dr", self._frame(write_addr, value, True), self.DR_BITS, False),
                ("idle", self.WRITE_IDLE_CYCLES),
            ]
            for addr in addrs:
                frame = self._frame(addr, 0, False)
                ops += [
                    ("dr", frame, self.DR_BITS, False),
                    ("idle", self.READ_IDLE_CYCLES),
                    ("dr", frame, self.DR_BITS, True),
                ]
            return [v & 0xFFFFFFFF for v in self._run_scans(ops)]

    @_in_one_session
    def read_block(self, addr: int, words: int) -> List[int]:
        """Read *words* registers; the DATA window of a narrow core goes
        through the burst DR when ``burst`` is on."""
        burst = self._burst_block_or_none(addr, words)
        if burst is not None:
            return burst
        return self.read_window_block(addr, words)

    @_in_one_session
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

    @_in_one_session
    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        (value,) = self.raw_dr_scan_batch([(bits, width)], chain=chain)
        return value

    @_in_one_session
    def raw_dr_scan_batch(
        self, scans: list[tuple[int, int]], *, chain: int | None = None
    ) -> list[int]:
        ops: list[ScanOp] = [("ir", self._active_chain if chain is None else chain)]
        for bits, width in scans:
            ops += [("dr", bits, width, True), ("idle", self.RAW_DR_IDLE_CYCLES)]
        return self._run_scans(ops)

