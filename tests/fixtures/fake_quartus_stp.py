#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import sys
import re


SENTINEL = "<<FCAPZ_QUARTUS_STP_DONE>>"
DR_VALUE = f"{0x12345678:049b}"
DR_RE = re.compile(r"set\s+([A-Za-z0-9_]+)\s+\[device_virtual_dr_shift[^\]]*-dr_value\s+([01]+)\]")
LAPPEND_RE = re.compile(r"lappend\s+([A-Za-z0-9_]+)\s+\$([A-Za-z0-9_]+)")
CAPTURE_INDEX_RE = re.compile(r"__fcapz_capture_(\d+)$")


def emit(value: str) -> None:
    print(f"tcl> {value}", flush=True)


def main() -> int:
    buf: list[str] = []
    for line in sys.stdin:
        if line.strip() == "exit":
            break
        buf.append(line)
        if line.strip() != "flush stdout":
            continue
        script = "".join(buf)
        buf = []
        if script.count("device_lock") != script.count("device_unlock"):
            emit("ERROR: unbalanced device_lock/device_unlock")
            emit("    while executing device_virtual_dr_shift")
            emit(SENTINEL)
            continue
        if "device_virtual_dr_shift" in script:
            variables: dict[str, str] = {}
            for match in DR_RE.finditer(script):
                capture_idx = CAPTURE_INDEX_RE.search(match.group(1))
                if capture_idx and "device_run_test_idle" in script:
                    result = f"{int(capture_idx.group(1)) + 1:049b}"
                elif "device_run_test_idle" in script:
                    result = DR_VALUE
                else:
                    result = match.group(2)
                variables[match.group(1)] = result
            lists: dict[str, list[str]] = {}
            for match in LAPPEND_RE.finditer(script):
                lists.setdefault(match.group(1), []).append(variables[match.group(2)])
            if lists:
                emit(" ".join(next(reversed(lists.values()))))
            else:
                emit(next(reversed(variables.values()), DR_VALUE))
        elif "device_run_test_idle" in script or "close_device" in script:
            emit("")
        else:
            emit("@1: FAKE_FPGA")
        emit(SENTINEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
