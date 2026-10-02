# 14 — Transports

> **Goal**: understand the `Transport` abstract base class, the built-in
> backends (AMD/Xilinx hw_server, OpenOCD, and Quartus USB-Blaster), the named
> `IR_TABLE_*` presets that handle the AMD/Xilinx per-family IR opcode
> differences, the readiness wait that catches "FPGA isn't programmed yet",
> the TCL injection prevention, and how to add a new transport.
>
> **Audience**: anyone whose default transport doesn't work for
> their board, or anyone porting fcapz to a new JTAG cable / TCF /
> raw USB stack.

## What a transport is

A `Transport` is the host-side bridge between the Python `fcapz`
controllers and the JTAG cable hardware.  It provides four
operations the controllers care about:

| Operation | Purpose |
|---|---|
| `connect()` | Open the cable, validate FPGA readiness if a bitfile was passed |
| `select_chain(chain)` | Switch to a BSCANE2 USER chain (`1`..`4`) — internally this picks an IR opcode from the `ir_table` |
| `read_reg(addr)` / `write_reg(addr, value)` | 49-bit DR scan against the chain's register interface |
| `raw_dr_scan(bits, width)` / `raw_dr_scan_batch(...)` | Raw DR shift for the burst engines (32-, 72-, 256-bit) |

For EJTAG-AXI on Arty / `hw_server`, the batched form matters in
practice: isolated USER4 raw scans were observed to return zeros on
that setup even though the bridge was alive, while the same USER4
traffic worked when kept inside one `raw_dr_scan_batch()` / single
XSDB `jtag sequence`.

There is also `read_block(addr, words)` for batched register reads,
which by default falls back to a loop of `read_reg()` but can be
overridden by transports that want to batch round-trips for
throughput (the AMD/Xilinx hw_server transport does this for the ELA
burst readback). Default AMD/Xilinx builds keep those wide burst scans on
the selected ELA control chain; pass `single_chain_burst=False` only
for legacy two-chain builds.

The 256-bit burst DR packs **whole samples** per scan, so `read_block`
uses it only when a sample fits one 32-bit word (`SAMPLE_W <= 32`); it
gates on the selected core's `SAMPLE_W`, read fresh, so it is correct when
a session hops between an ELA and a monitor. Wider cores — notably the AXI
monitor (`SAMPLE_W=160`) — are read with `read_sample_block()`, one sample
per scan, which returns each sample as 32-bit words for `capture()` to
reassemble. A slot without burst wiring, or a sample burst that fails to
run, is read through the 32-bit-word DATA window instead; a burst that
runs but returns the wrong number of samples raises. Feeding a
wide core's 32-bit *word* count to the burst engine would build a
multi-hundred-KB single-line TCL scan sequence that xsdb never
completes — a hard readback hang, not a throughput issue.

Every burst readback is a single pass.  The `BURST_PTR` write, the
staging-fill idle (real TCKs) and every burst scan run as one JTAG
transaction, so nothing else can reach the chain mid-burst, and the first
scan, which primes the staging register, is discarded.  Burst data carries
no framing or CRC: the reference Arty and DE25-Nano hardware tests capture a
free-running counter and require adjacent samples to increment by +1 when
decimation is disabled.  Designs with critical readback requirements should
check a similar application-level invariant.

An **optional** extension method `read_timestamp_block(addr, words,
timestamp_width)` accelerates timestamp readback via the burst path.
The host checks for it via `getattr(transport,
"read_timestamp_block", None)` and falls back to `read_block` when
absent.  See "Timestamp burst readback" below.

The full ABC contract is documented in
[`specs/transport_api.md`](specs/transport_api.md) — it's the
spec you implement against if you're adding a new backend.

## The built-in transports

### `XilinxHwServerTransport`

Drives Vivado's `hw_server` daemon via `xsdb` (the AMD/Xilinx system
debugger console).  This is the **default for AMD/Xilinx boards** and
the only path that has been hardware-validated on Arty A7-100T.

```python
from fcapz import XilinxHwServerTransport

t = XilinxHwServerTransport(
    host="127.0.0.1",
    port=3121,
    fpga_name="xc7a100t",                 # JTAG target name
    bitfile="my_design.bit",              # optional, programs FPGA on connect
    ir_table=None,                        # default = 7-series IR codes
    ready_probe_addr=0x0000,              # ELA VERSION register
    ready_probe_timeout=2.0,              # seconds
)
t.connect()
```

