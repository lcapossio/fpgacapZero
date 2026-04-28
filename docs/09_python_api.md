# 09 — Python API

> **Goal**: complete reference for the `fcapz` Python package.  By
> the end of this chapter you can drive every fcapz core
> programmatically, integrate it into your own scripts and tests,
> and reuse the same controllers that the CLI, RPC server, and GUI
> are built on top of.
>
> **Audience**: junior FPGA dev who can write basic Python and has
> read [chapter 02](02_install.md) so the package is installed.

## Package layout

```
fcapz/                        ← top-level package (pip install fpgacapzero)
  __init__.py                 Re-exports the public API
  _version.py                 __version__ resolution from VERSION file
  analyzer.py                 Analyzer, CaptureConfig, CaptureResult, ...
  eio.py                      EioController, EIO_CORE_ID
  ejtagaxi.py                 EjtagAxiController, AXIError
  ejtaguart.py                EjtagUartController
  transport.py                Transport ABC, OpenOcdTransport, XilinxHwServerTransport
  events.py                   ProbeDefinition, find_edges, summarize, ...
  cli.py                      `fcapz` CLI entry point (chapter 10)
  rpc.py                      JSON-RPC server (chapter 11)
  gui/                        Optional desktop GUI (chapter 12)
```

Everything you need for programmatic access is at the top level:

```python
from fcapz import (
    # Core controllers
    Analyzer, CaptureConfig, CaptureResult, TriggerConfig,
    ProbeSpec, SequencerStage,
    EioController,
    EjtagAxiController, AXIError,
    EjtagUartController,
    # Transports
    Transport, XilinxHwServerTransport, OpenOcdTransport,
    # Events / summary helpers
    ProbeDefinition, find_edges, find_rising_edges, find_falling_edges,
    find_bursts, frequency_estimate, summarize,
    # Version
    __version__, _version_tuple,
)
```

## The transport layer

Every controller talks to the FPGA through a `Transport` instance.
You construct one transport per session and pass it to as many
controllers as you need (each controller calls `select_chain()` to
move to its USER chain).

### `XilinxHwServerTransport` (default for Xilinx)

```python
from fcapz import XilinxHwServerTransport

transport = XilinxHwServerTransport(
    host="127.0.0.1",
    port=3121,
    fpga_name="xc7a100t",
    bitfile="examples/arty_a7/arty_a7_top.bit",   # optional, programs FPGA on connect()
    ir_table=None,                                 # default = 7-series IR codes
    ready_probe_addr=0x0000,                       # ELA VERSION register
    ready_probe_timeout=2.0,                       # seconds
)
```

Constructor parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `host` | `"127.0.0.1"` | hw_server host |
| `port` | `3121` | hw_server TCP port |
| `fpga_name` | `"xc7a100t"` | JTAG target name (XSDB filter pattern); validated against TCL-safe regex |
| `xsdb_path` | `None` | full path to xsdb if not on PATH |
| `bitfile` | `None` | if set, `connect()` runs `fpga -file <bitfile>` and waits for FPGA readiness; validated against TCL-safe regex |
| `ir_table` | `None` (= `IR_TABLE_XILINX7`) | dict mapping chain index → IR opcode |
| `ready_probe_addr` | `0x0000` | register polled after programming to detect "FPGA is alive"; pass `None` to skip the readiness wait |
| `ready_probe_timeout` | `2.0` | how long to wait for the FPGA to come up before raising `ConnectionError` |

Named IR-table presets (use as `ir_table=XilinxHwServerTransport.IR_TABLE_US`):

| Constant | Maps to |
|---|---|
| `IR_TABLE_XILINX7` | `{1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}` (default) |
| `IR_TABLE_XILINX_ULTRASCALE` | `{1: 0x24, 2: 0x25, 3: 0x26, 4: 0x27}` |
| `IR_TABLE_US` | alias for `IR_TABLE_XILINX_ULTRASCALE` |

See [chapter 14](14_transports.md) for more on the transports and
how to add a new one.

### `OpenOcdTransport`

