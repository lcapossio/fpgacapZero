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
| `--read-only` | Disables `fcapz_configure`, `fcapz_arm`, `fcapz_capture`, and all write/send/program enable flags. |
| `--allow-eio-write` | `fcapz_eio_write` |
| `--allow-axi-write` | `fcapz_axi_write`, `fcapz_axi_write_block` |
| `--allow-uart-send` | `fcapz_uart_send` |
| `--allow-program --bitfile-root DIR` | `fcapz_connect(program=...)` for `.bit` files under `DIR` |

`--read-only` cannot be combined with any write/program enable flag.

Programming is intentionally `hw_server`-only in the MCP layer.

If `program` is passed while programming is disabled, the server reports the
permission error before backend-specific validation so agents see the global
safety policy first.

## Backends And Connection Fields

The branch's live RPC layer supports:

| Backend | Target fields | Optional fields |
| --- | --- | --- |
| `hw_server` | `host`, `port`, `tap` | `program`, `single_chain_burst` defaults to `true` |
| `openocd` | `host`, `port`, `tap` | - |

The MCP layer also validates and forwards newer backend-specific fields for
compatibility with transports on adjacent branches:

| Backend | Target fields | Optional fields |
| --- | --- | --- |
| `usb_blaster` | `hardware`, `quartus_stp` | - |
| `spi` | `spi_url` | `spi_frequency`, `spi_cs`, `spi_timeout` |

Backend-irrelevant fields are rejected instead of being silently forwarded.
`hw_server` and `openocd` default `host` to `127.0.0.1` when omitted. `spi` and
`usb_blaster` have no host concept, so even explicit `host="127.0.0.1"` is
rejected.

The MCP session enforces a 30 second RPC response timeout by default; override
it with `--rpc-timeout SEC`. Backend transports may also have their own
timeouts; whichever timeout is shorter fires first. If the MCP timeout fires,
the server asks the RPC layer to cancel active transports and treats that as a
session-wide reset: ELA, EIO, AXI, UART, cached probe data, and cached capture
data are all cleared if the worker unwinds. Xilinx `xsdb` sessions are killed
quickly and OpenOCD sockets are closed; other backends use best-effort
`close()`. If a backend cannot be cancelled promptly, the server refuses new
hardware commands until the process is restarted. `--rpc-cancel-grace SEC`
controls how long the MCP layer waits for the worker to unwind after
cancellation before declaring it still active. It must be greater than zero.
Transport construction is still best-effort: if a backend blocks before a
transport object exists, cancellation cannot nudge that backend directly and the
same still-running worker guard applies.

## Tools

### Session and ELA

| Tool | Requires | Purpose |
| --- | --- | --- |
| `fcapz_status` | always available | Return session state, safety capabilities, MCP server version, and RPC schema version. |
| `fcapz_connect` | none for plain connect; `--allow-program` if `program=` is set | Connect to an ELA core. |
| `fcapz_close` | always available | Close the active ELA connection. Idempotent. |
| `fcapz_probe` | connected ELA | Read ELA identity, dimensions, and feature registers. |
| `fcapz_configure` | capture* | Configure the connected ELA without arming. |
| `fcapz_arm` | capture* | Arm the connected ELA using the current hardware configuration. |
| `fcapz_capture` | capture* | Configure, arm, capture, and cache the full capture payload. Returns summary metadata only. |
| `fcapz_get_last_capture` | always available | Return the cached full capture payload for clients without resource support. Defaults to a 1 MiB guard. |
| `fcapz_get_last_capture_chunk` | always available | Return a bounded JSON text chunk of the cached capture payload. |
| `fcapz_drop_last_capture` | always available | Drop the cached full capture payload and report whether one existed. |

`capture*` tools are enabled by default and blocked by `--read-only`.

`fcapz_capture` takes `include_event_summary` to ask the RPC layer for decoded
event metadata. The MCP name is deliberately more explicit than the RPC field
name (`summarize`).

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
bit 0 controls the lowest byte.

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

Large captures stay in memory until the next capture, `fcapz_close`, or
`fcapz_drop_last_capture`. Resource-aware clients should prefer
`fcapz://last-capture`; tool-only clients should prefer
`fcapz_get_last_capture_chunk(offset=0, max_bytes=65536)` and follow
the byte `next_offset` until it is `null`. Chunks are UTF-8 JSON text and never
split a multibyte character; callers must pass either `0` or a returned
`next_offset`, because offsets in the middle of a UTF-8 character are rejected.
`fcapz_get_last_capture` has a 1 MiB default guard and returns a compact
truncation marker for larger captures unless `max_bytes=null` is passed as an
explicit escape hatch.

## Status Fields

`fcapz_status` and `fcapz://status` include:

| Field | Meaning |
| --- | --- |
| `mcp_server_version` | The installed fpgacapZero package version. |
| `rpc_schema_version` | The RPC schema version. It is seeded before the first RPC and updated from successful RPC responses. |
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
fcapz_get_last_capture_chunk(offset=0, max_bytes=65536)
repeat with next_offset until null
fcapz_drop_last_capture()
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
| SPI or USB-Blaster rejects `host` | Those backends do not use host/port sockets. | Omit `host` entirely for those backends. |

## Related Chapters

- [Chapter 10 - CLI reference](10_cli_reference.md)
- [Chapter 11 - JSON-RPC server](11_rpc_server.md)
- [Chapter 14 - Transports](14_transports.md)
- [Chapter 15 - Export formats](15_export_formats.md)
