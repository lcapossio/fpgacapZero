#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Fetch the Forgix bitstream-loader firmware and apply the fcapz bridge patch.

Nothing in the upstream repository is modified: the sources are downloaded to a
local working directory, the vendored patch in this folder is applied there, and
the result is yours to build.  The upstream revision is pinned below so the
patch always applies to the tree it was generated against.

Usage::

    python apply_patch.py [--dest DIR] [--rev REV] [--check]

``--check`` verifies the patch applies without writing the patched files, which
is what CI runs; it still needs network access to fetch the pinned sources.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Upstream: https://bitbucket.org/adiuvo-engineering/forgix_public
# Pinned so the vendored patch keeps applying if upstream moves on.  To retarget
# a newer revision, bump this, re-run with --check, and regenerate the patch if
# it no longer applies.
UPSTREAM_REPO = "adiuvo-engineering/forgix_public"
UPSTREAM_REV = "c1d83e3e6ad10fa1c5a927731b1e4f54e771bf0f"
UPSTREAM_SUBDIR = "BitStream_Loader"

# Only the files the patch touches plus what they need to build.
FILES = (
    "firmware/pico/CMakeLists.txt",
    "firmware/pico/include/board_config.h",
    "firmware/pico/include/crc32.h",
    "firmware/pico/include/fpga_config.h",
    "firmware/pico/include/protocol.h",
    "firmware/pico/src/crc32.c",
    "firmware/pico/src/fpga_config.c",
    "firmware/pico/src/main.c",
    "firmware/pico/src/protocol.c",
)

HERE = Path(__file__).resolve().parent
PATCH = HERE / "0001-fcapz-uart-bridge.patch"


def _raw_url(rev: str, rel: str) -> str:
    return f"https://bitbucket.org/{UPSTREAM_REPO}/raw/{rev}/{UPSTREAM_SUBDIR}/{rel}"


def fetch(rev: str, dest: Path) -> None:
    """Download the pinned upstream sources into *dest*."""
    for rel in FILES:
        url = _raw_url(rev, rel)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
        except urllib.error.URLError as exc:
            raise SystemExit(
                f"failed to fetch {url}\n  {exc}\n"
                "Check network access, or download the repository manually and "
                "point --dest at its BitStream_Loader directory."
            ) from exc
        out.write_bytes(data)
        print(f"  fetched {rel}")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ("git",) + args, cwd=cwd, capture_output=True, text=True
    )


def apply_patch(dest: Path, check_only: bool) -> None:
    if shutil.which("git") is None:
        raise SystemExit("git is required to apply the patch but was not found on PATH")
    if not PATCH.is_file():
        raise SystemExit(f"vendored patch missing: {PATCH}")

    args = ["apply", "--verbose"]
    if check_only:
        args.append("--check")
    args.append(str(PATCH))

    res = _git(*args, cwd=dest)
    if res.returncode != 0:
        raise SystemExit(
            f"patch did not apply cleanly to {dest}\n{res.stderr.strip()}\n"
            f"The pinned revision is {UPSTREAM_REV}; if you changed --rev, the "
            "patch probably needs regenerating against that tree."
        )
    print(res.stderr.strip() or res.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dest",
        type=Path,
        default=HERE / "build" / "forgix_loader",
        help="working directory for the patched sources (default: ./build/forgix_loader)",
    )
    ap.add_argument(
        "--rev", default=UPSTREAM_REV, help=f"upstream revision (default: {UPSTREAM_REV})"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify the patch applies, without keeping the patched tree",
    )
    args = ap.parse_args()

    dest: Path = args.dest
    dest.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {UPSTREAM_REPO}@{args.rev[:12]} into {dest}")
    fetch(args.rev, dest)

    print(f"Applying {PATCH.name}" + (" (check only)" if args.check else ""))
    apply_patch(dest, args.check)

    if args.check:
        print("\nOK: patch applies cleanly.")
        return 0

    print(
        f"\nPatched sources are in {dest}\n"
        "Build them with the Pico SDK, e.g.:\n"
        f"  cmake -S {dest / 'firmware' / 'pico'} -B {dest / 'firmware' / 'pico' / 'build'} \\\n"
        '        -DPICO_SDK_PATH="$PICO_SDK_PATH" -DPICO_BOARD=pico2\n'
        f"  cmake --build {dest / 'firmware' / 'pico' / 'build'}\n"
        "Then flash forge_fpga_loader.uf2 to the RP2354 in BOOTSEL mode."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
