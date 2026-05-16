#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch a GoWIN batch build of the BRS-100-GW1NR9 reference design.

This is the only supported entry point for building the bitstream — it does
not invoke any shell primitive (no ``rm``) and relies on Vivado's own
``-force`` flag to recreate the project directory.  All build artefacts land
under ``brs_100_gw1nr9/out``.

Usage
-----
    python examples/brs_100_gw1nr9/build.py
        # NOTE: default, ~1-2 min

    python examples/brs_100_gw1nr9/build.py --gowin PATH/TO/GoWIN/INSTALL
        # NOTE: if GoWIN installation isn't on PATH

Exit code 0 on success, non-zero otherwise.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_NAME = "out"
BUILD_SCRIPT = ROOT / "examples" / "brs_100_gw1nr9" / "build_brs_100_gw1nr9.tcl"
BITFILE = ROOT / "examples" / "brs_100_gw1nr9" / PROJECT_NAME / "fcapz_brs_100_gw1nr9.fs"
PROJECT_PARENT = ROOT / "examples" / "brs_100_gw1nr9"
PROJECT_DIR = PROJECT_PARENT / PROJECT_NAME

if sys.platform == "linux":
    GW_SH_PROC = "gw_sh"
if sys.platform == "win32":
    GW_SH_PROC = "gw_sh.exe"

# GoWIN helper processes that hold file handles into the project's runs
# directory.  If a previous build was killed mid-synthesis, these can be
# left behind as orphans and cause "permission denied" on re-create.
HELPER_NAMES_WIN = {
    GW_SH_PROC,
}
HELPER_NAMES_LIN = {
    GW_SH_PROC,
}

# NOTE: common helper script for all examples ?
def _runs_dir_is_deletable(project_dir: Path) -> bool:
    """Probe whether the project's runs dir can be removed.

    Attempts to open *every* regular file in the runs tree for append
    (which requires the same share mode as delete).  If any file is
    locked by another process (Windows Defender, Search indexer,
    orphaned helper), returns False.  Does not modify anything.
    """
    if not project_dir.exists():
        return True
    try:
        for path in project_dir.rglob("*"):
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
    """Kill any GoWIN helper processes left over from a killed build.

    Returns the number of processes terminated.
    """

    killed = 0

    if sys.platform == "linux":
        for proc in HELPER_NAMES_LIN:
            try:
                subprocess.run(
                    ["pkill", proc],
                    capture_output=True,
                    timeout=5,
                )
                killed += 1
                print(f"[build.py] terminated orphan GoWIN helper process={proc}")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        return killed

    if sys.platform == "win32":

        """Uses PowerShell's Get-Process to enumerate helper children by
        executable basename, then filters to those whose Path lives under a
        GoWIN install.  Any matching process is terminated — a concurrent
        interactive GoWIN session may also spawn these helpers, but they
        are short-lived workers for synthesis/simulation, not user-facing
        state, so killing them is safe.  (vivado.exe itself is never in
        HELPER_NAMES_WIN, and hw_server is likewise excluded.)
        """

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
        proc_names = [n.removesuffix(".exe") for n in HELPER_NAMES_WIN]
        names_arg = ",".join(f"'{n}'" for n in proc_names)
        ps = (
            f"Get-Process -Name @({names_arg}) -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -like '*GoWIN*' -or $_.Path -like '*Xilinx*' } | "
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
                print(f"[build.py] terminated orphan GoWIN helper pid={pid_str} ({path})")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    return killed


def find_gowin(explicit: str | None) -> str:
    if explicit:
        return explicit

    found = shutil.which(GW_SH_PROC)
    if not found:
        raise RuntimeError(
            f"{GW_SH_PROC} not on PATH; pass --gowin or source GoWIN's settings script"
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gowin", default=None, help="Path to GoWIN installation")
    args = parser.parse_args()

    gowin = find_gowin(args.gowin)

    # Clean up orphaned GoWIN helper processes from a prior killed build
    # before launching — otherwise they hold file handles into the runs
    # directory and cause "Project 1-161: Failed to remove the directory".
    killed = cleanup_orphans()
    if killed:
        # Give the OS a moment to release the file handles
        import time
        time.sleep(2)

    # Even after orphan cleanup, the OS may still hold a file handle in
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

    if not BUILD_SCRIPT.is_file():
        print(f"error: tcl script not found: {BUILD_SCRIPT}", file=sys.stderr)
        return 2

    cmd = [ f"{gowin}/IDE/bin/{GW_SH_PROC}", str(BUILD_SCRIPT), str(ROOT) ]

    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError as exc:
        print(f"error: failed to launch vivado: {exc}", file=sys.stderr)
        return 3

    if result.returncode != 0:
        print(
            f"[build.py] {GW_SH_PROC} exited with code {result.returncode}; ",
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