What `connect()` does:

1. Spawns `xsdb` as a subprocess (uses `xsdb_path` if set,
   otherwise looks on `PATH`).
2. Sends `connect -url tcp:HOST:PORT` to xsdb's stdin.
3. If `bitfile` is set: waits for a live FPGA target (step 4), selects the
   **configuration target** (see below), then sends `fpga -file {BITFILE}`
   and `after <ms>` (GUI default 200 ms post-program delay).
4. Waits for a JTAG target matching `fpga_name`, selects it with
   `jtag targets -set -filter`, and confirms it with one IDCODE scan.
   When the previous xsdb client exits, hw_server releases every cable and
   reopens and rescans them all for the next client, which can take several
   seconds with a few boards attached. During that window `jtag targets`
   lists nothing, or lists the target from the stale cable while every scan
   fails with "JTAG node is not accessible". Both are waited out until
   `target_wait_timeout` (default 10 s; a live target is selected in
   milliseconds). A select that fails while the target is still listed (two
   boards matching `fpga_name`, say) and any other scan error are raised at
   once. The timeout bounds this polling, not a single xsdb command: as
   everywhere on this transport, a command hw_server never answers is
   waited for.
5. **Runs the readiness wait** — see "Readiness wait" below.

The connection persists until you call `close()` or the
subprocess dies.

#### Two target namespaces, and why programming picks a different one

xsdb has two separate target trees, and configuration uses the second:

* `jtag targets` — the **JTAG scan chain**. Nodes are named for the part
  (`xc7a100t`, `xck26`, `xczu7`). This is what step 4 selects, for the raw
  IR/DR scans the analyzer does.
* `targets` — the **debug targets**. On a standalone FPGA there is one node
  per device, named for the part. On Zynq UltraScale+ MPSoC (Kria xck24 /
  xck26, ZCU+ xczu\*) there is **no node named for the part at all**: the tree
  is `PS TAP` → `PMU`/`PL`, plus `PSU` → `RPU`/`APU`, and `fpga` works from
  `PS TAP`.

So the configuration target is chosen by trying, in order:

```tcl
targets -set -filter {jtag_device_name =~ "PART" && name =~ "PS TAP"}
targets -set -filter {jtag_device_name =~ "PART" && name =~ "PART"}
```

Both are scoped by `jtag_device_name`, because several boards can be attached
at once and each MPSoC contributes its own node named `PS TAP` — the part name
is the only thing that distinguishes them. If neither matches, `connect()`
raises rather than programming nothing.

Verified on a chain carrying an Arty A7 (`xc7a100t`), a KV260 (`xck26`) and a
ZCU-class board (`xczu7`) simultaneously, xsdb 2025.2.

> **Fixed in this release.** Programming previously filtered `targets` by the
> part name, which matches nothing on MPSoC. xsdb printed an error, the
> transport discarded it, `fpga -file` loaded nothing, and the session then ran
> against whatever configuration was already in the FPGA — wrong data with no
> warning. Both commands now run with error checking (see below).

#### xsdb error checking

xsdb reports a failure by *printing* a message and carrying on; a piped session
has no per-command exit status. `_send()` therefore returns the printed text
and lets the caller interpret it, which suits the read commands whose output is
parsed anyway. Commands whose only failure signal *is* that message —
`targets -set`, `fpga -file` — are sent with `check=True`, which wraps them in
a Tcl `catch` and raises `RuntimeError` instead of letting the failure pass.

**Why `connect()` can feel slow:** `fpga -file` dominates (bitstream size
and USB/JTAG speed — often tens of seconds). After that, the readiness
poll issues one full JTAG register read per interval until `VERSION` is
non-zero (GUI default timeout 60 s, interval 20 ms). Spawning `xsdb` and
`connect -url tcp:…` is usually sub-second on a warm `hw_server`.

**Profiling (no cProfile required):** set environment variable
`FCAPZ_LOG_CONNECT_TIMING=1` before starting the GUI or CLI. Logger
`fcapz.transport.hw_server` then emits phase timings for
`XilinxHwServerTransport.connect()` (spawn, TCP attach, programming,
JTAG target select, ready poll). The GUI connect worker also logs
`transport_build`, `transport.connect`, and `probe()` durations on
logger `fcapz.gui.connect`.

