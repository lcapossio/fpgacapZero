# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host helper for the AXI monitor core (``fcapz_axi_mon``).

The AXI monitor *is* an ELA fed by a flattened AXI interface, so capture, arm
and readback go through the normal :class:`~fcapz.analyzer.Analyzer`.  This
module adds the AXI-specific glue on top:

* **detect** an AXI monitor by reading its identity register (``AXI_MON_ID`` at
  ``0x00E8``; the embedded ELA's ``0x0000`` still reports ``"LA"``),
* decode the **geometry** register (``AXI_GEOM`` at ``0x00EC``),
* load the bundled **probe map** so captures/VCD show named AXI fields
  (``awaddr``, ``wdata``, ``bresp``, …) instead of one opaque ``sample`` word,
* **decode** a captured sample word into its AXI fields, and
* build a :class:`CaptureConfig` that **triggers on a write address** (``awaddr``
  occupies the low 32 bits of the capture vector, so it is reachable by the
  ELA's 32-bit trigger comparator).

Richer transaction triggers (response codes, ``wdata``, handshake events) need
the P2 RTL decode layer; see ``docs/specs/axi_monitor.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import axi_layout
from .analyzer import Analyzer, CaptureConfig, ProbeSpec, TriggerConfig
from .probes import ProbeFile

# AXI-monitor registers (in the free config gap, clear of the ELA data window).
ADDR_AXI_MON_ID = 0x00E8
ADDR_AXI_GEOM = 0x00EC
AXI_MON_MAGIC = 0x414D  # "AM"

_PROTO_NAMES = {1: "AXI4LITE"}

# Decode-layer event bits (low byte of the capture vector when DECODE_EN=1),
# derived from the single-source layout so the names/positions can't drift.
EVENT_BITS = {name: bit for bit, (name, _w) in enumerate(axi_layout.EVENT_FIELDS)}

# The per-channel handshake events (a beat = VALID & READY on that channel).
HANDSHAKE_EVENTS = ("aw_hs", "w_hs", "b_hs", "ar_hs", "r_hs")


class AxiMonitorError(RuntimeError):
    """Raised when an AXI monitor is required but absent or unsupported."""


@dataclass(frozen=True)
class AxiGeometry:
    addr_w: int
    data_w: int
    id_w: int
    cap_channels: int
    proto_code: int
    decode: bool = False  # DECODE_EN: 8-bit events word prepended at the LSB

    @property
    def proto(self) -> str:
        return _PROTO_NAMES.get(self.proto_code, f"proto{self.proto_code}")

    @property
    def sample_width(self) -> int:
        """Flatten width — must match fcapz_axi_mon's SAMPLE_W localparam.

        Derived from the single-source layout in :mod:`fcapz.axi_layout`.
        """
        return axi_layout.sample_width(self.addr_w, self.data_w, self.decode)


class AxiMonitor:
    """AXI-specific helpers around a connected :class:`Analyzer`."""

    def __init__(self, analyzer: Analyzer) -> None:
        self._an = analyzer

    def _read(self, addr: int) -> int:
        # Select the monitor's BSCAN chain first -- another core (e.g. the AXI
        # bridge on a different USER chain) may have left the transport selected
        # elsewhere.
        t = self._an.transport
        with t.transaction_lock():
            try:
                t.select_chain(self._an.bscan_chain)
            except NotImplementedError:
                pass
            return t.read_reg(addr)

    # ---- detection / geometry ------------------------------------------
    def identity(self) -> int | None:
        """Raw ``AXI_MON_ID`` if this core is an AXI monitor, else ``None``."""
        raw = self._read(ADDR_AXI_MON_ID)
        return raw if (raw >> 16) == AXI_MON_MAGIC else None

    @property
    def present(self) -> bool:
        return self.identity() is not None

    def geometry(self) -> AxiGeometry:
        ident = self.identity()
        if ident is None:
            raise AxiMonitorError("no AXI monitor on this core (AXI_MON_ID magic absent)")
        geom = self._read(ADDR_AXI_GEOM)
        return AxiGeometry(
            addr_w=geom & 0xFF,
            data_w=(geom >> 8) & 0xFF,
            id_w=(geom >> 16) & 0xF,
            cap_channels=(geom >> 20) & 0x1F,
            proto_code=(ident >> 8) & 0xFF,
            decode=bool(ident & 0x01),  # CAP_FLAGS bit0
        )

    # ---- probe map / field decode --------------------------------------
    def probe_map(self, geometry: AxiGeometry | None = None) -> ProbeFile:
        """Named-field probe map for the monitor's geometry.

        Derived directly from the single-source layout in
        :mod:`fcapz.axi_layout` (the bundled ``.prob`` sidecars are generated
        from the same source by ``tools/gen_axi_probes.py``), so runtime decode
        and the shipped files can never drift apart.
        """
        geo = geometry or self.geometry()
        if geo.proto_code != 1:
            raise AxiMonitorError(
                f"no probe map for proto {geo.proto_code} (only AXI4-Lite is supported)"
            )
        probes = axi_layout.axi_probes(geo.addr_w, geo.data_w, geo.decode)
        return ProbeFile(probes=probes, sample_width=geo.sample_width, core="axi_mon")

    def decode_sample(self, value: int, probes: list[ProbeSpec] | None = None) -> dict[str, int]:
        """Slice a packed capture word into ``{field: value}`` per the probe map."""
        specs = probes if probes is not None else self.probe_map().probes
        return {p.name: (value >> p.lsb) & ((1 << p.width) - 1) for p in specs}

    # ---- trigger helpers ------------------------------------------------
    def write_addr_capture_config(
        self,
        addr: int,
        *,
        pretrigger: int = 8,
        posttrigger: int = 24,
        addr_mask: int = 0xFFFF_FFFF,
        depth: int = 1024,
        sample_clock_hz: int = 100_000_000,
        qualify_valid: bool = True,
    ) -> CaptureConfig:
        """A capture that triggers when a write address (``awaddr``) matches.

        The trigger value/mask are built at ``awaddr``'s real bit offset from
        the probe map (bit 0 on a raw build, bit 8 on a decode build where the
        events word shifts everything up), so this works on **both** builds —
        the full-width comparator (``WIDE_TRIG``) reaches the address wherever
        it lands, not just the low 32 bits.

        With ``qualify_valid=True`` (the default) the trigger also requires
        ``awvalid`` to be asserted, so it fires on a genuine write-address
        handshake attempt rather than on a stale address the bus happens to be
        parked on while ``awvalid`` is low.

        Requires a ``WIDE_TRIG`` core when the address (or the ``awvalid`` bit)
        falls above bit 31 — the monitor is built that way; ``Analyzer.configure``
        raises otherwise.
        """
        geo = self.geometry()
        probes = {p.name: p for p in self.probe_map(geo).probes}
        aw = probes["awaddr"]
        value = (addr & addr_mask) << aw.lsb
        mask = (addr_mask & ((1 << aw.width) - 1)) << aw.lsb
        if qualify_valid:
            awv = probes["awvalid"]
            value |= 1 << awv.lsb
            mask |= 1 << awv.lsb
        return CaptureConfig(
            pretrigger=pretrigger,
            posttrigger=posttrigger,
            trigger=TriggerConfig(mode="value_match", value=value, mask=mask),
            sample_width=geo.sample_width,
            depth=depth,
            sample_clock_hz=sample_clock_hz,
            probes=list(probes.values()),
        )

    def beat_storage_qual(self) -> tuple[int, int, int]:
        """Storage-qualifier ``(mode, value, mask)`` that keeps only beats.

        A passive tap samples every ``ACLK`` cycle, so a mostly-idle bus fills
        the buffer with idle repeats and only a handful of real transactions.
        On a DECODE_EN build the five handshake bits (``aw_hs``..``r_hs``) sit
        in the low byte, so a NEQ-vs-zero storage qualifier over their mask
        stores a sample **only on cycles where at least one channel handshakes**
        — compressing the capture to transaction beats.

        Returns the ELA storage-qualifier tuple: mode ``1`` (NEQ, i.e. store
        when the masked bits are non-zero), value ``0``, mask = the OR of the
        handshake-event bits.  Requires a DECODE_EN=1 build (the handshake bits
        do not exist otherwise).
        """
        geo = self.geometry()
        if not geo.decode:
            raise AxiMonitorError(
                "beat storage qualification needs a DECODE_EN=1 monitor build"
            )
        mask = 0
        for name in HANDSHAKE_EVENTS:
            mask |= 1 << EVENT_BITS[name]
        return (1, 0, mask)  # NEQ vs 0 over the handshake bits

    def event_capture_config(
        self,
        *events: str,
        pretrigger: int = 8,
        posttrigger: int = 24,
        depth: int = 1024,
        sample_clock_hz: int = 100_000_000,
        store_on_beats: bool = False,
    ) -> CaptureConfig:
        """A capture that triggers on AXI transaction events (DECODE_EN=1 builds).

        ``events`` are names from :data:`EVENT_BITS` (e.g. ``"any_err"``,
        ``"b_hs"``).  The trigger fires when **all** named bits are asserted in
        the same cycle (use the pre-ORed ``"any_err"`` for "any error
        response").  The decode layer places these bits in the low byte so the
        ELA's value-match comparator reaches them.

        With ``store_on_beats=True`` the capture also enables the beat storage
        qualifier (:meth:`beat_storage_qual`), so idle cycles are dropped and
        the buffer holds only transaction beats around the trigger.
        """
        geo = self.geometry()
        if not geo.decode:
            raise AxiMonitorError(
                "event triggers require a DECODE_EN=1 monitor build"
            )
        if not events:
            raise AxiMonitorError("name at least one event (e.g. 'any_err')")
        mask = 0
        for name in events:
            if name not in EVENT_BITS:
                raise AxiMonitorError(
                    f"unknown AXI event {name!r}; known: {sorted(EVENT_BITS)}"
                )
            mask |= 1 << EVENT_BITS[name]
        sq_mode, sq_value, sq_mask = self.beat_storage_qual() if store_on_beats else (0, 0, 0)
        return CaptureConfig(
            pretrigger=pretrigger,
            posttrigger=posttrigger,
            trigger=TriggerConfig(mode="value_match", value=mask, mask=mask),
            sample_width=geo.sample_width,
            depth=depth,
            sample_clock_hz=sample_clock_hz,
            probes=list(self.probe_map(geo).probes),
            stor_qual_mode=sq_mode,
            stor_qual_value=sq_value,
            stor_qual_mask=sq_mask,
        )
