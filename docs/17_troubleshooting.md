# 17 — Troubleshooting

> **Goal**: a single page you can grep when something breaks.  Each
> entry is **symptom → cause → fix**, ordered roughly by how often
> we've seen it in practice.
>
> **Audience**: you, at 2 a.m., with a board that won't talk.

## Connection / identity

### `RuntimeError: ELA core identity check failed at VERSION[15:0]: expected 0x4C41 ('LA'), got 0x0000`

**Cause**: the FPGA isn't programmed, the wrong bitstream is
loaded, or the JTAG chain selected the wrong device.

**Fix**:
1. Confirm the transport sees the board: `xsdb -eval "connect; targets"`
   for `hw_server`, or `jtagconfig` / `fcapz --backend usb_blaster --tap auto
   probe` for Quartus USB-Blaster.
2. Pass `bitfile=` to the transport so `connect()` programs it for you.
3. Check `fpga_name` matches the actual part (`xc7a100t` vs `xc7a35t`).
4. If you have multiple devices on the chain, use a more specific
   `fpga_name` filter.

See [chapter 16](16_versioning_and_release.md) for why this magic
check exists.

### Quartus USB-Blaster: `ERROR: The specified device is not found`

**Cause**: Quartus found the cable but the device name passed to
`open_device` did not match any device on that cable.  This often
happens if a saved GUI/CLI config still contains a Xilinx target name
such as `xc7a100t`.

**Fix**:
- Use `--tap auto` / GUI target `auto` for the common single-FPGA chain.
- Run `jtagconfig` to see the Quartus hardware and device names.
- If your FPGA is not the first `@1` device, pass the exact Quartus
  device name with `--tap`.
- If Quartus is not on PATH, set the GUI **quartus_stp** field or pass
  `--quartus-stp C:/altera_pro/26.1/quartus/bin64/quartus_stp.exe`.

### `RuntimeError: EIO core identity check failed ... expected 0x494F ('IO')`

Same root cause as the ELA case — wrong bitstream or unprogrammed
FPGA.  Same fixes.

### `ConnectionError: FPGA did not become ready within 2.0s after program()`

**Cause**: bitstream loaded but the readiness probe register reads
zero.  Either the bitstream silently failed, the wrong target was
bound, or your design doesn't have an ELA at `ready_probe_addr=0x0000`.

**Fix**:
- Re-check `fpga_name` — Vivado may have bound a different device
  on the chain.
- If your design genuinely has no ELA, pass `ready_probe_addr=None`
  to disable the wait.
- Bump `ready_probe_timeout` if you're on a slow USB hub.

### `ValueError: bitfile path contains unsafe characters for TCL`

**Cause**: TCL injection guard tripped.  Your `bitfile=` or
`fpga_name=` contains `"`, `;`, `{`, `}`, `[`, `]`, or another
metacharacter.

**Fix**: rename the file/path.  Don't disable the regex — it
exists because xsdb will happily execute arbitrary TCL otherwise.
See [chapter 14](14_transports.md) "TCL injection prevention".

### xsdb error: `no bit string in output` / empty stdout

**Cause**: xsdb died mid-command, or the parser saw a frame with
no hex payload.  Often **hw_server lost the cable**, but the same
symptom appeared when **two threads talked to one xsdb session at
once** (e.g. EIO **Poll inputs** on a `QTimer` while the ELA capture
worker runs).  The host stack now serializes XSDB and OpenOCD socket
I/O with a lock so those paths cannot interleave.

**Fix**: unplug/replug the JTAG USB cable, restart `hw_server`,
retry.  Recent commits include captured xsdb stderr in the
parser error message — read it for the real reason.  If you still
see empty stdout on an older build, turn off EIO polling while
capturing.

## Build / RTL

### `DEPTH must be a power of 2`

**Cause**: the ELA wrapper enforces power-of-2 depths because the
address counter wraps with a mask.  You passed `DEPTH=1000`.

**Fix**: round to `1024`.

### `NUM_SEGMENTS must divide DEPTH evenly`

**Cause**: segmented memory splits `DEPTH` into equal slices.

**Fix**: pick `NUM_SEGMENTS ∈ {1, 2, 4, 8, ...}` such that
`DEPTH % NUM_SEGMENTS == 0`.

### Vivado orphan `xelab` / `xsim` processes after a failed build

**Cause**: `examples/arty_a7/build.py` was killed mid-run and left
Vivado children orphaned.

**Fix**: kill them by name (`taskkill /im xelab.exe /f` on Windows,
`pkill -f xelab` on Linux), then re-run `build.py`.  The build
launcher waits for `hw_server` reachability before declaring the
FPGA ready, so orphans can't poison the next run once cleared.

### `python tools/sync_version.py --check` fails in CI

**Cause**: you bumped `VERSION` but didn't regenerate the header.

**Fix**: `python tools/sync_version.py` (no `--check`), commit
the regenerated `rtl/fcapz_version.vh`.  See
[chapter 16](16_versioning_and_release.md).

## EJTAG-AXI bridge

