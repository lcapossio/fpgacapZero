# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Build a board's VexRiscv firmware and emit a $readmemh image.

Shared by both fpgacapZero board examples. Compiles the freestanding RV32I
firmware -- the shared ``boot.S`` here plus the board's own ``main.c`` (the bus
pattern generator, which differs per board) -- with a RISC-V GCC toolchain and
packs the result into ``fw.mem`` (32-bit little-endian words, one hex value per
line) in the board's firmware directory, where ``vex_cpu.v`` loads it via
``$readmemh`` at synthesis time. The linker script (``link.ld``) is shared too.

No hardcoded toolchain paths: the cross toolchain is found from ``$RISCV_PREFIX``
(e.g. ``riscv64-unknown-elf-``) or, failing that, the first known ``*-gcc`` on
``PATH``. Runs standalone (pass the board firmware dir) or is called by a
per-board build launcher before Vivado/Quartus:

    RISCV_PREFIX=riscv64-unknown-elf- \\
        python examples/common/vexriscv/fw/build_fw.py examples/arty_a7/vex/fw
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# Shared firmware sources live next to this script.
_COMMON_FW_DIR = Path(__file__).resolve().parent
_BOOT_S = _COMMON_FW_DIR / "boot.S"
_LINK_LD = _COMMON_FW_DIR / "link.ld"

# RV32I so the base VexRiscv_Lite core (no M extension) runs it; -ffreestanding
# keeps the compiler from assuming a hosted libc. The pattern generator is pure
# volatile loads/stores, so no libgcc/libc runtime is needed.
_CFLAGS = [
    "-march=rv32i", "-mabi=ilp32", "-O2",
    "-ffreestanding",
    "-Wall", "-Wextra", "-std=c11",
    "-ffunction-sections", "-fdata-sections",
]

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


def _run(cmd: list[str], cwd: Path) -> None:
    print("fcapz:", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


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


def build_firmware(board_fw_dir: Path | str, out_dir: Path | None = None) -> Path:
    """Compile + link + pack a board's firmware. Returns the path to fw.mem.

    ``board_fw_dir`` holds the board's ``main.c`` and receives ``fw.mem`` (where
    that board's ``$readmemh`` looks). ``out_dir`` (default: board_fw_dir) takes
    the intermediate elf/bin/map artefacts.
    """
    board_fw_dir = Path(board_fw_dir).resolve()
    main_c = board_fw_dir / "main.c"
    if not main_c.is_file():
        raise SystemExit(f"fcapz: board firmware source missing: {main_c}")

    prefix = _resolve_prefix()
    cc = f"{prefix}gcc"
    objcopy = f"{prefix}objcopy"
    out_dir = Path(out_dir).resolve() if out_dir else board_fw_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    elf = out_dir / "fw.elf"
    binf = out_dir / "fw.bin"
    mapf = out_dir / "fw.map"
    mem = board_fw_dir / "fw.mem"  # where this board's vex_cpu.v $readmemh looks

    # --build-id=none: some GCCs (e.g. the Vitis riscv build) emit a
    # .note.gnu.build-id by default, which the bare link script would place at
    # address 0 and collide with .text.init. We do not consume the note.
    # cwd=board_fw_dir so "main.c" resolves locally; boot.S/link.ld are shared.
    link = [cc, *_CFLAGS, "-nostdlib",
            f"-Wl,-T,{_LINK_LD}",
            "-Wl,--build-id=none",
            "-Wl,--gc-sections", f"-Wl,-Map,{mapf}",
            "-o", str(elf), str(_BOOT_S), "main.c"]
    _run(link, cwd=board_fw_dir)
    _run([objcopy, "-O", "binary", str(elf), str(binf)], cwd=board_fw_dir)
    _pack_mem(binf, mem)
    return mem


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: build_fw.py <board_fw_dir> [out_dir]\n"
            "  e.g. build_fw.py examples/arty_a7/vex/fw"
        )
    board = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    build_firmware(board, out)
