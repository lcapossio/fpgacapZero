# 10 — CLI reference

> **Goal**: complete reference for the `fcapz` command-line tool.
> Every subcommand, every flag, with copy-pasteable examples.
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

| Flag | Default | Description |
|---|---|---|
| `--backend {openocd,hw_server,usb_blaster}` | `openocd` | JTAG transport to use |
| `--host HOST` | `127.0.0.1` | Transport host |
| `--port PORT` | `6666` (openocd) or `3121` (hw_server) | Transport TCP port; ignored by `usb_blaster` |
| `--tap TAP` | `xc7a100t.tap` | OpenOCD TAP name, hw_server FPGA target name, or Quartus device name (`auto`, empty, or the default Xilinx value auto-selects the first `@1` device for `usb_blaster`) |
| `--hardware HARDWARE` | auto | Quartus hardware name for `usb_blaster`; required if more than one Quartus JTAG cable is connected |
| `--quartus-stp PATH` | PATH lookup | Path to `quartus_stp` for `usb_blaster` |
| `--program BITFILE` | none | Program the FPGA with this bitfile before running the subcommand (hw_server only) |

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
name starts with `@1`. The default Xilinx TAP values (`xc7a100t` and
`xc7a100t.tap`) are also treated as auto for USB-Blaster so old saved GUI/CLI
settings do not get passed to Quartus as literal device names. If the FPGA is
elsewhere in the JTAG chain, pass the exact Quartus device name with `--tap`.

## Subcommands at a glance

| Subcommand | What it does |
|---|---|
| `probe` | Read core identity registers (version, sample width, depth, features) |
| `arm` | Arm capture without configuring (advanced) |
| `configure` | Write capture configuration without arming |
| `capture` | Configure + arm + capture + export to file |
| `eio-probe` | Read EIO core identity and widths |
| `eio-read` | Read EIO input bus |
| `eio-write` | Write EIO output bus |
| `axi-read` | Single AXI read via JTAG-to-AXI bridge |
| `axi-write` | Single AXI write |
| `axi-dump` | Read a block of AXI words (auto-inc or burst) |
| `axi-fill` | Fill a block of AXI memory with a pattern |
| `axi-load` | Load a binary file into AXI memory |
| `uart-send` | Send data to UART TX via JTAG-to-UART bridge |
| `uart-recv` | Receive data from UART RX |
| `uart-monitor` | Continuous UART receive (Ctrl+C to stop) |

## `probe`

Read the core's identity, version, and FEATURES registers:

```bash
fcapz --backend hw_server --port 3121 --tap xc7a100t probe
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

## `capture` and `configure`

`capture` is the headline subcommand.  `configure` is the same
without arming or reading back — useful for one-shot pre-arm
setup.  Both take the same options.

### Required for `capture`

| Flag | Description |
|---|---|
| `--out FILE` | Output file path (extension determines format unless `--format` is set) |

### Capture/configure options (in alphabetical-ish order)

| Flag | Default | Description |
|---|---|---|
| `--pretrigger N` | `8` | Samples to keep before trigger |
| `--posttrigger N` | `16` | Samples to capture after trigger |
| `--trigger-mode MODE` | `value_match` | `value_match`, `edge_detect`, or `both` |
| `--trigger-value V` | `0` | Trigger compare value (decimal or `0x` hex) |
| `--trigger-mask M` | `0xFF` | Bit mask (hex) |
| `--trigger-delay N` | `0` | Post-trigger delay in sample-clock cycles (0..65535).  Shifts the committed trigger sample N cycles after the trigger event. |
| `--sample-width N` | `8` | Bits per sample (must match hardware) |
| `--depth N` | `1024` | Buffer depth (must match hardware) |
| `--sample-clock-hz N` | `100000000` | Sample clock for VCD timescale |
| `--channel N` | `0` | Probe channel mux selector |
| `--probe-sel N` | `0` | Runtime probe mux slice index |
| `--probes SPEC` | none | Probe definitions: `name:width:lsb,name:width:lsb,...` |
| `--probe-file FILE.prob` | none | Load probe definitions, sample width, and optional sample clock from a `.prob` sidecar |
| `--decimation N` | `0` | Capture every N+1 cycles (requires `DECIM_EN=1`) |
| `--ext-trigger-mode MODE` | `disabled` | `disabled`, `or`, `and` (requires `EXT_TRIG_EN=1`) |
| `--stor-qual-mode N` | `0` | 0=disabled, 1=store-when-match, 2=store-when-no-match |
| `--stor-qual-value V` | `0` | Storage qualification value |
| `--stor-qual-mask M` | `0` | Storage qualification mask |
| `--trigger-sequence JSON` | none | Multi-stage sequencer config: JSON file path or inline JSON array |

### `capture`-only options

| Flag | Default | Description |
|---|---|---|
| `--out FILE` | required | Output file path |
| `--format FMT` | `json` | `json`, `csv`, or `vcd` |
| `--timeout SEC` | `10.0` | Wait this long for the trigger to fire |
| `--summarize` | off | Print LLM-friendly capture summary to stdout after the capture |

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

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t eio-probe
{
  "in_w": 8,
  "out_w": 8,
  "chain": 3
}
```

