# 05 — ELA core

> **Goal**: deep dive on the Embedded Logic Analyzer.  By the end of
> this chapter you will understand every trigger mode, every storage
> option, and how the runtime knobs (decimation, segments, probe mux,
> startup arm, trigger holdoff, trigger delay) interact with the basic
> capture flow.
>
> **Pre-reads**: [01_overview](01_overview.md),
> [03_first_capture](03_first_capture.md),
> [04_rtl_integration](04_rtl_integration.md).

## The capture flow in one diagram

```
                  ┌──────────────┐
arm_pulse  ──────►│   ARMED      │ ── trigger_hit ──┐
                  │ (recording   │                  │
                  │  pre-trig    │                  ▼
                  │  history)    │           ┌──────────────┐
                  └──────────────┘           │  TRIGGERED   │
                                              │ (counting    │
                                              │  posttrig)   │
                                              └──────────────┘
                                                     │
                                                     │ post_count == posttrig_len
                                                     ▼
                                              ┌──────────────┐
                                              │    DONE      │ ── host reads buffer ──►
                                              └──────────────┘
```

The ELA is a circular buffer.  When you arm it, samples flow into a
dual-port BRAM continuously.  When the trigger fires, it captures
`posttrigger_len` more samples and stops.  The host then reads back
`pretrigger + 1 + posttrigger` samples — the pre-trigger window
shows what was happening *before* the trigger fired, the trigger
sample itself, and the post-trigger window.

On timing-sensitive builds, especially with `INPUT_PIPE=1`, the BRAM
write command is itself registered: write enable, address, sample data,
and timestamp data are captured together before they drive the inferred
RAM.  That keeps the trigger/store decision off the same-cycle BRAM
write path, while preserving the externally visible capture window and
trigger-sample alignment.

The trigger sample sits at index `pretrigger` in the captured array
(0-indexed).  So if you `--pretrigger 8 --posttrigger 16`, you get
25 samples total, and `samples[8]` is the one that caused the
trigger to fire.

## Simple trigger: value match, edge detect, both

The simplest trigger you can configure is a value match on the probe
bus:

```bash
fcapz capture \
    --trigger-mode value_match \
    --trigger-value 0x42 \
    --trigger-mask  0xFF \
    --pretrigger 8 --posttrigger 16 \
    ...
```

This fires the trigger when `(probe_in & trigger_mask) == (trigger_value & trigger_mask)`.
The mask lets you ignore bits — `--trigger-mask 0x0F` means "match
the low 4 bits, ignore the high 4 bits".

`edge_detect` mode triggers when the masked bits **change** between
two consecutive samples (any change, in either direction).  Use it
with `--trigger-mask 0x01` to trigger on the LSB toggling, etc.

`both` mode is the OR of the two: `value_match` OR `edge_detect`.
Useful when you want "trigger when this signal goes HIGH or LOW for
the first time".

These three modes map to the legacy `TRIG_MODE` register at `0x0020`
and use a single comparator (the "stage 0 simple trigger") inside
the ELA core.  Anything more complex needs the **trigger sequencer**.

## Trigger sequencer (TRIG_STAGES > 1)

When you build the ELA with `TRIG_STAGES=2..4`, the core gets a
multi-stage state machine where each stage has **two comparators
(A and B)** with one of 9 compare modes each, and a combine rule
between A and B.

The sequencer is the most powerful trigger feature in fcapz.  It
lets you say things like:

> "Wait for `addr == 0x4000_0000` to happen, then 5 clock cycles
> later, when `data > 0x80`, fire the trigger"

or

> "Trigger only after seeing `start` go HIGH AND `stall` go LOW,
> followed by `error` going HIGH within the next 100 cycles"

### The 9 compare modes