#### Timestamp burst readback

`XilinxHwServerTransport` implements the optional
`read_timestamp_block(addr, words, timestamp_width)` method, which
reads timestamp data from the ELA's timestamp BRAM using the same
256-bit DR burst path used for sample data. Default AMD/Xilinx transports
use the selected ELA control chain; `single_chain_burst=False` selects
legacy DATA_CHAIN readout.

The key difference from a sample burst:

Note: current hardware uses the same priming-scan behavior for timestamp
bursts as for sample bursts; the host discards that first 256-bit scan.

- `BURST_PTR` is written with `bit[31]=1` to switch the staging mux
  to the timestamp BRAM instead of the sample BRAM.
- `words_per_scan = 256 // timestamp_width` (e.g. 8 words per scan
  for 32-bit timestamps).

The host `Analyzer._read_timestamps()` uses this path automatically
when the transport supports it, avoiding the much slower per-word
USER1 readback that previously caused duplicate/backward timestamp
bugs (BUG-004).

```python
# Called internally by Analyzer.capture() — you don't call this directly
timestamps = transport.read_timestamp_block(0x1100, capture_len, 32)
```

### `OpenOcdTransport`

Talks to OpenOCD's TCL listener (default port `6666`) via raw
`irscan` / `drscan` commands.  Cross-platform, vendor-neutral,
**slower than hw_server** because OpenOCD's batched-scan support
is limited.

```python
from fcapz import OpenOcdTransport

t = OpenOcdTransport(
    host="127.0.0.1",
    port=6666,
    tap="xc7a100t.tap",
    ir_table=None,
)
t.connect()
```

OpenOCD must already be running with a board config that has the
right TAP defined:

```bash
openocd -f examples/arty_a7/arty_a7.cfg
```

The transport opens a TCP socket to OpenOCD's TCL listener,
sends commands like `irscan xc7a100t.tap 0x02 ; drscan xc7a100t.tap 49 0x...`,
parses the hex responses.  No subprocess, no Vivado required.

OpenOCD does **not** program the FPGA from this transport — you do
that separately with `pld load`, an `init`-time script, or your own
`openocd -c "...; init; pld load 0 my.bit; exit"`.

#### Tap auto-detect

The tap name must match a tap defined in the running OpenOCD config.  Pass
`tap="auto"` (or leave it empty) and `connect()` resolves it to the first name
OpenOCD reports from `jtag names` — handy for single-FPGA chains where you don't
want to hard-code the name.  The helper `fcapz.transport.list_openocd_taps()`
returns that list; the GUI's **Scan** button uses it to populate the TAP field
for the OpenOCD backend.

#### Gowin over OpenOCD

Gowin boards use this transport with `ir_table=OpenOcdTransport.IR_TABLE_GOWIN`
(ER1/ER2 → chains 1/2).  The CLI auto-selects it for `--tap GW...`; in code,
pass it explicitly.  The ELA sits on chain 1; a shared-chain EIO (`EIO_EN=1`) is
reached on chain 1 at base offset `0x8000`
(`EioController(t, chain=1, base_addr=0x8000)`).  See the
[BRS-100-GW1NR9 example](../examples/brs_100_gw1nr9/README.md).

### `QuartusStpTransport`

Talks to Quartus Prime's `quartus_stp -s` Tcl shell and uses Quartus
virtual JTAG commands to reach Intel/Altera `sld_virtual_jtag` instances.
This is the built-in path for USB-Blaster / USB-Blaster II cables.

```python
from fcapz.transport import QuartusStpTransport

t = QuartusStpTransport(
    hardware_name="DE25-Nano [USB-1]",     # optional when one cable is present
    device_name=None,                      # None / auto selects first @1 device
    quartus_stp_path=None,                 # or full path to quartus_stp.exe
)
t.connect()
```

The Intel RTL wrapper sets:

```verilog
.sld_auto_instance_index ("NO"),
.sld_instance_index      (CHAIN),
.sld_ir_width            (1)
```

