# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from ._version import _version_tuple
from .transport import Transport

_ADDR_VERSION = 0x0000
# ASCII "LA" (Logic Analyzer) packed into VERSION[15:0] as the ELA core
# identity magic.  Hosts must reject any bitstream that does not present
# this magic before touching any other ELA register on the same chain.
ELA_CORE_ID = 0x4C41
_ELA_CORE_ID = ELA_CORE_ID  # in-module alias


def expected_ela_version_reg() -> int:
    """Compute the VERSION register value the bitstream should report.

    Layout:  {major[7:0], minor[7:0], core_id[15:0]}, derived from
    ``fcapz.__version__`` (which itself reads the canonical VERSION
    file at the repo root via setuptools' dynamic version mechanism).
    Used by tests so nobody hardcodes the constant in multiple files;
    bumping VERSION + re-running ``tools/sync_version.py`` is the only
    place a release version lives.
    """
    major, minor, _patch = _version_tuple()
    return (
        ((major & 0xFF) << 24)
        | ((minor & 0xFF) << 16)
        | (ELA_CORE_ID & 0xFFFF)
    )


_ADDR_CTRL = 0x0004
_ADDR_STATUS = 0x0008
_ADDR_SAMPLE_W = 0x000C
_ADDR_DEPTH = 0x0010
_ADDR_PRETRIG = 0x0014
_ADDR_POSTTRIG = 0x0018
_ADDR_CAPTURE_LEN = 0x001C
_ADDR_TRIG_MODE = 0x0020
_ADDR_TRIG_VALUE = 0x0024
_ADDR_TRIG_MASK = 0x0028
_ADDR_CHAN_SEL = 0x00A0
_ADDR_NUM_CHAN = 0x00A4
_ADDR_DECIM = 0x00B0
_ADDR_TRIG_EXT = 0x00B4
_ADDR_NUM_SEGMENTS = 0x00B8
_ADDR_SEG_STATUS = 0x00BC
_ADDR_SEG_SEL = 0x00C0
_ADDR_SEG_START = 0x00C8
_ADDR_TIMESTAMP_W = 0x00C4
_ADDR_FEATURES = 0x003C
_ADDR_SEQ_BASE = 0x0040
_SEQ_STRIDE = 20
_ADDR_PROBE_SEL = 0x00AC
_ADDR_PROBE_MUX_W = 0x00D0
_ADDR_TRIG_DELAY = 0x00D4

# Order matches :meth:`Analyzer.probe` field extraction (hw_server pipelined read).
_ELA_PROBE_ADDRS: tuple[int, ...] = (
    _ADDR_VERSION,
    _ADDR_SAMPLE_W,
    _ADDR_DEPTH,
    _ADDR_NUM_CHAN,
    _ADDR_FEATURES,
    _ADDR_TIMESTAMP_W,
    _ADDR_NUM_SEGMENTS,
    _ADDR_PROBE_MUX_W,
)
_ADDR_SQ_MODE = 0x0030
_ADDR_SQ_VALUE = 0x0034
_ADDR_SQ_MASK = 0x0038
_ADDR_DATA_BASE = 0x0100

_STATUS_DONE = 1 << 2
_STATUS_OVERFLOW = 1 << 3

_CTRL_ARM = 1 << 0
_CTRL_RESET = 1 << 1

_TRIG_VALUE_MATCH = 1 << 0
_TRIG_EDGE_DETECT = 1 << 1


@dataclass
class SequencerStage:
    """One stage of the hardware trigger sequencer."""

    cmp_mode_a: int = 0       # compare mode A (0-8)
    cmp_mode_b: int = 0       # compare mode B (0-8)
    combine: int = 0          # 0=A_only, 1=B_only, 2=AND, 3=OR
    next_state: int = 0       # next sequencer state index
    is_final: bool = False    # True = trigger fires on match
    count_target: int = 1     # match-count before advancing/firing
    value_a: int = 0          # comparator A reference value
    mask_a: int = 0xFFFFFFFF  # comparator A mask
    value_b: int = 0          # comparator B reference value
    mask_b: int = 0xFFFFFFFF  # comparator B mask

    def pack_cfg(self) -> int:
        """Pack into the SEQ_CFG 32-bit register layout."""
        cfg = (self.cmp_mode_a & 0xF)
        cfg |= (self.cmp_mode_b & 0xF) << 4
        cfg |= (self.combine & 0x3) << 8
        cfg |= (self.next_state & 0x3) << 10
        cfg |= (int(self.is_final) & 0x1) << 12
        cfg |= (self.count_target & 0xFFFF) << 16
        return cfg


