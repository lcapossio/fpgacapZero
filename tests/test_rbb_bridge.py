# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""fcapz openocd-bridge: OpenOCD remote_bitbang onto MPSSE commands.
No hardware: the adapter is a fake pin port, or an MPSSE subset driving a
bit-level TAP model."""

from __future__ import annotations

import random
import socket
import struct
import sys
import threading
import unittest
from unittest import mock

from fcapz import cli
from fcapz import rbb_bridge
from fcapz.rbb_bridge import (
    TCK,
    TDI,
    TDO,
    TMS,
    Bitbang,
    BitbangError,
    PinIo,
    Sleep,
    openocd_config,
    serve,
    tdo_reply,
)
from test_ftdi_transport import _Device

FLASHPRO5 = (0x18, 0x1B)  # ADBUS value / direction
DIGILENT = (0x88, 0x8B)   # ADBUS7 enables the JTAG buffer
PLAIN = (0x08, 0x0B)      # an adapter with no known layout
GW1NR9_IDCODE = 0x1100481B


def translate(data, value, direction, trst=0, gpio=True):
    """One feed's I/O, joined: (commands, reads, quit)."""
    ops, quit_ = Bitbang(value, direction, trst, gpio=gpio).feed(data)
    io = [op for op in ops if isinstance(op, PinIo)]
    return b"".join(op.commands for op in io), sum(op.reads for op in io), quit_


class TapPins:
    """The MPSSE commands the bridge sends, run against a TAP model.

    A 0x80 write that raises TCK clocks the TAP, as on a real adapter; a
    1-bit 0x4B/0x6B clocks it once, leaving TCK low.  With *gpio* False the
    pin commands do nothing (0x80 is ignored, 0x81 answers 0x01), as on the
    BRS-100's FT2232-compatible adapter.  ``rises`` counts the TAP's rising
    edges.
    """

    def __init__(self, dev, gpio=True, value=PLAIN[0]):
        self.dev = dev
        self.gpio = gpio
        self.pins = value
        self.rises = 0

    def _tdo(self) -> int:
        return self.dev.sr & 1 if self.dev.state in ("SHIFT_DR", "SHIFT_IR") else 0

    def _rise(self, tms: int, tdi: int) -> int:
        self.rises += 1
        return self.dev.clock(tms, tdi)

    def exchange(self, commands, reply_bytes):
        rx = bytearray()
        i = 0
        while i < len(commands):
            op = commands[i]
            if op == 0x80:
                new = commands[i + 1]
                if self.gpio:
                    if new & TCK and not self.pins & TCK:
                        self._rise(int(bool(new & TMS)), int(bool(new & TDI)))
                    self.pins = new
                i += 3
            elif op == 0x81:
                rx.append(self.pins | (TDO if self._tdo() else 0) if self.gpio else 0x01)
                i += 1
            elif op in (0x4B, 0x6B):  # 1 bit: TMS from bit 0, TDI from bit 7
                assert commands[i + 1] == 0 and not self.pins & TCK
                tms, tdi = commands[i + 2] & 1, commands[i + 2] >> 7
                tdo = self._rise(tms, tdi)
                self.pins = (self.pins & ~(TCK | TMS | TDI)) | (TMS if tms else 0) \
                    | (TDI if tdi else 0)
                if op == 0x6B:
                    rx.append(0x80 if tdo else 0)
                i += 3
            elif op == 0x87:
                i += 1
            else:
                raise AssertionError(f"unexpected MPSSE opcode {op:#04x}")
        assert len(rx) == reply_bytes
        return bytes(rx)


def openocd_dr_scan(bits: int, tdi: int = 0) -> tuple[bytes, int]:
    """The remote_bitbang stream OpenOCD's bitbang_scan sends for a DR scan
    from Test-Logic-Reset: each clock is a TCK-low write, a sample when the
    bit is read, and a TCK-high write.  Returns (stream, rising edges)."""
    out = []

    def clk(tms, d=0, read=False):
        out.append(chr(0x30 + (tms << 1 | d)) + ("R" if read else "")
                   + chr(0x34 + (tms << 1 | d)))

    for _ in range(5):
        clk(1)                       # Test-Logic-Reset
    for tms in (0, 1, 0, 0):
        clk(tms)                     # Idle, Select-DR, Capture-DR, Shift-DR
    for i in range(bits):
        clk(int(i == bits - 1), (tdi >> i) & 1, read=True)
    clk(1)
    clk(0)                           # Update-DR, Idle
    return "".join(out).encode() + b"0", 5 + 4 + bits + 2