That means host-side `select_chain()` uses the RTL `CHAIN` parameter,
not a zero-based Python index.  The default fcapz Intel control path
is instance 1; EIO and other subsidiary cores use their own wrapper
parameters.

`QuartusStpTransport` keeps a persistent `quartus_stp` process, frames
each Tcl request with sentinels, and uses `device_lock` around composite
operations so a read transaction is not interleaved with SignalTap,
Programmer, or another Quartus Tcl session.  `read_reg()`,
`read_block()`, and `raw_dr_scan_batch()` are emitted as single locked
Tcl blocks where atomicity matters.

Auto device selection opens the first Quartus device whose name starts
with `@1`.  If the FPGA is at another JTAG position, pass the exact
Quartus device name as `device_name` / CLI `--tap`.  The CLI and GUI
treat `auto`, an empty tap, `xc7a100t`, and `xc7a100t.tap` as auto for
USB-Blaster so older AMD/Xilinx defaults do not get passed to Quartus as
literal device names.

## IR table presets

Different AMD/Xilinx families use different IR opcodes for the BSCANE2
USER chains.  The `ir_table` constructor parameter is a dict
mapping `chain_index` (1..4) → `ir_opcode` (e.g. `0x02`).  The
controllers call `transport.select_chain(N)` and the transport
looks up the opcode in the table.

To save users from looking up the codes, both AMD/Xilinx-style transports expose
named class-level presets:

```python
XilinxHwServerTransport.IR_TABLE_XILINX7
# {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

XilinxHwServerTransport.IR_TABLE_XILINX_ULTRASCALE
# {1: 0x24, 2: 0x25, 3: 0x26, 4: 0x27}

XilinxHwServerTransport.IR_TABLE_US        # alias for IR_TABLE_XILINX_ULTRASCALE
```

`OpenOcdTransport` exposes the same three constants under the same
names — both AMD/Xilinx-style transports use identical preset shapes so you can
swap one for the other without changing the IR table.

### When to use which

| Family | Preset | Extra constructor args |
|---|---|---|
| AMD/Xilinx Artix-7, Kintex-7, Virtex-7, Spartan-7, Zynq-7000 | `IR_TABLE_XILINX7` (default; you can omit `ir_table=`) | none |
| AMD/Xilinx Kintex / Virtex UltraScale (standalone) | `IR_TABLE_XILINX_ULTRASCALE` (alias `IR_TABLE_US`) | none |
| AMD/Xilinx Artix / Kintex / Virtex UltraScale+ (standalone) | `IR_TABLE_XILINX_ULTRASCALE` | none |
| **Zynq UltraScale+ MPSoC** (Kria xck24/xck26, ZCU+ xczu*) | none | `use_register_ir=True` (see below) |
| Lattice ECP5, Intel | n/a — those vendors use different TAP primitives, not BSCANE2; the transport's `ir_table` doesn't apply.  See "Adding a new transport" below. | n/a |
| Gowin GW-family | `OpenOcdTransport.IR_TABLE_GOWIN` | Auto-selected by the CLI for `--tap GW...`; current RTL wrappers still require one shared `GW_JTAG` primitive per design |

On MPSoC the ARM DAP's 1-bit BYPASS register is in series with the PL
TAP's DR, so every DR scan is one shift longer than the fcapz frame.
`use_register_ir=True` lets xsdb route the IR and pad the DR; the host
then shifts plain 49-bit / 256-bit frames.  The raw-opcode path
(`IR_TABLE_XILINX_ZYNQUS` with `ir_length`, `dr_extra_bits=1` and
`dr_extra_position`) is kept for experiments only — raw opcodes don't
reach the PL BSCANE2 through xsdb on MPSoC (see below), and which end of
the scan the DAP bit sits on is not established (next section).

CLI users don't have to pick manually: `fcapz --tap xck26 …` auto-selects
`use_register_ir=True` for MPSoC, and `fcapz --tap xcku040 …`
auto-selects `IR_TABLE_XILINX_ULTRASCALE`.
See `host/fcapz/cli.py::_chain_shape_kwargs`.

### Zynq UltraScale+ MPSoC — how the JTAG chain works with xsdb

