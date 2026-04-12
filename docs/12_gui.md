# 12 — Desktop GUI (`fcapz-gui`)

> **Goal**: install, launch, and use the PySide6 desktop GUI.  By
> the end of this chapter you will know what every panel does, how
> the embedded waveform preview interacts with external viewers
> like GTKWave, where settings are stored, and how to drive every
> fcapz core from a graphical front-end.
>
> **Audience**: anyone who would rather click than type.  All the
> same operations are also available via the CLI
> ([chapter 10](10_cli_reference.md)) and the Python API
> ([chapter 09](09_python_api.md)).

## What it is

`fcapz-gui` is a **desktop control panel** that wraps the existing
`fcapz` Python API with a PySide6 (Qt for Python) graphical front-end.
Every panel in the GUI is a thin wrapper around a controller — the
GUI never bypasses the API layer, so its behavior stays in lockstep
with the CLI and the JSON-RPC server.

The GUI is **optional**: it lives behind the `[gui]` extras in
`pyproject.toml`, so a headless install of fpgacapZero stays free
of the Qt dependency.

## Installation

```bash
pip install fpgacapzero[gui]
```

This adds **`PySide6`** and **`pyqtgraph`** and registers a second
console-script entry point:

```bash
fcapz-gui
```

Launch the GUI from any terminal.  No arguments — all configuration
is done in the GUI itself.

If `fcapz-gui` isn't on your `PATH` after install, see
[chapter 02](02_install.md) "Common install pitfalls".

### Headless / SSH installs

