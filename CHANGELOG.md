# Changelog

All notable changes to this project are documented in this file.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added

- **Core manager — resets a host can see, and a checked burst header.** New
  manager registers: `MGR_EPOCH` and `MGR_SLOT_EPOCH` count both edges of the
  hub and per-slot resets (odd while a reset is held), `MGR_TLR_COUNT` counts
  TAP Test-Logic-Reset entries (all never reset), `MGR_OWNER` holds an
  advisory owner token, and `MGR_CTRL` resets the hub, one slot or every slot.
  The priming scan of a burst now carries a header (magic, slot, start
  pointer, window, both epochs, owner, sample width) instead of a stale word.
  The host checks the header against what it read before the burst (the
  advisory owner only against another session's token), re-reads the epochs (and, where Test-Logic-Reset cancels bursts,
  `MGR_TLR_COUNT`) after it, and raises `BurstIntegrityError` when the burst
  is not the one it asked for or a reset hit it. `Analyzer` holds its slot,
  the slot epoch and the hub epoch from `configure()` through the readout and
  raises `ManagerResetError` when the slot was reset, the hub was reset during
  a readout, or (with no `instance`) the active slot moved; a wait that times
  out after a slot reset says so. A failed `configure()` leaves the analyzer
  unconfigured. `CaptureChangedError` reports a capture whose `SEG_START`
  moved during its readout. The host writes its owner token when it first
  selects a slot, warns about another token, and clears it on close; a
  reconnect or a new bitstream drops the claim and identifies the managers
  again. The hub
  shells take `TLR_RESET_EN` (default 0) to make Test-Logic-Reset also reset
  the burst protocol; leave it 0 behind Xilinx `hw_server`, which walks the
  TAP through Test-Logic-Reset between scans. `MGR_CAPS` bits 3-6 report each feature. Both HDLs,
  all three vendor shells.

- **ELA — `DATA_OFFSET` pages the DATA window.** The DATA and timestamp
  windows are register addresses, so they ended at `0xFFFF`, or at `0xF000`
  behind a core manager: a deep core without burst readout could not be read
  in full, and the hub refused to build one. The new `DATA_OFFSET` register
  (`0x00F4`, `COMPARE_CAPS` bit 20) adds a word offset to every window read,
  and the host pages reads past the limit through it. Arming or resetting the
  ELA sets it back to 0, so an offset a host left behind cannot shift the
  next capture. Reads keep no side
  effects, so every transport's window readers work unchanged. The hub's
  `0xF000` elaboration check is gone. Both HDLs.

- **Core manager — `MGR_SELECT_COUNT` reveals another controller's select.**
  A new read-only register (`0xF034`, `MGR_CAPS` bit 7) counts every
  `MGR_ACTIVE` write, refused ones too, and is never reset. Another
  controller that selected a slot during an analyzer's `configure()`,
  `arm()`, `reset()` or readout and then selected the analyzer's slot back left nothing
  to see: some writes or reads went to the other slot. The transport now
  counts its own `MGR_ACTIVE` writes, and `Analyzer` compares the difference
  across each of those operations and raises `ManagerResetError`. An analyzer
  with an `instance` also reads `MGR_ACTIVE` and refuses another slot there.
  Older hubs get the `MGR_ACTIVE` check only. Both HDLs.

- **ELA — `CAPTURE_GEN` identifies a capture.** A new read-only register
  (`0x00F8`, `COMPARE_CAPS` bit 21) counts every `CTRL` arm or reset write and
  every release of the core's register-side reset (two when both land in
  one cycle), and is never reset.
  `SEG_START` could not tell captures apart: a re-arm by another controller
  during a readout, or between `arm()` and the readout, can leave it where it
  was while new samples overwrite the buffer. `Analyzer.arm()` now expects
  `CAPTURE_GEN` to move by exactly one, and the readout expects the value
  `arm()` left and compares it across the readout; either raises
  `CaptureChangedError`. Standalone ELAs too. Cores without bit 21 are read
  as before. Both HDLs.

- **Formal parity — power-up values.** The Verilog/VHDL parity proofs matched
  registers by name and assumed equal states, so they never compared
  power-up values. Each configuration now also compares the state of every
  register after the reset the proofs assume, which covers the registers the
  reset does not clear (counters, synchronisers). GHDL keeps the power-up
  value of an async-reset flop on an alias that yosys `proc` drops, so the
  check keeps it under its own attribute first. `reset_sync` is compared
  without a reset, since its power-up value is its contract.

- **Host — core discovery.** `fcapz discover`, the RPC `discover` command and
  `fcapz.discovery.discover_cores()` list every fcapz core without being told
  a chain: ELAs, EIOs, AXI monitors, a core manager and each of its slots, and
  the EJTAG-AXI and EJTAG-UART bridges. A chain is read only at `0x0000`, a
  NOP on both bridges, until it answers as an ELA or EIO. A new bench,
  `fcapz_bridge_discovery`, shifts those scans into both bridges and checks
  that nothing moves. `list_cores` now lists the manager and its slots.

- **Core manager on every vendor.** The multi-core hub is now three layers:
  `fcapz_debug_multi_core` (manager and ELA/EIO slots, no JTAG),
  `fcapz_debug_multi` (TAP signals, reset sync and the JTAG pipe) and a thin
  vendor shell that only adds the TAP primitive. New shells
  `fcapz_debug_multi_xilinxus` (UltraScale `BSCANE2`) and
  `fcapz_debug_multi_intel` (`sld_virtual_jtag`, `CTRL_CHAIN` is the instance
  index) join `fcapz_debug_multi_xilinx7`, which keeps its parameters, ports
  and behaviour. Each has a VHDL twin. cocotb drives all three shells at their
  TAP primitives in both HDLs, static and formal parity cover the new layers,
  and an old-vs-new simulation of the Xilinx-7 wrapper matched. The layers are
  in every Arty build, the LiteX source lists and `core.json`.

- **DE25-Nano — core-manager variant.** `de25_nano_manager_top` puts two ELAs
  and two EIOs behind one `fcapz_debug_multi_intel` hub on instance 1, with
  EJTAG-AXI on instance 4 (`python examples/de25_nano/build.py --variant
  manager`). `test_hw_manager.py` covers slot enumeration, captures with
  timestamps across many burst packets, slot switches after a burst, both EIO
  slots and the bridge.

- **Host — managed bursts on USB-Blaster.** The Quartus transport reads ELA
  bursts from a separate data instance, but a managed hub bursts on its own
  instance. The analyzer now sends a managed slot's burst and timestamp reads
  through the hub's instance (`Transport.burst_on_data_chain` marks
  transports that need this) instead of the data instance.

- **Kria KV260 reference design and hardware test.** `examples/kv260/`
  puts a core on every BSCANE2 USER chain of the K26 SOM (`xck26`): the
  multi-core manager (two ELAs, one with a 4-stage sequencer, storage
  qualification and relational compares, and two EIOs) on USER1, the AXI
  monitor on USER2, the `_xilinxus` JTAG-UART on USER3 and the `_xilinxus`
  AXI bridge on USER4. `pl_clk0` comes from the PS through a minimal block
  design. The pytest suite programs the board through RPC `connect` and
  exercises each core over hw_server's `-register` mode, plus the RPC
  connect paths the web UI and MCP server use. `python
  examples/kv260/build.py` builds it.

- **MCP — multi-stage trigger sequences.** The capture `config` takes
  `trigger_sequence`, one typed object per sequencer stage (compare modes
  `0`-`8`, `combine` `0`-`3`, `next_state` `0`-`3`), so a core built with
  `TRIG_STAGES > 1` can be driven from an agent as it already could from RPC.

- **MCP — `fcapz_connect` takes `ir_table`.** For `hw_server` and `openocd`
  it names the JTAG IR-code preset (`xilinx7`, `ultrascale`, `gowin`) when the
  tap name does not identify the family; omitted, RPC still infers it.

- **MCP — run-length captures and the storage-qualification modes.** The
  capture `config` takes `rle` and `post_clocks`, and `stor_qual_mode` is now
  the enum `0`/`1`/`2` (off, store on match, store on no match) in the
  published schema. On a run-length capture each sample record and search
  match carries `clock` and `run_length`, and a burst's `length` counts
  clocks, so a stored entry is never read as one clock.

- **MCP — authenticated HTTP transport.** `fcapz-mcp --transport http` serves
  streamable HTTP at `/mcp` for a remote bench. Every request needs
  `Authorization: Bearer <token>`, with the token taken from
  `FCAPZ_MCP_TOKEN` or `--http-token-file` (never the command line; at least
  16 characters). It listens on `127.0.0.1:8765` by default
  (`--http-host`/`--http-port`); a non-loopback address requires TLS
  (`--http-tls-cert`/`--http-tls-key`) or an explicit `--http-insecure`. All
  HTTP clients share the one hardware session.

- **MCP — `--axi-write-range LO:HI` confines AXI writes.** Repeatable; it
  implies `--allow-axi-write` but only for the named inclusive byte ranges,
  so an agent can be given a peripheral's register window rather than the
  whole bus. A write with any byte outside is refused whole with
  `not_permitted`, naming the word and the allowed ranges; `fcapz_status`
  reports them as `capabilities.axi_write_ranges`. Reads are unaffected.

- **MCP — search a capture instead of paging it.** `fcapz_find_in_capture`
  finds the edges of a named field, rising/falling edges of a bit, every
  sample matching a value under a mask, or runs of one value (optionally at
  least `min_length` long), and returns them paged with `total`,
  `first_position` and `last_position` — so "the first sample where X == v" is
  one call. Each hit carries the position `fcapz_get_capture_samples` takes,
  and its offset from the trigger. Segmented captures are searched per
  segment, and wide values stay exact. `fcapz_get_capture_samples` also gains
  `around_trigger=N` for the window either side of the trigger.

- **Segmented captures are reachable from MCP.** `fcapz_capture` and
  `fcapz_capture_wait` take `segments=true` to read back every segment
  instead of segment 0; sample paging concatenates them, tags each sample
  with its segment, and resolves named fields from the per-segment probe map.

- **Wide EIO vectors survive a JavaScript MCP client.** `fcapz_eio_read`
  returns `value` as a hex string past 53 bits so it cannot disagree with
  `value_hex`, and `fcapz_eio_write` accepts a base-prefixed string, which is
  the only way such a client can drive a wide output exactly.

- **The MCP tool schema is typed.** `backend`, `format`, `radix`, `kind` and
  `trigger_mode` are `enum`s in the published schema instead of strings
  validated after the call, and capture `config` is a named object with a
  type per field instead of an open dictionary. The accepted key set is
  derived from that schema, so the two cannot drift. Costs roughly 2k tokens
  of tool surface in the default profile, and buys client-side rejection of
  values that previously needed a round trip to refuse.

- **Four MCP tools declare a real `outputSchema`.**
  `fcapz_get_capture_samples`, `fcapz_axi_transactions`,
  `fcapz_get_last_capture_chunk` and `fcapz_status` now publish their result
  shape instead of `{"additionalProperties": true}`, and each returns one
  fixed shape — every field always present, `null` where it does not apply —
  so a caller never branches on which keys exist. The remaining tools pass an
  RPC response through verbatim and stay open on purpose: MCP drops any field
  an `outputSchema` does not name, so declaring a subset of a response whose
  keys vary by backend and core would silently delete the rest.

- **MCP failures carry a code and a remedy.** A failed tool call reaches an
  agent as text and nothing else, so every failure is now rendered as one
  JSON object — `code`, `message`, `retryable`, `action`, plus the backend's
  own error as `detail` — instead of prose to pattern-match. Twelve codes, with
  `busy` and `session_recovering` tagged where they are raised so a reworded
  message cannot reclassify them, and `watchdog_timeout` kept distinct from
  `timeout` because only one of them requires reconnecting first.

- **Long captures report progress.** `fcapz_capture` and
  `fcapz_capture_wait` emit an MCP progress notification once a second while
  they wait — elapsed time against the caller's timeout, which is the only
  honest measure available from inside a JTAG readout. Clients that do not
  send a progress token are unaffected.

- **The AXI decoder is reachable from the CLI and the web UI.**
  `fcapz axi-decode CAPTURE` reassembles a saved capture JSON into AXI4-Lite
  transactions offline — no board, no connection — with `--only-anomalies`,
  `--kind`, `--limit` and `--json`; the probe map is inferred from the
  capture's recorded sample width. `fcapz capture --decode-axi` prints the
  same table straight after a live capture, and the web UI gains an **AXI
  Txn** tab showing the last capture as transactions with faulty rows
  highlighted. Previously the decoder had exactly one consumer, the MCP
  server.

- **Structured capture paging.** `fcapz_get_capture_samples` returns whole
  sample records — sliced into named fields from the capture's probe map, with
  `total` and `trigger_index` on every page — so each page is valid JSON on
  its own. The byte-chunk tool stays for verbatim export and csv/vcd
  captures, where its chunks must be concatenated before any of it parses.
  RPC `capture` now echoes the probe map alongside the samples, so any
  consumer can slice fields without re-deriving the layout.

- **AXI transaction decoding.** A host-side pass (`fcapz.decode_axi`)
  reassembles an AXI monitor capture from per-cycle samples into whole
  AXI4-Lite transactions: address, data, byte strobes, response, the cycle
  each beat landed on, latency, per-channel stall counts, and protocol
  anomaly flags (`error_response`, `partial_write`, `data_before_address`,
  half-formed writes, unaligned addresses). AXI4-Lite has no IDs, so
  responses are paired first-in-first-out; the result states that assumption
  and flags every transaction whose pairing a mid-flight capture window could
  have shifted. Legal-but-notable behaviour is reported separately from
  protocol faults. Works
  on both `DECODE_EN` and plain monitor builds, since a beat is `VALID &
  READY` either way. RPC `capture` attaches it on request (`decode_axi`), and
  the MCP server exposes `fcapz_axi_transactions` to page and filter it —
  answering "why is this write corrupt?" directly instead of returning a
  sample dump to interpret.

- **MCP server (`fcapz-mcp`).** A stdio MCP server that exposes the lab
  controls to coding agents: connect/probe/configure/arm/poll and capture for
  the ELA, EIO read/write, AXI read/write (single and bounded block), and UART
  send/receive. Session state is published as `fcapz://` resources (status,
  last probe, last capture, last EIO read). Every write-side operation is off
  by default behind an explicit capability flag — `--allow-eio-write`,
  `--allow-axi-write`, `--allow-uart-send`, and `--allow-program` (which can be
  confined to a `--bitfile-root`) — and `--read-only` drops the mutating tools
  at once. Payloads are bounded so a large capture or block read cannot flood
  the agent's context: captures are chunked from an atomic snapshot and AXI
  block ops are capped. All hardware commands run on a single owner thread
  that performs each RPC and its session-state update as one step, so a
  concurrent caller is refused with a `busy` error rather than interleaving,
  and a command abandoned after the watchdog tears the session down instead of
  committing late (`session_state` reports `ready`/`busy`/`poisoned`).
  Sample values wider than 53 bits are returned as hex
  strings (`"value_encoding": "hex"`) so they survive clients that parse JSON
  numbers as doubles. The MCP SDK is an optional dependency:
  `pip install fpgacapzero[mcp]`. See [MCP server](docs/20_mcp_server.md).

- **Run-length capture (`RLE_W`).** A new ELA parameter (0 or 1..16, default 0)
  adds a run-count RAM so one buffer entry holds a sample and how many sample
  clocks it repeated, up to `2^RLE_W`. Idle or slow signals then cover far more
  time in the same `DEPTH`. Turned on per capture with `CaptureConfig.rle`,
  `fcapz capture --rle`, the RPC `rle` field, or a checkbox in the GUI and web
  interface. Results gain `run_lengths`; VCD, the previews and the web viewer
  place entries at their start clocks, and `expand_run_lengths()` restores one
  sample per clock; a VCD ends where the last run does. Pre/post-trigger
  windows count entries. Counts read back on the timestamp burst lane (`BURST_PTR[31:30]=2'b11`) or the USER1 timestamp
  window. New registers `RLE_CTRL` (0x00A8) and `RLE_W` (0x00CC). An optional
  post-trigger clock limit (`RLE_POST_CLKS`, 0x0090; `CaptureConfig.post_clocks`,
  `--post-clocks`, RPC `post_clocks`, GUI and web fields) also ends the window
  N sample clocks after the trigger, so a quiet signal cannot hold it open.
  Both HDLs and all standalone ELA wrappers; `RLE_W=0` builds and behaves
  exactly as before. Not combinable with decimation or storage qualification. The DE25-Nano
  reference design builds with `RLE_W=16` and a second ELA channel that holds
  each value for 8 clocks, and is hardware-validated with it. An AXI monitor
  capture taken run-length decodes into transactions: the decoder expands
  each entry back to the clocks it held (up to 1M cycles), so cycle numbers
  and latencies count sample clocks.
- **Web GUI — `serial` backend.** The byte-stream TAP bridge is now selectable
  in the browser, not just from the Python API. It takes a serial port and baud
  rate in place of host/port/tap, and skips JTAG discovery entirely — the
  bridge's own identity probe reports a wrong port instead of returning
  garbage. Verified end to end against a Forgix board: `connect` -> `probe` ->
  `capture` returns a clean 1,024-sample ramp. The port is picked from a list
  the server enumerates (`list_serial_ports`), which identifies ports without
  opening any of them — opening one asserts DTR and resets an RP2040/RP2350,
  and a developer machine usually has unrelated JTAG cables and vendor probes
  enumerated as serial ports too.

- **Serial backend — hardened after review.** Remote clients on a token-less web
  server can no longer enumerate or open serial ports (an unauthenticated way to
  reset every board and probe on the host), nor send any session command while
  a serial session is open — checked under the session lock against the open
  session, since `capture` or `close` names no backend; loopback and
  authenticated remote clients are unaffected. A failed handshake now closes the port instead of
  leaking an exclusive handle, and a failed `connect` closes the transport the
  session never took ownership of. The burst chain is excluded from the generic
  core sweeps — it carries a streaming DR, not registers, and a magic word
  appearing in burst data could otherwise be reported as a core. EIO/AXI/UART
  side connections are refused with an explanation rather than an OS
  port-in-use error, and both panels say so. Baud rates are validated
  server-side. The port picker is a datalist, so the value is always visible and
  a typed path still works.

- **`connect` reports the link, not just the preset.** The reply carries
  `transport_kind` (`jtag` / `bytestream`) and a `link` object with the
  byte-stream bridge's negotiated protocol version, chain count, DR width and
  baud rate, so the web GUI can show `COM16 @ 1,000,000 baud · bridge v2 · 2
  chains · 64-bit max DR` instead of a stale JTAG host and port. `ir_table` is
  now **null** on a serial session rather than the sentinel string `"serial"` —
  it was occupying an IR-preset field with a value that is not a preset, and an
  arbitrary one supplied by a client was echoed back unvalidated.

- **CLI — `serial` backend and `fcapz list-ports`.** `--backend serial
  --serial-port COM16 [--baud N]` drives the byte-stream TAP bridge from the
  command line, and `list-ports` names the machine's serial ports without
  opening any of them. One CLI run builds one transport, so `eio-*`, `axi-*`
  and `uart-*` work over serial here even though the web session refuses them.
  Baud validation is now shared by every front end
  (`transport.validate_baudrate`).

- **Web — Log tab.** Backend diagnostics (JTAG readback, connection, transport
  warnings) are captured into a bounded ring and served at `GET /api/logs`; the
  browser tails them in a Log panel that sits as an auto-hiding hover-drawer
  under the waveform (pin it to keep it open), with Pause, Clear, and
  auto-scroll. The RPC gateway logs each command with timing and the analyzer
  logs burst-readback success/fallback, so the fast path is visible, not silent.
- **Web — saved dock layouts.** The current panel arrangement auto-persists
  across reloads, and a **Layout** menu saves, loads, and deletes named layouts
  (localStorage).
- **Web — connected FPGA shown on the Connection panel.** The status line now
  leads with the actual device the backend opened (family/part + IDCODE), not
  just the vendor.
