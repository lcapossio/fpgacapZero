# 15 — Export formats

> [!NOTE]
> **Goal**: understand every file format `Analyzer` can write, what
> each contains, when to use which, how the auto-generated `.gtkw`
> waveform-viewer layout file works, and the practical embedding
> caveats for the four supported viewers.

## Three formats, one capture

Every `CaptureResult` can be written to three different file
formats via the `Analyzer.write_*` helpers (or via the equivalent
`fcapz capture --format ...` CLI flag):

| Format | Method | Use when |
|---|---|---|
| **JSON** | `analyzer.write_json(result, "out.json")` | Programmatic consumption, LLM context, regression-test golden vectors |
| **CSV** | `analyzer.write_csv(result, "out.csv")` | Spreadsheets, Pandas, ad-hoc analysis |
| **VCD** | `analyzer.write_vcd(result, "out.vcd")` | Waveform viewers (GTKWave, Surfer, WaveTrace, etc.) |

The same `CaptureResult` can be exported to all three — the
`export_*_text()` / `export_json()` helpers return strings/dicts so
you can write to a file, send over a network, or hold in memory.

The full schema for each format is in
[`specs/waveform_schema.md`](specs/waveform_schema.md) — that file
is the canonical reference if a tool you use has trouble parsing
the output.

## JSON

The JSON format is the **richest** of the three.  It records a subset
of the `CaptureConfig` that produced the capture: `sample_clock_hz`,
`sample_width`, `depth`, `pretrigger`, `posttrigger`, `channel`,
`decimation`, `stor_qual_mode`, `ext_trigger_mode`, the simple
`trigger` (`mode`, `value`, `mask`) and the probe map.  It also holds
`overflow`, `segment`, the sample array, and timestamps if present.
It does **not** record the sequencer stages (`sequence`),
`trigger_delay`, `trigger_holdoff`, `stor_qual_value` / `stor_qual_mask`,
`probe_sel`, `startup_arm`, `rle` or `post_clocks`.

```json
{
  "version": "1.0",
  "sample_clock_hz": 100000000,
  "sample_width": 8,
  "depth": 1024,
  "pretrigger": 8,
  "posttrigger": 16,
  "channel": 0,
  "decimation": 0,
  "stor_qual_mode": 0,
  "ext_trigger_mode": 0,
  "trigger": {
    "mode": "value_match",
    "value": 66,
    "mask": 255
  },
  "overflow": false,
  "segment": 0,
  "samples": [
    {"index": 0, "value": 58},
    {"index": 1, "value": 59},
    {"index": 2, "value": 60},
    ...
    {"index": 8, "value": 66},   <-- trigger sample (index = pretrigger)
    ...
  ],
  "timestamps": [
    {"index": 0, "value": 12345600},
    {"index": 1, "value": 12345601},
    ...
  ]
}
```