| Code | Mode | Operation |
|---|---|---|
| 0 | EQ | `(probe & mask) == (value & mask)` |
| 1 | NEQ | `(probe & mask) != (value & mask)` |
| 2 | LT | `(probe & mask) <  (value & mask)` (unsigned) |
| 3 | GT | `(probe & mask) >  (value & mask)` (unsigned) |
| 4 | LEQ | `(probe & mask) <= (value & mask)` |
| 5 | GEQ | `(probe & mask) >= (value & mask)` |
| 6 | RISING | masked bits transition from all-zero to non-zero |
| 7 | FALLING | masked bits transition from non-zero to all-zero |
| 8 | CHANGED | any masked bit changed from the previous sample |

Each stage's two comparators run in parallel, then combine via:

| Combine | Meaning |
|---|---|
| 0 | A only (B ignored) |
| 1 | B only (A ignored) |
| 2 | A AND B |
| 3 | A OR B |

Each stage also has an **occurrence count** — wait until the combined
condition has been true `count_target` times before advancing — and
a `next_state` field that says which stage to jump to when the
condition fires.  The final stage that fires the trigger sets
`is_final = 1`.

### Configuring the sequencer from the host

The sequencer is a list of `SequencerStage` dataclass instances:

```python
from fcapz import Analyzer, CaptureConfig, TriggerConfig, SequencerStage

stage0 = SequencerStage(
    cmp_mode_a   = 0,           # EQ
    cmp_mode_b   = 0,
    combine      = 0,           # A only
    next_state   = 1,           # advance to stage 1 when this fires
    is_final     = False,
    count_target = 1,           # advance after one match
    value_a      = 0x4000_0000,
    mask_a       = 0xFFFF_FFFF,
)

stage1 = SequencerStage(
    cmp_mode_a   = 3,           # GT
    cmp_mode_b   = 0,
    combine      = 0,           # A only
    next_state   = 0,
    is_final     = True,        # firing this stage fires the overall trigger
    count_target = 1,
    value_a      = 0x80,
    mask_a       = 0xFF,
)

cfg = CaptureConfig(
    pretrigger  = 8,
    posttrigger = 16,
    trigger     = TriggerConfig(mode="value_match", value=0, mask=0xFF),
    sample_width= 32,
    depth       = 1024,
    sequence    = [stage0, stage1],   # ← the sequencer
)
analyzer.configure(cfg)
analyzer.arm()
result = analyzer.capture(timeout=10.0)
```

`Analyzer.configure()` writes each stage to the per-stage register
block at `ADDR_SEQ_BASE = 0x0040 + N * 20` and validates that
`len(sequence) <= hw_trig_stages` (read from FEATURES).  If you try
to write 5 stages to a `TRIG_STAGES=4` core you get a `ValueError`
at the API boundary, not a silent garbage write.

### Configuring the sequencer from the CLI

```bash
fcapz capture \
    --trigger-sequence '[{"cmp_a":0,"value_a":"0x40000000","next_state":1,"is_final":false},{"cmp_a":3,"value_a":"0x80","mask_a":"0xFF","is_final":true}]' \
    --pretrigger 8 --posttrigger 16 \
    ...
```

You can also pass a JSON file path instead of inline JSON:

```bash
fcapz capture --trigger-sequence my_sequence.json ...
```

See [chapter 10](10_cli_reference.md) for the full JSON schema.

## Storage qualification (`STOR_QUAL=1`)

Sometimes you don't care about every sample — you only want to
record the ones where some condition is true.  Storage qualification
is a **secondary comparator** that gates whether each sample is
written into the buffer:

- Comparator hits → store this sample
- Comparator misses → skip this sample (buffer write disabled)

The trigger logic still runs every cycle (so you can still trigger
on the gated condition), but only "interesting" samples make it
into the buffer.  This effectively multiplies the buffer depth by
however sparse your interesting events are.

Configuration:

```python
cfg = CaptureConfig(
    ...
    stor_qual_mode  = 1,            # 1 = store when match
    stor_qual_value = 0x42,
    stor_qual_mask  = 0xFF,
)
```