### `eio-read`

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t eio-read
0xA7
```

Always reads `probe_in`.

### `eio-write VALUE`

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t eio-write 0x55
wrote 0x55
```

`VALUE` accepts decimal or `0x` hex.

All three EIO subcommands take `--chain N` (default 3) to override
the BSCANE2 USER chain.

## AXI subcommands

All five AXI subcommands take `--chain N` (default 4).

### `axi-read --addr ADDR`

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-read --addr 0x40000000
0xDEADBEEF
```

### `axi-write --addr ADDR --data DATA [--wstrb W]`

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-write --addr 0x40000000 --data 0x12345678
wrote 0x12345678 -> 0x40000000 (resp=0)
```

`--wstrb` defaults to `0xF` (all 4 bytes).  Pass `0x3` to write only
the low 2 bytes, etc.

### `axi-dump --addr ADDR --count N [--burst]`

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-dump --addr 0x40000000 --count 16
0x40000000: 0x12345678
0x40000004: 0x00000001
...
```

`--burst` switches from auto-increment block read to AXI4 burst
read.  Subject to `count <= FIFO_DEPTH` (the host enforces this
and prints a clear error).

### `axi-fill --addr ADDR --count N --pattern P [--burst]`

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-fill --addr 0x40000000 --count 64 --pattern 0xAA55AA55
filled 64 words @ 0x40000000
```

### `axi-load --addr ADDR --file FILE [--burst]`

```bash
$ fcapz --backend hw_server --port 3121 --tap xc7a100t \
        axi-load --addr 0x10000000 --file firmware.bin
loaded 4096 words @ 0x10000000
```

The file is read as little-endian 32-bit words.  Trailing partial
words are zero-padded.

## UART subcommands

All three UART subcommands take `--chain N` (default 4).

### `uart-send`

Sources of data (mutually exclusive, exactly one required):

```bash
fcapz --backend hw_server --port 3121 --tap xc7a100t \
      uart-send --data "Hello, world!\n"

fcapz --backend hw_server --port 3121 --tap xc7a100t \
      uart-send --hex 48656C6C6F0A

fcapz --backend hw_server --port 3121 --tap xc7a100t \
      uart-send --file firmware.bin
```

### `uart-recv [--count N] [--timeout SEC] [--line]`

```bash
# Get up to 64 bytes with 2 s idle timeout
fcapz uart-recv --count 64 --timeout 2.0

# Get one line (stops at \n)
fcapz uart-recv --line

# Get whatever is currently in the FIFO and exit
fcapz uart-recv --count 0 --timeout 0.1
```

### `uart-monitor [--timeout SEC]`

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
