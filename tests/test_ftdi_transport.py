# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""FtdiMpsseTransport against a fake D2XX library that runs the MPSSE
command stream through a bit-level JTAG TAP model.  No hardware."""

from __future__ import annotations

import ctypes
import unittest
from unittest import mock

from fcapz import ftdi_transport as ft
from fcapz.ftdi_transport import (
    FtdiDevice,
    FtdiMpsseTransport,
    _Batch,
    _pick_device,
    family_from_idcode,
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
        if self.ir == self.idcode_ir:
            return 32
        if self.ir == self.user1:
            return 49
        return 1  # BYPASS

    def clock(self, tms: int, tdi: int) -> int:
        shifting = self.state in ("SHIFT_DR", "SHIFT_IR")
        tdo = self.sr & 1 if shifting else 0
        if self.state == "CAPTURE_DR":
            self.sr_len = self._dr_len()
            if self.ir == self.idcode_ir:
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


class _FakeD2xx:
    """D2XX entry points over an MPSSE interpreter driving ``_Device``."""

    def __init__(self, device=None, devices=None):
        self.dev = device or _Device()
        self.devices = devices or [
            FtdiDevice(0, "Embedded FlashPro5 A", "FP5SN0A", 0x15142008, False),
            FtdiDevice(1, "Embedded FlashPro5 B", "FP5SN0B", 0x15142008, False),
        ]
        self.rx = bytearray()
        self.opens = 0
        self.closes = 0
        self.writes = 0
        self.tms = 1
        self.divisor = None

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
        self._run(bytes(data[:n]))
        written._obj.value = n
        return 0

    def FT_Read(self, handle, buf, n, got):
        take = bytes(self.rx[:n])
        del self.rx[:n]
        ctypes.memmove(buf, take, len(take))
        got._obj.value = len(take)
        return 0

    # MPSSE
    def _clock(self, tms, tdi):
        self.tms = tms
        return self.dev.clock(tms, tdi)

    def _run(self, cmd: bytes) -> None:
        i = 0
        while i < len(cmd):
            op = cmd[i]
            if op in (0x8A, 0x97, 0x8D, 0x85, 0x87):
                i += 1
            elif op == 0x86:
                self.divisor = cmd[i + 1] | (cmd[i + 2] << 8)
                i += 3
            elif op == 0x80:
                i += 3
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


class SharedChannelTests(_FtdiTestCase):
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


if __name__ == "__main__":
    unittest.main()
