# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""LiteX integration helpers for fpgacapZero ELA.

The integration is intentionally thin: it instantiates the existing vendor
wrapper and leaves host access on the existing JTAG transport path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .analyzer import ProbeSpec
from .probes import probe_file_dict, write_probe_file


_ROOT = Path(__file__).resolve().parents[2]
_RTL_DIR = _ROOT / "rtl"


_COMMON_ELA_SOURCES = (
    "fcapz_version.vh",
    "fcapz_ela.v",
    "fcapz_core_manager.v",
    "fcapz_eio.v",
    "fcapz_regbus_mux.v",
    "trig_compare.v",
    "dpram.v",
    "reset_sync.v",
    "jtag_reg_iface.v",
    "jtag_pipe_iface.v",
    "jtag_burst_read.v",
)

_VENDOR_ELA_SOURCES: dict[str, tuple[str, ...]] = {
    "xilinx7": (
        "fcapz_ela_xilinx7.v",
        "fcapz_debug_multi_xilinx7.v",
        "jtag_tap/jtag_tap_xilinx7.v",
    ),
    "xilinxus": (
        "fcapz_ela_xilinxus.v",
        "fcapz_ela_xilinx7.v",
        "fcapz_debug_multi_xilinx7.v",
        "jtag_tap/jtag_tap_xilinx7.v",
    ),
    "ecp5": ("fcapz_ela_ecp5.v", "jtag_tap/jtag_tap_ecp5.v"),
    "intel": ("fcapz_ela_intel.v", "jtag_tap/jtag_tap_intel.v"),
    "gowin": ("fcapz_ela_gowin.v", "jtag_tap/jtag_tap_gowin.v"),
    "polarfire": ("fcapz_ela_polarfire.v", "jtag_tap/jtag_tap_polarfire.v"),
}

_WRAPPER_MODULES = {
    vendor: f"fcapz_ela_{vendor}"
    for vendor in _VENDOR_ELA_SOURCES
}


@dataclass(frozen=True)
class LiteXProbeField:
    """Named field packed into the LiteX ELA probe bus."""

    name: str
    width: int
    offset: int


def ela_rtl_sources(vendor: str = "xilinx7", rtl_dir: str | Path | None = None) -> list[Path]:
    """Return the RTL source list needed for a LiteX ELA instance."""

    vendor_key = vendor.lower()
    if vendor_key not in _VENDOR_ELA_SOURCES:
        known = ", ".join(sorted(_VENDOR_ELA_SOURCES))
        raise ValueError(f"unsupported ELA vendor {vendor!r}; expected one of: {known}")

    base = Path(rtl_dir) if rtl_dir is not None else _RTL_DIR
    rel_paths = (*_COMMON_ELA_SOURCES, *_VENDOR_ELA_SOURCES[vendor_key])
    return [base / rel for rel in rel_paths]


def add_ela_sources(
    platform: Any,
    vendor: str = "xilinx7",
    rtl_dir: str | Path | None = None,
) -> None:
    """Add all RTL files required by the selected vendor ELA wrapper."""

    for source in ela_rtl_sources(vendor=vendor, rtl_dir=rtl_dir):
        platform.add_source(str(source))


def _signal_width(signal: Any) -> int:
    try:
        return len(signal)
    except TypeError:
        return 1


def describe_probe_fields(
    probes: Mapping[str, Any] | Sequence[tuple[str, Any]] | Any,
) -> list[LiteXProbeField]:
    """Describe how named probe signals are packed into ``probe_in``.

    LiteX/Migen ``Cat`` packs the first signal into the low bits.  The returned
    offsets follow that convention so generated capture metadata can use them
    directly.
    """

    if isinstance(probes, Mapping):
        items: Iterable[tuple[str, Any]] = probes.items()
    elif isinstance(probes, Sequence) and not isinstance(probes, (str, bytes)):
        items = probes  # type: ignore[assignment]
    else:
        return [LiteXProbeField("probe", _signal_width(probes), 0)]

    fields: list[LiteXProbeField] = []
    offset = 0
    for name, signal in items:
        width = _signal_width(signal)
        if width < 1:
            raise ValueError(f"probe {name!r} has invalid width {width}")
        fields.append(LiteXProbeField(str(name), width, offset))
        offset += width
    if not fields:
        raise ValueError("at least one probe signal is required")
    return fields


def _require_litex() -> tuple[Any, Any, Any, Any, Any, type[Any]]:
    try:
        from migen import Cat, ClockSignal, Instance, ResetSignal, Signal
        from litex.gen import LiteXModule
    except ImportError as exc:
        raise ImportError(
            "fcapz.litex requires LiteX/Migen. Install LiteX in your SoC "
            "environment before instantiating FcapzELA."
        ) from exc
    return Cat, ClockSignal, Instance, ResetSignal, Signal, LiteXModule


def _cat_probes(cat: Any, probes: Mapping[str, Any] | Sequence[tuple[str, Any]] | Any) -> Any:
    if isinstance(probes, Mapping):
        return cat(*probes.values())
    if isinstance(probes, Sequence) and not isinstance(probes, (str, bytes)):
        return cat(*(signal for _name, signal in probes))
    return probes


