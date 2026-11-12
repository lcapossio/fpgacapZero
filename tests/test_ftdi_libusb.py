# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""The libusb byte I/O of the FTDI transport (fcapz.ftdi_libusb), against
a fake chip with finite buffers: nothing reads its replies unless the host
asks, as with a real one."""

from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from unittest import mock

from fcapz import ftdi_libusb as fl
from fcapz import ftdi_transport as ft
from fcapz.ftdi_transport import FtdiDevice, FtdiMpsseTransport
from test_ftdi_transport import POLARFIRE_IDCODE, _FakeD2xx

#: The real enumeration (conftest stubs it out for every test).
_LIST_USB_DEVICES = fl.list_usb_devices


def _command(buf: bytes, i: int, chip: str = "h") -> tuple[int, int] | None:
    """``(length, reply bytes)`` of the MPSSE command at *buf[i]*, as the
    fake interpreter runs it; ``None`` while it is incomplete."""
    op = buf[i]
    if op in (0x3D, 0x3F, 0x6F):
        op &= ~0x04
    if op in (0x8A, 0x97, 0x8D):
        return (1, 2) if chip == "d" else (1, 0)
    if op in (0x85, 0x87):
        return 1, 0
    if op in (0x86, 0x80):
        return (3, 0) if len(buf) - i >= 3 else None
    if op == 0x81:
        return 1, 1
    if op in (0x19, 0x39):
        if len(buf) - i < 3:
            return None
        n = (buf[i + 1] | buf[i + 2] << 8) + 1
        return (3 + n, n if op == 0x39 else 0) if len(buf) - i >= 3 + n else None
    if op in (0x1B, 0x3B, 0x4B, 0x6B):
        if len(buf) - i < 3:
            return None
        return 3, 1 if op in (0x3B, 0x6B) else 0
    return 1, 2  # bad command: 0xFA echo


class _FakeChipPort:
    """An FTDI channel's endpoints over the fake MPSSE interpreter, with a
    finite command buffer (*rx_fifo*) and reply buffer (*tx_fifo*): MPSSE
    stops when its next reply does not fit, and a write blocks when the
    command buffer is full."""

    STATUS = b"\x32\x60"

    def __init__(self, chip: _FakeD2xx, packet_size=512, rx_fifo=1024, tx_fifo=1024):
        self.chip = chip
        self.packet_size = packet_size
        self.rx_fifo, self.tx_fifo = rx_fifo, tx_fifo
        self.pending = bytearray()
        self.ctrls: list[tuple[int, int, int]] = []
        self.closed = 0
        self.fail_reads = False
        self.cond = threading.Condition()

    def _pump(self) -> None:
        while self.pending:
            cmd = _command(self.pending, 0, self.chip.chip)
            if cmd is None:
                return
            length, reply = cmd
            if self.chip.rx and len(self.chip.rx) + reply > self.tx_fifo:
                # Stalled until the host reads.  (A real chip streams a
                # reply longer than its buffer; here it lands at once.)
                return
            self.chip._run(bytes(self.pending[:length]))
            del self.pending[:length]

    def ctrl(self, request, value, index=0):
        with self.cond:
            self.ctrls.append((request, value, index))
            if request == fl._SIO_RESET and value == fl._PURGE_RX:
                self.chip.rx.clear()
            if request == fl._SIO_RESET and value == fl._PURGE_TX:
                self.pending.clear()

    def write(self, data, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000
        sent = 0
        with self.cond:
            while sent < len(data):
                space = self.rx_fifo - len(self.pending)
                if space > 0:
                    take = min(space, len(data) - sent)
                    self.pending += data[sent:sent + take]
                    sent += take
                    self._pump()
                    self.cond.notify_all()
                    continue
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.cond.wait(left)
                self._pump()
        if sent == 0:
            raise RuntimeError("FTDI write timed out (fake)")
        return sent

    def read(self, size, timeout_ms):
        if self.fail_reads:
            raise OSError("USB error (fake)")
        payload = self.packet_size - 2
        with self.cond:
            self._pump()
            if not self.chip.rx:
                # The chip answers status-only packets every latency period.
                self.cond.wait(min(timeout_ms / 1000, 0.002))
                self._pump()
            out = bytearray()
            for _ in range(size // self.packet_size):
                if not self.chip.rx and out:
                    break
                out += self.STATUS + self.chip.rx[:payload]
                del self.chip.rx[:payload]
                if len(out) % self.packet_size:
                    break  # a short packet ends the transfer
            self._pump()
            self.cond.notify_all()
        return bytes(out)

    def close(self):
        self.closed += 1


class _ScriptedPort:
    """Hands out a byte stream framed as USB packets of *packet_size*, in
    transfers of at most *chunk* packets, then status-only packets."""

    def __init__(self, stream: bytes, packet_size: int, chunk: int = 3, gaps: bool = False):
        self.stream = bytearray(stream)
        self.packet_size, self.chunk = packet_size, chunk
        self.gaps = gaps  # every other transfer: a status-only packet
        self.reads = 0
        self.sizes: list[int] = []

    def read(self, size, timeout_ms):
        self.reads += 1
        self.sizes.append(size)
        if self.gaps and self.reads % 2:
            return b"2`"  # the latency timer fired with nothing to send
        payload = self.packet_size - 2
        out = bytearray()
        for _ in range(min(self.chunk, size // self.packet_size)):
            out += b"\x32\x60" + self.stream[:payload]
            del self.stream[:payload]
            if not self.stream:
                break
        return bytes(out) or b"\x32\x60"


class FramingTests(unittest.TestCase):
    def test_status_bytes_are_stripped_at_every_packet_size(self):
        data = bytes(range(256)) * 20
        for ps in (64, 512):
            for n in (1, ps - 3, ps - 2, ps - 1, 2 * (ps - 2), 2 * (ps - 2) + 1, len(data)):
                with self.subTest(packet_size=ps, n=n):
                    io = fl.LibusbIo(_ScriptedPort(data, ps))
                    got = io.read(n)
                    self.assertEqual(got, data[:n])
                    rest = len(data) - n
                    if rest:  # what came early is kept for the next read
                        self.assertEqual(io.read(rest), data[n:])

    def test_status_only_packets_mid_reply(self):
        data = bytes(range(256)) * 20
        for ps in (64, 512):
            with self.subTest(packet_size=ps):
                io = fl.LibusbIo(_ScriptedPort(data, ps, gaps=True))
                self.assertEqual(io.read(len(data)), data)

    def test_read_larger_than_one_transfer(self):
        data = bytes(range(251)) * 1000  # 251 KB
        port = _ScriptedPort(data, 512, chunk=10_000)
        io = fl.LibusbIo(port)
        self.assertEqual(io.read(len(data)), data)
        self.assertLessEqual(max(port.sizes), fl.LibusbIo.MAX_READ)
        self.assertTrue(all(size % 512 == 0 for size in port.sizes))

    def test_partial_reply_times_out_with_the_count(self):
        io = fl.LibusbIo(_ScriptedPort(b"\x11" * 100, 64), timeout_ms=50)
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, r"read timed out: 100 of 200 bytes"):
            io.read(200)
        self.assertLess(time.monotonic() - start, 1.0)

    def test_setup_requests(self):
        port = _FakeChipPort(_FakeD2xx())
        port.chip.rx += b"stale"
        fl.LibusbIo(port).setup(1000)
        self.assertEqual(port.ctrls, [
            (fl._SIO_RESET, 0, 0),
            (fl._SIO_SET_LATENCY_TIMER, 1, 0),
            (fl._SIO_SET_FLOW_CTRL, 0, 0x0100),
            (fl._SIO_SET_BITMODE, 0x0000, 0),
            (fl._SIO_SET_BITMODE, 0x0200, 0),
            (fl._SIO_RESET, 1, 0),
            (fl._SIO_RESET, 2, 0),
        ])
        self.assertEqual(port.chip.rx, bytearray())


class TransferTests(unittest.TestCase):
    def _io(self, **kw):
        io = fl.LibusbIo(_FakeChipPort(_FakeD2xx(), **kw), timeout_ms=2000)
        io.setup(2000)
        return io

    def test_reply_larger_than_the_chip_buffer(self):
        # 300 KB of pin reads: the reply overflows the chip's buffer long
        # before the commands are all written.
        for ps in (64, 512):
            with self.subTest(packet_size=ps):
                io = self._io(packet_size=ps)
                n = 300 * 1024
                reply = io.transfer(bytes((0x81,)) * n + bytes((0x87,)), n)
                self.assertEqual(len(reply), n)

    def test_the_fake_stalls_like_a_chip(self):
        # Without the concurrent read the same transfer cannot finish.
        io = self._io()
        io.timeout_ms = 300
        with mock.patch.object(fl.LibusbIo, "DIRECT_REPLY_BYTES", 1 << 30):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                io.transfer(bytes((0x81,)) * 8192 + bytes((0x87,)), 8192)

    def test_full_speed_chip_buffers(self):
        # FT2232D: 128 command bytes, 384 reply bytes.  450 replies behind
        # 1800 command bytes stall the chip before the write ends.
        cmd = bytes((0x86, 0, 0, 0x81)) * 450 + bytes((0x87,))
        io = self._io(packet_size=64, rx_fifo=128, tx_fifo=384)
        self.assertEqual(len(io.transfer(cmd, 450)), 450)
        io = self._io(packet_size=64, rx_fifo=128, tx_fifo=384)
        io.timeout_ms = 300
        with mock.patch.object(fl.LibusbIo, "DIRECT_REPLY_BYTES_FULL_SPEED", 512):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                io.transfer(cmd, 450)

    def test_small_reply_is_one_write_then_one_read(self):
        io = self._io()
        with mock.patch.object(threading, "Thread", side_effect=AssertionError("thread")):
            self.assertEqual(len(io.transfer(bytes((0x81, 0x81, 0x87)), 2)), 2)

    def test_close_waits_for_a_reader_still_in_flight(self):
        events = []

        class SlowPort(_FakeChipPort):
            def write(self, data, timeout_ms):
                raise RuntimeError("USB write failed (fake)")

            def read(self, size, timeout_ms):
                time.sleep(1.5)  # a read that overruns its timeout
                events.append("read done")
                return self.STATUS

            def close(self):
                events.append("close")
                super().close()

        io = fl.LibusbIo(SlowPort(_FakeD2xx()), timeout_ms=100)
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            io.transfer(bytes((0x81,)) * 1024, 1024)
        io.close()
        self.assertEqual(events[-1], "close")
        self.assertIn("read done", events)

    def test_a_reader_stuck_past_close_releases_the_port_itself(self):
        events = []
        release = threading.Event()

        class StuckPort(_FakeChipPort):
            def write(self, data, timeout_ms):
                raise RuntimeError("USB write failed (fake)")

            def read(self, size, timeout_ms):
                release.wait(10)  # stuck in the backend
                events.append("read done")
                return self.STATUS

            def close(self):
                events.append("close")
                super().close()

        io = fl.LibusbIo(StuckPort(_FakeD2xx()), timeout_ms=50)
        with self.assertRaises(RuntimeError):
            io.transfer(bytes((0x81,)) * 1024, 1024)
        io.close()  # the reader is still inside read()
        self.assertEqual(events, [])  # the port is not released under it
        release.set()
        for _ in range(200):
            if "close" in events:
                break
            time.sleep(0.01)
        self.assertEqual(events, ["read done", "close"])
        self.assertEqual(io.port.closed, 1)

    def test_reader_that_just_ended_is_not_left_to_release_the_port(self):
        # The reader has run its cleanup, but its thread is not yet reported
        # dead: close() must release the port itself.
        io = self._io()

        class EndingThread:
            def join(self, timeout=None):
                pass

            def is_alive(self):
                return True

        io._reader, io._reader_busy = EndingThread(), False
        io.close()
        self.assertEqual(io.port.closed, 1)

    def test_close_leaves_mpsse_once(self):
        io = self._io()
        io.close()
        io.close()
        self.assertEqual(io.port.closed, 1)
        self.assertEqual(io.port.ctrls[-1], (fl._SIO_SET_BITMODE, 0x0000, 0))


_USB_FP5 = FtdiDevice(0, "Embedded FlashPro5 A", "FP5SN0A", 0x15142008, False,
                      backend="libusb", interface=0, location="libusb1:1:5")


class LibusbTransportTests(unittest.TestCase):
    """FtdiMpsseTransport on a ``usb:`` channel."""

    def setUp(self):
        self.lib = _FakeD2xx()
        self.ports: list[_FakeChipPort] = []
        self.usb_devices = [_USB_FP5]

        def open_port(dev, timeout_ms):
            port = _FakeChipPort(self.lib)
            self.ports.append(port)
            return port

        for patcher in (
            mock.patch.object(ft, "_load_d2xx", lambda: self.lib),
            mock.patch.object(fl, "list_usb_devices", lambda: list(self.usb_devices)),
            mock.patch.object(fl, "open_port", open_port),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(ft._OPEN_CHANNELS.clear)

    def _transport(self, **kw):
        t = FtdiMpsseTransport(**kw)
        t.connect()
        self.addCleanup(t.close)
        return t

    def test_connect_read_and_close(self):
        t = self._transport(device="usb:")
        self.assertEqual(t.idcode, POLARFIRE_IDCODE)
        self.assertEqual(t.adapter.backend, "libusb")
        self.assertEqual(t.read_reg(0x0000), 0x46430004)
        self.assertEqual(self.lib.opens, 0)  # D2XX untouched
        t.close()
        self.assertEqual(self.ports[0].closed, 1)

    def test_selectors(self):
        for device in ("usb:", "usb:Embedded FlashPro5 A", "usb:FP5SN0A"):
            with self.subTest(device=device):
                t = FtdiMpsseTransport(device=device)
                t.connect()
                self.assertEqual(t.adapter.location, "libusb1:1:5")
                t.close()
        with self.assertRaisesRegex(RuntimeError, "no FTDI channel"):
            FtdiMpsseTransport(device="usb:nope").connect()

    def test_wide_scans_through_finite_buffers(self):
        t = self._transport(device="usb:")
        out = t.raw_dr_scan_batch([(0, 49)] * 3000)
        self.assertEqual(len(out), 3000)

    def test_d2xx_and_libusb_names_share_one_channel(self):
        a = self._transport(device="Embedded FlashPro5 A")  # D2XX
        b = self._transport(device="usb:FP5SN0A")  # same chip and channel
        self.assertEqual(self.lib.opens, 1)
        self.assertEqual(self.ports, [])
        self.assertEqual(b.adapter.backend, "d2xx")
        self.assertEqual(a.read_reg(0x0000), b.read_reg(0x0000))

    def test_usb_default_does_not_guess_between_open_channels(self):
        digilent = FtdiDevice(1, "Digilent USB Device A", "210319A", 0x04036010, False,
                              backend="libusb", interface=0, location="libusb1:1:9")
        self.usb_devices.append(digilent)
        self._transport(device="usb:Embedded FlashPro5 A")
        self._transport(device="usb:Digilent USB Device A")
        with self.assertRaisesRegex(RuntimeError, "several FTDI JTAG adapters"):
            FtdiMpsseTransport(device="usb:").connect()

    def test_pin_channel_without_serial_is_still_reserved(self):
        self.usb_devices[:] = [_USB_FP5._replace(serial="")]
        pins = FtdiMpsseTransport(device="usb:")
        self.addCleanup(pins.close)
        pins.open_pins()
        with self.assertRaisesRegex(RuntimeError, "held by open_pins"):
            FtdiMpsseTransport(device="usb:").connect()
        self.assertEqual(len(self.ports), 1)

    def test_usb_selector_says_when_only_d2xx_lists_the_channel(self):
        self.usb_devices[:] = []
        with self.assertRaisesRegex(RuntimeError, "D2XX lists 'Embedded FlashPro5 A'.*usb: prefix"):
            FtdiMpsseTransport(device="usb:Embedded FlashPro5 A").connect()

    def test_plain_selector_says_when_only_libusb_lists_the_channel(self):
        self.usb_devices[:] = [_USB_FP5._replace(description="Digilent USB Device A",
                                                 serial="210319A")]
        with self.assertRaisesRegex(RuntimeError, "name it 'usb:Digilent USB Device A'"):
            FtdiMpsseTransport(device="Digilent USB Device A").connect()

    def test_usb_error_breaks_the_channel(self):
        a = self._transport(device="usb:")
        b = self._transport(device="usb:")
        self.ports[0].fail_reads = True
        with self.assertRaisesRegex(OSError, "USB error"):
            a.read_reg(0x0000)
        self.assertEqual(self.ports[0].closed, 1)
        with self.assertRaisesRegex(RuntimeError, "channel broken"):
            b.read_reg(0x0000)
        b.connect()
        self.assertEqual(len(self.ports), 2)
        self.assertEqual(b.read_reg(0x0000), 0x46430004)


class SameChannelTests(unittest.TestCase):
    def test_libusb_channels_compare_by_location(self):
        clone = FtdiDevice(0, "Dual RS232-HS A", "00000000A", 0x04036010, False,
                           backend="libusb", interface=0, location="libusb1:1:3")
        twin = clone._replace(location="libusb1:1:4")  # same serial, other chip
        self.assertFalse(ft._same_channel(clone, twin))
        self.assertTrue(ft._same_channel(clone, clone._replace(index=5)))
        self.assertFalse(ft._same_channel(clone, clone._replace(interface=1)))
        no_serial = clone._replace(serial="")
        self.assertTrue(ft._same_channel(no_serial, no_serial))

    def test_across_backends_by_serial(self):
        d2xx = FtdiDevice(0, "Embedded FlashPro5 A", "FP5SN0A", 0x15142008, False)
        self.assertTrue(ft._same_channel(d2xx, _USB_FP5))
        port_b = _USB_FP5._replace(interface=1, description="Embedded FlashPro5 B",
                                   serial="FP5SN0B")
        self.assertFalse(ft._same_channel(d2xx, port_b))
        self.assertFalse(ft._same_channel(d2xx._replace(serial=""), _USB_FP5._replace(serial="")))


class _UsbDev:
    """A pyusb device as list_usb_devices sees it."""

    def __init__(self, serial, bus, address, interfaces=(0, 1), product="Dual RS232-HS"):
        self.idVendor, self.idProduct, self.bcdDevice = 0x0403, 0x6010, 0x0700
        self.iProduct, self.iSerialNumber = 1 if product else 0, 2 if serial else 0
        self.strings = {1: product, 2: serial}
        self.bus, self.address = bus, address
        self.configs = [[mock.Mock(bInterfaceNumber=n) for n in interfaces]]
        self.openable = True

    def ctrl_transfer(self, *args):
        if not self.openable:
            raise OSError("held by another driver (fake)")
        return b"" + bytes(17)

    def __iter__(self):
        return iter(self.configs)


class EnumerationTests(unittest.TestCase):
    def _list(self, per_backend):
        usb = mock.Mock()
        usb.core.USBError = OSError
        usb.core.find = lambda find_all, backend, custom_match: per_backend[backend]
        usb.util.get_string = lambda dev, index: dev.strings[index]
        backends = [(name, name) for name in per_backend]
        with (
            mock.patch.object(fl, "_usb", lambda: usb),
            mock.patch.object(fl, "_backends", lambda: backends),
        ):
            return _LIST_USB_DEVICES()

    def test_clones_sharing_a_serial_are_all_listed(self):
        found = self._list({"libusb1": [_UsbDev("SAME", 1, 3), _UsbDev("SAME", 1, 4)]})
        self.assertEqual([d.location for d in found], ["libusb1:1:3"] * 2 + ["libusb1:1:4"] * 2)
        self.assertEqual([d.serial for d in found], ["SAMEA", "SAMEB"] * 2)

    def test_a_chip_both_backends_reach_is_listed_once(self):
        found = self._list({
            "libusb1": [_UsbDev("FT01", 1, 3)],
            "libusb0": [_UsbDev("FT01", 0, 255, interfaces=(0,)),
                        _UsbDev("FT01", 0, 254, interfaces=(1,))],
        })
        self.assertEqual([(d.description, d.location) for d in found], [
            ("Dual RS232-HS A", "libusb1:1:3"), ("Dual RS232-HS B", "libusb1:1:3"),
        ])

    def test_stringless_chip_its_driver_holds_is_left_out(self):
        held = _UsbDev("", 1, 3, product="")
        held.openable = False
        free = _UsbDev("", 1, 4, product="")
        found = self._list({"libusb1": [held, free]})
        self.assertEqual([(d.description, d.location) for d in found],
                         [("FTDI A", "libusb1:1:4"), ("FTDI B", "libusb1:1:4")])

    def test_serial_less_chips_are_kept_per_backend(self):
        found = self._list({
            "libusb1": [_UsbDev("", 1, 3)],
            "libusb0": [_UsbDev("", 0, 255, interfaces=(0,))],
        })
        self.assertEqual([d.location for d in found], ["libusb1:1:3"] * 2 + ["libusb0:0:255"])
        self.assertEqual(found[2].description, "Dual RS232-HS A")  # FT2232H: lettered


class DiscoveryTests(unittest.TestCase):
    def test_targets_from_both_backends(self):
        lib = _FakeD2xx()
        with (
            mock.patch.object(ft, "_load_d2xx", lambda: lib),
            mock.patch.object(fl, "list_usb_devices", lambda: [_USB_FP5]),
        ):
            self.assertEqual(ft.list_ftdi_targets(), [
                "Embedded FlashPro5 A", "Embedded FlashPro5 B", "usb:Embedded FlashPro5 A",
            ])

    def test_d2xx_error_only_when_neither_backend_works(self):
        def no_d2xx():
            raise RuntimeError("FTDI D2XX library missing")

        def no_pyusb():
            raise RuntimeError("usb: devices need pyusb")

        pyusb = {"usb": types.ModuleType("usb"), "usb.core": types.ModuleType("usb.core")}
        no_pyusb_module = {"usb": None, "usb.core": None}  # import fails
        with mock.patch.object(ft, "_load_d2xx", no_d2xx):
            with mock.patch.object(fl, "list_usb_devices", lambda: [_USB_FP5]):
                self.assertEqual(ft.list_ftdi_targets(), ["usb:Embedded FlashPro5 A"])
                # Without D2XX a plain selector picks from libusb's channels.
                with mock.patch.dict(sys.modules, pyusb):
                    self.assertEqual(ft._list_devices("Embedded FlashPro5 A"), [_USB_FP5])
                # Without pyusb either, the D2XX error says what to install.
                with mock.patch.dict(sys.modules, no_pyusb_module):
                    with self.assertRaisesRegex(RuntimeError, "D2XX library missing"):
                        ft._list_devices("Embedded FlashPro5 A")
            with mock.patch.object(fl, "list_usb_devices", no_pyusb):
                with self.assertRaisesRegex(RuntimeError, "D2XX library missing"):
                    ft.list_ftdi_targets()


if __name__ == "__main__":
    unittest.main()