```python
from fcapz import OpenOcdTransport

transport = OpenOcdTransport(
    host="127.0.0.1",
    port=6666,
    tap="xc7a100t.tap",
    ir_table=None,         # default = 7-series; OpenOcdTransport also has IR_TABLE_US
)
```

OpenOCD doesn't program the FPGA for you in this transport — you
program separately (e.g. `openocd -c "init; pld load 0 my.bit; exit"`)
or via your own startup script.  Once OpenOCD is running and
listening on TCL port 6666, the transport just talks to it.

### Sharing one transport between controllers

```python
t = XilinxHwServerTransport(port=3121, fpga_name="xc7a100t",
                            bitfile="my_design.bit")
t.connect()                  # opens xsdb, programs FPGA, waits for readiness

analyzer = Analyzer(t)
analyzer.connect()           # selects chain 1, no transport open

eio = EioController(t, chain=3)
eio.connect()                # selects chain 3, no second xsdb

bridge = EjtagAxiController(t, chain=4)
bridge.connect()             # selects chain 4, no third xsdb
```

The controllers cooperate on chain selection via `Transport.select_chain()`.
Each controller's methods automatically restore chain 1 (the
default) on exit so the others stay reachable.

The desktop GUI ([chapter 12](12_gui.md)) uses exactly this pattern
under the hood — one shared transport, four cooperating
controllers, no spawning a separate xsdb per panel.

## `Analyzer` — the ELA controller

### Construction and lifecycle

```python
from fcapz import Analyzer, CaptureConfig, TriggerConfig, ProbeSpec

a = Analyzer(transport)
a.connect()                  # selects chain 1, validates ELA core_id
# ... do work ...
a.close()                    # releases the transport
```

### `probe() -> dict`

Reads the ELA identity, version, and FEATURES bits.  Raises
`RuntimeError` if `VERSION[15:0] != 0x4C41` (the "LA" core_id magic
check).

```python
info = a.probe()
# {
#   "version_major": 0,
#   "version_minor": 3,
#   "core_id": 19521,           # 0x4C41 = "LA"
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

### `configure(config: CaptureConfig) -> None`

Writes the trigger / pre-post / decimation / etc. registers.
Validates the config against the live bitstream's parameters
(SAMPLE_W, DEPTH, NUM_CHANNELS, TRIG_STAGES) and raises `ValueError`
on any mismatch.

```python
cfg = CaptureConfig(
    pretrigger      = 8,
    posttrigger     = 16,
    trigger         = TriggerConfig(mode="value_match", value=0x42, mask=0xFF),
    sample_width    = 8,
    depth           = 1024,
    sample_clock_hz = 100_000_000,
    probes          = [ProbeSpec(name="counter", width=8, lsb=0)],
    channel         = 0,
    decimation      = 0,
    ext_trigger_mode= 0,
    sequence        = None,        # or list[SequencerStage] for multi-stage
    probe_sel       = 0,
    stor_qual_mode  = 0,
    stor_qual_value = 0,
    stor_qual_mask  = 0,
    startup_arm     = False,       # leave the core armed after RESET
    trigger_holdoff = 0,           # ignore triggers for N cycles after arm/re-arm
    trigger_delay   = 0,           # new in v0.3.0
)
a.configure(cfg)
```

Every field has a default; the only required ones are `pretrigger`,
`posttrigger`, and `trigger`.

### `arm() -> None`

Asserts the ARM bit.  After this the ELA is recording into its
circular buffer and waiting for the trigger.

### `wait_done(timeout=10.0, poll_interval=0.05) -> bool`

Polls the STATUS register until DONE is asserted, or returns False
on timeout.  You normally don't call this directly — `capture()`
calls it for you.

### `capture(timeout=10.0) -> CaptureResult`

The full pipeline: `wait_done()`, read back the captured samples
(via the configured burst path when available), read back timestamps if enabled, return a
`CaptureResult`.  Raises `TimeoutError` if the trigger never fires
within `timeout` seconds.

When `TIMESTAMP_W > 0`, timestamps are read via
`transport.read_timestamp_block()` if the transport implements that
method (writes `BURST_PTR[31]=1` to switch burst readout to the timestamp
BRAM).  If the method is absent, `Analyzer` falls back
to `read_block()` over USER1, which is correct but slower.
`XilinxHwServerTransport` always implements the fast path.

```python
a.arm()
result = a.capture(timeout=10.0)
print(f"got {len(result.samples)} samples, overflow={result.overflow}")
```

### `capture_continuous(count=0, timeout_per=10.0)`

Generator that arms, waits, captures, re-arms, repeats.  `count=0`
means "forever".

```python
for i, result in enumerate(a.capture_continuous(count=10)):
    print(f"capture {i}: {len(result.samples)} samples")
