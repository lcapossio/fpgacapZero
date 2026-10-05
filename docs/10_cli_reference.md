# 10 — CLI reference

> [!NOTE]
> **Goal**: complete reference for the `fcapz` command-line tool.
> Every subcommand, every flag, with copy-pasteable examples.  The
> usage lines and option tables are generated from the CLI itself
> (`tools/gen_docs.py`), so they always match `fcapz --help`.
>
> **Audience**: anyone who wants to use fcapz from a shell instead
> of writing Python.  Pre-read [chapter 03](03_first_capture.md) for
> the guided walkthrough that uses many of these commands.

## Invoking the CLI

After `pip install fpgacapzero`, two ways to invoke:

```bash
fcapz [global options] <subcommand> [options]
python -m fcapz.cli [global options] <subcommand> [options]   # equivalent
```

The console-script `fcapz` is registered by `pyproject.toml` and
should land on your `PATH` after install.  If it doesn't, see
[chapter 02](02_install.md) "Common install pitfalls".

## Global options

These come **before** the subcommand and apply to whichever
subcommand follows:

<!-- BEGIN GENERATED cli:global (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

| Option | Default | Description |
|---|---|---|
| `--gui-config PATH` | — | Path to gui.toml (default: per-user fpgacapzero config directory) |
| `--backend {openocd,hw_server,usb_blaster}` | `hw_server` | JTAG transport to use |
| `--host HOST` | `127.0.0.1` | Transport host (hw_server or OpenOCD) |
| `--port PORT` | `6666` | Transport TCP port. Left at 6666, hw_server uses its own port 3121; usb_blaster ignores it |
| `--tap TAP` | `xc7a100t.tap` | OpenOCD TAP name, hw_server FPGA target, or Quartus device name (usb_blaster: auto, empty, or this default selects the first device) |
| `--hardware NAME` | — | usb_blaster only: Quartus hardware name; default selects first USB-Blaster |
| `--quartus-stp PATH` | — | usb_blaster only: path to quartus_stp executable (default: found on PATH) |
| `--two-chain-burst` | off | hw_server only: use legacy ELA builds with 256-bit burst reads on USER2 |
| `--chain N` | `1` | ELA control BSCAN USER chain for probe, ela-list, arm, configure and capture |
| `--ela-instance N` | — | Core-manager ELA slot on the selected chain (default: current/legacy slot) |
| `--program BITFILE` | — | hw_server only: run fpga -file on this .bit before the command (slow). Omit to attach to the FPGA without reprogramming (already-loaded bitstream). |

<!-- END GENERATED cli:global -->

Examples:

```bash
# hw_server with explicit programming
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      --program my_design.bit \
      probe

# openocd with default port and tap
fcapz --backend openocd probe

# Override TAP name for a custom board
fcapz --backend openocd --tap my_custom_chip.tap probe

# Intel/Altera virtual JTAG through Quartus and USB-Blaster
fcapz --backend usb_blaster --tap auto probe

# Same, when quartus_stp is not on PATH
fcapz --backend usb_blaster --tap auto \
      --quartus-stp C:/altera_pro/26.1/quartus/bin64/quartus_stp.exe \
      probe
```

For `usb_blaster`, auto device selection chooses the first Quartus device whose
name starts with `@1`. The default AMD/Xilinx TAP values (`xc7a100t` and
`xc7a100t.tap`) are also treated as auto for USB-Blaster so old saved GUI/CLI
settings do not get passed to Quartus as literal device names. If the FPGA is
elsewhere in the JTAG chain, pass the exact Quartus device name with `--tap`.

## Subcommands at a glance

<!-- BEGIN GENERATED cli:subcommands (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

| Subcommand | What it does |
|---|---|
| `probe` | Read core identity registers |
| `ela-list` | Read core manager and probe all ELA slots |
| `arm` | Arm capture without configuring (advanced) |
| `axi-mon` | Detect an AXI monitor; print its identity and probe map |
| `configure` | Write capture configuration without arming |
| `capture` | Configure, arm, capture and export to a file |
| `eio-probe` | Read EIO core identity and widths |
| `eio-read` | Read EIO input probes |
| `eio-write` | Write EIO output probes |
| `axi-read` | Single AXI read via JTAG-to-AXI bridge |
| `axi-write` | Single AXI write via JTAG-to-AXI bridge |
| `axi-dump` | Read block of AXI words |
| `axi-fill` | Fill AXI memory with a pattern |
| `axi-load` | Load binary file into AXI memory |
| `uart-send` | Send data to UART TX via JTAG-to-UART bridge |
| `uart-recv` | Receive data from UART RX via JTAG-to-UART bridge |
| `uart-monitor` | Continuous UART receive (Ctrl+C to stop) |

<!-- END GENERATED cli:subcommands -->

## `probe`

Read the core's identity, version, and FEATURES registers:

<!-- BEGIN GENERATED cli:probe (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] probe`

No options of its own; the [global options](#global-options) apply.

<!-- END GENERATED cli:probe -->

```bash
fcapz --backend hw_server --port 3121 --tap xc7a100t probe
```

If the ELA wrapper was instantiated on another USER chain, pass `--chain`:

```bash
fcapz --backend hw_server --port 3121 --tap xc7a100t --chain 2 probe
```

For a managed multi-ELA design on one chain, list slots and select one:

```bash
fcapz --backend hw_server --port 3121 --tap xc7a100t ela-list
fcapz --backend hw_server --port 3121 --tap xc7a100t --ela-instance 1 probe
```

Output (formatted JSON to stdout):

```json
{
  "version_major": 0,
  "version_minor": 3,
  "core_id": 19521,
  "sample_width": 8,
  "depth": 1024,
  "num_channels": 1,
  "has_decimation": true,
  "has_ext_trigger": true,
  "has_timestamp": true,
  "timestamp_width": 32,
  "num_segments": 4,
  "probe_mux_w": 0
}
```

`core_id = 19521 = 0x4C41 = ASCII "LA"`.  If this is wrong, the
host raises `RuntimeError: ELA core identity check failed` — see
[chapter 17](17_troubleshooting.md).

## `ela-list`

Read the core manager on the selected `--chain` and probe every ELA slot behind
it (example under [`probe`](#probe) above).

<!-- BEGIN GENERATED cli:ela-list (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] ela-list`

No options of its own; the [global options](#global-options) apply.

<!-- END GENERATED cli:ela-list -->

## `arm`

Arm the core with the configuration it already holds, for example after a
`configure`.

<!-- BEGIN GENERATED cli:arm (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] arm`

No options of its own; the [global options](#global-options) apply.

<!-- END GENERATED cli:arm -->

## `axi-mon`

Detect an AXI monitor and print its identity and probe map; see
[chapter 19](19_axi_monitor.md).

<!-- BEGIN GENERATED cli:axi-mon (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] axi-mon [--write-probe-file PATH]`

| Option | Default | Description |
|---|---|---|
| `--write-probe-file PATH` | — | Write the matching .prob probe map to PATH (use with capture --probe-file) |

<!-- END GENERATED cli:axi-mon -->

## `capture` and `configure`

`capture` is the headline subcommand.  `configure` is the same
without arming or reading back — useful for one-shot pre-arm
setup.  Both take the same options.

### Options

<!-- BEGIN GENERATED cli:configure (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] configure [options]`

| Option | Default | Description |
|---|---|---|
| `--pretrigger N` | `8` | Samples to keep before the trigger |
| `--posttrigger N` | `16` | Samples to capture after the trigger |
| `--trigger-mode {value_match,edge_detect,both}` | `value_match` | Trigger comparator mode (see chapter 05) |
| `--trigger-value V` | `0` | Trigger compare value |
| `--trigger-mask M` | `0xff` | Trigger bit mask (hex or decimal) |
| `--sample-width N` | — | Bits per sample, must match the core (default: the probe file's, else 8) |
| `--depth N` | `1024` | Buffer depth in samples; must match the core |
| `--sample-clock-hz HZ` | — | Sample clock for the VCD timescale (default: the probe file's, else 100 MHz) |
| `--channel N` | `0` | Probe mux channel index |
| `--decimation N` | `0` | Sample decimation ratio (0=every cycle, N=every N+1); needs DECIM_EN=1 |
| `--ext-trigger-mode {disabled,or,and}` | `disabled` | Combine the external trigger input with the comparators; needs EXT_TRIG_EN=1 |
| `--probes SPEC` | — | Signal definitions: name:width:lsb,... (e.g. bus0:4:0,bus1:4:4) |
| `--probe-file FILE` | — | Load probe definitions, and the sample width and clock if given, from a .prob sidecar |
| `--trigger-sequence JSON` | — | JSON file path or inline JSON array of sequencer stages |
| `--probe-sel N` | `0` | Runtime probe mux slice index |
| `--stor-qual-mode N` | `0` | Storage qualification mode: 0=disabled, 1=store-when-match, 2=store-when-no-match |
| `--stor-qual-value V` | `0` | Storage qualification comparison value (hex or decimal) |
| `--stor-qual-mask M` | `0` | Storage qualification mask (hex or decimal) |
| `--startup-arm` | off | Leave the ELA armed after reset / configuration recovery. Useful with bitstreams that want to begin capturing immediately after startup or after an explicit RESET. |
| `--trigger-holdoff N` | `0` | Ignore trigger hits for N sample-clock cycles after arm or segmented auto-rearm. Distinct from --trigger-delay, which moves the committed trigger sample later. |
| `--trigger-delay N` | `0` | Post-trigger delay in sample-clock cycles (0..65535). Shifts the committed trigger sample N cycles after the trigger event to compensate for upstream pipeline latency. |
| `--profile NAME` | — | Use named probe list from gui.toml section [probe_profiles.NAME] |

<!-- END GENERATED cli:configure -->

### `capture`-only options

<!-- BEGIN GENERATED cli:capture/configure (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Options `capture` has in addition to those of `configure`:

| Option | Default | Description |
|---|---|---|
| `--timeout SEC` | `10.0` | Seconds to wait for the trigger |
| `--out FILE` | required | Output file |
| `--format {json,csv,vcd}` | `json` | Export format (not inferred from the --out extension) |
| `--summarize` | off | Print LLM-friendly capture summary to stdout |
| `--open-in VIEWER` | — | After capture, open the dump in a waveform viewer (requires --format vcd). Names: gtkwave, surfer, wavetrace, custom (needs gui.toml custom_argv). |

<!-- END GENERATED cli:capture/configure -->

### Examples

```bash
# Simple value-match capture, JSON output
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 8 --posttrigger 16 \
        --trigger-value 0x42 \
        --probes counter:8:0 \
        --out capture.json

# VCD output with named lanes
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 4 --posttrigger 4 \
        --trigger-value 0x10 \
        --probes lo:4:0,hi:4:4 \
        --format vcd --out capture.vcd

# Same idea, but load lanes from a .prob sidecar
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 4 --posttrigger 4 \
        --trigger-value 0x10 \
        --probe-file design.prob \
        --format vcd --out capture.vcd

# Trigger delay (commit trigger 4 cycles after the cause)
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 2 --posttrigger 8 \
        --trigger-value 0x10 \
        --trigger-delay 4 \
        --probes counter:8:0 \
        --out delayed.json

# Decimation (every 4th sample)
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 2 --posttrigger 5 \
        --trigger-value 0x20 \
        --decimation 3 \
        --probes counter:8:0 \
        --out decim.json

# Storage qualification (only store samples where bit 0 is high)
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 4 --posttrigger 16 \
        --trigger-value 0xFF --trigger-mask 0xFF \
        --stor-qual-mode 1 \
        --stor-qual-value 0x01 --stor-qual-mask 0x01 \
        --probes counter:8:0 \
        --out sparse.json

# Multi-stage trigger sequencer (inline JSON)
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 4 --posttrigger 16 \
        --trigger-sequence '[
          {"cmp_a":0,"value_a":"0x10","next_state":1,"is_final":false},
          {"cmp_a":3,"value_a":"0x80","mask_a":"0xFF","is_final":true}
        ]' \
        --probes counter:8:0 \
        --out sequenced.json

# Same, but loaded from a JSON file
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --trigger-sequence my_sequence.json \
        --probes counter:8:0 \
        --out sequenced.json

# Capture + summary (great for LLM consumption)
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      capture \
        --pretrigger 4 --posttrigger 8 \
        --trigger-value 0x42 \
        --probes counter:8:0 \
        --summarize \
        --out cap.json
```

### The `--probes` syntax

`--probes` takes a comma-separated list of `name:width:lsb`
triples.  Each triple defines one named lane within the packed
sample word:

```
--probes addr:4:0,data:4:4
```

This says "the low 4 bits are `addr`, the next 4 bits are `data`".
The names show up as separate signals in the VCD export and as
keys in the JSON / summary.

Constraints (validated by the host):
- `width > 0`
- `lsb >= 0`
- `lsb + width <= sample_width`
- No overlapping bit ranges across probes

Without `--probes` you get one giant `sample` signal in the VCD —
useful for quick checks but ugly for waveform viewing.

### The `.prob` sidecar format

`.prob` files are JSON probe maps.  They are the preferred way to keep signal
names next to a bitstream, especially when the ELA probe bus is wider than a
few hand-written fields:

```json
{
  "format": "fpgacapzero.probes.v1",
  "core": "ela",
  "sample_width": 41,
  "sample_clock_hz": 100000000,
  "probes": [
    {"name": "axi_valid", "width": 1, "lsb": 0},
    {"name": "axi_ready", "width": 1, "lsb": 1},
    {"name": "axi_addr", "width": 32, "lsb": 2},
    {"name": "state", "width": 7, "lsb": 34}
  ]
}
```

That file describes this packed RTL bus:

```verilog
assign ela_probe = {
    state,       // bits 40:34
    axi_addr,    // bits 33:2
    axi_ready,   // bit 1
    axi_valid    // bit 0
};
```

`--probe-file` and `--probes` are mutually exclusive.  If the file includes
`sample_width` or `sample_clock_hz`, those become the capture defaults; explicit
CLI `--sample-width` or `--sample-clock-hz` values still override them.

### The `--trigger-sequence` JSON schema

Each stage is a JSON object with these fields (all optional except
`value_a`):

```json
{
  "cmp_a":      0,           // 0..8 — compare mode A (default 0 = EQ)
  "cmp_b":      0,           // 0..8 — compare mode B
  "combine":    0,           // 0=A, 1=B, 2=A&B, 3=A|B (default 0)
  "next_state": 0,           // which stage to advance to (default 0)
  "is_final":   false,       // true on the final stage that fires the trigger
  "count":      1,           // advance after this many matches (default 1)
  "value_a":    "0x42",      // hex string or int
  "mask_a":     "0xFFFFFFFF",
  "value_b":    "0",
  "mask_b":     "0xFFFFFFFF"
}
```

`value_*` and `mask_*` accept Python int literals (decimal or `0x`
prefix).  See [chapter 05](05_ela_core.md) for the compare modes.

## EIO subcommands

### `eio-probe`

<!-- BEGIN GENERATED cli:eio-probe (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] eio-probe [--chain N] [--instance N] [--base-addr ADDR]`

| Option | Default | Description |
|---|---|---|
| `--chain N` | `3` | BSCANE2 USER chain |
| `--instance N` | — | Managed core slot on the selected chain |
| `--base-addr ADDR` | `0` | Register-bus mux offset for a shared-chain EIO (Gowin EIO_EN=1: 0x8000) |

<!-- END GENERATED cli:eio-probe -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t eio-probe
{
  "in_w": 8,
  "out_w": 8,
  "chain": 3
}
```

### `eio-read`

<!-- BEGIN GENERATED cli:eio-read (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] eio-read [--chain N] [--instance N] [--base-addr ADDR]`

| Option | Default | Description |
|---|---|---|
| `--chain N` | `3` | BSCANE2 USER chain |
| `--instance N` | — | Managed core slot on the selected chain |
| `--base-addr ADDR` | `0` | Register-bus mux offset for a shared-chain EIO (Gowin EIO_EN=1: 0x8000) |

<!-- END GENERATED cli:eio-read -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t eio-read
0xA7
```

Always reads `probe_in`.

### `eio-write`

<!-- BEGIN GENERATED cli:eio-write (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] eio-write [--chain N] [--instance N] [--base-addr ADDR] VALUE`

| Option | Default | Description |
|---|---|---|
| `--chain N` | `3` | BSCANE2 USER chain |
| `--instance N` | — | Managed core slot on the selected chain |
| `--base-addr ADDR` | `0` | Register-bus mux offset for a shared-chain EIO (Gowin EIO_EN=1: 0x8000) |
| `VALUE` | required | Output value (hex or decimal) |

<!-- END GENERATED cli:eio-write -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t eio-write 0x55
wrote 0x55
```

`VALUE` accepts decimal or `0x` hex.

All three EIO subcommands take `--chain N` to override
the BSCANE2 USER chain. For mixed-manager designs where EIO shares USER1,
also pass `--instance N` to select the EIO slot before each register access.
For a **shared-chain** EIO that is address-muxed onto another core's chain
(e.g. Gowin `EIO_EN=1` at offset `0x8000`), pass `--base-addr` instead:

```bash
fcapz --backend hw_server --tap xc7a100t eio-probe --chain 1 --instance 2
fcapz --backend hw_server --tap xc7a100t eio-write --chain 1 --instance 2 0x11
fcapz --backend hw_server --tap xc7a100t eio-read --chain 1 --instance 2

# Gowin shared-chain EIO (chain 1, mux offset 0x8000):
fcapz --backend openocd --tap GW1NR-9C.tap eio-read  --chain 1 --base-addr 0x8000
fcapz --backend openocd --tap GW1NR-9C.tap eio-write --chain 1 --base-addr 0x8000 0x15
```

## AXI subcommands

### `axi-read`

<!-- BEGIN GENERATED cli:axi-read (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] axi-read --addr ADDR [--chain N]`

| Option | Default | Description |
|---|---|---|
| `--addr ADDR` | required | AXI address (hex) |
| `--chain N` | `4` | BSCANE2 USER chain |

<!-- END GENERATED cli:axi-read -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-read --addr 0x40000000
0xDEADBEEF
```

### `axi-write`

<!-- BEGIN GENERATED cli:axi-write (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] axi-write --addr ADDR --data DATA [--wstrb W] [--chain N]`

| Option | Default | Description |
|---|---|---|
| `--addr ADDR` | required | AXI address (hex) |
| `--data DATA` | required | Write data (hex) |
| `--wstrb W` | `0xf` | Write strobe (hex, default 0xf) |
| `--chain N` | `4` | BSCANE2 USER chain |

<!-- END GENERATED cli:axi-write -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-write --addr 0x40000000 --data 0x12345678
wrote 0x12345678 -> 0x40000000 (resp=0)
```

Pass `--wstrb 0x3` to write only the low 2 bytes, etc.

### `axi-dump`

<!-- BEGIN GENERATED cli:axi-dump (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] axi-dump --addr ADDR --count N [--chain N] [--burst]`

| Option | Default | Description |
|---|---|---|
| `--addr ADDR` | required | Start address (hex) |
| `--count N` | required | Number of 32-bit words to read |
| `--chain N` | `4` | BSCANE2 USER chain |
| `--burst` | off | Use AXI4 burst transfers (count <= the bridge FIFO_DEPTH) |

<!-- END GENERATED cli:axi-dump -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-dump --addr 0x40000000 --count 16
0x40000000: 0x12345678
0x40000004: 0x00000001
...
```

`--burst` switches from auto-increment block read to AXI4 burst
read; the host refuses a count above the bridge's `FIFO_DEPTH` with a
clear error.

### `axi-fill`

<!-- BEGIN GENERATED cli:axi-fill (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] axi-fill --addr ADDR --count N --pattern P [--chain N] [--burst]`

| Option | Default | Description |
|---|---|---|
| `--addr ADDR` | required | Start address (hex) |
| `--count N` | required | Number of 32-bit words to fill |
| `--pattern P` | required | Fill pattern (hex) |
| `--chain N` | `4` | BSCANE2 USER chain |
| `--burst` | off | Use AXI4 burst transfers |

<!-- END GENERATED cli:axi-fill -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-fill --addr 0x40000000 --count 64 --pattern 0xAA55AA55
filled 64 words @ 0x40000000
```

### `axi-load`

<!-- BEGIN GENERATED cli:axi-load (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] axi-load --addr ADDR --file FILE [--chain N] [--burst]`

| Option | Default | Description |
|---|---|---|
| `--addr ADDR` | required | Start address (hex) |
| `--file FILE` | required | Binary file to load (little-endian 32-bit words; a partial last word is zero-padded) |
| `--chain N` | `4` | BSCANE2 USER chain |
| `--burst` | off | Use AXI4 burst transfers |

<!-- END GENERATED cli:axi-load -->

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-load --addr 0x10000000 --file firmware.bin
loaded 4096 words @ 0x10000000
```

## UART subcommands

### `uart-send`

<!-- BEGIN GENERATED cli:uart-send (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] uart-send [--chain N] (--data TEXT | --file FILE | --hex HEX)`

| Option | Default | Description |
|---|---|---|
| `--chain N` | `4` | BSCANE2 USER chain |
| `--data TEXT` | — | String data to send |
| `--file FILE` | — | Binary file to send |
| `--hex HEX` | — | Hex-encoded bytes to send (e.g. 48656C6C6F) |

Exactly one of `--data`, `--file`, `--hex` is required.

<!-- END GENERATED cli:uart-send -->

Send a string, hex bytes, or a file:

```bash
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      uart-send --data "Hello, world!\n"

fcapz --backend hw_server --port 3121 --tap xc7a100t \
      uart-send --hex 48656C6C6F0A

fcapz --backend hw_server --port 3121 --tap xc7a100t \
      uart-send --file firmware.bin
```

### `uart-recv`

<!-- BEGIN GENERATED cli:uart-recv (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] uart-recv [--chain N] [--count N] [--timeout SEC] [--line]`

| Option | Default | Description |
|---|---|---|
| `--chain N` | `4` | BSCANE2 USER chain |
| `--count N` | `0` | Number of bytes to receive (0=all available) |
| `--timeout SEC` | `1.0` | Idle timeout in seconds |
| `--line` | off | Receive until newline |

<!-- END GENERATED cli:uart-recv -->

```bash
# Get up to 64 bytes with 2 s idle timeout
fcapz uart-recv --count 64 --timeout 2.0

# Get one line (stops at \n)
fcapz uart-recv --line

# Get whatever is currently in the FIFO and exit
fcapz uart-recv --count 0 --timeout 0.1
```

### `uart-monitor`

<!-- BEGIN GENERATED cli:uart-monitor (tools/gen_docs.py from fcapz/cli.py; do not edit) -->

Usage: `fcapz [global options] uart-monitor [--chain N] [--timeout SEC]`

| Option | Default | Description |
|---|---|---|
| `--chain N` | `4` | BSCANE2 USER chain |
| `--timeout SEC` | `0.5` | Per-poll timeout in seconds |

<!-- END GENERATED cli:uart-monitor -->

```bash
fcapz uart-monitor               # runs forever, Ctrl+C to stop
```

## Argument validation

All numeric arguments are validated at parse time:

- `--port`: must be 1..65535
- `--timeout`: must be > 0
- `--count` (axi-dump, axi-fill): must be > 0
- `--count` (uart-recv): must be >= 0
- `--trigger-delay`: must be 0..65535
- `--probes`: width > 0, lsb >= 0, no overlap
- `--trigger-sequence`: malformed JSON / missing file → `ArgumentTypeError`
- `--tap` and `--program`: validated against the TCL-safe regex
  inside the transport (rejects quotes, brackets, semicolons)

If validation fails you get an `argparse: error: ...` message and
exit code 2 — no surprises.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Runtime error (TimeoutError, RuntimeError, etc.) — message on stderr |
| `2` | Argument parse error |

## What's next

- [Chapter 09 — Python API](09_python_api.md): the same operations
  programmatically.
- [Chapter 11 — JSON-RPC server](11_rpc_server.md): the same
  operations from another language / process.
- [Chapter 12 — Desktop GUI](12_gui.md): the same operations
  point-and-click.
