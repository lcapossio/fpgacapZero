# 11 — JSON-RPC server

> **Goal**: drive fpgacapZero from another language or process.
> By the end of this chapter you can spawn the RPC server, send
> JSON commands over its stdin, parse the JSON responses on its
> stdout, and integrate fcapz into a non-Python test harness or
> CI pipeline.
>
> **Audience**: anyone integrating fcapz with a Tcl test bench, a
> Rust test runner, a Node.js dashboard, or any environment that
> can read/write a child process's stdio.

## Why RPC and not the Python API directly

The Python API is the **fastest** way to drive fcapz from Python.
The RPC server exists for everything else:

- A test runner written in Tcl, Go, Rust, Node, etc.
- A long-running test harness that wants to keep one xsdb session
  alive across many independent test scripts.
- A CI pipeline that wants to share one fcapz process between many
  short-lived test workers.
- A custom GUI or dashboard that wants language flexibility.
- An LLM agent that calls fcapz as a tool: spawn once, send JSON,
  read JSON, repeat.

If you are calling from Python, just `import fcapz` and use the
controllers directly — there is no benefit to going through RPC.

## Protocol

**Transport**: line-delimited JSON over the server process's
stdin and stdout.  One JSON object per line on each side.  No
framing, no length prefix, no message ID — the protocol is
strictly request/response, in order.

**Request**:
```json
{"cmd":"connect","backend":"hw_server","port":3121,"tap":"xc7a100t"}
```

**Response on success**:
```json
{"ok":true,"schema_version":"1.1"}
```

**Response on failure**:
```json
{"ok":false,"schema_version":"1.1","error":"...","type":"RuntimeError","trace":"..."}
```

Every response carries `"schema_version"` so a stale client can
detect when it's talking to a newer server and update its
parser.  The current schema version is `"1.1"`.

## Spawning the server

```bash
python -m fcapz.rpc
```

The server starts immediately, reads JSON lines from stdin, and
writes JSON responses to stdout.  It runs forever until either
stdin closes (EOF) or it receives a fatal exception.

From a host language, spawn it as a child process and grab its
stdin/stdout pipes.  Examples below.

### Python (just for testing the protocol)

```python
import json, subprocess

p = subprocess.Popen(
    ["python", "-m", "fcapz.rpc"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    text=True, bufsize=1,
)

def call(cmd, **kwargs):
    req = {"cmd": cmd, **kwargs}
    p.stdin.write(json.dumps(req) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())

print(call("connect", backend="hw_server", port=3121, tap="xc7a100t"))
print(call("probe"))
print(call("close"))
p.stdin.close()
p.wait()
```

### Tcl

```tcl
set rpc [open "|python -m fcapz.rpc" r+]
fconfigure $rpc -buffering line

proc rpc_call {cmd args} {
    global rpc
    set req [dict create cmd $cmd]
    foreach {k v} $args { dict set req $k $v }
    puts $rpc [json::dict2json $req]
    return [json::json2dict [gets $rpc]]
}

rpc_call connect backend hw_server port 3121 tap xc7a100t
rpc_call probe
rpc_call close
close $rpc
```

### Node.js

```javascript
const { spawn } = require('child_process');
const readline = require('readline');

const proc = spawn('python', ['-m', 'fcapz.rpc']);
const rl = readline.createInterface({ input: proc.stdout });

function call(cmd, extra = {}) {
  proc.stdin.write(JSON.stringify({ cmd, ...extra }) + '\n');
  return new Promise(resolve => rl.once('line', l => resolve(JSON.parse(l))));
}

(async () => {
  console.log(await call('connect', { backend: 'hw_server', port: 3121, tap: 'xc7a100t' }));
  console.log(await call('probe'));
  console.log(await call('close'));
  proc.stdin.end();
})();
```

## Command reference

### Session management

#### `connect`

Open a transport, programs the FPGA if `program` is set, runs the
readiness wait.

```json
{
  "cmd": "connect",
  "backend": "hw_server",     // or "openocd"
  "host": "127.0.0.1",
  "port": 3121,
  "tap": "xc7a100t",          // hw_server: FPGA target name; openocd: TAP name
  "program": "my_design.bit"  // optional, hw_server only
}
```

Response: `{"ok": true, "schema_version": "1.1"}`

#### `close`

Releases the transport.

```json
{"cmd": "close"}
```

### ELA (Analyzer)

#### `probe`

Read core identity, version, FEATURES.

```json
{"cmd": "probe"}
```

Response:
```json
{
  "ok": true,
  "schema_version": "1.1",
  "probe": {
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
}
```

#### `configure`

Write the trigger / pre-post / decimation / etc. registers.  All
fields optional except `pretrigger`, `posttrigger`, `trigger_value`.