```

### Segmented memory

For `NUM_SEGMENTS > 1`:

```python
a.configure(cfg)
a.arm()
a.wait_all_segments_done(timeout=10.0)

for seg in range(4):
    result = a.capture_segment(seg)
    print(f"segment {seg}: {result.samples}")
```

### Export helpers

```python
a.write_json(result, "capture.json")
a.write_csv(result, "capture.csv")
a.write_vcd(result, "capture.vcd")

# Or get the text/dict in memory:
json_dict = a.export_json(result)
csv_text  = a.export_csv_text(result)
vcd_text  = a.export_vcd_text(result)
```

The VCD export uses the `ProbeSpec`s from the original `CaptureConfig`
to give each lane a meaningful name and position; without probes you
get one giant `sample` blob.  See [chapter 15](15_export_formats.md).

### `reset() -> None`

Asserts the RESET bit, clearing armed/triggered/done.  Use it to
abort an in-progress capture or recover from a stuck state.  If
`CaptureConfig.startup_arm` is enabled, a later RESET leaves the
core armed again instead of idle.

## `CaptureConfig` and friends

### `CaptureConfig`

```python
@dataclass
class CaptureConfig:
    pretrigger:       int           # 0..(depth - posttrigger - 1)
    posttrigger:      int           # 0..(depth - pretrigger - 1)
    trigger:          TriggerConfig
    sample_width:     int = 8       # must match hardware SAMPLE_W
    depth:            int = 1024    # must match hardware DEPTH
    sample_clock_hz:  int = 100_000_000   # used for VCD timescale
    probes:           list[ProbeSpec] = []
    channel:          int = 0       # NUM_CHANNELS mux selector
    decimation:       int = 0       # 0=every cycle, N=every N+1
    ext_trigger_mode: int = 0       # 0=disabled, 1=OR, 2=AND
    sequence:         list[SequencerStage] | None = None
    probe_sel:        int = 0       # PROBE_MUX_W slice selector
    stor_qual_mode:   int = 0       # 0/1/2
    stor_qual_value:  int = 0
    stor_qual_mask:   int = 0
    startup_arm:      bool = False  # RESET leaves the core armed
    trigger_holdoff:  int = 0       # 0..65535 cycles after arm/re-arm
    trigger_delay:    int = 0       # 0..65535 sample-clock cycles
```

### `TriggerConfig`

```python
@dataclass
class TriggerConfig:
    mode:  str    # "value_match" | "edge_detect" | "both"
    value: int
    mask:  int
```

### `ProbeSpec`

```python
@dataclass
class ProbeSpec:
    name:  str
    width: int   # bits, > 0
    lsb:   int   # bit offset from sample LSB, >= 0
```

Used for naming sub-signals inside a packed sample word.  The same
underlying word can be split into multiple named lanes:

```python
probes = [
    ProbeSpec(name="addr",  width=4, lsb=0),    # bits [3:0]
    ProbeSpec(name="data",  width=4, lsb=4),    # bits [7:4]
]
```

These names show up in the VCD export and the LLM-friendly summary.
Overlapping bit ranges raise `ValueError` in `Analyzer.configure()`.

For reusable probe maps, store the same fields in a `.prob` sidecar:

```python
from fcapz import load_probe_file, write_probe_file

write_probe_file(
    "design.prob",
    [ProbeSpec("valid", 1, 0), ProbeSpec("state", 7, 1)],
    sample_width=8,
)

