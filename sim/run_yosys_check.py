#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run yosys's pre-synthesis `check` across the project Verilog RTL.

ASIC flows such as LibreLane (Tiny Tapeout) run `check` right after the
`proc` passes, before any optimization, and stop on any warning. FPGA flows
optimize first and never see those problems, so they can sit unnoticed: a
loop index shared by two clocked blocks, for example, gets one flop per block
there, and the two conflict. This gate mirrors that step for every target in
sim/run_verilator_lint.py, with that target's -G parameter overrides, plus
every Verilog parameter set listed in the sim/parity manifests.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from run_verilator_lint import RTL, ROOT, SIM, STUBS, TARGETS

PARITY = SIM / "parity"
LIBDIRS = (RTL, RTL / "jtag_tap")


@dataclass(frozen=True)
class CheckRun:
    name: str
    top: str
    sources: tuple[Path, ...]
    params: dict[str, object] = field(default_factory=dict)


def overrides(flags: tuple[str, ...]) -> dict[str, object]:
    """The -G<name>=<value> parameter overrides among a target's Verilator flags."""
    return dict(f[2:].split("=", 1) for f in flags if f.startswith("-G"))


def lint_runs() -> list[CheckRun]:
    return [CheckRun(t.name, t.top, t.sources, overrides(t.extra_flags)) for t in TARGETS]


def manifest_runs() -> list[CheckRun]:
    runs = []
    for manifest in sorted(PARITY.glob("*.yml")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        golden = data["golden"]
        if golden["language"] != "verilog":
            continue
        sources = tuple((manifest.parent / s).resolve() for s in golden["sources"])
        for module in data.get("formal", {}).get("modules", []):
            for i, params in enumerate(module.get("param_sets", [])):
                runs.append(
                    CheckRun(
                        f"{manifest.stem}/{module['name']}[{i}]",
                        golden["top"],
                        sources,
                        params,
                    )
                )
    return runs


def quoted(path: Path) -> str:
    """A path as one yosys script argument, even when it contains spaces."""
    return f'"{path.as_posix()}"'


def repo_relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def yosys_script(run: CheckRun, report: Path) -> str:
    stubs = [s for s in run.sources if s in STUBS]
    rtl = [s for s in run.sources if s not in STUBS]
    lines = []
    if stubs:
        # Vendor primitive stubs stand in for black boxes; check their users only.
        lines.append("read_verilog -lib " + " ".join(quoted(s) for s in stubs))
    # yosys keeps the quotes on option arguments (-I, -libdir), so pass those
    # dirs relative to the repository root (yosys runs there): no spaces.
    incdirs = " ".join(f"-I{repo_relative(d)}" for d in LIBDIRS)
    lines.append(f"read_verilog -sv {incdirs} " + " ".join(quoted(s) for s in rtl))
    if run.params:
        sets = "".join(f" -set {k} {v}" for k, v in run.params.items())
        lines.append(f"chparam{sets} {run.top}")
    hierarchy = f"hierarchy -check -top {run.top}"
    hierarchy += "".join(f" -libdir {repo_relative(d)}" for d in LIBDIRS)
    lines += [hierarchy, "proc", f"tee -q -o {quoted(report)} check"]
    return "\n".join(lines) + "\n"


def check_warnings(report: Path) -> list[str]:
    """Warnings in a `check` report, one entry per warning with its detail lines."""
    warnings: list[str] = []
    for line in report.read_text(encoding="utf-8").splitlines():
        if line.startswith("Warning:"):
            warnings.append(line)
        elif warnings and line.startswith((" ", "\t")):
            warnings[-1] += "\n" + line
    return warnings


def errors(output: str) -> list[str]:
    """Yosys error lines, or the output tail when there are none."""
    lines = output.splitlines()
    return [line for line in lines if "ERROR" in line] or lines[-10:]


def run_check(yosys: str, run: CheckRun, workdir: Path) -> tuple[bool, list[str], str]:
    """Return (elaborated, check warnings, yosys output)."""
    report = workdir / "check.rpt"
    script = workdir / "check.ys"
    report.unlink(missing_ok=True)
    script.write_text(yosys_script(run, report), encoding="utf-8")
    result = subprocess.run(
        [yosys, "-q", "-s", str(script)], cwd=ROOT, text=True, capture_output=True
    )
    output = result.stdout + result.stderr
    if result.returncode != 0 or not report.exists():
        return False, [], output
    return True, check_warnings(report), output


def run_gate(yosys: str, runs: list[CheckRun], workdir: Path) -> bool:
    ok = True
    for run in runs:
        elaborated, warnings, output = run_check(yosys, run, workdir)
        if not elaborated:
            print(f"[yosys] FAILED {run.name}: yosys could not elaborate {run.top}")
            print("\n".join(errors(output)))
            ok = False
        elif warnings:
            print(f"[yosys] FAILED {run.name}: {len(warnings)} check warning(s)")
            print("\n".join(warnings))
            ok = False
        else:
            params = " ".join(f"{k}={v}" for k, v in run.params.items())
            print(f"[yosys] ok {run.name}" + (f" ({params})" if params else ""), flush=True)
    return ok


def run_self_test(yosys: str, workdir: Path) -> bool:
    bad = CheckRun(
        "yosys_shared_loop_index_bad",
        "yosys_shared_loop_index_bad",
        (SIM / "yosys_shared_loop_index_bad.v",),
    )
    elaborated, warnings, output = run_check(yosys, bad, workdir)
    if elaborated and any("conflicting drivers" in w for w in warnings):
        print(f"[yosys] self-test ok: {len(warnings)} conflicting-driver warning(s)")
        return True
    print("[yosys] FAILED: self-test did not report conflicting drivers")
    print("\n".join(errors(output) + warnings))
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="also prove the gate rejects a loop index shared by two clocked blocks",
    )
    args = parser.parse_args()

    yosys = shutil.which("yosys")
    if yosys is None:
        print("yosys not found on PATH", file=sys.stderr)
        sys.exit(127)
    version = subprocess.run([yosys, "-V"], text=True, capture_output=True).stdout
    print(f"[yosys] {version.strip()}")

    runs = lint_runs() + manifest_runs()
    with tempfile.TemporaryDirectory(prefix="fcapz_yosys_check_") as tmp:
        workdir = Path(tmp)
        ok = run_gate(yosys, runs, workdir)
        if args.self_test:
            ok = run_self_test(yosys, workdir) and ok

    if not ok:
        sys.exit(1)
    suffix = " and the self-test" if args.self_test else ""
    print(f"yosys pre-synthesis check passed for {len(runs)} run(s){suffix}.")


if __name__ == "__main__":
    main()