- **Virtual JTAG TAP over a byte stream — support for boards with no fabric
  JTAG.** New `fcapz_tap_bridge` reproduces the fpgacapZero TAP contract
  (`tck`/`tdi`/`tdo`/`capture`/`shift`/`update`/`sel`) from a framed byte
  stream, so `jtag_reg_iface`, `jtag_burst_read`, `fcapz_ela` and `fcapz_eio`
  run unchanged with no hard TAP block. Protocol and physical layer are split
  on both sides: `fcapz_uart_tap` is a UART PHY around the bridge, and the host
  `SerialTapTransport` is a pyserial backend over a generic
  `TapBridgeTransport` that owns the wire format, identity probe and register
  semantics. A new link type (SPI, USB-FIFO, TCP) needs only a PHY on each
  side. `fcapz_ela_uart` wraps it (chain 1 = control, chain 2 = burst), and
  `read_block()`/`read_timestamp_block()` use that burst chain the same way the
  Xilinx and Intel transports do — 8 8-bit samples per 64-bit scan, ~1.05
  bytes per sample on the wire against ~48 for per-word reads. Bridge protocol
  2 adds `CMD_BREAD`, which runs a whole burst's worth of scans under one
  command and one reply, removing a USB round trip per scan — and with it the
  reason to scan wide, since a batched reply packs samples under one shared
  header at any width. `fcapz_ela_uart` therefore defaults `BURST_W` to 64
  rather than the 256 the hard-TAP wrappers use, which on a Trion T8F49 is
  ~620 fewer logic cells and ~590 fewer registers for a marginally *smaller*
  byte count on the wire. Any `SAMPLE_W` or `TIMESTAMP_W` up to the burst DR
  is read over the burst chain, unpacked at the core's own width (read before
  every burst), so 20- or 48-bit cores and 48-bit timestamps need no window.
  `burst_start_sync` is honoured, so a core behind an older multi-slot core
  manager bursts the selected slot, as on the JTAG transports.
  pyserial is an optional extra (`pip install 'fpgacapzero[serial]'`). Covered
  by `tb/fcapz_uart_tap_tb.sv` and `tests/test_serial_tap_transport.py`, plus
  lint targets.
- **Byte-stream TAP — recovers from a lost byte without a board reset.** A
  command that stalls mid-parse for `RX_TIMEOUT_US` (10 ms by default, a
  `fcapz_uart_tap` / `fcapz_ela_uart` parameter; 0 disables it) is dropped
  silently, before its scan starts. Previously the parser waited for the
  missing bytes and read the next command into them. After a failed
  transaction the host waits for 50 ms of silence and discards any late
  reply, so it is not read as the next command's header; a link that will not
  go quiet raises `ConnectionError` on every later command until reconnected.
  The serial `timeout` now bounds silence, not the whole reply: a reply is
  read while its bytes keep arriving, so a long burst on a slow link or a slow
  fabric clock is not cut short.
- **Byte-stream TAP — a failed burst raises instead of falling back.**
  `SerialTapTransport.read_block()` / `read_timestamp_block()` used to catch a
  failed burst, switch burst off for the session and re-read through the
  register window. They now raise, like the JTAG transports. On a core built
  with `USER1_DATA_EN=0` the window reads zeros, so the fallback could turn a
  link fault into a capture of zeros. `read_window_block()` reads only the window.
- **Forgix — register-window readout dropped (`USER1_DATA_EN=0`).** Samples
  come back over the burst chain only, which saves 64 LE (2,103 LE, 28.5 %).
  Verified on hardware: a burst returns the ramp, and a window read returns zeros.
- **Forgix board example (Efinix Trion T8F49 + RP2354) — validated on
  hardware.** Ships a complete Efinity project (`examples/forgix/efinity/`)
  with the pin assignments worked out and confirmed: `clk_in` on B4 (32 MHz),
  `uart_rxd` on CCK/F3, `uart_txd` on CDI0/F2. On a real board the FPGA
  configures, the bridge identity and ELA registers read back, and a
  1024-sample capture returns a clean ramp over the burst chain in ~16 ms.
  The board exposes no
  JTAG to the fabric at all — the T8 is configured over a write-only passive
  SPI link and its JTAG pins are bonded out nowhere — and the T8F49 package has
  no JTAG User TAP blocks, so `fcapz_ela_efinix` cannot be used on it.
  `examples/forgix/` builds on the byte-stream TAP instead and
  needs **no extra wiring**: it reuses the configuration SPI pins, which go
  idle once `DONE` is high (CCK and CDI are dual-purpose pins, reusable as
  general I/O in user mode per Efinix AN006 Table 3). Includes a reference top
  and a locally vendored patch (pinned upstream revision, applied to a local
  copy) that turns the RP2354 bitstream loader into a transparent USB-CDC
  bridge after configuration. The README opens with a quick start that ends in
  a CLI capture, checked on the board, and a matching Python example. It also
  says where to get the upstream loader host tool. A clean checkout rebuilds a bitstream bit-identical to the
  one tested, and the vendored patch reproduces the firmware sources running on
  the board.
- **Efinix (Trion / Titanium) ELA wrapper.** New `fcapz_ela_efinix` (Verilog +
  VHDL) maps the two hard JTAG User TAP blocks a Trion device exposes onto the
  control and burst chains. Because the Efinix JTAG User TAP is an Efinity
  Interface Designer block (not an RTL primitive), the wrapper exposes the two
  TAP port groups (`jtag1_*`, `jtag2_*`) for top-level wiring. Host support
  rides the existing OpenOCD transport via a new `IR_TABLE_EFINIX` preset
  (auto-selected for `--tap trion.../titanium.../efinix...`) wired into
  discovery, RPC, and CLI; lint self-test targets added. The Verilog wrapper
  synthesizes, places and routes in Efinity 2025.1 on a Trion T20F256 and a
  Titanium Ti60F225 (the VHDL one on the T20F256), with both User TAP blocks
  bound and timing met. The USER1/USER2 opcodes match Efinity's BSDL for both
  families. Hardware validation is pending.

- **Direct FTDI JTAG transport (`--backend ftdi`).** `FtdiMpsseTransport`
  drives an FTDI MPSSE cable through FTDI's D2XX library, with no OpenOCD or
  vendor server. On Windows that is the driver the embedded FlashPro5 and
  Digilent cables already use, so PolarFire boards need no driver swap. The
  transport reads the IDCODE and IR length and picks the IR table (PolarFire,
  AMD/Xilinx 7-series, Gowin) and the burst default from them. It is offered
  by the CLI (`--hardware`, `--tck-mhz`), the RPC server, the desktop GUI and
  the web UI. Sessions in one process share the channel. On the PolarFire
  Discovery Kit all 11 hardware tests pass, a register read takes 0.14 ms and
  a 1024-sample burst 3 ms. On an Arty A7 the Digilent channel identifies the
  device; AMD/Xilinx register and burst access over this transport are not
  yet hardware-validated.

- **Burst readback over OpenOCD.** `OpenOcdTransport(burst=True)` reads
  captures through the ELA's 256-bit burst engine, with the `BURST_PTR`
  write and every scan in one Tcl command line, which no other Tcl client
  can interleave. Behind a core manager the line selects its slot first, and
  the burst is drained and header-checked as on `hw_server`. Run-length
  counts burst as well. It is on by default for the PolarFire preset only. Other
  presets opt in with the CLI's new `--burst` or the RPC's `"burst": true`,
  and `--two-chain-burst` / `--no-burst` now apply to OpenOCD as well. On
  the PolarFire Discovery Kit a 1024-sample capture read back in 3.4 s
  instead of 41 s, measured with an earlier form that split a burst over
  several Tcl lines; the one-line form has not yet run on hardware.

- **Microchip PolarFire — hardware-validated, with a Discovery Kit example.**
  `examples/mpfs_disco_kit/` puts an 8-bit × 1024 ELA and a shared-chain EIO on
  the PolarFire SoC Discovery Kit (MPFS095T), with a Libero batch flow
  (`build.py --program`), an OpenOCD config for the on-board FlashPro5 and
  hardware tests. All 11 hardware tests pass over OpenOCD. The host gains
  `OpenOcdTransport.IR_TABLE_POLARFIRE` (USER1/USER2 = `0x20`/`0x21`), selected
  for `MPF*` tap names by the CLI and board discovery and offered by the GUIs.
  The board config's OpenOCD `ftdi` path has not yet run on hardware: on
  Windows, Microchip's FlashPro driver owns the JTAG channel.

- **PolarFire ELA wrapper: the full parameter set.** `fcapz_ela_polarfire`
  (Verilog and VHDL) now offers everything `fcapz_ela_xilinx7` does:
  decimation, external trigger, timestamps, segments, probe mux, and burst
  readout on USER1 (`SINGLE_CHAIN_BURST=1`, the default) or USER2. A new
  testbench, `tb/fcapz_ela_polarfire_tb.sv`, drives it through `UJTAG`.

- **Vendor-neutral AXI4 interconnect.** A new generated `fcapz_axi_interconnect`
  (`rtl/`, a 2×1 full-AXI4 crossbar) merges a soft CPU and the EJTAG-AXI bridge
  onto one monitored bus as portable RTL, shared by both VexRiscv variants below
  in place of a vendor block design. Simulated in `tb/` and hardware-validated on
  both boards.

- **DE25-Nano — VexRiscv reference variant.** A new `de25_nano_vex_top` is a
  drop-in for the default design — same debug cores — with an open-source
  VexRiscv (RV32I) soft CPU in place of the RTL `axi4_traffic_gen`, so the AXI
  monitor captures real CPU bus traffic. The CPU and the EJTAG-AXI bridge are
  merged by `fcapz_axi_interconnect` onto one shared `axi4_test_slave` (the CPU
  uses words 16/17, the host words 0..15), so the host reads CPU writes back over
  EJTAG-AXI. Free-running firmware keeps the observable bus contract, so the whole
  `test_hw_integration.py` suite runs unchanged via `FPGACAP_BITSTREAM_VARIANT=vex`.
  New `vex/` RTL and `build_de25_nano_vex` launcher (Quartus Pro + riscv gcc).

- **Arty A7 — VexRiscv reference variant.** A new `arty_a7_vex_top` is a drop-in
  for the MicroBlaze design — same debug cores, same shared-bus wiring — with an
  open-source VexRiscv (RV32I) soft CPU in place of the proprietary MicroBlaze,
  so the reference design builds without a MicroBlaze licence or `mb-gcc`. Its
  firmware presents the identical host-gated bus pattern, so the whole
  `test_hw_integration.py` suite runs unchanged against it via
  `FPGACAP_BITSTREAM_VARIANT=vex`. New `vex/` RTL merging the CPU and EJTAG-AXI
  masters with `fcapz_axi_interconnect` (no vendor block design) and
  `build_arty_vex` launcher. Hardware-validated on the Arty A7-100T (Vivado
  2025.2 + Vitis riscv gcc 13.4): full suite green on the vex bitstream.

- **HTML user manual.** The Markdown manual in `docs/` now also builds into a
  searchable HTML site with MkDocs and the Material theme (`mkdocs.yml`; install
  with `pip install -e ".[docs]"`, then `mkdocs serve` or `mkdocs build`). The
  Markdown stays the single source and still reads on GitHub: a build hook
  points links that leave `docs/` at the repository. A new CI job runs
  `mkdocs build --strict`, so a broken link, anchor or image anywhere in the
  manual fails the pull request. The site is built only, not published.
  The site has tabs, search suggestions, per-page edit
  buttons and "last updated" dates, and the version in its title. Notes use
  GitHub alerts (`> [!NOTE]`) and the block and state diagrams are `mermaid`,
  both rendered on GitHub and in the site; Markdown only the site understands
  fails the build, so the two renderings cannot diverge.

- **Generated CLI tables and Python API reference.** `tools/gen_docs.py`
  rebuilds chapter 10's usage lines and option tables from the CLI parser and
  writes `docs/specs/python_api.md` (every public `fcapz` name with its
  signature and docstring). CI and pytest fail when either is out of date, so
  the manual follows the code. Every CLI option now has `--help` text, and the
  public API's undocumented classes and methods have docstrings.

### Changed

- **Host — `Analyzer.connect()` binds the first ELA slot.** An analyzer with
  no `instance` on a chain with a core manager is bound to the manager's
  first ELA slot when it connects, so it never reads whichever slot another
  program left active; a reconnect looks that slot up again, since the new
  image may differ. An explicit `instance` and a chain without a manager are
  unchanged. The GUI no longer moves the analyzer to slot 0 when an EIO
  is detached.

- **Host — an EIO left active no longer hides a hub's ELAs.**
  `Analyzer.probe_optional()` on a core manager whose active slot is not an
  ELA selects the first ELA slot (when the analyzer has no slot of its own),
  so the RPC connect and the GUI find the hub. `probe()` still reads only the
  active slot. The GUI connects to the first slot the descriptors call an ELA
  instead of slot 0.

- **Formal parity — vector parameters.** `sim/run_formal_hdl_parity.py`
  accepts bit-string parameters (such as a per-slot burst mask), and a
  manifest without a `formal` section is checked for interface parity only.

- **Core manager — slots the host cannot read fail elaboration.** A slot off
  the burst engine's shape is read only through its register window, so a
  design now fails elaboration when such a slot sets `USER1_DATA_EN=0`.
  `BURST_W` other than 256 is rejected too. These designs built before but
  could not be read back. Both HDLs.

- **Host — manager slot selection fails loudly.** Selecting a slot past
  `MGR_COUNT`, a negative slot, or one the manager does not take now raises
  instead of leaving the previous slot selected. `slot_info()` checks the
  range and confirms `MGR_DESC_INDEX`; `probe_all()` uses the descriptors to
  skip non-ELA slots and reports an ELA slot that does not answer. Moving an
  `Analyzer` to another slot with `select_instance()` drops its capture
  configuration, so call `configure()` again. A manager with more than 256
  slots is detected.
  The manager proof now also runs with a mixed burst mask.

- **MCP — fewer, broader tools.** The surface shrinks from 31 tools to 22
  (23 with `fcapz_find_in_capture`),
  cutting the schema every request carries. The read/write split stays, so
  annotations and capability gating are unchanged:

  | Before | Now |
  | --- | --- |
  | `fcapz_eio_connect` / `fcapz_axi_connect` / `fcapz_uart_connect` | `fcapz_connect(core="eio" \| "axi" \| "uart")` |
  | `fcapz_eio_close` / `fcapz_axi_close` / `fcapz_uart_close` | `fcapz_close(core="eio" \| "axi" \| "uart")`; `core="all"` (default) is the old `fcapz_close` |
  | `fcapz_capture_status` | `fcapz_capture_wait(status_only=true)`, still available under `--read-only` |
  | `fcapz_axi_dump` | `fcapz_axi_read(addr, count=N, burst=...)` |
  | `fcapz_axi_write_block` | `fcapz_axi_write(addr, data=[...], burst=...)` |

  `fcapz_axi_read` always returns `words` (plus `value` for one word), and
  AXI addresses and data now also accept hex strings such as `"0x40000000"`;
  values outside 32 bits are rejected. ELA-only fields (`program`,
  `single_chain_burst`) are refused for the other cores rather than ignored.

- **RPC — some refusals report a narrower `type` string.** The error
  envelope carries `exc.__class__.__name__`, and refusals that were bare
  `RuntimeError`s are now `NotConnectedError` / `NotEnabledError` (both
  subclass `RpcError`, which subclasses `RuntimeError`), while a capture
  still waiting for its trigger is `CaptureNotReady` (a `TimeoutError`
  subclass) rather than a bare `TimeoutError` — the distinction the MCP
  layer needs to tell "still armed, poll again" from "the transport stopped
  answering". Catching the base classes is unaffected; **migration:** a
  client comparing the `type` string should match the base classes or
  accept both spellings.

- **MCP — `--probe-root` is a flat directory.** `probe_file` must name a file
  sitting directly in the root; a subdirectory, a path climbing out of it, a
  symlink/junction, or a file with a second hard link are all refused. Nesting
  used to be allowed. It went because the lookup could not be made verifiable
  on every platform: Windows has no directory handles to open relative to, so
  a multi-component path can be reinterpreted between the check and the open,
  and a check that cannot be trusted is worse than a narrower rule. With one
  component the open is provable — `openat`/`O_NOFOLLOW` where the platform
  has it, an identity comparison otherwise. **Migration:** move probe maps to
  the top level of the root, or point `--probe-root` at the subdirectory in
  use. Probe files are also capped at 1 MiB, and a missing one now reports
  `not_found` instead of `invalid_argument`.

- **MCP — `fcapz_get_last_capture(max_bytes=null)` means 8 MiB, not
  unlimited.** `max_bytes` may lower the bound but no longer raise it past
  that ceiling, so `null` stopped being an escape hatch for forcing an
  arbitrarily large payload: the result is serialized back on the event loop
  after the offloaded call returns, at roughly 5 ms of whole-server stall per
  MB, and nothing bounded it. A capture over the ceiling returns the compact
  truncation marker, now carrying `ceiling_bytes` so a caller can tell the
  server's bound from its own. **Migration:** read `fcapz://last-capture` for
  the whole payload — it serves an already-built string, costs 0 ms of stall,
  and has no ceiling — or page it with `fcapz_get_last_capture_chunk`.

- **CI — RTL lint now includes yosys's pre-synthesis check.** A new
  `sim/run_yosys_check.py` runs `proc` then `check` (LibreLane's
  `pre_synth_chk` step) on every Verilator lint target, with that target's
  `-G` parameter overrides, and on every Verilog parameter set in the parity
  manifests, and fails on any warning. Its
  `--self-test` proves it rejects a loop index shared by two clocked blocks.
  The `lint-rtl` job now gets Verilator and yosys from a pinned OSS CAD Suite;
  Ubuntu's Verilator was too old to report `MULTIDRIVENPROC`. The job also
  elaborates the RTL with the suite's newer Icarus (`run_sim.py --lint-only`),
  which rejects a signal used before its declaration.

- **BREAKING (PolarFire wrappers): JTAG pad ports and new USER IR defaults.**
  `fcapz_ela_polarfire`, `fcapz_eio_polarfire` and `jtag_tap_polarfire`
  (Verilog and VHDL) gain `tck_pad_i`, `tms_pad_i`, `tdi_pad_i`, `trstb_pad_i`
  and `tdo_pad_o`. Connect them to top-level ports of the same direction;
  Libero binds them to the dedicated JTAG pins. `IR_USER1`/`IR_USER2` now
  default to `0x20`/`0x21`, because on PolarFire SoC the MSS debug module
  answers at the old `0x10`/`0x11`. `fcapz_ela_polarfire` also gains
  `trigger_in`, `trigger_out` and `armed_out`; tie `trigger_in` low when it is
  unused. No working design is affected: the old wrapper could not elaborate
  in Libero (see Fixed).

- **DE25-Nano — `trigger_out` is now observable from the host.** Both DE25
  tops count the clocks the ELA `trigger_out` is high and expose the count on
  EIO inputs 15:8 (cleared by EIO output 7), so the EIO there is now 16 inputs
  wide. A new hardware test uses it to check one `trigger_out` clock per
  trigger, with and without a trigger delay. Rebuild the DE25 bitstreams to
  get it.

- **VexRiscv is now the default Arty A7 design.** `examples/arty_a7/build.py` is
  a variant dispatcher defaulting to the open-source VexRiscv top (`vex`), with
  `--variant microblaze`/`--variant vhdl` for the others; `test_hw_integration.py`
  defaults to the vex bitstream. The Arty VHDL top (`arty_a7_top.vhd`) is now a
  mixed-language design instantiating the Verilog VexRiscv subsystem in place of
  the MicroBlaze block design.

- **VexRiscv core vendored + subsystem shared across boards.** The pinned core is
  vendored under `third_party/vexriscv/` (MIT licence + provenance, hash-verified
  offline — clean builds need no network), and the duplicated per-board CPU glue,
  firmware boot/link/build, and dependency check now live once in
  `examples/common/vexriscv/`. Only each board's `main.c` workload (and Arty's
  `vex_sys` bus adapter) stay board-local.

- **OpenOCD — adapter-agnostic wording and auto-discovery.** The docs now state
  that any OpenOCD-supported adapter (FTDI, WCH CH347, CMSIS-DAP, J-Link, …)
  works, since fpgacapZero only speaks to OpenOCD's TCL listener and never
  touches the USB adapter. The Connect USB filter parses each config's adapter
  `vid_pid` for any driver (`ch347 vid_pid`, `cmsis_dap vid_pid`, a bare
  `vid_pid`), not just `ftdi vid_pid`, so non-FTDI adapters are recognised
  instead of always probed.