probe_file = load_probe_file("design.prob")
cfg = CaptureConfig(..., sample_width=probe_file.sample_width, probes=probe_file.probes)
```

### `SequencerStage`

```python
@dataclass
class SequencerStage:
    cmp_mode_a:   int = 0    # 0..8 — see compare modes table in chapter 05
    cmp_mode_b:   int = 0
    combine:      int = 0    # 0=A, 1=B, 2=A&B, 3=A|B
    next_state:   int = 0    # which stage to advance to
    is_final:     bool = False
    count_target: int = 1    # advance after this many matches
    value_a:      int = 0
    mask_a:       int = 0xFFFFFFFF
    value_b:      int = 0
    mask_b:       int = 0xFFFFFFFF
```

Pass a list of these as `CaptureConfig.sequence` to drive the
multi-stage sequencer.  See [chapter 05](05_ela_core.md) for the
worked example.

### `CaptureResult`

```python
@dataclass
class CaptureResult:
    config:     CaptureConfig         # the config that produced this capture
    samples:    list[int]             # captured sample words, oldest first
    overflow:   bool                  # True if STATUS.overflow was set
    timestamps: list[int]             # parallel list of timestamps (empty if TIMESTAMP_W=0)
    segment:    int = 0               # which segment (for segmented captures)
```

The trigger sample is at `samples[config.pretrigger]` (0-indexed).
Pre-trigger samples are at indices `0..pretrigger-1`, post-trigger
at `pretrigger+1..pretrigger+posttrigger`.

## `EioController`

```python
from fcapz import EioController

eio = EioController(transport, chain=3)
info = eio.connect()
# also exposes eio.in_w, eio.out_w, eio.version_major, eio.version_minor, eio.core_id

value = eio.read_inputs()           # int, IN_W bits
bit5  = eio.get_bit(5)              # 0 or 1
eio.write_outputs(0xA5)             # int, masked to OUT_W bits
eio.set_bit(3, 1)                   # read-modify-write a single bit
back = eio.read_outputs()           # read back the OUT_W register
eio.close()
```

See [chapter 06](06_eio_core.md) for the full walkthrough.

## `EjtagAxiController`

```python
from fcapz import EjtagAxiController, AXIError

bridge = EjtagAxiController(transport, chain=4)
info = bridge.connect()
# {"bridge_id": 0x454A4158, "addr_w": 32, "data_w": 32, "fifo_depth": 16, ...}

# Single transactions
val = bridge.axi_read(0x40000000)
resp = bridge.axi_write(0x40000000, 0xDEADBEEF, wstrb=0xF)

# Auto-increment block
words = bridge.read_block(0x40000000, count=64)
bridge.write_block(0x40000000, [0xAA, 0xBB, 0xCC])

# AXI4 burst
words = bridge.burst_read(0x40000000, count=16)    # count <= fifo_depth
bridge.burst_write(0x40000000, [0xAA, 0xBB, 0xCC, 0xDD])

bridge.close()
```

`axi_read` / `axi_write` raise `AXIError` on a non-OKAY response.
`burst_read` / `burst_write` raise `ValueError` if the count
exceeds `fifo_depth` or AXI4's max burst (256).

See [chapter 07](07_ejtag_axi_bridge.md) for full details.

## `EjtagUartController`

```python
from fcapz import EjtagUartController

uart = EjtagUartController(transport, chain=4)
info = uart.connect()
# {"id": 0x454A5552, "version": 0x00010000}

uart.send(b"Hello\n")
data = uart.recv(count=64, timeout=1.0)
line = uart.recv_line(timeout=1.0)
status = uart.status()
uart.close()
```

See [chapter 08](08_ejtag_uart_bridge.md) for full details.

## The `events` module — LLM-friendly capture summaries

`fcapz.events` provides post-processing helpers that turn raw
`CaptureResult.samples` into structured event lists.  These are
designed to be passed straight into an LLM context, an LLM agent,
or a regression test.

### `ProbeDefinition`

```python
from fcapz import ProbeDefinition

