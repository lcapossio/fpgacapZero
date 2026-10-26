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

`fcapz-mcp` speaks MCP over **stdio** (the default) or **streamable HTTP**
(`--transport http`). Either way one server process owns one hardware
session: a single `FcapzMcpSession`, which can hold ELA, EIO, AXI, and UART
connections.

- **stdio** — the MCP client launches the server and is its only client. On
  stdio disconnect or normal server exit, the session closes every active
  hardware connection. Run a second `fcapz-mcp` process for a second client.
- **HTTP** — for a bench machine an agent reaches over the network. Every
  client that holds the token shares the *same* hardware session: one
  client's `fcapz_connect` is the other's open board, and a call made while
  another client's capture runs is refused with `busy`. A client
  disconnecting closes nothing; only server exit does.

### HTTP mode

Every request must carry `Authorization: Bearer <token>`; anything else is
answered `401` before it reaches MCP. The token comes from the
`FCAPZ_MCP_TOKEN` environment variable or `--http-token-file FILE` — never a
command-line flag, which would put it in the process list — and must be at
least 16 characters. There is no default token and none is generated.

```bash
export FCAPZ_MCP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
fcapz-mcp --transport http                       # http://127.0.0.1:8765/mcp
fcapz-mcp --transport http --http-host 0.0.0.0 \
          --http-tls-cert cert.pem --http-tls-key key.pem   # https, reachable on the LAN
```

| Flag | Effect |
| --- | --- |
| `--transport http` | Serve streamable HTTP at `/mcp` instead of stdio. |
| `--http-host ADDR` | Listen address, default `127.0.0.1`. A non-loopback address needs TLS or `--http-insecure`. (Unrelated to `--allow-host`, which names backend daemons.) |
| `--http-port PORT` | Listen port, default `8765`. |
| `--http-token-file FILE` | Read the bearer token from `FILE` instead of `FCAPZ_MCP_TOKEN`. |
| `--http-tls-cert PEM` / `--http-tls-key PEM` | Serve HTTPS. Both or neither. |
| `--http-insecure` | Permit plain HTTP on a non-loopback address; the token then crosses the network in clear text. Prefer TLS or an SSH tunnel (`ssh -L 8765:127.0.0.1:8765 bench`) to a loopback-bound server. |

On a loopback bind the MCP SDK also checks the `Host` header against
`127.0.0.1`/`localhost`/`[::1]`, which stops a web page from reaching the
server through DNS rebinding. A network bind drops that check — the `Host` is
whatever name the clients use — and relies on the token, which a browser page
cannot attach. The `--allow-*` safety flags apply exactly as they do on stdio:
the token decides who may call, the flags decide what a call may do.

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

For Claude Code, the same server is registered with `claude mcp add`; over
HTTP the token travels as a header:

```bash
claude mcp add fpgacapzero -- fcapz-mcp --read-only
claude mcp add --transport http fpgacapzero https://bench.example:8765/mcp \
    --header "Authorization: Bearer $FCAPZ_MCP_TOKEN"
```

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
| `--read-only` | Disables `fcapz_configure`, `fcapz_arm`, `fcapz_capture`, `fcapz_disarm`, the readout mode of `fcapz_capture_wait` (its `status_only` poll stays), and all write/send/program enable flags. |
| `--allow-eio-write` | `fcapz_eio_write` |
| `--allow-axi-write` | `fcapz_axi_write`, anywhere on the bus |
| `--axi-write-range LO:HI` | `fcapz_axi_write`, but only inside this inclusive byte-address range (repeatable; implies `--allow-axi-write`) |
| `--allow-uart-send` | `fcapz_uart_send` |
| `--allow-program --bitfile-root DIR` | `fcapz_connect(program=...)` for `.bit` files under `DIR` |
| `--probe-root DIR` | Capture config `probe_file` may read a probe map sitting directly in `DIR` |
| `--allow-host HOST` | A backend may connect to `HOST` as well as loopback (repeatable) |

`--read-only` cannot be combined with any write/program enable flag.