Modes:

| `stor_qual_mode` | Behavior |
|---|---|
| 0 | Disabled — store every sample (default) |
| 1 | Store when `(probe & mask) == (value & mask)` |
| 2 | Store when `(probe & mask) != (value & mask)` |

Cost: +21 LUTs in the RTL when `STOR_QUAL=1` is built in.  Free
when `STOR_QUAL=0`.

## Sample decimation (`DECIM_EN=1`)

Decimation captures every (N+1)-th sample instead of every sample,
extending the time window without growing the buffer.  Useful for
slow signals.

```python
cfg = CaptureConfig(
    ...
    decimation = 9,           # store every 10th sample
)
```

`decimation = 0` is the legacy "every cycle" behavior.  `decimation = 9`
means "every 10th cycle", so a 1024-sample buffer covers 10240 cycles
of real time.

The trigger logic still runs every cycle (not gated by decimation), so
you can still trigger on a single-cycle event even when storing every
10th sample.

When a trigger fires on a non-store cycle, the trigger sample is still
committed into the capture buffer at `samples[pretrigger]`.  That keeps
the host-visible capture shape stable: pre-trigger samples are the stored
history before the event, index `pretrigger` is the actual trigger-cycle
sample, and the post-trigger window starts after that sample.

The captured timestamps (if `TIMESTAMP_W > 0`) reflect the real cycle
counter, so a downstream tool can reconstruct the gaps between
samples accurately.

## External trigger I/O (`EXT_TRIG_EN=1`)

The ELA exposes `trigger_in` and `trigger_out` ports when built with
`EXT_TRIG_EN=1`.  These let you:

- **`trigger_out`** — pulse high for one cycle when the ELA's
  internal trigger fires.  Wire it to a pin / LED / another ELA's
  `trigger_in`.
- **`trigger_in`** — combine an external signal with the internal
  trigger logic.  Modes: disabled (default), OR, AND.

Use cases:

- **Cross-core triggering**: ELA on chip A's `trigger_out` →
  ELA on chip B's `trigger_in` for synchronised multi-chip capture.
- **Manual trigger**: a button on a pin → `trigger_in` with
  `ext_trigger_mode=1` (OR) → fires the trigger when you press the
  button regardless of the internal condition.
- **Conditional gating**: only allow the internal trigger to fire
  when an enable signal is high → `ext_trigger_mode=2` (AND).

Configuration:

```python
cfg = CaptureConfig(
    ...
    ext_trigger_mode = 1,         # 0=disabled, 1=OR, 2=AND
)
```

The reference Arty A7 design ties `trigger_in` to an EIO-controlled
fabric signal, so you can manually fire the trigger from the host
without rebuilding the bitstream — try it from the GUI or the CLI:

```bash
fcapz capture \
    --pretrigger 8 --posttrigger 16 \
    --trigger-mode value_match \
    --trigger-value 0xFF --trigger-mask 0xFF \
    --ext-trigger-mode or \
    --probes counter:8:0 \
    --out manual_trigger.json
```

(`0xFF` is unlikely to ever match the counter at the moment you arm,
so the OR-with-external-trigger behavior is the only way the trigger
fires.)

## Per-sample timestamps (`TIMESTAMP_W=32` or `48`)

When built with `TIMESTAMP_W > 0`, the ELA captures a free-running
cycle counter alongside every sample.  The host stack reads them
back and exposes them as `result.timestamps: list[int]`.  They are
exported into VCD with the right `$timescale` so GTKWave / Surfer
show them as real time.

Use cases:

- **Cycle-accurate timing**: see exactly how many cycles between
  two events even when decimation is enabled.
- **Cross-correlation**: capture multiple ELAs on the same chip
  with their timestamp counters running off the same clock, then
  align the captures in post-processing.
- **Performance analysis**: measure inter-event distances on a
  bursty AXI bus, etc.

