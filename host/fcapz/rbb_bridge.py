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
bound by OpenOCD's batching, not by a round trip per bit.  On an adapter
without working pin commands (some FT2232-compatible clones), each rising
TCK edge becomes a clocked MPSSE command instead; see :class:`Bitbang`.
TRST (``t``/``u``) drives the adapter's nTRST pin where it has a known one (FlashPro); SRST and
the LED (``B``/``b``) are not wired and are ignored.  The sleeps OpenOCD
sends with ``remote_bitbang use_remote_sleep on`` (``Z`` 1 ms, ``z`` 1 us)
are kept, in stream order.
"""

from __future__ import annotations

import socket
import time
from typing import Callable, NamedTuple, Protocol

#: ADBUS bits of an MPSSE JTAG channel.
TCK, TDI, TDO, TMS = 0x01, 0x02, 0x04, 0x08

DEFAULT_PORT = 3335
_SET_PINS, _READ_PINS, _SEND_IMMEDIATE = 0x80, 0x81, 0x87
# Clock TMS out (bit 0; TDI held at bit 7), the second with TDO in on the
# rising edge; for one bit, TDO lands in bit 7 of the reply.
_TMS_OUT, _TMS_IN, _TMS_IN_TDO = 0x4B, 0x6B, 0x80


class PinPort(Protocol):
    """What the bridge needs from the adapter: :class:`FtdiMpsseTransport`
    after :meth:`~fcapz.ftdi_transport.FtdiMpsseTransport.open_pins`."""

    def exchange(self, commands: bytes, reply_bytes: int) -> bytes: ...


class PinIo(NamedTuple):
    """MPSSE *commands*, and the TDO bit of each reply byte they return, in
    order: ``TDO`` for a pin read (``0x81``), ``0x80`` for a clocked one."""

    commands: bytes
    masks: bytes

    @property
    def reads(self) -> int:
        return len(self.masks)


class Sleep(NamedTuple):
    seconds: float


class BitbangError(RuntimeError):
    """A ``remote_bitbang`` request this adapter cannot carry out."""


class Bitbang:
    """Turns ``remote_bitbang`` characters into MPSSE commands and sleeps.

    *value* and *direction* are the adapter's ADBUS layout; its non-JTAG pins
    (buffer enables) keep their level.  *trst* is the adapter's active-low
    nTRST pin mask, or 0 when it has none (reset characters are then
    ignored).  TRST state carries across :meth:`feed` calls.

    *gpio* False is for adapters whose MPSSE pin commands (``0x80`` write,
    ``0x81`` read) do nothing (some FT2232-compatible clones); only the
    clocked commands work there.  Each rising TCK edge then becomes a 1-bit
    ``0x4B``, which sets TMS and TDI, raises TCK and lowers it again; a
    TCK-low write only sets the levels for the next edge.  OpenOCD scans
    each bit as TCK low, sample, TCK high, so a sample and the rising edge
    after it become one 1-bit ``0x6B``, which also reads TDO on that edge.
    A sample followed by anything but a rising edge raises
    :class:`BitbangError`; a sample at the end of a buffer waits for the
    next one.  TRST is not driven.
    """

    def __init__(self, value: int, direction: int, trst: int = 0, *,
                 gpio: bool = True) -> None:
        self.direction = direction & 0xFF
        self.base = value & ~(TCK | TDI | TMS) & 0xFF
        self.jtag = value & (TCK | TDI | TMS)
        self.gpio = gpio
        self.trst = trst & 0xFF if gpio else 0
        #: Without GPIO: a sample waiting for the rising edge it is read on.
        self.pending = False
        if self.trst:
            self.base |= self.trst  # deasserted

    def feed(self, data: bytes) -> tuple[list[PinIo | Sleep], bool]:
        """Return the operations for *data*, in order, and whether a ``Q``
        ended the session.  Characters after ``Q`` are dropped."""
        ops: list[PinIo | Sleep] = []
        cmd = bytearray()
        masks = bytearray()
        sleep_us = 0

        def flush_io() -> None:
            nonlocal cmd, masks
            if cmd:
                if masks:
                    cmd.append(_SEND_IMMEDIATE)
                ops.append(PinIo(bytes(cmd), bytes(masks)))
            cmd, masks = bytearray(), bytearray()

        def flush_sleep() -> None:
            nonlocal sleep_us
            if sleep_us:
                ops.append(Sleep(sleep_us / 1e6))
            sleep_us = 0

        for c in data:
            if 0x30 <= c <= 0x37:  # '0'..'7': bit 2 TCK, bit 1 TMS, bit 0 TDI
                flush_sleep()
                v = c - 0x30
                jtag = (TCK if v & 4 else 0) | (TMS if v & 2 else 0) | (TDI if v & 1 else 0)
                if self.gpio:
                    cmd += bytes((_SET_PINS, self.base | jtag, self.direction))
                else:
                    rising = bool(jtag & TCK) and not self.jtag & TCK
                    if self.pending and not rising:
                        self._unpaired(c)
                    if rising:
                        tms_tdi = (0x80 if v & 1 else 0) | (1 if v & 2 else 0)
                        if self.pending:
                            cmd += bytes((_TMS_IN, 0, tms_tdi))
                            masks.append(_TMS_IN_TDO)
                            self.pending = False
                        else:
                            cmd += bytes((_TMS_OUT, 0, tms_tdi))
                self.jtag = jtag
            elif c == 0x52:  # 'R': sample TDO
                flush_sleep()
                if self.gpio:
                    cmd.append(_READ_PINS)
                    masks.append(TDO)
                elif self.pending:
                    self._unpaired(c)
                else:
                    self.pending = True
            elif 0x72 <= c <= 0x75:  # 'r'..'u': bit 1 TRST, bit 0 SRST asserted
                if self.trst:
                    flush_sleep()
                    if (c - 0x72) & 2:
                        self.base &= ~self.trst & 0xFF
                    else:
                        self.base |= self.trst
                    cmd += bytes((_SET_PINS, self.base | self.jtag, self.direction))
            elif c in (0x5A, 0x7A):  # 'Z' 1 ms, 'z' 1 us, after what came before
                if self.pending:
                    self._unpaired(c)
                flush_io()
                sleep_us += 1000 if c == 0x5A else 1
            elif c == 0x51:  # 'Q'
                if self.pending:
                    self._unpaired(c)
                flush_sleep()
                flush_io()
                return ops, True
            # 'B'/'b' LED, SWD characters: not wired.
        flush_sleep()
        flush_io()
        return ops, False

    @staticmethod
    def _unpaired(c: int) -> None:
        raise BitbangError(
            "TDO sample not followed by a rising TCK edge: this adapter has no "
            "pin I/O, so it reads TDO only on a clock edge "
            f"(got {chr(c)!r} after 'R')"
        )


def tdo_reply(pin_bytes: bytes, masks: bytes) -> bytes:
    """The ``remote_bitbang`` answer (``'0'``/``'1'`` per read) to the reply
    bytes of a :class:`PinIo`, each tested with its mask."""
    if len(pin_bytes) != len(masks):
        raise BitbangError(f"adapter returned {len(pin_bytes)} reads for {len(masks)}")
    return bytes(0x31 if b & m else 0x30 for b, m in zip(pin_bytes, masks))


#: How long a sample may wait for the rising edge it is read on.
PENDING_TIMEOUT_S = 2.0


def serve_client(conn: socket.socket, pins: PinPort, bitbang: Bitbang) -> bool:
    """Serve one OpenOCD connection until it closes; return whether it
    sent ``Q``."""
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    while True:
        conn.settimeout(PENDING_TIMEOUT_S if bitbang.pending else None)
        try:
            data = conn.recv(1 << 16)
        except socket.timeout:
            raise BitbangError(
                "TDO sample still waiting for its rising TCK edge: this adapter "
                "has no pin I/O, so it reads TDO only on a clock edge"
            ) from None
        if not data:
            return False
        ops, quit_ = bitbang.feed(data)
        for op in ops:
            if isinstance(op, Sleep):
                time.sleep(op.seconds)
                continue
            reply = pins.exchange(op.commands, op.reads)
            if op.reads:
                conn.sendall(tdo_reply(reply, op.masks))
        if quit_:
            return True


def serve(
    pins: PinPort,
    layout: tuple[int, int],
    *,
    trst: int = 0,
    port: int = DEFAULT_PORT,
    host: str = "127.0.0.1",
    once: bool = False,
    log: Callable[[str], None] = print,
    ready: Callable[[int], None] | None = None,
    gpio: bool = True,
) -> None:
    """Accept OpenOCD connections on *host*:*port*, one at a time.

    Runs until a client sends ``Q`` (OpenOCD does on ``shutdown``) or, with
    *once*, until the first client leaves.  A connection that drops, or asks
    for what the adapter cannot do (:class:`BitbangError`), is logged and
    closed, and the next one accepted; an adapter error ends the server.
    *trst* is the adapter's nTRST pin mask (0: none).  *gpio* is whether
    the adapter's pin commands work (:class:`Bitbang`).  *ready* is called
    with the bound port once listening (port 0 picks a free one).
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
            quit_ = False
            try:
                with conn:
                    quit_ = serve_client(
                        conn, pins, Bitbang(value, direction, trst, gpio=gpio)
                    )
            except ConnectionError as exc:
                log(f"OpenOCD connection lost: {exc}")
            except BitbangError as exc:
                log(f"OpenOCD connection closed: {exc}")
            else:
                log("OpenOCD disconnected" + (" (quit)" if quit_ else ""))
            if quit_ or once:
                return


def openocd_config(port: int, host: str = "127.0.0.1", *, trst: bool = False) -> str:
    """The OpenOCD adapter lines that reach this bridge.  Without a TRST pin
    they also say ``reset_config none``: a ``trst_only`` config would rely on
    a reset that never happens."""
    return (
        "adapter driver remote_bitbang\n"
        f"remote_bitbang host {host}\n"
        f"remote_bitbang port {port}\n"
        "transport select jtag\n"
        + ("" if trst else "reset_config none\n")
    )