`samples` is always present.  `timestamps` is present **only** if
the bitstream was built with `TIMESTAMP_W > 0`.  `run_lengths` (same
`{"index", "value"}` form, clocks per entry) is present only for a
[run-length capture](05_ela_core.md#run-length-capture).  `probes` is present
only when the capture had a probe map, and lists `{name, width, lsb}` per lane.

`decimation` and `stor_qual_mode` record how the capture was sampled, which
is what tells a later reader whether consecutive samples are consecutive
cycles.  They are not decoration: the AXI decoder refuses a capture that
stored only some cycles rather than reading gaps as bus behaviour.

### When to use it

- **LLM context**: feed the JSON straight into an LLM with "find
  the anomaly in this capture" or "summarize what happened
  around the trigger".  The structure is regular and the field
  names are self-documenting.
- **Regression tests**: golden-vector tests that compare a fresh
  capture's JSON against a known-good file.  The
  `Analyzer.export_json()` output is deterministic for a given
  capture.
- **Cross-language consumption**: anything that can parse JSON
  (and that's everything) can read the file.

### Reading it back

```python
import json
with open("capture.json") as f:
    data = json.load(f)

print(f"trigger sample: {data['samples'][data['pretrigger']]}")
print(f"sample width:   {data['sample_width']} bits")
print(f"overflow:       {data['overflow']}")
```

There is no `read_json()` helper in `Analyzer` — the JSON is
intended for **export only**, not round-tripping into a fresh
controller.  If you need to re-process a captured file in Python,
read it directly with the `json` module.

## CSV

The CSV format is the **simplest** — one row per sample, two or
three columns.

Without timestamps:

```csv
index,value
0,58
1,59
2,60
...
8,66
...
```

With timestamps (when `TIMESTAMP_W > 0`):

```csv
index,value,timestamp
0,58,12345600
1,59,12345601
...
```

A run-length capture adds a `run_length` column (clocks per entry) after
`timestamp`, or after `value` without timestamps.

### When to use it

- **Spreadsheets**: import directly into Excel, LibreOffice, or
  Google Sheets and chart the captured signal.
- **Pandas / NumPy**: `pd.read_csv("capture.csv")` and you're
  off to the races.
- **Quick visual inspection**: `head capture.csv` or `column -t -s,`
  in a terminal.

### What it does NOT contain

CSV has no header metadata, no trigger config, no
`sample_clock_hz`.  If you need that context, export JSON
alongside or check the original `CaptureConfig`.

## VCD

VCD (Value Change Dump) is the **standard waveform format** for
digital simulation.  Every serious waveform viewer reads it.  The
`Analyzer.write_vcd()` helper produces a fully spec-compliant
VCD with:

- A fixed `$timescale` of `1 ns`, used as a plain tick: the time axis
  counts samples or cycles, not real nanoseconds (see below)
- One `$var wire` declaration per `ProbeSpec` from the
  `CaptureConfig` (or one giant `sample` signal if no probes
  were defined)
- A `$var wire` declaration for the timestamp counter if
  `TIMESTAMP_W > 0`
- One value-change record per stored sample, at the tick described
  below.

The `#` time of each sample is:

- **Without timestamps**: the stored-sample index, `0 .. n-1`.  One
  tick is one stored sample, so with decimation `N` a tick is `N+1`
  sample clocks.  A run-length capture places each entry at its start
  clock instead.
- **With timestamps**: the sample's timestamp minus the first sample's,
  so the dump starts at `#0` and one tick is one sample-clock cycle.  The
  `timestamp` wire still carries the raw counter values.

The viewer labels the axis "ns", but the number is a tick count.  To get
physical time, multiply by the period of one tick: with timestamps (or
without them, when every cycle was stored: no decimation and no storage
qualification) that is `1 / sample_clock_hz`, e.g. tick 150 at 150 MHz is
1 µs.  The rate is not in the VCD; it is in the JSON export's
`sample_clock_hz`.

For segmented captures, `Analyzer.export_vcd_text_segments(results)` emits all
segments in **one** VCD: the same signals and `logic` scope, segments
concatenated on the time axis (they are separate trigger windows with no shared
timebase), plus a `segment` wire marking which window each sample came from.
This is what the RPC `capture` command returns for `include_vcd` when
`segments: true`.

### Example output

For a capture with `--probes addr:4:0,data:4:4` (two named lanes
inside an 8-bit sample):

```vcd
$date
  generated by fcapz
$end
$version
  fcapz-mvp
$end
$timescale
  1 ns
$end
$scope module logic $end
$var wire 4 a addr $end
$var wire 4 b data $end
$upscope $end
$enddefinitions $end
$dumpvars
b0000 a
b0000 b
$end
#0
b0000 a
b0001 b
#1
b0001 a
b0001 b
...
```

The single-letter `var_id` codes (`a`, `b`, ...) are how VCD
references signals; the viewer ignores them and just shows the
human names (`addr`, `data`).

### Why named probes matter

Without `--probes`, you get one giant `sample` signal:

```bash
fcapz capture --pretrigger 8 --posttrigger 16 \
    --trigger-value 0x42 \
    --format vcd --out unnamed.vcd
# → one signal called "sample" with the full sample word
```

In GTKWave you see one row, all 8 bits packed into a single
hex/binary blob.  Workable but ugly.

With `--probes lo:4:0,hi:4:4`:

```bash
fcapz capture --pretrigger 8 --posttrigger 16 \
    --trigger-value 0x42 \
    --probes lo:4:0,hi:4:4 \
    --format vcd --out named.vcd
# → two signals "lo" and "hi"
```

In GTKWave you see two rows with meaningful names.  Much
nicer.

### Auto-generated `.gtkw` layout file (GUI only)

The desktop GUI's "Open in viewer (GTKWave)" button writes a
**`.gtkw` layout file** alongside the `.vcd` so GTKWave opens with
the signals already added to the waveform pane, in the order you
defined them in your `ProbeSpec` list, with sensible radixes (hex
for wide buses, binary for 1-bit signals).

The generator is at
[`host/fcapz/gui/gtkw_writer.py`](../host/fcapz/gui/gtkw_writer.py)
— ~75 lines.  It's invoked automatically when you click "Open in
viewer (GTKWave)" but you can also use it from your own scripts:

```python
from pathlib import Path
from fcapz.gui.gtkw_writer import write_gtkw_for_capture
write_gtkw_for_capture(result, vcd_path=Path("cap.vcd"), gtkw_path=Path("cap.gtkw"))
```

The paths must be `Path` objects; plain strings raise `AttributeError`.

GTKWave then opens with the layout pre-loaded:

```bash
gtkwave cap.vcd --save cap.gtkw
```

Surfer gets the same treatment: "Open in viewer (Surfer)" writes a
Surfer command file
([`host/fcapz/gui/surfer_command_writer.py`](../host/fcapz/gui/surfer_command_writer.py),
`write_surfer_command_file_for_capture(result, Path(...))`) that adds the
signals and places a marker on the trigger sample, and launches
`surfer --command-file <file> <vcd>`.  When the GUI reuses a running Surfer
for repeated captures, it reloads the new wave through Surfer's WCP
connection where available.

## Waveform viewer integration

The GUI's "Open in viewer" dropdown launches one of four built-in
viewer wrappers.  All four spawn the viewer as a **separate
top-level process** in a new window — see "Embedding caveat"
below.

### Built-in viewer classes

| Class | Detects | Launch | Layout file |
|---|---|---|---|
| `GtkWaveViewer` | `gtkwave` on PATH | `subprocess.Popen([gtkwave, vcd, "--save", gtkw])` | yes (`.gtkw`) |
| `SurferViewer` | `surfer` on PATH | `subprocess.Popen([surfer, "--command-file", cmd, vcd])` | yes (Surfer command file with trigger marker) |
| `WaveTraceViewer` | `wavetrace` on PATH | `subprocess.Popen([wavetrace, vcd])` | no |
| `CustomCommandViewer` | n/a | substitute `{VCD}` and `{SAVE}` in user argv template, spawn | depends on user template |

The custom command variant is the escape hatch for anything not
covered by the built-ins.  It is an argv list, one element per argument:

```toml
# in ~/.config/fpgacapzero/gui.toml (Windows: %APPDATA%\fpgacapzero\gui.toml)
[viewers]
custom_argv = ["myviewer", "--vcd", "{VCD}"]
```

Then "Open in viewer (Custom command)" appears in the GUI
dropdown alongside the auto-detected ones.

### Auto-detection

At GUI startup, [`viewer_registry.py`](../host/fcapz/gui/viewer_registry.py)
calls each `WaveformViewer` subclass's `detect_executable()`
classmethod (which uses `shutil.which()`) and lists only the
ones it finds (or that have a path override).  Missing viewers are
left out of the dropdown.

You can override the auto-detected path in **Settings →
Viewers** if your install lives somewhere unusual:

```toml
[viewers]
gtkwave_executable = "/opt/gtkwave/bin/gtkwave"
# also: surfer_executable, wavetrace_executable
```

### Embedding caveat

**The external waveform viewers are NOT embedded inside the
fcapz-gui window.**  This is a property of how those viewers are
built, not a fcapz design choice:

| Viewer | Toolkit | Embeddable in Qt? |
|---|---|---|
| GTKWave | GTK | **No** — separate process, no embedding API |
| Surfer (desktop) | wgpu/egui Rust | **No** — no embedding API |
| Surfer (web build, WASM) | WebAssembly in a browser | **Yes**, via `QtWebEngineWidgets` (planned, optional `[gui-surfer-web]` extra, not yet shipped) |
| WaveTrace | VS Code extension or Electron | **No** — opens in user's VS Code or its standalone window |
| Vivado XSim wave viewer | Tcl/Tk | **No** — spawns Vivado |
| Custom command | whatever | usually no |
| **Embedded `pyqtgraph` preview** | **native Qt** | **Yes** — lives inside the History panel |

The **only** waveform widget actually embedded inside fcapz-gui
today is the `pyqtgraph` quick-preview pane (see
[chapter 12](12_gui.md)).  External viewers are launched as
separate top-level windows; the user arranges them side-by-side
with fcapz-gui (snap left + snap right is the typical pattern).

This isn't a workaround: it keeps heavyweight viewers in their own
processes while the `pyqtgraph` preview covers the "instant feedback
inside the same window" case for most debug sessions. External viewers
handle the cases where you need search, decode, save layouts, scripted
analysis, or a viewer-specific workflow.

## Worked example: capture → JSON → LLM summary

```python
from fcapz import (
    XilinxHwServerTransport, Analyzer,
    CaptureConfig, TriggerConfig, ProbeSpec,
    summarize, ProbeDefinition,
)
import json

# Configure + capture
t = XilinxHwServerTransport(port=3121, fpga_name="xc7a100t",
                            bitfile="examples/arty_a7/arty_a7_vex_top.bit")
a = Analyzer(t)
a.connect()

cfg = CaptureConfig(
    pretrigger=8, posttrigger=16,
    trigger=TriggerConfig(mode="value_match", value=0x42, mask=0xFF),
    sample_width=8, depth=1024,
    sample_clock_hz=150_000_000,   # reference ELA0 samples at 150 MHz
    probes=[ProbeSpec(name="counter", width=8, lsb=0)],
)
a.configure(cfg); a.arm()
result = a.capture(timeout=5.0)

# Export to all three formats
a.write_json(result, "cap.json")
a.write_csv(result, "cap.csv")
a.write_vcd(result, "cap.vcd")

# Plus an LLM-friendly structured summary
summary = summarize(result, [ProbeDefinition("counter", 8, 0)])
with open("cap_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

a.close()
```

`cap.json` is the raw export.  `cap_summary.json` is the
LLM-friendly structured summary that flattens the capture into
"how many edges, how many bursts, longest burst, first/last edge"
fields — much shorter than the raw sample list and much more
useful as LLM context.  See [chapter 09](09_python_api.md) "the
events module".

## Worked example: VCD → GTKWave with named probes

```bash
fcapz capture \
    --pretrigger 8 --posttrigger 16 \
    --trigger-value 0x42 --trigger-mask 0xFF \
    --probes counter:8:0 \
    --format vcd \
    --out cap.vcd

gtkwave cap.vcd
```

Then in GTKWave, double-click `counter` in the SST tree to add
it to the waveform pane.  Right-click → "Data Format" → "Hex" if
you want hex display.

If you launch via the desktop GUI ("Open in viewer (GTKWave)"
button), the auto-generated `.gtkw` layout takes care of the
add-and-format step automatically.

## Worked example: CSV into pandas

```python
import pandas as pd

df = pd.read_csv("cap.csv")
print(df.describe())
print(f"trigger sample: {df.iloc[8]}")     # pretrigger=8
df.plot(x="index", y="value")
```

CSV is the path of least friction for ad-hoc analysis.

## Format comparison

| Question | JSON | CSV | VCD |
|---|---|---|---|
| Includes trigger config? | ✅ (simple trigger only) | ❌ | ❌ |
| Includes timestamps? | ✅ if `TIMESTAMP_W>0` | ✅ if `TIMESTAMP_W>0` | ✅ if `TIMESTAMP_W>0` (`timestamp` wire; ticks follow it) |
| Named probes? | ✅ | ❌ | ✅ if `--probes` set |
| Round-trippable into Python? | as a dict | as a DataFrame | as text only |
| Suitable for waveform viewer? | ❌ | ❌ | ✅ |
| Suitable for spreadsheet? | awkward | ✅ | ❌ |
| Suitable for LLM context? | ✅ | ✅ (smaller) | ❌ (too verbose) |
| File size (25 samples) | ~1 KB | ~150 B | ~1 KB |
| File size (1024 samples) | ~30 KB | ~6 KB | ~25 KB |

## What's next

- [Chapter 16 — Versioning](16_versioning_and_release.md): the
  `version` field in the JSON header and how it relates to the
  per-core identity magic
- [Chapter 17 — Troubleshooting](17_troubleshooting.md): VCD
  doesn't open / waveform looks wrong / GTKWave can't find the
  layout file
- [`specs/waveform_schema.md`](specs/waveform_schema.md): the
  canonical format spec
