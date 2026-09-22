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

from fcapz.transport import (
    SerialTapTransport,
    TapBridgeTransport,
    list_serial_ports,
)

ADDR_SAMPLE_W = TapBridgeTransport.ADDR_SAMPLE_W
ADDR_BURST_PTR = TapBridgeTransport.ADDR_BURST_PTR
ADDR_DATA_BASE = TapBridgeTransport.ADDR_DATA_BASE


class FakeTapPort:
    """Minimal stand-in for ``serial.Serial`` speaking the bridge protocol."""

    def __init__(self, *, num_chains=4, max_dr_bits=256, magic=b"FCZU",
                 version=2, extra=0, burst_chain=2):
        self.num_chains = num_chains
        self.burst_chain = burst_chain
        self.max_dr_bits = max_dr_bits
        self.magic = magic
        self.version = version
        self.extra = extra

        self._rx = bytearray()      # bytes the host has written
        self._tx = bytearray()      # bytes waiting to be read back
        self.closed = False

        # Modelled register file behind jtag_reg_iface.
        self.mem: dict[int, int] = {ADDR_SAMPLE_W: 8}
        self._cur_addr = 0
        self._sr = 0
        self.idle_calls: list[int] = []
        self.scans: list[tuple[int, int]] = []   # (chain, width)

        # Modelled burst chain behind jtag_burst_read: capture RAM plus the
        # queue of wide scan values a BURST_PTR write leaves behind.
        self.samples: list[int] = []
        self.timestamps: list[int] = []
        self.timestamp_width = 32
        self._burst_queue: list[int] = []
        self.breads: list[tuple[int, int, int]] = []   # (chain, width, count)

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
                            + self.max_dr_bits.to_bytes(2, "little")
                            + bytes([self.extra]))
            elif cmd == 0x02:                # IDLE
                if len(self._rx) < 4:
                    return
                self.idle_calls.append(int.from_bytes(self._rx[2:4], "little"))
                del self._rx[:4]
                self._reply(0x00)
            elif cmd == 0x04:                # BREAD
                if self.version < 2:
                    del self._rx[:2]
                    self._reply(0x01)            # BAD_FRAME on a v1 bridge
                    continue
                if len(self._rx) < 7:
                    return
                chain = self._rx[2]
                width = int.from_bytes(self._rx[3:5], "little")
                count = int.from_bytes(self._rx[5:7], "little")
                del self._rx[:7]
                if width == 0 or width > self.max_dr_bits:
                    self._reply(0x03)
                    continue
                if chain == 0 or chain > self.num_chains:
                    self._reply(0x02)
                    continue
                nb = (width + 7) // 8
                out = bytearray()
                for _ in range(count):
                    self.scans.append((chain, width))
                    out += self._do_scan(chain, width, bytes(nb), nb)
                self.breads.append((chain, width, count))
                self._reply(0x00, bytes(out))
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

    def _arm_burst(self, timestamp):
        """Pack the capture RAM into wide scan values, as jtag_burst_read does.

        The first entry is the priming scan: staging has not been loaded when
        the host's first wide CAPTURE happens, so the RTL returns junk there
        and the host must discard it.  Returning a deliberately wrong value
        makes a host that forgets to skip it fail loudly.
        """
        if timestamp:
            source, elem = self.timestamps, self.timestamp_width
        else:
            source, elem = self.samples, max(1, self.mem.get(ADDR_SAMPLE_W, 8))
        per_scan = max(1, self.max_dr_bits // elem)
        mask = (1 << elem) - 1

        self._burst_queue = [(1 << self.max_dr_bits) - 1]     # priming junk
        for base in range(0, len(source), per_scan):
            word = 0
            for i, value in enumerate(source[base:base + per_scan]):
                word |= (value & mask) << (i * elem)
            self._burst_queue.append(word)

    def _do_scan(self, chain, width, payload, nb):
        shifted_in = int.from_bytes(payload, "little") & ((1 << width) - 1)
        if (
            chain == self.burst_chain
            and width == self.max_dr_bits
            and self._burst_queue
        ):
            # Armed: hand back staged capture data.  Unarmed, the burst chain
            # is just a shift register, which is what the raw-scan tests use.
            return self._burst_queue.pop(0).to_bytes(nb, "little")
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
            if addr == ADDR_BURST_PTR:
                self._arm_burst(bool(data & 0x80000000))

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
    assert t.proto_version == 2
    assert t.num_chains == 4
    assert t.max_dr_bits == 256
    assert fake_serial["port"] == "COM_TEST"
    assert fake_serial["baudrate"] == 1_000_000


def test_connect_rejects_wrong_magic(fake_serial):
    fake_serial["obj"] = FakeTapPort(magic=b"XXXX")
    t = SerialTapTransport("COM_TEST")
    with pytest.raises(RuntimeError, match="no fcapz TAP bridge"):
        t.connect()
    # A wrong port is exactly the case that fails here, and on Windows it is an
    # exclusive handle -- holding it would block the user's next attempt.
    assert fake_serial["obj"].closed


def test_connect_rejects_future_protocol(fake_serial):
    fake_serial["obj"] = FakeTapPort(version=99)
    t = SerialTapTransport("COM_TEST")
    with pytest.raises(RuntimeError, match="unsupported fcapz TAP bridge protocol version"):
        t.connect()
    assert fake_serial["obj"].closed


def test_burst_chain_is_excluded_from_generic_probing(fake_serial):
    t = SerialTapTransport("COM_TEST", burst_data_chain=2)
    assert t.unprobeable_chains == (2,)


def test_no_burst_leaves_every_chain_probeable(fake_serial):
    t = SerialTapTransport("COM_TEST", burst=False)
    assert t.unprobeable_chains == ()


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
    """Outside the DATA window read_block is still plain per-word reads."""
    t, port = _connect(fake_serial)
    for i in range(4):
        port.mem[0x0200 + i * 4] = 0xA0 + i
    assert t.read_block(0x0200, 4) == [0xA0, 0xA1, 0xA2, 0xA3]
    assert all(width == 49 for _chain, width in port.scans)


# -- burst readback ---------------------------------------------------------

def test_read_block_uses_the_burst_chain_for_the_data_window(fake_serial):
    t, port = _connect(fake_serial)
    port.samples = [(i * 7) & 0xFF for i in range(100)]
    port.scans.clear()

    assert t.read_block(ADDR_DATA_BASE, 100) == port.samples

    # One control scan arms BURST_PTR; the rest are wide scans on chain 2.
    # 100 samples at 8 bits is 32 per 256-bit scan -> 4 scans, plus the
    # priming scan the host must discard.
    wide = [s for s in port.scans if s == (2, 256)]
    assert len(wide) == 5
    assert port.mem[ADDR_BURST_PTR] == 0


def test_burst_takes_all_its_scans_in_one_command(fake_serial):
    """One round trip for the whole readback, not one per scan."""
    t, port = _connect(fake_serial)
    port.samples = [(i * 3) & 0xFF for i in range(100)]
    port.breads.clear()

    assert t.read_block(ADDR_DATA_BASE, 100) == port.samples
    # 4 data scans + 1 priming scan, asked for together.
    assert port.breads == [(2, 256, 5)]


def test_batched_scans_match_one_at_a_time_scans(fake_serial):
    """CMD_BREAD must be exactly N zero-payload CMD_SCANs, nothing subtler."""
    t, port = _connect(fake_serial)
    batched = t.batched_dr_scans(3, 256, chain=3)
    one_at_a_time = [t.raw_dr_scan(0, 256, chain=3) for _ in range(3)]
    assert batched == one_at_a_time


def test_batched_scans_reject_an_impossible_count(fake_serial):
    t, _ = _connect(fake_serial)
    with pytest.raises(ValueError, match="exceeds the 16-bit field"):
        t.batched_dr_scans(0x10000, 256)
    assert t.batched_dr_scans(0, 256) == []


def test_a_version_1_bridge_still_bursts_one_scan_at_a_time(fake_serial):
    """Older bridges predate CMD_BREAD; the readback must still work."""
    fake_serial["obj"] = FakeTapPort(version=1)
    t, port = _connect(fake_serial)
    assert t.proto_version == 1
    port.samples = [(i * 5) & 0xFF for i in range(64)]
    port.breads.clear()
    port.scans.clear()

    assert t.read_block(ADDR_DATA_BASE, 64) == port.samples
    assert port.breads == []
    assert len([s for s in port.scans if s == (2, 256)]) == 3


def test_burst_moves_far_fewer_bytes_than_per_word_reads(fake_serial):
    """The whole point: a wide scan carries 32 samples, a read_reg pair one."""
    t, port = _connect(fake_serial)
    port.samples = list(range(64))
    port.scans.clear()
    t.read_block(ADDR_DATA_BASE, 64)
    burst_scans = len(port.scans)

    port.scans.clear()
    t.read_block(0x0200, 64)
    assert len(port.scans) > 10 * burst_scans


def test_burst_discards_the_priming_scan(fake_serial):
    """The first wide CAPTURE happens before staging is loaded."""
    t, port = _connect(fake_serial)
    port.samples = [0x11] * 32
    assert t.read_block(ADDR_DATA_BASE, 32) == [0x11] * 32


def test_burst_respects_the_hardware_sample_width(fake_serial):
    t, port = _connect(fake_serial)
    port.mem[ADDR_SAMPLE_W] = 16          # 16 samples per 256-bit scan
    port.samples = [(i * 1234) & 0xFFFF for i in range(48)]
    assert t.read_block(ADDR_DATA_BASE, 48) == port.samples


def test_read_timestamp_block_uses_the_burst_chain(fake_serial):
    t, port = _connect(fake_serial)
    port.timestamp_width = 32
    port.timestamps = [i * 3 for i in range(24)]
    port.scans.clear()

    assert t.read_timestamp_block(0x0180, 24, 32) == port.timestamps
    assert port.mem[ADDR_BURST_PTR] == 0x80000000       # timestamp select
    assert any(s == (2, 256) for s in port.scans)


def test_no_burst_chain_falls_back_to_per_word_reads(fake_serial):
    """A single-chain bridge has no chain 2 to shift on."""
    fake_serial["obj"] = FakeTapPort(num_chains=1)
    t, port = _connect(fake_serial)
    for i in range(4):
        port.mem[ADDR_DATA_BASE + i * 4] = 0xB0 + i
    assert t.read_block(ADDR_DATA_BASE, 4) == [0xB0, 0xB1, 0xB2, 0xB3]
    assert all(chain == 1 for chain, _width in port.scans)


def test_burst_can_be_disabled(fake_serial):
    t = SerialTapTransport("COM_TEST", burst=False)
    t.connect()
    port = fake_serial["obj"]
    for i in range(4):
        port.mem[ADDR_DATA_BASE + i * 4] = 0xC0 + i
    assert t.read_block(ADDR_DATA_BASE, 4) == [0xC0, 0xC1, 0xC2, 0xC3]


def test_a_failed_burst_falls_back_and_stays_disabled(fake_serial):
    """A rejected wide scan must cost throughput, not the capture."""
    t, port = _connect(fake_serial)
    port.samples = list(range(32))
    for i in range(2):
        port.mem[ADDR_DATA_BASE + i * 4] = 0xD0 + i

    # The bridge now refuses chain 2 -- e.g. a bitstream whose ELA was built
    # without the burst chain, behind a bridge that still advertises it.
    port.num_chains = 1

    assert t.read_block(ADDR_DATA_BASE, 2) == [0xD0, 0xD1]
    assert t._has_burst is False

    # Still disabled on the next call: no retry storm per block.
    port.scans.clear()
    assert t.read_block(ADDR_DATA_BASE, 2) == [0xD0, 0xD1]
    assert all(chain == 1 for chain, _width in port.scans)


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


# -- the protocol engine is PHY-agnostic ------------------------------------

class MemoryTapTransport(TapBridgeTransport):
    """A TapBridgeTransport over a plain in-memory byte channel.

    Stands in for any non-serial PHY (SPI, USB-FIFO, TCP). It exists to pin the
    split: if protocol logic ever leaks back into the serial subclass, this
    stops working.
    """

    def __init__(self, device, **kwargs):
        super().__init__(**kwargs)
        self.device = device

    def _open(self):
        pass

    def _close(self):
        pass

    def _write_bytes(self, data):
        self.device.write(data)

    def _read_bytes(self, count):
        return self.device.read(count)


def test_non_serial_phy_drives_the_same_engine():
    """No pyserial, no port, no serial module -- same protocol and semantics."""
    device = FakeTapPort()
    t = MemoryTapTransport(device)
    t.connect()

    assert t.num_chains == 4
    assert t.max_dr_bits == 256

    t.write_reg(0x0030, 0xFEEDFACE)
    assert device.mem[0x0030] == 0xFEEDFACE
    assert t.read_reg(0x0030) == 0xFEEDFACE

    value = (0xA5 << 248) | 0x5A
    assert t.raw_dr_scan(value, 256, chain=2) == value


def test_base_class_reports_its_own_channel_name():
    device = FakeTapPort(magic=b"NOPE")
    t = MemoryTapTransport(device)
    with pytest.raises(RuntimeError, match="MemoryTapTransport"):
        t.connect()


# -- port enumeration -------------------------------------------------------


class _FakePort:
    def __init__(self, device, description, hwid):
        self.device = device
        self.description = description
        self.hwid = hwid


def _install_fake_comports(monkeypatch, ports):
    """Plant a fake serial.tools.list_ports that list_serial_ports will import."""
    tools = types.ModuleType("serial.tools")
    mod = types.ModuleType("serial.tools.list_ports")
    mod.comports = lambda: ports  # type: ignore[attr-defined]
    tools.list_ports = mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "serial.tools", tools)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", mod)