def run_stream(chunks, pins, bitbang) -> bytes:
    """Feed *chunks* through *bitbang* onto *pins*; return the replies."""
    replies = b""
    for chunk in chunks:
        ops, _ = bitbang.feed(chunk)
        for op in ops:
            if isinstance(op, PinIo):
                reply = pins.exchange(op.commands, op.reads)
                if op.reads:
                    replies += tdo_reply(reply, op.masks)
    return replies


def bits_value(replies: bytes) -> int:
    return int(replies[::-1].decode(), 2)


class TranslateTests(unittest.TestCase):
    def test_each_bit_pattern_drives_tck_tms_tdi(self):
        value, direction = FLASHPRO5
        base = value & ~(TCK | TDI | TMS)
        cmd, reads, quit_ = translate(b"01234567", value, direction)
        expected = bytearray()
        for v in range(8):
            pins = base | (TCK if v & 4 else 0) | (TMS if v & 2 else 0) | (TDI if v & 1 else 0)
            expected += bytes((0x80, pins, direction))
        self.assertEqual(cmd, bytes(expected))
        self.assertEqual((reads, quit_), (0, False))

    def test_non_jtag_pins_keep_their_level(self):
        cmd, _, _ = translate(b"0", *DIGILENT)
        self.assertEqual(cmd, bytes((0x80, 0x80, 0x8B)))  # buffer enable stays on

    def test_reads_sample_tdo_and_flush(self):
        cmd, reads, _ = translate(b"2R6R", *FLASHPRO5)
        self.assertEqual(reads, 2)
        self.assertEqual(cmd.count(0x81), 2)
        self.assertEqual(cmd[-1], 0x87)  # send immediate after reads

    def test_quit_stops_and_drops_the_rest(self):
        cmd, reads, quit_ = translate(b"4RQ5R", *FLASHPRO5)
        self.assertTrue(quit_)
        self.assertEqual(reads, 1)
        self.assertEqual(cmd.count(0x80), 1)

    def test_led_and_swd_are_ignored(self):
        self.assertEqual(translate(b"BbOo", *FLASHPRO5), (b"", 0, False))

    def test_resets_are_ignored_without_a_trst_pin(self):
        self.assertEqual(translate(b"rstu", *DIGILENT), (b"", 0, False))

    def test_trst_drives_the_flashpro_ntrst_pin(self):
        bb = Bitbang(*FLASHPRO5, trst=0x10)
        ops, _ = bb.feed(b"2t")  # TMS high, then TRST asserted
        (io,) = ops
        self.assertEqual(io.commands, bytes((0x80, 0x18, 0x1B, 0x80, 0x08, 0x1B)))
        ops, _ = bb.feed(b"0")  # stays asserted across feeds
        self.assertEqual(ops[0].commands, bytes((0x80, 0x00, 0x1B)))
        ops, _ = bb.feed(b"s0")  # SRST only: TRST released
        self.assertEqual(ops[0].commands, bytes((0x80, 0x10, 0x1B, 0x80, 0x10, 0x1B)))

    def test_sleeps_keep_their_place_in_the_stream(self):
        ops, _ = Bitbang(*FLASHPRO5).feed(b"4RZZz5R")
        self.assertEqual([type(op) for op in ops], [PinIo, Sleep, PinIo])
        self.assertAlmostEqual(ops[1].seconds, 0.002001)
        self.assertEqual((ops[0].reads, ops[2].reads), (1, 1))

    def test_tdo_reply(self):
        masks = bytes((TDO,) * 4)
        self.assertEqual(tdo_reply(bytes((0x00, TDO, 0xFF & ~TDO, 0xFF)), masks), b"0101")
        # Each read has its own TDO bit: 0x81 replies in bit 2, 0x6B in bit 7.
        self.assertEqual(tdo_reply(bytes((0x80, 0x80, TDO, TDO)),
                                   bytes((0x80, TDO, TDO, 0x80))), b"1010")
        with self.assertRaises(BitbangError):
            tdo_reply(b"\x00", b"\x04\x04")


