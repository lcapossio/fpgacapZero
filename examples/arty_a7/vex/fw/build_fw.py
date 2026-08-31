# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Build the Arty VexRiscv Dhrystone firmware and emit a $readmemh image.

Compiles the freestanding RV32I firmware (boot.S + the Dhrystone port) with a
RISC-V GCC toolchain and packs the result into ``fw.mem`` -- 32-bit
little-endian words, one hex value per line -- which ``vex_cpu.v`` loads into
the on-chip BRAM via ``$readmemh`` at synthesis time.

No hardcoded toolchain paths: the cross toolchain is found from ``$RISCV_PREFIX``
(e.g. ``riscv64-unknown-elf-``) or, failing that, the first known ``*-gcc`` on
``PATH``. Runs standalone or is called by ``build_arty_vex.py`` before Vivado.

    RISCV_PREFIX=riscv64-unknown-elf- python examples/arty_a7/vex/fw/build_fw.py
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

_FW_DIR = Path(__file__).resolve().parent

# RV32I so the base VexRiscv_Lite core (no M extension) runs it; soft mul/div
# come from libgcc. -ffreestanding disables builtins, so our memcpy/strcpy in
# support.c are not turned into self-recursive libcalls, while the compiler
# still lowers Dhrystone's struct copies to memcpy (provided in support.c).
_CFLAGS = [
    "-march=rv32i", "-mabi=ilp32", "-O2",
    "-ffreestanding", "-fno-tree-loop-distribute-patterns",
    "-Wall", "-Wextra", "-std=c11",
    "-ffunction-sections", "-fdata-sections",
]
_SOURCES = ["boot.S", "support.c", "dhry_1.c", "dhry_2.c"]

# Must match the RAM aperture in link.ld / vex_cpu.v (64 KB, 16384 words).
_MEM_WORDS = 16384

_KNOWN_PREFIXES = (
    "riscv64-unknown-elf-",
    "riscv32-unknown-elf-",
    "riscv-none-elf-",
    "riscv64-elf-",
    "riscv32-elf-",
)


def _resolve_prefix() -> str:
    """Return a RISC-V toolchain prefix whose gcc is on PATH, or raise."""
    env = os.environ.get("RISCV_PREFIX")
    candidates = [env] if env else list(_KNOWN_PREFIXES)
    for prefix in candidates:
        if prefix and shutil.which(f"{prefix}gcc"):
            return prefix
    hint = env or " / ".join(_KNOWN_PREFIXES)
    raise SystemExit(
        f"fcapz: no RISC-V gcc found (looked for '{hint}gcc'). "
        "Install a RISC-V GCC toolchain and/or set RISCV_PREFIX, e.g. "
        "RISCV_PREFIX=riscv64-unknown-elf-"
    )


def _run(cmd: list[str]) -> None:
    print("fcapz:", " ".join(cmd))
    subprocess.run(cmd, cwd=_FW_DIR, check=True)


def _pack_mem(bin_path: Path, mem_path: Path) -> None:
    """Pack a raw binary into 32-bit little-endian hex words for $readmemh."""
    data = bin_path.read_bytes()
    if len(data) % 4:
        data += b"\x00" * (4 - len(data) % 4)
    words = len(data) // 4
    if words > _MEM_WORDS:
        raise SystemExit(
            f"fcapz: firmware is {words} words but BRAM holds {_MEM_WORDS} "
            "(64 KB). Reduce firmware size or grow the RAM aperture."
        )
    lines = [f"{struct.unpack('<I', data[i * 4:i * 4 + 4])[0]:08x}"
             for i in range(words)]
    mem_path.write_text("\n".join(lines) + "\n")
    print(f"fcapz: wrote {mem_path.name} ({words} words / {len(data)} bytes)")


def build_firmware(out_dir: Path | None = None) -> Path:
    """Compile + link + pack. Returns the path to fw.mem."""
    prefix = _resolve_prefix()
    cc = f"{prefix}gcc"
    objcopy = f"{prefix}objcopy"
    # Resolve to an absolute path: the compiler runs with cwd=_FW_DIR, so a
    # relative out_dir would otherwise be taken relative to the firmware dir.
    out_dir = Path(out_dir).resolve() if out_dir else _FW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    elf = out_dir / "fw.elf"
    binf = out_dir / "fw.bin"
    mapf = out_dir / "fw.map"
    mem = _FW_DIR / "fw.mem"  # where vex_cpu.v's $readmemh looks

    # --build-id=none: some GCCs (e.g. the Vitis riscv build) emit a
    # .note.gnu.build-id by default, which the bare link script would place at
    # address 0 and collide with .text.init. We do not consume the note.
    link = [cc, *_CFLAGS, "-nostdlib",
            f"-Wl,-T,{_FW_DIR / 'link.ld'}",
            "-Wl,--build-id=none",
            "-Wl,--gc-sections", f"-Wl,-Map,{mapf}",
            "-o", str(elf), *_SOURCES, "-lgcc"]
    _run(link)
    _run([objcopy, "-O", "binary", str(elf), str(binf)])
    _pack_mem(binf, mem)
    return mem


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    build_firmware(Path(out) if out else None)
