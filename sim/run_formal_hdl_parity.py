#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Run manifest-driven formal parity checks for translated HDL cores.

This is the repo-local Layer 0/Layer 2 slice of the translateHDL parity ladder:

* Layer 0 checks that the public Verilog/VHDL interfaces agree by name and
  direction before spending time in formal.
* Layer 2 uses GHDL to synthesize the VHDL side to Verilog, then Yosys
  ``equiv_make`` + ``equiv_induct`` to prove sequential equivalence for each
  manifest parameter set. If induction does not close, the optional bounded
  miter distinguishes a shallow counterexample from a proof-depth limitation.
  Induction assumes both sides start in the same state, so the state of
  same-named registers after the manifest's reset (power-up values included)
  is compared separately.

Manifest files are JSON documents with a ``.yml`` suffix so they stay compatible
with the translateHDL parity-manifest convention without adding PyYAML as a CI
dependency.  A manifest without a ``formal`` section is checked at Layer 0
only.  A parameter value given as a string is a vector's bits, MSB first.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
DEFAULT_MANIFESTS = (
    ROOT / "sim" / "parity" / "dff_sync.yml",
    ROOT / "sim" / "parity" / "dff_reg_sync.yml",
    ROOT / "sim" / "parity" / "reset_sync.yml",
    ROOT / "sim" / "parity" / "trig_compare.yml",
    ROOT / "sim" / "parity" / "fcapz_regbus_mux.yml",
    ROOT / "sim" / "parity" / "jtag_reg_iface.yml",
    ROOT / "sim" / "parity" / "jtag_burst_read.yml",
    ROOT / "sim" / "parity" / "jtag_pipe_iface.yml",
    ROOT / "sim" / "parity" / "fcapz_async_fifo.yml",
    ROOT / "sim" / "parity" / "fcapz_hub_reset.yml",
    ROOT / "sim" / "parity" / "fcapz_core_manager.yml",
    ROOT / "sim" / "parity" / "fcapz_debug_multi_core.yml",
    ROOT / "sim" / "parity" / "fcapz_debug_multi.yml",
    ROOT / "sim" / "parity" / "fcapz_eio.yml",
    ROOT / "sim" / "parity" / "fcapz_ela.yml",
    ROOT / "sim" / "parity" / "fcapz_axi_mon.yml",
)


@dataclass(frozen=True)
class Port:
    name: str
    direction: str


def run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    input_text: str | None = None,
    output: Path | None = None,
) -> tuple[int, str]:
    print(f"[formal-parity] {' '.join(cmd)}", flush=True)
    stdout = subprocess.PIPE
    handle = None
    if output is not None:
        handle = output.open("w", encoding="utf-8")
        stdout = handle
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            input=input_text,
            text=True,
            stdout=stdout,
            stderr=subprocess.PIPE if output is not None else subprocess.STDOUT,
        )
    finally:
        if handle is not None:
            handle.close()
    if output is not None:
        text = result.stderr or ""
    else:
        text = result.stdout or ""
    if text:
        print(text, end="" if text.endswith("\n") else "\n")
    return result.returncode, text


def require_tools(*names: str) -> bool:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        print(f"[formal-parity] missing required tool(s): {', '.join(missing)}", file=sys.stderr)
        return False
    return True


def find_tool(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path is not None:
            return path
    return None


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_sources(manifest: Path, sources: list[str]) -> list[Path]:
    base = manifest.parent
    resolved = [(base / source).resolve() for source in sources]
    missing = [source for source in resolved if not source.exists()]
    if missing:
        raise FileNotFoundError(", ".join(str(source) for source in missing))
    return resolved


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"--[^\n]*", "", text)