def test_list_serial_ports_reports_and_sorts_without_opening(monkeypatch):
    opened = []

    ports = [
        _FakePort("COM7", "USB Serial Port (COM7)", "USB VID:PID=0403:6011"),
        _FakePort("COM16", "USB Serial Device (COM16)", "USB VID:PID=2E8A:0009"),
    ]
    _install_fake_comports(monkeypatch, ports)
    # If enumeration ever opened a port it would reset an RP2350 board, so make
    # any attempt to do so loud rather than silent.
    fake_serial = types.ModuleType("serial")
    fake_serial.Serial = lambda *a, **k: opened.append(a)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "serial", fake_serial)

    got = list_serial_ports()

    # Natural order: COM7 before COM16, not the lexicographic reverse.
    assert [p["device"] for p in got] == ["COM7", "COM16"]
    assert got[1]["description"] == "USB Serial Device (COM16)"
    assert got[1]["hwid"] == "USB VID:PID=2E8A:0009"
    assert opened == []


def test_list_serial_ports_is_empty_without_pyserial(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial.tools", None)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", None)
    # A missing pyserial must not raise: the caller is populating a UI list.
    assert list_serial_ports() == []


# --- RPC-level serial wiring -------------------------------------------------
#
# The transport is only half the story: the RPC layer chooses it, validates its
# parameters, and decides which commands may use it at all.


