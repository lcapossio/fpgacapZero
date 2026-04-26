# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Read and write fpgacapZero ``.prob`` probe sidecar files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .analyzer import ProbeSpec

PROBE_FILE_FORMAT = "fpgacapzero.probes.v1"


@dataclass(frozen=True)
class ProbeFile:
    """Decoded contents of a ``.prob`` sidecar."""

    probes: list[ProbeSpec]
    sample_width: int | None = None
    sample_clock_hz: int | None = None
    core: str = "ela"

    def probe_arg(self) -> str:
        """Return CLI-compatible ``name:width:lsb,...`` text."""

        return probes_to_arg(self.probes)


def probes_to_arg(probes: Iterable[ProbeSpec]) -> str:
    """Return CLI-compatible ``name:width:lsb,...`` text."""

    return ",".join(f"{probe.name}:{probe.width}:{probe.lsb}" for probe in probes)


def _validate_probe_specs(probes: list[ProbeSpec], sample_width: int | None = None) -> None:
    occupied: set[int] = set()
    for probe in probes:
        if not probe.name:
            raise ValueError("probe name must not be empty")
        if probe.width <= 0:
            raise ValueError(f"probe '{probe.name}' width must be > 0, got {probe.width}")
        if probe.lsb < 0:
            raise ValueError(f"probe '{probe.name}' lsb must be >= 0, got {probe.lsb}")
        msb = probe.lsb + probe.width - 1
        if sample_width is not None and msb >= sample_width:
            raise ValueError(
                f"probe '{probe.name}' bits [{msb}:{probe.lsb}] exceed "
                f"sample_width {sample_width}"
            )
        bits = set(range(probe.lsb, msb + 1))
        overlap = occupied & bits
        if overlap:
            first = min(overlap)
            raise ValueError(f"probe '{probe.name}' overlaps bit {first}")
        occupied.update(bits)


def _parse_probe_entry(entry: Any) -> ProbeSpec:
    if not isinstance(entry, dict):
        raise ValueError("probe entries must be objects")
    try:
        name = str(entry["name"])
        width = int(entry["width"])
        lsb = int(entry.get("lsb", 0))
    except KeyError as exc:
        raise ValueError(f"probe entry missing required field {exc.args[0]!r}") from exc
    return ProbeSpec(name=name, width=width, lsb=lsb)


def probe_file_dict(
    probes: Iterable[ProbeSpec],
    *,
    sample_width: int | None = None,
    sample_clock_hz: int | None = None,
    core: str = "ela",
) -> dict[str, Any]:
    """Build a JSON-serializable ``.prob`` document."""

    probe_list = list(probes)
    _validate_probe_specs(probe_list, sample_width=sample_width)

    data: dict[str, Any] = {
        "format": PROBE_FILE_FORMAT,
        "core": core,
        "probes": [
            {"name": probe.name, "width": probe.width, "lsb": probe.lsb}
            for probe in probe_list
        ],
    }
    if sample_width is not None:
        data["sample_width"] = int(sample_width)
    if sample_clock_hz is not None:
        data["sample_clock_hz"] = int(sample_clock_hz)
    return data


def load_probe_file(path: str | Path) -> ProbeFile:
    """Load and validate a fpgacapZero ``.prob`` sidecar."""

    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{p}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{p}: expected a JSON object")
    fmt = data.get("format")
    if fmt != PROBE_FILE_FORMAT:
        raise ValueError(f"{p}: unsupported probe file format {fmt!r}")

    sample_width = data.get("sample_width")
    sample_width_i = int(sample_width) if sample_width is not None else None
    if sample_width_i is not None and sample_width_i <= 0:
        raise ValueError(f"{p}: sample_width must be > 0")

    sample_clock_hz = data.get("sample_clock_hz")
    sample_clock_hz_i = int(sample_clock_hz) if sample_clock_hz is not None else None
    if sample_clock_hz_i is not None and sample_clock_hz_i <= 0:
        raise ValueError(f"{p}: sample_clock_hz must be > 0")

    raw_probes = data.get("probes")
    if not isinstance(raw_probes, list) or not raw_probes:
        raise ValueError(f"{p}: probes must be a non-empty array")

    probes = [_parse_probe_entry(entry) for entry in raw_probes]
    _validate_probe_specs(probes, sample_width=sample_width_i)
    return ProbeFile(
        probes=probes,
        sample_width=sample_width_i,
        sample_clock_hz=sample_clock_hz_i,
        core=str(data.get("core", "ela")),
    )


def write_probe_file(
    path: str | Path,
    probes: Iterable[ProbeSpec],
    *,
    sample_width: int | None = None,
    sample_clock_hz: int | None = None,
    core: str = "ela",
) -> None:
    """Write a fpgacapZero ``.prob`` sidecar."""

    data = probe_file_dict(
        probes,
        sample_width=sample_width,
        sample_clock_hz=sample_clock_hz,
        core=core,
    )
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "PROBE_FILE_FORMAT",
    "ProbeFile",
    "load_probe_file",
    "probe_file_dict",
    "probes_to_arg",
    "write_probe_file",
]