def parse_verilog_ports(text: str, top: str) -> dict[str, Port]:
    text = strip_comments(text)
    module_match = re.search(rf"\bmodule\s+{re.escape(top)}\b", text)
    if module_match is None:
        raise ValueError(f"Verilog module {top!r} not found")

    i = module_match.end()
    while i < len(text) and text[i].isspace():
        i += 1
    if i < len(text) and text[i] == "#":
        i += 1
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text) or text[i] != "(":
            raise ValueError(f"malformed parameter list for Verilog module {top!r}")
        depth = 1
        i += 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text) or text[i] != "(":
        raise ValueError(f"port list for Verilog module {top!r} not found")

    start = i + 1
    depth = 1
    i += 1
    while i < len(text) and depth:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    body = text[start : i - 1]

    ports: dict[str, Port] = {}
    current_direction: str | None = None
    for item in body.split(","):
        item = re.sub(r"\s+", " ", item).strip()
        if not item:
            continue
        direction_match = re.match(r"^(input|output|inout)\b(.*)$", item)
        if direction_match:
            current_direction = direction_match.group(1)
            item = direction_match.group(2).strip()
        if current_direction is None:
            continue
        item = re.sub(r"\[[^\]]+\]", " ", item)
        item = re.sub(r"\b(?:wire|reg|logic|signed)\b", " ", item)
        item = re.sub(r"=.*$", "", item)
        names = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", item)
        if names:
            ports[names[-1]] = Port(names[-1], current_direction)
    return ports


def parse_vhdl_ports(text: str, top: str) -> dict[str, Port]:
    body_match = re.search(
        rf"\bentity\s+{re.escape(top)}\s+is\b(.*?)\bend\b",
        strip_comments(text),
        re.S | re.I,
    )
    if body_match is None:
        raise ValueError(f"VHDL entity {top!r} not found")
    port_match = re.search(r"\bport\s*\((.*)\)\s*;", body_match.group(1), re.S | re.I)
    if port_match is None:
        return {}
    ports: dict[str, Port] = {}
    for decl in port_match.group(1).split(";"):
        match = re.match(r"\s*([\w\s,]+?)\s*:\s*(in|out|inout)\b", decl, re.I)
        if not match:
            continue
        direction = {"in": "input", "out": "output", "inout": "inout"}[match.group(2).lower()]
        for name in re.split(r"\s*,\s*", match.group(1).strip()):
            ports[name] = Port(name, direction)
    return ports


def check_interface(manifest_path: Path, manifest: dict[str, Any]) -> bool:
    print(f"[formal-parity] Layer 0 interface: {manifest['name']}")
    parsers = {"verilog": parse_verilog_ports, "vhdl": parse_vhdl_ports}
    parsed: dict[str, dict[str, Port]] = {}
    for side in ("golden", "candidate"):
        spec = manifest[side]
        text = "\n".join(
            source.read_text(encoding="utf-8", errors="ignore")
            for source in resolve_sources(manifest_path, spec["sources"])
        )
        parsed[side] = parsers[spec["language"].lower()](text, spec["top"])

    ok = True
    golden_ports = parsed["golden"]
    candidate_ports = parsed["candidate"]
    for name in sorted(set(golden_ports) | set(candidate_ports)):
        if name not in golden_ports:
            print(f"  FAIL {name}: missing from golden")
            ok = False
        elif name not in candidate_ports:
            print(f"  FAIL {name}: missing from candidate")
            ok = False
        elif golden_ports[name].direction != candidate_ports[name].direction:
            print(
                f"  FAIL {name}: direction {golden_ports[name].direction} "
                f"!= {candidate_ports[name].direction}"
            )
            ok = False
    if ok:
        print(f"  PASS {len(golden_ports)} port(s) match by name and direction")
    return ok


def param_int(value: int | str) -> int:
    """A manifest parameter as an integer; a string is a vector's bits, MSB first."""
    return int(value, 2) if isinstance(value, str) else int(value)


def ghdl_generic(value: int | str) -> str:
    # GHDL takes a vector generic override only as a bit string.
    return value if isinstance(value, str) else str(int(value))


def ghdl_synth(
    manifest_path: Path,
    side: dict[str, Any],
    params: dict[str, int],
    work: Path,
    out: Path,
) -> bool:
    sources = resolve_sources(manifest_path, side["sources"])
    std = str(side.get("std", "08"))
    work.mkdir(parents=True, exist_ok=True)
    for source in sources:
        code, _ = run(
            ["ghdl", "-a", f"--std={std}", f"--workdir={work}", str(source)],
        )
        if code != 0:
            return False
    generics = [f"-g{name}={ghdl_generic(value)}" for name, value in params.items()]
    synth_options = [str(opt) for opt in side.get("synth_options", [])]
    code, output_text = run(
        [
            "ghdl",
            "--synth",
            f"--std={std}",
            f"--workdir={work}",
            "--out=verilog",
            *synth_options,
            *generics,
            side["top"],
        ],
        output=out,
    )
    return code == 0 and "error:" not in output_text.lower()