@dataclass
class TriggerConfig:
    mode: str
    value: int
    mask: int


@dataclass
class ProbeSpec:
    """Named sub-signal within the packed sample word."""

    name: str
    width: int
    lsb: int = 0


@dataclass
class CaptureConfig:
    pretrigger: int
    posttrigger: int
    trigger: TriggerConfig
    sample_width: int = 8
    depth: int = 1024
    sample_clock_hz: int = 100_000_000
    probes: List[ProbeSpec] = field(default_factory=list)
    channel: int = 0  # probe mux channel (0..NUM_CHANNELS-1)
    decimation: int = 0  # 0=every cycle, N=every N+1 cycles
    ext_trigger_mode: int = 0  # 0=disabled, 1=OR, 2=AND
    sequence: list[SequencerStage] | None = None  # trigger sequencer stages
    probe_sel: int = 0  # runtime probe mux slice index
    stor_qual_mode: int = 0    # 0=disabled; 1=store when match, 2=store when no match
    stor_qual_value: int = 0   # storage qualification comparison value
    stor_qual_mask: int = 0    # storage qualification mask
    trigger_delay: int = 0     # post-trigger delay in sample-clock cycles
                               # (0..65535) — shifts the committed trigger
                               # sample N cycles after the trigger event,
                               # compensating for upstream pipeline latency


@dataclass
class CaptureResult:
    config: CaptureConfig
    samples: List[int] = field(default_factory=list)
    overflow: bool = False
    timestamps: List[int] = field(default_factory=list)
    segment: int = 0  # which segment this result is from


def vcd_simulation_times(result: CaptureResult) -> list[int]:
    """Per-sample times for VCD ``#`` lines (``len(result.samples)`` entries).

    Without hardware timestamps this is ``0 .. n-1`` (one time unit per stored
    sample, matching the historical behaviour).

    With timestamps, values are **shifted by the first sample** so each dump
    starts at 0 while preserving relative spacing. Raw counters often jump
    between successive captures (continuous mode / live VCD reload); using
    absolute values as ``#`` time made the viewer timeline and timescale look
    broken. The ``timestamp`` wire in the VCD still carries raw hardware values.

    Times are forced **non-decreasing** so the file stays valid if the buffer
    has duplicate or slightly regressed counter values.
    """
    n = len(result.samples)
    ts = result.timestamps
    if ts and len(ts) == n:
        base = int(ts[0])
        out: list[int] = []
        last = -1
        for i in range(n):
            rel = int(ts[i]) - base
            t = max(rel, last + 1, 0)
            out.append(t)
            last = t
        return out
    return list(range(n))


