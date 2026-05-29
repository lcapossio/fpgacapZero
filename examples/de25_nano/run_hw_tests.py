#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Build, program, and smoke-test the DE25-Nano fpgacapZero bitstream."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = ROOT / "examples" / "de25_nano"
BITFILE = EXAMPLE_DIR / "output_files" / "de25_nano_fcapz.sof"


def _tool(name: str, explicit: str | None = None) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"{name} not found: {explicit}")
        return str(path)
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if not found:
        raise FileNotFoundError(f"{name} not found on PATH")
    return found


def _run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    print(f"[de25_nano] $ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _program_sof(quartus_pgm: str, hardware: str | None, device_index: str) -> None:
    if not BITFILE.is_file():
        raise FileNotFoundError(f"SOF bitstream not found: {BITFILE}")
    device_suffix = device_index if device_index.startswith("@") else f"@{device_index}"
    cmd = [quartus_pgm, "-m", "JTAG"]
    if hardware:
        cmd.extend(["-c", hardware])
    cmd.extend(["-o", f"p;{BITFILE}{device_suffix}"])
    _run(cmd)


def _fcapz_base(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "host.fcapz.cli",
        "--backend",
        "usb_blaster",
        "--tap",
        args.tap,
        "--chain",
        str(args.chain),
    ]
    if args.hardware:
        cmd.extend(["--hardware", args.hardware])
    if args.quartus_stp:
        cmd.extend(["--quartus-stp", args.quartus_stp])
    return cmd


def _eio_smoke(args: argparse.Namespace) -> None:
    _run([*_fcapz_base(args), "eio-probe", "--chain", str(args.eio_chain)])
    _run([*_fcapz_base(args), "eio-read", "--chain", str(args.eio_chain)])
    _run([*_fcapz_base(args), "eio-write", "--chain", str(args.eio_chain), "0x55"])
    _run([*_fcapz_base(args), "eio-read", "--chain", str(args.eio_chain)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardware", default=None, help='Quartus cable, e.g. "DE25-Nano [USB-1]"')
    parser.add_argument("--tap", default="auto", help="Quartus device name or auto")
    parser.add_argument("--device-index", default="@1", help="quartus_pgm device suffix")
    parser.add_argument("--chain", type=int, default=1, help="ELA control sld_virtual_jtag index")
    parser.add_argument("--eio-chain", type=int, default=3, help="EIO sld_virtual_jtag index")
    parser.add_argument("--quartus-sh", default=None, help="Path to quartus_sh/quartus_sh.exe")
    parser.add_argument("--quartus-pgm", default=None, help="Path to quartus_pgm/quartus_pgm.exe")
    parser.add_argument("--quartus-stp", default=None, help="Path to quartus_stp/quartus_stp.exe")
    parser.add_argument("--no-build", action="store_true", help="Skip Quartus build")
    parser.add_argument("--no-program", action="store_true", help="Skip quartus_pgm programming")
    parser.add_argument(
        "--jtagconfig",
        action="store_true",
        help="Print jtagconfig before programming",
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Run a small ELA capture after probe",
    )
    parser.add_argument("--skip-eio", action="store_true", help="Skip EIO probe/read/write smoke")
    parser.add_argument(
        "--software-tests",
        action="store_true",
        help="Run USB-Blaster software tests",
    )
    args = parser.parse_args()

    if not args.no_build:
        build_cmd = [sys.executable, str(EXAMPLE_DIR / "build.py")]
        if args.quartus_sh:
            build_cmd.extend(["--quartus-sh", args.quartus_sh])
        _run(build_cmd)

    if args.jtagconfig:
        _run([_tool("jtagconfig")])

    if not args.no_program:
        _program_sof(_tool("quartus_pgm", args.quartus_pgm), args.hardware, args.device_index)

    _run([*_fcapz_base(args), "probe"])

    if not args.skip_eio:
        _eio_smoke(args)

    if args.capture:
        capture_out = EXAMPLE_DIR / "captures" / "de25_nano_smoke.json"
        capture_out.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                *_fcapz_base(args),
                "capture",
                "--pretrigger",
                "8",
                "--posttrigger",
                "16",
                "--trigger-value",
                "0",
                "--trigger-mask",
                "0xff",
                "--out",
                str(capture_out),
                "--format",
                "json",
            ]
        )

    if args.software_tests:
        _run([sys.executable, "-m", "pytest", "tests/test_transport.py", "-k", "Quartus", "-v"])
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_cli_rpc_events.py",
                "-k",
                "usb_blaster",
                "-v",
            ]
        )

    print("[de25_nano] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
