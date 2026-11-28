# Waveform Schema

The export formats written by `Analyzer.export_json()` / `write_json()`,
`export_csv_text()` / `write_csv()` and `export_vcd_text()` / `write_vcd()`
(and by `fcapz capture --format json|csv|vcd`). The JSON `version` field is
the schema identifier, `"1.0"`; it is not the package version.

## JSON Export (LLM-Friendly)
```json
{
  "version": "1.0",
  "sample_clock_hz": 100000000,
  "sample_width": 8,
  "depth": 1024,
  "pretrigger": 8,
  "posttrigger": 24,
  "channel": 0,
  "decimation": 0,
  "stor_qual_mode": 0,
  "ext_trigger_mode": 0,
  "trigger": {
    "mode": "value_match",
    "value": 100,
    "mask": 255
  },
  "overflow": false,
  "segment": 0,
  "samples": [
    {"index": 0, "value": 92},
    {"index": 1, "value": 93},
    {"index": 2, "value": 94}
  ]
}
```

### Fields
| Field | Type | Present | Description |
|-------|------|---------|-------------|
| `version` | string | always | Schema version (`"1.0"`) |
| `sample_clock_hz` | int | always | Sample clock frequency from `CaptureConfig`, for time derivation |
| `sample_width` | int | always | Bits per sample |
| `depth` | int | always | Hardware buffer depth |
| `pretrigger` | int | always | Configured pre-trigger sample (entry) count |
| `posttrigger` | int | always | Configured post-trigger sample (entry) count |
| `channel` | int | always | Configured channel (`CaptureConfig.channel`; 0 on single-channel cores). On a `PROBE_MUX_W > 0` core the `PROBE_SEL` slice is captured instead |
| `decimation` | int | always | Decimation ratio (0 = every sample clock) |
| `stor_qual_mode` | int | always | Storage qualification mode (0 = off) |
| `ext_trigger_mode` | int | always | External trigger mode (0 = disabled, 1 = OR, 2 = AND) |
| `trigger` | object | always | Simple trigger configuration (`mode`: `value_match`, `edge_detect` or `both`; `value`; `mask`). Sequencer stages are not recorded. |
| `overflow` | bool | always | True if the hardware overflow flag was set |
| `segment` | int | always | Segment index given to `capture_segment()` or read by `stream_segments`. Plain `capture()` reports 0, though it reads whichever segment `SEG_SEL` selects |
| `samples` | array | always | Captured samples (entries) as `{index, value}` objects |
| `probes` | array | when the capture had a probe map | `{name, width, lsb}` per named lane |
| `timestamps` | array | `TIMESTAMP_W > 0` | `{index, value}`: raw hardware timestamp of each sample |
| `run_lengths` | array | run-length capture | `{index, value}`: sample clocks each entry held |
| `stream` | object | continuous capture | `{seq, after_gap, lost}` for this window (`Analyzer.stream_segments`) |

`decimation` and `stor_qual_mode` tell a reader whether consecutive samples
are consecutive sample clocks; see
[chapter 15](../15_export_formats.md#json).

### Note on sample ordering
The `samples` array is in readout order: **oldest first**, as read from the
capture window starting at the capture's start pointer. For a normal
triggered window the trigger sample is at `samples[pretrigger]`: the
`pretrigger` samples before it are the history before the event, and the
`posttrigger` samples after it follow the trigger. With a trigger delay the
sample at `samples[pretrigger]` is the delayed (committed) trigger sample.

Other captures keep the oldest-first order but differ in what the indices
mean:

- **Run-length captures:** `samples` holds entries, and `pretrigger` /
  `posttrigger` count entries, so the trigger entry is at index `pretrigger`;
  time comes from `run_lengths` (and `timestamps`, if present).
- **Segmented captures:** each segment is its own window, exported with its
  `segment` number.
- **Continuous raw blocks** (`STREAM_CTRL` bit 1): every stored sample is a
  trigger and `pretrigger` is 0, so each window is consecutive stored samples.

There is no separate `trigger_index` field.

## CSV Export
```
index,value
0,92
1,93
2,94
```
One header row followed by one row per sample. A `timestamp` column follows
`value` when the capture has timestamps, and a `run_length` column comes last
on a run-length capture, so the widest form is
`index,value,timestamp,run_length`. `index` is the sample (entry) index, as in
JSON; the CSV carries no metadata.

## VCD Export
- Fixed `$timescale` of `1 ns`, used as a plain tick: the `#` time is not
  derived from `sample_clock_hz`.
- One `$var wire` per probe of the probe map, or a single signal `sample` of
  width `SAMPLE_W` bits when there is none; plus a `timestamp` wire carrying
  the raw hardware timestamps when the capture has them.
- `#` time of each sample: with timestamps, the timestamp minus the first
  sample's, forced to increase by at least one per sample so the file stays
  valid; without timestamps, each entry's start clock on a run-length capture
  (the dump then closes where the last run ends), else the sample index
  (`0 .. n-1`).
- `Analyzer.export_vcd_text_segments()` concatenates several segments on the
  time axis and adds a `segment` wire.
- Compatible with GTKWave, Surfer, and other VCD viewers.

See [chapter 15](../15_export_formats.md#vcd) for how to convert ticks to
physical time.
