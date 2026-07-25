# 18 · Web interface (`fcapz-web`)

`fcapz-web` is a **browser-based front-end** for fpgacapZero — an alternative to
the desktop GUI ([chapter 12](12_gui.md)) that you can reach from the local
machine **or another machine on the network**. It is a small **FastAPI** server
that wraps the fcapz host stack and serves a prebuilt browser UI (Vite + React)
as static files, so running it needs **no Node.js** — just the Python package.

Under the hood it speaks the **same JSON-RPC `cmd` protocol** as the line
([chapter 11](11_rpc_server.md)) — one unified API, just a different transport.
There is no bespoke web protocol.

## Install and run

```bash
pip install -e ".[web]"     # adds fastapi + uvicorn to the host stack
fcapz-web                    # serves on http://127.0.0.1:7373
```

Open <http://127.0.0.1:7373>. Connection parameters (backend, host/port, an
optional tap — the IR table is inferred from the tap name) live in the UI, not
on the command line — one server can drive whatever board you point it at.

### Reaching it from another machine

```bash
fcapz-web --host 0.0.0.0 --port 7373 --token "$(openssl rand -hex 16)"
```

`--host 0.0.0.0` exposes it on the network. **Set `--token`** (or the
`FCAPZ_WEB_TOKEN` environment variable) whenever you do: it is then required as
`Authorization: Bearer <token>` on every `/api` route and as `?token=` on the
WebSocket, and the UI hides the token field until a server asks for it. There is
**no TLS** — put it behind a reverse proxy or an SSH tunnel if it leaves a
trusted network. `fcapz-web` prints a warning if you bind a non-localhost host
without a token.

Cross-origin API access is **off by default** (the bundled UI is same-origin,
and `npm run dev` proxies `/api`), so a random website cannot drive the board;
enable it only if you serve the frontend from a different origin, with
`--cors-origin`. When bound to a loopback address the server also rejects
requests whose `Host` header is not a loopback name (anti-DNS-rebinding).

| Flag | Default | Meaning |
|------|---------|---------|
| `--host` | `127.0.0.1` | Bind address; `0.0.0.0` to reach it from other machines. |
| `--port` | `7373` | HTTP port. |
| `--token` | `$FCAPZ_WEB_TOKEN` | Bearer token required on the API (unset = open). |
| `--static-dir` | bundled | Directory of built frontend assets to serve. |
| `--openocd` | `$FCAPZ_OPENOCD`, else `PATH` / known installs | Path to the `openocd` executable, to let the UI start OpenOCD. Auto-detected from `PATH` and common off-`PATH` installs (xPack, chocolatey) if unset, preferring a real `.exe` over a launcher shim. |
| `--openocd-cfg` | — | An OpenOCD config the UI may launch (repeatable; registered by filename stem). |
| `--openocd-cfg-dir` | `$FCAPZ_OPENOCD_CFG_DIR` | Auto-discover configs: register every `*.cfg` in this directory (repeatable; non-recursive). When neither this nor `--openocd-cfg` is given, the bundled `examples/*/` board configs are offered by default. |
| `--cors-origin` | — | Allow cross-origin API access from this origin (repeatable). Off by default. |

To enable the UI's "Start OpenOCD" convenience you need an `openocd` binary
**and** at least one config — and in the common case you supply **neither** flag.
The binary is found automatically on `PATH` and in known off-`PATH` installs
(xPack via `xpm` or a manual extract, chocolatey — preferring a real `.exe` over
a `.cmd`/`.bat` shim so the adapter is released cleanly on stop). Configs, when
you pass no `--openocd-cfg`/`--openocd-cfg-dir`, default to the repo's bundled
`examples/*/` board configs. So from a source checkout, plain `fcapz-web` is
enough: **Connect then discovers and brings OpenOCD up automatically** when no
board is reachable, so the user never manages the JTAG server (see below). You
can still point `--openocd-cfg-dir` at a folder of your own configs, or
`--openocd` at a specific binary. Only the discovered/listed configs can be
launched, and only from a **localhost** browser — a remote client cannot spawn
processes, even with a valid token.

None of this is required just to *use* the web frontend: without these flags you
simply connect to an already-running OpenOCD or hw_server via the backend/host/
port fields, and the "Start OpenOCD" button is hidden.