class ClockedTests(unittest.TestCase):
    """gpio=False: each rising edge is a 1-bit 0x4B, or with the sample
    before it a 1-bit 0x6B; nothing goes through the pin commands."""

    def feed(self, *chunks, trst=0):
        bb = Bitbang(*PLAIN, trst, gpio=False)
        return bb, [bb.feed(chunk)[0] for chunk in chunks]

    def test_a_rising_edge_is_a_clocked_write(self):
        cmd, reads, _ = translate(b"2604", *PLAIN, gpio=False)
        # TMS in bit 0, TDI in bit 7; TCK-low writes send nothing.
        self.assertEqual(cmd, bytes((0x4B, 0x00, 0x01, 0x4B, 0x00, 0x00)))
        self.assertEqual(reads, 0)

    def test_tdi_goes_in_bit_7(self):
        cmd, _, _ = translate(b"15", *PLAIN, gpio=False)
        self.assertEqual(cmd, bytes((0x4B, 0x00, 0x80)))

    def test_sample_and_rising_edge_become_one_clocked_read(self):
        _, (ops,) = self.feed(b"2R6")
        (io,) = ops
        self.assertEqual(io.commands, bytes((0x6B, 0x00, 0x01, 0x87)))
        self.assertEqual(io.masks, bytes((0x80,)))

    def test_holding_tck_high_adds_no_rising_edge(self):
        for stream in (b"0R44", b"0R46", b"0R40", b"44"):
            with self.subTest(stream=stream):
                cmd, _, _ = translate(stream, *PLAIN, gpio=False)
                self.assertEqual(len(cmd) - cmd.count(0x87), 3)

    def test_no_pin_command_is_ever_sent(self):
        stream, _ = openocd_dr_scan(32)
        cmd, _, _ = translate(stream + b"rstuBb", *PLAIN, trst=0x10, gpio=False)
        ops = cmd.replace(b"\x87", b"")[::3]
        self.assertEqual(set(ops), {0x4B, 0x6B})

    def test_a_sample_at_the_end_of_a_buffer_waits_for_the_next(self):
        bb, (first, second) = self.feed(b"0R", b"4")
        self.assertEqual(first, [])
        self.assertEqual(second[0].commands, bytes((0x6B, 0x00, 0x00, 0x87)))
        self.assertFalse(bb.pending)

    def test_led_and_resets_do_not_resolve_a_pending_sample(self):
        _, (ops,) = self.feed(b"0RBt4", trst=0x10)
        self.assertEqual(ops[0].masks, bytes((0x80,)))

    def test_a_sample_without_its_rising_edge_is_refused(self):
        for head, tail in ((b"0R", b"R"), (b"0R", b"0"), (b"0R", b"3"),
                           (b"4R", b"4"), (b"0R", b"Z"), (b"0R", b"z"),
                           (b"0R", b"Q")):
            with self.subTest(stream=head + tail), self.assertRaises(BitbangError):
                self.feed(head + tail)

    def test_gpio_keeps_the_pin_commands(self):
        cmd, reads, _ = translate(b"0R4", *PLAIN)
        self.assertEqual(cmd, bytes((0x80, 0x00, 0x0B, 0x81, 0x80, 0x01, 0x0B, 0x87)))
        self.assertEqual(reads, 1)