Cost: one extra BRAM the same depth as the sample BRAM.  Bigger
counters (`TIMESTAMP_W=48`) are only useful if you need more than
~43 seconds of run-time without wrapping (at 100 MHz).

Timestamp readback is width-aware.  A 48-bit timestamp is returned as
two 32-bit words, with the upper word zero-extended in bits `[31:16]`.
The same zero-extension rule applies to wide sample readback when the
last 32-bit chunk is only partially used.

**Timestamp readback uses the USER2 burst path**, not the slow per-word
USER1 register reads.  Writing `BURST_PTR` (0x002C) with `bit[31]=1`
switches the `jtag_burst_read` staging mux from the sample BRAM to the
timestamp BRAM; subsequent 256-bit USER2 DR scans return
`256 / TIMESTAMP_W` packed timestamps per scan.  The host calls
`transport.read_timestamp_block()` which handles the BRAM-select bit
and the no-priming-scan protocol automatically.  If the transport does
not implement that method the host falls back to the USER1 path, which
is correct but significantly slower.

## Segmented memory (`NUM_SEGMENTS > 1`)

Segmented memory splits the buffer into N equal-sized segments and
**auto-rearms** after each segment fills.  One arm captures N
trigger events back-to-back, each with its own pre/post-trigger
window.

Reference Arty A7 design uses `NUM_SEGMENTS=4`, so a single capture
run records 4 trigger events into 4 × 256-sample segments.

```python
# Configure with NUM_SEGMENTS=4 in the bitstream
cfg = CaptureConfig(
    pretrigger  = 2,
    posttrigger = 3,             # 2 + 1 + 3 = 6 samples per segment, fits in 256
    trigger     = TriggerConfig(mode="value_match", value=0, mask=0xFF),
)
analyzer.configure(cfg)
analyzer.arm()

# Wait for all 4 segments to fill
analyzer.wait_all_segments_done(timeout=10.0)

# Read each segment independently
for seg in range(4):
    result = analyzer.capture_segment(seg)
    print(f"Segment {seg}: {result.samples}")
```

The host stack uses the `SEG_SEL` register to select which segment
to read back; `seg_start_ptr[seg_sel]` is the buffer offset for that
segment.

Constraints:

- `NUM_SEGMENTS` must be a power of 2 dividing `DEPTH` evenly.
- `pretrigger + posttrigger + 1` must fit in `DEPTH / NUM_SEGMENTS`
  (the segment size).  The host's `Analyzer.configure()` validates
  this and raises `ValueError: pre+post+1 exceeds segment depth` if
  you try to overflow a segment.

## Runtime probe mux (`PROBE_MUX_W > 0`)

The runtime probe mux lets one ELA observe a wide bus and runtime-
select which `SAMPLE_W` slice to actually capture, **without
resynthesising the bitstream**.  Useful when you want to debug
several different signals at different times but don't have BRAM to
spare for one ELA per signal.

Build-time: set `PROBE_MUX_W` to the total bus width.

```verilog
wire [127:0] all_my_signals;   // 16 different 8-bit slices

fcapz_ela_xilinx7 #(
    .SAMPLE_W    (8),
    .DEPTH       (1024),
    .PROBE_MUX_W (128)
) u_ela (
    .sample_clk (clk),
    .sample_rst (rst),
    .probe_in   (all_my_signals),    // wide bus, 128 bits
    .trigger_in (1'b0),
    .trigger_out()
);
```

Runtime: set `probe_sel` in `CaptureConfig` to pick which 8-bit
slice to capture.  `0` means bits `[7:0]`, `1` means bits `[15:8]`,
... `15` means bits `[127:120]`.

```python
cfg = CaptureConfig(
    ...
    probe_sel = 5,    # capture bits [47:40] of the wide bus
)
```

## Startup arm and trigger holdoff

Two closely related knobs control **when the core is allowed to start
listening** for a trigger:

- `startup_arm`: if enabled, RESET leaves the core armed instead of idle.
  The RTL parameter `STARTUP_ARM=1` makes that behavior the power-up
  default, so a bitstream can come up ready to capture immediately after
  configuration.
- `trigger_holdoff`: ignore trigger hits for N sample-clock cycles after
  `ARM` and after each segmented auto-rearm.

`trigger_holdoff` is useful when the interesting trigger condition is
real, but the first few cycles after arming are noisy or guaranteed to
contain a false positive.

```python
cfg = CaptureConfig(
    ...,
    startup_arm=True,
    trigger_holdoff=8,
)
```

What happens at runtime:

1. The core arms (explicit `ARM`, segmented auto-rearm, or RESET with
   `startup_arm` enabled).
2. Samples still flow into the circular buffer normally.
3. Trigger comparators and sequencer transitions are ignored for
   `trigger_holdoff` cycles.
4. After that window expires, normal trigger evaluation resumes.

This is intentionally different from `trigger_delay`: holdoff suppresses
*early trigger acceptance*, while delay accepts the trigger and moves the
*committed trigger sample* later.

Hardware validation status on the checked-in Arty A7 reference design:

- Configuration/GSR startup is validated by programming the Arty bitstream
  built with `STARTUP_ARM=1`, then reading `STATUS` before issuing any host
  reset/config write.  The reference bitstream uses `DEFAULT_TRIG_EXT=2`
  so the core remains `armed=1` while waiting for the EIO-driven external
  trigger input.
- `startup_arm` is validated deterministically by checking the ELA
  status register after `RESET`: with `startup_arm=True`, the core
  comes back `armed=1`; with `startup_arm=False`, it stays idle.
- `trigger_holdoff` is validated deterministically with an on-chip
  trigger-test hook that generates a known external-trigger stimulus
  a fixed number of sample clocks after the ELA enters `ARMED`.
  The hardware tests confirm that a pulse 2 cycles after arm is
  blocked by `trigger_holdoff=4`, while a stimulus beginning 8 cycles
  after arm is accepted normally.

## Configurable trigger delay

Sometimes the cause of a problem and the moment you want to look at
are **not the same cycle**.  Example: a state machine asserts an
error pulse, but the bug is upstream — you want to see the bus
inputs that caused it, which were a few cycles earlier.

The `trigger_delay` field shifts the **committed trigger sample** N
sample-clock cycles after the trigger event.  The pre-trigger window
counts back from the new trigger position, so you effectively see
"N cycles after the cause" with the same pre/post window structure.

```python
cfg = CaptureConfig(
    ...
    trigger_delay = 4,    # commit trig_ptr 4 cycles after trigger_hit
)
```

What happens at runtime:

1. The comparator fires (`trigger_hit` goes high).
2. Instead of latching `trig_ptr <- wr_ptr` immediately, the FSM
   enters a **delay countdown**: `trig_delay_count <- trigger_delay - 1`.
3. The buffer keeps recording for `trigger_delay` more sample
   clocks (the trigger logic does NOT re-evaluate during the
   countdown).
4. When the countdown reaches zero, `trig_ptr <- wr_ptr` is
   committed and the post-trigger countdown begins normally.

Verified end-to-end on Arty A7 silicon: trigger on counter == 0x10
with `trigger_delay=4` → captured trigger sample = 0x14 (= cause + 4
counter ticks, since the reference design's probe is a free-running
counter).

`trigger_delay = 0` (the default) reproduces the legacy zero-delay
behavior exactly.  Range is `0..65535`.

## Channel mux (`NUM_CHANNELS > 1`)

The channel mux is the **build-time** sibling of the runtime probe
mux.  It lets one ELA core observe N separate `SAMPLE_W`-bit buses,
switching between them at arm time (not on the fly).