- **ELA — shorter segment-completion path.** The post-trigger count is now a
  down-counter with registered last-sample flags, so the decision that ends a
  capture or segment no longer starts at an arithmetic compare. Capture
  behavior is unchanged; this restores timing margin on the Arty A7 VexRiscv
  build's 150 MHz ELA. Both HDLs.

- **Host — a failed burst is raised, not read around.** A burst that failed
  used to turn burst readout off for the session and re-read the capture
  through the register window, which also hid real faults, such as a JTAG
  drop mid-burst. Any burst failure now raises, with a hint naming
  `--two-chain-burst` or `--no-burst`. A bitstream with no burst path at all
  (`SINGLE_CHAIN_BURST=0` with `BURST_EN=0`) must now be declared: CLI
  `--no-burst`, RPC `connect` `"burst": false`, the GUI's new "Burst readout"
  setting (which also selects two-chain builds), or `burst=False` on the
  hw_server and Quartus transports.

### Deprecated

- **`Analyzer.pin_active_slot()`** now calls `bind_manager_slot()`, which
  binds the first ELA slot instead of the slot the hub has active. Use
  `bind_manager_slot()`.

- **Arty A7 MicroBlaze variant.** The proprietary MicroBlaze design
  (`arty_a7_top.v`, block design moved to `examples/arty_a7/legacy-microblaze/`)
  is deprecated in favour of the VexRiscv default, but retained — it proves the
  fcapz cores drop into a proprietary-CPU design. Build it with
  `--variant microblaze` (needs a MicroBlaze licence and `mb-gcc`).

### Fixed

- **A managed EIO access could reach another slot unseen.** Another
  controller (a second process on the same hub) that selected another slot
  during an `EioController` read or write sent some of it there: a read
  returned the other core's value, a write landed on the other core. Each
  access of an EIO with an `instance`, `connect()` and `attach()` included,
  now runs in `Transport.held_manager_instance()`, which compares
  `MGR_SELECT_COUNT` less the transport's own selects across the access and
  reads `MGR_ACTIVE` after it, and raises `ManagerResetError` (now defined in
  `fcapz.transport`, still importable from `fcapz.analyzer`). Older hubs get
  the `MGR_ACTIVE` check only.

- **EIO discovery missed an Intel EIO.** With no chains given, `eio_discover`
  (RPC) and the desktop GUI's EIO auto-attach tried the transport's IR-table
  chains, and `usb_blaster` has none, so only instance 1 was tried and the
  DE25-Nano EIO on instance 3 was never found. They now try instances 1-3.
  On the session's board, RPC `eio_discover` attaches the EIO it finds there,
  standalone or in a core-manager slot, through the session's transport
  instead of opening a second connection to the board. A request for another
  board takes the connection fields it leaves out from the session, so a bare
  request on a `usb_blaster` session no longer opens a local `hw_server`.

- **JTAG pipe — a register command after a burst could read stale data.** In
  burst mode, the Capture-DR of every scan starts a preload of the next burst
  word, which runs for `256 / SAMPLE_W + 1` TCK cycles (257 for 1-bit
  samples), longer than a 49-bit register scan. A register command that
  followed went out while the preload still held the ELA's DATA window, and
  read 0. Every register command now ends the preload its own Capture-DR
  started. Both HDLs.

- **Host — a burst-wired slot behind a transport that does not burst.**
  OpenOCD, and hw_server for some sample widths, read `read_block(0x0100)`
  through the register window. The analyzer handed them the whole capture
  anyway, so a deep one overran the window instead of being paged. Transports
  now say whether they burst (`Transport.bursts_data_window()`), and the
  analyzer pages whenever they do not.

- **RPC — the analyzer ignored `connect(instance=...)`.** The session read
  whichever slot was active, so an EIO in another slot of the same hub took it
  over. `connect` and `rebind` now bind the slot, and a managed `eio_connect`
  pins an unbound session to the slot it reads. A managed `eio_connect` also
  shares the session's transport only when it names the same board.

- **Core manager — one ELA's reset could phantom-arm another.** Any ELA's
  `ela_sample_rst` reset the whole hub's JTAG side: `MGR_ACTIVE`, every EIO
  output, and the register side of every ELA. Another ELA's arm and reset
  commands cross to its sample clock as toggles, and only their JTAG halves
  were reset, so an ELA armed an odd number of times saw a phantom arm and
  re-armed over a capture the host had not read. Each ELA now resets its
  sample and register sides together from its own reset, and the hub resets
  only at power-up or from `MGR_CTRL` bit 0. A cocotb test reproduces the
  phantom arm on the old wiring on all three shells. Both HDLs.

- **`reset_sync` (Verilog) powered up released.** The VHDL synchroniser powers
  up asserted; the Verilog one had no power-up value, so it came up 0 and a
  design whose reset input was never asserted was never reset. It now powers
  up asserted too. Found by the new formal power-up check.

- **Host — slot selection could reset an EJTAG-AXI bridge.** Selecting a
  manager slot wrote `MGR_ACTIVE` (`0xF008`) before checking that the chain
  held a manager; on an EJTAG-AXI bridge that frame is `CMD_RESET`. The host
  now writes only after `0x0000` answers as an ELA or EIO and `0xF000` as a
  manager. Likewise `discover_eio()` read `0x8000`, an AXI read command on the
  bridge, on chains it had not identified. Neither path met a bridge on the
  default chains.

- **Core manager — a slot switch right after a burst could be dropped.** After
  a burst the JTAG pipe refills its burst buffer on the next scan, and the
  manager ignores an `MGR_ACTIVE` write while that refill runs. With narrow
  samples (1-5 bits) the refill outlasted the scan, so the next analyzer kept
  talking to the previous slot. The host now reads `MGR_ACTIVE` back after each
  switch and writes it again, up to three times. The manager now takes that
  write once a burst owner is bound (see the next entry), so on a new bitstream
  the first write lands; the host loop stays for older bitstreams.

- **Core manager — a slot switch could move a pending burst.** Each time the
  burst engine started loading, the manager rebound the burst to the active
  slot, so an `MGR_ACTIVE` write between the `BURST_PTR` write and the burst
  read the new slot's memory from the old slot's pointer. The `BURST_PTR` write
  now binds the owner until the next one; a burst with no `BURST_PTR` write
  since reset still binds the active slot once. The host's sequence never hit
  this, but custom plumbing on `fcapz_core_manager` could. Both HDLs.

- **Host — bursts of 24-, 26-, 27- or 31-bit samples unpacked wrong.** Both
  the hw_server and USB-Blaster transports unpacked a burst at
  `256 // (256 // SAMPLE_W)` bits per sample, wider than the packing whenever
  `SAMPLE_W` does not divide 256, so each sample picked up bits of the next
  one. They now unpack at `SAMPLE_W`, read for every burst, so a
  slot switch cannot leave the previous slot's width behind.

- **Host — two-chain Xilinx sessions sent managed bursts to USER2.** With
  `single_chain_burst=False` (`--two-chain-burst`) every burst went to USER2,
  which a core manager does not answer. Managed slots now burst on the hub's
  own chain, as on the USB-Blaster.

- **RPC — a managed EIO raced the analyzer.** `eio_connect` with a manager
  slot opened a second transport, whose cached active slot went stale when the
  analyzer switched slots. It now shares the analyzer's transport, and
  `eio_close` leaves that session open.

- **Core manager — VHDL defaults and EIO-only builds.** The VHDL
  `fcapz_debug_multi_xilinx7` defaulted `NUM_EIOS` to 1 and `ELA_PORT_COUNT`
  to 2 instead of following `EIO_EN` and `NUM_ELAS` like the Verilog, and
  rejected `NUM_ELAS=0`. Both HDLs now agree, and an EIO-only hub elaborates.

- **Core manager — sized parameter overrides and width warnings.** The
  replicated per-slot defaults now widen each scalar to 32 bits before
  replicating it. A sized override such as `.SAMPLE_W(8'd8)` used to pack as
  8-bit fields, so with two or more ELA slots the per-slot widths and depths
  were wrong and elaboration failed. This also clears Verilator `WIDTHCONCAT`.

- **RPC, web UI and MCP — hw_server on Zynq UltraScale+ MPSoC.** Only the
  CLI and GUI chose the chain shape from the tap name, so an RPC `connect`
  with `tap: xck26` shifted raw USER opcodes into the PS TAP and every core
  on USER1-3 read `0x00000040`. The shape choice is now one function,
  `fcapz.transport.hw_server_chain_shape_kwargs`, used by the CLI, GUI and
  RPC (and so the web UI and MCP server): `xck*` / `xczu*` select
  `use_register_ir`, standalone UltraScale(+) parts the UltraScale IR table.
- **ELA — a plain trigger on a multi-stage core.** On a core built with
  `TRIG_STAGES > 1` the hardware triggers only from the sequencer, so a
  capture configured with just `trigger` never fired. The host now programs
  such a trigger as a single final stage 0: `value_match` as EQ,
  `edge_detect` as CHANGED, and `both` as EQ on comparator A OR CHANGED on
  comparator B. `both` therefore means value-or-edge on these cores, as
  documented, while single-stage cores keep their RTL behaviour; on a
  multi-stage core built without `DUAL_COMPARE` it is refused. The stage
  has no hit count (`count_target` 0), so a hit is never lost to the
  16-bit stage counter wrapping. Every board validated before was built
  with `TRIG_STAGES=1`.
- **EJTAG-AXI — a burst read that fills the FIFO no longer loses a beat.**
  While filling the burst FIFO the bridge drove `rready` from a register
  holding last cycle's not-full, so in the cycle the FIFO filled the slave
  handed over a beat that was never written. The XPM FIFO reports full at
  `FIFO_DEPTH - 1`, so a 16-beat read on a 16-deep bridge failed with SLVERR
  while 15 passed (seen on a KV260). `rready` is now the FIFO's own not-full
  during the fill, so a beat is accepted exactly when it is written; a full
  FIFO holds the slave off until the host pops. The VHDL core also wrote
  the FIFO a cycle after accepting the beat, against a full flag that lagged
  by that cycle; its write is now combinational too. Both HDLs; needs a
  bitstream rebuild. A cocotb test drives a 24-beat burst through the
  16-deep FIFO in both HDLs.
- **EJTAG-UART — no more dropped bytes (BUG-002).** An `RX_POP` or
  `CMD_CONFIG` result appears in the next scan's capture, and the core
  clears it on every Update-DR of its chain. The host read it in a separate
  JTAG operation, so an update it did not issue in between discarded a byte
  that had already left the FIFO, with no overflow or framing error. On a
  KV260 that lost bytes in 9 of 15 32-byte loopback messages, and every byte
  with 50 ms between pop and readout. `recv`, `recv_line` and the identity
  read now run each pop and its readout in one batch (one `jtag sequence`
  on hw_server) ending in a NOP drain. `recv` starts with one pop per batch
  and doubles up to 64 while data keeps coming, so on transports that scan
  one at a time it still honours its idle timeout. Host-only; no bitstream
  change.
  The earlier explanation, an RX synchroniser missing stop bits on a
  zero-delay wire, is withdrawn.
- **RPC — `connect` binds manager slot 0.** Behind a multi-core manager an
  analyzer with no instance used whichever slot was last selected, so after
  an EIO session on slot 2 a later ELA `connect` (and the chain autodetect
  and `rebind`) talked to the EIO. RPC now selects slot 0 explicitly, and
  before every command it drops each session's cached slot, so an analyzer
  or EIO session never trusts a slot another session has since changed.
- **EIO and ELA — a session without a slot binds one behind a manager.** An
  EIO opened without `instance` (CLI `eio-*`, RPC `eio_connect`, and every
  `eio_discover`) used whichever slot was active, so once an ELA session
  moved the manager its writes reached the ELA. It now binds the manager's
  first EIO slot, and RPC reports it as `instance`. Discovery finds an EIO
  slot that is not active, and refuses `base_addr` behind a manager. The
  analyzers RPC opens for a moment to list cores, find the AXI monitor or
  discover boards bind the first ELA slot, and AXI monitor register reads
  re-select their analyzer's slot. CLI ELA commands without `--ela-instance`
  bind the first ELA slot too, instead of following the slot the last tool
  left selected (after `eio-write`, the EIO).
- **ELA — a sequencer stage could drop a met count after 65535 hits.** A
  stage's hit counter kept counting hits that an external trigger in AND
  mode held back, and being 16 bits it wrapped: the count read as not met
  again until the stage re-counted to its target, so the external trigger
  was ignored for up to `count_target` samples. The counter now saturates
  and the compare is 17 bits wide. Both HDLs; needs a bitstream rebuild. A
  cocotb test drives 66536 held-back hits through a stage with target
  0x8000 in both HDLs.
- **RPC — cancel reaches a connection that is still opening, and failed
  session swaps no longer leak.** `cancel_active` saw only installed
  sessions, so a `connect`, `eio_connect`, `eio_discover`, `axi_connect`
  or `uart_connect` hung in its handshake could not be aborted. A failed
  `eio_discover` handshake left its transport open, and a failed
  `eio_connect` replacement left the closed old controller installed.
  Discovery probes (`scan_targets`, `discover_boards`, `openocd_discover`)
  can be cancelled too: the `xsdb` child is killed and OpenOCD probe
  sockets are closed.
  On Quartus, `cancel` kills `quartus_stp` without taking the lock that a
  connect in progress holds, so a hung Quartus open can be aborted.
- **EJTAG-UART — `close` closes the transport even if a reset scan fails.**
- **hw_server — every core-manager access selects its own slot in the same
  JTAG sequence.** The host cached the `MGR_ACTIVE` it last wrote, so a
  second program on the same cable (a GUI next to a CLI, two MCP clients)
  moving the slot sent this one's next accesses to another core: EIO writes
  into an ELA, a capture read from the wrong slot. Now each sequence that
  reaches a slot starts with an uncaptured `MGR_ACTIVE` write: register
  accesses, block-read chunks, pipelined reads, and bursts (once, before
  `BURST_PTR`). Slot enumeration and descriptor reads (`MGR_DESC_INDEX`) are
  single sequences too. New `Transport.slot_scope` / `SlotSelection` /
  `atomic_slot_select` / `read_regs_after_write`. The first scope on a slot
  identifies the chain's manager and verifies the slot once; a chain that
  never answered as a manager (an EJTAG-AXI bridge, whose reset command
  `MGR_ACTIVE` is) gets no select. A manager without epochs (`MGR_CAPS`
  bit 3) gets a burst drain ahead of each select. Each select counts as this
  host's in `MGR_SELECT_COUNT`, and where every access selects its own slot,
  another program's selects no longer raise `ManagerResetError`; the epoch,
  `CAPTURE_GEN` and burst-header checks stay. Cost on a KV260: see the PR.
- **Quartus and OpenOCD — every core-manager access selects its own slot
  too.** As on hw_server above: on Quartus the select is shifted inside each
  access's own `device_lock` (register reads and writes, window reads,
  descriptor reads, and bursts, once before `BURST_PTR`); on OpenOCD each
  access is now one Tcl command line, which OpenOCD runs before serving
  another client. Both get the same identification, legacy drain and
  select counting, and a Quartus burst on the control chain now ends with
  the drain that hw_server's has. An `Analyzer` or `EioController` with an
  `instance` on either backend is no longer alarmed by another program's
  selects; one without keeps the check.
- **Run-length counts of a managed slot burst on its own chain.** Behind
  the USB-Blaster, or a two-chain hw_server session, the run counts of a
  core-manager slot were read through the register window, since the
  two-chain burst never reaches a manager. They now burst on the control
  chain, as samples and timestamps already did:
  `read_run_length_block(..., on_control_chain=True)`.
- **hw_server — a slot switch after a single-chain burst is no longer
  dropped.** The core manager ignores an `MGR_ACTIVE` write while the burst
  pipe fills its staging register, and on a 1-, 2- or 4-bit lane the fill
  that the next scan's capture starts outlasts a select scan. The select was
  dropped silently, and the next accesses (an EIO poll, say) reached the
  ELA slot. A burst on the control chain (single-chain, or a manager's slot
  on a two-chain session) now ends with an uncaptured `VERSION` read and 258
  idle TCKs inside the same sequence. New RTL testbench
  `fcapz_core_manager_select_after_burst`.
- **GUI — EIO panel chain switches hold the transport lock.** Polling,
  output writes and attach switched the shared JTAG chain without the lock,
  so a poll during a capture could send the capture's next access down the
  EIO's chain, then froze the window until the capture ended. A poll tick
  now skips while a capture holds the transport; a write waits up to a
  second, then reports that a capture is running.
- **EJTAG-AXI and EJTAG-UART — `attach` switches the chain under the
  transport's transaction lock**, so it cannot land between another
  controller's register accesses on a shared transport. The GUI refuses
  Attach (EIO, AXI, UART) while a capture runs, since the capture holds that
  lock for its whole wait and attaching would freeze the window.
- **ELA — a refused configuration writes nothing.** A trigger sequence with
  more stages than the core has, or a wide trigger value on a core without
  `WIDE_TRIG`, used to be refused after the capture registers were already
  written, so the next arm ran settings the host did not know about. Every
  check now runs before the first write. A stage `count_target`,
  `next_state` or `combine` too wide for `SEQ_CFG` is refused: a
  `count_target` of 65536 used to program 0, which fires on the first match.
- **ELA — storage qualification is refused on a core built without it.** A
  `stor_qual_mode` of 1 or 2 on a `STOR_QUAL=0` core was accepted and the
  capture stored every sample, while the caller believed it was filtered.
  It is now refused before anything is written, as run-length capture and
  the trigger sequencer already were.
- **EJTAG-AXI — the bridge is usable after an error response.** The bridge's
  error flag stays set until a RESET, and the host never sent one, so after
  one SLVERR/DECERR every later read or write failed (reporting `resp=0`)
  until a reconnect. The host now clears the flag when it reports the error.
- **MCP — an AXI error response is a `hardware_error`.** It was coded
  `internal` and told the agent to report a bug in the server.
- **CLI — `axi-decode` and `capture --decode-axi` read run-length captures.**
  Each entry was taken as one cycle, which shortened latencies (an 8-cycle
  wait could read as 2) and could merge back-to-back handshakes. Entries now
  expand to the clocks they held, as the RPC decode already did.
- **MCP — a refused reconnect keeps the live session.** `fcapz_connect`
  closed the open session before checking its arguments, so a misspelt or
  forbidden field dropped a working connection. Arguments are now checked
  first.
- **MCP — `--axi-write-range` accounts for the bridge's address width.** On a
  bridge narrower than 32 bits a block could pass the range check and wrap
  past the top of the address space to address 0. Such a block is refused.
- **RPC — `configure`/`capture` no longer assume a 1024-deep core.** An
  omitted `depth` defaulted to 1024 and an omitted `sample_width` to 8, so
  any core built another size (the Arty AXI monitor is 256 deep) refused
  the capture with "depth mismatch" unless the client spelled the geometry
  out. Omitted values are now read from the connected core, as the CLI and
  GUI already did; a probe file's `sample_width` still wins, and an explicit
  value that disagrees with the core still fails.