```json
{
  "cmd": "configure",
  "pretrigger": 8,
  "posttrigger": 16,
  "trigger_mode": "value_match",       // or "edge_detect" or "both"
  "trigger_value": 66,
  "trigger_mask": 255,
  "sample_width": 8,
  "depth": 1024,
  "sample_clock_hz": 100000000,
  "channel": 0,
  "decimation": 0,
  "ext_trigger_mode": 0,
  "stor_qual_mode": 0,
  "stor_qual_value": 0,
  "stor_qual_mask": 0,
  "trigger_delay": 0,
  "probes": [
    {"name": "counter", "width": 8, "lsb": 0}
  ]
}
```

`probes` can also be a string in the CLI `name:width:lsb,...` form.
Use `probe_file` with a `.prob` sidecar path to load the same information
from disk; `probes` and `probe_file` are mutually exclusive.

#### `arm`

```json
{"cmd": "arm"}
```

#### `capture`

Configure + arm + capture in one call, returning the result.

```json
{
  "cmd": "capture",
  "pretrigger": 8,
  "posttrigger": 16,
  "trigger_value": 66,
  "trigger_mask": 255,
  "probe_file": "design.prob",
  "format": "json",         // or "csv" or "vcd"
  "summarize": true,        // optional, returns LLM-friendly summary
  "timeout": 10.0
}
```

Response (format = "json"):
```json
{
  "ok": true,
  "schema_version": "1.1",
  "format": "json",
  "overflow": false,
  "sample_count": 25,
  "channel": 0,
  "result": { ... full export_json() output ... },
  "summary": { ... if summarize=true ... }
}
```

For `format=csv` or `format=vcd`, the response has `"content": "..."`
with the file body as a string instead of `result`.

### EIO

#### `eio_connect`

```json
{
  "cmd": "eio_connect",
  "backend": "hw_server",
  "port": 3121,
  "tap": "xc7a100t",
  "chain": 3
}
```

Response: `{"ok": true, "schema_version": "1.1", "in_w": 8, "out_w": 8, "chain": 3}`

#### `eio_close`

```json
{"cmd": "eio_close"}
```

#### `eio_read`

```json
{"cmd": "eio_read"}
```

Response: `{"ok": true, "schema_version": "1.1", "value": 167}`

#### `eio_write`

```json
{"cmd": "eio_write", "value": 85}
```

### EJTAG-AXI

#### `axi_connect`

```json
{
  "cmd": "axi_connect",
  "backend": "hw_server",
  "port": 3121,
  "tap": "xc7a100t",
  "chain": 4
}
```

Response includes the cached `fifo_depth`:
```json
{
  "ok": true,
  "schema_version": "1.1",
  "bridge_id": 19032,
  "core_id": 19032,
  "legacy_id": false,
  "legacy_raw_id": null,
  "version": 281176,
  "version_major": 0,
  "version_minor": 4,
  "addr_w": 32,
  "data_w": 32,
  "fifo_depth": 16
}
```

#### `axi_close`

```json
{"cmd": "axi_close"}
```

#### `axi_read`

```json
{"cmd": "axi_read", "addr": "0x40000000"}
```

`addr` accepts a hex string (`"0x..."`) or a decimal int.

Response: `{"ok": true, "schema_version": "1.1", "value": "0xDEADBEEF"}`

#### `axi_write`

```json
{
  "cmd": "axi_write",
  "addr": "0x40000000",
  "data": "0x12345678",
  "wstrb": "0xF"
}
```

Response: `{"ok": true, "schema_version": "1.1", "resp": 0}`

`resp` is the AXI response code: 0 = OKAY, 2 = SLVERR, 3 = DECERR.
A non-OKAY response raises `AXIError` server-side, which becomes
`{"ok": false, "error": "...", "type": "AXIError"}`.

#### `axi_dump`

```json
{
  "cmd": "axi_dump",
  "addr": "0x40000000",
  "count": 16,
  "burst": false              // false = auto-inc, true = AXI4 burst
}
```

Response:
```json
{
  "ok": true,
  "schema_version": "1.1",
  "words": ["0x12345678", "0x00000001", "0x00000002", ...]
}
```

#### `axi_write_block`

```json
{
  "cmd": "axi_write_block",
  "addr": "0x40000000",
  "data": ["0xAA", "0xBB", "0xCC", "0xDD"],
  "burst": false
}
```

Response: `{"ok": true, "schema_version": "1.1", "count": 4}`

### EJTAG-UART

#### `uart_connect`

```json
{
  "cmd": "uart_connect",
  "backend": "hw_server",
  "port": 3121,
  "tap": "xc7a100t",
  "chain": 4
}
```

