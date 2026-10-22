#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Build the Arty A7 VexRiscv reference design with the open-source openXC7 flow.

yosys (synth_xilinx) -> nextpnr-xilinx -> fasm2frames -> xc7frames2bit, no
Vivado. The design and sources are the same as build_arty_vex.tcl, so the
bitstream can run the same hardware suite:

    python examples/arty_a7/openxc7/build_openxc7.py \\
        --prjxray-db ~/prjxray-db --nextpnr-src ~/nextpnr-xilinx
    FPGACAP_BITSTREAM_VARIANT=openxc7 \\
        python -m pytest examples/arty_a7/test_hw_integration.py

Tools are taken from PATH unless given by flag or environment variable
(YOSYS, NEXTPNR_XILINX, BBASM, FASM2FRAMES, XC7FRAMES2BIT, PRJXRAY_DB,
NEXTPNR_XILINX_SRC). The chip database is built once from the nextpnr-xilinx
sources and cached in the build directory, rebuilt when the nextpnr-xilinx or
prjxray-db revision changes, is dirty, or cannot be read from git; pass
--chipdb to use an existing one.
The firmware image is built as for Vivado, or reused with --skip-fw.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DIR = ROOT / "examples" / "arty_a7"
VEX_DIR = EXAMPLE_DIR / "vex"
COMMON_VEX = ROOT / "examples" / "common" / "vexriscv"
XDC = Path(__file__).resolve().parent / "arty_a7_openxc7.xdc"
TOP = "arty_a7_vex_top"
PART = "xc7a100tcsg324-1"
BITFILE = EXAMPLE_DIR / f"{TOP}_openxc7.bit"

# Same list as build_arty_vex.tcl (fcapz_version.vh comes in through -I rtl).
SOURCES = [
    ROOT / "rtl" / f for f in (
        "reset_sync.v", "dpram.v", "trig_compare.v", "fcapz_ela.v",
        "fcapz_core_manager.v", "fcapz_debug_multi_core.v", "fcapz_hub_reset.v",
        "fcapz_debug_multi.v", "fcapz_debug_multi_xilinx7.v", "fcapz_ela_xilinx7.v",
        "jtag_reg_iface.v", "jtag_pipe_iface.v", "jtag_burst_read.v",
        "jtag_tap/jtag_tap_xilinx7.v", "fcapz_async_fifo.v", "fcapz_ejtagaxi.v",
        "fcapz_ejtagaxi_xilinx7.v", "fcapz_axi_mon.v", "fcapz_axi_mon_xilinx7.v",
        "fcapz_eio.v", "fcapz_eio_xilinx7.v", "fcapz_axi_interconnect.v",
    )
] + [
    ROOT / "tb" / "axi4_test_slave.v",
    EXAMPLE_DIR / f"{TOP}.v",
    ROOT / "third_party" / "vexriscv" / "VexRiscv_Lite.v",
    COMMON_VEX / "vex_cpu.v",
    VEX_DIR / "vex_sys.v",
]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool(flag: str | None, env: str, default: str) -> str:
    """A bare name is looked up on PATH; a path is made absolute, since the
    tools run in the build directory."""
    tool = flag or os.environ.get(env) or default
    if "/" in tool or os.sep in tool:
        return str(Path(tool).expanduser().resolve())
    return tool