## The workspace

The UI is a **dockable tab layout** — drag any tab to reorder, split, stack, or
float it; the layout is yours to arrange. The **Tabs** menu in the top bar
toggles panels (checked = open; click to close or reopen), and **Reset layout**
rebuilds the default arrangement without reloading — the session stays
connected. The panels:

- **Connection** — Connect/Disconnect sit at the top of the panel, with a
  **Cancel** button while a connect or scan is in flight. Pick the backend
  (OpenOCD or Xilinx hw_server), host and
  port. For OpenOCD, Connect **discovers fpgacapZero-compatible boards** — it
  probes each tap for the ELA identity and sweeps a few TCL ports (one OpenOCD
  instance per board) — and fails only if none are found; one board connects
  automatically, several show a picker. If nothing is already running **and** the
  server has an OpenOCD binary + config available (`--openocd-cfg-dir` or
  `--openocd-cfg`, with the binary auto-detected on `PATH`), Connect
  **auto-discovers boards**: it reads each config's `ftdi vid_pid`, keeps only
  the configs whose USB adapter is actually plugged in, then starts OpenOCD per
  surviving config and probes each — so the user never picks a config or touches
  the JTAG server. One confirmed board connects straight through; several show
  the picker. (USB filtering is best-effort — without it every config is probed;
  and two configs sharing a VID/PID sort out by probing, the first to answer
  claiming the adapter.) hw_server needs no such step: XSDB starts a local
  hw_server itself. The BSCAN chain is **autodetected server-side** — the user
  never picks one.
- **Cores** — stacked with Connection; the dock **jumps to it once a connect
  lands**. Lists every core discovered on the target (the ELA, any EIO, and
  cores on other chains such as an AXI monitor) with their parameters; the
  core the session is bound to is marked **in use**, and any other capture
  core gets a **Use this core** button that switches to it in one click. EIO
  is also auto-discovered into its own panel on connect.
- **ELA** — the capture configuration: channel, pre/post-trigger window,
  segmented capture, and **probe definitions** (load a `.prob` file or type
  `name:width:lsb` lines to get named signals in the waveform and the
  Trigger tab).