p = ProbeDefinition(name="bit0", width=1, lsb=0)
v = p.extract(0b1010)    # → 0
```

### `find_edges(result, probe=None, mask=0xFFFFFFFF) -> list[Edge]`

Returns every value-change between consecutive samples.

```python
from fcapz import find_edges
edges = find_edges(result)
# [Edge(index=1, old_value=0, new_value=1, probe="sample"), ...]
```

### `find_rising_edges(result, bit, probe=None) -> list[int]`

Returns the sample indices where `bit` transitions from 0 to 1.
`find_falling_edges()` is the dual.

### `find_bursts(result, probe=None, mask=0xFFFFFFFF) -> list[Burst]`

Returns contiguous runs of constant value:

```python
from fcapz import find_bursts
bursts = find_bursts(result)
# [Burst(start=0, end=8, value=0, probe="sample"),
#  Burst(start=8, end=10, value=1, probe="sample"), ...]
```

### `frequency_estimate(result, bit, probe=None) -> Optional[float]`

Estimates the toggle frequency of a bit, in Hz, using the
sample_clock_hz from `result.config`.  Returns `None` if there are
fewer than 2 rising edges.

### `summarize(result, probes=None) -> dict`

LLM-friendly capture summary:

```python
from fcapz import summarize
s = summarize(result, [ProbeDefinition("counter", 8, 0)])
# {
#   "total_samples": 25,
#   "sample_width": 8,
#   "sample_clock_hz": 100000000,
#   "pretrigger": 8,
#   "posttrigger": 16,
#   "trigger": {...},
#   "overflow": False,
#   "signals": [
#     {
#       "name": "counter",
#       "min": 58, "max": 82,
#       "unique_values": 25,
#       "edge_count": 24,
#       "burst_count": 25,
#       "longest_burst": {"value": 0, "length": 1, "start": 0},
#       "first_edge": {"index": 1, "from": 58, "to": 59},
#       "last_edge": {"index": 24, "from": 81, "to": 82},
#     }
#   ]
# }
```

The output schema is **stable**: every signal entry has the same
keys (`longest_burst`, `first_edge`, `last_edge`), defaulting to
`None` when there are no bursts/edges.  This means downstream code
(LLM context, regression tests, JSON consumers) can rely on the
shape regardless of capture content.

## A complete example

```python
"""
Capture an 8-bit counter on Arty A7, trigger on value 0x42,
export to VCD, and print an LLM-friendly summary.
"""
from fcapz import (
    XilinxHwServerTransport, Analyzer,
    CaptureConfig, TriggerConfig, ProbeSpec,
    summarize, ProbeDefinition,
)

transport = XilinxHwServerTransport(
    port=3121,
    fpga_name="xc7a100t",
    bitfile="examples/arty_a7/arty_a7_top.bit",   # programs FPGA on connect
)

analyzer = Analyzer(transport)
analyzer.connect()
print("probe:", analyzer.probe())

cfg = CaptureConfig(
    pretrigger  = 8,
    posttrigger = 16,
    trigger     = TriggerConfig(mode="value_match", value=0x42, mask=0xFF),
    sample_width= 8,
    depth       = 1024,
    probes      = [ProbeSpec(name="counter", width=8, lsb=0)],
)

analyzer.configure(cfg)
analyzer.arm()
result = analyzer.capture(timeout=5.0)

print(f"captured {len(result.samples)} samples, overflow={result.overflow}")
print(f"trigger sample (idx {cfg.pretrigger}) = 0x{result.samples[cfg.pretrigger]:02X}")

analyzer.write_vcd(result, "counter.vcd")
print("wrote counter.vcd")

print("\nSummary:")
import json
print(json.dumps(summarize(result, [ProbeDefinition("counter", 8, 0)]), indent=2))

analyzer.close()
```

Run it and you get a working capture, a viewable VCD, and a JSON
blob you could feed straight into an LLM ("here is what the
counter did, find the anomaly").

## What's next

- [Chapter 10 — CLI reference](10_cli_reference.md): every flag of
  the `fcapz` command, with examples.
- [Chapter 11 — JSON-RPC server](11_rpc_server.md): drive fcapz
  from another language.
- [Chapter 12 — Desktop GUI](12_gui.md): point-and-click instead.
- [Chapter 14 — Transports](14_transports.md): the transport ABC,
  IR-table presets, adding a new backend.