def normalize_ghdl_isignal_aliases(netlist: Path) -> None:
    """Rename GHDL's hidden ``nNNN`` state registers back to signal names.

    GHDL emits many VHDL signals as a public combinational alias driven by an
    anonymous state register, e.g. ``foo = n1234; // (isignal)``. Yosys then
    sees the real flop as ``n1234`` and cannot line it up with the Verilog
    state named ``foo`` during induction. This pass keeps the synthesized logic
    identical while restoring those state names for SEC.
    """

    text = netlist.read_text(encoding="utf-8")
    reg_decl_re = re.compile(
        r"^\s*reg(?P<width>\s+\[[^\]]+\])?\s+(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\s*;",
        re.M,
    )
    reg_widths = {
        match.group("name"): (match.group("width") or "")
        for match in reg_decl_re.finditer(text)
    }
    alias_re = re.compile(
        r"^\s*always @\*\n"
        r"\s*(?P<public>[A-Za-z_][A-Za-z0-9_$]*)\s*=\s*"
        r"(?P<hidden>n\d+)\s*;\s*// \(isignal\)\n",
        re.M,
    )

    rename: dict[str, str] = {}
    for match in alias_re.finditer(text):
        public = match.group("public")
        hidden = match.group("hidden")
        if (
            public in reg_widths
            and hidden in reg_widths
            and public != hidden
            and reg_widths[public] == reg_widths[hidden]
        ):
            rename.setdefault(hidden, public)

    if not rename:
        return

    for hidden, public in rename.items():
        text = re.sub(
            rf"(?<![A-Za-z0-9_$]){re.escape(hidden)}(?![A-Za-z0-9_$])",
            public,
            text,
        )

    text = re.sub(
        r"^\s*always @\*\n"
        r"\s*(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(?P=name)\s*;\s*"
        r"// \(isignal\)\n",
        "",
        text,
        flags=re.M,
    )

    seen_regs: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        match = reg_decl_re.match(line)
        if match:
            name = match.group("name")
            if name in seen_regs:
                continue
            seen_regs.add(name)
        lines.append(line)
    netlist.write_text("\n".join(lines) + "\n", encoding="utf-8")


def yosys_read_verilog(
    side: dict[str, Any],
    sources: list[Path],
    params: dict[str, int],
) -> list[str]:
    joined = " ".join(source.as_posix() for source in sources)
    cmds = [f"read_verilog -sv -defer -I{RTL.as_posix()} {joined}"]
    if params:
        sets = " ".join(f"-set {name} {param_int(value)}" for name, value in params.items())
        cmds.append(f"chparam {sets} {side['top']}")
    cmds.append(f"hierarchy -check -top {side['top']}")
    return cmds


def prep_side(
    read_cmds: list[str],
    top: str,
    name: str,
    renames: dict[str, str] | None = None,
) -> list[str]:
    rename_cmds: list[str] = []
    if renames:
        rename_cmds.append(f"cd {top}")
        rename_cmds.extend(
            f"rename {old_name} {new_name}"
            for old_name, new_name in renames.items()
        )
        rename_cmds.append("cd")
    return [
        "design -reset",
        *read_cmds,
        f"hierarchy -top {top}",
        "proc",
        "flatten",
        "memory_map",
        *rename_cmds,
        "async2sync",
        "setundef -zero",
        "opt -full",
        f"rename {top} {name}",
        f"design -stash {name}",
    ]


_FF_TYPES = {
    "$dff", "$dffe", "$adff", "$adffe", "$sdff", "$sdffe", "$sdffce",
    "$aldff", "$aldffe", "$dffsr", "$dffsre",
}


# Init attribute name while the init check runs proc; see check_init_parity.
_INIT_ATTR = "fcapz_init"