Zynq UltraScale+ MPSoC parts (Kria xck24/xck26, ZCU+ xczu*) have a
**multi-TAP boundary scan chain**: the PL TAP and the ARM DAP.
The ARM DAP (4-bit IR) handles Arm CoreSight debug; the PL TAP
(12-bit IR) handles FPGA configuration and BSCANE2 USER instructions.
When both TAPs are in the chain, every IR shift is 16 bits and every
DR shift carries an extra 1-bit BYPASS register from the DAP.

The physical order of the two TAPs is not established.  Earlier notes
here gave `TDI -> ARM DAP -> PL TAP -> TDO`, based on a KV260 TDO trace
taken through xsdb; OpenOCD's `xilinx_zynqmp.cfg` declares the DAP
nearest TDO, which implies the opposite.  It doesn't matter for
`use_register_ir=True`, where xsdb pads the DR.  It does matter for the
RTL: either way the PL sees one extra shift clock per DR scan, which is
why `jtag_pipe_iface` decodes the last 49 bits of a scan instead of
requiring exactly 49 shifts.

#### Why raw hex opcodes don't work on MPSoC

On 7-series and standalone UltraScale(+), fcapz shifts USER opcodes as
raw hex values (`irshift -hex 6 02` for USER1).  On MPSoC, xsdb
presents the PL TAP as a "virtual" target at the device level — and
its internal chain-handling intercepts the `irshift -hex` path in ways
that prevent USER2/3/4 from being reached:

- `irshift -hex 12 024` (the opcode that empirically hits USER1 at the
  PL-target level) **does** return ELA data.  But `0x025`, `0x026`,
  `0x027` (attempted USER2/3/4) all collapse to USER1's DR content.
- The BSDL-authoritative opcodes (`USER1=0x902`, `USER2=0x903`,
  `USER3=0x922`, `USER4=0x923` from the xczu5ev BSDL) return all
  zeros (BYPASS) at the PL-target level — xsdb's virtual-target
  translation doesn't forward them.

This was confirmed by an exhaustive sweep of candidate opcodes on
xck26 / KV260 with Vivado 2025.2 / xsdb 2025.2.

#### The fix: `-register userN` named-IR mode

xsdb's `irshift` command accepts a `-register <name>` option (documented
in UG1725) that selects a JTAG instruction by name instead of by hex
opcode.  In this mode, xsdb handles the multi-TAP IR routing and DR
BYPASS padding internally — the host shifts standard 49-bit / 256-bit
DRs with no extra bits.

Verified on xck26 / KV260:

| `-register` name | DR width | Result |
|---|---|---|
| `user1` | 49 | ELA VERSION `0x0003_4C41` ("LA") |
| `user2` | 256 | Real staging-buffer data (burst engine) |
| `user3` | 49 | Reachable (EIO can be instantiated here) |
| `user4` | 49 | Reachable |

All four USER chains work.  Reads, writes, and 256-bit burst scans
are confirmed end-to-end.

That verification predates the single-chain pipe interface
(`jtag_pipe_iface`): it ran on the register interface on USER1 with
bursts on USER2.  xsdb hides the DAP's BYPASS bit from the host, but
the PL still sees it as one extra shift clock on every DR scan (a
49-bit command is 50 TCKs in Shift-DR).  The pipe interface therefore
decodes a command from the last 49 bits of any scan that is at least
49 and fewer than `BURST_W` shifts long, instead of requiring exactly
49 (see the changelog).  Single-chain and multi-core
wrappers have not yet been re-verified on MPSoC hardware.

#### Register access sequence

Every DR scan the transport issues ends in an explicit `-state DRUPDATE`:
register reads and writes, block-read and pipelined-read scans, the burst
`BURST_PTR` write and burst scans, and the raw scans of the bridges.  Each
scan that carries a command for the core to act on before the next capture
is followed by idle TCKs with `state IDLE <n>`.  The explicit UPDATE-DR is
required on MPSoC in `-register` mode, where the `-state IDLE` shortcut
doesn't reliably fire the UPDATE-DR event through the named-register path.
The idle must be `state IDLE <n>`, which clocks `n` TCKs; xsdb's
`delay <usec>` only waits and clocks nothing, so it gives the TCK-domain
core no time to accept the command or stage the response.  Writes in
`-register` mode get 100 idle TCKs instead of 20:

