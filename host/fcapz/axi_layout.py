# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Single source of truth for the AXI monitor's capture-vector layout.

``fcapz_axi_mon`` flattens the five AXI4-Lite channels (plus, on DECODE_EN
builds, an 8-bit transaction-events word at the LSB) into one capture vector.
That bit layout used to be written out by hand in four places that had to stay
in lockstep: the RTL flatten order, the core ``SAMPLE_W`` localparam, a second
``SAMPLE_W`` formula in the Xilinx wrapper, and the host's formula plus the
hand-maintained ``.prob`` sidecars.

This module is the one place the layout is described.  From it we derive the
``ProbeSpec`` offsets, the ``SAMPLE_W``, and the bundled ``.prob`` files (see
``tools/gen_axi_probes.py``).  ``tests/test_axi_monitor.py`` asserts the derived
width matches the RTL's ``2*ADDR_W + 2*DATA_W + DATA_W/8 + 20 (+8)`` formula, so
a divergence fails CI instead of silently shifting every field.

The field order below is **LSB-first** and must match the RTL concatenation in
``rtl/fcapz_axi_mon.v`` (``channels`` is listed MSB-first there, i.e. the
reverse of this list) and the events word in ``events``.
"""

from __future__ import annotations

from .analyzer import ProbeSpec

# Transaction-events word (DECODE_EN=1): bit positions 0..7 at the vector LSB.
# Order matches the RTL ``events`` concatenation in fcapz_axi_mon.v.
EVENT_FIELDS: tuple[tuple[str, int], ...] = (
    ("aw_hs", 1),
    ("w_hs", 1),
    ("b_hs", 1),
    ("ar_hs", 1),
    ("r_hs", 1),
    ("b_err", 1),
    ("r_err", 1),
    ("any_err", 1),
)


def _channel_fields(addr_w: int, data_w: int) -> tuple[tuple[str, int], ...]:
    """AXI4-Lite channel fields in LSB-first order (AW, W, B, AR, R)."""
    strb_w = data_w // 8
    return (
        # AW channel (awaddr at the channel-block LSB)
        ("awaddr", addr_w), ("awprot", 3), ("awvalid", 1), ("awready", 1),
        # W channel
        ("wdata", data_w), ("wstrb", strb_w), ("wvalid", 1), ("wready", 1),
        # B channel
        ("bresp", 2), ("bvalid", 1), ("bready", 1),
        # AR channel
        ("araddr", addr_w), ("arprot", 3), ("arvalid", 1), ("arready", 1),
        # R channel
        ("rdata", data_w), ("rresp", 2), ("rvalid", 1), ("rready", 1),
    )


def axi_fields(addr_w: int, data_w: int, decode: bool) -> tuple[tuple[str, int], ...]:
    """Full LSB-first ``(name, width)`` field list for the capture vector."""
    fields = _channel_fields(addr_w, data_w)
    return (EVENT_FIELDS + fields) if decode else fields


def axi_probes(addr_w: int, data_w: int, decode: bool) -> list[ProbeSpec]:
    """Derive the ``ProbeSpec`` list (with computed ``lsb``) for the layout."""
    lsb = 0
    probes: list[ProbeSpec] = []
    for name, width in axi_fields(addr_w, data_w, decode):
        probes.append(ProbeSpec(name=name, width=width, lsb=lsb))
        lsb += width
    return probes


def sample_width(addr_w: int, data_w: int, decode: bool) -> int:
    """Flatten width — the sum of every field, == fcapz_axi_mon's SAMPLE_W."""
    return sum(width for _, width in axi_fields(addr_w, data_w, decode))


# Bundled probe-map geometries: (addr_w, data_w, decode) -> resource stem.
PROBE_MAPS: dict[tuple[int, int, bool], str] = {
    (32, 32, False): "axi4lite_32",
    (32, 32, True): "axi4lite_32_decode",
}
