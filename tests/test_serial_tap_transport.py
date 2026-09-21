# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Unit tests for SerialTapTransport (UART virtual-JTAG TAP).

The fake port below emulates ``rtl/fcapz_uart_tap.v`` closely enough to
exercise the host framing: identity probe, DR scan payload packing, and the
two-scan read shape that ``jtag_reg_iface`` imposes.  The RTL side of the same
protocol is covered by ``tb/fcapz_uart_tap_tb.sv``.
"""

from __future__ import annotations

import sys
import types

import pytest

from fcapz.transport import SerialTapTransport


class FakeTapPort:
    """Minimal stand-in for ``serial.Serial`` speaking the bridge protocol."""

    def __init__(self, *, num_chains=4, max_dr_bits=256, magic=b"FCZU", version=1):
        self.num_chains = num_chains
        self.max_dr_bits = max_dr_bits
        self.magic = magic
        self.version = version

        self._rx = bytearray()      # bytes the host has written
        self._tx = bytearray()      # bytes waiting to be read back
        self.closed = False

        # Modelled register file behind jtag_reg_iface.
        self.mem: dict[int, int] = {}
        self._cur_addr = 0
        self._sr = 0
        self.idle_calls: list[int] = []
        self.scans: list[tuple[int, int]] = []   # (chain, width)

    # -- serial.Serial surface ---------------------------------------------
    def write(self, data):
        self._rx.extend(data)
        self._drain()
        return len(data)

    def read(self, n):
        out = bytes(self._tx[:n])
        del self._tx[:n]
        return out

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def reset_input_buffer(self):
        self._tx.clear()

    def reset_output_buffer(self):
        self._rx.clear()

    # -- protocol ----------------------------------------------------------
    def _reply(self, status, payload=b""):
        self._tx.extend(bytes([0xA5, status]) + payload)

    def _drain(self):
        while self._rx:
            if self._rx[0] != 0x5A:          # hunt for SOF, as the RTL does
                del self._rx[0]
                continue
            if len(self._rx) < 2:
                return
            cmd = self._rx[1]

            if cmd == 0x03:                  # INFO
                del self._rx[:2]
                self._reply(0x00, self.magic
                            + bytes([self.version, self.num_chains])
                            + self.max_dr_bits.to_bytes(2, "little"))
            elif cmd == 0x02:                # IDLE
                if len(self._rx) < 4:
                    return
                self.idle_calls.append(int.from_bytes(self._rx[2:4], "little"))
                del self._rx[:4]
                self._reply(0x00)
            elif cmd == 0x01:                # SCAN
                if len(self._rx) < 5:
                    return
                chain = self._rx[2]
                width = int.from_bytes(self._rx[3:5], "little")
                if width == 0 or width > self.max_dr_bits:
                    del self._rx[:5]
                    self._reply(0x03)        # BAD_WIDTH, payload not consumed
                    continue
                nb = (width + 7) // 8
                if len(self._rx) < 5 + nb:
                    return
                payload = bytes(self._rx[5:5 + nb])
                del self._rx[:5 + nb]
                if chain == 0 or chain > self.num_chains:
                    self._reply(0x02)        # BAD_CHAIN, payload consumed
                    continue
                self.scans.append((chain, width))
                self._reply(0x00, self._do_scan(chain, width, payload, nb))
            else:
                del self._rx[:2]
                self._reply(0x01)

    def _do_scan(self, chain, width, payload, nb):
        shifted_in = int.from_bytes(payload, "little") & ((1 << width) - 1)
        if chain != 1 or width != 49:
            # Non-register chains just echo, like a plain shift register.
            return shifted_in.to_bytes(nb, "little")

        # CAPTURE replaces sr[31:0] with the addressed register's value; the
        # scan then shifts that captured word out while the new frame shifts in.
        captured = (self._sr & ~0xFFFFFFFF) | self.mem.get(self._cur_addr, 0)
        self._sr = shifted_in

        # UPDATE latches the new frame.
        rnw = (shifted_in >> 48) & 1
        addr = (shifted_in >> 32) & 0xFFFF
        data = shifted_in & 0xFFFFFFFF
        self._cur_addr = addr
        if rnw:
            self.mem[addr] = data

        return (captured & ((1 << width) - 1)).to_bytes(nb, "little")


@pytest.fixture
def fake_serial(monkeypatch):
    """Install a fake ``serial`` module whose Serial() returns our port."""
    created = {}

    def _serial_factory(port, baudrate, timeout=None):
        created["port"] = port
        created["baudrate"] = baudrate
        created["timeout"] = timeout
        return created.setdefault("obj", FakeTapPort())

    module = types.ModuleType("serial")
    module.Serial = _serial_factory
    monkeypatch.setitem(sys.modules, "serial", module)
    return created


def _connect(fake_serial, **kwargs):
    t = SerialTapTransport("COM_TEST", **kwargs)
    t.connect()
    return t, fake_serial["obj"]


# -- identity ---------------------------------------------------------------

def test_connect_reads_identity(fake_serial):
    t, _ = _connect(fake_serial)
    assert t.proto_version == 1
    assert t.num_chains == 4
    assert t.max_dr_bits == 256
    assert fake_serial["port"] == "COM_TEST"
    assert fake_serial["baudrate"] == 1_000_000


def test_connect_rejects_wrong_magic(fake_serial):
    fake_serial["obj"] = FakeTapPort(magic=b"XXXX")
    t = SerialTapTransport("COM_TEST")
    with pytest.raises(RuntimeError, match="no fcapz UART TAP"):
        t.connect()


def test_connect_rejects_future_protocol(fake_serial):
    fake_serial["obj"] = FakeTapPort(version=2)
    t = SerialTapTransport("COM_TEST")
    with pytest.raises(RuntimeError, match="unsupported .* protocol version"):
        t.connect()


def test_missing_pyserial_is_actionable(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial", None)
    t = SerialTapTransport("COM_TEST")
    with pytest.raises(RuntimeError, match="pyserial"):
        t.connect()


# -- register access --------------------------------------------------------

def test_write_then_read_roundtrip(fake_serial):
    t, port = _connect(fake_serial)
    t.write_reg(0x0010, 0xDEADBEEF)
    assert port.mem[0x0010] == 0xDEADBEEF
    assert t.read_reg(0x0010) == 0xDEADBEEF


def test_read_uses_two_scans_with_idle_between(fake_serial):
    """The read shape must match the JTAG transports, or CAPTURE races UPDATE."""
    t, port = _connect(fake_serial)
    port.mem[0x0020] = 0x12345678
    port.scans.clear()
    port.idle_calls.clear()

    assert t.read_reg(0x0020) == 0x12345678
    assert port.scans == [(1, 49), (1, 49)]
    assert port.idle_calls == [SerialTapTransport.READ_IDLE_CYCLES]


def test_write_reg_masks_to_32_bits(fake_serial):
    t, port = _connect(fake_serial)
    t.write_reg(0x0004, 0x1_FFFF_FFFF)
    assert port.mem[0x0004] == 0xFFFFFFFF


def test_read_block_reads_consecutive_word_addresses(fake_serial):
    t, port = _connect(fake_serial)
    for i in range(4):
        port.mem[0x0100 + i * 4] = 0xA0 + i
    assert t.read_block(0x0100, 4) == [0xA0, 0xA1, 0xA2, 0xA3]


# -- raw scans --------------------------------------------------------------

def test_raw_dr_scan_roundtrips_256_bit_burst(fake_serial):
    t, port = _connect(fake_serial)
    value = (0xA5 << 248) | (0x3C << 120) | 0xC5
    assert t.raw_dr_scan(value, 256, chain=2) == value
    assert port.scans[-1] == (2, 256)


def test_raw_dr_scan_rejects_width_over_bridge_max(fake_serial):
    t, _ = _connect(fake_serial)
    with pytest.raises(ValueError, match="exceeds the bridge"):
        t.raw_dr_scan(0, 257)


def test_raw_dr_scan_rejects_zero_width(fake_serial):
    t, _ = _connect(fake_serial)
    with pytest.raises(ValueError, match="width must be >= 1"):
        t.raw_dr_scan(0, 0)


def test_scan_payload_is_byte_packed_little_endian(fake_serial):
    """A 49-bit frame travels as 7 bytes, LSB first -- the RTL indexes them."""
    t, port = _connect(fake_serial)
    port._rx.clear()
    t.write_reg(0xBEEF, 0x11223344)
    # Re-derive what the register file saw; a packing slip would corrupt it.
    assert port.mem[0xBEEF] == 0x11223344


# -- chain selection --------------------------------------------------------

def test_select_chain_changes_target(fake_serial):
    t, port = _connect(fake_serial)
    t.select_chain(3)
    t.raw_dr_scan(0x5A, 8)
    assert port.scans[-1][0] == 3


def test_select_chain_rejects_out_of_range(fake_serial):
    t, _ = _connect(fake_serial)
    with pytest.raises(ValueError, match="out of range"):
        t.select_chain(9)
    with pytest.raises(ValueError, match="out of range"):
        t.select_chain(0)


def test_bridge_error_status_is_reported(fake_serial):
    t, _ = _connect(fake_serial)
    # Bypass the host-side guard to prove the bridge's status is surfaced.
    with pytest.raises(RuntimeError, match="chain out of range"):
        t.raw_dr_scan(0, 8, chain=9)


# -- connection handling ----------------------------------------------------

def test_calls_before_connect_raise(fake_serial):
    t = SerialTapTransport("COM_TEST")
    with pytest.raises(RuntimeError, match="not connected"):
        t.read_reg(0)


def test_close_is_idempotent(fake_serial):
    t, port = _connect(fake_serial)
    t.close()
    t.close()
    assert port.closed


def test_short_reply_raises(fake_serial):
    t, port = _connect(fake_serial)

    def _silent(_data):
        return 0

    port.write = _silent          # bridge stops answering
    with pytest.raises(RuntimeError, match="did not reply"):
        t.read_reg(0)