```verilog
fcapz_ela_xilinx7 #(
    .SAMPLE_W     (8),
    .DEPTH        (1024),
    .NUM_CHANNELS (4)
) u_ela (
    .sample_clk (clk),
    .sample_rst (rst),
    .probe_in   ({chan_d, chan_c, chan_b, chan_a}),  // 4 × 8 = 32 bits
    .trigger_in (1'b0),
    .trigger_out()
);
```

Runtime: set `channel` in `CaptureConfig` to pick which 8-bit
channel to capture.

```python
cfg = CaptureConfig(
    ...
    channel = 2,    # capture chan_c
)
```

Difference vs `PROBE_MUX_W`:

| | `NUM_CHANNELS` | `PROBE_MUX_W` |
|---|---|---|
| Bus interpretation | N concatenated buses, one per channel | One wide bus, slice arbitrary positions |
| Channel switching | At arm time (latched on arm) | At arm time (also latched on arm) |
| Use case | Several distinct signals | One wide structured bus you want to observe pieces of |
| Cost | Mux N → 1 of `SAMPLE_W` bits | Same |

You can use both at once if you really want to (one ELA observing N
channels of M signals each), but in practice pick the one that fits
your bus naturally.

## Reading the FEATURES register

When you call `Analyzer.probe()`, the host queries the `FEATURES`
register at `0x003C` to find out which features are compiled into
the bitstream:

```python
info = analyzer.probe()
# {
#   "version_major": 0,
#   "version_minor": 3,
#   "core_id": 0x4C41,
#   "sample_width": 8,
#   "depth": 1024,
#   "num_channels": 1,
#   "has_decimation": True,
#   "has_ext_trigger": True,
#   "has_timestamp": True,
#   "timestamp_width": 32,
#   "num_segments": 4,
#   "probe_mux_w": 0,
# }
```

The bitfield layout in `FEATURES` is documented in
[`specs/register_map.md`](specs/register_map.md), but you should
prefer reading them via `Analyzer.probe()` which returns the
decoded form.

## Resource usage

Vivado **synthesis**, **xc7a100t**, 2025.2 — **Slice LUTs** (same
measurement as `scripts/resource_comparison.tcl`). BRAM is Block RAM
tiles (18K granularity counts as 0.5 where applicable).

| Configuration | Slice LUTs | FFs | BRAM | Notes |
|---|---:|---:|---:|---|
| `SAMPLE_W=8`, `DEPTH=1024`, baseline | 1,595 | 1,478 | 0.5 | `TRIG_STAGES=1`, `STOR_QUAL=0` |
| Above + `STOR_QUAL=1` | 1,616 | 1,497 | 0.5 | +21 LUT |
| Above + `TRIG_STAGES=4` (no SQ) | 2,098 | 1,878 | 0.5 | 4-stage sequencer |
| Above + `TRIG_STAGES=4` + `STOR_QUAL=1` | 2,095 | 1,897 | 0.5 | seq + storage qualification |
| `SAMPLE_W=8`, `DEPTH=4096`, baseline | 1,541 | 1,490 | 1.0 | deeper buffer |
| `SAMPLE_W=32`, `DEPTH=1024`, baseline | 1,548 | 1,740 | 1.0 | wider samples |

The [Arty reference design](../examples/arty_a7/arty_a7_top.v) enables
`DECIM_EN`, `EXT_TRIG_EN`, `TIMESTAMP_W=32`, and `NUM_SEGMENTS=4` together
with EIO and EJTAG-AXI — **post-place** that top-level uses about **2.7k
slice LUTs** and **1.5 BRAM tiles** (see [README.md](../README.md#resource-usage)).
Your tool and family will vary.

## What's next

- [Chapter 06 — EIO core](06_eio_core.md): the simpler sibling.
- [Chapter 09 — Python API](09_python_api.md): full `Analyzer` API
  reference with worked examples for every feature in this chapter.
- [Chapter 10 — CLI reference](10_cli_reference.md): every flag,
  every option.
- [`specs/register_map.md`](specs/register_map.md): the canonical
  register map if you ever need to hand-craft a non-host driver.
