# 20 - MCP server

This chapter explains the `fcapz-mcp` server: what it exposes, how to run it,
which operations are gated for safety, and how agents should read large results
without flooding their own context.

The MCP server is a thin, stateful wrapper around the fpgacapZero JSON-RPC lab
controls from [chapter 11](11_rpc_server.md). It is meant for coding agents and
other MCP clients that need to drive an FPGA debug session through tools and
resources instead of a human CLI.

If you are wiring an agent to this server, skim the [Tools](#tools) and
[Resources](#resources) tables first, then come back to the safety flags before
enabling any write-like action. Human operators can read the chapter top to
bottom.

## Install

Install the MCP optional dependency:

```bash
pip install fpgacapzero[mcp]
```

For development from a checkout:

```bash
pip install -e ".[mcp]"
```

The console entry point is:

```bash
fcapz-mcp --help
```

## Transport Model

`fcapz-mcp` currently runs MCP over stdio. One server process owns one hardware
session and should be connected to one MCP client. If you need two agents or two
clients at the same time, run two separate `fcapz-mcp` processes.

The server creates one `FcapzMcpSession`, which can hold ELA, EIO, AXI, and UART
connections. On stdio disconnect or normal server exit, the session attempts to
close all active hardware connections.

If close operations fail during shutdown, the server writes one compact JSON
line to stderr:

```json
{"event":"shutdown_errors","errors":[{"step":"close","type":"RuntimeError","message":"..."}]}
```

Set `FCAPZ_MCP_DEBUG_SHUTDOWN=1` to include tracebacks in that JSON payload.
Accepted true values are `1`, `true`, `yes`, and `on` (case-insensitive).

If backend cancellation fails after a tool timeout, the server writes a compact
JSON line to stderr:

```json
{"event":"rpc_cancel_error","errors":[{"step":"cancel_active","cmd":"connect","type":"RuntimeError","message":"..."}]}
```

## MCP Client Configuration

Example stdio client configuration:

```json
{
  "mcpServers": {
    "fpgacapzero": {
      "command": "fcapz-mcp",
      "args": ["--read-only"]
    }
  }
}
```

Use `--read-only` for diagnostic sessions where the agent should not arm
captures or drive target-side state. Probe/read/status tools remain available.

MCP tool calls are JSON objects containing a tool `name` and `arguments`.
For example:

```json
{"name":"fcapz_status","arguments":{}}
```

## Safety Flags

Write-like operations are disabled by default. `--read-only` is broader: it
also disables capture-side actions that change ELA state.

| Flag | Effect |
| --- | --- |
| `--read-only` | Disables `fcapz_configure`, `fcapz_arm`, `fcapz_capture`, `fcapz_capture_wait`, `fcapz_disarm`, and all write/send/program enable flags. |
| `--allow-eio-write` | `fcapz_eio_write` |
| `--allow-axi-write` | `fcapz_axi_write`, `fcapz_axi_write_block` |
| `--allow-uart-send` | `fcapz_uart_send` |
| `--allow-program --bitfile-root DIR` | `fcapz_connect(program=...)` for `.bit` files under `DIR` |
| `--probe-root DIR` | Capture config `probe_file` may read probe maps under `DIR` |
| `--allow-host HOST` | A backend may connect to `HOST` as well as loopback (repeatable) |

`--read-only` cannot be combined with any write/program enable flag.

Two fields reach past the JTAG cable and are therefore confined by default:

- **`probe_file`** names a path the server opens. Without `--probe-root` it is
  rejected outright, because it would otherwise be an arbitrary file read on
  the machine running `fcapz-mcp`. Pass probe definitions inline via `probes`
  when you do not want to open a directory to the agent.
- **`host`** is handed to a network client (hw_server or OpenOCD), so without
  `--allow-host` only `127.0.0.1`, `localhost`, and `::1` are accepted —
  otherwise an agent could point the server at any such daemon on the
  network.

Both appear in `fcapz_status` under `capabilities` (`probe_root`,
`allowed_hosts`) so an agent can see the policy rather than discover it by
being refused.

`probe_file` is read once, by the MCP layer, and the probe map it contains
is sent to the RPC layer inline as `probes` — the path itself never travels.
So there is no second open to race: what was checked against `--probe-root` is
what gets loaded. Values the file carries (`sample_width`, `sample_clock_hz`)
remain defaults the caller's own `config` overrides, as before.

Programming is intentionally `hw_server`-only in the MCP layer.

If `program` is passed while programming is disabled, the server reports the
permission error before backend-specific validation so agents see the global
safety policy first.

## Backends And Connection Fields

The live RPC layer supports:

| Backend | Target fields | Optional fields |
| --- | --- | --- |
| `hw_server` | `host`, `port`, `tap` | `program`, `single_chain_burst` defaults to `true` |
| `openocd` | `host`, `port`, `tap` | - |
| `usb_blaster` | `hardware`, `quartus_stp` | - |

Backend-irrelevant fields are rejected instead of being silently forwarded.
`hw_server` and `openocd` default `host` to `127.0.0.1` when omitted.
`usb_blaster` (Intel/Altera via Quartus) has no host concept, so `host`,
`port`, and `tap` are rejected for it — even an explicit `host="127.0.0.1"`.
Any other backend name is rejected up front with `unknown backend: <name>`.

A caller-supplied `quartus_stp` names a host executable that the transport
spawns, so it is gated behind `--allow-program` — the same opt-in as
programming a bitstream — and rejected otherwise (including under
`--read-only`). Omit it to use the server's configured/`PATH` toolchain. The
`hardware` cable selector is a plain string and needs no gate.

The MCP session enforces a 30 second RPC response timeout by default; override
it with `--rpc-timeout SEC`. For wait-bearing commands (`fcapz_capture`,
`fcapz_capture_wait`, `fcapz_uart_recv`) the watchdog deadline is extended to
the caller's own `timeout` *plus* a full `--rpc-timeout` window of readback
headroom — so neither a long trigger wait nor a slow deep-capture readback
trips it. The caller's `timeout` itself is capped at 300 s (the RPC layer's
ceiling) and rejected above that rather than silently clamped. For all other
commands the plain `--rpc-timeout` window applies.

Every hardware command runs on a single long-lived **owner thread**. The JTAG
transport takes one command at a time, and the RPC call plus the session-state
write that follows it run together on that thread as one indivisible step. A
second caller arriving mid-command is refused with a `busy` error naming the
command in flight, rather than queued behind a capture that may run for
minutes. `fcapz_status` reports `session_state` (`ready` / `busy` /
`poisoned`) alongside `rpc_busy` and `active_rpc_cmd`.

If the watchdog fires, what happens depends on the transport:

- **No cancellation hook** (the usual case) — the call may simply be a slow
  readback finishing late, so the grace window is allowed to elapse and a
  completed result is returned rather than discarded. A slow-but-successful
  capture is not thrown away.
- **Cancellation hook present** — the transport is aborted and given the grace
  window to unwind. The board session is torn down; reconnect before retrying.

A command still running after the grace window is **abandoned**, and the
session becomes `poisoned`: further hardware commands are refused. This is not
merely a lock being held. When the abandoned command finally returns, its
result is *not* committed — the RPC layer may have connected, closed, or
captured in the meantime, so the only safe assumption is that nothing is where
the wrapper left it. The owner tears the board session down for real, clears
all wrapper state, and only then returns to `ready`. Watch `session_state` and
reconnect once it reports `ready`; a restart is needed only if it never does.

`--rpc-cancel-grace SEC` controls both how long a late command may still
deliver its result and how long the MCP layer waits for a cancelled transport
to unwind before abandoning it. It must be greater than zero.
Transport construction is still best-effort: if a backend blocks before a
transport object exists, cancellation cannot nudge that backend directly and the
same still-running worker guard applies.

## Tools

### Session and ELA

| Tool | Requires | Purpose |
| --- | --- | --- |
| `fcapz_status` | always available | Return session state, safety capabilities, MCP server version, and RPC schema version. |
| `fcapz_connect` | none for plain connect; `--allow-program` if `program=` or a caller-supplied `quartus_stp=` is set | Connect to an ELA core. `chain` selects the JTAG USER chain (omit to autodetect). |
| `fcapz_close` | always available | Close the **whole board session** — the ELA plus any EIO/AXI/UART controller. Idempotent, and runs even when only a side subsystem is open. |
| `fcapz_probe` | connected ELA | Read ELA identity, dimensions, and feature registers. |
| `fcapz_list_cores` | connected ELA | List debug cores on the board (type, JTAG `chain`, identity) so an agent can pick the right chain for side connects. |
| `fcapz_configure` | capture* | Configure the connected ELA without arming. |
| `fcapz_arm` | capture* | Arm the connected ELA using the current hardware configuration. |
| `fcapz_capture` | capture* | Configure, arm, capture, and cache the full capture payload. Returns summary metadata only. |
| `fcapz_capture_wait` | capture* | Read out an already-armed capture (from `fcapz_configure` + `fcapz_arm`) without reconfiguring or re-arming. Returns `{triggered: false, still_armed: true}` (not an error) if the trigger has not fired yet. |
| `fcapz_capture_status` | capture* | Poll an armed ELA without transferring samples (waiting-for-trigger vs. triggered). |
| `fcapz_disarm` | capture* | Soft-reset the capture FSM to idle, discarding any in-flight arm. |
| `fcapz_get_last_capture` | always available | Return the cached full capture payload for clients without resource support. Defaults to a 1 MiB guard. |
| `fcapz_get_capture_samples` | always available | Page the cached capture's samples as whole records, with named fields from the probe map. See [Reading a Capture](#reading-a-capture). |
| `fcapz_axi_transactions` | always available | Decoded AXI4-Lite transactions of the cached capture — paged, filterable by anomaly or read/write. See [AXI Transactions](#axi-transactions). |
| `fcapz_get_last_capture_chunk` | always available | Return a bounded JSON text chunk of the cached capture payload. |
| `fcapz_drop_last_capture` | always available | Drop the cached full capture payload and report whether one existed. |

`capture*` tools are enabled by default and blocked by `--read-only`.

**Disabled tools are not advertised.** A tool whose capability is off is left
out of the tool list entirely, rather than offered and then refused: the agent
would otherwise plan around it, spend a call discovering the refusal, and pay
for its schema in every request. So the advertised surface tracks the flags —
22 tools under `--read-only`, 27 by default, 31 with every write enabled. The
session-level permission checks remain as the actual enforcement; the gating
is about what the agent is told exists.

Two capture flows are available. `fcapz_capture` is the one-shot path: it
configures, arms, and reads out in a single call, re-arming every time. For a
long wait on a real hardware event, use the manual flow instead —
`fcapz_configure`, then `fcapz_arm` once, then `fcapz_capture_status` to poll
and `fcapz_capture_wait` to read out — so a single hardware arm is held across
many short polls with no re-arm blind gaps. `fcapz_capture_wait` returns
`{triggered: false, still_armed: true}` when its `timeout` expires before the
trigger fires, so the poll loop treats "not yet" as data rather than an error;
the core stays armed. `fcapz_disarm` stops an arm. A capture `timeout` may
exceed `--rpc-timeout` (up to the 300 s cap); the MCP watchdog extends its
deadline to outlast the caller's wait plus readback rather than orphaning the
call.

`fcapz_capture` also takes `immediate=true`, which rewrites the trigger to an
always-true condition so the capture fires now — a snapshot of current state
with no waiting.

`fcapz_capture` takes `include_event_summary` to ask the RPC layer for decoded
event metadata. The MCP name is deliberately more explicit than the RPC field
name (`summarize`).

Both `fcapz_capture` and `fcapz_capture_wait` take `segments=true`, which
reads back every segment of a segmented core rather than segment 0 alone
(`fcapz_probe` reports `num_segments`). Sample paging concatenates the
segments and tags each sample with its `segment`; `trigger_index` is withheld,
because a flattened index no longer locates the trigger.

The tool schema is typed, not free-form: `backend`, `format`, `radix`,
`kind` and `trigger_mode` are enums, and `config` is a named object rather
than an open dictionary, so a client rejects a bad value before spending a
round trip on it. Bit-vector fields (`trigger_value`, `trigger_mask`,
`stor_qual_value`, `stor_qual_mask`) accept a base-prefixed string as well as
an integer, because a value wider than 53 bits cannot survive a JSON number.
The session still validates everything it is given — the schema is the
client's contract, not the server's guarantee.

Valid `config` keys for `fcapz_capture` and `fcapz_configure` are:

| Key | Meaning |
| --- | --- |
| `pretrigger` | Number of samples to retain before the trigger point. |
| `posttrigger` | Number of samples to retain after the trigger point. |
| `trigger_mode` | Trigger comparator/mode selection. |
| `trigger_value` | Trigger compare value. |
| `trigger_mask` | Trigger compare mask. |
| `sample_width` | Expected sample width in bits. |
| `depth` | Capture depth in samples. |
| `sample_clock_hz` | Optional sample clock rate for timestamp/event reporting. |
| `probes` | Probe definitions, matching the RPC/Python probe schema. |
| `probe_file` | Path to a probe definition file. |
| `channel` | Capture channel or runtime probe mux channel. |
| `decimation` | Sample decimation factor. |
| `ext_trigger_mode` | External trigger mode. |
| `stor_qual_mode` | Storage qualification mode. |
| `stor_qual_value` | Storage qualification compare value. |
| `stor_qual_mask` | Storage qualification compare mask. |
| `startup_arm` | Arm from hardware startup behavior when supported. |
| `trigger_holdoff` | Trigger holdoff count. |
| `trigger_delay` | Delay between trigger match and capture stop window. |

### Embedded I/O

| Tool | Purpose |
| --- | --- |
| `fcapz_eio_connect` | Connect to an EIO core. |
| `fcapz_eio_close` | Close the active EIO connection. Idempotent. |
| `fcapz_eio_read` | Read the current EIO input vector and cache the response. |
| `fcapz_eio_write` | Write the EIO output vector when `--allow-eio-write` is set. |

### JTAG-to-AXI4

| Tool | Purpose |
| --- | --- |
| `fcapz_axi_connect` | Connect to an eJTAG-to-AXI4 bridge. |
| `fcapz_axi_close` | Close the AXI bridge connection. Idempotent. |
| `fcapz_axi_read` | Read one 32-bit AXI word. |
| `fcapz_axi_write` | Write one 32-bit AXI word when `--allow-axi-write` is set. |
| `fcapz_axi_write_block` | Write a sequence of 32-bit AXI words when `--allow-axi-write` is set. |
| `fcapz_axi_dump` | Read a sequence of 32-bit AXI words. |

AXI MCP schemas use integer byte addresses and integer 32-bit data words. Convert
hex strings such as `"0x40000000"` to JSON integers before calling. `count` is
measured in 32-bit words, not bytes. `wstrb` is a 4-bit integer byte-lane mask;
bit 0 controls the lowest byte. `fcapz_axi_dump` and `fcapz_axi_write_block` are
capped at **4096 words per call** — both to bound the JTAG round-trip against the
watchdog and to keep a dump from flooding model context; transfer larger regions
in chunks at successive addresses.

### eJTAG-UART

| Tool | Purpose |
| --- | --- |
| `fcapz_uart_connect` | Connect to an eJTAG-UART bridge. |
| `fcapz_uart_close` | Close the UART bridge connection. Idempotent. |
| `fcapz_uart_send` | Send bytes when `--allow-uart-send` is set. |
| `fcapz_uart_recv` | Receive bytes. |
| `fcapz_uart_status` | Return UART bridge status counters and FIFO state. |

`fcapz_uart_send` accepts either `data_base64` for arbitrary bytes or `text` for
UTF-8 text. Passing both is rejected.

## Resources

| Resource | Updated by | Payload |
| --- | --- | --- |
| `fcapz://status` | session lifecycle; live snapshot on each fetch | Same information as `fcapz_status`. |
| `fcapz://last-probe` | `fcapz_probe` | Last ELA probe result, or `{"available":false}`. |
| `fcapz://last-capture` | `fcapz_capture` | Last full capture response, or `{"available":false}`. |
| `fcapz://last-eio-read` | `fcapz_eio_read` | Last EIO read response, or `{"available":false}`. |

Resource JSON is compact. MCP clients that display resources can pretty-print it
locally.

## Reading a Capture

Large captures stay in memory until the next capture, `fcapz_close`, or
`fcapz_drop_last_capture`. There are three ways to read one, in order of
preference:

1. **`fcapz_axi_transactions`** — for an AXI monitor capture. Transactions
   beat cycles for bus debugging; see [AXI Transactions](#axi-transactions).
2. **`fcapz_get_capture_samples`** — for everything else. Returns whole
   sample records, sliced into named fields from the capture's probe map,
   with `total` and `trigger_index` on every page so a page can be read on
   its own. Page with `next_start` until it is `null` (`count` caps at 512).
   `fields` narrows the signals returned; `fields=[]` gives the packed value
   instead. `radix` is `"hex"` (default) or `"int"`, and values too wide for
   an exact JSON number stay hex either way.
3. **`fcapz_get_last_capture_chunk`** — raw bytes of the whole payload. Use
   it to export a capture verbatim, or for `csv`/`vcd` captures. It is a
   transfer mechanism, not a reading one: chunks are not independently
   parseable, so a caller must concatenate every chunk before any of it is
   valid JSON, and the 64 KiB default is roughly 16k tokens of one capture.

For scale, on a 4096-sample AXI capture: one byte chunk is ~18k tokens and
covers under a quarter of the payload, while a 128-sample page with four
named fields is ~2.7k tokens and complete in itself.

Resource-aware clients may also read `fcapz://last-capture`, which injects
the entire payload — fine for a small capture, not for a deep one.

Chunking mechanics, when you do need the raw payload: call
`fcapz_get_last_capture_chunk(offset=0, max_bytes=65536)` and follow the byte
`next_offset` until it is `null`. Chunks are UTF-8 JSON text and never split a
multibyte character; pass either `0` or a returned `next_offset`, because
offsets in the middle of a character are rejected. `max_bytes` must leave room
for at least one whole character (use `>= 4`); a window too small to fit the
next one is rejected rather than returning an empty chunk that would never
advance. `fcapz_get_last_capture` has a 1 MiB default guard and returns a
compact truncation marker for larger captures unless `max_bytes=null` is
passed as an explicit escape hatch.

## AXI Transactions

When a capture uses an AXI monitor probe map, the server reassembles the
per-cycle bus trace into whole AXI4-Lite transactions and
`fcapz_axi_transactions` pages them. This is the tool to reach for when
debugging bus behaviour — a raw sample dump makes an agent rebuild the
protocol structure itself, from data that mostly will not fit in context.

Each transaction carries its address, data, byte strobes, response, the cycle
each beat landed on, latency, per-channel stall counts, and `flags`:

```json
{"index": 12, "kind": "write", "addr": "0x00001000", "data": "0xcafebabe",
 "strb": "0xf", "resp": "SLVERR", "cycles": {"addr": 40, "data": 42, "resp": 47},
 "latency": 7, "stall_cycles": {"addr": 2}, "flags": ["error_response"]}
```

`only_anomalies=true` returns just the flagged transactions — usually the
right first call. `kind` filters to `"read"` or `"write"`. Page with the
returned `next_start` until it is `null`; `count` is capped at 256, and every
page is valid JSON on its own.

| Flag | Meaning |
| --- | --- |
| `error_response` | `SLVERR` or `DECERR` on B/R. |
| `partial_write` | `wstrb` enables some byte lanes but not all. |
| `write_strobe_zero` | A write beat with no byte lanes enabled. |
| `data_before_address` | The W beat preceded its AW. Legal AXI, but a common symptom when a bridge enqueues a command before its payload has settled. |
| `write_missing_data` / `write_missing_address` | A half-formed write — the shape a dropped or scrambled command leaves behind. |
| `unaligned_address` | Address is not a multiple of the data-bus width. |
| `request_not_observed` | A response arrived with no matching request in the capture. |
| `pairing_suspect` | Another transaction in the same direction had no visible request, so this one's pairing may be shifted. |
| `no_response_in_window` | The capture ended before the response arrived. Benign. |

`no_response_in_window`, `partial_write`, `write_strobe_zero` and
`data_before_address` are legal AXI; they are reported as observations and do
not count towards `anomaly_count` or `only_anomalies` (use `flagged_count` for
the total with any flag at all).

### What in-order pairing assumes

AXI4-Lite has no transaction IDs, so a single implicit ID applies and the
protocol requires responses in issue order. The decoder therefore pairs each
B/R with the oldest outstanding AW+W/AR — correct, *provided nothing was
already outstanding when the capture window opened*. A trace cannot prove
that: a read issued before the trigger and answered inside the window looks
exactly like an answer to the first address the capture happened to see.

So the decode result carries a `pairing` block naming the assumption, and
`pre_window_traffic_observed` lists the directions where a response arrived
with an empty queue — proof that the window opened mid-flight. Every other
transaction in such a direction is flagged `pairing_suspect`. Capture from a
quiet bus (or trigger on the first AW/AR) when exact addresses matter.

A response is never paired with a request handshaking on the same sampled
cycle: AXI forbids a combinational VALID-to-VALID path, so such a response
belongs to an earlier request.

The capture summary carries only the headline counts (`transaction_count`,
`error_count`, `anomaly_count`, `max_latency`); the transactions themselves
are only ever returned through this tool. Decoding is AXI4-Lite only, matching
the monitor RTL (`proto_code` 1, no IDs, no bursts), and works on both
`DECODE_EN` builds and plain ones. Non-AXI captures are unaffected.

## Wide Sample Values

JSON numbers are IEEE-754 doubles in most MCP clients (any JavaScript or
TypeScript host parses them with `JSON.parse`), so integers above `2**53 - 1`
are silently rounded. Captures can exceed that: an AXI monitor with
`DECODE_EN=1` produces 160-bit samples, and rounding would destroy exactly the
`awaddr`/`wdata`/`wstrb` bits you are trying to read.

When any value in a capture is too wide, every value in that list is returned
as a `0x…` hex string instead of a number and the payload carries
`"value_encoding": "hex"` at the top level. The encoding is all-or-nothing per
list, so a caller never has to handle a mix of integers and strings. Captures
that fit in 53 bits are unchanged and carry no `value_encoding` key.

The same applies to EIO: `fcapz_eio_read` returns `value` as a hex string
(with `value_encoding`) once the input vector is wider than 53 bits, so it can
never disagree with `value_hex`. On the way down, `fcapz_eio_write` accepts a
base-prefixed string as well as a number, which is the only way a JavaScript
client can drive a wide output vector exactly.

## Status Fields

`fcapz_status` and `fcapz://status` include:

| Field | Meaning |
| --- | --- |
| `mcp_server_version` | The installed fpgacapZero package version. |
| `rpc_schema_version` | The RPC schema version. It is seeded before the first RPC and updated from successful RPC responses. |
| `session_state` | `ready` (accepting commands), `busy` (one in flight; a second is refused), or `poisoned` (a command was abandoned after the watchdog; the owner is tearing the session down and will return to `ready`). |
| `rpc_busy` | Whether a hardware command is in flight. |
| `active_rpc_cmd` | Name of the command in flight, or `null` when idle. |
| `connected` | Whether an ELA connection is active. |
| `eio_connected` | Whether an EIO connection is active. |
| `axi_connected` | Whether an AXI bridge connection is active. |
| `uart_connected` | Whether a UART bridge connection is active. |
| `capabilities` | Server safety and timeout settings, including write/program enables, `bitfile_root`, `rpc_timeout_sec`, and `rpc_cancel_grace_sec`. |
| `last_probe` | Last probe result, or `null` before probing or after close/drop-reset paths. |
| `last_capture_summary` | Compact summary of the last capture, or `null` when no capture is cached. |
| `last_capture_size_bytes` | Compact JSON byte size of the cached full capture, or `null` when no capture is cached. |
| `last_eio_read` | Last EIO read response, or `null` before any EIO read. |

Agents should check these fields if they depend on exact response shapes.
Patch-version changes should be backward compatible; major-version or RPC schema
changes should be treated as protocol changes until the agent has been updated
or explicitly tested against that server. Before 1.0, minor-version bumps may
also include protocol changes.

## Example Flows

Read-only probe:

```text
fcapz_status()
fcapz_connect(backend="hw_server")
fcapz_probe()
fcapz_close()
```

Configure now, arm later:

```text
fcapz_connect(backend="openocd", port=6666, tap="xc7a100t.tap")
fcapz_configure(config={"pretrigger": 128, "posttrigger": 1024})
fcapz_arm()
fcapz_close()
```

Capture and then explicitly release the large payload:

```text
fcapz_capture(config={"pretrigger": 64, "posttrigger": 4096}, timeout=10.0)
fcapz_get_capture_samples(start=0, count=128)
repeat with next_start until null
fcapz_drop_last_capture()
fcapz_close()
```

Debug a bus fault with the AXI monitor — anomalies first, then their context:

```text
fcapz_connect(backend="hw_server")
fcapz_list_cores()                       # find the AXI monitor's chain
fcapz_capture(config={"probe_file": "axi.prob", "pretrigger": 512,
                      "posttrigger": 3584}, timeout=10.0)
                                         # summary carries the AXI headline counts
fcapz_axi_transactions(only_anomalies=True)
                                         # then widen around what it found
fcapz_axi_transactions(start=0, count=64)
fcapz_close()
```

AXI read:

```text
fcapz_axi_connect(backend="hw_server", chain=4)
fcapz_axi_read(addr=1073741824)  # 0x40000000
fcapz_axi_close()
```

UART receive:

```text
fcapz_uart_connect(backend="hw_server", chain=4)
fcapz_uart_recv(count=256, timeout=0.5)
fcapz_uart_close()
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tool says a write is disabled | Server was started without the matching safety flag. | Restart with the specific `--allow-*` flag, or keep read-only mode. |
| `program=` is rejected | Programming is disabled, outside `--bitfile-root`, not a `.bit`, or not `hw_server`. | Start with `--allow-program --bitfile-root DIR` and pass an allowed `.bit` file. |
| Tool call raises `TimeoutError` | The MCP 30 second response timeout fired before the backend returned. | The server attempted a session-wide backend cancellation. Retry only if `fcapz_status` responds; restart if the next call reports a previous RPC still running. |
| A new tool call says a previous RPC is still running | A timed-out hardware call is still executing in the background. | The MCP client or host wrapper needs to restart `fcapz-mcp` before issuing more hardware commands. |
| `fcapz://last-capture` is unavailable | No capture has completed, or the payload was dropped/closed. | Run `fcapz_capture` again. |
| USB-Blaster rejects `host` | That backend does not use host/port sockets. | Omit `host`, `port`, and `tap` entirely for `usb_blaster`. |

## Related Chapters

- [Chapter 10 - CLI reference](10_cli_reference.md)
- [Chapter 11 - JSON-RPC server](11_rpc_server.md)
- [Chapter 14 - Transports](14_transports.md)
- [Chapter 15 - Export formats](15_export_formats.md)