```
# Write (MPSoC, -register mode):
$seq irshift -state IRUPDATE -register user1
$seq drshift -state DRUPDATE -bits 49 $write_frame
$seq state IDLE 100
# [run; delete]
```

The transport handles this automatically when `use_register_ir=True`.

#### Usage

```python
# Programmatic:
t = XilinxHwServerTransport(
    fpga_name="xck26",
    use_register_ir=True,   # the only MPSoC-specific arg
)

# CLI (auto-detected for xck* / xczu* part names):
fcapz --tap xck26 probe
```

No `ir_table`, `ir_length`, or `dr_extra_bits` needed — xsdb handles
everything when using the named-register path.

#### Troubleshooting on MPSoC

If reads return wrong values or writes don't land:

1. **Confirm `hw_server` is running with `bscan-switch-user-mask 0xF`:**
   ```bash
   hw_server -e "set bscan-switch-user-mask 0xF"
   ```
   Verify after connect: `configparams bscan-switch-user-mask` should
   print `15`.

2. **Confirm no other debug logic collides with your BSCANE2 chains.**
   Some design flows can insert extra JTAG-facing debug logic on a USER
   scan chain. If another block is using the same chain as fpgacapZero,
   move it to an unused chain:
   ```tcl
   set_property C_USER_SCAN_CHAIN 3 [get_debug_cores dbg_hub]
   ```

3. **Use `FCAPZ_LOG_XSDB=1`** to trace every TCL command and xsdb
   response for wire-level debugging.

4. **Verify BSCANE2 instances exist in the bitstream** for the chains
   you intend to use:
   ```tcl
   get_cells -hier -filter {REF_NAME == BSCANE2}
   ```

### Chain-shape parameters (advanced / non-xsdb transports)

The `use_register_ir` mode above is the recommended path for MPSoC
through xsdb.  For cable-root JTAG access, non-xsdb transports, or
other multi-TAP scenarios where named-register mode isn't available,
the transport also supports explicit chain-shape parameters:

| Arg | Default | Meaning |
|---|---|---|
| `ir_length` | `6` | Total IR bits to shift on every `irshift`. |
| `dr_extra_bits` | `0` | Extra zero-padded bits for BYPASS registers of other TAPs. |
| `dr_extra_position` | `"tdo"` | Which end of the captured token holds the extra bits: `"tdo"` or `"tdi"`. |

These are overridden to defaults when `use_register_ir=True` (xsdb
handles chain-walking internally in that mode).

### Example: UltraScale board

```python
from fcapz import XilinxHwServerTransport, Analyzer

t = XilinxHwServerTransport(
    port=3121,
    fpga_name="xcku040",                                    # not xc7a100t
    bitfile="my_ultrascale_design.bit",
    ir_table=XilinxHwServerTransport.IR_TABLE_US,           # ← UltraScale codes
)
a = Analyzer(t)
a.connect()
print(a.probe())
```

The desktop GUI ([chapter 12](12_gui.md)) has an "IR table" dropdown
in the Connection panel that selects between the two presets, so
GUI users never have to remember the codes.

## Readiness wait

`XilinxHwServerTransport.connect()` does **not** return until the
FPGA is alive and responding on the JTAG chain.  After programming
the bitstream, the host polls the configured `ready_probe_addr`
register every 50 ms until it returns a non-zero value or
`ready_probe_timeout` seconds elapse.

```python
t = XilinxHwServerTransport(
    port=3121,
    fpga_name="xc7a100t",
    bitfile="my_design.bit",
    ready_probe_addr=0x0000,        # ELA VERSION register (default)
    ready_probe_timeout=2.0,        # 2 seconds is plenty for any 7-series
)
t.connect()
# At this point the FPGA is provably alive — Analyzer.probe() will succeed
```

If the timeout elapses, the transport raises:

```
ConnectionError: FPGA did not become ready within 2.0s after program()
(probe addr=0x0000, last_value=0x00000000, attempts=40).
Either the bitstream failed to load, the wrong fpga_name was selected,
or the probe register address is wrong for this design.
```

Three things this catches:

1. **Bitstream failed to load** — Vivado's `fpga -file` reported
   success but the FPGA didn't actually configure.  Sometimes
   happens with corrupted bitfiles or USB issues.
2. **Wrong fpga_name** — you typed `xc7a100t` but your board is
   `xc7a35t` and Vivado bound the wrong target on the chain.
