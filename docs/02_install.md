# 02 — Installation

> **Goal**: by the end of this chapter you will have the `fcapz`
> command-line tool on your `PATH`, the Python package importable as
> `import fcapz`, and a working JTAG transport (Vivado hw_server,
> OpenOCD, or Quartus USB-Blaster) ready to talk to a real board.

## Prerequisites

- **Python 3.10 or later.** Check with `python --version`.  Earlier
  versions will not work — fcapz uses `dataclass | None` syntax,
  `tomllib`, and `importlib.metadata`'s `PackageNotFoundError` shape
  that all require ≥3.10.
- **Git** to clone the repository.
- **A JTAG transport**, one of:
  - **Vivado / hw_server (2022.2 or later)** — required for the
    Xilinx hw_server backend.  This is the path that has been
    hardware-validated on Arty A7-100T.  If you already have Vivado
    installed for your day job, you have hw_server.
  - **OpenOCD with FTDI support** — cross-platform, vendor-neutral.
    Install from your distro package manager (Linux), Homebrew
    (macOS), or [openocd.org](https://openocd.org/) (Windows).
  - **Quartus Prime with `quartus_stp`** — required for Intel/Altera
    USB-Blaster access through `sld_virtual_jtag`.  See
    [`specs/transport_api.md`](specs/transport_api.md) for the
    hardware-validated Quartus edition.
- **Optional**: `iverilog` if you want to run the RTL simulation
  testbenches locally.  Install from your distro or
  [iverilog.icarus.com](http://iverilog.icarus.com/).
- **Optional**: a waveform viewer for the captured `.vcd` files —
  GTKWave (universal default), Surfer, WaveTrace, or whatever else
  you prefer.  See [chapter 15](15_export_formats.md).

## Step 1: clone the repo

```bash
git clone https://github.com/lcapossio/fpgacapZero.git
cd fpgacapZero
```

You can build / install / run from any other directory once you
have the repo on disk; the entry-point script and the Python package
are not tied to the repo location.

## Step 2: install the Python package (headless)

```bash
pip install -e .
```

This is an **editable install**: pip puts the package on your
`sys.path` and any edit you make under `host/fcapz/` is picked up
immediately, no reinstall needed.  Editable installs are the
recommended path for both development and day-to-day use because
fpgacapZero is small and you may want to read the source.

After install, three things are available:

```bash
$ fcapz --help                          # CLI tool on your PATH
$ python -c "import fcapz; print(fcapz.__version__)"
0.4.0
$ python -m fcapz.cli --help            # equivalent to `fcapz`
```

The `fcapz` console script is created by `pyproject.toml`'s
`[project.scripts]` entry; if it is not on your `PATH` after install,
add `$(python -m site --user-base)/bin` (Linux/macOS) or
`%APPDATA%\Python\Python310\Scripts` (Windows) to your `PATH` and try
again.

### Step 2a: install the dev extras (optional, recommended)

```bash
pip install -e ".[dev]"
```

This adds **`pytest`** and **`ruff`**, which you need to run the
test suite and lint the codebase.  No reason not to install them on
a development machine.

### Step 2b: install the GUI (optional)

```bash
pip install -e ".[gui]"
```

This adds **`PySide6`** and **`pyqtgraph`** and registers a second
console script:

```bash
$ fcapz-gui                             # launches the desktop GUI
```

The GUI is fully optional — the headless install above does not
require any Qt dependency, which keeps your CI runners and
headless servers slim.  See [chapter 12](12_gui.md) for the GUI
walkthrough.

## Step 3: install a JTAG transport

You need exactly one of the transports below.  If you have a
Xilinx board and Vivado already installed, the hw_server path is the
fast lane.  If you are on any other vendor or you do not want to
install Vivado, use OpenOCD or Quartus USB-Blaster depending on the
board and RTL wrapper.

### Option A: Xilinx hw_server (recommended for Xilinx boards)

`hw_server` ships with Vivado.  It is a small daemon that listens on
TCP port 3121 and gives the host stack a programmatic interface to
the JTAG cable.  fpgacapZero drives it via `xsdb`, the Xilinx system
debugger console.

1. **Make sure `vivado`, `xsdb`, and `hw_server` are on your PATH.**
   On Linux you typically `source /tools/Xilinx/Vivado/2025.2/settings64.sh`;
   on Windows the Vivado start-menu shortcut sets up the environment
   for you.

2. **Start `hw_server` in the background**:
   ```bash
   hw_server -d                         # -d = detach (daemonize)
   ```
   It listens on `tcp:127.0.0.1:3121` by default.  Confirm with:
   ```bash
   python -c "
   import socket
   s = socket.socket()
   s.settimeout(2)
   s.connect(('127.0.0.1', 3121))
   print('hw_server reachable')
   s.close()
   "
   ```

3. **Connect your board** via USB-JTAG (Arty A7 has an onboard
   FT2232H).  Vivado's `hw_manager` should see it; if not, neither
   will `fcapz`.

4. **Smoke test** without programming anything:
   ```bash
   fcapz --backend hw_server --port 3121 \
         --tap xc7a100t \
         probe
   ```
   You will get an error from the readiness wait if the FPGA isn't
   programmed yet — that's expected and *correct*.  See step 4
   below.

### Option B: OpenOCD (vendor-neutral)

OpenOCD talks directly to your USB-JTAG cable via libusb / libftdi
and exposes a TCL listener on TCP port 6666 (by default).
fpgacapZero connects to that listener and issues raw `irscan` /
`drscan` commands.

1. **Install OpenOCD** with FTDI support.  Confirm with
   `openocd --version` — you want at least 0.11.

2. **Start OpenOCD** with a board config:
   ```bash
   openocd -f examples/arty_a7/arty_a7.cfg &
   ```
   The reference config in the repo targets the Arty A7 onboard
   FT2232H.  For other boards, swap in the appropriate `.cfg` file
   from OpenOCD's `tcl/board/` or `tcl/interface/` directories.

3. **Smoke test**:
   ```bash
   fcapz --backend openocd --port 6666 --tap xc7a100t.tap probe
   ```

OpenOCD is slower than hw_server (no batched scan support) and has
not been as thoroughly hardware-validated, but it is still useful on
non-Xilinx boards with an OpenOCD-supported cable.  See
[`../CONTRIBUTING.md`](../CONTRIBUTING.md)
for the OpenOCD validation gaps if you want to help close them.

### Option C: Quartus USB-Blaster (Intel / Altera)

Quartus Prime ships `quartus_stp`, which fpgacapZero uses to access
Intel `sld_virtual_jtag` instances through a USB-Blaster cable.

1. **Make sure `quartus_stp` is on your PATH**, or remember the full
   path for `--quartus-stp` / the GUI field.  On Windows with Quartus
   Pro 26.1 this is typically:
   ```text
   C:\altera_pro\26.1\quartus\bin64\quartus_stp.exe
   ```

2. **Confirm Quartus sees the board**:
   ```bash
   jtagconfig
   ```
   A DE25-Nano should look similar to:
   ```text
   1) DE25-Nano [USB-1]
     4362C0DD   A5E(A013BB23B|B013BB23BCS)/..
   ```

3. **Smoke test an already-programmed fpgacapZero Intel bitstream**:
   ```bash
   fcapz --backend usb_blaster --tap auto probe
   ```
   If `quartus_stp` is not on PATH, pass it explicitly:
   ```bash
   fcapz --backend usb_blaster --tap auto \
         --quartus-stp C:/altera_pro/26.1/quartus/bin64/quartus_stp.exe \
         probe
   ```

`--tap auto` opens the first Quartus device whose name starts with
`@1`.  If your FPGA is elsewhere in the JTAG chain, pass the exact
Quartus device name with `--tap`.

## Step 4: get a fpgacapZero bitstream onto an FPGA

The `fcapz probe` smoke test from step 3 will fail unless an FPGA
on the JTAG chain is loaded with a bitstream that contains at least
one fpgacapZero core (otherwise the host's identity check sees garbage
and raises `RuntimeError: ELA core identity check failed`).

The fastest path:

```bash
# 1. Build the reference bitstream (Vivado required, ~10-15 min)
python examples/arty_a7/build.py

# 2. Program + probe in one shot (--program flag)
fcapz --backend hw_server --port 3121 \
      --tap xc7a100t \
      --program examples/arty_a7/arty_a7_top.bit \
      probe
```

Expected output (the exact `version_minor` will match
[`../VERSION`](../VERSION)):

```json
{
  "version_major": 0,
  "version_minor": 3,
  "core_id": 19521,
  "sample_width": 8,
  "depth": 1024,
  "num_channels": 1,
  ...
}
```

`core_id = 19521 = 0x4C41 = ASCII "LA"` — that's the ELA core
saying "I am alive and I am the right core".  See
[chapter 16](16_versioning_and_release.md) for the magic register
encoding.

## Step 5: run the test suite (optional but recommended)

```bash
pytest tests/                          # 218 unit tests, ~3 seconds
python sim/run_sim.py                  # RTL lint + simulation matrix
python sim/run_sim.py --lint-only      # RTL lint only
python tools/sync_version.py --check   # version-sync regression guard
ruff check .                           # lint
```

If these pass, your install is healthy.  The unit tests do not
need any hardware or transport — they exercise the controllers
against fake transports.  The sim suite needs `iverilog` and runs
`iverilog -Wall` before the testbenches, matching the CI RTL lint
job. The default simulation run also includes an ELA configuration
matrix that checks small/scalable builds such as `DUAL_COMPARE=0`,
`USER1_DATA_EN=0`, disabled feature registers, and `REL_COMPARE=1`
with `INPUT_PIPE=1`.

For the **hardware integration tests** (which need a real board, a
running `hw_server`, and a programmed bitstream):

```bash
pytest examples/arty_a7/test_hw_integration.py
```

Currently this is `54` collected items on the checked-in Arty reference
suite: `47` passing tests and `7` optional UART tests skipped unless
their separate UART loopback bitstream is enabled, plus `13` subtests.
Wall-clock time is about 4-5 minutes on Arty A7-100T.  See
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) for environment variables
that gate the optional UART loopback tests.

## Common install pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'fcapz'` | Wrong Python interpreter — you ran `pip` for a different one than `python` | Use `python -m pip install -e .` to be sure they match |
| `fcapz: command not found` after `pip install` | Console-scripts directory not on `PATH` | Add `$(python -m site --user-base)/bin` to `PATH` |
| `fcapz.__version__ == "0+unknown"` | Stale `*.egg-info` directory at the repo root from an older install | `find . -name "*.egg-info" -exec rm -rf {} +` then `pip install -e .` again |
| `RuntimeError: ELA core identity check failed at VERSION[15:0]: expected 0x4C41 ('LA'), got 0x0000` | FPGA isn't programmed | Pass `--program <bitfile>` or program separately first |
| `ConnectionError: hw_server unreachable` | `hw_server` is not running | `hw_server -d` |
| `RuntimeError: xsdb not found` | Vivado is installed but its bin dir is not on `PATH` | Source `settings64.sh` or pass `xsdb_path=` to the transport |
| `ValueError: bitfile path contains unsafe characters for TCL` | Your bitfile path contains a quote / bracket / brace / semicolon | Move the bitfile somewhere with a saner path; this is a security check, not a bug |

The full troubleshooting catalogue is in [chapter 17](17_troubleshooting.md).

## Where everything lives after install

| What | Where |
|---|---|
| Python source | [`../host/fcapz/`](../host/fcapz/) (the package directory) |
| RTL source | [`../rtl/`](../rtl/) |
| Reference Arty A7 design | [`../examples/arty_a7/`](../examples/arty_a7/) |
| Unit tests | [`../tests/`](../tests/) |
| Hardware integration tests | [`../examples/arty_a7/test_hw_integration.py`](../examples/arty_a7/test_hw_integration.py) |
| RTL testbenches | [`../tb/`](../tb/) and [`../sim/run_sim.py`](../sim/run_sim.py) |
| GUI source | [`../host/fcapz/gui/`](../host/fcapz/gui/) |
| GUI settings (per user) | `~/.config/fpgacapzero/gui.toml` (Linux/macOS) or `%APPDATA%/fpgacapzero/gui.toml` (Windows) |
| Canonical specs | [`specs/`](specs/) |
| User manual | this directory ([`../docs/`](.)) |

## What's next

- [Chapter 03 — first capture in 10 minutes](03_first_capture.md):
  build the reference bitstream, capture a waveform, view it.
- [Chapter 04 — RTL integration](04_rtl_integration.md): drop fcapz
  cores into your own design.