class FcapzELA:
    """LiteX module wrapper for a JTAG-accessible ELA instance.

    The class intentionally does not add LiteX CSRs.  It routes probes into the
    normal fpgacapZero vendor wrapper, so capture control remains through the
    existing JTAG host tools.
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        *_, LiteXModule = _require_litex()
        if cls is FcapzELA:
            runtime_cls = type("_FcapzELALiteX", (FcapzELA, LiteXModule), {})
            return object.__new__(runtime_cls)
        return object.__new__(cls)

    def __init__(
        self,
        platform: Any,
        probes: Mapping[str, Any] | Sequence[tuple[str, Any]] | Any,
        *,
        sample_clk: Any | None = None,
        sample_rst: Any | None = None,
        vendor: str = "xilinx7",
        depth: int = 1024,
        sample_width: int | None = None,
        trig_stages: int = 1,
        stor_qual: int = 0,
        input_pipe: int = 0,
        decim_en: int = 0,
        ext_trig_en: int = 0,
        timestamp_w: int = 0,
        num_segments: int = 1,
        probe_mux_w: int = 0,
        startup_arm: int = 0,
        default_trig_ext: int = 0,
        burst_w: int = 256,
        burst_en: int = 1,
        single_chain_burst: int = 1,
        ctrl_chain: int = 1,
        data_chain: int = 2,
        rel_compare: int = 0,
        dual_compare: int = 1,
        user1_data_en: int = 1,
        trigger_in: Any = 0,
        trigger_out: Any | None = None,
        armed_out: Any | None = None,
        rtl_dir: str | Path | None = None,
    ) -> None:
        cat, clock_signal, instance, reset_signal, signal, _ = _require_litex()
        if hasattr(super(), "__init__"):
            super().__init__()

        vendor_key = vendor.lower()
        supported_wrappers = ("xilinx7", "xilinxus")
        if vendor_key not in supported_wrappers:
            known = ", ".join(supported_wrappers)
            raise ValueError(
                f"LiteX FcapzELA currently supports {known}; got {vendor!r}. "
                "Use ela_rtl_sources() as the lower-level manifest helper for other wrappers."
            )

        add_ela_sources(platform, vendor=vendor_key, rtl_dir=rtl_dir)
        self.probe_fields = describe_probe_fields(probes)
        inferred_width = sum(field.width for field in self.probe_fields)
        if sample_width is None:
            sample_width = inferred_width
        if sample_width != inferred_width and probe_mux_w == 0:
            raise ValueError(
                f"sample_width ({sample_width}) must match packed probe width "
                f"({inferred_width}) unless probe_mux_w is used"
            )

        probe_bus = _cat_probes(cat, probes)
        trigger_out_sig = trigger_out if trigger_out is not None else signal()
        armed_out_sig = armed_out if armed_out is not None else signal()

        self.sample_width = int(sample_width)
        self.depth = int(depth)
        self.vendor = vendor_key
        self.trigger_out = trigger_out_sig
        self.armed_out = armed_out_sig

        # Migen's ``specials`` collector is provided by LiteXModule.
        self.specials += instance(
            _WRAPPER_MODULES[vendor_key],
            p_SAMPLE_W=int(sample_width),
            p_DEPTH=int(depth),
            p_TRIG_STAGES=int(trig_stages),
            p_STOR_QUAL=int(stor_qual),
            p_INPUT_PIPE=int(input_pipe),
            p_NUM_CHANNELS=1,
            p_DECIM_EN=int(decim_en),
            p_EXT_TRIG_EN=int(ext_trig_en),
            p_TIMESTAMP_W=int(timestamp_w),
            p_NUM_SEGMENTS=int(num_segments),
            p_PROBE_MUX_W=int(probe_mux_w),
            p_STARTUP_ARM=int(startup_arm),
            p_DEFAULT_TRIG_EXT=int(default_trig_ext),
            p_BURST_W=int(burst_w),
            p_BURST_EN=int(burst_en),
            p_SINGLE_CHAIN_BURST=int(single_chain_burst),
            p_CTRL_CHAIN=int(ctrl_chain),
            p_DATA_CHAIN=int(data_chain),
            p_REL_COMPARE=int(rel_compare),
            p_DUAL_COMPARE=int(dual_compare),
            p_USER1_DATA_EN=int(user1_data_en),
            i_sample_clk=sample_clk if sample_clk is not None else clock_signal(),
            i_sample_rst=sample_rst if sample_rst is not None else reset_signal(),
            i_probe_in=probe_bus,
            i_trigger_in=trigger_in,
            o_trigger_out=trigger_out_sig,
            o_armed_out=armed_out_sig,
            i_eio_probe_in=0,
        )

    def probe_specs(self) -> list[ProbeSpec]:
        """Return probe fields as host-side ``ProbeSpec`` objects."""

        return [
            ProbeSpec(name=field.name, width=field.width, lsb=field.offset)
            for field in self.probe_fields
        ]

    def probe_file_dict(self, *, sample_clock_hz: int | None = None) -> dict[str, Any]:
        """Return a JSON-serializable ``.prob`` document for this LiteX ELA."""

        return probe_file_dict(
            self.probe_specs(),
            sample_width=self.sample_width,
            sample_clock_hz=sample_clock_hz,
        )

    def write_probe_file(
        self,
        path: str | Path,
        *,
        sample_clock_hz: int | None = None,
    ) -> None:
        """Write a ``.prob`` sidecar for this LiteX ELA instance."""

        write_probe_file(
            path,
            self.probe_specs(),
            sample_width=self.sample_width,
            sample_clock_hz=sample_clock_hz,
        )


__all__ = [
    "FcapzELA",
    "LiteXProbeField",
    "add_ela_sources",
    "describe_probe_fields",
    "ela_rtl_sources",
]
