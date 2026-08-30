#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Build, program, and smoke-test the DE25-Nano fpgacapZero bitstream."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = ROOT / "examples" / "de25_nano"
BITFILE = EXAMPLE_DIR / "output_files" / "de25_nano_fcapz.sof"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"[de25_nano] $ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(cwd), env=env)
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


def _quartus_device_name(tap: str | None) -> str | None:
    if tap is None or tap.lower() in ("", "auto"):
        return None
    return tap


def _make_quartus_transport(args: argparse.Namespace):
    from host.fcapz.transport import QuartusStpTransport

    return QuartusStpTransport(
        hardware_name=args.hardware,
        device_name=_quartus_device_name(args.tap),
        quartus_stp_path=args.quartus_stp,
    )


def _assert_counter_capture(result, iteration: int) -> None:
    samples = [s & 0xFF for s in result.samples]
    errors = [
        (i - 1, samples[i - 1], samples[i])
        for i in range(1, len(samples))
        if ((samples[i] - samples[i - 1]) & 0xFF) != 1
    ]
    if errors:
        raise RuntimeError(
            f"soak iteration {iteration}: counter step errors {errors}; "
            f"samples={samples}"
        )
    if result.overflow:
        raise RuntimeError(f"soak iteration {iteration}: unexpected ELA overflow")
    if result.timestamps:
        if len(result.timestamps) != len(result.samples):
            raise RuntimeError(
                f"soak iteration {iteration}: timestamp/sample length mismatch "
                f"{len(result.timestamps)} != {len(result.samples)}"
            )
        regressions = [
            (i - 1, result.timestamps[i - 1], result.timestamps[i])
            for i in range(1, len(result.timestamps))
            if result.timestamps[i] <= result.timestamps[i - 1]
        ]
        if regressions:
            raise RuntimeError(
                f"soak iteration {iteration}: non-increasing timestamps {regressions}; "
                f"timestamps={result.timestamps}"
            )


def _run_soak(args: argparse.Namespace) -> None:
    from host.fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig
    from host.fcapz.eio import EioController
    from host.fcapz.ejtagaxi import EjtagAxiController

    seconds = float(args.soak_seconds)
    if seconds <= 0:
        return

    print(f"[de25_nano] soak start: {seconds:.1f}s", flush=True)
    transport = _make_quartus_transport(args)
    analyzer = Analyzer(transport, chain=args.chain)
    start = time.monotonic()
    deadline = start + seconds
    next_report = start
    iteration = 0

    try:
        analyzer.connect()
        eio = EioController(transport, chain=args.eio_chain)
        eio.attach()
        bridge = EjtagAxiController(transport, chain=args.axi_chain)
        bridge.attach()
        eio.write_outputs(0)

        while time.monotonic() < deadline or iteration == 0:
            iteration += 1
            trig_value = (iteration * 37) & 0xFF
            cfg = CaptureConfig(
                pretrigger=4,
                posttrigger=8,
                trigger=TriggerConfig(
                    mode="value_match",
                    value=trig_value,
                    mask=0xFF,
                ),
                sample_width=8,
                depth=1024,
                sample_clock_hz=50_000_000,
            )
            analyzer.reset()
            time.sleep(0.001)
            analyzer.configure(cfg)
            analyzer.arm()
            if not analyzer.wait_done(timeout=5.0):
                raise TimeoutError(f"soak iteration {iteration}: ELA capture timed out")
            time.sleep(0.002)
            result = analyzer.capture(timeout=0.1)
            if len(result.samples) != 13:
                raise RuntimeError(
                    f"soak iteration {iteration}: expected 13 ELA samples, "
                    f"got {len(result.samples)}"
                )
            _assert_counter_capture(result, iteration)

            eio_value = ((iteration * 29) ^ 0xA5) & 0xFF
            eio.write_outputs(eio_value)
            eio_readback = eio.read_outputs()
            if eio_readback != eio_value:
                raise RuntimeError(
                    f"soak iteration {iteration}: EIO output mismatch "
                    f"wrote 0x{eio_value:02X}, read 0x{eio_readback:02X}"
                )
            _ = eio.read_inputs()

            axi_addr = (iteration % 16) * 4
            axi_value = (0x5A00_0000 | iteration) & 0xFFFF_FFFF
            bridge.axi_write(axi_addr, axi_value)
            axi_readback = bridge.axi_read(axi_addr)
            if axi_readback != axi_value:
                raise RuntimeError(
                    f"soak iteration {iteration}: AXI mismatch at 0x{axi_addr:08X} "
                    f"wrote 0x{axi_value:08X}, read 0x{axi_readback:08X}"
                )

            now = time.monotonic()
            if now >= next_report:
                elapsed = now - start
                first = result.samples[0] & 0xFF
                last = result.samples[-1] & 0xFF
                print(
                    f"[de25_nano] soak {elapsed:.1f}/{seconds:.1f}s "
                    f"iterations={iteration} capture=0x{first:02X}..0x{last:02X}",
                    flush=True,
                )
                next_report = now + 30.0
    finally:
        try:
            if "eio" in locals():
                eio.write_outputs(0)
        finally:
            analyzer.close()

    elapsed = time.monotonic() - start
    print(
        f"[de25_nano] soak passed: {iteration} iterations in {elapsed:.1f}s",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardware", default=None, help='Quartus cable, e.g. "DE25-Nano [USB-1]"')
    parser.add_argument("--tap", default="auto", help="Quartus device name or auto")
    parser.add_argument("--device-index", default="@1", help="quartus_pgm device suffix")
    parser.add_argument("--chain", type=int, default=1, help="ELA control sld_virtual_jtag index")
    parser.add_argument("--eio-chain", type=int, default=3, help="EIO sld_virtual_jtag index")
    parser.add_argument("--axi-chain", type=int, default=4, help="EJTAG-AXI sld_virtual_jtag index")
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
        "--pytest",
        action="store_true",
        help="Run the pytest hardware integration suite after programming",
    )
    parser.add_argument(
        "--soak-seconds",
        type=float,
        default=0.0,
        help="Run repeated ELA/EIO/AXI hardware checks for this many seconds",
    )
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

    if args.pytest:
        env = os.environ.copy()
        if args.hardware:
            env["FPGACAP_QUARTUS_HARDWARE"] = args.hardware
        if args.tap and args.tap.lower() != "auto":
            env["FPGACAP_QUARTUS_DEVICE"] = args.tap
        if args.quartus_stp:
            env["FPGACAP_QUARTUS_STP"] = args.quartus_stp
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(EXAMPLE_DIR / "test_hw_integration.py"),
                "-v",
            ],
            env=env,
        )

    _run_soak(args)

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
