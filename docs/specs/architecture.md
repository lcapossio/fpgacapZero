# Architecture — v0.3.0

## Goal
Vendor-agnostic JTAG logic analyzer core with configurable features,
designed to fit on any FPGA with minimal resource usage.

## Core Blocks
- **Probe Input**: User-defined probe buses flattened into `SAMPLE_W` bits (1-256+).
- **Trigger Block** (`trig_compare.v` × 2 per stage): Dual comparators (A and B)
  with 9 compare modes (==, !=, <, >, <=, >=, rising, falling, changed) and
  boolean combine (A-only, B-only, AND, OR). Optional multi-stage sequencer
  (2-4 states) with occurrence counter and state transitions.
  Controlled by `TRIG_STAGES` parameter (1 = simple, 2-4 = sequencer).
- **Storage Qualification**: Optional condition that filters which samples
  are stored, effectively multiplying buffer depth. `STOR_QUAL` parameter
  (0 = off, 1 = on, +21 LUTs).
- **Sample Buffer**: Dual-port BRAM (`dpram.v`) for pre-trigger history plus
  post-trigger capture. Port A on sample_clk, port B on jtag_clk.
- **Capture Controller**: Arm, trigger detect, post-trigger countdown, done.
- **JTAG Register Map** (`jtag_reg_iface.v`): 49-bit DR on USER1 for
  control/status + per-word data readback.
- **Burst Readback** (`jtag_burst_read.v`): 256-bit DR on USER2 for fast
  block reads (32 8-bit samples per scan).
- **Embedded I/O** (`fcapz_eio.v`): JTAG-accessible input/output probe registers
  on USER3 (CHAIN=3). `IN_W`-bit input bus synchronised to jtag_clk;
  `OUT_W`-bit output register driven to fabric.  Parameters: `IN_W`, `OUT_W`.
- **TAP Wrappers** (`jtag_tap/`): Vendor-specific JTAG primitives for
  Xilinx, Lattice, Intel, and Gowin.

## Parameters
| Parameter | Default | Description |
|-----------|--------:|-------------|
| `SAMPLE_W` | 32 | Probe width in bits (1-256+) |
| `DEPTH` | 1024 | Sample buffer depth |
| `TRIG_STAGES` | 1 | Trigger sequencer stages (1 = simple, 2-4 = sequencer) |
| `STOR_QUAL` | 0 | Storage qualification (0 = off, 1 = on) |

When `TRIG_STAGES=1` and `STOR_QUAL=0`, the sequencer and qualification
logic optimize away completely.

EIO core parameters (separate module, `fcapz_eio.v`):

| Parameter | Default | Description |
|-----------|--------:|-------------|
| `IN_W` | 32 | Input probe width (fabric → host) |
| `OUT_W` | 32 | Output probe width (host → fabric) |

## Resource Usage (xc7a100t)
| Config | LUTs | BRAM |
|--------|-----:|-----:|
| 8b × 1024, baseline (dual comparators) | 1,990 | 0.5 |
| 8b × 1024, full (4-stage seq + SQ) | ~2,500 | 0.5 |
| 32b × 1024, baseline | ~2,000 | 1.0 |

## Clocking
- `sample_clk` is the capture clock.
- JTAG clock (TCK) is independent; control registers cross via 2FF CDC.
- Sample buffer uses true dual-port RAM (port A = sample_clk, port B = TCK).
- EIO probe_in uses a 2-FF synchroniser into jtag_clk. probe_out is in jtag_clk domain.

## Data Model
- Samples stored as packed `SAMPLE_W` vectors in BRAM.
- Wide samples (> 32 bits) read as multiple 32-bit chunks via USER1,
  or natively via the 256-bit USER2 burst DR.
- Timestamps are implicit by sample index.

## JTAG-to-AXI4 Bridge (`fcapz_ejtagaxi.v`)

The bridge provides AXI4 master access from the JTAG port using a 72-bit
pipelined DR on USER4 (CHAIN=4). The pipeline is: **72-bit DR → shadow
registers → CDC → AXI4 master FSM → AXI bus**.

**Data path:** On DR update, the parsed command and address/data are latched
into shadow registers in the TCK domain. A toggle-handshake CDC transfers
the request to the `axi_clk` domain, where a 10-state FSM drives the AXI4
channels. The response is latched back and presented on the next DR capture.

**CDC strategy:** Single-word transactions use a toggle-handshake between
TCK and `axi_clk`. Burst reads use an asynchronous FIFO (Gray-coded
pointers, configurable `FIFO_DEPTH`) so the AXI side can fill data while
the host scans out words one per DR shift. Burst writes use per-beat
toggle handshake: the AXI FSM acks each beat (except the last) so the
host can queue the next.

**Burst timing:** The AXI-side timeout (`TIMEOUT` parameter) applies only
to AXI handshake waits (wready, bvalid, arready, rvalid). It does NOT
apply between burst write beats in `ST_BURST_W`, because inter-beat pacing
is host-controlled via JTAG scans (~0.5 ms per beat) — far longer than
any AXI-side timeout.

**Burst read pipeline:** The FIFO read has a 1-scan pipeline delay: the
first `BURST_RDATA` scan sets `last_cmd` but does not capture FIFO data
(because `last_cmd` was still `BURST_RSTART` at CAPTURE time). The host
sends a priming `BURST_RDATA`, then N data scans for N words.

**Throughput (Arty A7, onboard FT2232H, Xilinx hw_server/XSDB, TCK up to
30 MHz):** ~0.6 KB/s sequential (single `raw_dr_scan` per word, dominated
by 0.64 ms XSDB round-trip), ~5-8 KB/s with `raw_dr_scan_batch`.
Hardware-validated on Arty A7-100T: single read/write, auto-increment
blocks, and AXI4 burst read/write all pass.  Different JTAG adapters or
a raw TCF transport (bypassing XSDB) would significantly change these
numbers.

Parameters: `ADDR_W` (default 32), `DATA_W` (default 32), `FIFO_DEPTH`
(default 16), `TIMEOUT` (default 4096 axi_clk cycles).

**Verified Xilinx 7-series IR codes** (xc7a100t):
USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.

## Testing

| Level | Command | Coverage |
|-------|---------|----------|
| Unit (Python) | `pytest tests/test_host_stack.py` | Transport, Analyzer, EioController |
| Simulation | `python sim/run_sim.py` | ELA: 17 checks; EIO: 18 checks; EJTAG-AXI: TB |
| Hardware | `pytest tests/test_hw_integration.py` | 15 tests, Arty A7-100T |