`--axi-write-range` is the safer way to enable AXI writes on a live system:
name the peripheral's register window rather than handing the agent the whole
bus, which on a SoC includes DDR, interconnect configuration and the bridge's
own neighbours. Addresses are hex or decimal, `LO <= HI`, both within 32
bits:

```bash
fcapz-mcp --axi-write-range 0x40000000:0x4000FFFF --axi-write-range 0x43C00000:0x43C0001F
```

Every byte of every word a call writes must fall inside some range, so two
adjacent ranges admit a block that straddles them, and a call with any word
outside is refused whole (`not_permitted`, naming the word and the ranges)
rather than written part way. A block that would run past the top of the
bridge's address space (its `addr_w` from `fcapz_connect`) is refused too,
because the bridge's address counter would wrap it to address 0.
Reads are not confined. `fcapz_status` reports
the ranges under `capabilities.axi_write_ranges` (`null` when writes, if
enabled, may go anywhere).

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

The name must be a **file directly inside `--probe-root`** — not a
subdirectory, not a path climbing out of it, and not a link. This is a
security boundary, not housekeeping. Whoever can write inside the root is
trusted with the *contents* of a probe map and nothing more, so they must
not be able to turn it into a read of anything else, and checking a path
before opening it does not achieve that: a name swapped for a link in
between is followed by the open and by any re-check of the same path, which
then agree with each other and approve it.

With one component the lookup is verifiable. Where the platform has
`openat`/`O_NOFOLLOW` the file is opened relative to a descriptor already
held for the root, so nothing about the path can be reinterpreted and a link
fails the open outright. Elsewhere (Windows, which has no directory handles
to open relative to) the file is inspected and then opened, and the two
identities are compared — a link already in place is refused, and a swap in
between makes them disagree. A file with more than one hard link is refused
either way: its entry looks ordinary and its identity is stable, but the
bytes can belong to a file outside the root. Probe files are also capped at
1 MiB.

Programming is intentionally `hw_server`-only in the MCP layer.

If `program` is passed while programming is disabled, the server reports the
permission error before backend-specific validation so agents see the global
safety policy first.

## Backends And Connection Fields

The live RPC layer supports:

| Backend | Target fields | Optional fields |
| --- | --- | --- |
| `hw_server` | `host`, `port`, `tap`, `ir_table` | `program`, `single_chain_burst` defaults to `true` |
| `openocd` | `host`, `port`, `tap`, `ir_table` | - |
| `usb_blaster` | `hardware`, `quartus_stp` | - |
| `ftdi` | `hardware`, `ir_table` | `tck_mhz` (default 6) |
| `serial` | `serial_port` | `baudrate` (default 1000000) |

`ir_table` names the JTAG IR-code preset: `"xilinx7"`, `"ultrascale"`,
`"gowin"`, `"polarfire"` or `"efinix"`. Omit it and the RPC layer infers one
from `tap` (`gw*` is Gowin, `xcku*`/`xcvu*`/`xcau*` UltraScale, anything else
7-series), or on `ftdi` from the device IDCODE; pass it when the tap name does
not say which family the part is.

`ftdi` drives an FTDI MPSSE adapter directly through the D2XX driver, with no
daemon: the PolarFire kits' embedded FlashPro5, a Digilent cable, or any
FT2232H/FT4232H JTAG adapter (see [Transports](14_transports.md)). `hardware`
names the adapter by its D2XX description (for example
`"Embedded FlashPro5 A"`) or serial. Omit it only when a single FlashPro or
Digilent adapter is attached: other FTDI adapters (a generic FT2232H board,
say) are not recognised and must be named.
EIO, AXI and UART sessions on the same adapter share its handle.

`serial` talks to the byte-stream TAP bridge (`rtl/fcapz_uart_tap.v`, used by
the Efinix Trion example) over a serial port. `serial_port` is required and
must be a port the machine lists (`COM5`, `/dev/ttyACM0`): the transport opens
it as a device path, so any other name is refused rather than opened. The ELA
session holds the port exclusively, so on `serial` an EIO works only in a
core-manager slot on the ELA's own port and chain (its `chain` defaults to the
ELA's), and AXI/UART are not available. Such a request is refused before the
session it would replace is closed.