- **Trigger** — its own tab, laid out like Vivado ILA's **Trigger Setup**.
  **+ Add probe…** appends a row to the trigger table — named probes when
  defined, otherwise the raw probe bits (`bit0`…`bitN`), so triggering needs
  zero setup. Each row is **Name | Operator | Radix | Value**: operators
  `==`/`!=`; radix **[B]** binary, **[H]** hex, **[U]** unsigned; values
  take **X** don't-care digits (binary and hex), and 1-bit probes in binary
  accept the edge tokens **R** (rising), **F** (falling), **B** (either
  edge). **Grouping:** tick the checkboxes on two or more rows and press
  **Group selected** to concatenate them into one field (top row = MSB), so a
  single value spans several probes — e.g. `{addr_hi, addr_lo} == 0x1234`. The
  ▲/▼ arrows set which member is the MSB, and **Ungroup** splits it back. A
  group takes `==`/`!=` with **X** don't-cares across the whole field and
  compiles to one comparator; the hardware compares the packed sample word, so
  grouped probes need not be adjacent. Every member must sit in the low 32 bits
  — **except on a `WIDE_TRIG` core** (e.g. the 160-bit AXI monitor), where a
  single value-match (`==`) or any-change row reaches the **full sample width**,
  so every field is listed and triggerable; `!=`/second-comparator combinations
  on fields above bit 32 still zero-extend and are refused with a clear message.
  A **Trigger condition** dropdown picks **Global AND / Global OR**,
  exactly like ILA. The table compiles onto the hardware (all `==` rows
  merge into one comparator pattern under AND; a second pattern, a `!=`, or
  an edge uses the sequencer stage's dual compare — `TRIG_STAGES ≥ 2`), and
  combinations the comparators can't express are refused with a message
  saying why. The raw trigger fields (mode/value/mask, external trigger,
  sequencer JSON) stay editable under **Advanced**.
- **Run** — a fixed one-row toolbar strip sitting between the config tabs
  and the waveform viewer (a headerless, fixed-height dock group — no tab,
  can't be resized or covered): **Arm** (trigger-gated capture), **Trigger
  Immediate** (force a capture now), **Auto re-arm** (continuous re-arming
  loop), **Stop**, and a single **Download…** picker exporting the last
  capture as VCD, CSV or JSON.
  While armed, the status shows a pulsing **armed - waiting for trigger**
  indicator until the condition fires (or Stop disarms). Armed waits have
  **no deadline**: the core is armed once and polled, so the trigger can
  come an hour later — nothing times out and nothing is missed in between.
- **Viewer** — an embedded **[Surfer](https://surfer-project.org/)** waveform
  viewer (runs entirely in the browser via WebAssembly). **Every capture core
  gets its own viewer tab** ("Viewer: ELA", "Viewer: AXI Mon", …), each holding
  that core's last capture — switching cores never overwrites another core's
  waveform, and **clicking a viewer tab re-binds the session to its core**, so
  the ELA/Run tabs immediately drive what you're looking at. Each capture's
  signals are added automatically; subsequent captures reload the data in
  place, so the same view and zoom are preserved.
- **EIO** — read fabric inputs (with a selectable poll rate) and drive outputs
  live.
- **AXI** — attach the JTAG-to-AXI4 bridge on a chain, then single 32-bit
  read/write (with `WSTRB`) and block dump, with an operation log.
- **AXI Mon** — when the target has an [AXI monitor](19_axi_monitor.md)
  anywhere, this tab shows its geometry and builds AXI-aware triggers:
  transaction-event checkboxes on decode builds (`any_err`, handshakes, …) or
  a write-address match otherwise. Applying a trigger or the probe map
  automatically re-binds the session to the monitor if it wasn't the active
  core; the probe map is auto-applied so captures decode to named AXI fields.

## The API behind it

The browser is just another consumer of the unified JSON-RPC API. Two transports
expose the **same** command set:

| Transport | Endpoint | Shape |
|-----------|----------|-------|
| HTTP | `POST /api/rpc` | body is one request `{"cmd": ...}`; returns the response envelope |
| WebSocket | `/api/ws` | send request objects, receive response objects (lower latency; suited to scripted live polling — the bundled UI itself uses `POST /api/rpc`) |

Every command and field is exactly the contract in
[chapter 11](11_rpc_server.md): `connect`, `probe`, `capture`, `eio_*`,
`axi_*`, `uart_*`. **Errors are in-band** (`{"ok": false, "error": ...}`), so a
bad command still returns HTTP 200 — matching the line-protocol semantics. You
can drive the server with `curl` exactly as you would pipe JSON to
`python -m fcapz.rpc`:

```bash
curl -s localhost:7373/api/rpc -H 'Content-Type: application/json' \
  -d '{"cmd":"connect","backend":"openocd","tap":"GW1NR-9C.tap"}'   # ir_table and chain are inferred
curl -s localhost:7373/api/rpc -H 'Content-Type: application/json' -d '{"cmd":"probe"}'
```

One physical board is one serialized session: a re-entrant lock guards the single
`RpcServer`, so multiple connected browsers share it safely, and blocking JTAG
work runs in a threadpool so the event loop stays responsive while a capture
waits for its trigger.

## Building the frontend (contributors)

Running `fcapz-web` never needs Node — the built bundle ships in the package. You
only need Node to **change** the UI. The source lives in `web/frontend/`; during
development run the Vite dev server, which proxies `/api` and `/surfer` (the
Viewer's waveform iframe) to the backend:

```bash
cd web/frontend && npm install && npm run dev   # http://localhost:5173
fcapz-web                                        # backend on :7373
```

For a release build, `npm run build` outputs to `host/fcapz/web/static/` (which
`fcapz-web` serves and which ships in the wheel as package data). The bundle uses
stable filenames, so a rebuild is a clean diff. The vendored Surfer WASM viewer
lives under `host/fcapz/web/vendor/surfer/` (EUPL-1.2; see its `NOTICE.md`) and
is served at `/surfer`, decoupled from the Vite output.

## See also

- [Chapter 11 · JSON-RPC server](11_rpc_server.md) — the full command schema the
  web UI speaks.
- [Chapter 12 · Desktop GUI](12_gui.md) — the PySide6 alternative.
- [Chapter 15 · Export formats](15_export_formats.md) — what the downloaded
  VCD / CSV / JSON contain.
