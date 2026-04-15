# 14 — Transports

> **Goal**: understand the `Transport` abstract base class, the two
> built-in backends (Xilinx hw_server and OpenOCD), the named
> `IR_TABLE_*` presets that handle the per-family IR opcode
> differences, the readiness wait that catches "FPGA isn't
> programmed yet", the TCL injection prevention, and how to add a
> new transport for a vendor we don't ship today.
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

There is also `read_block(addr, words)` for batched register reads,
which by default falls back to a loop of `read_reg()` but can be
overridden by transports that want to batch round-trips for
throughput (the Xilinx hw_server transport does this for the ELA
burst readback).

An **optional** extension method `read_timestamp_block(addr, words,
timestamp_width)` accelerates timestamp readback via the USER2 burst
path.  The host checks for it via `getattr(transport,
"read_timestamp_block", None)` and falls back to `read_block` when
absent.  See "Timestamp burst readback" below.

The full ABC contract is documented in
[`specs/transport_api.md`](specs/transport_api.md) — it's the
spec you implement against if you're adding a new backend.

## The two built-in transports

### `XilinxHwServerTransport`

Drives Vivado's `hw_server` daemon via `xsdb` (the Xilinx system
debugger console).  This is the **default for Xilinx boards** and
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
3. If `bitfile` is set: sends `targets -set -filter {name =~ "FPGA_NAME"}`
   then `fpga -file {BITFILE}` then `after <ms>` (GUI default 200 ms post-program delay).
4. Sends another `jtag targets -set -filter` to lock onto the
   actual FPGA target (not just any device on the chain).
5. **Runs the readiness wait** — see "Readiness wait" below.

The connection persists until you call `close()` or the
subprocess dies.

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
USER2 256-bit DR burst path used for sample data.

The key difference from a sample burst:

- `BURST_PTR` is written with `bit[31]=1` to switch the staging mux
  to the timestamp BRAM instead of the sample BRAM.
- No priming scan is needed — the staging buffer is already filled
  from the first 256-bit capture, so the first scan returns valid
  data directly.
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

## IR table presets

Different Xilinx families use different IR opcodes for the BSCANE2
USER chains.  The `ir_table` constructor parameter is a dict
mapping `chain_index` (1..4) → `ir_opcode` (e.g. `0x02`).  The
controllers call `transport.select_chain(N)` and the transport
looks up the opcode in the table.

To save users from looking up the codes, both transports expose
named class-level presets:

```python
XilinxHwServerTransport.IR_TABLE_XILINX7
# {1: 0x02, 2: 0x03, 3: 0x22, 4: 0x23}

XilinxHwServerTransport.IR_TABLE_XILINX_ULTRASCALE
# {1: 0x24, 2: 0x25, 3: 0x26, 4: 0x27}

XilinxHwServerTransport.IR_TABLE_US        # alias for IR_TABLE_XILINX_ULTRASCALE
```

`OpenOcdTransport` exposes the same three constants under the same
names — both transports use identical preset shapes so you can
swap one for the other without changing the IR table.

### When to use which

| Family | Preset | Extra constructor args |
|---|---|---|
| Xilinx Artix-7, Kintex-7, Virtex-7, Spartan-7, Zynq-7000 | `IR_TABLE_XILINX7` (default; you can omit `ir_table=`) | none |
| Xilinx Kintex / Virtex UltraScale (standalone) | `IR_TABLE_XILINX_ULTRASCALE` (alias `IR_TABLE_US`) | none |
| Xilinx Artix / Kintex / Virtex UltraScale+ (standalone) | `IR_TABLE_XILINX_ULTRASCALE` | none |
| **Zynq UltraScale+ MPSoC** (Kria xck24/xck26, ZCU+ xczu*) | `IR_TABLE_XILINX_ZYNQUS` | `ir_length=12`, `dr_extra_bits=1`, `dr_extra_position="tdi"` |
| Lattice ECP5, Intel, Gowin | n/a — those vendors use different TAP primitives, not BSCANE2; the transport's `ir_table` doesn't apply.  See "Adding a new transport" below. | n/a |