3. **Wrong probe address** — your design doesn't have an ELA core
   on USER1 at register `0x0000`.  Pass
   `ready_probe_addr=None` to skip the wait if you genuinely
   don't have an ELA in your bitstream (e.g. you only have the
   AXI bridge).

The wait was added in v0.2.0 and eliminated a class of "first read
returns garbage" race conditions where tests would `connect()`,
immediately read the ELA's identity, and get back zeros from a
not-yet-configured FPGA.  Now `connect()` either succeeds with a
provably-alive FPGA or fails loudly.

## TCL injection prevention

`XilinxHwServerTransport` interpolates `fpga_name` and `bitfile`
into TCL commands sent to xsdb.  Since these values come from
user input (CLI flags, RPC `connect` requests, GUI form fields),
there's a real injection risk if a malicious value contains TCL
metacharacters.

The transport validates both fields against safe-character regexes
at construction time and at every `program()` call:

```python
_TCL_NAME_RE = re.compile(r'^[A-Za-z0-9._:/*\- ]+$')
_TCL_PATH_RE = re.compile(r'^[A-Za-z0-9._:/*\-\\ ]+$')
```

`_TCL_NAME_RE` is the strict pattern for `fpga_name` (used inside
a double-quoted TCL string in the `targets -set -filter` command).
`_TCL_PATH_RE` is the slightly more permissive pattern for
`bitfile` (which is wrapped in TCL braces in `fpga -file {...}`,
where backslash is fine but `{`/`}`/`"` are not — Windows paths
need backslash, hence the split).

If either pattern fails to match, the transport raises
`ValueError: bitfile path contains unsafe characters for TCL`
**before** sending anything to xsdb.  This means a CLI invocation
like:

```bash
fcapz --tap 'xc7a100t"; exec rm -rf /' probe
```

dies at the host with a clear error instead of executing arbitrary
TCL inside Vivado's xsdb session.

The unit tests in
[`tests/test_transport.py`](../tests/test_transport.py) cover
quotes, brackets, semicolons, backslashes, and a positive test for
real Windows paths.

## Adding a new transport

To support a new JTAG cable / protocol / vendor, you implement the
`Transport` ABC.  The contract is in
[`specs/transport_api.md`](specs/transport_api.md) — required
methods, expected error types, what `select_chain` should do.

Skeleton:

```python
from fcapz.transport import Transport

class MyTransport(Transport):
    DEFAULT_IR_TABLE: dict[int, int] = {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

    def __init__(self, ...):
        self.ir_table = dict(self.DEFAULT_IR_TABLE)
        self._active_chain = 1

    def connect(self) -> None:
        # open your cable, optionally program the FPGA, optionally do
        # the readiness wait
        ...

    def close(self) -> None:
        ...

    def select_chain(self, chain: int) -> None:
        if chain not in self.ir_table:
            raise ValueError(f"chain {chain} not in ir_table {self.ir_table}")
        self._active_chain = chain

    def raw_dr_scan(self, bits: int, width: int, *, chain: int | None = None) -> int:
        # do an irscan + drscan via your cable, return the captured value
        ...

    def read_reg(self, addr: int) -> int:
        # 49-bit DR frame: bits[31:0]=data, [47:32]=addr, [48]=rnw=0 for read
        # Send the frame, drain idle TCKs, send another frame, read back
        ...

    def write_reg(self, addr: int, value: int) -> None:
        ...

    # Optional override for throughput:
    def raw_dr_scan_batch(self, scans: list[tuple[int, int]], *, chain=None) -> list[int]:
        # default falls back to a loop of raw_dr_scan; override if your
        # cable supports batching multiple DR scans in one round trip
        return [self.raw_dr_scan(b, w, chain=chain) for b, w in scans]
```

Once that's done, your transport drops into any controller:

```python
t = MyTransport(...)
t.connect()
analyzer = Analyzer(t)
analyzer.connect()
```

No other code changes.  The whole point of the ABC is that the
controllers don't care which cable they're talking through.

### Existing transport reference implementations

Look at [`host/fcapz/transport.py`](../host/fcapz/transport.py)
for the full implementations of:

- `OpenOcdTransport` — TCP socket to OpenOCD's TCL listener;
  ~150 LOC; the simplest reference impl
