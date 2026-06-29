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
from importlib import resources

from .analyzer import Analyzer, CaptureConfig, ProbeSpec, TriggerConfig
from .probes import ProbeFile, load_probe_file

# AXI-monitor registers (in the free config gap, clear of the ELA data window).
ADDR_AXI_MON_ID = 0x00E8
ADDR_AXI_GEOM = 0x00EC
AXI_MON_MAGIC = 0x414D  # "AM"

# (addr_w, data_w) -> bundled probe-map resource name under fcapz/probes/.
_PROBE_MAPS = {
    (32, 32): "axi4lite_32.prob",
}

_PROTO_NAMES = {1: "AXI4LITE"}


class AxiMonitorError(RuntimeError):
    """Raised when an AXI monitor is required but absent or unsupported."""


@dataclass(frozen=True)
class AxiGeometry:
    addr_w: int
    data_w: int
    id_w: int
    cap_channels: int
    proto_code: int

    @property
    def proto(self) -> str:
        return _PROTO_NAMES.get(self.proto_code, f"proto{self.proto_code}")

    @property
    def sample_width(self) -> int:
        """Flatten width — must match fcapz_axi_mon's SAMPLE_W localparam."""
        return 2 * self.addr_w + 2 * self.data_w + self.data_w // 8 + 20


class AxiMonitor:
    """AXI-specific helpers around a connected :class:`Analyzer`."""

    def __init__(self, analyzer: Analyzer) -> None:
        self._an = analyzer

    def _read(self, addr: int) -> int:
        with self._an.transport.transaction_lock():
            return self._an.transport.read_reg(addr)

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
        )

    # ---- probe map / field decode --------------------------------------
    def probe_map(self, geometry: AxiGeometry | None = None) -> ProbeFile:
        """Load the bundled probe map matching the monitor's geometry."""
        geo = geometry or self.geometry()
        name = _PROBE_MAPS.get((geo.addr_w, geo.data_w))
        if name is None:
            raise AxiMonitorError(
                f"no bundled probe map for AXI {geo.addr_w}/{geo.data_w}; "
                "supported: " + ", ".join(f"{a}/{d}" for a, d in _PROBE_MAPS)
            )
        path = resources.files("fcapz").joinpath("probes", name)
        with resources.as_file(path) as real_path:
            return load_probe_file(real_path)

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
    ) -> CaptureConfig:
        """A capture that triggers when a write address (``awaddr``) matches.

        ``awaddr`` occupies the capture vector's low 32 bits, so the ELA's
        32-bit value-match comparator triggers on it directly.  The bundled
        probe map is attached so the result decodes to named AXI fields.
        """
        geo = self.geometry()
        return CaptureConfig(
            pretrigger=pretrigger,
            posttrigger=posttrigger,
            trigger=TriggerConfig(mode="value_match", value=addr & addr_mask, mask=addr_mask),
            sample_width=geo.sample_width,
            depth=depth,
            sample_clock_hz=sample_clock_hz,
            probes=list(self.probe_map(geo).probes),
        )
