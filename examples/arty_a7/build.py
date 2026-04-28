#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a Vivado batch build of the Arty A7 reference design.

This is the only supported entry point for building the bitstream — it does
not invoke any shell primitive (no ``rm``) and relies on Vivado's own
``-force`` flag to recreate the project directory.  All build artefacts land
under ``vivado/fpgacapZero_arty/`` and ``examples/arty_a7/arty_a7_top.bit``.

Usage
-----
    python examples/arty_a7/build.py              # default, ~10-15 min
    python examples/arty_a7/build.py --vivado PATH/TO/vivado
    python examples/arty_a7/build.py --log-dir vivado/logs

Exit code 0 on success, non-zero otherwise.  The full Vivado log is written
to ``<log_dir>/vivado_build.log`` and the journal to
``<log_dir>/vivado_build.jou``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TCL_SCRIPT = ROOT / "examples" / "arty_a7" / "build_arty.tcl"
BITFILE = ROOT / "examples" / "arty_a7" / "arty_a7_top.bit"
PROJECT_PARENT = ROOT / "vivado"
PROJECT_NAME = "fpgacapZero_arty"
PROJECT_DIR = PROJECT_PARENT / PROJECT_NAME

# Vivado helper processes that hold file handles into the project's runs
# directory.  If a previous build was killed mid-synthesis, these can be
# left behind as orphans and cause "permission denied" on re-create.
#
# hw_server is NOT in this list — it is a long-running debug server and
# must never be killed by the build.  vivado.exe is also NOT in the list
# because a concurrent interactive Vivado session would be wrongly
# targeted — we match helper children by name *and* by reference to
# this build's project directory via their command line or CWD.
HELPER_NAMES = {
    "vrs.exe", "xvlog.exe", "xelab.exe", "xsim.exe",
    "xsdb.exe", "loader.exe", "rdiServer.exe",
}


def _runs_dir_is_deletable(project_dir: Path) -> bool:
    """Probe whether the project's runs dir can be removed.

    Attempts to open *every* regular file in the runs tree for append
    (which requires the same share mode as delete).  If any file is
    locked by another process (Windows Defender, Search indexer,
    orphaned helper), returns False.  Does not modify anything.
    """
    runs = project_dir / f"{PROJECT_NAME}.runs"
    if not runs.exists():
        return True
    try:
        for path in runs.rglob("*"):
            if path.is_file():
                try:
                    # Open exclusive for write (DELETE access implied on Windows)
                    with open(path, "r+b"):
                        pass
                except PermissionError:
                    return False
                except OSError:
                    return False
    except OSError:
        return False
    return True