The MPSoC row is not optional padding — the ARM DAP's 1-bit BYPASS
register sits in series with the PL TAP's DR on the TDO side, so every
DR scan carries one extra bit that `dr_extra_bits=1` accounts for.
Without it the host's address field lands one bit position off and
every non-zero register address reads the wrong register (see BUG-006
in `no_commit/BUGS.md` for the wire-level decode that pinned this
down).

CLI users don't have to pick manually: `fcapz --tap xck26 …` auto-selects
the full MPSoC kwargs (`IR_TABLE_XILINX_ZYNQUS` + `ir_length=12` +
`dr_extra_bits=1` + `dr_extra_position="tdi"`), and
`fcapz --tap xcku040 …` auto-selects `IR_TABLE_XILINX_ULTRASCALE`.
See `host/fcapz/cli.py::_chain_shape_kwargs`.

### Chain-shape parameters (multi-TAP boundary scan)

The default `XilinxHwServerTransport` shifts a single-device 6-bit IR
and a 49-bit DR — exactly what 7-series and standalone UltraScale(+)
parts present.  When the JTAG chain has additional TAPs in series with
the PL TAP (most notably the ARM DAP on Zynq UltraScale+ MPSoC), every
IR and DR scan must account for those extra TAPs' IR bits and BYPASS
bits.  Three constructor arguments handle this without forking the
transport:

| Arg | Default | Meaning |
|---|---|---|
| `ir_length` | `6` | IR bits the host shifts on every `irshift`.  When xsdb auto-walks part of the chain (e.g. targeting the PL TAP on MPSoC), this is just the PL's IR width; xsdb pads the rest of the chain's IR with BYPASS itself. |
| `dr_extra_bits` | `0` | Extra zero-padded bits the host adds to every DR scan for BYPASS registers of other TAPs in the chain.  xsdb does **not** pad DR — the host must. |
| `dr_extra_position` | `"tdo"` | Where the extra bits sit in the captured token: `"tdo"` if the bypass TAP is closer to TDO than the fcapz BSCANE2 (BYPASS bits appear at the start of the captured string), `"tdi"` if closer to TDI.  On Zynq US+ MPSoC the ARM DAP is on the TDI side of the PL TAP, so the right choice is `"tdi"`. |

The `ir_table` value for each chain is shifted **as-is** for `ir_length`
bits.  Example for Zynq US+ MPSoC (xck26 / KV260), using xsdb at the
PL-TAP target level where xsdb handles the DAP's IR portion and we
handle the DAP's 1-bit DR BYPASS:

```python
t = XilinxHwServerTransport(
    fpga_name="xck26",
    ir_table=XilinxHwServerTransport.IR_TABLE_XILINX_ZYNQUS,
    ir_length=12,
    dr_extra_bits=1,
    dr_extra_position="tdi",
)
```

That's also exactly what the CLI auto-selects for `xck*` / `xczu*` part
names, so `fcapz --tap xck26 …` Just Works.

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
   The ELA controller needs chain 1, EIO needs chain 3, AXI/UART
   need chain 4.  If your transport doesn't switch the IR opcode
   between calls, you'll silently scan against the wrong chain
   and read garbage.  The cooperating controller pattern (each
   controller restores chain 1 on exit) only works if your
   `select_chain` actually emits a new `irscan`.
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
| `Analyzer.capture()` of 1024 samples (USER2 burst) | ~50 ms |

**OpenOCD:** no measured numbers yet — `OpenOcdTransport` is not yet
hardware-validated on Arty A7 (pending a first run with FT2232; see
[`specs/transport_api.md`](specs/transport_api.md)).  Expect it to be
slower than `hw_server` per scan because OpenOCD's TCL listener has
limited batched-scan support, but the delta is not documented until
somebody benchmarks it.

The bottleneck on the measured path is JTAG round-trip latency through
the tooling, not the RTL.  The fastest path today is hw_server with
batched scans.  A future raw-TCF transport (bypassing xsdb) could cut
per-scan overhead further on Xilinx boards.  See the TODO roadmap.

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