If you install `[gui]` on a headless machine for the unit tests
(the GUI tests use Qt's offscreen platform), you can still run
the test suite without a display.  The repo's `tests/conftest.py`
sets `QT_QPA_PLATFORM=offscreen` automatically:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_*.py
```

You only need an actual display when you run `fcapz-gui` itself.

## First launch

```bash
fcapz-gui
```

You will see a window with a top menu bar, a left-side connection
panel, and a tabbed area for the four cores plus a capture history
panel.  Nothing is connected yet — the panels are grayed out until
you click **Connect** on the connection panel.

The GUI **does not auto-connect** at startup.  This is deliberate:
it lets you change which board / bitstream / IR table you're using
without restarting the GUI.

## Panels

### Connection panel

The leftmost (or topmost, depending on layout) panel.  Holds:

| Field | What it does |
|---|---|
| **Backend** | Dropdown: `hw_server` (default) or `openocd` |
| **Host** | TCP host of the transport, default `127.0.0.1` |
| **Port** | TCP port, default `3121` for hw_server / `6666` for openocd |
| **FPGA target** | hw_server target name (e.g. `xc7a100t`) or openocd TAP name |
| **Bitfile** | Optional path to a `.bit` file; if set, the GUI runs `fpga -file <bitfile>` and waits for the readiness probe before declaring "connected" |
| **IR table** | Dropdown: `Xilinx 7-series` (default) or `Xilinx UltraScale / UltraScale+`.  Maps to the `IR_TABLE_*` presets in [chapter 14](14_transports.md) |
| **[Connect] / [Disconnect]** | Open or close the underlying transport |

When you click **Connect**:

1. The GUI builds a `XilinxHwServerTransport` (or `OpenOcdTransport`)
   with the field values.
2. Calls `transport.connect()`, which spawns `xsdb` (or talks to
   OpenOCD), programs the FPGA if a bitfile is set, runs the
   readiness probe.
3. On success, all the other panels become enabled.
4. On failure, an error dialog pops up with the underlying
   exception's message — typically a `RuntimeError` from the
   identity check or a `ConnectionError` from the readiness wait.
   See [chapter 17](17_troubleshooting.md).

The connection settings are persisted across runs in
`~/.config/fpgacapzero/gui.toml` (Linux/macOS) or
`%APPDATA%/fpgacapzero/gui.toml` (Windows) so you don't have to
re-type them every launch.

### Probe summary panel

After connecting, this panel shows the live `Analyzer.probe()`
output:

```
Version : 0.3
Core ID : 0x4C41 ('LA')
Sample W: 8 bits
Depth   : 1024 samples
Channels: 1
Features: decimation, ext-trigger, timestamps (32-bit), 4 segments
```

If the bitstream is wrong (no fcapz core, wrong chain), the
underlying `Analyzer.probe()` raises and the panel shows the error
in red instead of the values.  This is the same magic check as
[chapter 05](05_ela_core.md) "Identity check".

### ELA capture panel

The headline panel.  Form-driven: every field is a widget that
maps directly to a `CaptureConfig` field.

Top section — **trigger**:

| Widget | CaptureConfig field |
|---|---|
| **Pretrigger** spinner (0..depth) | `pretrigger` |
| **Posttrigger** spinner (0..depth) | `posttrigger` |
| **Trigger mode** dropdown | `trigger.mode` (`value_match` / `edge_detect` / `both`) |
| **Trigger value** + radix (default **Hex**; also Dec / Oct / Bin) | `trigger.value` (parsed in the selected base) |
| **Trigger mask** hex input | `trigger.mask` |
| **Trigger delay** spinner (0..65535) | `trigger_delay` (new in v0.3.0) |
| **Decimation** spinner | `decimation` |
| **Ext-trigger mode** dropdown | `ext_trigger_mode` |

Middle section — **storage qualification**:

| Widget | CaptureConfig field |
|---|---|
| **SQ mode** dropdown (off / store-when-match / store-when-no-match) | `stor_qual_mode` |
| **SQ value / mask** hex inputs | `stor_qual_value` / `stor_qual_mask` |

**Probes** subform: a small table where you add named
sub-signals.  Each row is a `name` / `width` / `lsb` triple that
becomes a `ProbeSpec` in the `CaptureConfig`.  The probe panel
validates as you type — overlapping bit ranges turn red.

Main **toolbar** (always visible): **Connect**, **Disconnect**, **Configure**, **Arm**,
**Trigger Immediate**, **Stop**, **Auto re-arm** (checkbox beside **Stop**).

ELA dock — bottom **action buttons**:

| Control | What it does |
|---|---|
| **Arm** | Same as the toolbar: normal ILA-style capture — `configure` from the panel, `arm`, then `capture(timeout)` on a worker thread; wait for the selected trigger, read back, show in History. |
| **Trigger Immediate** | Same as the toolbar: immediate capture — always-true compare (`mask=0` value-match, plus a one-stage sequencer when the bitstream has `TRIG_STAGES>1`) so the core triggers as soon as the pre-trigger history is ready; external-trigger gating is cleared for that run. |
| **Stop** | Ends an auto re-arm loop (cancels the worker between captures). |
| **Configure** | Writes registers from the panel only (`analyzer.configure(cfg)`), without arming. |

**Auto re-arm** (toolbar checkbox): when checked, **Arm** or **Trigger Immediate** repeats in a loop (re-configure + arm + capture each time) until **Stop** — continuous / auto re-arm behaviour for either normal or immediate trigger.

The capture itself runs on a **`QThread` worker** so the GUI
stays responsive while waiting for the trigger.  When the worker
emits `captureFinished`, the History panel adds a row.  When it
emits `captureFailed`, a non-blocking notification appears at the
bottom of the window.

After **Connect**, the **Advanced** block grays out options the
bitstream does not implement: **decimation** (FEATURES bit 5),
**external trigger** (bit 6), **storage qualification** (bit 4),
and **probe mux sel** when the mux is only one slice wide.  Tooltips
on disabled widgets explain why.  The **ELA identity** dock shows
the same capability flags in prose.

### Capture history panel

Shows a table of every capture from this session, in reverse
chronological order:

| # | Time | Samples | Channel | Trigger | Status |
|---|---|---|---|---|---|
| 3 | 14:22:03 | 25 | 0 | `value=0x42 mask=0xFF` | OK |
| 2 | 14:21:58 | 25 | 0 | `value=0x42 mask=0xFF` | OVERFLOW |
| 1 | 14:21:54 | 25 | 0 | `value=0x42 mask=0xFF` | OK |

Click a row to make it the **active** capture.  Right-side controls:

- **[Open in viewer ▾]** — dropdown of detected viewers (GTKWave,
  Surfer, WaveTrace, Custom command).  Click to spawn the viewer
  on the captured `.vcd`.  See "Waveform viewer integration" below.
- **[Export JSON]** / **[Export CSV]** / **[Export VCD]** — write
  the active capture to a file via the same `Analyzer.write_*`
  helpers used by the CLI.
- **[Quick preview ▾]** — toggle the embedded `pyqtgraph` preview
  pane (see next section).

### Embedded waveform preview (pyqtgraph)

Below the History table is an **embedded waveform preview**
rendered with `pyqtgraph`.  It's a small widget that shows the
captured `result.samples` directly, one row per `ProbeSpec`, with:

- Shared X axis (sample index by default; switches to timestamp
  units when `TIMESTAMP_W > 0`)
- Mouse wheel to zoom horizontally, drag to pan
- Click a sample to see its value in a tooltip
- Trigger position highlighted with a vertical line

This is **not** a full waveform viewer — it's a sanity-check pane.
It exists so you can verify "did the trigger fire on the right
value?" without launching an external tool.  For deep inspection
(search, decode, save layouts) use the **Open in viewer** button
to launch GTKWave or Surfer instead.

The preview reads `lanes_from_capture()` from
[`fcapz.gui.waveform_preview`](../host/fcapz/gui/waveform_preview.py),
which slices each `ProbeSpec` out of the packed sample word
according to its `lsb` and `width`.  Step plotting is used so
adjacent identical values render as a flat line, not a sawtooth.

### EIO panel

**JTAG chain** spin box and **Attach EIO** create an `EioController` on the
current transport and show core identity / bus widths.

For each input bit, **read-only checkboxes** update from
`EioController.read_inputs()` while **Poll inputs** is checked.
A small combo box next to the checkbox sets the poll period (presets
**25–1000 ms**, default **250 ms**).  For each output bit, a **clickable
toggle** calls `EioController.set_bit()` when its state changes.

Uncheck **Poll inputs** or disconnect to stop periodic JTAG reads.

### EJTAG-AXI bridge panel

Three sub-areas:

**Single ops**:

- Address input + **Read** button → `bridge.axi_read()`, value
  shown next to the button
- Address + Data + Wstrb inputs + **Write** button →
  `bridge.axi_write()`

**Block ops**:

- Address + Count inputs + **Dump** button →
  `bridge.read_block()` or `bridge.burst_read()` depending on a
  "burst mode" checkbox; result goes into a scrollable hex table
- Address + Pattern + Count inputs + **Fill** button →
  `bridge.write_block()` / `burst_write()`
- **Load file** button → file picker → reads as little-endian
  32-bit words → `write_block()` / `burst_write()` at the
  configured address

**Status**:

- The cached `fifo_depth` from `connect()` is shown so you can
  see why long bursts get rejected
- AXI errors (`AXIError`) appear as red text below the action
  buttons; the panel does not pop up modal dialogs for them
  because they're often expected in a debug session

### EJTAG-UART terminal panel

A **scrolling text widget** plus an input line:

- The top half is a `QPlainTextEdit` that shows incoming bytes
  decoded as UTF-8 (with replacement characters for invalid
  sequences).  A worker thread polls `uart.recv(count=0,
  timeout=0.1)` continuously and appends new bytes.
- The bottom half is a single-line input + Send button.  Hitting
  Enter sends the line plus a newline via `uart.send()`.
- A **Clear** button wipes the display.
- Status indicators (TX full, RX overflow, frame error, TX free
  bytes) update from `uart.status()` once per second.

For binary data, use the CLI (`fcapz uart-send --hex` /
`--file`) instead of the GUI — the terminal panel is for
human-readable streams.

## Waveform viewer integration

The "Open in viewer" dropdown in the History panel lists every
viewer the GUI detected at startup.  Detection is automatic via
[`viewer_registry.py`](../host/fcapz/gui/viewer_registry.py),
which calls `shutil.which()` for each known viewer.

Built-in viewer classes (in
[`viewers.py`](../host/fcapz/gui/viewers.py)):

| Class | Detects | Launch |
|---|---|---|
| `GtkWaveViewer` | `gtkwave` on PATH | `subprocess.Popen([gtkwave, vcd, "--save", gtkw])` |
| `SurferViewer` | `surfer` on PATH | `subprocess.Popen([surfer, vcd])` |
| `WaveTraceViewer` | `wavetrace` on PATH | `subprocess.Popen([wavetrace, vcd])` |
| `CustomCommandViewer` | user-supplied template like `myviewer --vcd {VCD}` | substitutes `{VCD}` and `{GTKW}` and spawns |

The viewer is spawned as a **separate top-level process** with
`start_new_session=True`, so it lives in its own window and
closing the GUI does not kill it.  See [chapter 15](15_export_formats.md)
"Embedding caveat" for why most external viewers cannot be
embedded inside the Qt window.

**Windows:** When you **minimize** the main `fcapz-gui` window, the GUI also
minimizes the largest top-level window of each **external viewer process it
started** (the same association used when tiling the viewer above the GUI).
When you restore `fcapz-gui` from the taskbar, those viewer windows are
restored too.  On Linux and macOS this coupling is not implemented — the viewer
stays in whatever state you left it.

When you click **Open in viewer (GTKWave)**, the GUI also writes
an **auto-generated `.gtkw` layout file** alongside the VCD.  The
layout file tells GTKWave to:

- Open the VCD
- Show the signals from your `ProbeSpec` list in the order you
  defined them
- Group multi-bit buses
- Set radix to hex for wide buses

This means GTKWave opens with a polished view of your capture
instead of the bare signal tree.  See
[`gtkw_writer.py`](../host/fcapz/gui/gtkw_writer.py) for the
generation logic.

## Settings dialog

**File → Settings...** opens a dialog with three tabs:

1. **Connection** — last-used backend, host, port, FPGA target,
   bitfile path, IR-table preset.  Persists across sessions.
2. **Viewers** — detected viewer paths and their per-viewer
   override paths (in case you have a non-standard install of
   GTKWave).  Default viewer dropdown: which one is selected by
   default in the History panel's "Open in viewer" button.
3. **Probe profiles** — named sets of `ProbeSpec` lists you can
   reuse across sessions.  e.g. "uart-debug" maps to a specific
   probe layout you use a lot.

All settings are stored in TOML at
`~/.config/fpgacapzero/gui.toml` (or `%APPDATA%/fpgacapzero/gui.toml`).
The file is human-editable; the GUI loads it on startup and
re-saves on close.

## Threading model

The GUI uses one **`QThread` worker** per active controller
(Analyzer / EIO / AXI / UART).  Worker threads call the
synchronous controller methods (`analyzer.capture(...)`,
`uart.recv(...)`) and emit Qt signals when they finish:

- `captureFinished(result)` → main thread updates the History
  panel
- `captureFailed(error_message)` → main thread shows a
  non-blocking notification
- `uartRxBytes(data)` → main thread appends to the terminal panel

This means **the GUI stays responsive** during long captures and
slow JTAG round-trips.  No spinning beach ball, no "Application
not responding" — you can browse the capture history, look at
old captures, change panels, all while a capture is in flight.

## Layout customisation

The main window uses Qt's docking layout, so you can:

- Drag a panel out to a separate floating window
- Snap two panels side by side
- Hide panels you don't need (View menu → uncheck)
- Save and restore your layout (View menu → Save layout / Load layout)

Layouts are persisted in `gui.toml` so the next launch reopens
the same arrangement.

## Limitations

- **No sequencer table editor**.  The capture panel exposes the
  simple-trigger fields (mode, value, mask, delay).  For
  multi-stage sequencer configs, edit a JSON file and pass the
  path via the **Trigger sequence file** input.  A graphical
  table editor is on the roadmap but not implemented.
- **No live waveform reload** for external viewers.  When you
  capture again, the GUI opens a new viewer instance — it does
  not push a "reload this VCD" command to an already-open
  GTKWave window.  GTKWave's reload-on-change support is flaky
  enough that we don't try to use it.
- **No embedded GTKWave / Surfer / WaveTrace**.  The embedded
  preview is `pyqtgraph` only.  See [chapter 15](15_export_formats.md)
  for why and what the embedding constraints are for each viewer.
- **One transport at a time**.  The GUI manages one shared
  transport across all panels; you cannot have two simultaneous
  hw_server sessions to two different boards from one GUI
  instance.  Workaround: launch two `fcapz-gui` processes side
  by side.

## Worked example: a debug session

1. Launch `fcapz-gui` from a terminal.
2. In the **Connection** panel, set backend = `hw_server`, port =
   `3121`, target = `xc7a100t`, bitfile =
   `examples/arty_a7/arty_a7_top.bit`, click **Connect**.
3. Wait ~3-5 seconds (FPGA programming + readiness probe).  The
   probe summary panel populates.
4. Click the **ELA capture** tab.
5. Set Pretrigger=8, Posttrigger=16, Trigger mode=value_match,
   Trigger value=`0x42` (radix defaults to hex; you can enter `42` without the prefix),
   Trigger mask=`0xFF`.
6. In the **Probes** subform, add `name=counter, width=8, lsb=0`.
7. Click **Arm** (or use the toolbar).  Watch the spinner; when the
   counter matches `0x42`, the capture appears in the History panel.
   (Use **Trigger Immediate** for a forced trigger without waiting.)
8. Click the row, then click **[Quick preview ▾]** at the bottom
   to see the embedded waveform.  You should see the 8-bit
   counter incrementing past `0x42`.
9. Click **[Open in viewer ▾] → GTKWave**.  GTKWave opens in a
   separate window with the auto-generated `.gtkw` layout — your
   `counter` signal is already added and labelled.
10. Click the **EIO** tab, click **Attach EIO** (chain **3** on the
    Arty reference bitstream). Turn on **Poll inputs** to refresh the
    **Inputs** checkboxes — they mirror `btn[3:0]` and the counter
    nibbles; they do **not** light the board by themselves. Use the
    **Outputs** checkboxes to drive `probe_out`; on Arty, bits **0–3**
    drive the four **green** LEDs (active high). **All outputs on**
    sets every `probe_out` bit in one write (unchecked clears all bits).
    Until **Attach EIO** succeeds, poll controls and the I/O grids stay
    disabled.
11. Click the **EJTAG-AXI** tab, type `0x40000000` into the address
    field, click **Read**.
12. Done.  Disconnect from the Connection panel when you're
    finished.

This whole flow is what the desktop GUI is for: **fast iteration
on a real board without writing a single line of host code**.

## Tests

The GUI has its own test suite using Qt's offscreen platform
(no display required):

| Test | What it covers |
|---|---|
| `tests/test_gui_settings.py` | TOML round-trip, default config path |
| `tests/test_gui_viewers.py` | Each `WaveformViewer` subclass with mocked subprocess |
| `tests/test_gui_viewer_registry.py` | Auto-detect ordering and missing-binary handling |
| `tests/test_gui_capture_panel.py` | `CapturePanel` widget construction + `CaptureConfig` round-trip |
| `tests/test_gui_connection_panel.py` | `ConnectionPanel` field binding to `ConnectionSettings` |
| `tests/test_gui_main_window.py` | `MainWindow` smoke test |
| `tests/test_gui_transport_from_settings.py` | `ConnectionSettings → Transport` factory including `IR_TABLE_US` |
| `tests/test_gtkw_writer.py` | Auto-generated `.gtkw` content matches expected layout |
| `tests/test_waveform_preview.py` | `lanes_from_capture()` slicing for named probes, X-axis selection, step plotting edges |

Run them with:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_*.py tests/test_waveform_preview.py tests/test_gtkw_writer.py
```

The repo's `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`
automatically so you can also just run:

```bash
pytest tests/
```

and the GUI tests run alongside everything else without popping
windows.

## What's next

- [Chapter 13 — Register map](13_register_map.md): the canonical
  register map.
- [Chapter 14 — Transports](14_transports.md): how the GUI's
  IR-table dropdown maps to the named presets.
- [Chapter 15 — Export formats](15_export_formats.md): the
  auto-generated `.gtkw` layout file format.