def ff_init_bits(json_path: Path, top: str) -> dict[tuple[str, int], str]:
    """``(register, bit) -> init value`` for one design: ``"0"``, ``"1"`` or
    ``"x"``.

    A flip-flop without an init powers up at 0 on the FPGAs fcapz targets, so
    a missing init reads as ``"0"``.
    """
    module = json.loads(json_path.read_text(encoding="utf-8"))["modules"][top]
    q_bits: set[int] = set()
    for cell in module["cells"].values():
        if cell["type"] in _FF_TYPES:
            q_bits.update(bit for bit in cell["connections"]["Q"] if isinstance(bit, int))
    # The init can sit on any net of the bit: GHDL puts it either on its own
    # state register (``n123_q``) or on the signal that aliases it.
    bit_init: dict[int, str] = {}
    for net in module["netnames"].values():
        init = net.get("attributes", {}).get("init")
        if isinstance(init, str) and len(init) == len(net["bits"]):
            for bit, value in zip(net["bits"], reversed(init)):
                if isinstance(bit, int) and value in ("0", "1", "x"):
                    bit_init.setdefault(bit, value)
    bits: dict[tuple[str, int], str] = {}
    for name, net in module["netnames"].items():
        if net.get("hide_name"):
            continue
        for index, bit in enumerate(net["bits"]):
            if bit in q_bits:
                bits[(name, index)] = bit_init.get(bit, "0")
    return bits


def check_init_parity(
    gold_read: list[str],
    gate_read: list[str],
    golden: dict[str, Any],
    candidate: dict[str, Any],
    manifest: dict[str, Any],
    work: Path,
    yosys: str,
) -> str | None:
    """Compare the state the two sides start the proofs from.

    Both proofs leave power-up state unchecked: ``equiv_induct`` matches
    registers by name and assumes their states equal, and the bounded proof
    starts after ``reset_cycles`` of reset.  So this compares every register
    the two sides share by name after that same reset, with every other input
    held at 0.  A register the reset clears is equal either way; one it does
    not clear (a counter, a synchroniser fed by a non-reset input) keeps its
    power-up value, which the two sides must agree on.  That a reset is
    asserted at power-up is the wrappers' contract: their ``reset_sync``
    powers up asserted.  ``reset_sync`` itself is checked raw, with
    ``"init_after_reset": false`` in its manifest, since its power-up value is
    that contract.  A register left undefined after the reset is reported:
    the check cannot compare it.  Returns a failure message, or ``None``.
    """
    formal = manifest.get("formal", {})
    reset_inputs = formal.get("reset_inputs", [])
    reset_cycles = int(formal.get("reset_cycles", 0))
    clock_inputs = formal.get("clock_inputs", [])
    reset_sim: list[str] = []
    if reset_inputs and reset_cycles and formal.get("init_after_reset", True):
        reset_sim.append(
            "sim -zinit -w"
            + "".join(f" -clock {clock}" for clock in clock_inputs)
            + "".join(f" -reset {reset}" for reset in reset_inputs)
            + f" -rstlen {reset_cycles} -n {reset_cycles}"
        )
    sides = {}
    for name, read_cmds, side in (
        ("gold", gold_read, golden),
        ("gate", gate_read, candidate),
    ):
        out = work / f"init_{name}.json"
        renames = side.get("state_renames") or {}
        script = "\n".join(
            [
                "design -reset",
                *read_cmds,
                f"hierarchy -top {side['top']}",
                # proc drops an init it finds on a combinationally driven
                # signal, which is where GHDL puts the init of an async-reset
                # flop.  Move each init to its own attribute first.
                "proc_clean",
                "proc_rmdead",
                "proc_prune",
                "proc_init",
                f"attrmap -rename init {_INIT_ATTR}",
                "proc",
                "flatten",
                # As in the proofs; sim cannot run unmapped memories.
                "memory_map",
                *([f"cd {side['top']}"] if renames else []),
                *(f"rename {old} {new}" for old, new in renames.items()),
                *(["cd"] if renames else []),
                "opt_clean",
                f"attrmap -rename {_INIT_ATTR} init",
                *(
                    [
                        # Hold every input but the clocks and resets at 0.
                        "delete -port "
                        + " ".join(
                            [f"{side['top']}/i:*"]
                            + [
                                f"{side['top']}/w:{port} %d"
                                for port in (*clock_inputs, *reset_inputs)
                            ]
                        ),
                        "setundef -zero -undriven",
                        *reset_sim,
                    ]
                    if reset_sim
                    else []
                ),
                f"write_json {out.as_posix()}",
            ]
        ) + "\n"
        _, output = run([yosys, "-"], input_text=script)
        if not out.exists():
            return "init check could not write the netlist: " + next(
                (line for line in output.splitlines() if "ERROR:" in line), "yosys failed"
            )
        sides[name] = ff_init_bits(out, side["top"])

    gold, gate = sides["gold"], sides["gate"]
    undefined = sorted(
        f"{name}[{index}]"
        for name, index in gold.keys() & gate.keys()
        if "x" in (gold[(name, index)], gate[(name, index)])
    )
    if undefined:
        shown = ", ".join(undefined[:8])
        more = f" (+{len(undefined) - 8} more)" if len(undefined) > 8 else ""
        return f"registers undefined after the reset: {shown}{more}"
    mismatches = [
        f"{name}[{index}] {gold[(name, index)]}/{gate[(name, index)]}"
        for name, index in sorted(gold.keys() & gate.keys())
        if gold[(name, index)] != gate[(name, index)]
    ]
    if mismatches:
        shown = ", ".join(mismatches[:8])
        more = f" (+{len(mismatches) - 8} more)" if len(mismatches) > 8 else ""
        return f"power-up values differ (Verilog/VHDL): {shown}{more}"
    return None


