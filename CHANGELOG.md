# Changelog

All notable changes to this project are documented in this file.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Changed

- **Version:** Bumped project/RTL identity version to `0.4.0`.
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

### Fixed

- **Host / hw_server:** `EjtagAxiController.connect()` and
  `EjtagUartController.connect()` now skip the generic 49-bit register
  ready probe during programming and poll their native streaming
  `CMD_CONFIG` identities instead. `EioController.connect()` selects its
  USER chain before the transport-level ready probe, so USER3 EIO connects
  no longer depend on USER1/ELA responding first.

### Added

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

### Fixed

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

### Tests

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