class TapScanTests(unittest.TestCase):
    """OpenOCD's scan stream through the bridge onto a TAP model."""

    def scan(self, chunks, gpio):
        pins = TapPins(_Device(GW1NR9_IDCODE), gpio=gpio)
        replies = run_stream(chunks, pins, Bitbang(*PLAIN, gpio=gpio))
        return replies, pins.rises

    def test_idcode_on_both_adapter_kinds(self):
        stream, rises = openocd_dr_scan(32)
        for gpio in (True, False):
            with self.subTest(gpio=gpio):
                replies, got_rises = self.scan([stream], gpio)
                self.assertEqual(bits_value(replies), GW1NR9_IDCODE)
                self.assertEqual(got_rises, rises)  # one rising edge per clock

    def test_pin_commands_on_an_adapter_without_them_never_reach_the_tap(self):
        # The bug clocked mode fixes: 0x80 never clocks the TAP there, and
        # 0x81 answers 0x01.
        pins = TapPins(_Device(GW1NR9_IDCODE), gpio=False)
        replies = run_stream([openocd_dr_scan(32)[0]], pins, Bitbang(*PLAIN))
        self.assertEqual((bits_value(replies), pins.rises), (0, 0))

    def test_every_split_of_the_stream(self):
        stream, rises = openocd_dr_scan(32)
        for gpio in (True, False):
            for k in range(len(stream) + 1):
                with self.subTest(gpio=gpio, split=k):
                    replies, got_rises = self.scan([stream[:k], stream[k:]], gpio)
                    self.assertEqual(bits_value(replies), GW1NR9_IDCODE)
                    self.assertEqual(got_rises, rises)

    def test_byte_at_a_time_long_scan(self):
        # 600 bits through the 32-bit IDCODE register: TDI comes back out 32
        # bits later.  Longer than OpenOCD's 255-sample buffer.
        pattern = random.Random(7).getrandbits(600)
        stream, rises = openocd_dr_scan(600, pattern)
        for gpio in (True, False):
            with self.subTest(gpio=gpio):
                replies, got_rises = self.scan([bytes((b,)) for b in stream], gpio)
                value = bits_value(replies)
                self.assertEqual(value & 0xFFFF_FFFF, GW1NR9_IDCODE)
                self.assertEqual(value >> 32, pattern & ((1 << 568) - 1))
                self.assertEqual(got_rises, rises)


class FakePins:
    """Answers every read with the next TDO level in *tdo*, in reply bit
    *bit* (TDO for pin reads, 0x80 for clocked ones)."""

    def __init__(self, tdo=(), bit=TDO):
        self.tdo = list(tdo)
        self.bit = bit
        self.commands = []

    def exchange(self, commands, reply_bytes):
        self.commands.append(commands)
        return bytes(self.bit if self.tdo.pop(0) else 0 for _ in range(reply_bytes))


class ServeTests(unittest.TestCase):
    def _start(self, pins, **kw):
        bound = []
        ready = threading.Event()

        def on_ready(port):
            bound.append(port)
            ready.set()

        thread = threading.Thread(
            target=serve, args=(pins, FLASHPRO5),
            kwargs={"port": 0, "ready": on_ready, "log": lambda m: None, **kw},
            daemon=True,
        )
        thread.start()
        self.assertTrue(ready.wait(5))
        return thread, bound[0]

    def test_reads_are_answered_in_order(self):
        pins = FakePins(tdo=[1, 0, 1])
        thread, port = self._start(pins, once=True)
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(b"0R4R0R")
            got = b""
            while len(got) < 3:
                got += c.recv(16)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(got, b"101")

    def test_quit_ends_the_server(self):
        pins = FakePins(tdo=[1])
        thread, port = self._start(pins)  # not once: only Q ends it
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(b"6RQ")
            self.assertEqual(c.recv(16), b"1")
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_a_dropped_connection_does_not_end_the_server(self):
        pins = FakePins(tdo=[1])
        thread, port = self._start(pins)
        c = socket.create_connection(("127.0.0.1", port))
        # Abort with RST, as a killed OpenOCD does.
        c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        c.sendall(b"0")
        c.close()
        with socket.create_connection(("127.0.0.1", port)) as c2:
            c2.sendall(b"4RQ")
            self.assertEqual(c2.recv(16), b"1")
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_sleeps_are_slept(self):
        pins = FakePins(tdo=[0])
        with mock.patch("fcapz.rbb_bridge.time.sleep") as sleep:
            thread, port = self._start(pins, once=True)
            with socket.create_connection(("127.0.0.1", port)) as c:
                c.sendall(b"ZZR")
                self.assertEqual(c.recv(16), b"0")
            thread.join(5)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args[0][0], 0.002)

    def test_clocked_reads_are_answered(self):
        pins = FakePins(tdo=[1, 0], bit=0x80)
        thread, port = self._start(pins, once=True, gpio=False)
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(b"0R")       # the sample waits for its rising edge ...
            c.sendall(b"40R4")     # ... which comes in the next send
            got = b""
            while len(got) < 2:
                got += c.recv(16)
        thread.join(5)
        self.assertEqual(got, b"10")
        self.assertIn(0x6B, b"".join(pins.commands))

    def test_a_sample_left_waiting_closes_the_connection(self):
        pins = FakePins(tdo=[1], bit=0x80)
        logs = []
        with mock.patch.object(rbb_bridge, "PENDING_TIMEOUT_S", 0.05):
            thread, port = self._start(pins, gpio=False, log=logs.append)
            with socket.create_connection(("127.0.0.1", port)) as c:
                c.sendall(b"0R")
                self.assertEqual(c.recv(16), b"")  # closed, nothing answered
            # The server goes on to the next connection.
            with socket.create_connection(("127.0.0.1", port)) as c2:
                c2.sendall(b"0R4Q")
                self.assertEqual(c2.recv(16), b"1")
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any("rising TCK edge" in m for m in logs), logs)

    def test_listens_on_loopback_only(self):
        pins = FakePins()
        thread, port = self._start(pins, once=True)
        with socket.create_connection(("127.0.0.1", port)) as c:
            self.assertEqual(c.getpeername()[0], "127.0.0.1")
        thread.join(5)

    def test_openocd_config(self):
        lines = ("adapter driver remote_bitbang\nremote_bitbang host 127.0.0.1\n"
                 "remote_bitbang port 3335\ntransport select jtag\n")
        self.assertEqual(openocd_config(3335, trst=True), lines)
        # No TRST pin: a trst_only config would never reset the TAP.
        self.assertEqual(openocd_config(3335), lines + "reset_config none\n")