#### `uart_close`

```json
{"cmd": "uart_close"}
```

#### `uart_send`

`data` is a **base64-encoded** byte string (so binary payloads
survive the JSON line):

```python
import base64
print(base64.b64encode(b"Hello\n").decode())
# 'SGVsbG8K'
```

```json
{"cmd": "uart_send", "data": "SGVsbG8K"}
```

Response: `{"ok": true, "schema_version": "1.1", "bytes_sent": 6}`

#### `uart_recv`

```json
{"cmd": "uart_recv", "count": 64, "timeout": 1.0}
```

Response (`data` is base64-encoded):
```json
{
  "ok": true,
  "schema_version": "1.1",
  "data": "SGVsbG8gd29ybGQK",
  "bytes_received": 12
}
```

#### `uart_status`

```json
{"cmd": "uart_status"}
```

Response: returns the same dict as `EjtagUartController.status()`:
```json
{
  "ok": true,
  "schema_version": "1.1",
  "rx_ready": true,
  "tx_full": false,
  "rx_overflow": false,
  "frame_error": false,
  "tx_free": 250
}
```

## Schema versioning

Every response carries `"schema_version"`.  The current version is
`"1.1"`.  When the schema changes in a backwards-incompatible way
(adding required fields, removing keys, changing semantics) the
major number bumps; backwards-compatible additions bump the minor.

A robust client should:

1. Read `schema_version` on the first response after `connect`.
2. Compare against the version it was written for.
3. If the major doesn't match, abort or fall back gracefully.

## Error handling

On any exception, the response shape is:

```json
{
  "ok": false,
  "schema_version": "1.1",
  "error": "burst_read: count 17 exceeds bridge FIFO_DEPTH (16); rebuild bitstream with larger FIFO_DEPTH",
  "type": "ValueError",
  "trace": "Traceback (most recent call last):\n  File ..."
}
```

`type` is the Python exception class name; `trace` is the last
frame of the traceback.  Both are useful for surfacing meaningful
errors back to the calling language.

Common error types you should expect:

- `RuntimeError` — `"not connected"`, `"ELA core identity check failed"`,
  `"xsdb not found"`, `"xsdb: no bit string in output"`
- `ConnectionError` — `"FPGA did not become ready within 2.0s"`,
  `"OpenOCD closed the connection"`
- `ValueError` — argument validation, FIFO_DEPTH overflow, sequencer
  bound violations, probe overlaps
- `TimeoutError` — capture didn't complete within timeout
- `AXIError` — AXI slave returned SLVERR or DECERR

## Worked example: a Tcl test harness

```tcl
package require Tcl 8.6
package require json
package require json::write

set rpc [open "|python -m fcapz.rpc" r+]
fconfigure $rpc -buffering line

proc rpc_call {req} {
    global rpc
    puts $rpc $req
    flush $rpc
    set line [gets $rpc]
    return [json::json2dict $line]
}

# Connect + probe
set resp [rpc_call {{"cmd":"connect","backend":"hw_server","port":3121,"tap":"xc7a100t"}}]
if {![dict get $resp ok]} { error "connect failed: [dict get $resp error]" }

set probe [dict get [rpc_call {{"cmd":"probe"}}] probe]
puts "ELA: v[dict get $probe version_major].[dict get $probe version_minor], depth=[dict get $probe depth]"

# Capture
set cap [rpc_call {{"cmd":"capture","pretrigger":8,"posttrigger":16,"trigger_value":66,"trigger_mask":255,"format":"json"}}]
if {[dict get $cap ok]} {
    puts "got [dict get $cap sample_count] samples"
} else {
    puts "capture failed: [dict get $cap error]"
}

# Close
rpc_call {{"cmd":"close"}}
close $rpc
```

## Limitations

- **One client per server**.  The protocol is strictly
  request/response and stateful.  Don't try to multiplex multiple
  clients onto one fcapz.rpc process — spawn one per client.
- **No streaming**.  `uart_recv` returns a complete buffer; for
  continuous monitoring use `uart_recv` in a loop.  A future
  schema version may add streaming subscriptions.
- **No cancellation mid-call**.  If you send `capture` and the
  trigger never fires, the only way to recover is to wait for the
  timeout or kill the child process.
- **stderr is not parsed**.  Anything the server writes to stderr
  (Python warnings, traceback context) is informational only —
  the client should not depend on it.

## What's next

- [Chapter 09 — Python API](09_python_api.md): the same operations
  in the same process.
- [Chapter 10 — CLI reference](10_cli_reference.md): the same
  operations one-shot from a shell.
- [Chapter 12 — Desktop GUI](12_gui.md): the same operations
  point-and-click.
