# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host-side controller for the fcapz_eio JTAG Embedded I/O core.

Register map (USER3, same 49-bit DR protocol as ELA):
  0x0000  VERSION   (R)  {major[7:0], minor[7:0], core_id[15:0]="IO"=0x494F}
  0x0004  EIO_IN_W  (R)  input probe width
  0x0008  EIO_OUT_W (R)  output probe width
  0x0010  IN[0]     (R)  probe_in[31:0]   (synchronised to jtag_clk)
  0x0014  IN[1]     (R)  probe_in[63:32]
  ...
  0x0100  OUT[0]    (RW) probe_out[31:0]
  0x0104  OUT[1]    (RW) probe_out[63:32]
  ...

The VERSION register is the EIO core's identity.  ``connect()`` reads it
and raises ``RuntimeError`` if the low-16 magic does not equal 0x494F
('IO').  This rejects an unprogrammed FPGA, a wrong JTAG chain, or a
non-fcapz bitstream before any other EIO register is touched — the same
contract as ``Analyzer.probe()``.  The decoded major/minor are exposed
on the ``EioController`` instance as ``version_major`` /
``version_minor`` and should match ``fcapz.__version__``.
"""

from __future__ import annotations

from .transport import Transport

# ASCII "IO" packed into VERSION[15:0]; constant per-core, never zero on
# a valid bitstream.  Same encoding scheme as the ELA core's "LA" magic.
EIO_CORE_ID = 0x494F

_ADDR_VERSION  = 0x0000
_ADDR_IN_W     = 0x0004
_ADDR_OUT_W    = 0x0008
_ADDR_IN_BASE  = 0x0010
_ADDR_OUT_BASE = 0x0100


class EioController:
    """Read input probes and write output probes via JTAG USER3."""

    def __init__(self, transport: Transport, chain: int = 3) -> None:
        self._t = transport
        self._chain = chain
        self.in_w: int = 0
        self.out_w: int = 0
        self.version_major: int = 0
        self.version_minor: int = 0
        self.core_id: int = 0

    # ------------------------------------------------------------------
    def connect(self) -> None:
        """Connect transport, verify EIO core identity, read parameters.

        Reads VERSION at 0x0000 and asserts that the low-16 magic equals
        ``EIO_CORE_ID`` (ASCII "IO" = 0x494F).  Raises ``RuntimeError``
        on mismatch with a remediation hint that covers the three common
        failure modes (wrong chain, wrong bitstream / unprogrammed FPGA,
        wrong core).  Decoded ``version_major`` / ``version_minor`` are
        cached on the instance for the caller; they should match
        ``fcapz.__version__``.
        """
        self._t.connect()
        self._t.select_chain(self._chain)
        version = int(self._t.read_reg(_ADDR_VERSION))
        core_id = version & 0xFFFF
        if core_id != EIO_CORE_ID:
            raise RuntimeError(
                f"EIO core identity check failed at VERSION[15:0]: "
                f"expected 0x{EIO_CORE_ID:04X} ('IO'), got 0x{core_id:04X}. "
                f"Wrong JTAG chain, wrong bitstream, or core not loaded?"
            )
        self.version_major = (version >> 24) & 0xFF
        self.version_minor = (version >> 16) & 0xFF
        self.core_id = core_id
        self.in_w  = self._t.read_reg(_ADDR_IN_W)
        self.out_w = self._t.read_reg(_ADDR_OUT_W)

    def close(self) -> None:
        self._t.close()

    # ------------------------------------------------------------------
    def read_inputs(self) -> int:
        """Return current probe_in value as a single integer (LSB = bit 0)."""
        words = (self.in_w + 31) // 32
        value = 0
        for i in range(words):
            word = self._t.read_reg(_ADDR_IN_BASE + i * 4)
            value |= word << (i * 32)
        mask = (1 << self.in_w) - 1
        return value & mask

    def write_outputs(self, value: int) -> None:
        """Write probe_out as a single integer (LSB = bit 0)."""
        mask = (1 << self.out_w) - 1
        value = value & mask
        words = (self.out_w + 31) // 32
        for i in range(words):
            word = (value >> (i * 32)) & 0xFFFF_FFFF
            self._t.write_reg(_ADDR_OUT_BASE + i * 4, word)

    def read_outputs(self) -> int:
        """Read back the currently programmed probe_out value.

        Returns the full OUT_W-bit value that was last written to the output
        registers via write_outputs() or set_bit().  Reads live hardware
        registers rather than a local cache, so the value reflects any
        external reset or JTAG-level reset that may have cleared the outputs.

        Returns:
            Current output register value as an unsigned integer, zero-padded
            to OUT_W bits (bits above OUT_W are masked off).
        """
        words = (self.out_w + 31) // 32
        value = 0
        for i in range(words):
            word = self._t.read_reg(_ADDR_OUT_BASE + i * 4)
            value |= word << (i * 32)
        mask = (1 << self.out_w) - 1
        return value & mask

    # ------------------------------------------------------------------
    def set_bit(self, bit: int, level: int) -> None:
        """Set or clear a single output bit without disturbing other bits.

        Performs a read-modify-write: reads the current output register,
        updates the requested bit, and writes the result back.  This is not
        atomic — concurrent accesses from another host session can race.

        Args:
            bit:   Bit index to modify (0 = LSB).  Must be in [0, OUT_W).
            level: 1 to set the bit, 0 to clear it.  Any non-zero value sets.

        Raises:
            ValueError: If *bit* is outside [0, OUT_W).
        """
        if not (0 <= bit < self.out_w):
            raise ValueError(f"bit {bit} out of range (OUT_W={self.out_w})")
        current = self.read_outputs()
        if level:
            current |= (1 << bit)
        else:
            current &= ~(1 << bit)
        self.write_outputs(current)

    def get_bit(self, bit: int) -> int:
        """Read a single input bit from probe_in.

        Args:
            bit: Bit index to read (0 = LSB).  Must be in [0, IN_W).

        Returns:
            0 or 1.

        Raises:
            ValueError: If *bit* is outside [0, IN_W).
        """
        if not (0 <= bit < self.in_w):
            raise ValueError(f"bit {bit} out of range (IN_W={self.in_w})")
        return (self.read_inputs() >> bit) & 1

    # ------------------------------------------------------------------
    def __repr__(self) -> str:
        return f"EioController(in_w={self.in_w}, out_w={self.out_w})"
