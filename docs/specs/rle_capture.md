# Run-length encoded capture (`RLE_W`)

Status: built in both HDLs and the host stack. User guide:
[Run-length capture](../05_ela_core.md#run-length-capture).

## Goal

A fixed-depth buffer covers more time when the probe repeats. Each buffer
entry stores a sample and how many sample clocks it held. `RLE_W=0` (the
default) builds none of it, and the core behaves and costs exactly as today.

## Build parameter and discovery

- `RLE_W` (0 or 1..16, default 0): width of the run-count field. Values above
  16 fail elaboration in both HDLs. On a core with timestamps the counts
  share the timestamp lane, so `RLE_W` must not exceed `TIMESTAMP_W`; a
  larger value fails elaboration too.
- New RO register `RLE_W` at `0x00CC` reads the parameter. It reads 0 on cores
  without RLE (unknown addresses read 0), so it is also the capability bit.
  (`0x00E8` and `0x00EC` are not used: the AXI monitor answers there.)
- New RW register `RLE_POST_CLKS` at `0x0090` (see Post-trigger clock
  limit).
- New RW register `RLE_CTRL` at `0x00A8`:
  - bit 0 = enable. Resets to 0, so an RLE core boots and captures exactly
    like a non-RLE one until the host turns it on. Taken on arm, like the
    other capture settings.
  - bit 1 = the USER1 timestamp window returns run counts instead of
    timestamps (see Readout). Cleared by arm and by soft reset.

## Storage

- A parallel count RAM, `DEPTH x RLE_W`, beside the sample RAM. It works like
  the timestamp RAM: same port-A address, written in sample_clk, read through
  port B.
- The sample RAM is untouched. Total BRAM grows by `RLE_W / SAMPLE_W`.
- An entry stores `count = run length - 1`, so a single sample is 0 and the
  longest run is `2^RLE_W` clocks.
- The count write is registered, one per clock, so with `INPUT_PIPE >= 1` a
  new entry and the next clock's extend of it never collide.

## Write rule (RLE enabled)

One register holds the open entry's value and count, and another its address.
On every sample clock that the core would store today (`store_enable`):

- **Extend**: if the sample equals the open entry's value, the count is not
  saturated, and nothing forces a new entry, the count goes up by one and is
  written at the open entry's address. The write pointer does not move, and
  the pre/post counters do not count it.
- **New entry**: otherwise the core stores the sample as today (pointer moves,
  pre/post counters count it), writes count 0 at its address, and makes it the
  open entry.

Things that force a new entry:
- the trigger commit (the trigger sample always starts an entry, so its time
  is exact; the commit already force-stores it);
- a saturated count;
- the first store after any arm or soft reset, and the first store of each
  segment;
- a selection flush.

The compare is the full `SAMPLE_W` sample, after the input pipeline, on the
same `probe_prev` the RAM stores.

## Semantics

- `PRETRIG_LEN` and `POSTTRIG_LEN` count **entries**, not clocks. This falls
  out of the existing counters, which already count stores. So a capture of
  `pre + post + 1` entries covers between `pre + post + 1` clocks and
  `(pre + post + 1) * 2^RLE_W` clocks.
- The pre-trigger ring wraps whole entries: the oldest entry is overwritten
  together with its count.
- The last post-trigger entry ends the capture on the clock it opens, so its
  count is 0 (a clock limit can end it later; see below). The capture covers
  exactly `sum(count + 1)` clocks, so no extra end-time register is needed.
  Waveforms end there.
- An entry still open when the capture ends is never left half-written,
  because the count is written on every extend.

## Post-trigger clock limit

An entry-based window can wait forever on an idle bus. `RLE_POST_CLKS`
(`0x0090`, RW) also ends it after N clocks, whichever comes first:

- The trigger commit is clock 0. The window covers clocks 0..N, so
  `sum(count + 1)` over the post-trigger entries is N + 1 when the limit
  wins. 0 (the reset value) means no limit.
- Width `min(32, LEN_W + RLE_W)`: the most clocks a window of entries can
  span. The register reads back the bits kept. CDC and arm latch as for
  `TRIG_DELAY`. Active only while RLE is on (`rle_active`), so a non-RLE
  capture ignores it.
- A down-counter loaded at the commit and a registered "last clock" flag,
  so the stop starts at a flop. The stop clock uses the one completion path
  the entry limit uses; it stores that clock as usual, either as a new entry
  or as an extend of the open one. So the last entry can have count > 0.
- `CAPTURE_LEN` reports the entries stored:
  `pre + post + 1 - post_left`, plus one if the stop clock opens an entry.
  Segmented builds keep each segment's length (`seg_len`, cleared on arm and
  snapshotted to the JTAG side like the segment start pointers). For a
  capture with a clock limit, `CAPTURE_LEN` and the DATA window bound follow
  `SEG_SEL`; the host already reads `CAPTURE_LEN` per segment. Without a
  limit the snapshot copies the capture length into every segment, so they
  read exactly as on a core without `seg_len`, mid-capture too.