def _rpc_server():
    from fcapz.rpc import RpcServer

    return RpcServer()


def test_rpc_builds_a_serial_transport_without_an_ir_table():
    t = _rpc_server()._build_transport(
        {"backend": "serial", "serial_port": "COM16", "baudrate": 2_000_000}
    )
    assert isinstance(t, SerialTapTransport)
    assert t.baudrate == 2_000_000


def test_rpc_requires_a_serial_port():
    with pytest.raises(ValueError, match="needs a serial_port"):
        _rpc_server()._build_transport({"backend": "serial", "serial_port": "  "})


@pytest.mark.parametrize("bad", [0, -1, 1.5, "abc", float("nan"), 99_000_000])
def test_rpc_rejects_an_impossible_baudrate(bad):
    with pytest.raises(ValueError, match="baudrate"):
        _rpc_server()._build_transport(
            {"backend": "serial", "serial_port": "COM16", "baudrate": bad}
        )


def test_rpc_defaults_the_baudrate_when_blank():
    # A cleared number field arrives as "" (or null), which must mean "default",
    # not "0 baud".
    for blank in ("", None):
        t = _rpc_server()._build_transport(
            {"backend": "serial", "serial_port": "COM16", "baudrate": blank}
        )
        assert t.baudrate == 1_000_000


def test_rpc_refuses_serial_side_connections():
    # EIO/AXI/UART each build a SECOND transport; the analyzer already owns the
    # port exclusively, so this must fail with our message, not the OS's.
    with pytest.raises(ValueError, match="side connections"):
        _rpc_server()._build_transport(
            {"backend": "serial", "serial_port": "COM16"}, side=True
        )
