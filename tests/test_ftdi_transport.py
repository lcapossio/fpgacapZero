# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""FtdiMpsseTransport against a fake D2XX library that runs the MPSSE
command stream through a bit-level JTAG TAP model.  No hardware."""

from __future__ import annotations

import ctypes
import itertools
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fcapz import ftdi_transport as ft
from fcapz.ftdi_transport import (
    FtdiDevice,
    FtdiMpsseTransport,
    _Batch,
    _pick_device,
    bitstream_idcode,
    family_from_idcode,
    read_xilinx_bitstream,
)

# -- TAP model ----------------------------------------------------------------

_NEXT = {
    # state: (next with TMS=0, next with TMS=1)
    "RESET": ("IDLE", "RESET"),
    "IDLE": ("IDLE", "SELECT_DR"),
    "SELECT_DR": ("CAPTURE_DR", "SELECT_IR"),
    "CAPTURE_DR": ("SHIFT_DR", "EXIT1_DR"),
    "SHIFT_DR": ("SHIFT_DR", "EXIT1_DR"),
    "EXIT1_DR": ("PAUSE_DR", "UPDATE_DR"),
    "PAUSE_DR": ("PAUSE_DR", "EXIT2_DR"),
    "EXIT2_DR": ("SHIFT_DR", "UPDATE_DR"),
    "UPDATE_DR": ("IDLE", "SELECT_DR"),
    "SELECT_IR": ("CAPTURE_IR", "RESET"),
    "CAPTURE_IR": ("SHIFT_IR", "EXIT1_IR"),
    "SHIFT_IR": ("SHIFT_IR", "EXIT1_IR"),
    "EXIT1_IR": ("PAUSE_IR", "UPDATE_IR"),
    "PAUSE_IR": ("PAUSE_IR", "EXIT2_IR"),
    "EXIT2_IR": ("SHIFT_IR", "UPDATE_IR"),
    "UPDATE_IR": ("IDLE", "SELECT_DR"),
}

POLARFIRE_IDCODE = 0x0F8181CF  # MPFS095T; manufacturer 0x0E7 (Microchip)
XILINX_IDCODE = 0x13631093  # manufacturer 0x049 (AMD/Xilinx), xc7a100t


class _Device:
    """One TAP with an fcapz 49-bit register core on USER1."""

    def __init__(self, idcode=POLARFIRE_IDCODE, ir_len=8, user1=0x20, idcode_ir=0x0F):
        self.idcode = idcode
        self.ir_len = ir_len
        self.user1 = user1
        self.idcode_ir = idcode_ir
        self.state = "RESET"
        self.ir = idcode_ir
        self.sr = 0
        self.sr_len = 1
        self.regs: dict[int, int] = {0x0000: 0x46430004, 0x000C: 8}
        self.read_data = 0
        self.writes: list[tuple[int, int]] = []

    def _dr_len(self):
        if self.ir == self.idcode_ir and self.idcode is not None:
            return 32
        if self.ir == self.user1:
            return 49
        return 1  # BYPASS

    def clock(self, tms: int, tdi: int) -> int:
        shifting = self.state in ("SHIFT_DR", "SHIFT_IR")
        tdo = self.sr & 1 if shifting else 0
        if self.state == "CAPTURE_DR":
            self.sr_len = self._dr_len()
            if self.ir == self.idcode_ir and self.idcode is not None:
                self.sr = self.idcode
            elif self.ir == self.user1:
                self.sr = self.read_data
            else:
                self.sr = 0
        elif self.state == "CAPTURE_IR":
            self.sr_len = self.ir_len
            self.sr = 0b01
        elif shifting:
            self.sr = (self.sr >> 1) | ((tdi & 1) << (self.sr_len - 1))
        self.state = _NEXT[self.state][tms & 1]
        if self.state == "UPDATE_IR":
            self.ir = self.sr
        elif self.state == "UPDATE_DR" and self.ir == self.user1:
            write = (self.sr >> 48) & 1
            addr = (self.sr >> 32) & 0xFFFF
            data = self.sr & 0xFFFFFFFF
            if write:
                self.regs[addr] = data
                self.writes.append((addr, data))
            else:
                self.read_data = self.regs.get(addr, addr ^ 0xA5A5)
        elif self.state == "RESET":
            self.ir = self.idcode_ir
        return tdo


class _Chain:
    """TAPs in series, listed from the TDO end: TDI enters the last one."""

    def __init__(self, *devices: _Device) -> None:
        self.devices = list(devices)

    @property
    def state(self) -> str:
        return self.devices[0].state

    @property
    def sr(self) -> int:
        return self.devices[0].sr

    def clock(self, tms: int, tdi: int) -> int:
        for dev in reversed(self.devices):
            tdi = dev.clock(tms, tdi)  # each passes on its bit from before
        return tdi


def _dap(idcode: int | None = None) -> _Device:
    """An ARM DAP: 4-bit IR; with no *idcode* it comes up in BYPASS, as a
    Zynq UltraScale+ one does."""
    return _Device(idcode=idcode, ir_len=4, user1=0x0A, idcode_ir=0x0E)


ZYNQUS_IDCODE = 0x04724093  # xck26


def _zynqus() -> _Device:
    return _Device(ZYNQUS_IDCODE, ir_len=12, user1=0x902, idcode_ir=0x249)


class _Xilinx7Device(_Device):
    """A 7-series TAP with its JTAG configuration logic (UG470): JPROGRAM
    clears the FPGA for *clear_clocks* TCKs, CFG_IN collects the bitstream,
    and JSTART plus 2000 idle TCKs raise DONE if it was *accepts*."""

    CFG_IN, JPROGRAM, JSTART = 0x05, 0x0B, 0x0C

    def __init__(self, accepts: bytes = b"", clear_clocks: int = 3000):
        super().__init__(XILINX_IDCODE, ir_len=6, user1=0x02, idcode_ir=0x09)
        self.accepts = accepts
        self.clear_clocks = clear_clocks
        self.done = self.init = True
        self.clear_left = 0
        self.cfg_bits: list[int] = []
        self.started = False
        self.startup_clocks = 0
        self.programs = 0

    #: Bits CFG_IN sees before the bitstream: one per BYPASS device on its
    #: TDI side, still holding their captured zero.
    lead = 0

    def loaded(self) -> bytes:
        bits = self.cfg_bits[self.lead:]
        return bytes(
            sum(bits[i + k] << (7 - k) for k in range(8)) for i in range(0, len(bits) - 7, 8)
        )

    def clock(self, tms: int, tdi: int) -> int:
        if self.state == "SHIFT_DR" and self.ir == self.CFG_IN:
            self.cfg_bits.append(tdi & 1)
        if self.clear_left:
            self.clear_left -= 1
            self.init = self.clear_left == 0
        if self.started and self.state == "IDLE":
            self.startup_clocks += 1
            if self.startup_clocks >= 2000 and self.loaded() == self.accepts:
                self.done = True
        before = self.state
        tdo = super().clock(tms, tdi)
        if before == "CAPTURE_IR":
            self.sr = 0b01 | (0x10 if self.init else 0) | (0x20 if self.done else 0)
        if self.state == "UPDATE_IR":
            if self.ir == self.JPROGRAM:
                self.programs += 1
                self.done = self.init = self.started = False
                self.clear_left = self.clear_clocks
                self.cfg_bits = []
            elif self.ir == self.JSTART:
                self.started, self.startup_clocks = True, 0
        return tdo


def _bitstream(idcode: int = XILINX_IDCODE & 0x0FFFFFFF, body: bytes = b"\x5a\xc3" * 20) -> bytes:
    """Configuration data shaped like Vivado's: dummy words, the bus-width
    pattern, the sync word, then an IDCODE check."""
    return (
        b"\xff" * 8 + b"\x00\x00\x00\xbb\x11\x22\x00\x44" + b"\xff" * 4
        + b"\xaa\x99\x55\x66" + b"\x30\x01\x80\x01" + idcode.to_bytes(4, "big") + body
    )


def _bit_file(data: bytes, part: str = "7a100tcsg324") -> bytes:
    """A Vivado .bit around *data*."""
    def field(key: str, text: str) -> bytes:
        value = text.encode() + b"\0"
        return key.encode() + len(value).to_bytes(2, "big") + value

    return (
        b"\x00\x09\x0f\xf0\x0f\xf0\x0f\xf0\x0f\xf0\x00\x00\x01"
        + field("a", "top;UserID=0XFFFFFFFF") + field("b", part)
        + field("c", "2026/11/02") + field("d", "12:00:00")
        + b"e" + len(data).to_bytes(4, "big") + data
    )


class _FakeD2xx:
    """D2XX entry points over an MPSSE interpreter driving ``_Device``.

    *chip* picks the MPSSE flavour: ``"h"`` (FT2232H/FT4232H), ``"d"`` (a
    full-speed FT2232D, which rejects the H-series opcodes), or ``"clone"``
    (an FT2232-compatible adapter that accepts them but has no pin I/O: it
    ignores 0x80 writes and answers 0x81 reads with 0x01, as the BRS-100's
    does).  A 0x80 write that raises TCK clocks the TAP.
    """

    def __init__(self, device=None, devices=None, chip="h"):
        self.chip = chip
        self.dev = device or _Device()
        self.devices = devices or [
            FtdiDevice(0, "Embedded FlashPro5 A", "FP5SN0A", 0x15142008, False),
            FtdiDevice(1, "Embedded FlashPro5 B", "FP5SN0B", 0x15142008, False),
        ]
        self.rx = bytearray()
        self.opens = 0
        self.closes = 0
        self.writes = 0
        self.write_clocks: list[int] = []  # TCK clocked by each write
        self.clocks = 0
        self.read_waits: list[int] = []  # TCK queued ahead of each read
        self._read_mark = 0
        self.tms = 1
        self.divisor = None
        self.pins = None  # last ADBUS value set with 0x80
        self.falling_reads = 0  # read commands that sample TDO on the falling edge

    # enumeration
    def FT_CreateDeviceInfoList(self, count):
        count._obj.value = len(self.devices)
        return 0

    def FT_GetDeviceInfoDetail(self, i, flags, typ, usb_id, loc, serial, desc, handle):
        d = self.devices[i]
        flags._obj.value = 1 if d.opened else 0
        usb_id._obj.value = d.usb_id
        serial.value = d.serial.encode()
        desc.value = d.description.encode()
        return 0

    def FT_Open(self, index, handle):
        self.opens += 1
        handle._obj.value = 0x1000 + index
        return 0

    def FT_Close(self, handle):
        self.closes += 1
        return 0

    def __getattr__(self, name):
        if name.startswith("FT_"):
            return lambda *args: 0  # setup calls: accept and ignore
        raise AttributeError(name)

    def FT_Write(self, handle, data, n, written):
        self.writes += 1
        start = self.clocks
        self._run(bytes(data[:n]))
        self.write_clocks.append(self.clocks - start)
        written._obj.value = n
        return 0

    def FT_Read(self, handle, buf, n, got):
        self.read_waits.append(self.clocks - self._read_mark)
        self._read_mark = self.clocks
        take = bytes(self.rx[:n])
        del self.rx[:n]
        ctypes.memmove(buf, take, len(take))
        got._obj.value = len(take)
        return 0

    # MPSSE
    def _clock(self, tms, tdi):
        self.clocks += 1
        self.tms = tms
        return self.dev.clock(tms, tdi)

    def _run(self, cmd: bytes) -> None:
        i = 0
        while i < len(cmd):
            op = cmd[i]
            if op in (0x3D, 0x3F, 0x6F):  # falling-edge TDO sample: same bits here
                self.falling_reads += 1
                op &= ~0x04
            if op in (0x8A, 0x97, 0x8D) and self.chip == "d":
                self.rx += bytes((0xFA, op))  # H-series only
                i += 1
            elif op in (0x8A, 0x97, 0x8D, 0x85, 0x87):
                i += 1
            elif op == 0x86:
                self.divisor = cmd[i + 1] | (cmd[i + 2] << 8)
                i += 3
            elif op == 0x80 and self.chip == "clone":
                i += 3
            elif op == 0x80:
                pins = cmd[i + 1]
                if pins & 0x01 and not (self.pins or 0) & 0x01:  # TCK rises
                    self._clock((pins >> 3) & 1, (pins >> 1) & 1)
                self.pins = pins
                i += 3
            elif op == 0x81:  # read ADBUS: the pins as last driven, and TDO
                shifting = self.dev.state in ("SHIFT_DR", "SHIFT_IR")
                tdo = 0x04 if shifting and self.dev.sr & 1 else 0
                self.rx.append(0x01 if self.chip == "clone" else (self.pins or 0) | tdo)
                i += 1
            elif op in (0x19, 0x39):
                n = (cmd[i + 1] | (cmd[i + 2] << 8)) + 1
                data = cmd[i + 3:i + 3 + n]
                for byte in data:
                    r = 0
                    for b in range(8):
                        r |= self._clock(self.tms, (byte >> b) & 1) << b
                    if op == 0x39:
                        self.rx.append(r)
                i += 3 + n
            elif op in (0x1B, 0x3B):
                n = cmd[i + 1] + 1
                byte = cmd[i + 2]
                r = 0
                for b in range(n):
                    r = (r >> 1) | (self._clock(self.tms, (byte >> b) & 1) << 7)
                if op == 0x3B:
                    self.rx.append(r)
                i += 3
            elif op in (0x4B, 0x6B):
                n = cmd[i + 1] + 1
                byte = cmd[i + 2]
                tdi = byte >> 7
                r = 0
                for b in range(n):
                    r = (r >> 1) | (self._clock((byte >> b) & 1, tdi) << 7)
                if op == 0x6B:
                    self.rx.append(r)
                i += 3
            else:
                self.rx += bytes((0xFA, op))  # bad command echo
                i += 1


class _FtdiTestCase(unittest.TestCase):
    def setUp(self):
        self.lib = _FakeD2xx()
        patcher = mock.patch.object(ft, "_load_d2xx", lambda: self.lib)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ft._OPEN_CHANNELS.clear)

    def _transport(self, **kw) -> FtdiMpsseTransport:
        t = FtdiMpsseTransport(**kw)
        t.connect()
        self.addCleanup(t.close)
        return t


class OpenPinsTests(_FtdiTestCase):
    """open_pins(): the channel for fcapz openocd-bridge, which drives the
    pins itself."""

    def test_opens_without_scanning_or_sharing(self):
        self.lib.dev = _Device(idcode=0x12345001)  # unknown to connect()
        t = FtdiMpsseTransport()
        self.addCleanup(t.close)
        self.assertEqual(t.open_pins(), ft._layout_for("Embedded FlashPro5 A"))
        self.assertEqual(t.adapter.description, "Embedded FlashPro5 A")
        self.assertIsNone(t.idcode)  # no chain scan
        self.assertEqual(self.lib.dev.state, "RESET")
        # Registered, so nothing else opens it, but no transport joins it.
        self.assertEqual([ch.exclusive for ch in ft._OPEN_CHANNELS], [True])
        for device in ("Embedded FlashPro5 A", "FP5SN0A"):
            with self.subTest(device=device):
                with self.assertRaisesRegex(RuntimeError, "held by open_pins"):
                    FtdiMpsseTransport(device=device).connect()
        # The default pick lands on the same channel: refused as well.
        with self.assertRaisesRegex(RuntimeError, "held by open_pins"):
            FtdiMpsseTransport().connect()
        self.assertEqual(self.lib.opens, 1)
        t.close()
        self.assertEqual(ft._OPEN_CHANNELS, [])
        again = FtdiMpsseTransport()
        again.open_pins()  # free again
        again.close()

    def test_refused_on_a_channel_a_transport_holds(self):
        self._transport()
        for device in (None, "FP5SN0A"):
            with self.subTest(device=device):
                with self.assertRaisesRegex(RuntimeError, "already open in this process"):
                    FtdiMpsseTransport(device=device).open_pins()
        self.assertEqual(self.lib.opens, 1)

    def test_other_channel_of_the_chip_stays_free(self):
        pins = FtdiMpsseTransport(device="Embedded FlashPro5 B")
        self.addCleanup(pins.close)
        pins.open_pins()
        self.assertEqual(self._transport().adapter.description, "Embedded FlashPro5 A")
        self.assertEqual(self.lib.opens, 2)

    def test_exchange_and_close(self):
        t = FtdiMpsseTransport()
        t.open_pins()
        reply = t.exchange(bytes((0x80, 0x0D, 0x0B, 0x81, 0x87)), 1)
        self.assertEqual(reply, bytes((0x0D,)))
        t.close()
        self.assertEqual(self.lib.closes, 1)
        t.close()  # idempotent
        self.assertEqual(self.lib.closes, 1)

    def test_cancel_while_opening_is_kept(self):
        t = FtdiMpsseTransport()
        self.addCleanup(t.close)
        errors = []

        def open_pins():
            try:
                t.open_pins()
            except RuntimeError as exc:
                errors.append(str(exc))

        with ft._OPEN_CHANNELS_LOCK:  # open_pins() waits for the registry
            opener = threading.Thread(target=open_pins)
            opener.start()
            opener.join(0.1)
            t.cancel()
        opener.join(2.0)
        self.assertEqual(len(errors), 1)
        self.assertIn("cancelled", errors[0])
        self.assertEqual(self.lib.closes, 1)  # the half-open channel is released

    def test_a_second_open_is_refused(self):
        t = FtdiMpsseTransport()
        self.addCleanup(t.close)
        t.open_pins()
        with self.assertRaisesRegex(RuntimeError, "already holds"):
            t.open_pins()

    def test_gpio_is_checked_without_clocking_the_tap(self):
        for chip, works in (("h", True), ("d", True), ("clone", False)):
            with self.subTest(chip=chip):
                self.lib = _FakeD2xx(chip=chip)
                with mock.patch.object(ft, "_load_d2xx", lambda: self.lib):
                    t = FtdiMpsseTransport()
                    layout = t.open_pins()
                    try:
                        self.assertIs(t.gpio, works)
                        self.assertEqual(self.lib.dev.state, "RESET")
                        # Levels restored (the clone never takes any).
                        self.assertEqual(self.lib.pins, layout[0] if works else None)
                        self.assertEqual(self.lib.rx, bytearray())  # nothing left over
                    finally:
                        t.close()


class SetupTests(_FtdiTestCase):
    """MPSSE setup on H-series, full-speed and clone chips."""

    def _connect_on(self, chip, **kw):
        self.lib = _FakeD2xx(chip=chip)
        with mock.patch.object(ft, "_load_d2xx", lambda: self.lib):
            return self._transport(**kw)

    def test_full_speed_chip_rejections_are_drained(self):
        # A genuine FT2232D rejects 0x8A/0x97/0x8D: their 0xFA echoes must
        # not be taken for the IDCODE scan's data.
        t = self._connect_on("d")
        self.assertEqual(t.idcode, POLARFIRE_IDCODE)
        self.assertEqual(self.lib.rx, bytearray())

    def test_full_speed_chip_clocks_from_6_mhz(self):
        t = self._connect_on("d", tck_hz=1e6)
        self.assertEqual(self.lib.divisor, 5)
        self.assertEqual(t.actual_tck_hz, 1e6)
        t.close()
        ft._OPEN_CHANNELS.clear()
        t = self._connect_on("d", tck_hz=30e6)  # the D's fastest is 6 MHz
        self.assertEqual((self.lib.divisor, t.actual_tck_hz), (0, 6e6))

    def test_high_speed_and_clone_clock_from_30_mhz(self):
        for chip in ("h", "clone"):
            with self.subTest(chip=chip):
                ft._OPEN_CHANNELS.clear()
                t = self._connect_on(chip, tck_hz=1e6)
                self.assertEqual(self.lib.divisor, 29)
                self.assertEqual(t.actual_tck_hz, 1e6)
                self.assertEqual(t.idcode, POLARFIRE_IDCODE)
                t.close()

    def test_unexpected_setup_reply_fails_cleanly(self):
        lib = _FakeD2xx()
        run = lib._run

        def garbled(cmd):
            run(cmd)
            if 0xAB in cmd:
                lib.rx[:0] = b"\x12\x34"
        lib._run = garbled
        with mock.patch.object(ft, "_load_d2xx", lambda: lib):
            with self.assertRaisesRegex(RuntimeError, "unexpected MPSSE setup reply 1234"):
                FtdiMpsseTransport().connect()
        self.assertEqual(lib.closes, 1)


class ConnectTests(_FtdiTestCase):
    def test_identifies_polarfire_and_defaults(self):
        t = self._transport()
        self.assertEqual(t.adapter.description, "Embedded FlashPro5 A")
        self.assertEqual(t.idcode, POLARFIRE_IDCODE)
        self.assertEqual(t.ir_length, 8)
        self.assertEqual(t.family, "polarfire")
        self.assertEqual(t.ir_table, {1: 0x20, 2: 0x21})
        self.assertTrue(t.burst)
        self.assertEqual(t.opened_device, f"IDCODE 0x{POLARFIRE_IDCODE:08x} (polarfire)")
        self.assertEqual(self.lib.dev.state, "IDLE")

    def test_clock_divisor(self):
        t = self._transport(tck_hz=6e6)
        self.assertEqual(self.lib.divisor, 4)
        self.assertEqual(t.actual_tck_hz, 6e6)

    def test_identifies_xilinx_ir6(self):
        self.lib.dev = _Device(XILINX_IDCODE, ir_len=6, user1=0x02, idcode_ir=0x09)
        t = self._transport()
        self.assertEqual((t.family, t.ir_length), ("xilinx7", 6))
        self.assertEqual(t.read_reg(0x0000), 0x46430004)

    def test_explicit_burst_and_ir_table_win(self):
        t = self._transport(burst=False, ir_table={1: 0x20, 2: 0x21, 3: 0x22})
        self.assertFalse(t.burst)
        self.assertEqual(t.ir_table, {1: 0x20, 2: 0x21, 3: 0x22})

    def test_unknown_device_needs_an_ir_table(self):
        self.lib.dev = _Device(idcode=0x12345001)
        with self.assertRaisesRegex(RuntimeError, "unknown JTAG device"):
            FtdiMpsseTransport().connect()
        self.assertEqual(self.lib.closes, 1)
        self.assertEqual(ft._OPEN_CHANNELS, [])

    def test_close_is_idempotent(self):
        t = self._transport()
        t.close()
        t.close()
        self.assertEqual(self.lib.closes, 1)
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            t.read_reg(0)


class RegisterTests(_FtdiTestCase):
    def test_read_and_write_registers(self):
        t = self._transport()
        self.assertEqual(t.read_reg(0x0000), 0x46430004)
        t.write_reg(0x0024, 0xDEADBEEF)
        self.assertEqual(self.lib.dev.writes, [(0x0024, 0xDEADBEEF)])
        self.assertEqual(t.read_reg(0x0024), 0xDEADBEEF)

    def test_one_usb_write_per_register_access(self):
        t = self._transport()
        before = self.lib.writes
        t.read_reg(0x000C)
        self.assertEqual(self.lib.writes - before, 1)

    def test_pipelined_window_read(self):
        t = self._transport()
        t.burst = False
        for i in range(700):
            self.lib.dev.regs[0x0100 + 4 * i] = i * 3 + 1
        self.assertEqual(t.read_block(0x0100, 700), [i * 3 + 1 for i in range(700)])

    def test_bypass_loopback(self):
        t = self._transport(ir_table={1: 0xFF})  # BYPASS: one-bit DR
        value = 0x5A5AA5A5
        self.assertEqual(t.raw_dr_scan(value, 33) & ((1 << 33) - 1), (value << 1) & ((1 << 33) - 1))

    def test_large_batch_is_flushed_in_pieces(self):
        t = self._transport()
        before = self.lib.writes
        out = t.raw_dr_scan_batch([(0, 49)] * 3000)
        self.assertEqual(len(out), 3000)
        self.assertGreater(self.lib.writes - before, 1)


class ChannelKeyTests(unittest.TestCase):
    def test_d2xx_channel_letter_comes_off_the_serial(self):
        key = ft._channel_key
        self.assertEqual(
            key(FtdiDevice(0, "Digilent USB Device B", "210319A5F2B", 0x04036010, False)),
            (0x04036010, "210319A5F2", "B"),
        )
        # Letter on the description but not the serial: the serial stays.
        self.assertEqual(
            key(FtdiDevice(0, "Dual RS232-HS A", "FT9XYZ", 0x04036010, False)),
            (0x04036010, "FT9XYZ", "A"),
        )
        # Single-channel chip: channel A, serial as is.
        self.assertEqual(
            key(FtdiDevice(0, "USB Debugger", "FT1234B", 0x04036014, False)),
            (0x04036014, "FT1234B", "A"),
        )

    def test_no_serial_no_identity(self):
        self.assertIsNone(ft._channel_key(FtdiDevice(0, "Clone A", "", 0x04036010, False)))
        self.assertIsNone(ft._channel_key(FtdiDevice(0, "Clone A", "A", 0x04036010, False)))


class SharedChannelTests(_FtdiTestCase):
    def test_joins_the_same_physical_channel_under_another_name(self):
        self._transport(device="Embedded FlashPro5 A")
        # The same channel enumerated under another description (as another
        # driver would list it): same VID/PID, serial and channel letter.
        a = self.lib.devices[0]
        self.lib.devices[0] = a._replace(description="FlashPro5 Port A", serial="FP5SN0")
        b = self._transport(device="FlashPro5 Port A")
        self.assertEqual(self.lib.opens, 1)
        self.assertEqual(b.adapter.description, "Embedded FlashPro5 A")

    def test_second_transport_shares_the_open_channel(self):
        a = self._transport()
        b = self._transport()
        self.assertEqual(self.lib.opens, 1)
        self.assertEqual(b.family, "polarfire")
        a.close()
        self.assertEqual(self.lib.closes, 0)
        self.assertEqual(b.read_reg(0x0000), 0x46430004)
        b.close()
        self.assertEqual(self.lib.closes, 1)

    def test_named_device_shares_by_description(self):
        self._transport()
        self._transport(device="Embedded FlashPro5 A")
        self.assertEqual(self.lib.opens, 1)

    def test_second_transport_takes_the_channel_sample_edge(self):
        self._transport(tck_hz=30e6)
        b = self._transport(tck_hz=6e6)
        self.assertTrue(b.sample_falling)

    def _break_reads(self):
        """The next FT_Read comes back one byte short."""
        real = self.lib.FT_Read

        def short(handle, buf, n, got):
            self.lib.FT_Read = real
            status = real(handle, buf, n, got)
            got._obj.value = max(0, got._obj.value - 1)
            return status

        self.lib.FT_Read = short

    def test_failed_transfer_breaks_the_channel_for_every_user(self):
        a = self._transport()
        b = self._transport()
        self._break_reads()
        with self.assertRaisesRegex(RuntimeError, "read timed out"):
            a.read_reg(0x0000)
        self.assertEqual(self.lib.closes, 1)  # MPSSE may be mid-command
        for t in (a, b):
            with self.assertRaisesRegex(RuntimeError, "channel broken"):
                t.read_reg(0x0000)
        # A new transport does not join the broken channel.
        c = self._transport()
        self.assertEqual(self.lib.opens, 2)
        self.assertEqual(c.read_reg(0x0000), 0x46430004)

    def test_reconnect_reopens_a_broken_channel(self):
        a = self._transport()
        b = self._transport()
        self._break_reads()
        with self.assertRaises(RuntimeError):
            a.read_reg(0x0000)
        b.connect()
        self.assertEqual(self.lib.opens, 2)
        self.assertEqual(b.read_reg(0x0000), 0x46430004)
        a.connect()  # joins the fresh channel
        self.assertEqual(self.lib.opens, 2)
        self.assertEqual(a.read_reg(0x0000), 0x46430004)
        a.close()
        b.close()
        self.assertEqual(self.lib.closes, 2)  # the broken handle once, the new once


class ProgramTests(_FtdiTestCase):
    """program(): JTAG configuration of an AMD/Xilinx 7-series FPGA."""

    def setUp(self):
        super().setUp()
        self.data = _bitstream()
        self.lib.dev = _Xilinx7Device(accepts=self.data)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _file(self, content: bytes, name: str = "design.bit") -> str:
        path = self.dir / name
        path.write_bytes(content)
        return str(path)

    def test_configures_with_a_bit_file(self):
        t = self._transport()
        t.write_reg(0x0010, 1)  # anything learned about the old image is dropped
        t.program(self._file(_bit_file(self.data)))
        dev = self.lib.dev
        self.assertEqual(dev.programs, 1)
        self.assertEqual(dev.loaded(), self.data)  # MSB of each byte first
        self.assertTrue(dev.done)
        self.assertGreaterEqual(dev.startup_clocks, 2000)
        self.assertEqual((dev.state, dev.ir), ("IDLE", dev.idcode_ir))  # left reset
        self.assertEqual(t.read_reg(0x0000), 0x46430004)

    def test_configures_with_a_raw_bin(self):
        t = self._transport()
        t.program(self._file(self.data, "design.bin"))
        self.assertTrue(self.lib.dev.done)

    def test_slow_clock_writes_in_pieces(self):
        data = self.data + b"\x00" * 1000
        self.lib.dev.accepts = data
        t = self._transport(tck_hz=10e3)  # a quarter second is 312 bytes
        writes = self.lib.writes
        t.program(self._file(data, "design.bin"))
        self.assertGreater(self.lib.writes - writes, 4)
        # The data, the startup clocks and every status poll alike: no write,
        # and no read waiting behind clocks still queued in the adapter,
        # outlasts much more than a quarter second.
        self.assertLessEqual(max(self.lib.write_clocks[writes:]), 2500 + 20)
        self.assertLessEqual(max(self.lib.read_waits[-50:]), 2600)
        self.assertTrue(self.lib.dev.done)

    def test_wrong_part_is_refused_before_clearing(self):
        t = self._transport()
        path = self._file(_bit_file(_bitstream(idcode=0x03727093), part="7k70tfbg676"))
        with self.assertRaisesRegex(RuntimeError, r"IDCODE 0x03727093 \(7k70tfbg676\)"):
            t.program(path)
        self.assertEqual(self.lib.dev.programs, 0)
        self.assertTrue(self.lib.dev.done)

    def test_done_staying_low_is_an_error(self):
        self.lib.dev.accepts = b"something else"
        self.lib.dev.clear_clocks = 10  # cleared by the first poll, whatever the load
        t = self._transport()
        with self.assertRaisesRegex(RuntimeError, r"DONE stayed low.*IR status 0x11"):
            t.program(self._file(self.data, "design.bin"), timeout_s=0.01)
        self.assertEqual(self.lib.dev.state, "IDLE")

    def test_clearing_that_never_finishes_is_an_error(self):
        self.lib.dev.clear_clocks = 10**9
        t = self._transport()
        with self.assertRaisesRegex(RuntimeError, r"did not finish clearing.*0x01\)"):
            t.program(self._file(self.data, "design.bin"), timeout_s=0.01)

    def test_other_families_are_refused(self):
        self.lib.dev = _Device()  # PolarFire
        t = self._transport()
        with self.assertRaisesRegex(RuntimeError, "7-series only.*polarfire"):
            t.program(self._file(self.data, "design.bin"))

    def test_bitfile_programs_only_when_opening_the_channel(self):
        path = self._file(self.data, "design.bin")
        a = self._transport(bitfile=path)
        self.assertEqual(self.lib.dev.programs, 1)
        self._transport(bitfile=path)  # joins a's channel: no reprogram under it
        self.assertEqual(self.lib.dev.programs, 1)
        self.assertEqual(a.read_reg(0x0000), 0x46430004)

    def test_failed_program_at_connect_releases_the_channel(self):
        t = FtdiMpsseTransport(bitfile=self._file(self.data, "design.bin"))
        clock = mock.Mock(monotonic=mock.Mock(side_effect=itertools.count(0, 10)))
        with mock.patch.object(ft, "time", clock):  # every wait times out at once
            with self.assertRaisesRegex(RuntimeError, "did not finish clearing"):
                t.connect()
        self.assertEqual(self.lib.closes, 1)
        self.assertEqual(ft._OPEN_CHANNELS, [])

    def test_no_transport_joins_while_programming_at_connect(self):
        published = []
        real = FtdiMpsseTransport._program

        def spy(t, *args, **kw):
            published.append(list(ft._OPEN_CHANNELS))
            return real(t, *args, **kw)

        with mock.patch.object(FtdiMpsseTransport, "_program", spy):
            self._transport(bitfile=self._file(self.data, "design.bin"))
        self.assertEqual(published, [[]])
        self.assertEqual(len(ft._OPEN_CHANNELS), 1)

    def test_interrupted_program_at_connect_releases_the_channel(self):
        t = FtdiMpsseTransport(bitfile=self._file(self.data, "design.bin"))
        with mock.patch.object(t, "_shift_dr_bytes", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                t.connect()
        self.assertEqual(self.lib.closes, 1)
        self.assertEqual(ft._OPEN_CHANNELS, [])

    def test_refused_while_other_transports_share_the_channel(self):
        a = self._transport()
        self._transport()
        with self.assertRaisesRegex(RuntimeError, "1 other transport"):
            a.program(self._file(self.data, "design.bin"))
        self.assertEqual(self.lib.dev.programs, 0)

    def test_reconnect_while_loading_is_refused(self):
        a = self._transport()
        real = a._load_bitstream

        def reconnect(path):
            data = real(path)  # checked against the old channel's device
            a.close()  # a moves to a new channel, maybe another FPGA
            a.connect()
            self._transport()
            return data

        with mock.patch.object(a, "_load_bitstream", reconnect):
            with self.assertRaisesRegex(RuntimeError, "reconnected while the bitstream"):
                a.program(self._file(self.data, "design.bin"))
        self.assertEqual(self.lib.dev.programs, 0)

    def test_cancel_and_reconnect_while_loading_is_refused(self):
        a = self._transport()
        peer = self._transport()  # keeps the channel object alive
        real = a._load_bitstream

        def cancel_and_rejoin(path):
            data = real(path)
            worker = threading.Thread(target=lambda: (a.cancel(), a.connect()))
            worker.start()
            worker.join(2.0)
            peer.close()  # a is alone on the same channel again
            return data

        with mock.patch.object(a, "_load_bitstream", cancel_and_rejoin):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                a.program(self._file(self.data, "design.bin"))
        self.assertEqual(self.lib.dev.programs, 0)
        self.assertEqual(a.read_reg(0x0000) & 0xFFFF, self.lib.dev.regs[0] & 0xFFFF)

    def test_cancelled_program_does_not_cancel_the_recovering_connect(self):
        t = self._transport()
        snapshot = []

        def cancel_and_snapshot(cycles):  # cancel(), then connect() starts
            t.cancel()
            snapshot.append(t._cancel_count)
            raise RuntimeError("FTDI transport cancelled; reconnect")

        with mock.patch.object(t, "_idle", cancel_and_snapshot):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                t.program(self._file(self.data, "design.bin"))
        # The detach after the cancel did not retire the session again: a
        # connect() that read the count after the cancel still works.
        self.assertEqual(t._cancel_count, snapshot[0])

    def test_cancel_stops_programming_without_waiting(self):
        t = self._transport()
        real = t._idle
        blocked = []

        def cancel_from_another_thread(cycles):
            if not blocked:  # programming holds the registry lock here
                worker = threading.Thread(target=t.cancel)
                worker.start()
                worker.join(1.0)
                blocked.append(worker.is_alive())
            return real(cycles)

        with mock.patch.object(t, "_idle", cancel_from_another_thread):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                t.program(self._file(self.data, "design.bin"))
        self.assertEqual(blocked, [False])  # cancel() returned at once
        self.assertEqual(self.lib.closes, 1)
        self.assertEqual(ft._OPEN_CHANNELS, [])

    def test_cancel_stops_scans_and_spares_peers(self):
        a = self._transport()
        b = self._transport()
        with ft._OPEN_CHANNELS_LOCK:  # takes no lock: a busy registry is fine
            a.cancel()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            a.read_reg(0x0000)
        self.assertEqual(b.read_reg(0x0000), 0x46430004)
        a.connect()  # a new session on the same channel
        self.assertEqual(a.read_reg(0x0000), 0x46430004)
        self.assertEqual(self.lib.opens, 1)

    def test_reconnect_waits_for_the_cancelled_call(self):
        a = self._transport()
        self._transport()  # a peer keeps the channel open
        a.cancel()
        held, release = threading.Event(), threading.Event()

        def call_in_flight():
            with a._io_lock:
                held.set()
                release.wait(2.0)

        flight = threading.Thread(target=call_in_flight)
        flight.start()
        held.wait(2.0)
        reconnect = threading.Thread(target=a.connect)
        reconnect.start()
        reconnect.join(0.2)
        self.assertTrue(reconnect.is_alive())  # the cancelled call ends first
        release.set()
        flight.join(2.0)
        reconnect.join(2.0)
        self.assertFalse(reconnect.is_alive())
        self.assertEqual(a.read_reg(0x0000), 0x46430004)

    def test_cancel_while_connect_waits_cancels_it(self):
        t = FtdiMpsseTransport(bitfile=self._file(self.data, "design.bin"))
        real = ft._find_open_channel

        def cancel_then_find(device):  # cancel() lands once connect() waits
            t.cancel()
            return real(device)

        with mock.patch.object(ft, "_find_open_channel", cancel_then_find):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                t.connect()
        self.assertEqual(self.lib.dev.programs, 0)
        self.assertEqual(ft._OPEN_CHANNELS, [])
        self.assertEqual(self.lib.closes, 1)

    def test_reconnect_forgets_the_old_bitstream(self):
        t = self._transport()
        t.__dict__["_fcapz_owned_managers"] = {(1, 0x0000): 7}
        t.close()
        t.connect()
        self.assertNotIn("_fcapz_owned_managers", t.__dict__)

    def test_short_write_closes_the_channel(self):
        t = self._transport()
        real = self.lib.FT_Write
        calls = itertools.count()

        def flaky(handle, data, n, written):
            status = real(handle, data, n, written)
            if next(calls) == 3:  # partway through the configuration
                written._obj.value = n - 1
            return status

        self.lib.FT_Write = flaky
        with self.assertRaisesRegex(RuntimeError, "write short"):
            t.program(self._file(self.data, "design.bin"))
        self.assertEqual(self.lib.closes, 1)  # MPSSE may be mid-command
        self.assertEqual(ft._OPEN_CHANNELS, [])
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            t.read_reg(0)
        # The session ended too: a call bound to it fails after a reconnect.
        self.assertTrue(t._cancelled)


class SessionTests(_FtdiTestCase):
    """Owner tokens and session binding across close / cancel / connect."""

    MGR = 0xF000

    def _manager(self) -> None:
        self.lib.dev.regs[self.MGR + 0x10] = 0x08  # MGR_CAPS: MGR_OWNER

    def test_close_clears_the_owner_token(self):  # BUG-283
        self._manager()
        t = self._transport()
        t._claim_manager(1, self.MGR)
        self.assertNotEqual(self.lib.dev.regs[self.MGR + 0x24], 0)
        t.close()
        self.assertEqual(self.lib.dev.regs[self.MGR + 0x24], 0)
        nxt = self._transport()
        with self.assertNoLogs("fcapz.transport", level="WARNING"):
            nxt._claim_manager(1, self.MGR)

    def test_close_spares_a_peer_token(self):
        self._manager()
        a = self._transport()
        b = self._transport()
        a._claim_manager(1, self.MGR)
        with self.assertLogs("fcapz.transport", level="WARNING"):
            b._claim_manager(1, self.MGR)
        token = self.lib.dev.regs[self.MGR + 0x24]
        a.close()
        self.assertEqual(self.lib.dev.regs[self.MGR + 0x24], token)
        b.close()
        self.assertEqual(self.lib.dev.regs[self.MGR + 0x24], 0)

    def test_cancelled_close_skips_the_release(self):
        self._manager()
        t = self._transport()
        t._claim_manager(1, self.MGR)
        t.cancel()
        with self.assertNoLogs("fcapz.transport", level="WARNING"):
            t.close()
        self.assertNotEqual(self.lib.dev.regs[self.MGR + 0x24], 0)
        self.assertEqual(self.lib.closes, 1)

    def test_multi_batch_read_does_not_resume_on_a_new_session(self):  # BUG-284
        a = self._transport()
        self._transport()  # a peer keeps the channel open
        a.burst = False
        real = a._run_scans
        batches = itertools.count()

        def cancel_and_reconnect_between_batches(ops):
            out = real(ops)
            if next(batches) == 0:
                a.cancel()
                worker = threading.Thread(target=a.connect)  # another thread
                worker.start()
                worker.join(2.0)
            return out

        with mock.patch.object(a, "_run_scans", cancel_and_reconnect_between_batches):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                a.read_window_block(0x0100, 700)  # two batches
        # The new session works, for calls that start under it.
        self.assertEqual(a.read_reg(0x0000), 0x46430004)
        self.assertEqual(len(a.read_window_block(0x0100, 700)), 700)

    def test_multi_batch_read_does_not_resume_after_a_broken_channel(self):
        a = self._transport()
        b = self._transport()
        a.burst = False
        real = a._run_scans
        batches = itertools.count()
        real_read = self.lib.FT_Read

        def short(handle, buf, n, got):
            self.lib.FT_Read = real_read
            status = real_read(handle, buf, n, got)
            got._obj.value = max(0, got._obj.value - 1)
            return status

        def break_and_reconnect_between_batches(ops):
            out = real(ops)
            if next(batches) == 0:
                self.lib.FT_Read = short
                with self.assertRaises(RuntimeError):
                    b.read_reg(0x0000)  # the peer breaks the channel
                worker = threading.Thread(target=a.connect)  # another thread
                worker.start()
                worker.join(2.0)
            return out

        with mock.patch.object(a, "_run_scans", break_and_reconnect_between_batches):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                a.read_window_block(0x0100, 700)  # two batches
        self.assertEqual(self.lib.opens, 2)
        self.assertEqual(len(a.read_window_block(0x0100, 700)), 700)

    def test_broken_channel_is_closed_before_it_is_marked(self):
        a = self._transport()
        ch = a._channel
        seen = []
        real_close = ch.io.close

        def close():
            seen.append(ch.broken)
            real_close()

        ch.io.close = close
        self.lib.FT_Write = lambda *args: 4  # D2XX status: I/O error
        with self.assertRaises(RuntimeError):
            a.read_reg(0x0000)
        self.assertEqual(seen, [None])  # not yet visible as broken
        self.assertIsNotNone(ch.broken)

    def test_call_session_is_cleared_after_each_call(self):
        t = self._transport()
        t.read_reg(0x0000)
        self.assertIsNone(getattr(t._call_local, "session", None))
        t.cancel()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            t.read_reg(0x0000)
        self.assertIsNone(getattr(t._call_local, "session", None))
        t.connect()
        self.assertEqual(t.read_reg(0x0000), 0x46430004)


    def test_close_and_reconnect_also_end_a_multi_batch_read(self):
        a = self._transport()
        self._transport()  # a peer keeps the channel open
        a.burst = False
        real = a._run_scans
        batches = itertools.count()

        def close_and_reconnect_between_batches(ops):
            out = real(ops)
            if next(batches) == 0:
                worker = threading.Thread(target=lambda: (a.close(), a.connect()))
                worker.start()
                worker.join(2.0)
            return out

        with mock.patch.object(a, "_run_scans", close_and_reconnect_between_batches):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                a.read_window_block(0x0100, 700)
        self.assertEqual(len(a.read_window_block(0x0100, 700)), 700)

    def test_close_waits_for_the_call_in_flight(self):
        a = self._transport()
        self._transport()  # a peer: a's close leaves the channel open
        held, release = threading.Event(), threading.Event()

        def call_in_flight():
            with a._io_lock:
                held.set()
                release.wait(2.0)

        flight = threading.Thread(target=call_in_flight)
        flight.start()
        held.wait(2.0)
        a.cancel()  # skips the token release: only the detach waits
        closer = threading.Thread(target=a.close)
        closer.start()
        closer.join(0.2)
        self.assertTrue(closer.is_alive())
        self.assertIsNotNone(a._handle)  # still there for the pending read
        release.set()
        flight.join(2.0)
        closer.join(2.0)
        self.assertFalse(closer.is_alive())
        self.assertIsNone(a._handle)

    def test_open_pins_forgets_unreleased_claims(self):
        self._manager()
        t = self._transport()
        t.close()
        t.__dict__["_fcapz_owned_managers"] = {(1, self.MGR)}  # left behind
        t.__dict__["_fcapz_owner_token"] = 0x1234
        t.open_pins()
        self.assertNotIn("_fcapz_owned_managers", t.__dict__)
        before = self.lib.writes
        t.close()
        self.assertEqual(self.lib.writes, before)  # no register scans

    def test_read_regs_after_write_is_one_batch(self):
        t = self._transport()
        self.lib.dev.regs[0x0104] = 0x1234
        before = self.lib.writes
        self.assertEqual(
            t.read_regs_after_write(0x0024, 7, [0x0024, 0x0104]), [7, 0x1234]
        )
        self.assertEqual(self.lib.writes - before, 1)
        self.assertEqual(t.read_regs_after_write(0x0028, 9, []), [])
        self.assertEqual(self.lib.dev.regs[0x0028], 9)

    def test_scan_waiting_on_a_replaced_channel_fails(self):
        t = self._transport()
        stale = t._io_lock
        t.close()
        t.connect()  # a new channel and lock
        current = t._io_lock
        self.assertIsNot(current, stale)
        # _run_scans reads the old lock, then a reconnect replaces it.
        lock_reads = iter([stale, current])
        with mock.patch.object(
            type(t), "_io_lock", property(lambda self: next(lock_reads)), create=True
        ):
            with self.assertRaisesRegex(RuntimeError, "reconnected"):
                t.read_reg(0x0000)
        self.assertEqual(t.read_reg(0x0000), 0x46430004)


class BitstreamFileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _write(self, content: bytes) -> str:
        path = self.dir / "f.bit"
        path.write_bytes(content)
        return str(path)

    def test_bit_header_and_raw_bin(self):
        data = _bitstream()
        self.assertEqual(
            read_xilinx_bitstream(self._write(_bit_file(data))), (data, "7a100tcsg324")
        )
        self.assertEqual(read_xilinx_bitstream(self._write(data)), (data, None))
        self.assertEqual(bitstream_idcode(data), XILINX_IDCODE & 0x0FFFFFFF)
        self.assertIsNone(bitstream_idcode(b"\xff" * 4 + b"\xaa\x99\x55\x66"))

    def test_bad_files(self):
        with self.assertRaisesRegex(ValueError, "no AMD/Xilinx sync word"):
            read_xilinx_bitstream(self._write(b"\x01\x02" * 100))
        with self.assertRaisesRegex(ValueError, "truncated"):
            read_xilinx_bitstream(self._write(_bit_file(_bitstream())[:-4]))


class SampleEdgeTests(_FtdiTestCase):
    def test_rising_edge_up_to_15_mhz(self):
        t = self._transport(tck_hz=15e6)
        self.assertFalse(t.sample_falling)
        self.assertEqual(t.read_reg(0x0000), 0x46430004)
        self.assertEqual(self.lib.falling_reads, 0)

    def test_falling_edge_above_15_mhz(self):
        t = self._transport(tck_hz=30e6)
        self.assertTrue(t.sample_falling)
        self.assertEqual(t.read_reg(0x0000), 0x46430004)
        self.assertGreater(self.lib.falling_reads, 0)

    def test_explicit_rising_at_30_mhz(self):
        self.assertFalse(self._transport(tck_hz=30e6, tdo_sample_edge="rising").sample_falling)

    def test_explicit_falling_at_6_mhz(self):
        t = self._transport(tck_hz=6e6, tdo_sample_edge="falling")
        self.assertTrue(t.sample_falling)
        self.assertEqual(t.read_reg(0x0000), 0x46430004)

    def test_rejects_unknown_edge(self):
        with self.assertRaises(ValueError):
            FtdiMpsseTransport(tdo_sample_edge="both")


class BatchTests(unittest.TestCase):
    def test_decode_round_trips_widths(self):
        for width in (1, 2, 7, 8, 9, 49, 256):
            dev = _Device(ir_len=8, user1=0x20)
            lib = _FakeD2xx(dev)
            dev.state = "IDLE"
            dev.ir = 0xFF  # BYPASS: output = input delayed one bit
            batch = _Batch()
            value = (0x9E3779B97F4A7C15 * (width + 1)) & ((1 << width) - 1)
            batch.scan(False, value, width, True)
            lib._run(bytes(batch.cmd))
            (got,) = batch.decode(bytes(lib.rx))
            self.assertEqual(got, (value << 1) & ((1 << width) - 1), width)
            self.assertEqual(dev.state, "IDLE")

    def test_rejects_zero_width(self):
        with self.assertRaises(ValueError):
            _Batch().scan(False, 0, 0, True)


class PickDeviceTests(unittest.TestCase):
    FP = [
        FtdiDevice(0, "Embedded FlashPro5 A", "SA", 0x15142008, False),
        FtdiDevice(1, "Embedded FlashPro5 B", "SB", 0x15142008, False),
    ]

    def test_default_is_the_known_channel_a(self):
        self.assertEqual(_pick_device(self.FP, None).index, 0)

    def test_named_by_description_or_serial(self):
        self.assertEqual(_pick_device(self.FP, "Embedded FlashPro5 B").index, 1)
        self.assertEqual(_pick_device(self.FP, "SB").index, 1)
        with self.assertRaisesRegex(RuntimeError, "no FTDI channel"):
            _pick_device(self.FP, "nope")

    def test_several_adapters_must_be_named(self):
        devs = self.FP + [FtdiDevice(2, "Digilent USB Device A", "D", 0x04036010, False)]
        with self.assertRaisesRegex(RuntimeError, "several"):
            _pick_device(devs, None)

    def test_busy_channels_get_a_hint(self):
        devs = [FtdiDevice(0, "", "", 0, True), FtdiDevice(1, "", "", 0, True)]
        with self.assertRaisesRegex(RuntimeError, "2 FTDI channel.*open in another program"):
            _pick_device(devs, None)


class FamilyTests(unittest.TestCase):
    def test_families(self):
        self.assertEqual(family_from_idcode(POLARFIRE_IDCODE, 8), "polarfire")
        self.assertEqual(family_from_idcode(XILINX_IDCODE, 6), "xilinx7")
        self.assertEqual(family_from_idcode(0x0000081B, 8), "gowin")
        self.assertIsNone(family_from_idcode(XILINX_IDCODE, 8))

    def test_idcode_parse_marks_bypass(self):
        chain = (POLARFIRE_IDCODE << 1) | 0  # BYPASS device first, then IDCODE
        width = 32 * 3
        chain |= ((1 << width) - 1) & ~((1 << 33) - 1)
        self.assertEqual(
            FtdiMpsseTransport._parse_idcodes(chain, width), [None, POLARFIRE_IDCODE]
        )

    def test_idcode_parse_stuck_lines(self):
        with self.assertRaisesRegex(RuntimeError, "all zeros"):
            FtdiMpsseTransport._parse_idcodes(0, 64)
        with self.assertRaisesRegex(RuntimeError, "all ones"):
            FtdiMpsseTransport._parse_idcodes((1 << 64) - 1, 64)


class ChainTests(_FtdiTestCase):
    """A JTAG chain of several devices: one is scanned, the others are kept
    in BYPASS."""

    def _check_core(self, t: FtdiMpsseTransport, dev: _Device) -> None:
        t.write_reg(0x0010, 0x1234ABCD)
        self.assertEqual(dev.writes, [(0x0010, 0x1234ABCD)])
        self.assertEqual(t.read_reg(0x0010), 0x1234ABCD)
        self.assertEqual(t.read_reg(0x0000), 0x46430004)
        self.assertEqual(
            t.read_window_block(0x0000, 3), [0x46430004, 0x0004 ^ 0xA5A5, 0x0008 ^ 0xA5A5]
        )

    def _assert_bypassed(self, *devices: _Device) -> None:
        for dev in devices:
            self.assertEqual(dev.ir, (1 << dev.ir_len) - 1)
            self.assertEqual(dev.writes, [])

    def test_zynqus_behind_a_dap_in_bypass(self):
        # The KV260's chain: the DAP nearest TDO, reading BYPASS after reset.
        dap, pl = _dap(), _zynqus()
        self.lib.dev = _Chain(dap, pl)
        t = self._transport()
        self.assertEqual(t.chain, [(None, 4), (ZYNQUS_IDCODE, 12)])
        self.assertEqual((t.chain_tap, t.idcode, t.ir_length), (1, ZYNQUS_IDCODE, 12))
        self.assertEqual(t.family, "zynqus")
        self.assertEqual(t.ir_table, {1: 0x902, 2: 0x903, 3: 0x922, 4: 0x923})
        self.assertIn("device 1 of 2", t.opened_device)
        self._check_core(t, pl)
        self._assert_bypassed(dap)

    def test_device_nearest_tdi_side_dap_known_by_idcode(self):
        dap, pl = _dap(0x5BA00477), _zynqus()
        self.lib.dev = _Chain(pl, dap)
        t = self._transport()
        self.assertEqual(t.chain, [(ZYNQUS_IDCODE, 12), (0x5BA00477, 4)])
        self.assertEqual(t.chain_tap, 0)
        self._check_core(t, pl)
        self._assert_bypassed(dap)

    def test_middle_device_and_one_ir_length_from_the_total(self):
        a, mid, b = _dap(0x4BA00477), _Device(), _dap(0x5BA00477)  # PolarFire
        self.lib.dev = _Chain(a, mid, b)
        t = self._transport()
        self.assertEqual([n for _c, n in t.chain], [4, 8, 4])  # 8 = 16 - 4 - 4
        self.assertEqual((t.chain_tap, t.family), (1, "polarfire"))
        self._check_core(t, mid)
        self._assert_bypassed(a, b)

    def test_two_known_devices_need_tap(self):
        first = _Device(XILINX_IDCODE, ir_len=6, user1=0x02, idcode_ir=0x09)
        second = _Device(0x03631093, ir_len=6, user1=0x02, idcode_ir=0x09)
        self.lib.dev = _Chain(first, second)
        with self.assertRaisesRegex(
            RuntimeError, r"2 devices on the JTAG chain \(0: 0x13631093, 1: 0x03631093\)"
            r".*pass tap="
        ):
            FtdiMpsseTransport().connect()
        self.assertEqual(ft._OPEN_CHANNELS, [])
        t = self._transport(tap=1)
        self._check_core(t, second)
        self._assert_bypassed(first)

    def test_unknown_ir_lengths_need_ir_lengths(self):
        other, target = _Device(idcode=0x12345001, ir_len=5), _Device()
        self.lib.dev = _Chain(other, target)
        with self.assertRaisesRegex(RuntimeError, r"13 IR bits in all\); pass ir_lengths="):
            FtdiMpsseTransport().connect()
        with self.assertRaisesRegex(RuntimeError, r"ir_lengths=\[6, 8\] does not match"):
            FtdiMpsseTransport(ir_lengths=[6, 8]).connect()
        with self.assertRaisesRegex(RuntimeError, r"ir_lengths=\[13\] does not match"):
            FtdiMpsseTransport(ir_lengths=[13]).connect()
        t = self._transport(ir_lengths=[5, 8])
        self.assertEqual(t.chain_tap, 1)
        self._check_core(t, target)
        self._assert_bypassed(other)

    def test_multi_die_7series_ir_is_not_taken_for_six_bits(self):
        # Family 0x1B, but a 24-bit IR (UG470): read as six bits, the
        # PolarFire would get 26 and the XC7V2000T would be picked.
        target, ssi = _Device(), _Device(0x236B3093, ir_len=24, user1=0x3C2, idcode_ir=0x3C9)
        self.lib.dev = _Chain(target, ssi)
        t = self._transport()
        self.assertEqual(t.chain, [(POLARFIRE_IDCODE, 8), (0x236B3093, 24)])
        self.assertEqual((t.chain_tap, t.family), (0, "polarfire"))
        self._check_core(t, target)
        self._assert_bypassed(ssi)

    def test_chain_with_more_than_127_ir_bits(self):
        ssis = [
            _Device(0x236B3093 + (i << 28), ir_len=24, user1=0x3C2, idcode_ir=0x3C9)
            for i in range(5)
        ]
        target = _Device()
        self.lib.dev = _Chain(*ssis, target)  # 5 * 24 + 8 = 128 IR bits
        t = self._transport()
        self.assertEqual([n for _c, n in t.chain], [24] * 5 + [8])
        self.assertEqual(t.chain_tap, 5)
        self._check_core(t, target)
        self._assert_bypassed(*ssis)

    def test_tap_past_the_chain(self):
        self.lib.dev = _Chain(_dap(), _zynqus())
        with self.assertRaisesRegex(RuntimeError, r"tap=2 but the JTAG chain has 2"):
            FtdiMpsseTransport(tap=2).connect()
        with self.assertRaises(ValueError):
            FtdiMpsseTransport(tap=-1)
        with self.assertRaises(ValueError):
            FtdiMpsseTransport(ir_lengths=[4, 1])

    def test_single_device_ignores_nothing_it_is_given(self):
        t = self._transport(tap=0, ir_lengths=[8])
        self.assertEqual(t.chain, [(POLARFIRE_IDCODE, 8)])
        self.assertNotIn("device", t.opened_device)
        with self.assertRaisesRegex(RuntimeError, r"tap=1 but the JTAG chain has 1"):
            FtdiMpsseTransport(device="Embedded FlashPro5 B", tap=1).connect()

    def test_joining_with_another_tap_is_refused(self):
        self.lib.dev = _Chain(_dap(0x5BA00477), _zynqus())
        a = self._transport()
        refused = FtdiMpsseTransport(tap=0)
        with self.assertRaisesRegex(RuntimeError, r"open for JTAG device 1, not tap=0"):
            refused.connect()
        # Nothing of the channel it was refused is left on it.
        self.assertEqual((refused.idcode, refused.chain, refused.opened_device), (None, [], None))
        self.assertEqual(a._channel.users, 1)
        with self.assertRaisesRegex(RuntimeError, r"IR lengths \[4, 12\], not"):
            FtdiMpsseTransport(ir_lengths=[12, 4]).connect()
        b = self._transport(tap=1)
        self.assertEqual(b.read_reg(0x0000), 0x46430004)
        self.assertEqual(a._channel, b._channel)

    def _program(self, tdo_side: int, tdi_side: int) -> _Xilinx7Device:
        data = _bitstream()
        fpga = _Xilinx7Device(accepts=data)
        fpga.lead = tdi_side
        before = [_dap(0x4BA00477) for _ in range(tdo_side)]
        after = [_dap(0x5BA00477) for _ in range(tdi_side)]
        self.lib.dev = _Chain(*before, fpga, *after)
        t = self._transport()
        self.assertEqual((t.chain_tap, t.family), (tdo_side, "xilinx7"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.bin"
            path.write_bytes(data)
            t.program(str(path))
        self.assertEqual(fpga.programs, 1)
        self.assertEqual(fpga.loaded(), data)
        # The whole bitstream reached the FPGA, and nothing after it.
        self.assertEqual(len(fpga.cfg_bits), tdi_side + 8 * len(data))
        self.assertTrue(fpga.done)
        self.assertEqual(t.read_reg(0x0000), 0x46430004)
        self._assert_bypassed(*before, *after)
        t.close()  # the next chain opens the channel afresh
        return fpga

    def test_program_with_a_device_on_the_tdo_side(self):
        self._program(tdo_side=1, tdi_side=0)

    def test_program_with_devices_on_the_tdi_side(self):
        self._program(tdo_side=0, tdi_side=1)
        self._program(tdo_side=1, tdi_side=2)


class PaddedBatchTests(unittest.TestCase):
    def test_target_bits_only(self):
        # TDO side: a 4-bit IR; TDI side: a 6-bit and a 5-bit IR.
        tdo, target, tdi1, tdi2 = _dap(), _Device(), _Device(ir_len=6), _Device(ir_len=5)
        chain = _Chain(tdo, target, tdi1, tdi2)
        lib = _FakeD2xx(chain)
        for dev in chain.devices:
            dev.state = "IDLE"
        batch = _Batch(pad=(4, 1, 11, 2))
        batch.scan(True, 0x20, 8, True)  # USER1
        batch.scan(False, 0x1_2345_6789_ABCD, 49, False)  # write 0x2345
        batch.scan(False, 0x2345 << 32, 49, False)  # read it
        batch.idle(5)
        batch.scan(False, 0, 49, True)
        lib._run(bytes(batch.cmd))
        ir_capture, read = batch.decode(bytes(lib.rx))
        self.assertEqual(ir_capture, 0b01)
        self.assertEqual(target.writes, [(0x2345, 0x6789ABCD)])
        self.assertEqual(read, 0x6789ABCD)
        self.assertEqual([d.ir for d in chain.devices], [0xF, 0x20, 0x3F, 0x1F])


class KnownIrLengthTests(unittest.TestCase):
    def test_lengths(self):
        self.assertEqual(ft.known_ir_length(0x5BA00477), 4)
        self.assertEqual(ft.known_ir_length(0x4BA00477), 4)
        self.assertEqual(ft.known_ir_length(XILINX_IDCODE), 6)
        self.assertEqual(ft.known_ir_length(0x03722093), 6)  # xc7z010 PL
        self.assertEqual(ft.known_ir_length(ZYNQUS_IDCODE), 12)
        # Multi-die 7-series (UG470 table 1-1); the 7V2000T ignores bits 13:12.
        self.assertEqual(ft.known_ir_length(0x236B3093), 24)
        self.assertEqual(ft.known_ir_length(0x236B0093), 24)
        self.assertEqual(ft.known_ir_length(0x236D5093), 24)
        self.assertEqual(ft.known_ir_length(0x236D9093), 22)
        self.assertEqual(ft.known_ir_length(0x236DB093), 38)
        self.assertEqual(ft.known_ir_length(0x23691093), 6)  # 7VX690T: one die
        self.assertIsNone(ft.known_ir_length(POLARFIRE_IDCODE))
        self.assertIsNone(ft.known_ir_length(None))
        self.assertEqual(family_from_idcode(ZYNQUS_IDCODE, 12), "zynqus")
        # A 12-bit Xilinx IR outside Zynq UltraScale+ (a multi-die part).
        self.assertIsNone(family_from_idcode(0x0390D093, 12))


if __name__ == "__main__":
    unittest.main()