class CliTests(unittest.TestCase):
    def _run(self, *argv):
        with mock.patch.object(sys, "argv", ["fcapz", *argv]):
            return cli.main()

    def test_opens_the_named_adapter_serves_and_releases_it(self):
        pins = mock.MagicMock()
        pins.open_pins.return_value = FLASHPRO5
        pins.adapter.description = "Embedded FlashPro5 A"
        pins.gpio = True
        with mock.patch("fcapz.ftdi_transport.FtdiMpsseTransport",
                        return_value=pins) as ctor, \
                mock.patch("fcapz.rbb_bridge.serve") as serve_:
            rc = self._run("--hardware", "Embedded FlashPro5 A", "openocd-bridge",
                           "--listen-port", "4444", "--once")
        self.assertEqual(rc, 0)
        ctor.assert_called_once_with(device="Embedded FlashPro5 A")
        args, kwargs = serve_.call_args
        self.assertEqual(args, (pins, FLASHPRO5))
        self.assertEqual((kwargs["port"], kwargs["once"]), (4444, True))
        self.assertEqual(kwargs["trst"], 0x10)  # FlashPro nTRST
        self.assertIs(kwargs["gpio"], True)
        pins.close.assert_called_once()

    def test_an_adapter_without_gpio_is_served_clocked_without_trst(self):
        pins = mock.MagicMock()
        pins.open_pins.return_value = FLASHPRO5
        pins.adapter.description = "Embedded FlashPro5 A"  # has a TRST pin ...
        pins.gpio = False                                  # ... it cannot drive
        with mock.patch("fcapz.ftdi_transport.FtdiMpsseTransport", return_value=pins), \
                mock.patch("fcapz.rbb_bridge.serve") as serve_:
            rc = self._run("openocd-bridge")
        self.assertEqual(rc, 0)
        kwargs = serve_.call_args[1]
        self.assertEqual((kwargs["gpio"], kwargs["trst"]), (False, 0))

    def test_port_in_use_reports_and_releases(self):
        pins = mock.MagicMock()
        pins.open_pins.return_value = FLASHPRO5
        pins.adapter.description = "Digilent USB Device A"
        with mock.patch("fcapz.ftdi_transport.FtdiMpsseTransport", return_value=pins), \
                mock.patch("fcapz.rbb_bridge.serve", side_effect=OSError("in use")):
            rc = self._run("openocd-bridge")
        self.assertEqual(rc, 1)
        pins.close.assert_called_once()

    def test_bad_listen_port_is_refused_before_opening(self):
        with mock.patch("fcapz.ftdi_transport.FtdiMpsseTransport") as ctor:
            rc = self._run("openocd-bridge", "--listen-port", "70000")
        self.assertEqual(rc, 2)
        ctor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