def prove_config(
    manifest_path: Path,
    manifest: dict[str, Any],
    params: dict[str, int],
    work: Path,
    induct_depth: int,
    bounded_depth: int,
    yosys: str,
) -> tuple[str, str]:
    golden = manifest["golden"]
    candidate = manifest["candidate"]
    vhdl_netlist = work / f"{manifest['name']}_{len(params)}_candidate.v"
    vhdl_work = work / "ghdl"
    if not ghdl_synth(manifest_path, candidate, params, vhdl_work, vhdl_netlist):
        return "FAIL", "GHDL synthesis failed"
    normalize_ghdl_isignal_aliases(vhdl_netlist)

    gold_read = yosys_read_verilog(
        golden,
        resolve_sources(manifest_path, golden["sources"]),
        params,
    )
    gate_read = yosys_read_verilog(candidate, [vhdl_netlist], {})
    init_error = check_init_parity(
        gold_read, gate_read, golden, candidate, manifest, work, yosys
    )
    if init_error is not None:
        return "FAIL", init_error
    script = "\n".join(
        [
            *prep_side(
                gold_read,
                golden["top"],
                "gold",
                golden.get("state_renames"),
            ),
            *prep_side(
                gate_read,
                candidate["top"],
                "gate",
                candidate.get("state_renames"),
            ),
            "design -reset",
            "design -copy-from gold -as gold gold",
            "design -copy-from gate -as gate gate",
            "equiv_make gold gate equiv",
            "hierarchy -top equiv",
            "clean -purge",
            "opt -full",
            "equiv_struct",
            "equiv_simple",
            f"equiv_induct -undef -seq {induct_depth}",
            "equiv_status",
        ]
    ) + "\n"
    _, output = run([yosys, "-"], input_text=script)
    if "Equivalence successfully proven" in output:
        return "PASS", "equiv_induct closed"
    if "ERROR:" in output:
        error = next(line for line in output.splitlines() if "ERROR:" in line)
        return "FAIL", error

    unproven = re.search(r"Found a total of (\d+) unproven", output) or re.search(
        r"(\d+) are unproven",
        output,
    )
    count = unproven.group(1) if unproven else "?"
    if bounded_depth <= 0:
        return "FAIL", f"{count} unproven equivalence point(s)"

    reset_inputs = manifest.get("formal", {}).get("reset_inputs", [])
    reset_cycles = int(manifest.get("formal", {}).get("reset_cycles", 0))
    clock_inputs = manifest.get("formal", {}).get("clock_inputs", [])
    zero_inputs = manifest.get("formal", {}).get("zero_inputs", [])
    reset_args: list[str] = []
    for cycle in range(1, bounded_depth + 1):
        for clock in clock_inputs:
            reset_args.extend(["-set-at", str(cycle), f"in_{clock}", "1"])
        for signal in zero_inputs:
            reset_args.extend(["-set-at", str(cycle), f"in_{signal}", "0"])
    for cycle in range(1, reset_cycles + 1):
        for reset in reset_inputs:
            reset_args.extend(["-set-at", str(cycle), f"in_{reset}", "1"])
    if reset_cycles:
        for cycle in range(reset_cycles + 1, bounded_depth + 1):
            for reset in reset_inputs:
                reset_args.extend(["-set-at", str(cycle), f"in_{reset}", "0"])
        reset_args.extend(["-prove-skip", str(reset_cycles)])
    dump_vcd = os.environ.get("FORMAL_PARITY_DUMP_VCD")
    dump_args = f" -dump_vcd {Path(dump_vcd).as_posix()}" if dump_vcd else ""
    show_extra = os.environ.get("FORMAL_PARITY_SHOW", "")
    show_args = "".join(
        f" -show {signal.strip()}"
        for signal in show_extra.split(",")
        if signal.strip()
    )

    bounded = "\n".join(
        [
            *prep_side(
                gold_read,
                golden["top"],
                "gold",
                golden.get("state_renames"),
            ),
            *prep_side(
                gate_read,
                candidate["top"],
                "gate",
                candidate.get("state_renames"),
            ),
            "design -reset",
            "design -copy-from gold -as gold gold",
            "design -copy-from gate -as gate gate",
            "miter -equiv -make_assert -make_outputs -make_outcmp -flatten gold gate miter",
            "hierarchy -top miter",
            "opt -full",
            "sat "
            f"-seq {bounded_depth} "
            "-set-init-zero "
            + " ".join(reset_args)
            + f" -prove-asserts -show-ports{show_args}{dump_args}",
        ]
    ) + "\n"
    _, bounded_output = run([yosys, "-"], input_text=bounded)
    if "no model found" in bounded_output:
        return (
            "BOUNDED",
            f"{count} unproven point(s), no counterexample within {bounded_depth} cycles",
        )
    return (
        "FAIL",
        f"{count} unproven point(s), bounded check did not prove equivalence",
    )