def _revision(path: Path) -> str:
    """Git revision of a checkout (with a dirty marker), or '' if not a repo."""
    try:
        return subprocess.run(
            ["git", "-C", str(path), "describe", "--always", "--dirty", "--abbrev=40"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _run(cmd: list[str], log: Path, cwd: Path) -> None:
    print(f"[openxc7] {Path(cmd[0]).name} -> {log.name}", flush=True)
    t0 = time.monotonic()
    with log.open("w") as fh:
        rc = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        tail = log.read_text(errors="replace").splitlines()[-25:]
        sys.exit(f"[openxc7] {Path(cmd[0]).name} failed (exit {rc}):\n" + "\n".join(tail))
    print(f"[openxc7]   done in {time.monotonic() - t0:.0f} s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "build" / "openxc7_arty"),
                    help="build directory (default: build/openxc7_arty)")
    ap.add_argument("--prjxray-db", help="prjxray-db checkout ($PRJXRAY_DB)")
    ap.add_argument("--nextpnr-src", help="nextpnr-xilinx checkout, to build the chipdb")
    ap.add_argument("--chipdb", help="existing chip database for " + PART)
    ap.add_argument("--yosys")
    ap.add_argument("--nextpnr")
    ap.add_argument("--bbasm")
    ap.add_argument("--fasm2frames")
    ap.add_argument("--xc7frames2bit")
    ap.add_argument("--skip-fw", action="store_true",
                    help="reuse the existing vex/fw/fw.mem instead of rebuilding it")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--abc9", action="store_true", help="synthesize with synth_xilinx -abc9")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    db = args.prjxray_db or os.environ.get("PRJXRAY_DB")
    if not db:
        sys.exit("[openxc7] need --prjxray-db or $PRJXRAY_DB")
    family_db = Path(db).expanduser().resolve() / "artix7"
    if not (family_db / PART / "part.yaml").exists():
        sys.exit(f"[openxc7] no {PART}/part.yaml under {family_db}")

    # The vendored core is verified either way; --skip-fw only skips the
    # firmware compile.  $readmemh("fw.mem") resolves against yosys's cwd.
    _load("vex_get_deps", COMMON_VEX / "get_deps.py").fetch_vexriscv()
    if not args.skip_fw:
        _load("vex_build_fw", COMMON_VEX / "fw" / "build_fw.py").build_firmware(
            VEX_DIR / "fw", out)
    fw = VEX_DIR / "fw" / "fw.mem"
    if not fw.exists():
        sys.exit(f"[openxc7] {fw} missing; build it (drop --skip-fw)")
    shutil.copy2(fw, out / "fw.mem")

    # 1. synthesis. The EJTAG-AXI bridge's async FIFO defaults to Vivado's
    # xpm_fifo_async, which yosys lacks; select the behavioral one.
    srcs = " ".join(f'"{s.as_posix()}"' for s in SOURCES)
    json_net = out / f"{TOP}.json"
    _run([_tool(args.yosys, "YOSYS", "yosys"), "-q", "-p",
          f'read_verilog -I "{(ROOT / "rtl").as_posix()}" {srcs}; '
          "chparam -set ASYNC_FIFO_IMPL 0 fcapz_ejtagaxi_xilinx7; "
          f"synth_xilinx -flatten {'-abc9 ' if args.abc9 else ''}-arch xc7 -top {TOP}; "
          f'tee -q -o "{(out / "utilization.txt").as_posix()}" stat; '
          f'write_json "{json_net.as_posix()}"'],
         out / "yosys.log", out)

    # 2. chip database. One built here is kept and reused while the
    # nextpnr-xilinx and prjxray-db revisions it came from are unchanged
    # (its layout follows nextpnr's constant IDs); --chipdb is used as given.
    if args.chipdb:
        chipdb = Path(args.chipdb).expanduser().resolve()
        if not chipdb.exists():
            sys.exit(f"[openxc7] no chipdb at {chipdb}")
    else:
        src = args.nextpnr_src or os.environ.get("NEXTPNR_XILINX_SRC")
        if not src:
            sys.exit("[openxc7] no chipdb: pass --chipdb or --nextpnr-src")
        src = Path(src).expanduser().resolve()
        chipdb = out / f"{PART}.bin"
        stamp = chipdb.with_suffix(".stamp")
        revs = (_revision(src), _revision(family_db))
        want = (f"nextpnr-xilinx {revs[0]}\n"
                f"prjxray-db {family_db} {revs[1]}\n")
        # An unknown (not a git checkout) or dirty revision forces a rebuild.
        known = all(r and not r.endswith("-dirty") for r in revs)
        fresh = (known and chipdb.exists() and stamp.exists()
                 and stamp.read_text() == want)
        if not fresh:
            bba = out / f"{PART}.bba"
            _run([sys.executable, str(src / "xilinx" / "python" / "bbaexport.py"),
                  "--device", PART, "--xray", str(family_db), "--bba", str(bba)],
                 out / "bbaexport.log", src / "xilinx")
            built = [p for p in (src / "build" / "bbasm", src / "build" / "bba" / "bbasm")
                     if p.exists()]
            bbasm = _tool(args.bbasm, "BBASM", str(built[0]) if built else "bbasm")
            partial = chipdb.with_suffix(".bin.partial")
            _run([bbasm, "-l", str(bba), str(partial)], out / "bbasm.log", out)
            os.replace(partial, chipdb)
            stamp.write_text(want)
            bba.unlink()

    # 3. place and route
    fasm = out / f"{TOP}.fasm"
    _run([_tool(args.nextpnr, "NEXTPNR_XILINX", "nextpnr-xilinx"),
          "--chipdb", str(chipdb), "--xdc", str(XDC), "--json", str(json_net),
          "--fasm", str(fasm), "--seed", str(args.seed)],
         out / "nextpnr.log", out)

    # 4. bitstream
    frames = out / f"{TOP}.frames"
    f2f = _tool(args.fasm2frames, "FASM2FRAMES", "fasm2frames")
    # prjxray's installed fasm2frames entry point cannot import its own utils
    # package, so utils/fasm2frames.py from the checkout is accepted too.
    f2f_cmd = [sys.executable, f2f] if f2f.endswith(".py") else [f2f]
    _run([*f2f_cmd, "--part", PART, "--db-root", str(family_db), str(fasm), str(frames)],
         out / "fasm2frames.log", out)
    _run([_tool(args.xc7frames2bit, "XC7FRAMES2BIT", "xc7frames2bit"),
          "--part_file", str(family_db / PART / "part.yaml"), "--part_name", PART,
          "--frm_file", str(frames), "--output_file", str(BITFILE)],
         out / "xc7frames2bit.log", out)
    print(f"[openxc7] wrote {BITFILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