### `Bad EJTAG-AXI VERSION[15:0]: 0x0000` on Arty / `hw_server` even though USER4 is present

**Cause**: on the Arty A7 reference setup, isolated USER4 raw scans
through `xsdb` / `hw_server` were observed to return all-zero TDO.
The bridge itself was fine; the same USER4 traffic worked when the
host kept it inside one batched raw-scan sequence.

**Fix**:
- Use a recent host build where `EjtagAxiController` batches USER4
  scan sequences internally.
- If you are debugging at the transport layer, prefer
  `raw_dr_scan_batch()` over standalone `raw_dr_scan()` for USER4
  traffic on this setup.
- If you still see this after updating, confirm the bitstream really
  contains the USER4 bridge and that the chain number matches the RTL
  wrapper (`CHAIN=4` on the Arty reference top).

### `ValueError: burst length 32 exceeds FIFO_DEPTH-1=15`

**Cause**: the bridge was synthesized with `FIFO_DEPTH=16`, so the
hardware can only accept AXI4 `awlen` up to 15 (16 beats).  You
asked for 32.

**Fix**: split the transfer into chunks ≤ `FIFO_DEPTH-1`, or
re-synthesize the bridge with a deeper FIFO.  The host's
`burst_read()` / `burst_write()` will chunk for you if you call
the high-level helper.  See [chapter 07](07_ejtag_axi_bridge.md).

### AXI reads return `0xDEADBEEF` or all-ones

**Cause**: the AXI slave returned an error response (`SLVERR` /
`DECERR`).  The bridge surfaces this in the status bits of the
72-bit DR; the controller raises it as a `RuntimeError` with the
response code.

**Fix**: check your address is mapped, the slave is out of reset,
and the burst doesn't cross a 4 KB boundary.

## EJTAG-UART bridge

### Loopback test drops bytes at 115200 baud

**Cause**: **BUG-002** — known issue.  Internal loopback at high
baud rates drops bytes due to a CDC settling window.  Documented
in [chapter 08](08_ejtag_uart_bridge.md).

**Workaround**: drop to 9600 baud for loopback verification, or
use external loopback (TX→RX wire) which is unaffected.

## Capture / runtime

### `Analyzer.capture()` raises `TimeoutError`

**Cause**: the trigger condition never fired.  The core is still
armed, waiting.

**Fix**:
- Check your `trigger_value` and `trigger_mask` actually match
  your data.
- Try `mode="value_match"` with `mask=0` (matches everything) to
  prove the capture path works end-to-end.
- Bump the `timeout=` argument if your trigger is genuinely rare.

### Capture returns all zeros

**Cause**: usually means the channel mux is pointing at an
unconnected probe input, or the source signal is genuinely zero.

**Fix**:
- Verify `channel=` in `CaptureConfig` matches a connected
  `probe_in_*` port on the wrapper.
- Free-run with `mask=0` and look at the values — if still zero,
  the RTL upstream is the problem, not fcapz.

### Capture returns sensible data but the trigger sample is wrong index

**Cause**: you read `samples[0]` expecting the trigger.  The
trigger sample is at `samples[pretrigger]`.

**Fix**: `result.samples[result.config.pretrigger]`.

## GUI

### `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`

**Cause**: headless host, no display.

**Fix**: `export QT_QPA_PLATFORM=offscreen` for tests, or run with
a real display / X forwarding for interactive use.  See
[chapter 12](12_gui.md).

### "Open in viewer (GTKWave)" is grayed out

**Cause**: `gtkwave` not on `PATH`.

**Fix**: install GTKWave, or set the path explicitly in
**Settings → Viewers**.

## Install

### `fcapz.__version__ == "0+unknown"`

**Cause**: both the `importlib.metadata` lookup and the
direct-`VERSION`-file fallback failed.  Usually because you're
running from a fresh clone with no `pip install -e .` and the
`VERSION` file isn't reachable from `_version.py`.

**Fix**: `pip install -e .` from the repo root.

### `ModuleNotFoundError: No module named 'fcapz'` after `pip install -e .`

**Cause**: stale `*.egg-info` from a previous install with the
old `host.fcapz` package layout.

**Fix**:
```bash
find . -name "*.egg-info" -exec rm -rf {} +
pip install -e .
```

## When all else fails

1. Re-read the relevant chapter — the error message usually quotes
   a specific term that maps to a section heading.
2. Run the unit tests: `pytest tests/` — if those fail, the issue
   is in the host stack, not your setup.
3. Run the RTL testbenches: `python sim/run_sim.py` — if those
   fail, the issue is in the RTL, not the host stack.
4. File an issue at
   https://github.com/lcapossio/fpgacapZero/issues with: the exact
   error, your `fcapz.__version__`, your board, and the bitstream
   commit hash if you built it yourself.

## What's next

You're at the end of the manual.  From here:

- [`../CHANGELOG.md`](../CHANGELOG.md) — release history
- [`specs/register_map.md`](specs/register_map.md) — bit-level
  reference for every core
