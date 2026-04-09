# 01 — Overview

> **Audience**: junior FPGA developer who has never used fpgacapZero
> before.  Takes about 10 minutes to read.

## What fpgacapZero is

fpgacapZero is an **open-source, vendor-agnostic FPGA debug suite** —
a small set of RTL cores you drop into your own design plus a Python
host stack that talks to them over JTAG.  Apache-2.0 licensed, no
strings attached.

It is the open alternative to commercial in-chip debug tools like
Xilinx ChipScope (now Vivado ILA/VIO), Intel SignalTap, and Lattice
Reveal.  Those tools work well, but they lock you to one vendor, one
toolchain, and one workflow.  fpgacapZero gives you the same
capability — observe and drive signals on a running FPGA from a host
PC over JTAG — without the lock-in.

## The four cores

Every fpgacapZero design uses one or more of these four cores.  They
all live under [`../rtl/`](../rtl/), and they all speak to the host
PC through the FPGA's JTAG TAP via the BSCANE2 (or vendor-equivalent)
primitive.

### 1. ELA — Embedded Logic Analyzer

> **What it replaces**: Vivado ILA, SignalTap, Reveal.

The ELA core is a **circular sample buffer** with a configurable
trigger.  You connect it to a bus of fabric signals; it captures
samples on every sample-clock edge into a dual-port BRAM; when the
trigger fires it captures `posttrigger` more samples and stops; the
host then reads the buffer back over JTAG.

Headline features (every one is parameter-gated, so the smallest
configuration uses zero overhead for unused features):

- Sample width 1–256 bits per channel.
- Buffer depth 16 samples to 16 M samples (limited by available BRAM).
- **2 comparators per trigger stage** with 9 compare modes (`==`,
  `!=`, `<`, `>`, `<=`, `>=`, rising, falling, changed) and AND/OR
  combine.
- Optional **multi-stage trigger sequencer** (2-4 states with
  occurrence counters and inter-state transitions).
- Optional **storage qualification** — only store samples that match
  a secondary condition; effectively multiplies buffer depth on sparse
  signals.
- **Sample decimation** — capture every N+1 cycles instead of every
  cycle, extending the time window without growing the buffer.
- **Per-sample timestamp counter** (32 or 48 bit) — exported into VCD
  for cycle-accurate timing even with decimation enabled.
- **Segmented memory** — auto-rearm after each segment fills, so a
  single capture run can record 4, 8, or 16 separate trigger events.
- **Runtime probe mux** — observe a wide bus and runtime-select which
  `SAMPLE_W` slice gets captured, without resynthesising.
- **External trigger I/O** — `trigger_in` / `trigger_out` ports with
  OR/AND combine modes for cross-core or cross-chip synchronisation.
- **Configurable trigger delay** (new in v0.3.0) — shifts the
  committed trigger sample N sample-clock cycles after the trigger
  event to compensate for upstream pipeline latency between the
  cause signal and its visible effect on the probe bus.

The ELA's full feature deep-dive is in [chapter 05](05_ela_core.md).

### 2. EIO — Embedded I/O

> **What it replaces**: Vivado VIO, SignalTap's "in-system source &
> probe", Reveal's `IO_PROBE`.

The EIO core gives the host **runtime read/write access to fabric
signals**.  You define an input bus (fabric → host) and an output
bus (host → fabric); the host can poll the inputs and drive the
outputs over JTAG, without resynthesising the bitstream.

It is the simplest of the four cores — just a register file with
clock-domain-crossing synchronisers — but it is enormously useful for
runtime configuration, manual reset/enable bits, on-the-fly tuning,
and quick "is this signal stuck high?" checks.  See
[chapter 06](06_eio_core.md).

### 3. EJTAG-AXI — JTAG-to-AXI4 Master Bridge

> **What it replaces**: Vivado JTAG-to-AXI Master, ChipScope AXI bus
> master, Intel "system console" master.

This bridge gives the host PC **memory-mapped AXI4 master access** to
your design, over JTAG.  Single read/write transactions, sequential
auto-increment blocks, and full AXI4 burst transfers (read and write,
up to 256 beats).  You can poke registers in your CSRs, dump and
load DDR memory, read back BRAM contents, drive AXI peripherals
without booting a CPU — anywhere you would normally use Vivado's
JTAG-to-AXI Master, this works the same way and ships with full
source.

A single 72-bit pipelined DR scan is one AXI transaction; the host
side caches the bridge's `FIFO_DEPTH` from the FEATURES register and
rejects oversized bursts at the API boundary so a buggy host can
never overflow the on-chip read FIFO.  Hardware-validated on Arty
A7-100T at ~5-8 KB/s with the batched-scan transport.  Full chapter:
[chapter 07](07_ejtag_axi_bridge.md).

### 4. EJTAG-UART — JTAG-to-UART Bridge

> **What it replaces**: Xilinx STDIO over JTAG (XSDB `mrd`/`mwr` games),
> Intel system console serial pipe.

This bridge gives the host PC a **bidirectional UART** to your design
over JTAG, with TX and RX async FIFOs.  You can use it as a debug
console, a printf-over-JTAG sink, a firmware uploader, or a generic
byte stream — without burning a physical UART pin or wiring up a USB
serial adapter.

Use cases that just work:

- A small softcore (PicoRV32, Ibex, NEORV32, etc.) prints to the
  bridge instead of a physical UART pin; the host streams it with
  `fcapz uart-recv`.
- The host uploads a small firmware image into BRAM via the bridge,
  then resets the CPU and watches the debug output stream back.
- Two FPGAs talk over JTAG via two `fcapz-uart` instances on the
  host, no UART wires.

Full chapter: [chapter 08](08_ejtag_uart_bridge.md).  Note: there is
one known limitation with internal loopback at 115200 baud — see
chapter 17 for details.

