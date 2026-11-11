# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""FTDI MPSSE byte I/O through libusb (pyusb), for :mod:`fcapz.ftdi_transport`.

The D2XX path needs FTDI's driver.  This one talks to the chip directly
through libusb, so it works where D2XX does not: an adapter bound to WinUSB
or libusbK on Windows (as OpenOCD and several vendor tools set it up), and
Linux or macOS without FTDI's library.  Install it with
``pip install fpgacapzero[usb]`` (pyusb plus a bundled libusb).

Name a libusb channel with a ``usb:`` selector: ``usb:`` alone picks the
known JTAG adapter, ``usb:Digilent USB Device A`` names it by description and
``usb:210319A5F2B0A`` by serial.  Channels are named as D2XX names them: the
USB product string, then the channel letter on a multi-channel chip, and
the USB serial number with the same letter.
"""

from __future__ import annotations

import sys
import threading
import time

from .ftdi_transport import FtdiDevice

#: Vendor IDs of FTDI-based JTAG adapters: FTDI's own, and Microchip's
#: (embedded FlashPro5).
FTDI_VIDS = (0x0403, 0x1514)

# FTDI vendor requests (to the device, wIndex = channel number from 1).
_SIO_RESET = 0x00
_SIO_SET_FLOW_CTRL = 0x02
_SIO_SET_LATENCY_TIMER = 0x09
_SIO_SET_BITMODE = 0x0B
_RESET_SIO, _PURGE_RX, _PURGE_TX = 0, 1, 2
_RTS_CTS_HS = 0x0100  # flow control, in wIndex's high byte (as D2XX sets it)
_BITMODE_RESET, _BITMODE_MPSSE = 0x0000, 0x0200

#: Channels per chip, by bcdDevice: FT2232C/D, FT2232H, FT4232H.  Every
#: other FTDI chip with MPSSE (FT232H) has one.
_CHANNELS_BY_BCD = {0x0500: 2, 0x0700: 2, 0x0800: 4}

_INSTALL_HINT = (
    "install the libusb backend with: pip install fpgacapzero[usb]"
)


def _usb():
    """Import pyusb, or explain how to get it."""
    try:
        import usb.core
        import usb.util
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError(f"usb: devices need pyusb ({exc}); {_INSTALL_HINT}") from exc
    return usb


def _backends() -> list[tuple[str, object]]:
    """The libusb backends to enumerate, libusb-1.0 first: the bundled one
    from ``libusb_package`` when installed, else the system's; then
    libusb-0.1 (libusb-win32 on Windows), which reaches adapters bound to
    libusb0.sys."""
    _usb()
    import usb.backend.libusb0
    import usb.backend.libusb1

    found: list[tuple[str, object]] = []
    be = None
    try:
        import libusb_package

        be = libusb_package.get_libusb1_backend()
    except ImportError:
        pass
    if be is None:
        be = usb.backend.libusb1.get_backend()
    if be is not None:
        found.append(("libusb1", be))
    be0 = usb.backend.libusb0.get_backend()
    if be0 is not None:
        found.append(("libusb0", be0))
    return found


def list_usb_devices() -> list[FtdiDevice]:
    """Every FTDI channel libusb can open, named as D2XX names it.

    A device whose strings cannot be read is left out: its driver (FTDI's
    own, on Windows) keeps libusb away, and D2XX lists it instead.  A chip
    that two backends both reach is listed once, from libusb-1.0, if it has
    a serial number; without one it cannot be told from a twin, so each
    backend's entry stays.
    """
    usb = _usb()
    out: list[FtdiDevice] = []
    # Channels from earlier backends: a later backend's entry with the same
    # serial is the same chip.  Within one backend every location is kept,
    # clones that share a serial included.
    earlier: set[tuple[int, str, int]] = set()
    for name, be in _backends():
        found_here: set[tuple[int, str, int]] = set()
        try:
            devices = list(usb.core.find(find_all=True, backend=be,
                                         custom_match=lambda d: d.idVendor in FTDI_VIDS))
        except usb.core.USBError:
            continue
        for dev in devices:
            try:
                product = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ""
                serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else ""
                numbers = sorted({intf.bInterfaceNumber for cfg in dev for intf in cfg})
            except (usb.core.USBError, ValueError, NotImplementedError):
                continue
            multi = len(numbers) > 1 or _CHANNELS_BY_BCD.get(dev.bcdDevice, 1) > 1
            usb_id = dev.idVendor << 16 | dev.idProduct
            for number in numbers:
                if number > 3:
                    continue
                letter = "ABCD"[number]
                key = (usb_id, serial, number)
                if serial and key in earlier:
                    continue
                found_here.add(key)
                out.append(
                    FtdiDevice(
                        index=len(out),
                        description=f"{product or 'FTDI'} {letter}" if multi else product,
                        serial=serial + letter if multi and serial else serial,
                        usb_id=usb_id,
                        opened=False,
                        backend="libusb",
                        interface=number,
                        location=f"{name}:{dev.bus}:{dev.address}",
                    )
                )
        earlier |= found_here
    return out


class _PyusbPort:
    """One FTDI channel's bulk endpoints and vendor requests through pyusb:
    the transport-facing contract of :class:`LibusbIo`.

    ``read`` returns the raw USB data, modem-status bytes included, and
    ``b""`` on a timeout; ``write`` returns the bytes sent."""

    def __init__(self, dev, interface: int, timeout_ms: int) -> None:
        usb = _usb()
        self._usb = usb
        self.dev = dev
        self.interface = interface
        self.timeout_ms = timeout_ms
        self._reattach = False
        self._claimed = False
        try:
            cfg = dev.get_active_configuration()
        except usb.core.USBError:
            # Unconfigured (some Linux setups): configure it.  A configured
            # device is left alone: setting it again resets the other
            # channels, which another program may be using.
            dev.set_configuration()
            cfg = dev.get_active_configuration()
        intf = usb.util.find_descriptor(cfg, bInterfaceNumber=interface)
        if intf is None:
            raise RuntimeError(f"USB device has no interface {interface}")
        if sys.platform.startswith("linux"):
            try:
                if dev.is_kernel_driver_active(interface):
                    dev.detach_kernel_driver(interface)  # ftdi_sio, this channel only
                    self._reattach = True
            except (usb.core.USBError, NotImplementedError):
                pass
        try:
            usb.util.claim_interface(dev, interface)
        except Exception:
            self.close()  # gives the channel back to its kernel driver
            raise
        self._claimed = True

        def direction(want):
            return lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == want

        self.ep_out = usb.util.find_descriptor(intf, custom_match=direction(usb.util.ENDPOINT_OUT))
        self.ep_in = usb.util.find_descriptor(intf, custom_match=direction(usb.util.ENDPOINT_IN))
        if self.ep_out is None or self.ep_in is None:
            self.close()
            raise RuntimeError(f"USB interface {interface} has no bulk endpoint pair")
        self.packet_size = int(self.ep_in.wMaxPacketSize)

    def ctrl(self, request: int, value: int, index: int = 0) -> None:
        self.dev.ctrl_transfer(
            0x40, request, value, index | (self.interface + 1), None, self.timeout_ms
        )

    def write(self, data: bytes, timeout_ms: int) -> int:
        try:
            return int(self.ep_out.write(data, max(1, timeout_ms)))
        except self._usb.core.USBTimeoutError as exc:
            # libusb does not say how much went out before the timeout.
            raise RuntimeError(f"FTDI write timed out ({len(data)} bytes queued)") from exc

    def read(self, size: int, timeout_ms: int) -> bytes:
        try:
            return bytes(self.ep_in.read(size, max(1, timeout_ms)))
        except self._usb.core.USBTimeoutError:
            return b""

    def close(self) -> None:
        usb = self._usb
        try:
            if self._claimed:
                usb.util.release_interface(self.dev, self.interface)
                self._claimed = False
            if self._reattach:
                self.dev.attach_kernel_driver(self.interface)
                self._reattach = False
        except (usb.core.USBError, NotImplementedError):
            pass
        finally:
            usb.util.dispose_resources(self.dev)


def open_port(dev: FtdiDevice, timeout_ms: int) -> _PyusbPort:
    """Open the libusb channel *dev* (from :func:`list_usb_devices`)."""
    usb = _usb()
    name, bus, address = dev.location.split(":")
    backend = dict(_backends()).get(name)
    found = None
    if backend is not None:
        found = usb.core.find(backend=backend, custom_match=lambda d: (
            d.bus == int(bus) and d.address == int(address)
            and (d.idVendor << 16 | d.idProduct) == dev.usb_id
        ))
    if found is not None and dev.serial:
        # A replug can hand the bus address to another adapter.
        try:
            serial = usb.util.get_string(found, found.iSerialNumber) or ""
        except (usb.core.USBError, ValueError):
            serial = None
        if serial is None or dev.serial not in (serial, serial + "ABCD"[dev.interface]):
            found = None
    if found is None:
        raise RuntimeError(f"USB device for {dev.description!r} is gone (unplugged?)")
    try:
        return _PyusbPort(found, dev.interface, timeout_ms)
    except usb.core.USBError as exc:
        hint = (
            "bind it to WinUSB or libusbK (e.g. with Zadig), or use its D2XX name"
            if sys.platform == "win32" else
            "check the udev rules / permissions for the adapter"
        )
        raise RuntimeError(f"cannot open USB channel {dev.description!r} ({exc}); {hint}") from exc


class LibusbIo:
    """Byte I/O on one MPSSE channel through libusb, for the transport.

    Same contract as the D2XX one: :meth:`setup`, :meth:`write`,
    :meth:`read`, :meth:`transfer`, :meth:`close`.  Unlike D2XX, nothing
    reads from the chip unless the host asks: when its reply buffer is full
    MPSSE stops taking commands, so a long command whose reply outgrows that
    buffer would stall its own write.  :meth:`transfer` therefore reads on a
    second thread while it writes once the reply could overflow the
    smallest chip buffer (FT232H: 1 KB).

    Every USB packet from the chip starts with two modem-status bytes,
    stripped here by the endpoint's packet size (64 full speed, 512 high).
    """

    backend = "libusb"
    #: Reply bytes any high-speed chip buffers whole (FT232H: 1 KB): up to
    #: this a transfer is a plain write then read.
    DIRECT_REPLY_BYTES = 512
    #: The same for a full-speed chip (64-byte packets): the FT2232D holds
    #: 384 reply bytes and 128 command bytes.
    DIRECT_REPLY_BYTES_FULL_SPEED = 256
    #: Largest single bulk read request.
    MAX_READ = 0x10000

    def __init__(self, port, timeout_ms: int = 2000) -> None:
        self.port = port
        self.timeout_ms = timeout_ms
        self.closed = False
        self._rx = bytearray()
        #: A transfer's reader still running after the transfer failed.
        self._reader: threading.Thread | None = None
        #: Port release left to that reader (see :meth:`close`).
        self._release_lock = threading.Lock()
        self._release_pending = False

    def setup(self, timeout_ms: int) -> None:
        """Reset the channel and put it in MPSSE mode (as D2XX does)."""
        self.timeout_ms = timeout_ms
        ctrl = self.port.ctrl
        ctrl(_SIO_RESET, _RESET_SIO)
        ctrl(_SIO_SET_LATENCY_TIMER, 1)
        ctrl(_SIO_SET_FLOW_CTRL, 0, _RTS_CTS_HS)
        ctrl(_SIO_SET_BITMODE, _BITMODE_RESET)
        ctrl(_SIO_SET_BITMODE, _BITMODE_MPSSE)
        ctrl(_SIO_RESET, _PURGE_RX)
        ctrl(_SIO_RESET, _PURGE_TX)
        self._drain()

    def _drain(self) -> None:
        """Drop what the chip still holds from before (a purge does not
        reach bytes already on their way)."""
        self._rx.clear()
        ps = self.port.packet_size
        for _ in range(64):
            raw = self.port.read(4 * ps, 20)
            if len(raw) <= 2:
                return

    def write(self, data: bytes, deadline: float | None = None) -> None:
        if deadline is None:
            deadline = time.monotonic() + self.timeout_ms / 1000
        view = memoryview(data)
        while view:
            left_ms = int((deadline - time.monotonic()) * 1000)
            if left_ms <= 0:
                raise RuntimeError(f"FTDI write timed out: {len(data) - len(view)} of "
                                   f"{len(data)} bytes")
            sent = self.port.write(bytes(view), left_ms)
            if sent <= 0:
                raise RuntimeError(f"FTDI write short: {len(data) - len(view)} of "
                                   f"{len(data)} bytes")
            view = view[sent:]

    def read(self, n: int, deadline: float | None = None) -> bytes:
        if n == 0:
            return b""
        if deadline is None:
            deadline = time.monotonic() + self.timeout_ms / 1000
        ps = self.port.packet_size
        payload = ps - 2
        while len(self._rx) < n:
            left_ms = int((deadline - time.monotonic()) * 1000)
            if left_ms <= 0:
                raise RuntimeError(
                    f"FTDI read timed out: {len(self._rx)} of {n} bytes (adapter "
                    "unplugged or held by another program?)"
                )
            want = n - len(self._rx)
            packets = -(-want // payload)
            size = min(packets * ps, self.MAX_READ - self.MAX_READ % ps)
            raw = self.port.read(size, left_ms)
            for i in range(0, len(raw), ps):  # each packet: 2 status bytes, data
                self._rx += raw[i + 2:i + ps]
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def transfer(self, cmd: bytes, reply_bytes: int) -> bytes:
        """Send *cmd* and read its *reply_bytes* bytes of reply, reading
        while writing when the reply could fill the chip's buffer."""
        deadline = time.monotonic() + self.timeout_ms / 1000
        direct = (self.DIRECT_REPLY_BYTES_FULL_SPEED if self.port.packet_size <= 64
                  else self.DIRECT_REPLY_BYTES)
        if reply_bytes <= direct:
            self.write(cmd, deadline)
            return self.read(reply_bytes, deadline)
        result: list = []

        def reader() -> None:
            try:
                result.append(self.read(reply_bytes, deadline))
            except BaseException as exc:  # handed to the caller below
                result.append(exc)
            finally:
                with self._release_lock:
                    release, self._release_pending = self._release_pending, False
                if release:
                    self._release_port()

        thread = threading.Thread(target=reader, name="fcapz-ftdi-read", daemon=True)
        thread.start()
        try:
            self.write(cmd, deadline)
        finally:
            # The reader ends by the same deadline; never leave it running
            # on the port.
            thread.join(max(0.0, deadline - time.monotonic()) + 1.0)
            if thread.is_alive():
                self._reader = thread  # close() waits for it
        if thread.is_alive() or not result:
            raise RuntimeError("FTDI read did not finish")
        if isinstance(result[0], BaseException):
            raise result[0]
        return result[0]

    def close(self) -> None:
        """Leave MPSSE mode and release the channel (once)."""
        if self.closed:
            return
        self.closed = True
        reader, self._reader = self._reader, None
        if reader is not None:
            # A USB read still in flight must end before the device goes.
            reader.join(self.timeout_ms / 1000 + 1.0)
            with self._release_lock:
                if reader.is_alive():
                    # Still in the backend (libusb-win32 can wait without
                    # bound to cancel a timed-out read): the reader releases
                    # the port when it returns.  Until then the interface
                    # stays claimed, so nothing else can open it.
                    self._release_pending = True
                    return
        self._release_port()

    def _release_port(self) -> None:
        try:
            self.port.ctrl(_SIO_SET_BITMODE, _BITMODE_RESET)
        except Exception:
            pass
        finally:
            self.port.close()