class Analyzer:
    def __init__(self, transport: Transport):
        self.transport = transport
        self._config: CaptureConfig | None = None
        self._hw_timestamp_w: int = 0
        self._hw_num_segments: int = 1

    def connect(self) -> None:
        self.transport.connect()

    def close(self, *, fast: bool = False) -> None:
        """Close the JTAG transport. ``fast=True`` skips long waits (e.g. Ctrl+C)."""
        if fast:
            closer = getattr(self.transport, "close_fast", None)
            if callable(closer):
                closer()
                return
        self.transport.close()

    def reset(self) -> None:
        self.transport.write_reg(_ADDR_CTRL, _CTRL_RESET)

    @staticmethod
    def _validate_probes(probes: List[ProbeSpec], sample_width: int) -> None:
        occupied: set[int] = set()
        for probe in probes:
            if not probe.name:
                raise ValueError("probe name must be non-empty")
            if probe.width <= 0:
                raise ValueError(f"probe '{probe.name}' width must be > 0")
            if probe.lsb < 0:
                raise ValueError(f"probe '{probe.name}' lsb must be >= 0")
            msb = probe.lsb + probe.width
            if msb > sample_width:
                raise ValueError(
                    f"probe '{probe.name}' exceeds sample width {sample_width}"
                )
            for bit in range(probe.lsb, msb):
                if bit in occupied:
                    raise ValueError(f"probe '{probe.name}' overlaps another probe")
                occupied.add(bit)

    def configure(self, config: CaptureConfig) -> None:
        if config.pretrigger < 0 or config.posttrigger < 0:
            raise ValueError("pretrigger/posttrigger must be >= 0")
        if config.pretrigger + config.posttrigger + 1 > config.depth:
            raise ValueError("pre+post+1 exceeds configured depth")
        if config.sample_clock_hz <= 0:
            raise ValueError("sample_clock_hz must be > 0")
        if not (0 <= config.trigger_delay <= 0xFFFF):
            raise ValueError(
                f"trigger_delay must be 0..65535, got {config.trigger_delay}"
            )

        self._validate_probes(config.probes, config.sample_width)

        # Validate host config against the synthesized core to avoid silent
        # mismatch between CLI defaults and FPGA bitstream parameters.
        _read = getattr(self.transport, "read_reg_verified", self.transport.read_reg)
        hw_sample_w = int(_read(_ADDR_SAMPLE_W))
        hw_depth = int(_read(_ADDR_DEPTH))
        hw_num_chan = max(1, int(_read(_ADDR_NUM_CHAN)))
        if config.sample_width != hw_sample_w:
            raise ValueError(
                f"sample_width mismatch: config={config.sample_width}, hw={hw_sample_w}"
            )
        if config.depth != hw_depth:
            raise ValueError(f"depth mismatch: config={config.depth}, hw={hw_depth}")
        if not (0 <= config.channel < hw_num_chan):
            raise ValueError(
                f"channel out of range: config={config.channel}, hw_num_channels={hw_num_chan}"
            )

        # Auto-detect hw capabilities
        hw_features = int(_read(_ADDR_FEATURES))
        hw_trig_stages = hw_features & 0xF  # bits[3:0]
        self._hw_timestamp_w = int(_read(_ADDR_TIMESTAMP_W))
        self._hw_num_segments = max(1, int(_read(_ADDR_NUM_SEGMENTS)))

        # Segment depth check
        if self._hw_num_segments > 1:
            seg_depth = config.depth // self._hw_num_segments
            if config.pretrigger + config.posttrigger + 1 > seg_depth:
                raise ValueError(
                    f"pre+post+1 exceeds segment depth {seg_depth}"
                )

        mode_bits = 0
        if config.trigger.mode in ("value_match", "both"):
            mode_bits |= _TRIG_VALUE_MATCH
        if config.trigger.mode in ("edge_detect", "both"):
            mode_bits |= _TRIG_EDGE_DETECT
        if mode_bits == 0:
            raise ValueError("invalid trigger mode")

        self.transport.write_reg(_ADDR_PRETRIG, config.pretrigger)
        self.transport.write_reg(_ADDR_POSTTRIG, config.posttrigger)
        self.transport.write_reg(_ADDR_TRIG_MODE, mode_bits)
        self.transport.write_reg(_ADDR_TRIG_VALUE, config.trigger.value)
        self.transport.write_reg(_ADDR_TRIG_MASK, config.trigger.mask)
        self.transport.write_reg(_ADDR_CHAN_SEL, config.channel)
        self.transport.write_reg(_ADDR_DECIM, config.decimation)
        self.transport.write_reg(_ADDR_TRIG_EXT, config.ext_trigger_mode)
        self.transport.write_reg(_ADDR_PROBE_SEL, config.probe_sel)
        self.transport.write_reg(_ADDR_TRIG_DELAY, config.trigger_delay)
        if config.stor_qual_mode:
            self.transport.write_reg(_ADDR_SQ_MODE, config.stor_qual_mode)
            self.transport.write_reg(_ADDR_SQ_VALUE, config.stor_qual_value)
            self.transport.write_reg(_ADDR_SQ_MASK, config.stor_qual_mask)

        if config.sequence is not None:
            if hw_trig_stages == 0:
                raise ValueError(
                    "trigger sequencer not present in this bitstream (TRIG_STAGES=0)"
                )
            if len(config.sequence) > hw_trig_stages:
                raise ValueError(
                    f"sequence has {len(config.sequence)} stages but hw supports "
                    f"only {hw_trig_stages}"
                )
            for idx, stage in enumerate(config.sequence):
                base = _ADDR_SEQ_BASE + idx * _SEQ_STRIDE
                self.transport.write_reg(base + 0, stage.pack_cfg())
                self.transport.write_reg(base + 4, stage.value_a)
                self.transport.write_reg(base + 8, stage.mask_a)
                self.transport.write_reg(base + 12, stage.value_b)
                self.transport.write_reg(base + 16, stage.mask_b)

        self._config = config

    def arm(self) -> None:
        self.transport.write_reg(_ADDR_CTRL, _CTRL_ARM)

    def wait_done(self, timeout: float = 10.0, poll_interval: float = 0.05) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.transport.read_reg(_ADDR_STATUS)
            if status & _STATUS_DONE:
                return True
            time.sleep(poll_interval)
        return False

    def _read_timestamps(self, total: int) -> list[int]:
        """Read timestamp values for captured samples."""
        if self._hw_timestamp_w == 0:
            return []
        sw = self._config.sample_width if self._config else 8
        words_per_sample = (sw + 31) // 32
        ts_base = _ADDR_DATA_BASE + self._config.depth * words_per_sample * 4
        ts_words_per = (self._hw_timestamp_w + 31) // 32
        ts_word_count = total * ts_words_per
        # Timestamp RAM is stable once capture is done, but the hardware
        # USER1 readback path can return one stale word immediately after the
        # USER2 sample burst.  Read twice and require stability; a third read
        # resolves the rare case where only the second block is transient.
        raw_a = self.transport.read_block(ts_base, ts_word_count)
        raw_b = self.transport.read_block(ts_base, ts_word_count)
        if raw_a == raw_b:
            raw = raw_b
        else:
            raw_c = self.transport.read_block(ts_base, ts_word_count)
            raw = raw_c if raw_b != raw_c else raw_b
        timestamps = []
        mask = (1 << self._hw_timestamp_w) - 1
        if ts_words_per == 1:
            timestamps = [v & mask for v in raw]
        else:
            for i in range(0, len(raw), ts_words_per):
                val = 0
                for j in range(min(ts_words_per, len(raw) - i)):
                    val |= (raw[i + j] & 0xFFFFFFFF) << (j * 32)
                timestamps.append(val & mask)
        return timestamps

    def capture(self, timeout: float = 10.0) -> CaptureResult:
        if self._config is None:
            raise RuntimeError("call configure() before capture()")
        if not self.wait_done(timeout):
            raise TimeoutError("capture did not complete within timeout")

        status = self.transport.read_reg(_ADDR_STATUS)
        fallback_total = self._config.pretrigger + self._config.posttrigger + 1
        reported_total = int(self.transport.read_reg(_ADDR_CAPTURE_LEN))
        if 0 < reported_total <= self._config.depth:
            total = reported_total
        else:
            total = fallback_total
        sw = self._config.sample_width
        words_per_sample = (sw + 31) // 32
        raw = self.transport.read_block(_ADDR_DATA_BASE, total * words_per_sample)
        mask = (1 << sw) - 1
        if words_per_sample == 1:
            samples = [v & mask for v in raw]
        else:
            # Wide samples: reassemble from 32-bit chunks.
            samples = []
            for i in range(0, len(raw), words_per_sample):
                val = 0
                for j in range(min(words_per_sample, len(raw) - i)):
                    val |= (raw[i + j] & 0xFFFFFFFF) << (j * 32)
                samples.append(val & mask)

        timestamps = self._read_timestamps(total)

        return CaptureResult(
            config=self._config,
            samples=samples,
            overflow=bool(status & _STATUS_OVERFLOW),
            timestamps=timestamps,
        )

    def wait_all_segments_done(
        self, timeout: float = 10.0, poll_interval: float = 0.05
    ) -> bool:
        """Wait until all segments have completed capture."""
        return self.wait_done(timeout, poll_interval)

    def capture_segment(self, seg_idx: int, timeout: float = 10.0) -> CaptureResult:
        """Read back data from a specific segment after all segments are done."""
        if self._config is None:
            raise RuntimeError("call configure() before capture_segment()")

        # Select segment for readback.  seg_start_ptr[seg_sel] is read
        # directly by the burst engine (stable after all_seg_done).
        self.transport.write_reg(_ADDR_SEG_SEL, seg_idx)

        status = self.transport.read_reg(_ADDR_STATUS)
        fallback_total = self._config.pretrigger + self._config.posttrigger + 1
        reported_total = int(self.transport.read_reg(_ADDR_CAPTURE_LEN))
        if 0 < reported_total <= self._config.depth:
            total = reported_total
        else:
            total = fallback_total

        sw = self._config.sample_width
        words_per_sample = (sw + 31) // 32
        raw = self.transport.read_block(_ADDR_DATA_BASE, total * words_per_sample)
        mask = (1 << sw) - 1
        if words_per_sample == 1:
            samples = [v & mask for v in raw]
        else:
            samples = []
            for i in range(0, len(raw), words_per_sample):
                val = 0
                for j in range(min(words_per_sample, len(raw) - i)):
                    val |= (raw[i + j] & 0xFFFFFFFF) << (j * 32)
                samples.append(val & mask)

        timestamps = self._read_timestamps(total)

        return CaptureResult(
            config=self._config,
            samples=samples,
            overflow=bool(status & _STATUS_OVERFLOW),
            timestamps=timestamps,
            segment=seg_idx,
        )

    def export_json(self, result: CaptureResult) -> Dict:
        cfg = result.config
        d: Dict = {
            "version": "1.0",
            "sample_clock_hz": cfg.sample_clock_hz,
            "sample_width": cfg.sample_width,
            "depth": cfg.depth,
            "pretrigger": cfg.pretrigger,
            "posttrigger": cfg.posttrigger,
            "channel": cfg.channel,
            "decimation": cfg.decimation,
            "ext_trigger_mode": cfg.ext_trigger_mode,
            "trigger": {
                "mode": cfg.trigger.mode,
                "value": cfg.trigger.value,
                "mask": cfg.trigger.mask,
            },
            "overflow": result.overflow,
            "segment": result.segment,
            "samples": [{"index": i, "value": v} for i, v in enumerate(result.samples)],
        }
        if result.timestamps:
            d["timestamps"] = [
                {"index": i, "value": v} for i, v in enumerate(result.timestamps)
            ]
        return d

    def write_json(self, result: CaptureResult, out_path: str) -> None:
        Path(out_path).write_text(
            json.dumps(self.export_json(result), indent=2), encoding="utf-8"
        )

    def export_csv_text(self, result: CaptureResult) -> str:
        if result.timestamps:
            lines = ["index,value,timestamp"]
            for i, (v, t) in enumerate(zip(result.samples, result.timestamps)):
                lines.append(f"{i},{v},{t}")
        else:
            lines = ["index,value"]
            for i, v in enumerate(result.samples):
                lines.append(f"{i},{v}")
        return "\n".join(lines) + "\n"

    def write_csv(self, result: CaptureResult, out_path: str) -> None:
        Path(out_path).write_text(self.export_csv_text(result), encoding="ascii")

    def export_vcd_text(self, result: CaptureResult) -> str:
        cfg = result.config
        sig_w = cfg.sample_width
        timescale_ns = max(1, int(round(1_000_000_000 / cfg.sample_clock_hz)))

        # Build signal list: use probe definitions if available, else one raw signal.
        signals: list[tuple[str, str, int, int]] = []  # (var_id, name, width, lsb)
        next_id = ord("a")
        if cfg.probes:
            for probe in cfg.probes:
                signals.append((chr(next_id), probe.name, probe.width, probe.lsb))
                next_id += 1
        else:
            signals.append(("s", "sample", sig_w, 0))
            next_id = ord("t")

        # Add timestamp signal if available
        ts_var_id = ""
        if result.timestamps:
            ts_var_id = chr(next_id)

        lines = [
            "$date",
            "  generated by fcapz",
            "$end",
            "$version",
            "  fcapz-mvp",
            "$end",
            "$timescale",
            f"  {timescale_ns} ns",
            "$end",
            "$scope module logic $end",
        ]
        for var_id, name, width, _ in signals:
            lines.append(f"$var wire {width} {var_id} {name} $end")
        if ts_var_id:
            ts_w = self._hw_timestamp_w if self._hw_timestamp_w else 32
            lines.append(f"$var wire {ts_w} {ts_var_id} timestamp $end")
        lines.extend([
            "$upscope $end",
            "$enddefinitions $end",
            "$dumpvars",
        ])
        for var_id, _, width, _ in signals:
            lines.append(f"b{'0' * width} {var_id}")
        if ts_var_id:
            lines.append(f"b{'0' * ts_w} {ts_var_id}")
        lines.append("$end")

        sim_times = vcd_simulation_times(result)
        for i, sample in enumerate(result.samples):
            lines.append(f"#{sim_times[i]}")
            for var_id, _, width, lsb in signals:
                val = (sample >> lsb) & ((1 << width) - 1)
                bits = format(val, f"0{width}b")
                lines.append(f"b{bits} {var_id}")
            if ts_var_id and i < len(result.timestamps):
                ts_bits = format(result.timestamps[i], f"0{ts_w}b")
                lines.append(f"b{ts_bits} {ts_var_id}")
        return "\n".join(lines) + "\n"

    def write_vcd(self, result: CaptureResult, out_path: str) -> None:
        Path(out_path).write_text(self.export_vcd_text(result), encoding="ascii")

    def capture_continuous(
        self,
        count: int = 0,
        timeout_per: float = 10.0,
    ):
        """Generator that yields successive ``CaptureResult`` objects.

        After each capture completes, the core is **automatically re-armed**
        (same idea as “continuous” / auto re-arm in many vendor ILAs): each
        iteration calls :meth:`arm`, then :meth:`capture` to wait for the next
        trigger and read back. Yields *count* results, or runs indefinitely if
        *count* is 0.
        """
        if self._config is None:
            raise RuntimeError("call configure() before capture_continuous()")
        yielded = 0
        while count == 0 or yielded < count:
            self.arm()
            result = self.capture(timeout=timeout_per)
            yield result
            yielded += 1

    def probe(self) -> Dict:
        """Read the ELA identity and feature registers.

        Verifies the VERSION register's low-16 magic equals the ASCII
        "LA" core identifier (0x4C41, Logic Analyzer).  Raises
        RuntimeError on mismatch so the caller cannot accidentally
        drive a non-fcapz bitstream.

        When the transport exposes
        :meth:`~fcapz.transport.XilinxHwServerTransport.read_regs_pipelined_user1`
        (hw_server), all probe registers share **one** XSDB ``_send`` plus
        a pipeline flush read.
        Otherwise uses ``read_reg_verified`` for VERSION when the transport implements it,
        then :meth:`~fcapz.transport.Transport.read_reg` for the remaining registers.

        Returns a dict with `version_major`, `version_minor`, `core_id`
        (always 0x4C41 on success),         `trig_stages` (FEATURES[3:0]: hardware
        trigger sequencer depth, 0 if absent), `has_storage_qualification`
        (FEATURES[4]), and the rest of the feature flags.
        """
        piped = getattr(self.transport, "read_regs_pipelined_user1", None)
        if callable(piped):
            vals = piped(list(_ELA_PROBE_ADDRS))
            version = int(vals[0])
            sample_w = int(vals[1])
            depth = int(vals[2])
            num_chan = int(vals[3])
            features = int(vals[4])
            timestamp_w = int(vals[5])
            num_segments = max(1, int(vals[6]))
            probe_mux_w = int(vals[7])
        else:
            _vread = getattr(self.transport, "read_reg_verified", self.transport.read_reg)
            version = int(_vread(_ADDR_VERSION))
            sample_w = int(self.transport.read_reg(_ADDR_SAMPLE_W))
            depth = int(self.transport.read_reg(_ADDR_DEPTH))
            num_chan = int(self.transport.read_reg(_ADDR_NUM_CHAN))
            features = int(self.transport.read_reg(_ADDR_FEATURES))
            timestamp_w = int(self.transport.read_reg(_ADDR_TIMESTAMP_W))
            num_segments = max(1, int(self.transport.read_reg(_ADDR_NUM_SEGMENTS)))
            probe_mux_w = int(self.transport.read_reg(_ADDR_PROBE_MUX_W))
        core_id = version & 0xFFFF
        if core_id != _ELA_CORE_ID:
            raise RuntimeError(
                f"ELA core identity check failed at VERSION[15:0]: "
                f"expected 0x{_ELA_CORE_ID:04X} ('LA'), got 0x{core_id:04X}. "
                f"Wrong JTAG chain, wrong bitstream, or core not loaded?"
            )
        return {
            "version_major": (version >> 24) & 0xFF,
            "version_minor": (version >> 16) & 0xFF,
            "core_id": core_id,
            "sample_width": sample_w,
            "depth": depth,
            "num_channels": num_chan if num_chan >= 1 else 1,
            "trig_stages": int(features & 0xF),
            "has_storage_qualification": bool(features & (1 << 4)),
            "has_decimation": bool(features & (1 << 5)),
            "has_ext_trigger": bool(features & (1 << 6)),
            "has_timestamp": bool(features & (1 << 7)),
            "timestamp_width": timestamp_w,
            "num_segments": num_segments,
            "probe_mux_w": probe_mux_w,
        }
