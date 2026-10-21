# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""OpenOCD ``remote_bitbang`` server on an FTDI MPSSE adapter.

On Windows the FTDI JTAG adapters that ship with vendor drivers (the PolarFire
kits' embedded FlashPro5, Digilent cables) are bound to the D2XX driver, which
OpenOCD's ``ftdi`` driver cannot open without replacing it (Zadig/WinUSB),
and that breaks the vendor tools.  This serves the adapter to OpenOCD over
its ``remote_bitbang`` protocol instead, through fcapz's own D2XX layer, so
OpenOCD and the vendor tools keep working side by side::

    fcapz openocd-bridge                 # then, in the OpenOCD config:
    adapter driver remote_bitbang
    remote_bitbang host 127.0.0.1
    remote_bitbang port 3335

Each protocol character becomes one MPSSE pin write (``0x80``) or pin read
(``0x81``); a received buffer is sent as one USB transfer, so throughput is
bound by OpenOCD's batching, not by a round trip per bit.  TRST/SRST
(``r``..``u``) and the LED (``B``/``b``) are not wired and are ignored.
"""

from __future__ import annotations

import socket
from typing import Callable, Protocol

#: ADBUS bits of an MPSSE JTAG channel.
TCK, TDI, TDO, TMS = 0x01, 0x02, 0x04, 0x08

DEFAULT_PORT = 3335
_SET_PINS, _READ_PINS, _SEND_IMMEDIATE = 0x80, 0x81, 0x87


class PinPort(Protocol):
    """What the bridge needs from the adapter: :class:`FtdiMpsseTransport`
    after :meth:`~fcapz.ftdi_transport.FtdiMpsseTransport.open_pins`."""

    def exchange(self, commands: bytes, reply_bytes: int) -> bytes: ...


def translate(data: bytes, value: int, direction: int) -> tuple[bytes, int, bool]:
    """Turn ``remote_bitbang`` characters into MPSSE commands.

    *value* and *direction* are the adapter's ADBUS layout; its non-JTAG pins
    (buffer enables) keep their level.  Returns ``(commands, reads, quit)``:
    the MPSSE bytes, how many TDO samples they read (each answered by one
    byte), and whether a ``Q`` ended the session.  Characters after ``Q``
    are dropped.
    """
    base = value & ~(TCK | TDI | TMS) & 0xFF
    cmd = bytearray()
    reads = 0
    for c in data:
        if 0x30 <= c <= 0x37:  # '0'..'7': bit 2 TCK, bit 1 TMS, bit 0 TDI
            v = c - 0x30
            pins = base
            if v & 4:
                pins |= TCK
            if v & 2:
                pins |= TMS
            if v & 1:
                pins |= TDI
            cmd += bytes((_SET_PINS, pins, direction & 0xFF))
        elif c == 0x52:  # 'R': sample TDO
            cmd.append(_READ_PINS)
            reads += 1
        elif c == 0x51:  # 'Q'
            return bytes(_flushed(cmd, reads)), reads, True
        # 'B'/'b' LED, 'r'..'u' resets, anything newer: not wired.
    return bytes(_flushed(cmd, reads)), reads, False


def _flushed(cmd: bytearray, reads: int) -> bytearray:
    if reads:
        cmd.append(_SEND_IMMEDIATE)
    return cmd


def tdo_reply(pin_bytes: bytes) -> bytes:
    """The ``remote_bitbang`` answer (``'0'``/``'1'`` per read) to the ADBUS
    bytes the reads returned."""
    return bytes(0x31 if b & TDO else 0x30 for b in pin_bytes)


def serve_client(
    conn: socket.socket, pins: PinPort, value: int, direction: int
) -> bool:
    """Serve one OpenOCD connection until it closes; return whether it
    sent ``Q``."""
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    while True:
        data = conn.recv(1 << 16)
        if not data:
            return False
        cmd, reads, quit_ = translate(data, value, direction)
        if cmd:
            reply = pins.exchange(cmd, reads)
            if reads:
                conn.sendall(tdo_reply(reply))
        if quit_:
            return True


def serve(
    pins: PinPort,
    layout: tuple[int, int],
    *,
    port: int = DEFAULT_PORT,
    host: str = "127.0.0.1",
    once: bool = False,
    log: Callable[[str], None] = print,
    ready: Callable[[int], None] | None = None,
) -> None:
    """Accept OpenOCD connections on *host*:*port*, one at a time.

    Runs until a client sends ``Q`` (OpenOCD does on ``shutdown``) or, with
    *once*, until the first client leaves.  *ready* is called with the bound
    port once listening (port 0 picks a free one).
    """
    value, direction = layout
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind((host, port))
        srv.listen(1)
        bound = srv.getsockname()[1]
        if ready is not None:
            ready(bound)
        while True:
            conn, peer = srv.accept()
            log(f"OpenOCD connected from {peer[0]}:{peer[1]}")
            with conn:
                quit_ = serve_client(conn, pins, value, direction)
            log("OpenOCD disconnected" + (" (quit)" if quit_ else ""))
            if quit_ or once:
                return


def openocd_config(port: int, host: str = "127.0.0.1") -> str:
    """The OpenOCD adapter lines that reach this bridge."""
    return (
        "adapter driver remote_bitbang\n"
        f"remote_bitbang host {host}\n"
        f"remote_bitbang port {port}\n"
        "transport select jtag\n"
    )
