#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Generate the bundled AXI-monitor ``.prob`` sidecars from the single-source
layout in :mod:`fcapz.axi_layout`.

Run after changing the AXI capture-vector layout::

    python tools/gen_axi_probes.py           # rewrite the .prob files
    python tools/gen_axi_probes.py --check    # fail if they are stale (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "host"))

from fcapz.axi_layout import PROBE_MAPS, axi_probes, sample_width  # noqa: E402
from fcapz.probes import probe_file_dict  # noqa: E402

_PROBE_DIR = _ROOT / "host" / "fcapz" / "probes"


def _doc(addr_w: int, data_w: int, decode: bool) -> str:
    probes = axi_probes(addr_w, data_w, decode)
    data = probe_file_dict(
        probes, sample_width=sample_width(addr_w, data_w, decode), core="axi_mon"
    )
    return json.dumps(data, indent=2) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if any file is stale")
    args = ap.parse_args()

    stale = []
    for (addr_w, data_w, decode), stem in PROBE_MAPS.items():
        path = _PROBE_DIR / f"{stem}.prob"
        want = _doc(addr_w, data_w, decode)
        if args.check:
            have = path.read_text(encoding="utf-8") if path.exists() else ""
            if have != want:
                stale.append(path.name)
        else:
            path.write_text(want, encoding="utf-8")
            print(f"wrote {path.relative_to(_ROOT)}")

    if args.check and stale:
        print(f"stale probe files: {', '.join(stale)} — run tools/gen_axi_probes.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