- Cost: about 5 x the register width in flip-flops, plus
  3 x `NUM_SEGMENTS` x `LEN_W` with segments.
- Host: `CaptureConfig.post_clocks` (0 = off), CLI `--post-clocks`, RPC
  `post_clocks`, a GUI spinner and a web field. `configure()` refuses it
  without `rle` and clamps it to the register width.

## Interactions (v1)

- **Decimation, storage qualification:** RLE is rejected when either is on.
  The host refuses the config, and the RTL treats RLE as off when
  `DECIM != 0` or `SQ_MODE` selects a mode, so a raw register write cannot
  produce counts that mean something else.
- **Timestamps:** both can be built. With RLE on, the timestamp is the clock
  of the entry's first sample. The host checks counts against timestamps in
  tests.
- **Segments:** each segment starts with a new entry. Per-segment windows
  count entries.
- **Sequencer, trigger delay, holdoff:** unchanged. They run every clock.
  Trigger delay is in clocks; the delayed commit still forces a new entry.
- **Pre-arm rolling history:** RLE also runs while idle, so history is
  entries. Arming with a different enable voids the history
  (`arm_voids_history`), like a channel change.

## Readout

Counts travel on the timestamp lane, so no new burst format exists.

- The lane is `TIMESTAMP_W` bits wide, or `RLE_W` bits on a core without
  timestamps. Every core that exists today keeps its lane width.
- **Burst (USER2):** `BURST_PTR[31:30] = 2'b11` reads counts. Bit 31 alone
  still reads timestamps. It is per burst and holds no state.
- **USER1 DATA window:** the timestamp window returns counts while
  `RLE_CTRL[1]` is set, with every timestamp-window rule (base, the
  `0x10000` alias on older cores, paging). The host restores the bit after
  the read; arm and soft reset clear it.
- The host reads counts through the same code as timestamps.
- Wrappers: the standalone ELA wrappers that hold the burst reader (Xilinx
  7-series, Intel, ECP5, PolarFire) take `RLE_W` and size the lane. The core
  manager, `debug_multi` and the AXI monitor keep `RLE_W = 0` in v1.
- Both HDLs.

## Host

- `CaptureConfig.rle: bool = False`. `configure()` writes `RLE_CTRL` on cores
  with `RLE_W != 0`, and raises if `rle=True` on a core without it or with
  decimation or storage qualification set.
- `CaptureResult` keeps `samples` as the stored entries and gains
  `run_lengths` (clocks per entry, empty when RLE is off). The trigger
  index stays an entry index. A helper expands entries to one sample per
  clock, with a size limit.
- VCD and the other exporters place each entry at its start clock, from the
  run lengths.
- GUI and web: a checkbox on RLE cores; previews and the trigger marker use
  clock time, not entry index. A post-trigger clock limit field while it is
  checked.
- RPC and CLI: `rle` flag and the run lengths in the capture reply.
- Old bitstreams: `RLE_W` reads 0, `rle` defaults to False, and nothing
  changes.

## Verification

- cocotb in both HDLs, with `INPUT_PIPE` 0 and 1: a value that changes every
  clock then holds, runs of 1, long runs, saturation at `2^RLE_W`,
  trigger in the middle of a run, ring wrap during pre-trigger, segments,
  pre-arm history across arm, RLE rejected with decimation / qualification,
  `RLE_W=0` unchanged. The clock limit: stops inside a run, on a new entry,
  on the same clock as the entry limit, after it, with a trigger delay, with
  RLE off (ignored), and per segment with unequal lengths.
- Host unit tests for expansion, exports, and the config checks.
- Verilator lint, static parity, hardware run on a board build with
  `RLE_W=16`: the DE25-Nano reference design (both variants) runs
  `TestRunLengthCapture` on a second ELA channel that holds each value for
  8 clocks, including the clock limit read back from all four segments.
- A value-match trigger on a held value can fire after the run's first
  clock (on the first clock the pre-trigger window is full). The trigger
  still opens a new entry, so that run shows up as two entries. The
  hardware tests trigger on a value change to keep the runs whole.