def run_manifest(manifest_path: Path) -> bool:
    manifest = load_manifest(manifest_path)
    ok = check_interface(manifest_path, manifest)
    formal = manifest.get("formal")
    if formal is None:
        # A composition of cores that each have their own proof; its
        # behavior is covered by the shared cocotb regression.
        print(f"[formal-parity] {manifest['name']}: interface only, no proof configured")
        return ok
    induct_depth = int(formal.get("induct_depth", 20))
    bounded_depth = int(formal.get("bounded_depth", 0))
    yosys = find_tool("yosys", "yowasp-yosys")
    if yosys is None:
        print("[formal-parity] missing required tool(s): yosys or yowasp-yosys", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory(prefix=".formal_hdl_", dir=ROOT) as tmp:
        work = Path(tmp)
        for module in formal["modules"]:
            for params in module.get("param_sets") or [{}]:
                tag = ", ".join(f"{name}={value}" for name, value in params.items()) or "default"
                status, detail = prove_config(
                    manifest_path,
                    manifest,
                    params,
                    work,
                    induct_depth,
                    bounded_depth,
                    yosys,
                )
                print(
                    f"[formal-parity] {manifest['name']} {module['name']}[{tag}]: "
                    f"{status} - {detail}"
                )
                if status != "PASS":
                    ok = False
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="*", type=Path, help="manifest(s) to run")
    parser.add_argument(
        "--interface-only",
        action="store_true",
        help="only run Layer 0 manifest/interface checks",
    )
    args = parser.parse_args()

    manifests = tuple(args.manifest) if args.manifest else DEFAULT_MANIFESTS
    try:
        loaded = [(path, load_manifest(path)) for path in manifests]
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[formal-parity] manifest error: {exc}", file=sys.stderr)
        sys.exit(1)

    ok = True
    for path, manifest in loaded:
        ok &= check_interface(path, manifest)

    if args.interface_only:
        if not ok:
            sys.exit(1)
        print(f"[formal-parity] interface checks passed for {len(loaded)} manifest(s).")
        return

    if not require_tools("ghdl") or find_tool("yosys", "yowasp-yosys") is None:
        if find_tool("yosys", "yowasp-yosys") is None:
            print(
                "[formal-parity] missing required tool(s): yosys or yowasp-yosys",
                file=sys.stderr,
            )
        sys.exit(1)

    ok = True
    for path, _manifest in loaded:
        ok &= run_manifest(path)

    if not ok:
        sys.exit(1)
    print(f"[formal-parity] formal parity passed for {len(loaded)} manifest(s).")


if __name__ == "__main__":
    main()
