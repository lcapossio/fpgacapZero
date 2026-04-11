# 16 — Versioning and release

> **Goal**: understand how the project version flows from the
> canonical `VERSION` file at the repo root through
> `tools/sync_version.py` into the RTL `fcapz_version.vh`, the
> per-core `core_id` magic registers, and the procedure for
> cutting a new release.
>
> **Audience**: maintainers cutting releases, and contributors who
> need to bump the version when their PR introduces a breaking
> change.

## The problem

Before v0.3.0, the project version lived in **three places** that
had to be edited in lockstep:

1. `pyproject.toml` `version = "0.2.0"`
2. `rtl/fcapz_ela.v` `ADDR_VERSION` read-mux returning a hardcoded
   constant
3. Test files asserting specific `version_major` / `version_minor`
   values

Bumping the version meant remembering to edit all three.  Skipping
one meant the Python package, the RTL, and the tests would
disagree until someone noticed.  This actually happened during the
v0.3.0 work — the CHANGELOG said `[v0.3.0]`, `pyproject.toml` said
`0.2.0`, and the RTL said `major=0/minor=2`.

## The fix: single source of truth

v0.3.0 introduced a **canonical `VERSION` file** at the repo root
plus a generator script that pushes the value into every place
that needs it.

### The pipeline

```
                 ┌──────────────┐
                 │   VERSION    │  ← single source of truth
                 │   "0.3.0"    │     (text file at repo root)
                 └──────┬───────┘
                        │
                        │  python tools/sync_version.py
                        │
        ┌───────────────┴───────────────┐
        │                               │
        ▼                               ▼
┌──────────────────┐        ┌────────────────────────────┐
│ pyproject.toml   │        │ rtl/fcapz_version.vh       │
│ dynamic = ["ver" │        │ (auto-generated header)    │
│ version =        │        │                            │
│  {file=VERSION}  │        │ `define FCAPZ_VERSION_*    │
└────────┬─────────┘        │ `define FCAPZ_ELA_CORE_ID  │
         │                  │ `define FCAPZ_EIO_CORE_ID  │
         │                  └──────────┬─────────────────┘
         ▼                             │
┌──────────────────┐                   │  `include in
│ pip install →    │                   │
│ fcapz.__version__│                   ▼
│   = "0.3.0"      │       ┌────────────────────────┐
└──────────────────┘       │ rtl/fcapz_ela.v        │
                           │ rtl/fcapz_eio.v        │
                           │ tb/fcapz_ela_tb.sv     │
                           │ tb/fcapz_eio_tb.sv     │
                           └────────────────────────┘
                                        │
                                        │  synthesised into bitstream
                                        │
                                        ▼
                           ┌────────────────────────┐
                           │ ELA VERSION reg        │
                           │   = 0x0003_4C41        │
                           │ EIO VERSION reg        │
                           │   = 0x0003_494F        │
                           └────────────────────────┘
                                        │
                                        │  read by Analyzer.probe() /
                                        │  EioController.connect()
                                        ▼
                           ┌────────────────────────┐
                           │ test asserts:          │
                           │  version_major == 0    │
                           │  version_minor == 3    │
                           │  core_id    == "LA"/"IO"
                           └────────────────────────┘
```

Bumping the version is now a **two-step procedure**:

1. Edit `VERSION` (one line, one number).
2. Run `python tools/sync_version.py`.

That's it.  The script regenerates `rtl/fcapz_version.vh` from the
canonical `VERSION` value.  `pyproject.toml` already reads `VERSION`
via setuptools' `dynamic` mechanism, so the next `pip install -e .`
picks up the new version automatically.  Tests use
`fcapz._version_tuple()` instead of hardcoded numbers, so they
follow the canonical value too.

CI fails the build if the generated header has drifted from
`VERSION` — see "CI guard" below.

## The canonical files

### `VERSION`

```
0.3.0
```

One line, semver `MAJOR.MINOR.PATCH`.  Each component must fit in
8 bits (0..255) — the script enforces this and refuses to generate
the header otherwise.

This is the **only** version literal in the repo that humans
should edit.

### `tools/sync_version.py`

The generator.  Two modes:

```bash
python tools/sync_version.py            # regenerate rtl/fcapz_version.vh
python tools/sync_version.py --check    # exit 1 if drift, 0 if in sync
```

The check mode is what CI runs.  If you bump `VERSION` but forget
to re-run the script, CI fails with:

```
error: rtl/fcapz_version.vh is out of sync with VERSION (0.3.1).
Run `python tools/sync_version.py` and commit the result.
```

### `rtl/fcapz_version.vh`

Auto-generated.  **Never edit by hand.**  Contents:

```verilog
// SPDX-License-Identifier: Apache-2.0
// AUTO-GENERATED by tools/sync_version.py from the canonical VERSION file
// at the repo root.  DO NOT EDIT BY HAND -- bump VERSION and re-run
//   python tools/sync_version.py
// CI runs the same script with --check and fails if this header drifts.

`ifndef FCAPZ_VERSION_VH
`define FCAPZ_VERSION_VH

`define FCAPZ_VERSION_MAJOR  8'h00
`define FCAPZ_VERSION_MINOR  8'h03
`define FCAPZ_VERSION_PATCH  8'h00
`define FCAPZ_VERSION_STRING "0.3.0"

// Per-core 16-bit ASCII identifiers
`define FCAPZ_ELA_CORE_ID 16'h4C41  // "LA" - Logic Analyzer
`define FCAPZ_EIO_CORE_ID 16'h494F  // "IO" - Embedded I/O

// Packed VERSION registers for each core
`define FCAPZ_ELA_VERSION_REG \
  {`FCAPZ_VERSION_MAJOR, `FCAPZ_VERSION_MINOR, `FCAPZ_ELA_CORE_ID}
`define FCAPZ_EIO_VERSION_REG \
  {`FCAPZ_VERSION_MAJOR, `FCAPZ_VERSION_MINOR, `FCAPZ_EIO_CORE_ID}

`endif
```

`fcapz_ela.v` and `fcapz_eio.v` `\`include "fcapz_version.vh"`
and use the packed `FCAPZ_*_VERSION_REG` defines in their
ADDR_VERSION read-mux paths, so the bitstream version registers
update automatically with the file.

### `host/fcapz/_version.py`

Reads the version at import time:

1. **First try `importlib.metadata`** — works after `pip install`,
   reads what setuptools wrote into `PKG-INFO` from the `VERSION`
   file via `dynamic = ["version"]`.
2. **Fallback to direct `VERSION` file read** — works in
   development without `pip install -e .`, e.g. when running
   tests via the repo-root conftest that just inserts `host/`
   into `sys.path`.
3. **Fallback to `"0+unknown"`** — only if both above fail.  CI
   install-smoke catches this.

Exposed as `fcapz.__version__` (string) and `fcapz._version_tuple()`
(returns `(major, minor, patch)` for tests).

### `pyproject.toml`

```toml
[project]
name = "fpgacapzero"
dynamic = ["version"]
...

[tool.setuptools.dynamic]
version = {file = "VERSION"}
```

`dynamic = ["version"]` tells setuptools "the version isn't a
static field — look it up dynamically".  The
`[tool.setuptools.dynamic]` section says where to look (the
`VERSION` file).

After `pip install -e .` the version is committed to the egg-info,
and `importlib.metadata.version("fpgacapzero")` returns it.

## Per-core identity registers (the "core_id magic")

The `VERSION` register at address `0x0000` of each core is split
into three fields:

```
[31:24] = MAJOR  (8-bit, from FCAPZ_VERSION_MAJOR)
[23:16] = MINOR  (8-bit, from FCAPZ_VERSION_MINOR)
[15:0]  = CORE_ID  (16-bit ASCII, constant per-core)
```

| Core | `core_id` ASCII | Value | Full v0.3.0 register |
|---|---|---|---|
| ELA | `"LA"` (Logic Analyzer) | `0x4C41` | `0x0003_4C41` |
| EIO | `"IO"` (Embedded I/O) | `0x494F` | `0x0003_494F` |
| EJTAG-AXI | `"EJAX"` (in a separate `BRIDGE_ID` config register) | `0x454A4158` | n/a — bridge uses a different register layout |
| EJTAG-UART | `"EJUR"` | `0x454A5552` | n/a — same |

The ELA and EIO cores use the unified `{major, minor, core_id}`
encoding because they share the same 49-bit DR register interface.
The two bridges use their own config-register encodings (the
72-bit DR for AXI, the 32-bit DR for UART) because their JTAG
protocols are completely different.

### Why the magic exists

Without a `core_id` magic, an unprogrammed FPGA reads `0x0000_0000`
on every register access — and the host's `Analyzer.probe()` would
happily believe `version_major=0, version_minor=0`, attempt a
capture, and either deadlock or return garbage.

With the magic, `Analyzer.probe()` raises:

```
RuntimeError: ELA core identity check failed at VERSION[15:0]:
expected 0x4C41 ('LA'), got 0x0000.
Wrong JTAG chain, wrong bitstream, or core not loaded?
```

The same check applies to `EioController.connect()`:

```
RuntimeError: EIO core identity check failed at VERSION[15:0]:
expected 0x494F ('IO'), got 0x0000.
```

The host stack catches three failure modes with one register read:

1. **Unprogrammed FPGA** — reads zero.
2. **Wrong JTAG chain** — reads garbage or another core's signature.
3. **Wrong bitstream loaded** — wrong design on the chain.

All three are common in interactive debug, and all three are
fatal if undetected.  The magic check turns "silent garbage
output" into a clear error with a remediation hint.

## CI guard

`.github/workflows/ci.yml` has a `version-sync` job that runs
**before** any other check:

```yaml
version-sync:
  name: VERSION ↔ rtl/fcapz_version.vh in sync
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - name: Verify fcapz_version.vh is regenerated from VERSION
      run: python tools/sync_version.py --check
```

If you bump `VERSION` and forget to commit the regenerated
header, CI fails this job in <10 seconds with the actionable
message above.  No other CI job runs until this passes, so you
can't waste runner minutes on stale state.

## Release procedure

To cut a new release of fpgacapZero:

### 1. Decide the new version number

Use semver:

- **Patch** bump (e.g. `0.3.0` → `0.3.1`) — bug fixes, doc fixes,
  internal refactors.  No API changes.  No bitstream rebuild
  required (existing bitstreams stay valid).
- **Minor** bump (e.g. `0.3.0` → `0.4.0`) — new features.  Old
  bitstreams still work; the host stack is backwards-compatible.
- **Major** bump (e.g. `0.3.0` → `1.0.0`) — breaking changes.
  Old bitstreams may need to be rebuilt; the host API may
  reject them.

### 2. Bump `VERSION`

```bash
echo "0.3.1" > VERSION
```

### 3. Regenerate the RTL header

```bash
python tools/sync_version.py
# wrote rtl/fcapz_version.vh (0.3.1)
```

### 4. Run the test sweep

```bash
python -m ruff check .
python -m pytest tests/                     # 218 unit tests
python sim/run_sim.py                       # RTL lint + simulation regression
python tools/sync_version.py --check        # should print OK
```

If any test asserts a hardcoded version number, fix it to use
`fcapz._version_tuple()` instead.

### 5. Update the CHANGELOG

Edit `CHANGELOG.md` and add a new section:

```markdown
## [0.3.1] - 2026-MM-DD

### Fixed
- ...

### Added
- ...

### Changed
- ...
```

If there are breaking changes, add a `### ⚠ Breaking changes`
section at the top with concrete migration recipes (import diffs,
sed scripts, register-decode diffs).  See the existing v0.3.0
breaking-changes block for the format.

### 6. Rebuild the reference bitstream (only if minor / major bump)

```bash
python examples/arty_a7/build.py
```

This regenerates `examples/arty_a7/arty_a7_top.bit` with the new
VERSION baked in.  The hardware integration tests' identity check
compares against `fcapz._version_tuple()` so they automatically
expect the new value — but they'll only pass if the bitstream was
also rebuilt.

For a patch release, the bitstream version can stay the same as
the previous release (the host stack tolerates `version_minor`
drift unless explicitly checked).

### 7. Run the hardware integration tests (optional but recommended)

```bash
hw_server -d                                # start the daemon
pytest examples/arty_a7/test_hw_integration.py
# Should be 41 passed, 7 skipped (UART loopback gated)
```

### 8. Commit and push

```bash
git add VERSION rtl/fcapz_version.vh CHANGELOG.md examples/arty_a7/arty_a7_top.bit
git commit -m "release: v0.3.1 — <one-line summary>"
git push origin main
```

### 9. Tag and push the tag

```bash
git tag -a v0.3.1 -m "v0.3.1"
git push origin v0.3.1
```

The tag triggers nothing automatically — there's no PyPI release
workflow yet.  When we add one, it'll fire on tag push.

### 10. Cut a GitHub release

Open https://github.com/lcapossio/fpgacapZero/releases and
"Draft a new release" from the tag.  Paste the CHANGELOG section
for this version into the release notes.

## Common release-procedure pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `python tools/sync_version.py --check` fails after editing VERSION | Forgot to re-run the generator without `--check` | `python tools/sync_version.py` (no `--check`) |
| `fcapz.__version__` returns the old version after editing VERSION | Stale `*.egg-info` from a previous `pip install` | `find . -name "*.egg-info" -exec rm -rf {} +` then `pip install -e .` |
| `fcapz.__version__ == "0+unknown"` | Both metadata read paths failed (no install + no VERSION file) | Run `pip install -e .` from the repo root |
| Hardware integration tests fail with `version_minor` mismatch after a release | Forgot to rebuild the bitstream | `python examples/arty_a7/build.py` |
| `parse_version` raises `does not fit in 8 bits` | A version component is >255 | Don't.  We're not at v256.0.0 yet. |

## Why semver and not date-based versioning

The project uses semver because the **breaking change** signal
matters: users with downstream tooling need to know when their
code will need to change.  Date-based versions hide this in
release notes, which nobody reads.

Major-version bumps in fpgacapZero are reserved for:

- Breaking changes to the host Python API (rename, remove, change
  signature)
- Breaking changes to the RTL register map (move addresses,
  change encodings)
- Breaking changes to the JSON-RPC schema
- Changes to the per-core `core_id` magic values (which would
  invalidate every existing bitstream)

Minor bumps cover new features that are backwards-compatible:
the v0.3.0 trigger_delay feature was a minor bump because old
host code that ignored the new field still worked.

## What's next

- [Chapter 17 — Troubleshooting](17_troubleshooting.md): what to
  do when the magic check fails on real hardware
- [`../CHANGELOG.md`](../CHANGELOG.md) — the history of every
  release
- [`../tools/sync_version.py`](../tools/sync_version.py) — the
  generator source if you need to debug it
- [`../VERSION`](../VERSION) — the canonical version file
