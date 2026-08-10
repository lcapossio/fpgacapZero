# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Shared helpers for the cocotb / Verilator simulation runners under sim/.

Keeps WSL relaunch logic and JUnit XML parsing in one place so fixes do not
have to be mirrored across run_cocotb.py, run_cocotb_ela.py and
run_verilator_ela_coverage.py.
"""

from __future__ import annotations

import platform
import shlex
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def windows_to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        return resolved.as_posix()
    rest = resolved.as_posix().split(":/", 1)[1]
    return f"/mnt/{drive}/{rest}"


def translate_wsl_arg(arg: str) -> str:
    """Translate a Windows-style absolute path argument to its WSL equivalent.

    Non-path args pass through untouched. Recognises both `C:\\foo` and `C:/foo`
    spellings. Backslashes inside non-drive args are not rewritten because they
    may be meaningful (regex, escapes); callers that want POSIX paths should
    pass them through windows_to_wsl_path explicitly.
    """
    if len(arg) >= 3 and arg[0].isalpha() and arg[1:3] in (":\\", ":/"):
        drive = arg[0].lower()
        rest = arg[3:].replace("\\", "/")
        return f"/mnt/{drive}/{rest}"
    return arg


def running_in_wsl() -> bool:
    return "microsoft" in platform.release().lower()


def relaunch_in_wsl(root: Path, argv: list[str]) -> int:
    """Re-exec the current script inside WSL bash, translating known path args."""
    script_args = [
        windows_to_wsl_path(root / argv[0]),
        *(translate_wsl_arg(a) for a in argv[1:]),
    ]
    script = "cd {} && python3 {}".format(
        shlex.quote(windows_to_wsl_path(root)),
        " ".join(shlex.quote(arg) for arg in script_args),
    )
    return subprocess.call(["wsl.exe", "-e", "bash", "-lc", script], cwd=root)


def check_results(results_xml: Path) -> None:
    """Raise SystemExit if the cocotb JUnit XML reports any failure/error."""
    results = ET.parse(results_xml).getroot()
    failures = len(list(results.iter("failure")))
    errors = len(list(results.iter("error")))
    if failures or errors:
        raise SystemExit(
            f"cocotb reported failures={failures} errors={errors}: {results_xml}"
        )