- **MCP — a board with no fpgacapZero cores was reported as a server bug.**
  Transports report a board that answered wrongly as a bare `RuntimeError`,
  which the error classifier filed under `internal` ("report this; it is a
  bug in fcapz-mcp"). A `RuntimeError` raised from inside the hardware call
  is now `hardware_error`; a `TypeError` or similar from the same path still
  reads as `internal`.

- **A full-capture tool result can no longer stall the server for an
  unbounded time.** FastMCP turns a tool result back into JSON on the event
  loop *after* the offloaded call returns, so the payload
  `fcapz_get_last_capture` hands over is a stall nothing else can interleave
  with — measured against the real call path at roughly 5 ms per MB, with a
  concurrent heartbeat seeing a gap exactly as long as the whole call
  (125 ms for a 24 MB capture). `max_bytes=null` meant "no limit", so a deep
  capture had nothing bounding it. `max_bytes` may now lower the bound but
  not raise it past an 8 MiB ceiling, and `null` means that ceiling; a
  marker returned because of it carries `ceiling_bytes` so a caller can tell
  the server's bound from its own. The whole payload stays available from
  `fcapz://last-capture`, which serves an already-built string and measured
  0 ms of stall for that same 24 MB capture.

- **A wedged backend no longer kills the MCP session for the rest of the
  process.** The JTAG owner is a single thread, and `RpcServer` published no
  abort hook, so the watchdog could only mark a call abandoned and hope the
  backend returned. When it never did — `xsdb` staying alive but silent left
  `_send` in a `readline()` with no deadline — the owner stayed in that call
  forever, nothing was left to clear the poison flag, and every later
  hardware command was refused. `RpcServer.cancel_active` now aborts the
  transports the session holds, and the XSDB transport reads its responses
  through a queued reader with a deadline (`FCAPZ_XSDB_TIMEOUT`, default
  60 s; `fpga -file` gets its own) that kills the process rather than
  waiting on it, the same shape `quartus_stp` already used. Measured against
  a backend that never returns: previously poisoned indefinitely, now ready
  again in ~0.3 s.

- **A cancel can no longer abort the wrong command.** `cancel_active` stops
  whatever the session currently holds, so a watchdog past its grace window
  or a recovery nudge firing as reconciliation completes could reach through
  a finished command into the next one. The check and the abort now happen
  together under the session lock. The same window made the watchdog re-read
  a command's state outside the lock, fall through when the owner had
  reconciled in between, and surface a bare `queue.Empty` instead of the
  watchdog error.

- **`probe_file` confinement no longer loses the swap race.** A path was
  approved, opened, then re-checked by stat'ing the *same path* — which
  follows the same newly planted link and agrees with itself, so a name
  swapped for a link between the two was accepted. The file must now sit
  directly in `--probe-root`, which makes the lookup verifiable: `openat`
  with `O_NOFOLLOW` where the platform has it, and otherwise an identity
  comparison between what was inspected and what was opened. Hard links and
  files over 1 MiB are refused, and a missing file now reports `not_found`
  rather than `invalid_argument`.

- **A capture that stored only some cycles is no longer read as AXI.**
  Reassembly treats a sample's position as its bus cycle and pairs each
  response with the oldest queued request; decimation and storage
  qualification break both, because a handshake that was never stored cannot
  be told apart from one that never happened. A single dropped response
  silently shifted every later pairing onto the wrong address, and "latency"
  counted stored samples rather than cycles. `decode_axi` now takes the
  capture's sampling provenance and refuses such a trace with
  `decoded: false` and a reason, keeping its full result shape. The capture
  exporter records `stor_qual_mode` (and the probe map) so an offline
  `fcapz axi-decode` knows the same thing.

- **The AXI pairing caveat reaches the reader.** The assumption that nothing
  was outstanding when the window opened is now stated on every page of
  `fcapz_axi_transactions`, on the capture summary, in the CLI and in the
  web panel — unconditionally, not only when a response happened to arrive
  with an empty queue. That evidence can disprove the assumption; nothing
  can confirm it. `AR(A)` before the window, then `AR(B)` and `R(A)` inside
  it, yields a clean-looking row with A's data at address B and no flag of
  any kind, so silence on a tidy decode was the dangerous case.

- **Window edges are no longer counted as bus faults.** A response whose
  request handshook before the capture, or a write whose second beat falls
  after it, is legal traffic seen through a keyhole. Both were in
  `FAULT_FLAGS`, so `anomaly_count`, `--only-anomalies` and the web "Faults
  only" filter presented boundary effects as failures. Only `error_response`
  and `unaligned_address` — what a finite window can actually prove — count
  now; the rest are reported as observations via `flagged_count`.

- **`fcapz_capture_wait` no longer reports a wedged link as "still armed".**
  Every `TimeoutError` was treated as "the trigger has not fired", including
  one raised by the transport while reading status or samples, which sent
  the caller into a poll loop against a session that would never answer. The
  analyzer now raises `CaptureNotReady` for the expected case and only that
  is turned into `{"triggered": false, "still_armed": true}`.

- **An ordinary RPC refusal is no longer reported as a bug in this server.**
  The MCP layer calls `RpcServer.handle` in process, so its exceptions
  arrive as themselves rather than as an `{"ok": false}` envelope — and a
  bare `RuntimeError("not connected")` was classified `internal`,
  `retryable: false`, "report this bug". `fcapz_probe` while disconnected
  was the common case. The RPC layer now raises typed refusals
  (`NotConnectedError`, `NotEnabledError`, `RpcError`) and the classifier
  reads both routes the same way.

- **Every tool-call failure is one coded JSON object.** Argument validation
  runs before the tool body, so a rejected enum or an unknown field used to
  reach the agent as pydantic prose with no code, no `retryable` and no
  remedy; a coded failure also arrived behind FastMCP's "Error executing
  tool X:" prefix. Both are handled at one seam above validation, and the
  body names the failing `tool`. New codes: `capture_not_ready`,
  `unknown_tool`.

- **A misspelled argument is rejected instead of dropped.** Pydantic
  validates a TypedDict by filtering, so `config={"posttriger": 9}` was
  discarded before the call, the capture ran with the default posttrigger,
  and the agent was told it succeeded — the server's own unknown-key check
  never saw it. The same held for misspelled tool arguments, which pydantic
  ignores. The capture config now publishes `additionalProperties: false`,
  and top-level arguments are checked against the published schema.
  `ProbeEntry.lsb` became optional to match the parser, which defaults it
  to 0.

- **Hardware tools no longer freeze the MCP server.** FastMCP awaits a
  synchronous tool directly on the event loop, so every JTAG round trip
  stopped the server answering anything at all for its duration — a 300 s
  capture blocked even `fcapz_status` for five minutes. Tools now run in a
  worker thread; hardware access is still serialized by the owner thread.

- **`probe_file` is read once, where it is checked.** The MCP layer validated
  the path and the RPC layer opened it a queue hop later, so anyone able to
  write inside `--probe-root` could swap the file — or an ancestor — in
  between and have different content loaded than was approved. The probe map
  is now read in the MCP layer and passed inline as `probes`; there is no
  second open to race.

- **Capture snapshots are built off the hardware lock.** A multi-megabyte
  capture ran its `json.dumps` while holding the lock every other caller
  needs, delaying `fcapz_status` and a concurrent caller's `busy` reply for
  as long as it took. Commands may now carry a `prepare` step that runs
  before the lock is taken; only the single publishing assignment is inside
  it. `fcapz_status` likewise reads its whole body under one hold, so it can
  no longer report a busy slot beside connection flags from after that
  command committed.

- **AXI decoding no longer invents pairings it cannot justify.** A response
  is never matched to a request handshaking on the same sampled cycle (AXI
  forbids a combinational VALID-to-VALID path, so it belongs to an earlier
  request), an unmatched response reads the same wherever it lands in the
  window rather than being excused by a cycle-number heuristic, and the
  leftover transactions at the end of a window are numbered in trace order.

- **Two races in the MCP hardware owner.** A close that found nothing open
  decided and acted in two separate holds of the lock, so a connect could
  commit in between and leave the board connected with the wrapper reporting
  otherwise. And a watchdog whose grace window expired just as recovery
  finished poisoned the session with nothing left to clear the flag, refusing
  every later hardware command for the life of the process. A stalled
  recovery teardown now also gets a second abort attempt rather than wedging
  the owner thread.

- **Non-finite watchdog and tool timeouts are rejected.** `nan` passed every
  ordered comparison and then made the wait spin instead of expiring,
  disabling the watchdog it was meant to configure.

- **Two MCP fields that reached past the JTAG cable are now confined.**
  `probe_file` opened any path on the server's filesystem; it now requires
  `--probe-root DIR` and must stay inside it. `host` accepted any network
  target for hw_server/OpenOCD; it is now loopback-only unless a host is
  named with `--allow-host`. Both policies are reported in `fcapz_status`.

- **The MCP tool list now tracks the safety flags.** A tool whose capability
  is disabled is no longer advertised and then refused — it is left out of the
  list, so an agent neither plans around it nor pays for its schema in every
  request (16 tools under `--read-only`, 20 by default, 23 with all writes
  enabled). The session-level permission checks are unchanged and remain the
  enforcement.

- **ELA — a setting written just before ARM could miss that capture.** The
  settings crossed into the sample clock through two synchronizer flops, but
  the arm pulse came off the first flop of its own, one clock ahead. With a
  sample clock slower than the JTAG writes, a setting and the ARM (or
  `STARTUP_ARM` and a soft reset) landing on the same sample clock edge gave
  that capture the old setting. The `CTRL` write that arms or soft-resets now
  snapshots the settings in the JTAG domain, and the sample domain copies that
  snapshot one clock before the pulse that uses it, so a capture takes exactly
  the settings written before its ARM and none written after. The snapshot
  replaces the first synchronizer stage, so the cost is four flip-flops, with
  no new timing constraints. ARM and soft reset reach the capture two sample
  clocks later than before. Older bitstreams keep the race; `force_idle()`
  still covers it for `STARTUP_ARM`.
- **ELA — storage qualification stored the wrong samples.** The core took
  `SQ_MODE` as the raw compare mode with 0 meaning off, so EQ could not be
  selected, and the host wrote 1 for "store when match" (NEQ on the core) and 2
  for "store when no match" (LT). The host also skipped the write for mode 0, so
  a qualifier from an earlier capture stayed on. `SQ_MODE` now holds the compare
  mode plus one (1 = EQ, 2 = NEQ, ... 9 = CHANGED; 0 and 10..15 = off), shown by
  new `COMPARE_CAPS` bit 22, and the host always writes it. On older cores the
  host maps mode 2 to NEQ and rejects mode 1. Code that writes `SQ_MODE`
  directly must add 1 to the compare mode. `AxiMonitor.beat_storage_qual()` now
  returns mode 2. Both HDLs. The DE25-Nano ELA now builds with `STOR_QUAL=1`,
  and its hardware tests cover modes 0, 1 and 2.

- **ELA — the sequencer loop index had two drivers before optimization.** One
  module-level `integer si` was the loop index of two clocked blocks, so right
  after `proc` yosys `check` reported 32 conflicting drivers, and recent
  Verilator releases flag `MULTIDRIVENPROC`. Optimization removed the dead flops, so FPGA netlists
  were correct, but flows that gate on the pre-synthesis check (LibreLane, Tiny
  Tapeout) stopped at synthesis. Each block now declares its own index; the
  synthesized netlist is unchanged.

- **EJTAG-UART — yosys could not read the core.** The simulation-only baud
  check calls `$error`/`$warning` with run-time arguments in an `initial`
  block, which yosys rejects, so yosys-based flows stopped at read. Synthesis
  now skips that block (`` `ifndef SYNTHESIS ``); simulators still run it.

- **ELA (Gowin) — the unused user chain's TDO was undriven.** Only the
  selected chain's TDO had a driver, leaving the other `GW_JTAG` input
  floating. It is now tied low. Both HDLs.

- **EJTAG-AXI and EJTAG-UART — newer Icarus could not elaborate them.** Each
  used registers before declaring them, which Icarus 14 rejects. The
  declarations (and the UART's error-flag synchronizer) now come first; the
  logic is unchanged.
- **Intel ELA wrapper — `PROBE_MUX_W` captured zeros above the first slice.**
  `fcapz_ela_intel.v` forwarded `PROBE_MUX_W` to the core, whose `probe_in` is
  then `PROBE_MUX_W` bits wide, but declared its own port as
  `SAMPLE_W*NUM_CHANNELS`. Tools only warn and zero-pad that, so every mux
  slice past the first read zeros. The port now matches the core, as on the
  Xilinx wrappers. No shipped example sets `PROBE_MUX_W` on Intel. The ECP5,
  Gowin and PolarFire wrappers and the VHDL Intel wrapper take no
  `PROBE_MUX_W` and were not affected.

- **hw_server and Quartus — burst readout decoded some sample widths wrong.**
  Samples were unpacked at a stride of `256 // (256 // SAMPLE_W)` bits,
  while `jtag_burst_read` packs them at `SAMPLE_W`. The two differ whenever
  the width does not divide 256 (20, 22, 24, 26, 27, 29, 30, 31 bits), and
  every sample after the first in each scan came back shifted. The width was
  also cached for the life of the transport, so a session that changed core
  or core-manager slot kept decoding at the first one's width. `SAMPLE_W` is
  now read before every burst and used as the stride. Quartus `read_block()`
  also no longer bursts a core wider than 32 bits, which returned whole
  samples where 32-bit words were expected; such cores read with
  `read_sample_block()`, as on hw_server.

- **Web — any website could drive a token-less server over the WebSocket.**
  CORS does not cover WebSockets, and a page's handshake to
  `ws://127.0.0.1:7373/api/ws` carries the real loopback `Host`, so the
  anti-rebinding check let it through with the full API, OpenOCD control
  included. `/api/ws` now requires the handshake's `Origin` to be the server's
  own, a `--cors-origin`, or a loopback page on a loopback client (the Vite dev
  proxy). Clients that send no `Origin` (scripts) are unchanged.

- **PolarFire — `UJTAG` instantiation.** `jtag_tap_polarfire` used per-bit
  `UIREG0..7` ports and left out the JTAG pins, which do not match Libero's
  `UJTAG`. It now uses the `UIREG[7:0]` bus and passes the pins through. The
  simulation stub, which had copied the wrong port list, now matches Libero's.

- **ELA — `trigger_out` stayed high through the trigger delay.** With
  `trigger_delay > 0` a hit still present during the countdown kept
  `trigger_out` asserted, for up to `trigger_delay + 1` clocks, and a hit that
  came and went during the countdown pulsed it again. It is now one pulse per
  trigger, on the trigger event, as documented. Both HDLs.

- **ELA — a soft reset during a decimated capture could stall the idle
  prefill.** Decimation was cleared on arm but not on soft reset, and the idle
  ring stores only on a decimation tick while holding the count. A soft reset
  (`force_idle()` / `Analyzer.reset()`) that landed mid-ratio therefore stopped
  the pre-arm history until the next arm, so a trigger shortly after that arm
  waited for the pre-trigger window to fill and could be missed. Soft reset now
  clears the decimation count. Both HDLs.

- **Single-chain and multi-core Xilinx cores dropped every command on Zynq
  UltraScale+ MPSoC.** `jtag_pipe_iface` only acted on a scan of
  exactly 49 shift clocks. Every other TAP in BYPASS on the chain adds one
  clock (the ARM DAP on MPSoC), so each 49-bit command arrived as 50 and was
  silently ignored: `ela-list` reported `got 0x0000`, and no write could
  land. A command is now the last 49 bits of any scan at least 49 and fewer
  than `BURST_W` clocks long (the same last-49-bits rule `jtag_reg_iface`
  uses); full bursts still saturate the counter and never execute. The MPSoC
  failure affected `fcapz_debug_multi_xilinx7`, `fcapz_ela_xilinx7`/`_xilinxus`
  with the default `SINGLE_CHAIN_BURST=1`, and `fcapz_axi_mon_xilinx7`; fixing
  it needs a bitstream rebuild. Every `jtag_pipe_iface` user, including
  `fcapz_axi_mon_intel`, now also executes a stray 50..`BURST_W`-1 bit scan on
  its chain as a command instead of ignoring it. `BURST_W` must now exceed 49.

- **Core manager — a burst after switching slots could read from the old
  pointer.** The manager passed on each slot's own burst-start toggle, but the
  burst reader keeps one last-seen copy: after a slot switch the new slot's
  toggle could match it, the start was missed and the burst read the new
  slot's RAM from the previous burst's pointer, with no error; a slot switch
  alone could also look like a start. The manager now raises the start itself
  on every `BURST_PTR` write to a burst-capable slot (both HDLs) and reports it
  in `MGR_CAPS` bit 2. On a manager with two or more slots and without that
  bit, the host now syncs the start before each burst, in the same JTAG
  transaction: after the `BURST_PTR` write, one burst scan whose capture
  copies the new owner's toggle, then a second `BURST_PTR` write the reader
  cannot miss. Old bitstreams keep burst speed; no rebuild is needed.

- **hw_server — a connect right after another session could fail.** About
  1 s after the last xsdb client exits, hw_server releases its cables one
  after another, and once a client is connected again it reopens and rescans
  them all, which takes several seconds. A client that connects after the
  release has begun does not stop it: it sees some cables closed and the
  rest still open, and a target on an open cable answers a scan, then drops
  out with "JTAG node is not accessible" until the reopen finishes. Connect
  polled the list for up to 3 s and took the first listed target. It now
  first waits until hw_server reports every cable open and initialized
  (one reporting an error, such as a board powered off, is not waited for),
  which marks the end of a release (none starts while a client is
  connected), then waits for the target to be listed, within 10 s in all
  (`target_wait_timeout`), and confirms it with one IDCODE scan. A select
  or scan that fails is raised at once instead of being retried. One rare
  window remains. A connect that lands right as the release starts can see
  every cable open for about 0.2 s after hw_server has decided to close one,
  and hw_server reports no closing state. The target then drops out for
  about 1 s, and connect's IDCODE scan or the reads just after it fail
  with "JTAG node is not accessible" (see docs/14_transports.md).

- **hw_server — a failed burst send went unnoticed.** A burst is built over
  several xsdb sends, but only the last send's output was checked, so an
  error in an earlier send could leave a partial sequence that still ran.
  Every send is now checked. A burst that returns any other number of scans
  or values than it queued now raises `BurstIntegrityError` instead of being
  re-read through the register window, which would hide the defect. The
  Quartus single-chain burst raises it too, instead of a plain `RuntimeError`.

- **hw_server — a deep burst could drop out of burst mode mid-read.** Each
  chunk of scans ran as its own `jtag sequence`, and between two runs hw_server
  can put a scan of its own through the PL (seen on Zynq UltraScale+ MPSoC),
  which the pipe decodes as a register command. The pointer write and every
  scan are now one sequence, built over several xsdb sends and run once.

- **ELA — trigger sample one late with `INPUT_PIPE ≥ 1`.** The registered
  compare stage judges each sample a clock after the probe path delivers it,
  but the RAM stored the sample then current, so `samples[pretrigger]` was the
  sample *after* the one that matched, and storage qualification kept or
  dropped each sample by its predecessor's compare. The core now stores the
  judged sample. `trigger_in` is also delayed to match the probe path
  (`INPUT_PIPE − 1` extra flops for `INPUT_PIPE ≥ 2`), so an external trigger
  marks the sample driven alongside it, and AND mode compares like with like.
  A core with `EXT_TRIG_EN=1` and `INPUT_PIPE=0` is now built as
  `INPUT_PIPE=1`, so its probe path is as long as the `trigger_in`
  synchronizer and it aligns the same way; before, its external trigger marked
  the sample two clocks after the pulse. That costs one probe stage plus the
  registered RAM write command (data, address, timestamp and write enable)
  and two clocks of latency. Timestamps keep their spacing; their absolute
  offset from `probe_in` grows by one clock (two for that `INPUT_PIPE=0`
  case). Fixing it needs a bitstream rebuild.

- **ELA (Verilog) — timestamps aliased onto sample data on deep cores.** The
  timestamp window base (`0x100 + DEPTH·words·4`) was compared as 16 bits, so
  once it passed `0xFFFF` every data-window read returned timestamps. It is now
  compared at full width, as the VHDL core already did. A fixed core sets
  `COMPARE_CAPS` bit 19 and the host reads its whole window; for an older
  core the host still refuses window reads from the aliased address
  (`base & 0xFFFF`) on. Burst readout is unaffected.

- **Host — reads past the end of the 16-bit register window.** A capture larger
  than the data window (from `0x0100` up to `0xF000` behind a core manager,
  which is now detected even when no slot is selected, `0x10000` otherwise)
  read on into manager registers and returned garbage for the last samples.
  The host now refuses such a window read with `DataWindowError`. On `hw_server`, samples wider than 32 bits (and their
  timestamps) are instead read with the single-chain burst, chunked 256 scans
  per TCL call, rather than 32 bits per scan: it has no window limit and is
  much faster. A manager slot without burst wiring is never burst-read (it
  would return zeros); a manager without slot descriptors (`MGR_CAPS` bit 1
  clear) keeps the burst for every slot, selected or not.

- **ELA — a sequencer could fire on a sample matched against the previous
  stage (`INPUT_PIPE ≥ 1`).** With the registered compare, each sample was
  compared against the stage active when it arrived, but the hit was used a
  clock later by whatever stage was active then. Right after an advance, a
  sample that matched only the old stage counted as a hit of the new one:
  stage 0 `== 5` → stage 1 `== 7` fired on `5, 5`. Every stage's compare is
  now registered and the decision takes the current stage's hit, so counts,
  AND/OR combine and back-to-back matches follow the stage that is actually
  active. Costs one comparator pair per extra stage when `TRIG_STAGES > 1`
  and `INPUT_PIPE ≥ 1`. Both HDLs; fixing it needs a bitstream rebuild.

- **ELA — an arm that switched channel or probe slice used old-selection
  samples.** `NUM_CHANNELS > 1` and `PROBE_MUX_W` select the probe on arm, but
  the probe pipeline, the previous-sample register and the registered
  compares still held the old selection's samples for a few clocks after it.
  Those samples could trigger the new capture, land in its window, or read as
  an edge against the first new sample, and a single-segment core's rolling
  pre-arm history (all old-selection samples) counted toward the pre-trigger
  window. After an arm that changes the selection the core now neither
  stores nor evaluates the trigger until the pipeline holds only new samples
  (the probe pipeline length plus up to two clocks), and the pre-trigger
  window is refilled from the new selection. An external trigger in those
  clocks is ignored. Arms that keep the selection are unchanged. Both HDLs;
  fixing it needs a bitstream rebuild.

- **ELA — a segment could not trigger on the first sample after the previous
  one (`INPUT_PIPE ≥ 1`).** Each segment's auto-rearm cleared the registered
  compare hits, so the sample right after a completed segment was never
  judged; with no pre-trigger a matching sample there was skipped and the
  next segment started on a later match. The hits are now kept across the
  rearm. Both HDLs; fixing it needs a bitstream rebuild.

- **ELA — an ARM or soft reset during a running capture could be lost or
  corrupt the next capture.** On the clock the restart landed, the running
  capture's own transitions still applied and won: a trigger or completion
  of the old capture could leave the core `done` (or triggered with the old
  configuration) instead of re-armed, a segmented core restarted at the old
  write address with stale pre-trigger credit, and a new holdoff was lost.
  The restart now takes priority; single-segment cores still keep their
  rolling history contiguous, and restarting a capture that had already
  triggered re-earns the pre-trigger window instead of reaching back across
  the samples it never wrote. Likewise, with storage qualification and
  `INPUT_PIPE ≥ 1` every arm drops the sample right after it, so such an arm
  now re-earns the window too. Both HDLs; fixing it needs a bitstream
  rebuild.

- **ELA — `STATUS.done` after an ARM could describe the previous capture,
  and a badly timed ARM could stop status updates.** A capture that
  completed while an ARM was still crossing into the sample clock domain
  set `done` after the ARM had cleared it, so the host read the previous
  capture as the new one. Done is now tagged with the ARM / reset it
  belongs to and a stale one is not reported. Separately, an ARM or reset
  written on the one JTAG clock a capture-status update arrived dropped
  that update's handshake, after which `done` and segment progress never
  updated again until the core's reset inputs were asserted. Both HDLs;
  fixing it needs a bitstream rebuild.

- **hw_server — register access now clocks the JTAG idle it meant to.**
  xsdb's `jtag sequence delay` waits without clocking TCK, so the idle
  cycles meant to let a command land were never clocked. Every idle is now
  `state IDLE <n>`, and every DR scan (register, block and pipelined reads,
  bursts, and the bridges' raw scans) ends in an explicit UPDATE-DR, which
  `-register` mode needs. The
  warmup read that the hw_server transport discarded before identity and
  status reads is gone, so each of those reads is one scan sequence, not two.
  Validated on Zynq UltraScale+ MPSoC (`-register` mode) on a KV260.

- **Burst readout runs once.** Each burst used to be repeated until two
  passes agreed (hw_server single-chain, and both Quartus burst paths), and
  burst timestamps that did not count strictly forward were re-read through
  the slow window, which also re-read valid captures spanning a full counter
  period. On hw_server the stale passes came from the pointer write and the
  scans running as separate JTAG transactions with no clocked idle between
  them, both since fixed; repeated hardware stress on Arty A7 and DE25-Nano
  showed no stale pass on any burst path. Each burst is now one pass instead
  of at least two. Quartus register reads are likewise read once, not twice.

- **Core-manager detection is deterministic.** A standalone ELA answers
  `0xF000` from its DATA/timestamp window, so on a very deep core a sample
  could read as the manager ID. The ID is now conclusive only when a
  standalone core of the probed geometry cannot reach `0xF000`; otherwise the
  rest of the manager block must match too, and a manager with descriptors
  and two or more slots must latch a test write to `MGR_DESC_INDEX`
  (restored afterwards, even when the readback fails, and then the failure
  propagates without caching an answer), which a standalone core ignores.
  Only a deep core whose live capture reproduces the register block of a
  one-slot or descriptor-less manager can still fool it.
  `Analyzer(..., manager=True/False)` states the topology outright.

- **CLI.** `--trigger-value` accepts hex (`0x…`); `--depth` and the sample
  width default to what the core reports instead of 1024/8.

- **Docs — chapter 04's MPSoC note.** It still said only USER1 is reachable on
  Zynq UltraScale+ MPSoC and linked a chapter 14 section that no longer exists.
  It now says that the hw_server transport's named-register mode reaches all
  four USER chains, so `EIO_EN=1` is needed there only without that mode.

- **Docs — chapter 10 had drifted from the CLI.** It gave `openocd` as the
  default `--backend` (it is `hw_server`) and `8` as the `--sample-width`
  default (it comes from the probe file, else the core), said `--format` follows the
  `--out` extension (it does not), and left out `--gui-config`,
  `--two-chain-burst`, `--startup-arm`, `--trigger-holdoff`, `--profile`,
  `--open-in` and the `axi-mon` subcommand. The tables are now generated.

- **Docs — the AXI monitor spec said no RTL exists.** Phase P1 ships for
  AXI4-Lite (`rtl/fcapz_axi_mon.v`, chapter 19); the spec now says so.

- **ELA — one stale sample after a soft reset with `INPUT_PIPE ≥ 1`.** Arming
  (and soft reset) cancelled the RAM write queued in the input pipeline while
  the write pointer still advanced, so that address kept a sample one
  buffer-length old. It shows only when a pre-trigger window reaches back across
  the arm, which after a soft reset it can: the first capture after
  `force_idle()` or `Analyzer.reset()`, when the trigger fires within the
  pre-trigger length of the arm, had one wrong sample at the arm point. In the
  shipped examples that is the AXI monitors (single-segment, `INPUT_PIPE=1`);
  segmented ELAs never build pre-arm history and were not affected, nor were
  captures re-armed straight after a completed one. The queued write now always
  lands, as it does with `INPUT_PIPE=0`.

- **ELA (native VHDL) — four behaviours now match the Verilog core.**
  - A segmented capture could start segment 0 on stale pre-arm samples: the
    idle block's write-pointer update overrode the reset to address 0 on the
    arm edge. The window was wrong while the capture reported success.
  - A final sequencer stage with a count target above 1 never triggered; its
    hits were not counted. With `INPUT_PIPE ≥ 1` the VHDL also registered the
    fully qualified trigger instead of the raw comparator hits, so a stage
    could count one hit and trigger on another; a hit landing on the last
    holdoff cycle was dropped from the count and could leave the capture
    armed for good. It now registers the comparator hits as Verilog does.
  - `INPUT_PIPE` built one probe register whatever its value, so with 2 or more
    the window sat one or more samples late.
  - Decimation and external-trigger mode were latched on arm straight from the
    JTAG clock domain instead of through their synchronisers, so a write close
    to arm could apply to that capture, or be sampled mid-change.

- **Intel/Altera — `close()` now waits for `quartus_stp` to exit.**
  `QuartusStpTransport.close()` signalled the process and returned at once, so
  it could return while `quartus_stp` was still alive and still attached to the
  USB-Blaster; a script that closed one session and opened the next raced its
  own previous process for the cable. `close()` now runs Quartus' own
  `close_device`, sends `exit` and closes stdin, then waits for the process to
  exit, escalating to terminate and kill. The whole teardown is bounded, even
  when another thread's request is stalled holding the I/O lock. Closing now
  takes about 0.05–0.1 s where it used to return immediately. A new
  `close_fast()` skips the wait for Ctrl+C, matching the Xilinx transport.

  This was reported as a second session failing to open the cable, but that
  failure did **not** reproduce on a DE25-Nano with Quartus Pro 26.1: there a
  second session opens even while the first is still open, and the next
  process spawn takes long enough to hide the race. Treat this as lifecycle
  hardening against that class of failure, not as a confirmed fix for it.

- **Intel/Altera — one session can no longer damage another.** A request that
  timed out killed whichever process the transport held *at that moment*, so a
  stale request could destroy the connection that had replaced its own; the
  output-draining threads could likewise deliver a closed session's
  end-of-stream marker into the next session and fail its first scan with
  "process exited unexpectedly". A request arriving just after another timed
  out could also read that request's late answer as its own. Each session is
  now one object, built completely before it is published, and every request
  stays bound to the session it started on; a timeout or interruption marks
  that session dead before the next request can reach it. `connect()` on a
  transport that is still open closes the previous session instead of leaking
  its process, and a failed `connect()` no longer leaves `quartus_stp` running.
  A timed-out session is now reaped — waited for and its pipes closed — rather
  than only signalled. Cancelling a connect from the GUI no longer waits for an
  `open_device` that keeps printing without finishing: `close()` kills it.

- **ELA (native VHDL) — a capture length of `DEPTH` is no longer silently
  truncated.** The VHDL core sized `pretrig_len`/`posttrig_len` and their
  clock-crossing stages one bit narrower than the Verilog core, which sizes them
  to hold a length equal to `DEPTH`. It kept only the low `PTR_W` bits of a
  written length where the Verilog keeps one more, so any length with that bit
  set was misread — a length of `DEPTH`, for instance, as 0. An oversize request
  was accepted without raising `overflow`, and a `posttrigger` of `DEPTH`
  returned a capture with no post-trigger samples. Two more widths had to move
  with it — `post_count`, and the width the overflow comparison is evaluated at.
  Widening the lengths alone would otherwise have made a `posttrigger` of
  `DEPTH` never complete, and let a `pretrigger`/`posttrigger` pair summing to
  `2×DEPTH` wrap and clear `overflow`.
  No capture the host library can request was affected — it validates
  `pretrigger + posttrigger + 1` against the depth, and against the segment
  depth for segmented builds — so this only reached a JTAG master writing the
  registers directly, which is what the overflow flag exists to catch. Values
  too wide even for the Verilog's field still wrap, now identically in both
  cores.

- **ELA (native VHDL) — the data-window address decode now defaults out of
  range.** Reading any register below the sample-data window matched neither
  branch of the decode and fell through to an in-range default of sample 0,
  where the Verilog core lands far out of range and reports out-of-bounds.
  Masked in practice, since the decoded value is only consumed on a data-window
  read.

- **ELA — captures no longer splice across a re-arm.** In single-segment builds
  the pre-trigger history rolls continuously, but sample writes stop while a
  completed capture is read out, leaving a hole in it. The core kept vouching
  for that history, so the next capture could commit a trigger immediately and
  return a window joined from two different moments — samples missing at the
  seam, nothing marking it, and only ever in the pre-trigger half. The
  pre-trigger credit is now dropped when a capture completes, so the next arm
  re-earns `pretrigger` fresh samples first; a readout can no longer join
  two moments into one window. Applied to both the Verilog and the native
  VHDL core. Segmented builds already reset that credit on arm and are
  unchanged. Trade-off: a one-shot trigger arriving within `pretrigger` stored
  samples of a re-arm is now missed rather than captured with a spliced
  prehistory.

- **`--program` silently programmed nothing on Zynq UltraScale+ MPSoC.** The
  configuration target was selected out of xsdb's `targets` tree by the part
  name (`xck26`), but on MPSoC that tree has no node named for the part — it is
  `PS TAP` → `PMU`/`PL` plus `PSU` → `RPU`/`APU`. The filter matched nothing,
  `fpga -file` loaded nothing, and because xsdb reports failures by *printing*
  a message rather than by exit status, both errors were discarded: the session
  continued against whatever configuration was already in the FPGA. A Kria or
  ZCU capture taken with `--program` on an earlier version may not be from the
  bitstream you thought you loaded. Standalone FPGAs (7-series, UltraScale+)
  were never affected — there the device node *is* named for the part.

  Programming now selects `PS TAP` on MPSoC and the part-named node elsewhere,
  scoped by `jtag_device_name` so the right board is picked when several are
  attached, and both `targets -set` and `fpga -file` run with error checking so
  a failure raises instead of passing silently. Verified on a chain carrying an
  Arty A7, a KV260 and a ZCU-class board at once (xsdb 2025.2).

---

## [0.4.9] — 2026-08-13

### Added

- **Web — Log tab.** Backend diagnostics (JTAG readback, connection, transport
  warnings) are captured into a bounded ring and served at `GET /api/logs`; the
  browser tails them in a Log panel that sits as an auto-hiding hover-drawer
  under the waveform (pin it to keep it open), with Pause, Clear, and
  auto-scroll. The RPC gateway logs each command with timing and the analyzer
  logs burst-readback success/fallback, so the fast path is visible, not silent.

- **Web — saved dock layouts.** The current panel arrangement auto-persists
  across reloads, and a **Layout** menu saves, loads, and deletes named layouts
  (localStorage).

- **Web — connected FPGA shown on the Connection panel.** The status line now
  leads with the actual device the backend opened (family/part + IDCODE), not
  just the vendor.

- **Efinix (Trion / Titanium) listed as a planned vendor** in the README and the
  manual vendor matrices — support pending, wrapper not yet implemented.

- **Web — USB-Blaster backend.** The browser Connection panel now offers the
  Intel/Altera `usb_blaster` backend (previously only in the CLI, RPC, and
  desktop GUI). Selecting it swaps host/port for an optional **Quartus cable**
  field; Connect goes straight to the local cable with no TCP scan. The
  `quartus_stp` executable is **auto-detected** on the server — via `PATH`,
  `$QUARTUS_ROOTDIR`, and common Intel/Altera install roots (new
  `find_quartus_stp()`), so the usual case needs no path anywhere. A
  `fcapz-web --quartus-stp` flag (`$FCAPZ_QUARTUS_STP`) overrides when
  auto-detect misses. Auto-detect returns the `quartus_stp` Tcl shell, never the
  `quartus_stpw` windowed GUI beside it.

### Changed

- **Transport — fast wide-core readback over USB-Blaster.** Wide, single-chain
  cores (the 160-bit AXI monitor) now stream their samples **and** timestamps via
  a single-chain burst on the core's own BSCAN instance — one 256-bit DR scan per
  sample instead of per-word register reads, ~15× fewer `quartus_stp` commands
  (~20 s → ~1–2 s for 1024×160-bit). Falls back to the per-word path if the
  stream will not stabilize. Hardware-validated on the DE25-Nano (Agilex 5).

- **Web — Trigger Immediate fills the whole window** (the 64-sample cap on wide
  cores is gone) and shows the same live readback progress as an armed capture.

- **Web — ELA trigger window model.** The pre/post-trigger boxes are replaced by
  a **window size + trigger position** pair (e.g. a 1024-sample window with
  position 512 → 511 pre-trigger / 512 post-trigger samples).

- **Docs & UI — Xilinx rebranded to AMD/Xilinx** across the manual and the web /
  PySide vendor labels (code identifiers and `IR_TABLE_*` names unchanged).

- **Docs — README manual links are absolute** so they resolve on the PyPI
  project page (PyPI has no repo context, so relative links 404 there).

### Fixed

- **Quartus USB-Blaster — clearer "no cores" message.** A board that presents no
  fpgacapZero cores (e.g. an unconfigured device) now reports *"No
  fpgacapZero-compatible cores found"* instead of the raw quartus *"virtual JTAG
  instance cannot be found"*, which read like a cable/chain fault when the
  connection was actually fine.

---

## [0.4.8] — 2026-08-10

Packaging only: rewrote the README's two image URLs (logo, web demo)
and its licence links as absolute URLs so they resolve on the PyPI
project page.
No functional change beyond the version constants a bump regenerates.

---

## [0.4.7] — 2026-08-10

Packaging only: the PyPI summary still called this a "JTAG logic
analyzer for Xilinx 7-series FPGAs"; it now reads "vendor-agnostic
full-featured FPGA debug cores". No functional change beyond the
version constants a bump regenerates.

---

## [0.4.6] — 2026-08-10

> Covers everything between v0.3.0 and v0.4.6. The tree passed through
> 0.4.0 and 0.4.5 on the way, but neither was tagged, so the entries
> that accumulated across them are collected here under the first
> tagged release that contains them.

### Added

- **AXI monitor — read-address trigger + full-sample hardware verification.**
  New `AxiMonitor.read_addr_capture_config(addr)` builds an `araddr`-qualified
  value trigger (the read-channel mirror of `write_addr_capture_config`), so a
  single read can be isolated on a bus carrying unrelated read traffic. New Arty
  A7 stress tests inject distinct known write and read patterns and read back the
  **full 160-bit sample**, asserting `awaddr`/`wdata`/`araddr`/`rdata` — which
  straddle all five 32-bit readback words. They pass on **both** the Verilog and
  VHDL bitstreams on real silicon (15/15 `TestAxiMonitor*`). The content tests
  soak the readback — 128 writes + 128 reads per bitstream, fresh data each
  round — so intermittent corruption would show. This retires the earlier
  "wide-SAMPLE_W readback is timing-marginal at 150 MHz" caveat: the full sample
  reads back correctly and reliably (0 mismatches across both languages); the
  design meets timing with the tightest paths in ELA segment-pointer logic, not
  the monitor readback.

- **AXI monitor — native VHDL implementation.** `fcapz_axi_mon` and its
  Xilinx-7 wrapper now ship as native VHDL alongside the Verilog source of
  truth (`rtl/vhdl/core/fcapz_axi_mon.vhd`, `rtl/vhdl/fcapz_axi_mon_xilinx7.vhd`),
  so the monitor is usable from a pure-VHDL flow rather than only via
  mixed-language instantiation. Kept in lockstep by the Verilog/VHDL parity
  checks: static generic/register parity, Layer-0 interface parity, and the
  shared cocotb bench run against **both** languages
  (`sim/run_cocotb_axi_mon.py --hdl verilog|vhdl` — identical tests pass on
  each). The full formal-equivalence proof is deferred: the monitor's active-low
  `ARESETN` (inverted to the ELA's `sample_rst` internally) is not drivable by
  the parity miter's active-high reset sequencing; the embedded `fcapz_ela` is
  proven separately. Hardware-validated on Arty A7: the VHDL Arty build binds
  the Verilog wrapper to the native VHDL core (as the ELA already does), and all
  13 `TestAxiMonitor*` hardware tests pass on the VHDL bitstream on real silicon.

- **Waveform x-axis reads sample indices, not nanoseconds.** The exported VCD
  now uses one time unit per stored sample (`$timescale 1 ns`), so the viewer's
  x-axis and the `#` times are the sample number (sample 8 shows as `8`, was
  `80 ns` at 100 MHz). The web viewer keeps the units raw (no SI rescale to
  µs/ms on deep captures). Surfer has no dedicated "samples" unit, so the axis is
  still suffixed `ns` — the number is the sample. The real sample rate stays in
  the JSON metadata (`sample_clock_hz`) for converting back to time.

- **Web — trigger-point marker in the waveform.** After a capture the viewer
  drops a static yellow `trigger` marker at the trigger sample — a fixed vertical
  line that stays put while you click around to move the red cursor. Its time is
  read from the VCD (the `pretrigger`-th `#time` line), so it lands correctly for
  timestamped and plain captures alike, and it moves (never stacks) to the new
  trigger on every capture. It carries one `trigger` row in the signal list —
  Surfer couples a marker's line with a list item, so that row is the cost of a
  line that doesn't move when you click.

- **Web — per-bit edges in the trigger value (Vivado ILA style).** A binary
  trigger value now accepts per-bit edge tokens — `R` (rising), `F` (falling),
  `B` (either) — mixed freely with `0`/`1`/`X`, MSB first (e.g. `10XR`), on
  probes of any width, not just 1-bit rows. A row's bits are ANDed and compiled
  to comparators: the `0`/`1` bits form one level compare and each edge bit its
  own edge comparator. The hardware's two comparators allow one edge alongside
  the levels; two different edges in a row, or a level+edge row under Global OR,
  are refused with a clear message.

- **Web — full-width triggering on WIDE_TRIG cores (AXI monitor):** the Trigger
  tab previously listed only signals in the low 32 bits, so on the 160-bit AXI
  monitor you could trigger on the events byte or `awaddr` but not `wdata`,
  `bresp`, or any channel above bit 32 — even though the hardware comparator is
  full-width. The backend now advertises the capability (`has_wide_trigger` from
  `COMPARE_CAPS` bit 18) and the Trigger tab lists **every** captured field as
  triggerable on such a core; a single value-match (`==`) or any-change row
  reaches the full sample width. The `!=`/second-comparator and sequencer paths
  still zero-extend from 32 bits, so those combinations on fields above bit 32
  are refused with a clear message instead of silently matching the low word.

- **Arty A7 example — MicroBlaze on the shared AXI bus:** the reference design
  now integrates a MicroBlaze soft CPU whose `M_AXI_DP` master and the EJTAG-AXI
  bridge master are merged by an in-BD SmartConnect onto one AXI4 bus driving the
  test slave, so the AXI monitor (USER2) captures **real CPU bus traffic** — not
  just host traffic. The CPU's debug module sits on the free USER3 tap; the AXI
  fabric runs on a dedicated 100 MHz clock. Baked-in, host-gated firmware writes
  a known pattern to the slave on demand (staying write-quiet otherwise). New
  `TestAxiMonitorMicroBlaze` hardware tests validate CPU-driven capture and an
  EJTAG cross-read of the CPU's writes; the full Arty suite is green with no
  regressions. Everything ships in one bitstream (Verilog top only).

- **RPC / Web — EJTAG-AXI auto-detect:** a new `ejtag_axi_probe` command finds
  an EJTAG-AXI bridge on the connected target (its own USER chain, default
  USER4) using the bridge's read-only CONFIG identity scan on the shared
  transport — no reconnect, ELA session untouched. The web calls it on connect
  and the AXI tab shows a "bridge detected on chain N" banner with its chain
  pre-filled. When a bridge is detected the AXI tab now **auto-attaches** it
  (once per connection), landing straight in the read/write view with no click.

- **Web / RPC — auto-discover OpenOCD boards on Connect:** a new
  `openocd_discover` command (loopback-only, like `openocd_start`) finds
  compatible boards without the user picking a JTAG config. It reads each
  allow-listed config's `ftdi vid_pid`, keeps only the configs whose USB adapter
  is actually plugged in (best-effort enumeration; degrades to probing all when
  unavailable), then starts OpenOCD per surviving config and probes for an
  fpgacapZero core — leaving each confirmed board on its own running port. When
  nothing is already running, Connect calls this automatically: one board
  connects straight through, several show the existing picker. Two configs that
  share a VID/PID disambiguate by probing (the first claims the adapter). New
  `fcapz.board_autodiscover` module with unit tests.

- **Web — zero-config "Start OpenOCD":** enabling the UI's server-managed
  OpenOCD no longer needs any flags in the common case. The `openocd` binary is
  found on `PATH` **and** in known off-`PATH` install locations (xPack via `xpm`
  or a manual extract, chocolatey — what Digilent/BRS boards typically use),
  preferring a real `.exe` over a `.cmd`/`.bat` launcher shim; still overridable
  via `--openocd`/`$FCAPZ_OPENOCD`. And when no `--openocd-cfg`/`--openocd-cfg-dir`
  is given, the repo's bundled `examples/*/` board configs are offered by
  default — so `fcapz-web` from a source checkout can start OpenOCD for a shipped
  board with no flags at all. `--openocd-cfg-dir` (or `$FCAPZ_OPENOCD_CFG_DIR`)
  still registers every `*.cfg` in a folder. The security model is unchanged:
  only discovered/listed configs can be started, loopback only. Using the
  frontend against an already-running OpenOCD/hw_server needs none of this.

- **ELA — full-width trigger comparator (`WIDE_TRIG`):** the trigger comparators
  were always `SAMPLE_W`-wide in silicon, but the register path only let the host
  set the low 32 bits of comparator A's value/mask (upper bits forced to 0), so
  on a wide core (e.g. the 160-bit AXI monitor) most of the captured vector was
  un-triggerable. A new `WIDE_TRIG` parameter (default 0 — ELA/EIO builds are
  bit-identical) adds a `WIDE_SEL`/`WIDE_DATA` indexed-word window that programs
  comparator A across the entire `SAMPLE_W`. The AXI monitor enables it, so a
  trigger can now match any field — a VALID-qualified full write address, a
  response code in the upper bits, etc. The VHDL ELA core
  (`rtl/vhdl/core/fcapz_ela.vhd`) mirrors the parameter for full HDL parity. The
  wide path is proven by the shared cocotb `wide_trigger_upper_bit` test, which
  triggers on a bit above 31 (with an idle-bus control that must not fire)
  against **both** the Verilog and VHDL ELA; the static and interface parity
  gates (`run_hdl_parity.py`, `--interface-only`) keep the two in lockstep and
  the `WIDE_TRIG=0` path stays bit-identical to the previous behaviour.

- **Arty A7 VHDL variant — MicroBlaze parity:** the VHDL reference design now
  instantiates the same MicroBlaze subsystem as the Verilog build (`mb_sys`
  block design + firmware ELF, MDM on USER3), sharing one monitored AXI bus with
  the EJTAG-AXI bridge. `build_arty_vhdl.tcl` moves to a Vivado project flow (so
  the block design + ELF-in-BRAM work) and `arty_a7_top.vhd` gains the 100 MHz
  AXI domain, the `mb_sys_wrapper` instance, and the shared-bus rewiring. The
  full `test_hw_integration.py` suite now passes on the VHDL bitstream on an Arty
  A7 (67 passed / 7 UART skips), including the CPU-traffic MicroBlaze tests that
  previously had no CPU to exercise.

- **Web — connect UX:** Connect/Disconnect moved to the top of the Connection
  panel, and a **Cancel** button aborts an in-flight connect/scan (the slow
  XSDB cold start no longer locks the panel until timeout).

- **Web — Cores tab:** the discovered-cores list moved out of the Connection
  panel into its own Cores tab (stacked with Connection); the dock jumps to
  it once a connection is established. The Run tab is a single row with the
  Download VCD/CSV/JSON buttons folded into one **Download…** picker.

- **Web — ILA-style Trigger Setup:** the Trigger tab became a Vivado-ILA-like
  table: add probes as rows (Name | Operator | Radix | Value) with `==`/`!=`,
  binary/hex/unsigned radix, X don't-care digits, R/F/B edge tokens on 1-bit
  probes, and a Global AND/OR trigger condition; raw fields moved under
  Advanced.

- **Web — grouped trigger fields:** trigger rows can be concatenated into one
  field (check the rows, press **Group selected**; top row = MSB, ▲/▼ reorder,
  **Ungroup** to split) so a single value spans several probes, e.g.
  `{addr_hi, addr_lo} == 0x1234`. Groups take `==`/`!=` with X don't-cares
  across the whole field and compile to one comparator; members may be
  non-adjacent in the sample word but must lie in the low 32 bits.

- **Web — Run strip:** the Run controls became a fixed one-row strip between
  the config tabs and the waveform viewer — a headerless, fixed-height,
  locked dock group: no tab header, less vertical space, always visible.

- **Web — armed indicator:** while a capture is armed and the trigger hasn't
  fired, the Run bar shows a pulsing "armed - waiting for trigger" status
  (single-shot and auto re-arm both).

- **Web — armed waits never time out:** Arm holds one hardware arm and polls
  the new `capture_wait` RPC (wait + read-out on the existing arm, no
  re-configure/re-arm) until the trigger fires or Stop disarms — a trigger
  can arrive arbitrarily late with no blind gaps and no 10 s deadline.

- **Web — Stop works while armed:** Stop is enabled during any armed wait
  (not just auto re-arm); it aborts the in-flight capture request and a new
  `disarm` RPC (`force_idle`) soft-resets the core to verified idle.

- **Web — Trigger tab with click-to-trigger:** triggering gets its own tab
  next to ELA. It lists every signal — named probes when defined, else the
  raw probe bits (bit0…bitN), so no setup is needed — and clicking
  ↑/↓/1/0/⇅/= adds that signal's condition (rising/falling on TRIG_STAGES ≥
  2 builds, level, any-change, field value) as a removable chip; multiple
  signals combine with AND/OR. Compositions map onto the comparators
  (merged patterns, dual-compare stage for a second pattern or an edge);
  impossible ones are refused with the reason. The raw trigger fields
  (mode/value/mask, external trigger, sequencer JSON) moved here from the
  ELA tab and always show the result, staying editable.

- **Web — per-core viewer tabs:** every capture core (plain ELA, AXI monitor)
  gets its own Surfer viewer tab holding its own last capture, so switching
  cores never clobbers another core's waveform; the tabs appear on connect,
  are listed in the Tabs menu, and follow the discovered core list. Clicking
  a viewer tab re-binds the session to that core, so the ELA/Run controls
  always drive the waveform you're looking at. Run controls freeze during a
  core switch (and auto re-arm stops) so an arm built for one core can never
  hit another core's geometry ("sample_width mismatch").

- **Web — chain autodetection:** `connect` without a `chain` scans the BSCAN
  USER chains and binds to the first debug core it finds (echoing the resolved
  chain); `list_cores` reports cores on other chains too, and `axi_mon_probe`
  returns the monitor's full identity (with its `chain`) from any core. The UI
  drops the Chain field entirely — core cards get a **Use this core** button,
  and the AXI Mon tab works regardless of the active core: applying a trigger
  or probe map re-binds the session to the monitor automatically, with each
  core keeping its own ELA config across switches (e.g. the Arty reference
  design's monitor on USER2). Hardware-validated on Arty A7: detection, probe
  map, and decode-layer event triggers (aw_hs, any_err on a SLVERR) all
  confirmed over the web RPC.

- **Web — AXI monitor support:** the UI detects an AXI monitor on connect
  (`axi_mon_probe`), lists it in the Connection panel's cores, auto-applies its
  probe map so captures decode to named AXI fields, and adds an **AXI Mon** tab
  with an AXI-aware trigger builder — transaction-event checkboxes on
  `DECODE_EN=1` builds, write-address match otherwise. Server side,
  `axi_mon_probe` now reports `decode` and `list_cores` includes the monitor.

- **Web — Tabs menu:** a top-bar dropdown that toggles dock tabs (checked =
  open; click to close or reopen) and a **Reset layout** action that rebuilds
  the default arrangement in place — previously a closed tab could only be
  recovered by reloading the page, which also dropped the UI session.

- **Web interface (`fcapz-web`):** New browser front-end over the unified
  JSON-RPC API — a FastAPI gateway (`python -m fcapz.web`) plus a React/Vite UI
  with dockable panels (Connection, ELA, Run, EIO, JTAG-AXI) and an embedded,
  self-hosted Surfer waveform viewer that reloads captures in place. Local or
  token-gated network access; auto-scans JTAG targets and auto-discovers EIO on
  connect. Install with `pip install -e ".[web]"`, then run `fcapz-web`. See
  [`docs/18_web_interface.md`](docs/18_web_interface.md).

- **Web — board discovery:** browser Connect discovers fpgacapZero-compatible
  boards over OpenOCD (probes each tap for the ELA identity, sweeps TCL ports),
  connects automatically to a single board, offers a picker for several, and
  fails only when none are compatible. New `discover_boards` RPC.

- **Web — server-managed OpenOCD:** `fcapz-web --openocd <exe> --openocd-cfg
  <cfg>` lets the UI start OpenOCD itself; Connect brings it up automatically
  when no board is reachable (localhost-only, allow-listed configs). New
  `openocd_start` / `openocd_stop` / `openocd_status` RPC.

- **Web — cores listing:** the Connection panel lists the cores present (the
  ELA and any EIO) as labeled cards with their parameters and JTAG location,
  and names the core instead of showing the raw magic. New `list_cores` RPC.

- **EJTAG-AXI RTL:** Vendor wrappers now expose `CMD_FIFO_DEPTH` and
  `RESP_FIFO_DEPTH` independently from burst `FIFO_DEPTH`; the Arty
  reference sets both command/response queues to 16 and forces the small
  command queue to distributed XPM storage to trim BRAM usage while
  keeping the 16-beat burst FIFO. The placed Arty A7 reference now reports
  1.5 BRAM tiles total, and the EJTAG-AXI hierarchy itself reports 0 BRAM.

- **EJTAG-AXI RTL:** `DEBUG_EN` parameter on the core and vendor wrappers,
  defaulting off to prune bridge-only debug buses, capture records, and
  counters from production builds; RTL reset regression now sweeps
  `DEBUG_EN=0` and `DEBUG_EN=1`.

- **Docs:** JTAG register map spec — in-document index, ↑ Top anchors, and
  clarified per-core “address map” scope ([`docs/specs/register_map.md`](docs/specs/register_map.md));
  chapter 13 stub updated ([`docs/13_register_map.md`](docs/13_register_map.md)).

- **Transport:** Optional `FCAPZ_LOG_CONNECT_TIMING=1` logs hw_server connect
  phases (socket open, hello, target open, JTAG open) to stderr for diagnosing
  slow or stuck connects; GUI worker enables it when the env var is set.

- **GUI:** Application event filter ignores the mouse wheel on spin boxes and
  combo boxes so scrolling docks does not accidentally change values; same
  filter in the dummy-capture demo app.

- **GUI:** `Analyzer.immediate_variant()` and **Trigger Immediate** (was Capture)
  — force a waveform as soon as pre-trigger is ready (always-true compare;
  sequencer bypass when `TRIG_STAGES>1`). **Arm** runs a normal triggered capture
  on a worker thread. **Auto re-arm** sits beside **Stop** on the main toolbar
  and applies to both paths; toolbar no longer has a separate Continuous action.
  After **restoreState**, the checkbox is re-applied from saved prefs so layout
  restore does not clear it.

- **Windows:** Minimizing the `fcapz-gui` main window also minimizes external
  waveform viewer windows started from the History panel; restoring the GUI
  restores them (same PID/window association as vertical tiling).

- **GUI:** Trigger value: radix dropdown (hex / dec / oct / bin) next to the
  value field (**hex** by default); choice is saved in UI prefs, in
  trigger-history presets as `trigger_value_radix`, and passed when recording
  captures to `gui.toml`.

- **GUI:** After connect, advanced ELA controls are disabled when the
  bitstream lacks the matching FEATURES bits (decimation, external trigger,
  storage qualification) or when the probe mux has only one slice; `probe()`
  exposes `has_storage_qualification` (FEATURES[4]).

- **GUI:** EIO panel — small combo box next to “Poll inputs” to choose the
  poll period (25–1000 ms presets; default 250 ms).

- **GUI / API:** `Analyzer.probe_optional()` — same USER1 reads as `probe()` but
  returns `None` when VERSION is not the fcapz ELA (`'LA'`). The connect worker
  uses it so **Connect** succeeds without an ELA; ELA capture and toolbar
  actions stay off while EIO / EJTAG-AXI / UART docks can still attach on their
  chains. CLI behaviour unchanged (`probe()` still requires ELA).

### Changed

- **Web — sensible capture defaults on connect.** A freshly connected core now
  defaults to filling one capture window — **8 pre-trigger samples, the rest
  post-trigger** — sized to the usable per-segment depth (`depth / num_segments`)
  instead of a fixed 25-sample window that under-filled deep buffers (and
  overflowed segmented cores with "pre+post+1 exceeds segment depth"). The
  default trigger is now **match-anything** (`mask=0`), so Arm captures on the
  next sample until a real trigger is set, rather than waiting for the low byte
  to read 0.

- **Web — connection UI.** With multiple discovered targets the connect button
  reads just **Connect** (the picker already names the target), and the transient
  scan status drops the "(starting XSDB can take a while)" aside.

- **AXI monitor — meaningful geometry telemetry:** the `AXI_GEOM` register's
  channel-count field carried a hardcoded `0x1F` placeholder and the ID-width
  field a bare `0` with no documented meaning. They now read the real values —
  ID width `0` (AXI4-Lite has no `AWID`/`ARID`) and `5` captured channels
  (AW/W/B/AR/R) — via named RTL localparams, validated in cocotb and on hardware.

- **AXI monitor — VALID-qualified write-address trigger (correctness):**
  `write_addr_capture_config` now builds the trigger at `awaddr`'s real bit
  offset (from the probe map) and, by default, also requires `awvalid` — so it
  fires on a genuine write-address handshake attempt instead of on a stale
  address the bus is parked on while `awvalid` is low. It works on **both** raw
  and decode builds now (previously it rejected decode builds because `awaddr`
  left the low 32 bits); `Analyzer.configure` programs the full-width value/mask
  through the wide window. `Analyzer` gained wide value/mask programming for any
  trigger whose value/mask exceed 32 bits (guarded by the `WIDE_TRIG` cap bit).

- **AXI monitor — beat storage qualifier:** `AxiMonitor.event_capture_config`
  gained `store_on_beats=True` (and a `beat_storage_qual()` helper). On a
  DECODE_EN build it enables the ELA storage qualifier to keep only cycles where
  a channel handshakes (`aw_hs`..`r_hs`), so a mostly-idle bus no longer fills
  the capture buffer with idle repeats — the window holds transaction beats.

- **AXI monitor — single-source sample layout:** the capture-vector bit layout
  now lives in one place (`fcapz.axi_layout`); the host `sample_width`/probe map
  and the bundled `.prob` sidecars (via `tools/gen_axi_probes.py`) derive from
  it, and a test asserts the derived width matches the RTL `SAMPLE_W` formula —
  replacing four hand-maintained copies that had to stay in lockstep.

- **Web — Run bar shows the trigger condition:** the Run bar now displays what
  Arm will fire on (e.g. `any_err=1 & awaddr=0x40`), decoded live from the
  config against the named probes — so it's correct whether the trigger came
  from the trigger table, the AXI Mon tab, or the raw Advanced fields. Falls
  back to `value & mask` when no probe map is loaded, and reads the sequencer
  and external-trigger combine too.

- **RPC / Web — instant core switching:** switching the session between the
  ELA and the AXI monitor (which live on different BSCAN taps) no longer does a
  full reconnect. A new `rebind` RPC keeps the live JTAG transport and just hops
  the tap + re-probes, so the switch is one short round-trip instead of a
  `connect` (transport teardown + reopen) plus `probe`. The web AXI Mon tab and
  Cores "Use this core" switch use it; side sessions (EIO/AXI/UART) are left
  untouched.

- **Web — Trigger & Run move onto the viewer:** the Trigger setup leaves the
  dock for a hover-out drawer on the waveform's right edge (a thin `⚡ Trigger`
  rail expands the full ILA-style setup; pin to keep it open). The Run controls
  (Arm / Trigger Immediate / Stop / Auto re-arm / Download) become a bar above
  the viewer: pinned by default so it docks and shares the vertical space, or
  unpinned to collapse to a `▶ Run` tab that peeks on hover and stays open while
  a capture is armed/running. Reclaims the dock space the two panels used.

- **Web:** the default HTTP port is now `7373` (was `8000`), to avoid clashes
  with the many tools that default to 8000. Override with `--port`.

- **Version:** Bumped project/RTL identity version to `0.4.5`.

- **EJTAG bridges:** EJTAG-AXI and EJTAG-UART now expose ELA/EIO-style
  packed `VERSION` identities through their native `CMD_CONFIG` paths:
  `JX` (`0x4A58`) for AXI and `JU` (`0x4A55`) for UART, with major/minor
  version bytes in `VERSION[31:16]`. Hosts still accept legacy `EJAX` /
  `EJUR` bridge IDs for old bitstreams and emit `RuntimeWarning`.

- **Host API:** EJTAG `connect()` / `attach()` now report normalized
  16-bit core IDs (`bridge_id` / `id` and `core_id`) for both new and
  legacy bitstreams. Legacy 32-bit identity words are exposed separately
  as `legacy_raw_id` with `legacy_id=True`; new bitstreams report
  `legacy_raw_id=None`. EJTAG bridge
  `version_major` / `version_minor` now decode the 8-bit packed VERSION
  fields for new bitstreams; legacy bitstreams keep the old 16-bit decode.
  Upgrade the host before rebuilding v0.4.0 bitstreams: v0.3.x hosts do
  not understand the new packed EJTAG identity word.

- **Version resolution:** Source-tree runs now resolve the package version
  from the repo `VERSION` file before falling back to installed package
  metadata, so a stale wheel/editable install cannot mask the working-tree
  version.

- **Debug manager:** Added a generic `"CM"` active-slot manager and Xilinx
  `fcapz_debug_multi_xilinx7` wrapper so multiple ELAs and an EIO can share
  one USER chain. The Arty reference now routes two ELA slots plus two EIO
  slots through USER1; EIO CLI/API calls can pass `instance=N` for managed
  slots.

- **GUI:** ELA capture can select managed ELA slots when a USER1 core manager
  is present, and the EIO dock can attach to managed EIO slots such as Arty's
  USER1 slots 2 and 3.

### Deprecated

- **Python desktop GUI (`fcapz-gui`):** no longer maintained in favour of the
  web frontend (`fcapz-web`), which is now the supported interface. The GUI
  still runs but shows a notice on launch and won't get new features or fixes.

### Fixed

- **Web — AXI-monitor probe map leaked onto the next board's ELA:** the browser
  session kept its ELA config (probes/trigger) across disconnect, so an
  AXI-monitor probe map (e.g. `awaddr` at bit 8, width 32) carried over to the
  next board's plain 8-bit ELA and every capture failed with
  `probe 'awaddr' exceeds sample width 8`. Disconnect now resets the ELA config
  to its defaults — probes belong to the board you were on. A backend contract
  test pins that `Analyzer._validate_probes` still rejects an over-wide probe.

- **hw_server — wide-core readback was ~25x too slow (AXI monitor):** reading a
  160-bit x 256 capture back took ~13-17 s — over the web UI's 14 s
  "Trigger Immediate" client timeout, so full-depth monitor captures failed
  intermittently in the browser. Two per-word paths were to blame: `read_block`'s
  DATA-window fallback did one xsdb round-trip per 32-bit word, and
  `_read_block_user1` hardcoded USER1 (so a monitor on USER2 read the wrong
  chain). Both now use one pipelined `jtag sequence` per chunk on the active
  chain, and `Analyzer._read_data_words` routes wide cores through `read_block`
  instead of its own per-word loop. Measured on Arty: full-depth monitor capture
  **13 s -> 0.52 s** (~25x), identical data. `USER1_DATA_SETTLE_READS` removed.

- **AXI monitor — immediate/always-true trigger never fired (root cause):** on a
  `WIDE_TRIG` core (the AXI monitor, `SAMPLE_W=160`), `Analyzer.configure` only
  programmed the wide-trigger window's upper comparator words when the trigger
  value/mask exceeded 32 bits. An always-true trigger (`value=0, mask=0`, used by
  "Trigger Immediate") therefore cleared only the low 32 mask bits and left the
  upper 128 mask bits at their stale/reset value, so the comparator was not
  actually don't-care — the trigger never fired and the capture never completed
  (10s `TimeoutError`). `configure` now programs every high word on every
  configure for wide cores (zeroing them when the value/mask fit in 32 bits), so
  the immediate trigger is genuinely always-true. Validated on Arty hardware:
  immediate monitor captures now complete (8 and full-depth 256 samples).

- **hw_server — AXI monitor readback hang (root cause):** capturing a wide core
  (`SAMPLE_W > 32`, e.g. the 160-bit AXI monitor) over hw_server could hang the
  server indefinitely — previously mislabeled a "timing-marginal" wide readback.
  The real cause: the 256-bit burst DR packs whole samples per scan, valid only
  when a sample is one 32-bit word, but `capture()` passes a *word* count for
  wide samples (5 words for 160 bits). The burst engine read that as a *sample*
  count and built a 5x-oversized single-line TCL scan sequence that xsdb never
  finishes, so `_send`'s `readline()` blocked forever (and the returned data
  would have been wrong-width regardless). `read_block` now gates the burst
  fast-path on the selected core's `SAMPLE_W`; wide cores use the 32-bit-word
  DATA path that `capture()` reassembles. Deterministic and correct; no hang.

- **Web — OpenOCD orphaned on stop (adapter held):** when `openocd` was launched
  via a Windows `.cmd`/`.bat` launcher shim, the real `openocd.exe` ran as a
  *grandchild*, so `openocd_stop` killed the shim but left `openocd.exe` holding
  the JTAG adapter — the next config (or connect) then failed with
  `LIBUSB_ERROR_ACCESS`. Teardown now kills the whole process tree
  (`taskkill /T` on Windows) and binary detection prefers a real `.exe` over a
  shim, so the adapter is reliably released between probes. This is what made
  auto-discovery of a second board on the same adapter fail.

- **Host / hw_server:** `connect()` now waits for a JTAG target matching
  `fpga_name` to appear before selecting it (bounded by `target_wait_timeout`,
  default 3s), instead of firing `jtag targets -set` into a transiently empty
  chain. This rides out the re-enumeration window when another board is
  plugged in (or right after `fpga -file`); previously that produced opaque
  "target list is empty" / "no bit string in output" errors. Times out with a
  clear message listing the visible targets.

- **Host / hw_server:** `EjtagAxiController.connect()` and
  `EjtagUartController.connect()` now skip the generic 49-bit register
  ready probe during programming and poll their native streaming
  `CMD_CONFIG` identities instead. `EioController.connect()` selects its
  USER chain before the transport-level ready probe, so USER3 EIO connects
  no longer depend on USER1/ELA responding first.

- **Web — wide bit vectors:** ELA trigger value/mask and EIO values now cross
  JSON as hex/decimal strings (parsed with full precision) and the frontend
  uses BigInt, so values wider than 53/31 bits no longer round or truncate.
  `eio_read` adds a full-width `value_hex`; `eio_write` accepts hex strings.

- **Web — Disconnect:** `close` is now a full session teardown, releasing the
  EIO / AXI / UART transports (and any bare transport from a partial connect),
  not just the analyzer.

- **Web — hw_server connect:** the XSDB-backed connect path uses a larger
  budget than OpenOCD's fast TCL (capped at 15 s), so a slow XSDB cold start no
  longer aborts the connect prematurely.

- **Web — segmented wide captures:** segmented `capture` now honors the
  requested `format`; wide (>53-bit) segmented captures no longer attach
  JSON-number samples, so the UI's Download JSON can't export rounded data.

- **Web — AXI addressing:** the AXI panel normalizes addresses/data to
  canonical `0x…` hex before sending (bare decimal input previously targeted a
  different register than the one displayed) and rejects malformed input.

- **Web — auto re-arm:** a per-window trigger timeout re-arms instead of
  stopping with an error, so sparse triggers are captured as intended.

- **Web — EIO polling:** the input poller keeps at most one `eio_read` in
  flight, so armed captures no longer stack timed-out polls behind the
  server's command lock.

- **Web — board discovery:** `discover_boards` accepts a `budget` (overall
  wall-clock cap); the UI sends 12 s so discovery always answers before the
  client aborts and cannot keep the command lock busy afterwards.

- **Web — loopback checks:** loopback detection now uses `ipaddress`
  (127.0.0.0/8, `::1`, IPv4-mapped `::ffff:127.0.0.1`), fixing OpenOCD control
  being denied to local browsers on dual-stack binds; the `--token` warning
  uses the same logic.

- **Web — WebSocket:** valid-JSON non-object frames (e.g. `42`) get an in-band
  `{ok:false}` reply instead of crashing the connection.

- **Web — viewer:** the Vite dev server proxies `/surfer` to the backend (the
  Viewer tab was blank under `npm run dev`), and Surfer's first-load signal
  setup is no longer lost when a second capture arrives within ~450 ms.

- **Web — IR table:** `connect` infers `ir_table` from the tap name server-side
  and echoes the resolved preset; the frontend's duplicate mapping is gone.

- **Web — Run toolbar drag:** the Run bar's `::` grip was decorative (dockview
  only drags via tab/title bars) — the Run panel now has a real "Run" tab that
  drags, stacks, and closes like every other panel; the grip is gone.

- **RPC — segmented VCD:** `capture` with `segments: true` and `include_vcd`
  now returns **all** segments concatenated on the time axis (with a `segment`
  marker wire), not just segment 0's waveform.

- **RPC — timeout clamping:** caller-supplied waits (capture/scan/uart_recv
  `timeout`, `openocd_start` `wait`, discovery `budget`) are clamped to 300 s
  so a handful of huge timeouts can't pin every web threadpool worker.

- **Web — OpenOCD double-spawn:** a second `openocd_start` on the same port
  during OpenOCD's bind window now waits on the pending spawn instead of
  launching a second process that orphaned the first (both fighting for the
  JTAG adapter).

- **ELA pre-trigger capture:** sample memory now maintains a rolling
  pre-arm history in single-segment mode, so a trigger shortly after
  `arm()` captures the actual early event with valid pre-trigger samples
  instead of waiting for a post-arm prefill window or exposing stale/zero
  entries. Segmented capture mode is unchanged and remains tracked
  separately. The pre-trigger window may include samples from before the
  latest `arm()` call, including the previous capture tail; pulse
  `sample_rst` between captures if each capture must be independent.

- **Arty / EJTAG-AXI host path:** `EjtagAxiController` now prefers
  batched USER4 raw-scan sequences for bridge probe, single
  transactions, block traffic, and bursts when running over Xilinx
  `hw_server`.  On the Arty A7 reference setup, isolated USER4 raw
  scans could return all-zero TDO even though the bridge was alive;
  batching the same USER4 traffic is hardware-validated and fixes the
  false `Bad EJTAG-AXI VERSION[15:0]: 0x0000` failure.

- **Arty reference EIO:** USER3 `probe_in` now exposes
  `{btn[3:0], slow_counter[3:0]}` where `slow_counter` increments once
  per second, and the Arty EIO hardware test now checks that slower
  observable behavior directly.

- **GUI / EIO:** Probe UI stays disabled until **Attach EIO**; **All outputs on**
  / **All outputs off** buttons write the full output width to all 1s or all 0s;
  output checkboxes sync from hardware readback
  after writes; tooltips plus [`docs/06_eio_core.md`](docs/06_eio_core.md) and
  [`docs/12_gui.md`](docs/12_gui.md) clarify Attach, **Poll inputs** (inputs
  only) vs **Outputs** (fabric / board LEDs on the Arty reference).

- **Arty A7-100T constraints:** `arty_a7.xdc` mapped `led[0:3]` to the wrong
  package pins; they now match Digilent’s reference (**H5, J5, T9, T10**).
  Rebuild the bitstream for EIO → LED feedback on the board.

- **Arty reference (`arty_a7_top`):** Resynchronize `probe_out[3:0]` from the
  EIO `jtag_clk` domain into `sys_clk` before driving the green LEDs.

- **hw_server / OpenOCD:** Serialize transport I/O with a mutex so concurrent
  JTAG users (e.g. EIO input polling on a timer plus ELA capture on a worker
  thread) no longer corrupt the xsdb or OpenOCD protocol stream, which used to
  surface as ``xsdb: no bit string in output`` with empty stdout.

- ELA capture now commits the trigger-cycle sample even when decimation or
  storage qualification would otherwise skip that cycle, so
  `samples[pretrigger]` remains the actual trigger sample.

- ELA full-depth pre/post windows no longer write one extra post-trigger
  sample or advance the start pointer incorrectly at the end of capture.

- ELA sequencer stages with `count_target=1` now advance or fire on the
  first matching occurrence.

- ELA 48-bit timestamp readback and wide sample readback now zero-extend
  partially used 32-bit chunks instead of truncating or leaking stale bits.

- ELA triggers now wait until the requested pretrigger history has been filled,
  preventing stale RAM/timestamp entries from appearing at the front of captures
  when a trigger fires immediately after arm, especially with decimation enabled.

### Security

- **Web — OpenOCD tap injection:** the OpenOCD tap name is now validated
  (`[A-Za-z0-9._:-]+`) before it is interpolated into OpenOCD TCL, closing a
  command-injection / RCE path from an attacker-controlled `tap`.

- **Web — cross-origin & DNS rebinding:** cross-origin API sharing is now OFF
  by default (the bundled UI is same-origin; opt in with `--cors-origin`), and
  when bound to loopback the server rejects requests whose `Host` header is not
  a loopback name. Together these stop a malicious website from driving the
  board (or starting OpenOCD) via the local API.

### Tests

- **AXI monitor — wide-trigger validation:** cocotb `wide_trigger_high_bit`
  triggers on a bit above bit 31 (idle-bus control must not fire) and
  `beat_storage_qualifier` proves idle cycles are dropped. On hardware,
  `TestAxiMonitorWideTrigger` validates on the Arty A7 that a trigger on
  `awvalid` (bit 43) and a VALID-qualified full write-address both work — with
  the full AXI-monitor and plain-ELA suites green on the rebuilt bitstream.

- **AXI monitor — stress coverage:** a new cocotb `stress_backtoback_fill`
  target saturates the tap with back-to-back write handshakes, fills the capture
  buffer to depth, and reads every wide (multi-word `SAMPLE_W`) sample back —
  verifying each slot returns its own distinct sample (the functional side of
  the timing-marginal wide readback). On hardware, `TestAxiMonitorStress` hammers
  the arm/trigger/complete path: 50 back-to-back arm→trigger→done churn cycles,
  30 repeated captures under continuous MicroBlaze CPU traffic, and a sustained
  clean-traffic run that must not false-trigger on `any_err`. All green on the
  Arty A7 with no regressions.

- **Web frontend:** vitest unit tests for the frontend's pure logic
  (`toHexParam` hex/decimal normalization, probe-text parsing, and the
  `rpc()`/`RpcError` envelope contract that auto re-arm depends on), run via
  `npm test` and wired into the CI `frontend-build` job before the bundle
  build.

- Added `tb/fcapz_ela_bug_probe_tb.sv` as a normal regression testbench for
  the ELA capture-window, decimated-trigger, sequencer-count, timestamp, and
  wide-sample readback cases.

- `sim/run_sim.py` now runs a shared `iverilog -Wall` RTL lint pass before the
  default simulation regression, and supports `--lint-only` for local and CI
  lint-only runs.

### CI

- GitHub Actions now invokes `python sim/run_sim.py --lint-only` for RTL lint,
  while the simulation job runs `python sim/run_sim.py`, so `iverilog -Wall`
  is part of both the standalone lint job and the full regression path.

### Documentation

- [docs/07_ejtag_axi_bridge.md](docs/07_ejtag_axi_bridge.md),
  [docs/14_transports.md](docs/14_transports.md), and
  [docs/17_troubleshooting.md](docs/17_troubleshooting.md) now note the
  Arty / `hw_server` USER4 batching behavior for EJTAG-AXI; 
  [docs/06_eio_core.md](docs/06_eio_core.md) reflects the reference
  design's 1 Hz EIO counter nibble.

- README and manual resource tables refreshed against Vivado 2025.2
  synthesis reports (`scripts/resource_comparison.tcl` harness + Apr 2026
  `arty_a7_top` place & route): corrected baseline slice LUTs (~1,595 vs
  stale ~1,990), sequencer/SQ rows, reference top (~2.7k LUT / 1.5 BRAM /
  optional ELA features + EIO + AXI), and WNS for `sys_clk`.  Spec
  architecture parameters list extended for decimation, timestamps, segments,
  etc.; `resource_comparison.tcl` resolves repo root from its path (or
  `FPGACAP_ROOT`).

- README and user manual (`docs/`, including specs) no longer quote fixed
  KB/s (or similar) throughput numbers; they describe batching, round trips,
  and tool/adapter dependence instead.

- [docs/12_gui.md](docs/12_gui.md) and [docs/06_eio_core.md](docs/06_eio_core.md)
  describe the EIO panel as implemented (attach, **Poll inputs**, ms-period
  combo, per-bit toggles); troubleshooting notes concurrent poll + capture.

- [CONTRIBUTING.md](CONTRIBUTING.md) and [README.md](README.md) now describe the
  default pytest `-m "not hw"` filter, how to override it, and the opt-in
  GUI+hardware suite (`tests/test_gui_hw_capture.py`, `FPGACAP_GUI_HW=1`).
  Pre-push checklist distinguishes Arty integration tests from GUI+hardware.

- CONTRIBUTING branch rules and pre-push checklist require updating the user
  manual under `docs/` (index `docs/README.md`) when end-user behaviour or
  documentation should change.

---

## [v0.3.0]

### ⚠ Breaking changes

**1. Python package renamed: `host.fcapz` → `fcapz`**

Any external code that imports from `host.fcapz.*` will break with
`ModuleNotFoundError: No module named 'host'` after upgrading. There is
no compatibility shim — this is a hard rename. The fix is mechanical:

```diff
- from host.fcapz import Analyzer, CaptureConfig, TriggerConfig
- from host.fcapz.transport import XilinxHwServerTransport
- from host.fcapz.eio import EioController
- from host.fcapz.ejtagaxi import EjtagAxiController, AXIError
- from host.fcapz.ejtaguart import EjtagUartController
+ from fcapz import Analyzer, CaptureConfig, TriggerConfig
+ from fcapz.transport import XilinxHwServerTransport
+ from fcapz.eio import EioController
+ from fcapz.ejtagaxi import EjtagAxiController, AXIError
+ from fcapz.ejtaguart import EjtagUartController
```

CLI entry point form also changes:

```diff
- python -m host.fcapz.cli ...
- python -m host.fcapz.rpc
+ python -m fcapz.cli ...
+ python -m fcapz.rpc
```

The installed `fcapz` console script (`pip install -e .` then run
`fcapz`) is unchanged. The on-disk path `host/fcapz/` is unchanged
— only the importable name moved.

One-shot migration on a checkout:

```bash
# Linux / macOS
grep -rl 'host\.fcapz' . | xargs sed -i 's/host\.fcapz/fcapz/g'

# Windows PowerShell
Get-ChildItem -Recurse -File | Select-String -Pattern 'host\.fcapz' -List |
  ForEach-Object { (Get-Content $_.Path) -replace 'host\.fcapz', 'fcapz' |
                   Set-Content $_.Path }
```

**2. EIO `VERSION` register replaces `EIO_ID`**

The 32-bit register at EIO address `0x0000` was previously a flat
32-bit identity word `0x56494F01` (`"EIO"` + literal `0x01`).  It is
now the same `{major, minor, core_id}` layout as the ELA core, with
`core_id = ASCII "IO" = 0x494F`.  ``EioController.connect()`` now
raises ``RuntimeError`` on a wrong / missing core_id, exposes
``version_major`` / ``version_minor`` / ``core_id`` on the controller
instance, and the old hardcoded `EIO_ID = 0x56494F01` constant is
gone.

Pre-v0.3.0 EIO bitstreams will fail the new magic check and need to
be rebuilt.

**3. ELA `VERSION` register layout changed**

The 32-bit register at address `0x0000` no longer encodes
`{major[15:0], minor[15:0]}`. The new layout is:

| Bits | Field | Value (v0.3.0) |
|------|-------|----------------|
| `[31:24]` | `major` (8-bit) | `0x00` |
| `[23:16]` | `minor` (8-bit) | `0x02` |
| `[15:0]`  | `core_id` (ASCII `"LA"`) | `0x4C41` |

Constant: `0x0002_4C41`.

`Analyzer.probe()` now raises `RuntimeError` on a wrong / missing
core_id, so an unprogrammed FPGA, a wrong JTAG chain, or a
non-fcapz bitstream is rejected before any other ELA register is
read. The returned dict gains a new `core_id` key.

Hosts that decoded `version` by hand must update:

```diff
- version_major = (version >> 16) & 0xFFFF
- version_minor = version & 0xFFFF
+ version_major = (version >> 24) & 0xFF
+ version_minor = (version >> 16) & 0xFF
+ core_id       = version & 0xFFFF        # must equal 0x4C41
```

Bitstreams built before v0.3.0 will report `core_id = 0x0001`
(because the old encoding put `minor=1` in the low half), which
the new probe magic check rejects. **Rebuild the bitstream** when
upgrading the host.

### Added

**Xilinx UltraScale / UltraScale+ wrappers**
- Five new wrapper files that target UltraScale and UltraScale+
  devices.  Because BSCANE2 is the same primitive on 7-series,
  UltraScale, and UltraScale+ (verified against UG570 / UG574),
  the new files are **thin shims** that instantiate the existing
  `_xilinx7` modules.  This avoids duplicating ~280 LOC of wrapper
  body across two files; any change to the 7-series wrappers
  automatically applies to the UltraScale path.
  * `rtl/jtag_tap/jtag_tap_xilinxus.v` — instantiates `jtag_tap_xilinx7`
  * `rtl/fcapz_ela_xilinxus.v` — instantiates `fcapz_ela_xilinx7`
  * `rtl/fcapz_eio_xilinxus.v` — instantiates `fcapz_eio_xilinx7`
  * `rtl/fcapz_ejtagaxi_xilinxus.v` — instantiates `fcapz_ejtagaxi_xilinx7`
  * `rtl/fcapz_ejtaguart_xilinxus.v` — instantiates `fcapz_ejtaguart_xilinx7`
- Distinct module names give users an unambiguous per-vendor
  entry point in their Vivado source-file list and in `set_property
  top` calls, while the underlying definition lives in one place.
- Confirmed device families documented at the top of
  `jtag_tap_xilinxus.v`:
  * UltraScale: Kintex / Virtex UltraScale
  * UltraScale+: Artix / Kintex / Virtex / Zynq UltraScale+
- USER chain → IR opcode mapping for UltraScale (UG570 / UG574):
  USER1=`0x24`, USER2=`0x25`, USER3=`0x26`, USER4=`0x27` —
  different from the 7-series codes.
- Host: `OpenOcdTransport` and `XilinxHwServerTransport` gain
  named `IR_TABLE_XILINX7`, `IR_TABLE_XILINX_ULTRASCALE`, and
  `IR_TABLE_US` (alias) presets so UltraScale users don't have
  to look the codes up.  Pass via the existing `ir_table=...`
  constructor parameter.  README example updated.
- CI: `lint-rtl` job adds 5 new iverilog elaboration steps for the
  new wrappers (using the existing BSCANE2 sim stub).  Shared
  `IVFLAGS` now includes `-I rtl` so `\`include "fcapz_version.vh"`
  resolves on the runner.
- README support matrix and project structure updated to list the
  UltraScale wrappers separately from 7-series.
- Versal devices (XCVM/VC/VP/VE/VH) are explicitly NOT covered;
  they need a separate wrapper that targets their TAP primitive.
- Status: implemented in RTL, lint-clean under `iverilog -Wall`,
  IR-table presets unit-tested (5 new tests, total 177).  Not yet
  hardware-validated (no UltraScale board on hand).

**Single source of truth for the project version**
- New ``VERSION`` text file at the repo root holds the canonical
  ``MAJOR.MINOR.PATCH`` semver string.
- New ``tools/sync_version.py`` reads it and regenerates
  ``rtl/fcapz_version.vh``, a Verilog header that exposes the version
  fields and per-core ASCII identifiers as `\`define`s
  (``FCAPZ_VERSION_MAJOR``, ``FCAPZ_VERSION_MINOR``,
  ``FCAPZ_ELA_VERSION_REG``, ``FCAPZ_EIO_VERSION_REG``, etc.).
- ``rtl/fcapz_ela.v`` and ``rtl/fcapz_eio.v`` ``\`include`` the
  generated header and use ``FCAPZ_*_VERSION_REG`` instead of
  hardcoded constants in their ``ADDR_VERSION`` read-mux paths.
- The ELA and EIO testbenches reference the same defines so a
  version bump propagates from the VERSION file → header →
  RTL → TB in one ``python tools/sync_version.py`` invocation.
- ``pyproject.toml`` declares ``dynamic = ["version"]`` and reads
  the same VERSION file via setuptools, so the Python package
  version, the RTL VERSION register constants, and the testbench
  expectations all share one number.
- New ``host/fcapz/_version.py`` exposes ``__version__`` via
  ``importlib.metadata`` (after ``pip install``) with a fallback
  that reads the VERSION file directly so editable / dev runs
  still work.  ``fcapz._version_tuple()`` returns
  ``(major, minor, patch)`` for tests and probe comparisons.
- New ``analyzer.expected_ela_version_reg()`` and
  ``_expected_eio_version_reg()`` test helpers compute the
  packed VERSION register from the canonical version, so
  ``FakeTransport`` instances stay in sync automatically.
- New ``test_probe_matches_canonical_version`` and
  ``test_connect_decodes_version_fields`` regression tests fail
  loudly if the RTL header and Python ``__version__`` ever drift.
- ``sim/run_sim.py`` adds ``-I rtl`` so iverilog finds
  ``fcapz_version.vh``.
- ``examples/arty_a7/build_arty.tcl`` registers
  ``rtl/fcapz_version.vh`` as a global Verilog include and
  upgrades existing on-disk projects in place so post-v0.3.0
  rebuilds don't need a fresh project dir.
- ``.github/workflows/ci.yml`` gains a ``version-sync`` job that
  runs ``tools/sync_version.py --check`` and fails the build if
  the generated header has drifted from VERSION (e.g. someone
  bumped the file but forgot to re-run the script).

**Configurable trigger delay (TRIG_DELAY)**
- New ELA register `ADDR_TRIG_DELAY` (`0x00D4`, RW, 16-bit, default 0)
- When non-zero, the committed trigger sample is shifted N sample-clock
  cycles after the trigger event, compensating for upstream pipeline
  latency between a cause signal and its visible effect on the probe bus
- RTL: `trig_delay`/`trig_delay_count`/`trig_delay_pending` state in the
  sample-clock domain; routed through the existing 2-FF sync chain;
  latched on arm; on `trigger_hit` the FSM either commits immediately
  (delay=0, legacy behavior) or enters a per-cycle countdown that
  commits `trig_ptr <= wr_ptr` at terminal count. Buffer recording
  unaffected during the delay window. Cleared on `reset_pulse` and on
  segmented re-arm.
- Host API: `CaptureConfig.trigger_delay` field, validated 0..65535 in
  `Analyzer.configure()`
- CLI: `--trigger-delay` argument (decimal or hex) on both `configure`
  and `capture` subparsers, backed by a new `_uint16` validator
- RPC: `trigger_delay` field in `_build_config`, validated by
  `_validated_trigger_delay`
- Testbench: 3 new ELA TB scenarios (round-trip, delay=0 equivalence
  with legacy capture window, delay=4 with verified sample alignment).
  ELA TB now 58/0 passing.
- Hardware integration tests: `test_trigger_delay_shifts_window`
  (TRIG_DELAY=4) and `test_trigger_delay_zero_equivalence` — both pass
  on real Arty A7-100T silicon.
- Register map doc updated.

**Package rename: `host.fcapz` → `fcapz`**
- `pyproject.toml` package discovery now uses `where = ["host"]`,
  `include = ["fcapz*"]` so editable installs (`pip install -e .`)
  expose the importable name as `fcapz` — matching the existing CLI
  binary name.
- Project version bumped to `0.2.0`.
- All tests, examples, and the README updated from `host.fcapz`
  to `fcapz`. Two README import lines that already used the bare
  `from fcapz import ...` form (and silently broke before this
  refactor) now actually work.
- New `conftest.py` at the repo root inserts `host/` into `sys.path`
  so `from fcapz import …` resolves when running tests directly
  without `pip install`.
- `host/fcapz/*.py` is unchanged (already used relative imports).

**Build infrastructure**
- New `examples/arty_a7/build.py` Python launcher for Vivado batch
  builds: orphan helper-process cleanup (`vrs.exe`,
  `parallel_synth_helper`), file-lock detection via
  `_runs_dir_is_deletable()`, and automatic sidestep to a fresh
  sibling project directory when the canonical path is locked by a
  zombie Vivado run on Windows.
- `examples/arty_a7/build_arty.tcl` reuses an existing project (with
  `reset_run` on stale runs) instead of always recreating, and honors
  `FPGACAP_PROJECT_DIR` from the launcher.

---

## [0.2.0] — 2026-04-07

### Added

**EJTAG-AXI Bridge (`rtl/fcapz_ejtagaxi.v`)**
- New module: JTAG-to-AXI4 master bridge on USER4 (CHAIN=4)
- 72-bit pipelined streaming DR — one AXI transaction per scan, zero polling
- 12 commands: single read/write, auto-increment, burst setup/data, config, reset
- Toggle-handshake CDC (TCK → axi_clk) with shadow registers
- Async FIFO (Gray-coded pointers, configurable `FIFO_DEPTH`) for burst reads
- Per-beat toggle handshake for burst writes (no inter-beat timeout)
- Parameters: `ADDR_W`, `DATA_W`, `FIFO_DEPTH`, `TIMEOUT`
- `FIFO_DEPTH` exposed in `FEATURES[23:16]` as `(FIFO_DEPTH-1)` (AXI4 awlen
  convention so 256 fits in 8 bits) and validated at elaboration time
- Vendor wrappers: `fcapz_ejtagaxi_xilinx7.v`, `fcapz_ejtagaxi_intel.v`
- Reusable AXI4 test slave: `tb/axi4_test_slave.v`
- Testbench: `tb/fcapz_ejtagaxi_tb.sv` (29 assertions)
- Hardware-validated on Arty A7-100T

**EJTAG-UART Bridge (`rtl/fcapz_ejtaguart.v`)**
- New module: JTAG-to-UART bridge with bidirectional TX/RX async FIFOs
- 32-bit pipelined DR; commands: NOP, TX_PUSH, RX_POP, TXRX, CONFIG, RESET
- ~1.5 KB/s per direction (Arty A7 / FT2232H / XSDB)
- Use cases: debug console, firmware upload, printf-over-JTAG
- Vendor wrappers: `fcapz_ejtaguart_xilinx7.v`, `fcapz_ejtaguart_intel.v`
- Testbench `tb/fcapz_ejtaguart_tb.sv` and `host/fcapz/ejtaguart.py`
- CLI: `uart-send`, `uart-recv`, `uart-monitor`

**Async FIFO (`rtl/fcapz_async_fifo.v`)**
- Vendor-agnostic async FIFO with two implementations:
  `USE_BEHAV_ASYNC_FIFO=1` portable Gray-coded pointer FIFO (default)
  and `USE_BEHAV_ASYNC_FIFO=0` Xilinx XPM wrapper
- Equivalence testbench `tb/fcapz_async_fifo_equiv_tb.v` +
  `tb/xpm_fifo_async_stub.v` so the XPM branch elaborates and runs
  under iverilog without a vendor install
- Python regression test `tests/test_rtl_fifo_equiv.py` runs the
  equivalence sim via subprocess (skipped when iverilog not on PATH)

**ELA capture engine — advanced features**
- Storage qualification (STOR_QUAL): record only samples that match a
  secondary comparator, +21 LUTs for 10x effective depth on sparse
  signals; new RW registers `SQ_MODE` (0x0030), `SQ_VALUE` (0x0034),
  `SQ_MASK` (0x0038), exposed in Python API and CLI
- Sample decimation (DECIM_EN=1): /N divider, captures every N+1 cycles
- External trigger I/O (EXT_TRIG_EN=1): `trigger_in`/`trigger_out` ports
  with disabled / OR / AND combine modes
- Per-sample timestamp counter (TIMESTAMP_W=32 or 48), exported to VCD
- Segmented memory (NUM_SEGMENTS>1): auto-rearm after each segment
  fills, capturing multiple trigger events in a single run
- Runtime probe mux (PROBE_MUX_W>0): one ELA observes a wide bus and
  selects a SAMPLE_W slice at runtime via `PROBE_SEL` (0x00AC)

**Transport chain selection and hardening**
- `Transport` ABC: `select_chain()`, `raw_dr_scan()`, `raw_dr_scan_batch()`
- Both OpenOCD and hw_server transports support dynamic IR/chain selection
- Verified IR codes on xc7a100t: USER1=0x02, USER2=0x03, USER3=0x22, USER4=0x23
- `XilinxHwServerTransport.connect()` now waits until the FPGA responds
  with valid data after `program()` (configurable `ready_probe_addr` /
  `ready_probe_timeout`); raises `ConnectionError` on timeout with the
  last value, attempt count, and remediation hints
- `fpga_name` and `bitfile` validated against TCL-safe regexes to
  prevent command injection through XSDB session strings
- Parser failures now include the last 10 lines of captured xsdb stderr
  for diagnosability
- `assert` statements in `_cmd()` and `_drain_stderr()` replaced with
  `RuntimeError` (safe under `python -O`)

**Host API hardening**
- `analyzer.configure()` rejects sequences exceeding hardware
  `TRIG_STAGES`
- `ejtagaxi.close()` warns instead of swallowing reset failures silently
- `ejtagaxi.connect()` caches `FIFO_DEPTH` from FEATURES;
  `burst_read`/`burst_write` reject counts exceeding the bridge FIFO
  or AXI4 max (256)
- `rpc._parse_probes()` rejects negative `lsb` / non-positive `width`
- `rpc` validates `stor_qual_mode` in `{0, 1, 2}`
- `events.ProbeDefinition` validates `width > 0` and `lsb >= 0`
- `events.summarize()` always emits `longest_burst` / `first_edge` /
  `last_edge` keys for a stable output schema

**CLI hardening**
- `--port` validated to TCP range 1-65535
- `--timeout` validated `> 0`
- `--count` validated (positive on `axi-dump`/`axi-fill`,
  non-negative on `uart-recv`)
- `--trigger-sequence` JSON / file errors wrapped in
  `argparse.ArgumentTypeError`

**RTL parameter validation**
- `fcapz_ela.v`: `DEPTH` power-of-2, `TRIG_STAGES` 1..4, `SAMPLE_W` 1..256
- `fcapz_ejtagaxi.v`: `FIFO_DEPTH` 1..256 power-of-2
- `fcapz_async_fifo.v`: `DEPTH` power-of-2, `DATA_W >= 1`
- `fcapz_ejtaguart.v`: TX/RX FIFO depths power-of-2, baud / clock ratio
- All checks via `generate` synthesis traps + `initial $error` for sims

**Host software**
- `host/fcapz/ejtagaxi.py`: `EjtagAxiController` — `connect`, `axi_read`,
  `axi_write`, `read_block`, `write_block`, `burst_read`, `burst_write`, `close`
- `write_block`/`read_block` use `raw_dr_scan_batch` for throughput
- CLI: `axi-read`, `axi-write`, `axi-dump`, `axi-fill`, `axi-load`
- RPC: `axi_connect`, `axi_close`, `axi_read`, `axi_write`, `axi_dump`,
  `axi_write_block`
- `EioController` uses `chain=3` and `select_chain()` — EIO hardware access
  unblocked

**Tests**
- 158 Python unit tests (was 91 in v0.1.0): added coverage for
  `Transport` ABC, OpenOCD/XilinxHwServer failure modes, multi-segment
  capture, wide-sample (1-bit and 256-bit) reassembly, sequencer
  bounds, CLI argument validators, trigger-sequence JSON edge cases,
  ProbeDefinition extract edge cases, frequency_estimate corner cases,
  TCL injection rejection, burst FIFO_DEPTH guard rails, async FIFO
  equivalence

**Documentation**
- `CONTRIBUTING.md` with testing guidelines, OpenOCD validation gaps,
  multi-vendor board support
- `docs/specs/register_map.md` updated for SQ, FIFO_DEPTH encoding,
  ext trigger, timestamps, segmented memory, probe mux
- README documentation linked to draft-only specification documents

**Build / lint**
- `ruff` added to dev deps and `E501` (line length, max 100) enforced
- All 24 pre-existing line-length violations fixed

### Fixed
- `jtag_trig_value_w`/`jtag_trig_mask_w` width mismatch for `SAMPLE_W != 32`
  (replaced one-line ternary with `generate` block)
- Same width mismatch for SQ and per-stage sequencer registers at
  `SAMPLE_W <= 32` (replication count went negative inside `always` blocks)
- TCL-safe regex split into `_TCL_NAME_RE` (strict, for the JTAG target
  filter inside double quotes) and `_TCL_PATH_RE` (permissive, allows
  backslash for Windows bitfile paths inside TCL braces) — the original
  combined regex rejected every Windows bitfile path

---

## [0.1.0] — 2026-03-16

### Added

**ELA Core (`rtl/fcapz_ela.v`)**
- Dual-port RAM sample buffer (`rtl/dpram.v`) — 78% LUT reduction vs. distributed-RAM shift-register design
- Dual comparators per trigger stage (A and B) with configurable combine logic (A, B, A&B, A|B)
- 9 compare modes per comparator: EQ, NEQ, LT, GT, LEQ, GEQ, RISING, FALLING, CHANGED
- Multi-stage sequencer trigger (configurable `TRIG_STAGES` parameter, default 4)
- Storage qualification (`STOR_QUAL` parameter) — record only samples that match a secondary comparator
- Probe channel mux (`NUM_CHANNELS` parameter) — one ELA instance observes up to 256 mutually exclusive
  signal buses selected at runtime via the `CHAN_SEL` register (0x00A0); channel is latched on ARM
- `ADDR_FEATURES` register (0x003C) exposes `TRIG_STAGES`, `STOR_QUAL`, and `NUM_CHANNELS` to the host
- `ADDR_CHAN_SEL` (0x00A0, RW) and `ADDR_NUM_CHAN` (0x00A4, RO) registers
- Out-of-range `CHAN_SEL` values are clamped to channel 0 on ARM

**EIO Core (`rtl/fcapz_eio.v`)**
- New module: Embedded I/O on JTAG USER3 chain
- Parameters: `IN_W` (input/probe width), `OUT_W` (output/drive width)
- Input probes synchronised to JTAG clock domain via 2-FF CDC
- Output registers live in JTAG clock domain and are driven combinatorially to `probe_out`
- Register map: `EIO_ID` (0x0000), `EIO_IN_W` (0x0004), `EIO_OUT_W` (0x0008),
  `IN[i]` (0x0010 + i×4), `OUT[i]` (0x0100 + i×4)

**Host software**
- `host/fcapz/eio.py`: `EioController` class — `connect`, `read_inputs`, `write_outputs`,
  `read_outputs`, `set_bit`, `get_bit`
- `host/fcapz/analyzer.py`: added `channel` field to `CaptureConfig`, `configure()` now writes
  `CHAN_SEL`; `probe()` now returns `num_channels`

**Simulation**
- `sim/run_sim.py`: multi-testbench runner (iverilog + vvp); supports `fcapz_ela`, `fcapz_eio`, `chan_mux`
- `tb/fcapz_ela_tb.sv`: rewritten with burst-port connections and RESET between tests (17 checks)
- `tb/fcapz_eio_tb.sv`: new testbench for EIO core (18 checks)
- `tb/chan_mux_tb.sv`: new testbench for channel mux feature (8 checks)
- `sim/bscane2_stub.v`: simulation stub for Xilinx BSCANE2 primitive

**CI**
- `.github/workflows/ci.yml`: 4-job pipeline — `lint-python` (ruff), `test-host` (pytest),
  `lint-rtl` (iverilog -Wall), `sim` (run_sim.py)

**Documentation**
- `docs/specs/register_map.md`: full EIO register map, ELA channel-mux registers
- `docs/specs/architecture.md`: EIO block, channel mux, testing section
- `README.md`: EIO instantiation example, Python API example, CI badge table, project structure

### Fixed
- BRAM write-enable alignment: `mem_we_a` was registered (one cycle late), causing the first
  captured sample to be written to address 1 instead of 0. Changed to a combinatorial wire
  `armed && !done && store_sample` so the enable and address align in the same clock cycle.
- BRAM read address: `rd_addr_sync2` was one pipeline stage behind the request-toggle edge,
  causing every first data read to use the previous read's address. Fixed by using `rd_addr_sync1`
  at edge-detection time (address and toggle are set in the same JTAG clock cycle and are
  therefore coherent).
- BRAM read latency: `rd_phase` was 1-bit (2 states), missing one wait cycle for synchronous
  BRAM read latency. Expanded to 2-bit (3 states) so `dout_a` is captured one cycle after
  `addr_a` is presented.
- Overflow flag used stale pre-arm values; changed to use `pretrig_len_sync2` / `posttrig_len_sync2`
  (values already synchronized at arm time).

---
