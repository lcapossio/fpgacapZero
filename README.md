# fpgacapZero

[![CI](https://github.com/lcapossio/fpgacapZero/actions/workflows/ci.yml/badge.svg)](https://github.com/lcapossio/fpgacapZero/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

<a id="readme-top"></a>

Open-source, vendor-agnostic FPGA debug cores: an **Embedded Logic Analyzer
(ELA)** for waveform capture, an **Embedded I/O (EIO)** for runtime
read/write of fabric signals, and a **JTAG-to-AXI4 Bridge (EJTAG-AXI)** for
memory-mapped bus access — all over JTAG. Drop them into any FPGA design and
export captures to JSON, CSV, or VCD.

Includes single-instantiation wrappers for **Xilinx 7-series**, **Xilinx
UltraScale / UltraScale+**, **Lattice ECP5**, **Intel / Altera**, and
**Gowin** in both Verilog and VHDL. The core RTL and Python host stack
are fully portable.

📖 **[User manual](docs/README.md)** — full walkthrough of the RTL cores,
host stack, CLI, RPC server, and desktop GUI. **JTAG register / shift maps**
are not duplicated in this README; see the manual (e.g. chapter 13 and
[`docs/specs/register_map.md`](docs/specs/register_map.md)) and
[`docs/specs/transport_api.md`](docs/specs/transport_api.md) for canonical
specs.

## Contents

- [Features](#features)
- [Support status](#support-status)
- [Quick start](#quick-start)
  - [Desktop GUI (fcapz-gui)](#desktop-gui-fcapz-gui)
- [Usage](#usage)
  - [CLI reference](#cli-reference)
  - [Python API](#python-api)
  - [JSON-RPC server](#json-rpc-server)
- [Integrating the core into your design](#integrating-the-core-into-your-design)
  - [RTL instantiation](#rtl-instantiation)
  - [Vendor JTAG chain availability](#vendor-jtag-chain-availability)
  - [JTAG protocol and register reference](#jtag-protocol-and-register-reference)
- [Comparison with other embedded logic analyzers](#comparison-with-other-embedded-logic-analyzers)
- [Resource usage](#resource-usage)
- [CI](#ci)
- [Building from source](#building-from-source)
- [Project structure](#project-structure)
- [License](#license)

Jump within this page: [↑ Top](#readme-top)

## Features

- **Tiny, parameterizable RTL core** -- ~1,595 slice LUTs + 0.5 BRAM baseline
  (8b × 1024, dual comparators, Vivado 2025.2 synth on xc7a100t);
  configurable sample width (1-256+ bits) and buffer depth (16-16M samples)
- **Flexible trigger** -- optional dual comparators per stage with lightweight
  default modes (==, !=, rising, falling, changed), optional relational modes
  (<, >, <=, >=), boolean combine (AND/OR), and optional multi-stage
  sequencer (2-4 states)
- **Configurable trigger delay** (`TRIG_DELAY`, 0-65535 sample clocks) --
  shifts the committed trigger sample N cycles after the trigger event
  to compensate for upstream pipeline latency between a cause signal
  and its visible effect on the probe bus
- **Circular buffer** with pre/post-trigger lengths and optional storage
  qualification (10x effective depth for sparse signals, +21 LUTs)
- **Burst readback** -- 256-bit USER2 DR packs multiple samples per scan so
  readback amortises host round-trips; observed rate depends on the adapter,
  tool chain, and whether the transport batches DR scans
- **Two JTAG backends** -- OpenOCD (cross-platform) and Xilinx hw_server/XSDB
- **Python host stack** -- ELA CLI, optional **PySide6 desktop GUI** (`fcapz-gui`),
  programmatic API, JSON-RPC server, and LLM event extraction helpers
- **Embedded I/O (EIO)** -- RTL cores and Python controller for runtime
  read/write of fabric signals via JTAG USER3
- **JTAG-to-AXI4 Bridge (EJTAG-AXI)** -- 72-bit pipelined DR for single
  and burst AXI4 transactions over JTAG; block and burst paths use
  `raw_dr_scan_batch` where the transport supports it to amortise scan overhead
- **JTAG-to-UART Bridge (EJTAG-UART)** -- 32-bit pipelined DR for
  bidirectional UART over JTAG; TX/RX async FIFOs (effective rate is
  dominated by JTAG round-trip latency). Use cases: debug console,
  firmware upload, printf-over-JTAG without a physical UART pin
- **Three export formats** -- JSON (LLM-friendly), CSV, VCD
- **Multi-signal probes** -- named sub-signals in VCD export and capture
  summaries
- **Timing-friendly trigger pipeline** -- `INPUT_PIPE>=1` also registers
  comparator hits, so optional relational trigger modes can be used in faster
  sample-clock builds with one extra cycle of trigger decision latency
- **Sample decimation** (DECIM_EN=1) -- /N divider captures every N+1 cycles,
  extending effective capture window without increasing buffer depth
- **External trigger I/O** (EXT_TRIG_EN=1) -- trigger_in / trigger_out ports
  with OR and AND combine modes for multi-core or cross-chip synchronisation
- **Timestamp counter** (TIMESTAMP_W=32 or 48) -- per-sample cycle-accurate
  timestamps; exported to VCD for precise timing even with decimation
- **Segmented memory** (NUM_SEGMENTS>1) -- auto-rearm after each segment fills,
  capturing multiple trigger events in a single run
- All four features are **parameter-gated** -- the smallest core configuration
  has none enabled, adding zero overhead

[↑ Top](#readme-top)

## Support status

| Area | Status |
|------|--------|
| Xilinx `hw_server` backend | Implemented and hardware-validated on Arty A7 (7-series) |
| OpenOCD backend | Implemented, needs more hardware validation |
| Xilinx 7-series wrappers (`*_xilinx7.v`) | Implemented and hardware-validated on Arty A7-100T |
| Xilinx UltraScale / UltraScale+ wrappers (`*_xilinxus.v`) | Implemented in RTL (BSCANE2, identical to 7-series); not yet hardware-validated |
| Lattice / Intel / Gowin TAP wrappers | Implemented in RTL, host validation still limited |
| Runtime channel mux | Implemented in RTL and host API/CLI/RPC |
| EIO over real transports | Implemented — transport chain selection supports USER3 |
| EJTAG-AXI bridge | Hardware-validated on Arty A7 (single, auto-inc, and burst modes) |
| EJTAG-UART bridge | Hardware-validated on Arty A7 (loopback: send, recv, recv_line, status) |
| Sample decimation | Implemented in RTL and host API/CLI |
| External trigger I/O | Implemented in RTL and host API/CLI |
| Timestamp counter | Implemented in RTL and host API/CLI |
| Segmented memory | Hardware-validated on Arty A7 (4 segments, auto-rearm) |
| Raw TCF transport | Planned |

[↑ Top](#readme-top)

## Quick start

### Prerequisites

- Python 3.10+
- Any FPGA board with JTAG access (tested on Arty A7-100T)
- One of:
  - [OpenOCD](https://openocd.org/) with FTDI support (any vendor), **or**
  - Vivado/XSDB (2022.2+) for the Xilinx hw_server backend

### Developer quick start

```bash
pip install -e ".[dev]"
pytest tests/ -v
python sim/run_sim.py
```

`python sim/run_sim.py` runs the shared RTL lint pass (`iverilog -Wall`)
first, then the default simulation regression.  Use
`python sim/run_sim.py --lint-only` when you only want the RTL lint check.

Use the installed `fcapz` entry point for day-to-day ELA work. The legacy
`python -m fcapz.cli` form still works, but the package install path is
what contributors should rely on. GitHub Actions runs a subset of these checks
(see [CI](#ci)); run `pytest tests/ -v` locally before pushing so CLI, RPC, and
event-helper tests run too.

### Desktop GUI (fcapz-gui)

Install the GUI extra (PySide6, pyqtgraph, GTKWave/Surfer/WaveTrace optional on PATH):

```bash
pip install -e ".[gui]"
fcapz-gui
```

Connect over **hw_server** or **OpenOCD**, capture from the **ELA** tab, inspect
waveforms in the embedded preview, or open captures in **GTKWave** (`.gtkw`
sidecar) or **Surfer** (`--command-file` sidecar, `*.surfer.txt`). Settings and
probe profiles live in `%APPDATA%\\fpgacapzero\\gui.toml` (Windows) or
`~/.config/fpgacapzero/gui.toml` (Unix). Next to that file, `fcapz-gui-window.ini`
stores main-window geometry, dock/tab layout, expandable section state, and any
**Window → Save layout as…** presets. Docks are detachable and tabbable; the log
dock supports level filter, substring search, optional stderr mirroring, and
Clear / Copy all from the **File** menu.

Connect runs in the background; **Cancel** stops the attempt by closing the
transport (TCP/JTAG may take a moment to unwind if the server hung). The
Connection panel sets **Connect timeout** (OpenOCD TCP, seconds) and **HW ready
timeout** (after programming a `.bit`, seconds); both are stored in `gui.toml`
under `[connection]` as `connect_timeout_sec` and `hw_ready_timeout_sec`.

**Surfer:** the GUI opens the native **Surfer** binary in its **own window** (same as
GTKWave). Upstream does not expose a supported way to dock the native Surfer UI inside
the Qt main window; true in-app embedding would mean a **WebEngine** surface (Surfer’s
WASM/web API) or **server** mode, not the current `Popen` path. When `surfer` is on
`PATH`, `pytest tests/test_surfer_integration_smoke.py` runs a small CLI smoke check.

CLI capture can spawn a viewer after export (VCD only):

```bash
fcapz capture --format vcd --out dump.vcd --open-in gtkwave ...
fcapz capture --format vcd --out dump.vcd --open-in surfer ...
```

### Probe the core

The `--program` flag programs the FPGA automatically before running the
command. Build the Arty A7 reference design bitstream first (see
[Building from source](#building-from-source)), or use your own bitstream.

```bash
# hw_server backend (Vivado) — programs FPGA and probes in one command
fcapz --backend hw_server --port 3121 \
  --program examples/arty_a7/arty_a7_top.bit probe

# OpenOCD backend (program separately, then probe)
openocd -f examples/arty_a7/arty_a7.cfg &
fcapz --backend openocd --port 6666 probe
```

Sample output:

```json
{
  "version_major": 0,
  "version_minor": 3,
  "core_id": 19521,
  "sample_width": 8,
  "depth": 1024,
  "num_channels": 1
}
```

`core_id` is the ASCII string `"LA"` packed as `0x4C41` (= 19521).
`Analyzer.probe()` raises `RuntimeError` if this magic does not match,
so a wrong-chain / wrong-bitstream / unprogrammed FPGA is rejected
before any other ELA register is touched.

### Capture a waveform

```bash
fcapz --backend hw_server --port 3121 \
  --program examples/arty_a7/arty_a7_top.bit \
  capture \
  --pretrigger 8 --posttrigger 16 \
  --trigger-mode value_match --trigger-value 0 --trigger-mask 0xFF \
  --out capture.json
```

This programs the FPGA, arms the trigger, waits for a match, reads back
samples via burst mode, and writes `capture.json`.

### Capture with LLM summary

```bash
fcapz --backend hw_server --port 3121 \
  --program examples/arty_a7/arty_a7_top.bit \
  capture --pretrigger 8 --posttrigger 16 \
  --trigger-value 0 --trigger-mask 0xFF \
  --probes counter_lo:4:0,counter_hi:4:4 \
  --out capture.vcd --format vcd --summarize
```

The `--summarize` flag prints a structured JSON summary (edge counts, value
ranges, burst lengths) that an LLM can consume directly. The `--probes` flag
splits the 8-bit sample into named sub-signals in VCD output.

[↑ Top](#readme-top)

## Usage

### CLI reference

```
fcapz [global options] <command> [command options]
```

**Global options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--backend` | `hw_server` | `openocd` or `hw_server` |
| `--host` | `127.0.0.1` | Server address |
| `--port` | `6666` | `6666` for OpenOCD, `3121` for hw_server |
| `--tap` | `xc7a100t.tap` | JTAG TAP name |
| `--program` | *(none)* | Program FPGA with bitfile before command (hw_server) |

**Commands:**

| Command | Description |
|---------|-------------|
| `probe` | Read core identity (version, sample width, depth) |
| `arm` | Arm the trigger without configuring |
| `configure` | Write capture configuration to hardware |
| `capture` | Configure, arm, wait for trigger, read samples, export |
| `uart-send` | Send data to UART TX via JTAG-to-UART bridge |
| `uart-recv` | Receive data from UART RX via JTAG-to-UART bridge |
| `uart-monitor` | Continuous UART receive (Ctrl+C to stop) |

**Capture / configure options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--pretrigger` | `8` | Samples to keep before trigger |
| `--posttrigger` | `16` | Samples to capture after trigger |
| `--trigger-mode` | `value_match` | `value_match`, `edge_detect`, or `both` |
| `--trigger-value` | `0` | Trigger compare value |
| `--trigger-mask` | `0xFF` | Bit mask (hex) |
| `--trigger-delay` | `0` | Post-trigger delay in sample-clock cycles (0..65535) — shifts the committed trigger sample N cycles after the trigger event |
| `--sample-width` | `8` | Bits per sample |
| `--depth` | `1024` | Buffer depth |
| `--sample-clock-hz` | `100000000` | For VCD timescale |
| `--channel` | `0` | Probe mux channel index |
| `--probes` | *(none)* | Signal definitions: `name:width:lsb,...` |
| `--timeout` | `10.0` | Seconds to wait for trigger (capture only) |
| `--out` | *(required)* | Output file path (capture only) |
| `--format` | `json` | `json`, `csv`, or `vcd` (capture only) |
| `--decimation` | `0` | Decimation ratio (capture every N+1 cycles; 0=off, requires DECIM_EN) |
| `--ext-trigger-mode` | `disabled` | External trigger mode: `disabled`, `or`, `and` (requires EXT_TRIG_EN) |
| `--summarize` | off | Print LLM-friendly capture summary (capture only) |
| `--open-in` | *(none)* | After VCD capture, open viewer: `gtkwave` (`.gtkw`), `surfer` (`.surfer.txt`), `wavetrace`, or `custom` |
| `--gui-config` | per-user path | `gui.toml` for viewer paths and custom argv |

### Python API

```python
from fcapz import Analyzer, CaptureConfig, TriggerConfig, ProbeSpec
from fcapz import XilinxHwServerTransport
from fcapz import summarize, find_edges, ProbeDefinition

# Default ir_table is the Xilinx 7-series preset (USER1=0x02, USER2=0x03,
# USER3=0x22, USER4=0x23).  For an UltraScale / UltraScale+ board, pass
# the named UltraScale preset instead — the IR opcodes differ:
#     transport = XilinxHwServerTransport(
#         port=3121,
#         fpga_name="xcku040",
#         ir_table=XilinxHwServerTransport.IR_TABLE_US,  # USER1=0x24, ...
#     )
transport = XilinxHwServerTransport(port=3121)
analyzer = Analyzer(transport)
analyzer.connect()

print(analyzer.probe())

config = CaptureConfig(
    pretrigger=8,
    posttrigger=16,
    trigger=TriggerConfig(mode="value_match", value=0, mask=0xFF),
    probes=[ProbeSpec("counter_lo", 4, 0), ProbeSpec("counter_hi", 4, 4)],
    channel=0,
)
analyzer.configure(config)
analyzer.arm()
result = analyzer.capture(timeout=5.0)

# Export
analyzer.write_json(result, "capture.json")
analyzer.write_vcd(result, "capture.vcd")   # named signals in VCD

# LLM event extraction
edges = find_edges(result)
summary = summarize(result, [ProbeDefinition("lo", 4, 0)])
print(summary)

# Continuous capture (auto-rearm)
for result in analyzer.capture_continuous(count=3):
    print(f"got {len(result.samples)} samples")

analyzer.close()

# Embedded I/O
from fcapz.eio import EioController
from fcapz import XilinxHwServerTransport  # reuse same transport type

eio = EioController(XilinxHwServerTransport(port=3121))
eio.connect()
print(eio.read_inputs())        # read probe_in from fabric
eio.write_outputs(0x1)          # drive probe_out into fabric
eio.set_bit(0, 1)               # set single bit without disturbing others
eio.close()
```

#### JTAG-to-AXI4 Bridge

```python
from fcapz import EjtagAxiController

bridge = EjtagAxiController(transport, chain=4)
bridge.connect()
bridge.axi_write(0x40000000, 0xDEADBEEF)
value = bridge.axi_read(0x40000000)
bridge.close()
```

#### JTAG-to-UART Bridge

```bash
# Send a string
fcapz --backend hw_server --port 3121 uart-send --data "Hello\n"

# Send hex-encoded bytes
fcapz --backend hw_server --port 3121 uart-send --hex 48656C6C6F0A

# Send a file
fcapz --backend hw_server --port 3121 uart-send --file firmware.bin

# Receive up to 64 bytes with 2-second timeout
fcapz --backend hw_server --port 3121 uart-recv --count 64 --timeout 2.0

# Receive a single line (stops at newline)
fcapz --backend hw_server --port 3121 uart-recv --line

# Continuous monitor (Ctrl+C to stop)
fcapz --backend hw_server --port 3121 uart-monitor
```

```python
from fcapz import EjtagUartController

uart = EjtagUartController(transport, chain=4)
uart.connect()
uart.send(b"Hello\n")
data = uart.recv(count=0, timeout=1.0)
line = uart.recv_line(timeout=1.0)
print(uart.status())
uart.close()
```

### JSON-RPC server

For LLM-driven or scripted ELA control:

```bash
python -m fcapz.rpc
```

Send JSON commands on stdin, receive responses on stdout. Responses now carry
`schema_version`, and ELA `capture` supports `json`, `csv`, or `vcd` plus
optional `channel`, `probes`, and `summarize` fields.

```json
{"cmd": "connect", "backend": "hw_server", "port": 3121, "program": "examples/arty_a7/arty_a7_top.bit"}
{"cmd": "probe"}
{"cmd": "configure", "pretrigger": 8, "posttrigger": 16, "channel": 1}
{"cmd": "arm"}
{"cmd": "capture", "timeout": 5.0, "format": "vcd", "summarize": true,
 "probes": [{"name": "counter_lo", "width": 4, "lsb": 0}]}
```

[↑ Top](#readme-top)

## Integrating the core into your design

### RTL instantiation

Pick the wrapper for your FPGA vendor — one instantiation each for ELA and EIO:

```verilog
// Swap the wrapper suffix to port to another FPGA:
//   fcapz_ela_xilinx7  / fcapz_eio_xilinx7   — Xilinx 7-series (Artix-7,
//                                              Kintex-7, Virtex-7,
//                                              Spartan-7, Zynq-7000)
//   fcapz_ela_xilinxus / fcapz_eio_xilinxus  — Xilinx UltraScale and
//                                              UltraScale+ (Kintex/Virtex
//                                              UltraScale, Artix/Kintex/
//                                              Virtex/Zynq UltraScale+)
//   fcapz_ela_ecp5     / fcapz_eio_ecp5      — Lattice ECP5
//   fcapz_ela_intel    / fcapz_eio_intel     — Intel / Altera
//   fcapz_ela_gowin    / fcapz_eio_gowin     — Gowin GW1N / GW2A

wire [127:0] my_signals;  // up to 256+ bits

// ELA — embedded logic analyzer (one instantiation, all JTAG internals bundled)
fcapz_ela_xilinx7 #(
    .SAMPLE_W(128), .DEPTH(4096),
    .TRIG_STAGES(4), .STOR_QUAL(1),
    .DECIM_EN(0),        // 1 = enable sample decimation (/N divider)
    .EXT_TRIG_EN(0),     // 1 = enable external trigger I/O ports
    .TIMESTAMP_W(0),     // 32 or 48 = cycle-accurate timestamps (0 = off)
    .NUM_SEGMENTS(1)     // >1 = segmented memory with auto-rearm
) u_ela (
    .sample_clk (sys_clk),
    .sample_rst (reset),
    .probe_in   (my_signals)
);

// EIO — embedded I/O (optional, co-exists with ELA on a separate USER chain)
wire [31:0] eio_out;
fcapz_eio_xilinx7 #(.IN_W(32), .OUT_W(32)) u_eio (
    .probe_in  (my_signals[31:0]),
    .probe_out (eio_out)
);
```

**ECP5 / Gowin — ELA + EIO combined** (limited JTAG chains):

```verilog
// On ECP5 (2 chains) and Gowin (1 chain), EIO shares the ELA wrapper:
fcapz_ela_ecp5 #(
    .SAMPLE_W(128), .DEPTH(4096),
    .EIO_EN(1), .EIO_IN_W(32), .EIO_OUT_W(32)
) u_ela (
    .sample_clk   (sys_clk),
    .sample_rst   (reset),
    .probe_in     (my_signals),
    .eio_probe_in (my_signals[31:0]),
    .eio_probe_out(eio_out)
);
```

VHDL wrappers are also provided in `rtl/vhdl/`.

### Vendor JTAG chain availability

| Vendor | Primitive | User chains | ELA (needs 2) | EIO (needs 1) | EJTAG-AXI (needs 1) | EJTAG-UART (needs 1) |
|--------|-----------|:-----------:|:---:|:---:|:---:|:---:|
| **Xilinx** | BSCANE2 | 4 (USER1-4) | USER1+USER2 | USER3 | USER4 | USER4 (shared) |
| **Intel** | sld_virtual_jtag | Unlimited | inst 0+1 | inst 2 | inst 3 | inst 5 |
| **ECP5** | JTAGG | 2 (ER1+ER2) | ER1+ER2 | `EIO_EN=1` on ER1 | *deferred to v2* | *deferred to v2* |
| **Gowin** | JTAG | 1 | No burst | `EIO_EN=1` | *deferred to v2* | *deferred to v2* |

**Verified Xilinx 7-series IR codes** (xc7a100t, Arty A7):
USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23.

**Note:** On Xilinx 7-series, only 4 USER chains exist. The EJTAG-UART
wrapper defaults to USER4 (same as EJTAG-AXI). To use both in one
bitstream, assign UART to a free chain (e.g. USER3 if EIO is not used —
the Arty A7 reference design does this). On Intel, each gets a unique
virtual JTAG instance, so both always coexist.

On Gowin, the single chain means **no burst readback** — sample data is read
word-by-word through the sample DATA window (functional but slower). Details
are in the manual (see below).

### JTAG protocol and register reference

Bit-level DR layouts, ELA/EIO **address maps**, EJTAG-AXI / EJTAG-UART bridge
formats, and identity checks are maintained in one place so they do not drift
from the RTL.

- **[User manual index](docs/README.md)** — start here; [chapter 04 — RTL integration](docs/04_rtl_integration.md) covers chains, IR presets, and how the cores attach to the TAP.
- **Canonical spec:** [`docs/specs/register_map.md`](docs/specs/register_map.md) — full register / shift encodings for ELA, EIO, EJTAG-AXI, and EJTAG-UART (ground truth; [chapter 13](docs/13_register_map.md) is a short pointer into that file).

[↑ Top](#readme-top)

## Comparison with other embedded logic analyzers

| Feature | **fpgacapZero** | Vivado ILA | SignalTap II | Lattice Reveal | Gowin GAO | LiteScope |
|---------|:-----------:|:----------:|:------------:|:--------------:|:---------:|:---------:|
| **Vendor-portable** | Yes | No | No | No | No | Yes |
| **Open source** | Apache 2.0 | No | No | No | No | BSD |
| **Trigger modes** | 5 default, 9 with relational option | ==, !=, edge | ==, !=, compare | Value + edge | 6 types | Value match |
| **Trigger sequencer** | 2-4 stages | 16-state FSM | State-based | 16 levels | Multi-level | Basic |
| **Dual comparators** | Yes (AND/OR) | Yes | Yes | Yes (TU+TE) | Yes | No |
| **Storage qualification** | Yes | Yes | Yes | -- | -- | Subsampling |
| **Buffer type** | BRAM (any vendor) | BRAM/URAM | BRAM | EBR | BSRAM | BRAM |
| **Channel mux** | Yes (runtime) | Multiple cores | Runtime mux | Multiple cores | Up to 16 AO | Groups |
| **Readback** | JTAG burst  | JTAG | JTAG | JTAG | JTAG | Wishbone (UART/ETH/PCIe) |

\* 
| **Host interface** | Python API + CLI + JSON-RPC | GUI + Tcl + ChipScoPy | GUI + Tcl | GUI | GUI | Python + CLI |
| **Export formats** | JSON, CSV, VCD | CSV, VCD | CSV, VCD, TBL | Proprietary | CSV, VCD, PRN | VCD, CSV, SR |
| **Virtual I/O** | EIO core | VIO | In-System Sources | -- | GVIO | LiteScopeIO |
| **LLM-friendly** | Yes (JSON-RPC, summaries) | Moderate (Tcl) | Moderate (Tcl) | Limited | Limited | Good (Python) |
| **Baseline LUTs** | ~1,600 | ~1,000+ | Varies | Varies | Varies | Small |

**Key differentiators:**

- **Only vendor-portable option with advanced triggers** — optional dual
  comparators, optional relational modes, boolean combine, and multi-stage sequencer;
  LiteScope is also portable but offers only basic triggering
- **LLM-native host stack** — JSON-RPC server, structured event extraction
  (edges, bursts, frequency), and capture summaries designed for AI-driven debug
- **Single RTL file per core** — no code generation, no Python build step;
  standard Verilog parameters for all configuration
- **Apache 2.0 license** — usable in proprietary designs with explicit patent grant

[↑ Top](#readme-top)

## Resource usage

All features are compile-time optional via parameters. The sample buffer
uses dual-port BRAM, so scaling wider or deeper adds BRAM, not LUTs.

Numbers below are **Slice LUTs** and **FFs** from Vivado **synthesis**
reports on **xc7a100t** (2025.2), except the last row, which uses the
same **post–place & route** totals as the shipped `arty_a7_top`
reference (Apr 2026). Regenerate ELA-only rows with
`vivado -mode batch -source scripts/resource_comparison.tcl` (set
`FPGACAP_ROOT` if the repo is not next to `scripts/`).

| Config | Slice LUTs | FFs | BRAM | Notes |
|--------|-----:|----:|-----:|-------|
| 8b × 1024, baseline | 1,595 | 1,478 | 0.5 | Dual comparators, 9 modes; `TRIG_STAGES=1`, `STOR_QUAL=0` |
| 8b × 1024, +storage qual | 1,616 | 1,497 | 0.5 | +21 LUT |
| 8b × 1024, +4-stage seq | 2,098 | 1,878 | 0.5 | `TRIG_STAGES=4`, `STOR_QUAL=0` |
| 8b × 1024, seq + SQ | 2,095 | 1,897 | 0.5 | `TRIG_STAGES=4`, `STOR_QUAL=1` |
| 8b × 4096 | 1,541 | 1,490 | 1.0 | Deeper buffer (+0.5 BRAM tile vs 1024) |
| 32b × 1024 | 1,548 | 1,740 | 1.0 | Wider samples (+0.5 BRAM tile vs 8b×1024) |
| 8b x 1024, single comparator, slow USER1 readout | 596 | 779 | 0.5 | One BSCANE2; advanced features compiled out |
| 8b x 1024, single comparator, single-chain fast readout | 912 | 1,234 | 0.5 | One BSCANE2; 256-bit USER1 burst via `SINGLE_CHAIN_BURST=1` |
| **`arty_a7_top` (placed)** | **2,701** | **2,743** | **1.5** | ELA with `DECIM_EN`, `EXT_TRIG_EN`, `TIMESTAMP_W=32`, `NUM_SEGMENTS=4` + EIO 8/8 + EJTAG-AXI + `axi4_test_slave` (no UART in this bitstream) |

Optional ELA parameters (`DECIM_EN`, `EXT_TRIG_EN`, `TIMESTAMP_W`,
`NUM_SEGMENTS`, channel mux, etc.) add registers, comparators, and
extra BRAM (e.g. timestamp storage); the reference row above is the
authoritative “full validation” footprint for that combination.
Per-core deltas are not additive in synthesis because Vivado optimises
across hierarchy.

**Fmax (reference build):** `sys_clk` @ 100 MHz with WNS ≈ 1.13 ns after
route on `arty_a7_top` (xc7a100t, same build). JTAG `tck_bscan` is
constrained at 10 MHz (adapter-dependent in practice, often higher).

Both the EJTAG-AXI and EJTAG-UART cores use `fcapz_async_fifo`, a
reusable async FIFO module with per-domain reset (`wr_rst` + `rd_rst`).
`USE_BEHAV_ASYNC_FIFO=1` (default) uses a portable behavioral gray-coded
pointer FIFO; `USE_BEHAV_ASYNC_FIFO=0` wraps a vendor primitive (Xilinx
`xpm_fifo_async`). The Xilinx wrappers set it to 0 automatically.

Synthesis / P&R from Vivado 2025.2, xc7a100t (Arty A7). Fits on even
the smallest Artix-7.

```verilog
// Minimal core (Xilinx — swap suffix for other vendors)
fcapz_ela_xilinx7 #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
    .sample_clk(clk), .sample_rst(rst), .probe_in(signals)
);

// Full featured
fcapz_ela_xilinx7 #(.SAMPLE_W(8), .DEPTH(1024), .TRIG_STAGES(4), .STOR_QUAL(1)) u_ela (
    .sample_clk(clk), .sample_rst(rst), .probe_in(signals)
);
```

[↑ Top](#readme-top)

## CI

GitHub Actions runs on every push and pull request to `main` or `master`:

| Job | What it checks |
|-----|----------------|
| `lint-python` | `ruff` E/F/W rules on the whole repo |
| `test-host` | `pytest tests/ -v --tb=short` with the default `not hw` marker filter, plus an explicit JTAG readback pipeline regression step for USER1/USER2 priming and timestamp stabilization |
| `lint-rtl` | `python sim/run_sim.py --lint-only` — shared `iverilog -Wall` elaboration for the core RTL, Xilinx 7-series / UltraScale wrappers, and simulation stubs |
| `sim` | `python sim/run_sim.py` — runs the same `iverilog -Wall` lint pass, then ELA, ELA regression probe, EIO, and channel-mux testbenches (Icarus Verilog + `vvp`) |

Hardware integration tests run manually (require physical Arty A7-100T + hw_server).
Optional **GUI + hardware** checks in `tests/test_gui_hw_capture.py` are
documented in [CONTRIBUTING.md](CONTRIBUTING.md) (`FPGACAP_GUI_HW=1`, not run in CI).
Those board-level checks now require every adjacent Arty counter sample to
increment by +1 when decimation is disabled, so partial burst readback
corruption is caught instead of hidden by a shorter valid prefix.

[↑ Top](#readme-top)

## Building from source

### RTL (Vivado)

```bash
vivado -mode batch -source examples/arty_a7/build_arty.tcl
```

Produces `examples/arty_a7/arty_a7_top.bit`.

### Simulation (Icarus Verilog)

```bash
python sim/run_sim.py
python sim/run_sim.py --lint-only
```

The default command runs `iverilog -Wall` lint before compiling and running
the testbenches.  CI uses the same runner so local regressions and GitHub
Actions exercise the same RTL lint target list.

### Tests

```bash
# Unit tests (no hardware needed) — full suite recommended locally
python -m pytest tests/ -v

# Hardware integration tests (requires Arty A7 + hw_server + built bitstream)
python -m pytest examples/arty_a7/test_hw_integration.py -v

# Force-skip hardware integration tests (e.g. laptop without board)
FPGACAP_SKIP_HW=1 python -m pytest examples/arty_a7/test_hw_integration.py -v

# GUI + real JTAG (fcapz-gui) — opt-in; requires PySide6, pytest-qt, and a board.
# Default pytest excludes @pytest.mark.hw; see CONTRIBUTING.md for details.
FPGACAP_GUI_HW=1 python -m pytest tests/test_gui_hw_capture.py -v --tb=short \
  --override-ini='addopts=-p no:cacheprovider'
```

[↑ Top](#readme-top)

## Project structure

```
fpgacapZero/
  rtl/
    dpram.v                  Dual-port RAM (infers BRAM automatically)
    trig_compare.v           Comparator unit (9 modes)
    fcapz_ela.v              ELA core (vendor-agnostic)
    fcapz_eio.v              EIO core (vendor-agnostic)
    jtag_reg_iface.v         JTAG-to-register bridge
    jtag_pipe_iface.v        Single-chain register + burst pipe
    jtag_burst_read.v        Burst data readout (256-bit DR)
    fcapz_ela_xilinx7.v       ELA wrapper — Xilinx 7-series
    fcapz_ela_xilinxus.v      ELA wrapper — Xilinx UltraScale / UltraScale+
    fcapz_ela_ecp5.v          ELA wrapper — Lattice ECP5
    fcapz_ela_intel.v         ELA wrapper — Intel / Altera
    fcapz_ela_gowin.v         ELA wrapper — Gowin
    fcapz_eio_xilinx7.v       EIO wrapper — Xilinx 7-series
    fcapz_eio_xilinxus.v      EIO wrapper — Xilinx UltraScale / UltraScale+
    fcapz_eio_ecp5.v          EIO wrapper — Lattice ECP5
    fcapz_eio_intel.v         EIO wrapper — Intel / Altera
    fcapz_eio_gowin.v         EIO wrapper — Gowin
    fcapz_ejtagaxi.v          EJTAG-AXI bridge core (vendor-agnostic)
    fcapz_ejtagaxi_xilinx7.v  EJTAG-AXI wrapper — Xilinx 7-series
    fcapz_ejtagaxi_xilinxus.v EJTAG-AXI wrapper — Xilinx UltraScale / UltraScale+
    fcapz_ejtagaxi_intel.v    EJTAG-AXI wrapper — Intel / Altera
    fcapz_ejtaguart.v         EJTAG-UART bridge core (vendor-agnostic)
    fcapz_ejtaguart_xilinx7.v EJTAG-UART wrapper — Xilinx 7-series
    fcapz_ejtaguart_xilinxus.v EJTAG-UART wrapper — Xilinx UltraScale / UltraScale+
    fcapz_ejtaguart_intel.v   EJTAG-UART wrapper — Intel / Altera
    jtag_tap/
      jtag_tap_xilinx7.v    TAP primitive — Xilinx 7-series (BSCANE2)
      jtag_tap_xilinxus.v   TAP primitive — Xilinx UltraScale / UltraScale+ (BSCANE2)
      jtag_tap_ecp5.v       TAP primitive — Lattice (JTAGG)
      jtag_tap_intel.v      TAP primitive — Intel (sld_virtual_jtag)
      jtag_tap_gowin.v      TAP primitive — Gowin (JTAG)
    vhdl/
      fcapz_ela_*.vhd       VHDL ELA wrappers (one per vendor)
      fcapz_eio_*.vhd       VHDL EIO wrappers (one per vendor)
  tb/
    fcapz_ela_tb.sv          ELA core testbench
    fcapz_ela_bug_probe_tb.sv ELA regression probe for capture-window edge cases
    fcapz_eio_tb.sv          EIO core testbench (7 scenarios, 18 checks)
    chan_mux_tb.sv           Channel mux (NUM_CHANNELS) testbench
    fcapz_ejtagaxi_tb.sv    EJTAG-AXI bridge testbench
    fcapz_ejtaguart_tb.sv   EJTAG-UART bridge testbench
  host/fcapz/
    __init__.py            Public API
    analyzer.py            Analyzer, CaptureConfig, CaptureResult, ProbeSpec
    transport.py           OpenOCD and hw_server transports (burst + pipelined)
    events.py              LLM event extraction (edges, bursts, frequency, summarize)
    cli.py                 Command-line interface
    rpc.py                 JSON-RPC server
    eio.py                 EioController: read/write fabric probes via JTAG USER3
    ejtagaxi.py            EjtagAxiController: AXI4 read/write over JTAG USER4
    ejtaguart.py           EjtagUartController: UART send/recv over JTAG USER4
  examples/arty_a7/
    arty_a7_top.v          Reference design top-level
    arty_a7.xdc            Pin constraints
    build_arty.tcl         Vivado batch build
    arty_a7.cfg            OpenOCD config (onboard FT2232)
    arty_a7_hs3.cfg        OpenOCD config (Digilent HS3)
    test_hw_integration.py Hardware integration tests
  tests/
    test_host_stack.py     Python unit tests
    test_cli_rpc_events.py CLI, RPC, and event helper tests
    test_ejtaguart.py      EJTAG-UART controller unit tests
  docs/
    README.md              User-manual index (chapters 01_*–17_*)
    01_overview.md         What fpgacapZero is, the four cores, vendor matrix
    02_install.md          Python install, optional GUI extras, prereqs
    03_first_capture.md    10-minute walkthrough on Arty A7
    ...                    (see docs/README.md for the full chapter list)
    specs/                 Canonical reference docs
      architecture.md      Core block diagram
      register_map.md      Register map specification (ground truth)
      transport_api.md     Transport interface spec
      waveform_schema.md   Export format spec
```

[↑ Top](#readme-top)

## Author

Leonardo Capossio — [bard0 design](https://www.bard0.com) — <hello@bard0.com>

[↑ Top](#readme-top)

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

[↑ Top](#readme-top)