- `QuartusStpTransport` â€” subprocess + `quartus_stp` Tcl framing
  for Intel/Altera USB-Blaster access to `sld_virtual_jtag`
  instances via `device_virtual_ir_shift` / `device_virtual_dr_shift`
- `XilinxHwServerTransport` — subprocess + xsdb stdin/stdout
  framing with a `<<XSDB_DONE>>` sentinel; ~400 LOC; richer
  because it handles programming, readiness, error parsing
- `VendorStubTransport` — placeholder for future TCF / direct USB
  backends

The OpenOCD impl is the easier starting point if you're writing
something new.

### Common transport pitfalls

1. **Forgetting to drain idle TCKs between read scans.**  The
   ELA's `jtag_reg_iface` has a CDC pipeline that needs ~20 idle
   TCKs to settle between back-to-back reads.  See the
   `READ_IDLE_CYCLES = 20` constant in the existing transports.
2. **Not handling the 49-bit DR frame properly.**  The frame is
   `{rnw_bit, addr[15:0], data[31:0]}` (49 bits total, LSB first).
   Don't confuse the order; don't drop the rnw bit.
3. **Sharing state between controllers without `select_chain`.**
   The ELA controller needs its configured chain (default 1), EIO
   usually needs chain 3, and AXI/UART usually need chain 4.
   If your transport doesn't switch the IR opcode
   between calls, you'll silently scan against the wrong chain
   and read garbage.  The cooperating controller pattern only works
   if your `select_chain` actually emits a new `irscan`.
4. **Not raising the right exceptions.**  The host stack and the
   tests assume:
   - `RuntimeError` if called before `connect()` or after `close()`
   - `ConnectionError` if the transport endpoint dies mid-call
   - `ValueError` for an unknown chain index
   - `OSError` / `TimeoutError` for cable-level errors
5. **Forgetting that `tap` and `fpga_name` are user input.**  If
   your transport interpolates them into shell or TCL commands,
   apply the same TCL-safe regex pattern as
   `XilinxHwServerTransport`, or sanitize differently for your
   target language.

## Latency and batching (illustrative)

Example wall-clock numbers on Arty A7-100T, FT2232H onboard JTAG,
TCK ~30 MHz, via `XilinxHwServerTransport`.  These are **per-call
or wall-clock examples**, not a spec — your adapter and host load
will differ.

| Operation | hw_server |
|---|---|
| `read_reg()` (single 32-bit) | ~1.5 ms / call |
| `read_block()` (16 words via `raw_dr_scan_batch`) | ~3 ms total |
| `burst_read()` (16 beats AXI) | uses batched DR where available |
| `Analyzer.capture()` of 1024 samples (256-bit burst) | ~50 ms |

**OpenOCD:** hardware-validated on Gowin BRS-100-GW1NR9, but not yet
benchmarked with the same detail as the Arty A7 `hw_server` path. Expect it
to be slower than `hw_server` per scan because OpenOCD's TCL listener has
limited batched-scan support, but the delta is not documented until somebody
benchmarks it.

**Quartus USB-Blaster:** hardware probe/capture is validated on the
DE25-Nano (Agilex 5); see [`specs/transport_api.md`](specs/transport_api.md) for
the tested Quartus edition.  Latency depends heavily on Quartus Tcl
startup and USB-Blaster speed; `QuartusStpTransport` keeps one
`quartus_stp` process alive and batches composite reads under one
`device_lock` to avoid avoidable round trips.

The bottleneck on the measured path is JTAG round-trip latency through
the tooling, not the RTL.  The fastest measured AMD/Xilinx path today is
hw_server with batched scans.  A future raw-TCF transport (bypassing
xsdb) could cut per-scan overhead further on AMD/Xilinx boards.  See the
TODO roadmap.

## What's next

- [Chapter 09 — Python API](09_python_api.md): how the
  controllers use the transport
- [Chapter 12 — Desktop GUI](12_gui.md): the IR-table dropdown
  and how the GUI threads transport calls
- [Chapter 16 — Versioning](16_versioning_and_release.md): the
  per-core identity magic and how the readiness wait depends on
  it
- [`specs/transport_api.md`](specs/transport_api.md): the formal
  ABC contract you implement against
