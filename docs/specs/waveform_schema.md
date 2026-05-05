# Waveform Schema — v0.4.0

## JSON Export (LLM-Friendly)
```json
{
  "version": "1.0",
  "sample_clock_hz": 100000000,
  "sample_width": 8,
  "depth": 1024,
  "pretrigger": 8,
  "posttrigger": 24,
  "trigger": {
    "mode": "value_match",
    "value": 100,
    "mask": 255
  },
  "overflow": false,
  "samples": [
    {"index": 0, "value": 92},
    {"index": 1, "value": 93},
    {"index": 2, "value": 94}
  ]
}
```

### Fields
| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Schema version (`"1.0"`) |
| `sample_clock_hz` | int | Sample clock frequency for time derivation |
| `sample_width` | int | Bits per sample |
| `depth` | int | Hardware buffer depth |
| `pretrigger` | int | Configured pre-trigger sample count |
| `posttrigger` | int | Configured post-trigger sample count |
| `trigger` | object | Trigger configuration (mode, value, mask) |
| `overflow` | bool | True if hardware overflow flag was set |
| `samples` | array | Captured samples as `{index, value}` objects |

### Note on sample ordering
The `samples` array is read sequentially from the hardware data window
(`0x0100+`).  The first sample is the trigger point; pretrigger samples
follow, then posttrigger samples.  A future version may add a
`trigger_index` field for explicit unwrapping.

## CSV Export
```
index,value
0,92
1,93
2,94
```
One header row followed by one row per sample.

## VCD Export
- Timescale derived from `sample_clock_hz` (e.g. `10 ns` for 100 MHz).
- Single signal `sample` of width `SAMPLE_W` bits.
- Sample index used as VCD timestamp.
- Compatible with GTKWave, Surfer, and other VCD viewers.
