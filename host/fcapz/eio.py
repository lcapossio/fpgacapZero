# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host-side controller for the fcapz_eio JTAG Embedded I/O core.

Register map (USER3, same 49-bit DR protocol as ELA):
  0x0000  EIO_ID    (R)  0x56494F01
  0x0004  EIO_IN_W  (R)  input probe width
  0x0008  EIO_OUT_W (R)  output probe width
  0x0010  IN[0]     (R)  probe_in[31:0]   (synchronised to jtag_clk)
  0x0014  IN[1]     (R)  probe_in[63:32]
  ...
  0x0100  OUT[0]    (RW) probe_out[31:0]
  0x0104  OUT[1]    (RW) probe_out[63:32]
  ...
"""

from __future__ import annotations

from .transport import Transport

_EIO_ID       = 0x56494F01

_ADDR_EIO_ID   = 0x0000
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

    # ------------------------------------------------------------------
    def connect(self) -> None:
        """Connect transport and read core parameters."""
        self._t.connect()
        self._t.select_chain(self._chain)
        vid = self._t.read_reg(_ADDR_EIO_ID)
        if vid != _EIO_ID:
            raise RuntimeError(
                f"EIO ID mismatch: expected 0x{_EIO_ID:08X}, got 0x{vid:08X}. "
                "Wrong JTAG chain / core not loaded?"
            )
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
        """Read back the currently programmed probe_out value."""
        words = (self.out_w + 31) // 32
        value = 0
        for i in range(words):
            word = self._t.read_reg(_ADDR_OUT_BASE + i * 4)
            value |= word << (i * 32)
        mask = (1 << self.out_w) - 1
        return value & mask

    # ------------------------------------------------------------------
    def set_bit(self, bit: int, level: int) -> None:
        """Set a single output bit without disturbing others."""
        if not (0 <= bit < self.out_w):
            raise ValueError(f"bit {bit} out of range (OUT_W={self.out_w})")
        current = self.read_outputs()
        if level:
            current |= (1 << bit)
        else:
            current &= ~(1 << bit)
        self.write_outputs(current)

    def get_bit(self, bit: int) -> int:
        """Read a single input bit."""
        if not (0 <= bit < self.in_w):
            raise ValueError(f"bit {bit} out of range (IN_W={self.in_w})")
        return (self.read_inputs() >> bit) & 1

    # ------------------------------------------------------------------
    def __repr__(self) -> str:
        return f"EioController(in_w={self.in_w}, out_w={self.out_w})"
