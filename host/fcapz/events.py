# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""LLM-friendly event extraction helpers for capture results.

These functions take a ``CaptureResult`` and return structured data
describing edges, transitions, bursts, and other patterns that an LLM
can consume without parsing raw sample arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .analyzer import CaptureResult


@dataclass
class ProbeDefinition:
    """Defines a named sub-signal within the packed sample word."""

    name: str
    width: int
    lsb: int  # bit offset from sample LSB

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError(f"ProbeDefinition '{self.name}': width must be > 0, got {self.width}")
        if self.lsb < 0:
            raise ValueError(f"ProbeDefinition '{self.name}': lsb must be >= 0, got {self.lsb}")

    def extract(self, sample: int) -> int:
        return (sample >> self.lsb) & ((1 << self.width) - 1)


@dataclass
class Edge:
    """A value transition between consecutive samples."""

    index: int
    old_value: int
    new_value: int
    probe: str = "sample"


@dataclass
class Burst:
    """A contiguous run of samples where a signal holds a constant value."""

    start: int
    end: int  # exclusive
    value: int
    probe: str = "sample"

    @property
    def length(self) -> int:
        return self.end - self.start


def find_edges(
    result: CaptureResult,
    probe: Optional[ProbeDefinition] = None,
    mask: int = 0xFFFFFFFF,
) -> List[Edge]:
    """Return all value-change edges in the capture.

    If *probe* is given, only that sub-signal is examined.  Otherwise the
    full sample value is used, masked by *mask*.
    """
    samples = result.samples
    if not samples:
        return []

    edges: list[Edge] = []
    name = probe.name if probe else "sample"

    def val(s: int) -> int:
        if probe:
            return probe.extract(s)
        return s & mask

    prev = val(samples[0])
    for i in range(1, len(samples)):
        cur = val(samples[i])
        if cur != prev:
            edges.append(Edge(index=i, old_value=prev, new_value=cur, probe=name))
            prev = cur
    return edges


def find_rising_edges(
    result: CaptureResult,
    bit: int,
    probe: Optional[ProbeDefinition] = None,
) -> List[int]:
    """Return indices where *bit* transitions from 0 to 1."""
    samples = result.samples
    if not samples:
        return []

    indices: list[int] = []
    def val(s: int) -> int:
        v = probe.extract(s) if probe else s
        return (v >> bit) & 1

    prev = val(samples[0])
    for i in range(1, len(samples)):
        cur = val(samples[i])
        if prev == 0 and cur == 1:
            indices.append(i)
        prev = cur
    return indices


def find_falling_edges(
    result: CaptureResult,
    bit: int,
    probe: Optional[ProbeDefinition] = None,
) -> List[int]:
    """Return indices where *bit* transitions from 1 to 0."""
    samples = result.samples
    if not samples:
        return []

    indices: list[int] = []
    def val(s: int) -> int:
        v = probe.extract(s) if probe else s
        return (v >> bit) & 1

    prev = val(samples[0])
    for i in range(1, len(samples)):
        cur = val(samples[i])
        if prev == 1 and cur == 0:
            indices.append(i)
        prev = cur
    return indices


def find_bursts(
    result: CaptureResult,
    probe: Optional[ProbeDefinition] = None,
    mask: int = 0xFFFFFFFF,
) -> List[Burst]:
    """Return contiguous runs of constant value."""
    samples = result.samples
    if not samples:
        return []

    name = probe.name if probe else "sample"

    def val(s: int) -> int:
        if probe:
            return probe.extract(s)
        return s & mask

    bursts: list[Burst] = []
    start = 0
    cur_val = val(samples[0])

    for i in range(1, len(samples)):
        v = val(samples[i])
        if v != cur_val:
            bursts.append(Burst(start=start, end=i, value=cur_val, probe=name))
            start = i
            cur_val = v
    bursts.append(Burst(start=start, end=len(samples), value=cur_val, probe=name))
    return bursts


def frequency_estimate(
    result: CaptureResult,
    bit: int,
    probe: Optional[ProbeDefinition] = None,
) -> Optional[float]:
    """Estimate the toggle frequency of *bit* in Hz.

    Returns ``None`` if fewer than 2 rising edges are found.
    """
    rising = find_rising_edges(result, bit, probe)
    if len(rising) < 2:
        return None
    period_samples = (rising[-1] - rising[0]) / (len(rising) - 1)
    if period_samples <= 0:
        return None
    return result.config.sample_clock_hz / period_samples


def summarize(
    result: CaptureResult,
    probes: Optional[List[ProbeDefinition]] = None,
) -> Dict:
    """Produce a structured summary of the capture for LLM consumption.

    Returns a dict with overview stats, value ranges, edge counts, and
    notable patterns for each probe (or the raw sample if no probes).
    """
    cfg = result.config
    samples = result.samples

    summary: Dict = {
        "total_samples": len(samples),
        "sample_width": cfg.sample_width,
        "sample_clock_hz": cfg.sample_clock_hz,
        "pretrigger": cfg.pretrigger,
        "posttrigger": cfg.posttrigger,
        "trigger": {
            "mode": cfg.trigger.mode,
            "value": cfg.trigger.value,
            "mask": cfg.trigger.mask,
        },
        "overflow": result.overflow,
        "signals": [],
    }

    targets: list[tuple[str, Optional[ProbeDefinition]]] = []
    if probes:
        for p in probes:
            targets.append((p.name, p))
    else:
        targets.append(("sample", None))

    for name, probe in targets:
        if probe:
            values = [probe.extract(s) for s in samples]
        else:
            mask = (1 << cfg.sample_width) - 1
            values = [s & mask for s in samples]

        edges = find_edges(result, probe)
        bursts = find_bursts(result, probe)

        sig_info: Dict = {
            "name": name,
            "min": min(values) if values else 0,
            "max": max(values) if values else 0,
            "unique_values": len(set(values)),
            "edge_count": len(edges),
            "burst_count": len(bursts),
            "longest_burst": None,
            "first_edge": None,
            "last_edge": None,
        }

        if bursts:
            longest = max(bursts, key=lambda b: b.length)
            sig_info["longest_burst"] = {
                "value": longest.value,
                "length": longest.length,
                "start": longest.start,
            }

        if edges:
            sig_info["first_edge"] = {
                "index": edges[0].index,
                "from": edges[0].old_value,
                "to": edges[0].new_value,
            }
            sig_info["last_edge"] = {
                "index": edges[-1].index,
                "from": edges[-1].old_value,
                "to": edges[-1].new_value,
            }

        summary["signals"].append(sig_info)

    return summary