Backend-irrelevant fields are rejected instead of being silently forwarded.
`hw_server` and `openocd` default `host` to `127.0.0.1` when omitted; `host`,
`port` and `tap` are rejected for `ftdi` and `serial`, which are local USB and
serial devices.
`usb_blaster` (Intel/Altera via Quartus) has no host concept, so `host`,
`port`, `tap` and `ir_table` are rejected for it — even an explicit `host="127.0.0.1"`.
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
| `fcapz_connect` | none for plain connect; `--allow-program` if `program=` or a caller-supplied `quartus_stp=` is set | Connect to a debug core: `core` is `"ela"` (default), `"eio"`, `"axi"` or `"uart"`. `chain` selects the JTAG USER chain (ELA: omit to autodetect; EIO: 3, or 0 on `usb_blaster`; AXI/UART: 4). The EIO/AXI/UART sessions need the ELA session open, and reconnecting the ELA closes them, so connect it first. |
| `fcapz_close` | always available | `core="all"` (default) closes the **whole board session** — the ELA plus any EIO/AXI/UART controller; `"eio"`, `"axi"` or `"uart"` closes just that core. Idempotent. |
| `fcapz_probe` | connected ELA | Read ELA identity, dimensions, and feature registers. |
| `fcapz_list_cores` | connected ELA | List debug cores on the board (type, JTAG `chain`, identity) so an agent can pick the right chain for side connects. |
| `fcapz_configure` | capture* | Configure the connected ELA without arming. |
| `fcapz_arm` | capture* | Arm the connected ELA using the current hardware configuration. |
| `fcapz_capture` | capture* | Configure, arm, capture, and cache the full capture payload. Returns summary metadata only. |
| `fcapz_capture_wait` | capture* (readout); always (`status_only`) | Read out an already-armed capture (from `fcapz_configure` + `fcapz_arm`) without reconfiguring or re-arming. Returns `{triggered: false, still_armed: true}` (not an error) if the trigger has not fired yet. `status_only=true` reads the capture FSM state without waiting or transferring samples. |
| `fcapz_disarm` | capture* | Soft-reset the capture FSM to idle, discarding any in-flight arm. |
| `fcapz_get_last_capture` | always available | Return the cached full capture payload for clients without resource support. Defaults to a 1 MiB guard, capped at 8 MiB. |
| `fcapz_get_capture_samples` | always available | Page the cached capture's samples as whole records, with named fields from the probe map; `around_trigger=N` reads the window around the trigger. See [Reading a Capture](#reading-a-capture). |
| `fcapz_find_in_capture` | always available | Search the cached capture for edges, rising/falling bits, value matches or runs of one signal, paged, with first/last positions. See [Searching a Capture](#searching-a-capture). |
| `fcapz_axi_transactions` | always available | Decoded AXI4-Lite transactions of the cached capture — paged, filterable by anomaly or read/write. See [AXI Transactions](#axi-transactions). |
| `fcapz_get_last_capture_chunk` | always available | Return a bounded JSON text chunk of the cached capture payload. |
| `fcapz_drop_last_capture` | always available | Drop the cached full capture payload and report whether one existed. |

`capture*` tools are enabled by default and blocked by `--read-only`.

**Disabled tools are not advertised.** A tool whose capability is off is left
out of the tool list entirely, rather than offered and then refused: the agent
would otherwise plan around it, spend a call discovering the refusal, and pay
for its schema in every request. So the advertised surface tracks the flags —
16 tools under `--read-only`, 20 by default, 23 with every write enabled. The
session-level permission checks remain as the actual enforcement; the gating
is about what the agent is told exists.

Two capture flows are available. `fcapz_capture` is the one-shot path: it
configures, arms, and reads out in a single call, re-arming every time. For a
long wait on a real hardware event, use the manual flow instead —
`fcapz_configure`, then `fcapz_arm` once, then `fcapz_capture_wait` to poll
and read out (`status_only=true` to peek without a readout) — so a single hardware arm is held across
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

Five tools declare an `outputSchema` as well: `fcapz_get_capture_samples`,
`fcapz_find_in_capture`, `fcapz_axi_transactions`,
`fcapz_get_last_capture_chunk`, and `fcapz_status`.
Those are the payloads this server builds end to end, and each returns one
fixed shape — every field is always present, `null` where it does not apply,
so a caller never has to branch on which keys exist. Everything else is an
RPC response passed through verbatim and stays deliberately open: a declared
schema is not documentation, it is a filter, and MCP drops any field the
schema does not name from `structuredContent`. Naming a subset of an RPC
response would silently delete the rest.

Valid `config` keys for `fcapz_capture` and `fcapz_configure` are:

| Key | Meaning |
| --- | --- |
| `pretrigger` | Number of samples to retain before the trigger point. |
| `posttrigger` | Number of samples to retain after the trigger point. |
| `trigger_mode` | Trigger comparator/mode selection. |
| `trigger_value` | Trigger compare value. |
| `trigger_mask` | Trigger compare mask. |
| `sample_width` | Expected sample width in bits. Omit it to use the probe file's, else the core's. |
| `depth` | Capture depth in samples. Omit it to use the core's. |
| `sample_clock_hz` | Optional sample clock rate for timestamp/event reporting. |
| `probes` | Probe definitions, matching the RPC/Python probe schema. |
| `probe_file` | Name of a probe definition file directly inside `--probe-root`. |
| `channel` | Input channel of the channel mux (`0`..`NUM_CHANNELS`-1). The runtime probe mux slice (`probe_sel`) is not exposed over MCP or RPC and stays at `0`; select another slice from Python (`CaptureConfig(probe_sel=...)`) or the CLI (`--probe-sel`). |
| `decimation` | Sample decimation factor. |
| `ext_trigger_mode` | External trigger mode. |
| `stor_qual_mode` | Storage qualification: `0` off, `1` store only matching samples, `2` store only non-matching ones. `1` needs a core reporting `COMPARE_CAPS` bit 22; older cores have only `2`. |
| `stor_qual_value` | Storage qualification compare value. |
| `stor_qual_mask` | Storage qualification compare mask. |
| `startup_arm` | Arm from hardware startup behavior when supported. |
| `trigger_holdoff` | Trigger holdoff count. |
| `trigger_delay` | Delay between trigger match and capture stop window. |
| `rle` | Run-length capture: each stored entry is a value and the sample clocks it held. Needs `rle_width > 0` in `fcapz_probe`; not with `decimation` or `stor_qual_mode`. |
| `post_clocks` | With `rle`, also end the capture this many sample clocks after the trigger (0 = no limit). |
| `trigger_sequence` | Programs the hardware trigger sequencer, one object per stage, up to `trig_stages` in `fcapz_probe`. Each stage takes `cmp_mode_a`/`cmp_mode_b` (`0`-`8`: EQ, NEQ, LT, GT, LEQ, GEQ, RISING, FALLING, CHANGED; LT-GEQ need `REL_COMPARE`), `value_a`/`mask_a`/`value_b`/`mask_b`, `combine` (`0` A, `1` B, `2` A and B, `3` A or B), `count_target` (`0`-`65535`), `next_state` (`0`-`3`) and `is_final`. See the trigger sequencer in [ELA core](05_ela_core.md). |

### Embedded I/O

Open the core with `fcapz_connect(core="eio")` and close it with
`fcapz_close(core="eio")`.

| Tool | Purpose |
| --- | --- |
| `fcapz_eio_read` | Read the current EIO input vector and cache the response. |
| `fcapz_eio_write` | Write the EIO output vector when `--allow-eio-write` is set. |

### JTAG-to-AXI4

Open the bridge with `fcapz_connect(core="axi")` and close it with
`fcapz_close(core="axi")`.

| Tool | Purpose |
| --- | --- |
| `fcapz_axi_read` | Read `count` 32-bit words (default 1) from a byte address; `burst=true` uses the burst path. Always returns `words`, plus `value` for one word. |
| `fcapz_axi_write` | Write one word (with a `wstrb` byte-lane mask) or a list of words (`burst=true` for the burst path) when `--allow-axi-write` is set. |

Addresses are byte addresses and data are 32-bit words; both accept a JSON
integer or a base-prefixed string such as `"0x40000000"`, and anything outside
32 bits is rejected. `count` is measured in 32-bit words, not bytes. `wstrb` is
a 4-bit byte-lane mask (bit 0 controls the lowest byte) and applies to a
single-word write only. Reads and block writes are capped at **4096 words per
call** — both to bound the JTAG round-trip against the
watchdog and to keep a dump from flooding model context; transfer larger regions
in chunks at successive addresses.

### eJTAG-UART

Open the bridge with `fcapz_connect(core="uart")` and close it with
`fcapz_close(core="uart")`.

| Tool | Purpose |
| --- | --- |
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
preference — and when you are looking for something specific, search first
with `fcapz_find_in_capture` ([below](#searching-a-capture)) and read only
around the hits:

1. **`fcapz_axi_transactions`** — for an AXI monitor capture. Transactions
   beat cycles for bus debugging; see [AXI Transactions](#axi-transactions).
2. **`fcapz_get_capture_samples`** — for everything else. Returns whole
   sample records, sliced into named fields from the capture's probe map,
   with `total` and `trigger_index` on every page so a page can be read on
   its own. Page with `next_start` until it is `null` (`count` caps at 512).
   `fields` narrows the signals returned; `fields=[]` gives the packed value
   instead. `radix` is `"hex"` (default) or `"int"`, and values too wide for
   an exact JSON number stay hex either way. `around_trigger=N` returns
   the `N` samples either side of the trigger instead of `start`/`count`
   (`N` up to 255, so the window fits one page — rejected above that); when
   the trigger cannot be located (a segmented capture, or one shorter than
   `pretrigger + posttrigger + 1`) the page comes back empty with a `reason`
   rather than a guess. On a run-length capture the page has
   `run_length_capture: true` and each record also carries `run_length` (the
   sample clocks that value held) and `clock` (where it starts, counted from
   the segment's first entry); `total` and positions count stored entries.
3. **`fcapz_get_last_capture_chunk`** — raw bytes of the whole payload. Use
   it to export a capture verbatim, or for `csv`/`vcd` captures. It is a
   transfer mechanism, not a reading one: chunks are not independently
   parseable, so a caller must concatenate every chunk before any of it is
   valid JSON, and the 64 KiB default is roughly 16k tokens of one capture.

For scale, on a 4096-sample AXI capture: one byte chunk is ~18k tokens and
covers under a quarter of the payload, while a 128-sample page with four
named fields is ~2.7k tokens and complete in itself.

Resource-aware clients may also read `fcapz://last-capture`, which injects
the entire payload — fine for a small capture, not for a deep one. It is the
cheapest route on the server side (the payload is already serialized) and the
only one with no size ceiling, but it still lands in full in model context.

Chunking mechanics, when you do need the raw payload: call
`fcapz_get_last_capture_chunk(offset=0, max_bytes=65536)` and follow the byte
`next_offset` until it is `null`. Chunks are UTF-8 JSON text and never split a
multibyte character; pass either `0` or a returned `next_offset`, because
offsets in the middle of a character are rejected. `max_bytes` must leave room
for at least one whole character (use `>= 4`); a window too small to fit the
next one is rejected rather than returning an empty chunk that would never
advance. `fcapz_get_last_capture` has a 1 MiB default guard and returns a
compact truncation marker for larger captures. `max_bytes` may lower that
bound but not raise it past an **8 MiB ceiling**, and `max_bytes=null` means
that ceiling rather than "unlimited": a tool result is turned back into JSON
on the event loop *after* the offloaded call returns, so the payload costs
the whole server a stall of roughly 5 ms per MB that nothing else can
interleave with — 125 ms for a 24 MB capture, and more for a deep segmented
one. A marker returned because of the ceiling carries `ceiling_bytes`, so a
caller can tell the server's bound from its own.

Nothing is unreachable as a result: `fcapz://last-capture` still serves the
entire payload, and does it from a string that is already built, so it
measures 0 ms of loop stall for the same 24 MB the tool needed 125 ms for.
Prefer the resource for a whole payload, and the chunk tool where the client
has no resource support.

## Searching a Capture

`fcapz_find_in_capture` answers "where does X happen" without paging the
capture into context. It scans one signal — a probe-map `field`, or the packed
sample when `field` is omitted — and returns the matches, paged:

| `op` | Finds | Entry fields |
| --- | --- | --- |
| `edges` | Every change of the (masked) signal; with `value`, only changes *to* it. | `from`, `to` |
| `rising` / `falling` | A 0→1 / 1→0 of bit `bit` (default 0) of the signal. | — |
| `match` | Every sample where `signal & mask == value & mask`. | `value` |
| `bursts` | Maximal runs of one value, at least `min_length` sample clocks long; with `value`, only runs of it. | `length` (clocks), `value` |

`mask` defaults to the whole signal. `value` and `mask` accept a base-prefixed
string for signals wider than 53 bits, and one with bits the signal does not
have is rejected rather than silently never matching.

Every entry carries `position`, the flattened index that
`fcapz_get_capture_samples(start=position)` takes, so a hit can be read in
context with one more call; the sample's own `index`; `segment` on a
segmented capture; and `trigger_offset` (samples after the trigger, negative
before it) when the trigger can be located. On a run-length capture each
entry also carries `clock`, and a burst's `length` adds up the clocks its
entries held, so it is time, not stored entries. A segmented capture is searched
segment by segment, so the jump between two segments is never reported as an
edge.

`total`, `first_position` and `last_position` cover every match, not just the
page, so "the first sample where `state == 3`" is
`fcapz_find_in_capture(op="match", field="state", value=3, count=1)` and needs
no paging. Page with `next_start` until it is `null`; `count` is capped at 512.

```text
fcapz_find_in_capture(op="rising", field="valid")          # every handshake start
fcapz_find_in_capture(op="bursts", field="busy", value=1, min_length=100)
fcapz_get_capture_samples(start=<position>, count=16)      # read one in context
```

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
| `request_not_observed` | A response arrived with no matching request in the capture — its request handshook before the window opened. |
| `pairing_suspect` | Another transaction in the same direction had no visible request, so this one's pairing may be shifted. |
| `no_response_in_window` | The capture ended before the response arrived. Benign. |

Only `error_response` and `unaligned_address` count as **bus faults**
(`anomaly_count`, and what `only_anomalies` keeps): they are the two a finite
capture can actually prove. Everything else is either legal AXI
(`partial_write`, `write_strobe_zero`, `data_before_address`) or an artefact
of the window's own edges (`request_not_observed`, `no_response_in_window`,
`write_missing_*`, `pairing_suspect`) — a transaction clipped at the start or
the end of a capture is ordinary traffic seen through a keyhole, not a
violation. `flagged_count` is the total with any flag at all.

### What in-order pairing assumes

AXI4-Lite has no transaction IDs, so a single implicit ID applies and the
protocol requires responses in issue order. The decoder therefore pairs each
B/R with the oldest outstanding AW+W/AR — correct, *provided nothing was
already outstanding when the capture window opened*. A trace cannot prove
that: a read issued before the trigger and answered inside the window looks
exactly like an answer to the first address the capture happened to see.

So the `pairing` block travels on the decode, on the capture summary, **and
on every page of `fcapz_axi_transactions`** — not only the first, and not
only when something looked wrong. `pre_window_traffic_observed` lists the
directions where a response arrived with an empty queue, and
`pre_window_traffic_proven` is true only then: it is evidence the assumption
is *false*, never evidence that it holds. The undetectable case is the
dangerous one — `AR(A)` before the window, `AR(B)` and then `R(A)` inside it
yields a clean-looking row reporting A's data at address B, with nothing in
the trace to mark it. Every other transaction in a direction with proven
pre-window traffic is flagged `pairing_suspect`. Capture from a quiet bus (or
trigger on the first AW/AR) when exact addresses matter.

A response is never paired with a request handshaking on the same sampled
cycle: AXI forbids a combinational VALID-to-VALID path, so such a response
belongs to an earlier request.

### Captures that cannot be decoded at all

Reassembly reads a sample's position as its bus cycle and pairs each response
with the oldest queued request. **Decimation and storage qualification break
both.** They store only selected cycles, so a handshake that was never stored
cannot be told apart from one that never happened: a dropped response shifts
every later pairing onto the wrong address, and "latency" becomes a count of
stored samples. Nothing can recover the missing beats afterwards, so such a
capture is refused rather than misread —

```json
{"decoded": false,
 "unavailable_reason": "the capture stored only selected cycles (decimation=3), ...",
 "sampling": {"decimation": 3, "storage_qualified": false, "run_length": false,
              "contiguous": false},
 "transactions": []}
```

The result keeps its full shape, so one code path reads both. `sampling` is
reported either way, and travels with every transaction page. Re-capture with
`decimation` 0 and `stor_qual_mode` 0 to decode. A run-length capture drops no
cycle, so it decodes: the decoder expands each entry back to the clocks it
held (`sampling.run_length` is `true`), and cycle numbers and latencies count
sample clocks.

The capture summary carries only the headline counts (`transaction_count`,
`error_count`, `anomaly_count`, `flagged_count`, `max_latency`) plus
`pairing` and `sampling`; the transactions themselves
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

## Long Calls

Every hardware tool runs in a worker thread. FastMCP awaits a synchronous
tool on the event loop, so before this a JTAG round trip stopped the server
answering anything at all for its duration — a 300 s capture froze even
`fcapz_status` for five minutes. Hardware access is still serialized by the
owner thread; only the loop is freed.

`fcapz_capture` and `fcapz_capture_wait` also emit MCP progress
notifications once a second while they wait, when the client sends a progress
token. There is no progress to read from inside a JTAG readout, so what is
reported is elapsed time against the timeout the caller set — enough to show
the server is alive and how much of the budget is gone. A client that does
not take progress notifications is unaffected: the capture still completes.

## Errors

MCP has no structured error channel — a failed tool call reaches the agent as
text and nothing else — so every failure is rendered as one JSON object
rather than as prose to pattern-match:

```json
{"code": "busy",
 "message": "fcapz is busy running 'capture'; the JTAG transport takes one command at a time",
 "retryable": true,
 "action": "wait for the running command to finish (fcapz_status shows active_rpc_cmd); JTAG runs one command at a time"}
```

`retryable` says whether repeating the identical call could ever succeed;
`action` says what to do first when it could not. An RPC refusal also carries
the backend's own error object as `detail`.

| Code | Means | Retryable |
| --- | --- | --- |
| `busy` | Another hardware command is running; JTAG takes one at a time. | yes |
| `session_recovering` | The watchdog abandoned a command and the session is tearing it down. | yes |
| `watchdog_timeout` | A command outran the watchdog; the board session was torn down. | yes, after reconnecting |
| `capture_not_ready` | The trigger has not fired; the core is still armed. | yes, keep polling |
| `timeout` | A wait expired without the hardware finishing. | yes |
| `not_connected` | No connection for that subsystem yet. | yes, after connecting |
| `not_permitted` | The capability is switched off; only the operator can enable it. | no |
| `invalid_argument` | An argument was rejected. | no |
| `not_found` | A path does not exist on the server. | no |
| `unknown_tool` | This server does not publish that tool. | no |
| `hardware_error` | The board or backend rejected the command, or the AXI bus answered `SLVERR`/`DECERR`. | yes |
| `internal` | A bug in `fcapz-mcp`. | no |

Every failure of a tool call is coded, including the two that never reach the
tool body: a misspelled argument and a value the schema rejects, both caught
by validation beforehand. The body also names the failing `tool`.

`busy` and `session_recovering` are tagged where they are raised, not matched
by wording, so rephrasing a message cannot reclassify it.

A misspelled argument is **rejected, never dropped**. Both the tool's own
arguments and the fields of `config` are checked against the published
schema, so `{"posttriger": 9}` fails with `invalid_argument` naming the field
instead of quietly running a capture with the default posttrigger.

`capture_not_ready` is distinct from `timeout` on purpose. `fcapz_capture_wait`
returns `{"triggered": false, "still_armed": true}` only for the former — the
analyzer's own "the trigger has not fired". A timeout from the transport
while reading status or samples may mean the link is wedged, and is reported
as a failure rather than as another poll.

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
| `capabilities` | Server safety and timeout settings, including write/program enables, `axi_write_ranges`, `probe_root`, `allowed_hosts`, `bitfile_root`, `rpc_timeout_sec`, and `rpc_cancel_grace_sec`. |
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
fcapz_connect(backend="hw_server", chain=<monitor chain>)
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
fcapz_connect(backend="hw_server")       # the ELA session comes first
fcapz_connect(core="axi", backend="hw_server", chain=4)
fcapz_axi_read(addr="0x40000000")
fcapz_axi_read(addr="0x40000000", count=16)
fcapz_close(core="axi")
```

PolarFire board on its embedded FlashPro5, no daemon:

```text
fcapz_connect(backend="ftdi")
fcapz_capture(config={"pretrigger": 8, "posttrigger": 247}, timeout=10.0)
fcapz_close()
```

Efinix Trion behind the serial TAP bridge:

```text
fcapz_connect(backend="serial", serial_port="COM5")
fcapz_capture(config={"pretrigger": 8, "posttrigger": 247}, timeout=10.0)
fcapz_close()
```

UART receive:

```text
fcapz_connect(backend="hw_server")       # the ELA session comes first
fcapz_connect(core="uart", backend="hw_server", chain=4)
fcapz_uart_recv(count=256, timeout=0.5)
fcapz_close(core="uart")
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tool says a write is disabled | Server was started without the matching safety flag. | Restart with the specific `--allow-*` flag, or keep read-only mode. |
| `program=` is rejected | Programming is disabled, outside `--bitfile-root`, not a `.bit`, or not `hw_server`. | Start with `--allow-program --bitfile-root DIR` and pass an allowed `.bit` file. |
| Tool call raises `TimeoutError` | The RPC watchdog (`--rpc-timeout`, 30 s by default) fired before the backend returned. | The board session is torn down, or is being torn down if the call was abandoned. Poll `fcapz_status` until `session_state` is `ready`, then call `fcapz_connect` again. Restart `fcapz-mcp` only if it never returns to `ready`. |
| A new tool call is refused while the session is recovering from an abandoned call (`session_recovering`) | A timed-out hardware call is still being torn down; `session_state` is `poisoned`. | Wait: once the abandoned call returns, the server closes the board session, clears its state and goes back to `ready`. Then reconnect. Restart only if recovery never completes. |
| `fcapz://last-capture` is unavailable | No capture has completed, or the payload was dropped/closed. | Run `fcapz_capture` again. |
| USB-Blaster rejects `host` | That backend does not use host/port sockets. | Omit `host`, `port`, and `tap` entirely for `usb_blaster`. |
| `serial_port ... is not a serial port on this machine` | The name is not one the OS lists, or the board is not in bridge mode yet. | Use a name from the error's `present:` list (or `fcapz list-ports`); program the FPGA first so the bridge enumerates. |
| `ftdi` connect finds no adapter, or the wrong one | Another program (OpenOCD, a vendor tool) holds the channel, or several adapters are attached. | Close the other program; pass `hardware` with the adapter's D2XX description or serial. |
| The next session cannot open the cable after an HTTP server went away | The server was killed rather than stopped, so its shutdown never closed the board session and a backend process (for example `quartus_stp`) may still hold the JTAG cable. | Stop an HTTP server with Ctrl-C, which closes every hardware connection. After a hard kill, end the leftover backend process before reconnecting. |
| HTTP client gets `401` | Missing, misspelled or wrong `Authorization: Bearer` header. | Send the exact token the server was started with (`FCAPZ_MCP_TOKEN` or `--http-token-file`). |
| HTTP client gets `421 Invalid Host header` | A loopback-bound server only accepts `127.0.0.1`, `localhost` or `[::1]` as the `Host`. | Connect by one of those names, or bind a network address with `--http-host` (plus TLS). |

## Related Chapters

- [Chapter 10 - CLI reference](10_cli_reference.md)
- [Chapter 11 - JSON-RPC server](11_rpc_server.md)
- [Chapter 14 - Transports](14_transports.md)
- [Chapter 15 - Export formats](15_export_formats.md)