## How the cores fit together

Each core uses a **separate JTAG USER chain** (USER1 through USER4
on Xilinx 7-series / UltraScale, equivalent on other vendors), so
multiple cores can coexist in the same bitstream and the host stack
can talk to all of them in one xsdb / OpenOCD session.

| Core | Default chain | Default IR (7-series) | Default IR (UltraScale) |
|------|---------------|-----------------------|-------------------------|
| ELA control | USER1 | `0x02` | `0x24` |
| ELA burst data | USER2 | `0x03` | `0x25` |
| EIO | USER3 | `0x22` | `0x26` |
| EJTAG-AXI / EJTAG-UART | USER4 | `0x23` | `0x27` |

The IR codes differ between 7-series and UltraScale, but you don't
have to memorise either set: the Python transport ships named
`IR_TABLE_XILINX7` and `IR_TABLE_XILINX_ULTRASCALE` (alias
`IR_TABLE_US`) presets — see [chapter 14](14_transports.md).

ELA and EIO are completely independent.  The two bridges (AXI and
UART) can share USER4 by being instantiated at the same time only if
you arbitrate them externally; in practice you pick one bridge per
bitstream.  The reference Arty A7 design includes ELA + EIO + AXI
together, and a separate "uart loopback" bitstream includes ELA +
EIO + UART.

## The host stack

Everything talks to a Python package called `fcapz`.  After
`pip install fpgacapzero` you get:

- **`fcapz` console command** — the CLI for one-shot operations:
  probe, capture, configure, AXI read/write/dump, UART send/recv,
  EIO read/write.  Documented in [chapter 10](10_cli_reference.md).
- **`fcapz` Python package** — programmatic API.  `Analyzer`,
  `EioController`, `EjtagAxiController`, `EjtagUartController`,
  plus transports and a small `events` module for LLM-friendly
  capture summaries.  Documented in [chapter 09](09_python_api.md).
- **JSON-RPC server** (`python -m fcapz.rpc`) — line-delimited
  JSON over stdin/stdout for integration with other languages or
  long-running test harnesses.  Documented in
  [chapter 11](11_rpc_server.md).
- **`fcapz-gui` desktop app** (optional, install with
  `pip install fpgacapzero[gui]`) — PySide6 control panel that wraps
  every controller with a graphical front-end, including an embedded
  `pyqtgraph` waveform preview and one-click "open in GTKWave /
  Surfer / WaveTrace" for the captured `.vcd`.  Documented in
  [chapter 12](12_gui.md).

The host stack is the **only** way to talk to the cores — there is no
"design your own register access" path.  This is by design: every
controller validates input, decodes the new core_id magic
automatically, applies the readiness wait after programming the FPGA,
and surfaces protocol errors with actionable messages.  Bypassing it
loses all of that.

## Two JTAG transports

The host stack supports two JTAG transports out of the box:

- **Xilinx hw_server / XSDB** — the default for Xilinx boards.
  Driven by Vivado's `hw_server` (running on `localhost:3121` by
  default).  Programs the FPGA, talks to BSCANE2, hardware-validated
  on Arty A7-100T, no extra software to install if you already have
  Vivado.
- **OpenOCD** — cross-platform, works with any FTDI-based JTAG cable
  on any board.  Slower than hw_server but vendor-neutral.  Talks to
  OpenOCD's TCL listener (default `localhost:6666`) and uses raw
  `irscan` / `drscan` commands.

Both transports implement the same `Transport` abstract base class,
so the rest of the host stack does not care which one you use.  To
add a third (e.g. raw TCF for ~10× the throughput, or USB-Blaster
direct), implement the ABC and you are done — no other code changes
needed.  See [chapter 14](14_transports.md) and
[`specs/transport_api.md`](specs/transport_api.md).

## Vendor support matrix

| Vendor | TAP primitive | RTL wrapper | Hardware-validated |
|--------|--------------|-------------|---------------------|
| Xilinx 7-series (Artix-7, Kintex-7, Virtex-7, Spartan-7, Zynq-7000) | `BSCANE2` (unisim) | [`fcapz_*_xilinx7.v`](../rtl/) | ✅ Arty A7-100T |
| Xilinx UltraScale / UltraScale+ | `BSCANE2` (unisim) | [`fcapz_*_xilinxus.v`](../rtl/) (thin shims over `_xilinx7`) | ❌ Implemented, lint-clean, not yet hardware-validated |
| Lattice ECP5 | `JTAGG` | [`fcapz_*_ecp5.v`](../rtl/) | ❌ |
| Intel / Altera | `sld_virtual_jtag` | [`fcapz_*_intel.v`](../rtl/) | ❌ |
| Gowin GW1N / GW2A | Gowin `JTAG` primitive | [`fcapz_*_gowin.v`](../rtl/) | ❌ |
| Xilinx Versal (XCVM/VC/VP/VE/VH) | Different TAP primitive (CIPS / `BSCANE2_INST`) | **Not supported** | — |

The wrappers are all single-instantiation: pick the one for your
vendor, set parameters, connect your probes, and you are done.  See
[chapter 04](04_rtl_integration.md) for the full instantiation
walkthrough.

## What's next

- If you want to **see it work end-to-end** before learning anything
  else, jump to [chapter 03 — first capture in 10 minutes](03_first_capture.md).
- If you want to **install the host stack first**, read
  [chapter 02 — installation](02_install.md).
- If you want to **integrate it into your own design now**, read
  [chapter 04 — RTL integration](04_rtl_integration.md).
- If you want the **deep dive** on each core, chapters 05-08.

The recommended first read for a new user is `01 → 02 → 03 → 04`,
then dip into 05-08 for whichever cores you actually plan to use.