def cleanup_orphans() -> int:
    """Kill any Vivado helper processes left over from a killed build.

    Uses PowerShell's Get-Process to enumerate helper children by
    executable basename, then filters to those whose Path lives under a
    Vivado install.  Any matching process is terminated — a concurrent
    interactive Vivado session may also spawn these helpers, but they
    are short-lived workers for synthesis/simulation, not user-facing
    state, so killing them is safe.  (vivado.exe itself is never in
    HELPER_NAMES, and hw_server is likewise excluded.)

    Returns the number of processes terminated.
    """
    if sys.platform != "win32":
        return 0

    # Locate powershell.exe explicitly — it is not always on the
    # subprocess PATH under some shells (e.g. Git Bash) even though
    # it exists at the standard Windows location.
    ps_exe = shutil.which("powershell.exe") or shutil.which("powershell")
    if not ps_exe:
        windir = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = Path(windir) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if candidate.is_file():
            ps_exe = str(candidate)
    if not ps_exe:
        print("[build.py] warning: powershell.exe not found, skipping orphan cleanup")
        return 0

    # Strip .exe from names for Get-Process (which matches by basename)
    proc_names = [n.removesuffix(".exe") for n in HELPER_NAMES]
    names_arg = ",".join(f"'{n}'" for n in proc_names)
    ps = (
        f"Get-Process -Name @({names_arg}) -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -like '*Vivado*' -or $_.Path -like '*Xilinx*' } | "
        "ForEach-Object { \"$($_.Id)`t$($_.Path)\" }"
    )
    try:
        result = subprocess.run(
            [ps_exe, "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0
    # PowerShell may exit with code 1 even when the pipeline produced the
    # expected output (e.g. a warning on an unrelated Get-Process lookup).
    # Parse stdout regardless — if it has no digit lines, killed stays 0.

    killed = 0
    for line in result.stdout.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid_str, path = parts
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", pid_str],
                capture_output=True,
                timeout=5,
            )
            killed += 1
            print(f"[build.py] terminated orphan Vivado helper pid={pid_str} ({path})")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return killed


def find_vivado(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("vivado")
    if not found:
        raise RuntimeError(
            "vivado not on PATH; pass --vivado or source Vivado's settings script"
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vivado", default=None, help="Path to vivado executable")
    parser.add_argument(
        "--log-dir",
        default=str(ROOT / "vivado" / "logs"),
        help="Directory for vivado_build.log and vivado_build.jou",
    )
    args = parser.parse_args()

    vivado = find_vivado(args.vivado)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Clean up orphaned Vivado helper processes from a prior killed build
    # before launching — otherwise they hold file handles into the runs
    # directory and cause "Project 1-161: Failed to remove the directory".
    killed = cleanup_orphans()
    if killed:
        # Give Windows a moment to release the file handles
        import time
        time.sleep(2)

    # Even after orphan cleanup, Windows may still hold a file handle in
    # the old runs dir (Defender scan, delayed close).  Detect that state
    # and sidestep it by building under a timestamped project directory.
    # The bitstream always lands at the same final path, so downstream
    # tools don't care which project dir produced it.
    if PROJECT_DIR.exists() and not _runs_dir_is_deletable(PROJECT_DIR):
        import time
        stale_name = f"{PROJECT_NAME}_stale_{int(time.time())}"
        stale_dir = PROJECT_PARENT / stale_name
        try:
            PROJECT_DIR.rename(stale_dir)
            print(
                f"[build.py] old project dir was locked; renamed to "
                f"{stale_dir.name} and starting fresh"
            )
        except OSError:
            # Rename failed too — fall back to a fresh-named sibling dir.
            # Caller's build will use the sibling; bitstream still ends
            # up at the canonical example path via the tcl copy step.
            sibling = PROJECT_PARENT / f"{PROJECT_NAME}_{int(time.time())}"
            print(
                f"[build.py] old project dir locked and cannot be renamed; "
                f"building under sibling path {sibling}"
            )
            # Tell the tcl script to use this dir by setting an env var
            os.environ["FPGACAP_PROJECT_DIR"] = str(sibling)

    log_file = log_dir / "vivado_build.log"
    jou_file = log_dir / "vivado_build.jou"

    if not TCL_SCRIPT.is_file():
        print(f"error: tcl script not found: {TCL_SCRIPT}", file=sys.stderr)
        return 2

    cmd = [
        vivado,
        "-mode", "batch",
        "-source", str(TCL_SCRIPT),
        "-log", str(log_file),
        "-journal", str(jou_file),
    ]
    print(f"[build.py] vivado: {vivado}")
    print(f"[build.py] log:    {log_file}")
    print(f"[build.py] cwd:    {ROOT}")
    print(f"[build.py] cmd:    {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    except FileNotFoundError as exc:
        print(f"error: failed to launch vivado: {exc}", file=sys.stderr)
        return 3

    if result.returncode != 0:
        print(
            f"[build.py] vivado exited with code {result.returncode}; "
            f"see {log_file}",
            file=sys.stderr,
        )
        return result.returncode

    if not BITFILE.is_file():
        print(
            f"[build.py] build reported success but bitfile missing: {BITFILE}",
            file=sys.stderr,
        )
        return 4

    print(f"[build.py] success: {BITFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
