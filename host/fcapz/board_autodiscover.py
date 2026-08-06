# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Auto-discover fpgacapZero-compatible boards behind OpenOCD.

The web UI's "Connect" should not make the user pick a JTAG config. This module
turns the allow-listed OpenOCD configs (see :mod:`fcapz.openocd_launcher`) into a
list of *confirmed* boards with a two-stage strategy:

1. **USB filter** — read each config's ``ftdi vid_pid`` and keep only the
   configs whose adapter is actually plugged in (best-effort USB enumeration).
   A config with no parseable ``vid_pid`` (e.g. one that ``source``\\ s an
   adapter file) is always a candidate — we cannot rule it out, so we probe it.
   If USB enumeration is unavailable, *every* config is a candidate.
2. **Probe** — for each surviving config, start OpenOCD on its own TCL port and
   ask :func:`fcapz.analyzer.discover_boards` whether a compatible fpgacapZero
   core answers. Keep the instance running and tag the board with its config on
   success; stop the instance on failure.

Everything degrades gracefully: missing ``pyusb``, unparseable configs, adapters
already claimed by another OpenOCD — each just narrows or skips a candidate
rather than raising. Two configs that share a VID/PID (an ambiguous adapter)
disambiguate naturally: the first OpenOCD claims the adapter, the second fails
to start and is skipped.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .analyzer import discover_boards

VidPid = Tuple[int, int]

# Sentinel: "run a live USB scan" (distinct from ``None`` = "skip filtering").
_AUTO = object()

# ``ftdi vid_pid 0x0403 0x6010`` (0.11+) or the legacy ``ftdi_vid_pid``; either
# may list several VID/PID pairs on one line.
_VID_PID_RE = re.compile(r"ftdi[ _]vid_pid\b(.*)", re.IGNORECASE)
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")


def parse_cfg_vid_pids(path: str) -> Set[VidPid]:
    """Extract every ``(vid, pid)`` an OpenOCD config names via ``ftdi vid_pid``.

    Returns an empty set when the file is unreadable or names no VID/PID (e.g.
    it defers the adapter to a ``source``\\ d file) — callers treat empty as
    "unknown, cannot filter out".
    """
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return set()
    pairs: Set[VidPid] = set()
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        m = _VID_PID_RE.search(stripped)
        if not m:
            continue
        nums = [int(h, 16) for h in _HEX_RE.findall(m.group(1))]
        # Pairs are (vid, pid) in order; ignore a dangling trailing value.
        for i in range(0, len(nums) - 1, 2):
            pairs.add((nums[i], nums[i + 1]))
    return pairs


def enumerate_usb_ids() -> Optional[Set[VidPid]]:
    """Best-effort set of ``(vid, pid)`` for every attached USB device.

    Returns ``None`` when enumeration is unavailable (no ``pyusb``, no backend,
    or it errors) — the caller must then treat every config as a candidate
    rather than filtering, since "we don't know" must not hide a real board.
    """
    try:
        import usb.core  # type: ignore
    except Exception:
        return None
    try:
        devices = usb.core.find(find_all=True)
        ids = {(int(d.idVendor), int(d.idProduct)) for d in devices}
        return ids or None
    except Exception:
        return None


def candidate_configs(
    configs: Dict[str, str],
    present_usb: Optional[Set[VidPid]],
) -> List[str]:
    """Config names worth probing, given the plugged-in USB adapters.

    Keeps a config when its adapter is present, when it names no VID/PID (can't
    be excluded), or when USB enumeration failed (``present_usb is None``).
    """
    if present_usb is None:
        return sorted(configs)
    keep: List[str] = []
    for name in sorted(configs):
        vps = parse_cfg_vid_pids(configs[name])
        if not vps or (vps & present_usb):
            keep.append(name)
    return keep


def auto_discover_boards(
    launcher,
    *,
    present_usb=_AUTO,
    port_base: int = 6666,
    chain: int = 1,
    wait_sec: float = 10.0,
    timeout_sec: float = 5.0,
) -> List[Dict]:
    """Filter configs by USB, probe the survivors, return confirmed boards.

    Each confirmed board is a :func:`fcapz.analyzer.discover_boards` dict with an
    added ``config`` key (the OpenOCD config that reached it); its ``port`` is a
    still-running instance the caller can connect to directly. Instances that
    turn up no compatible board are stopped again.

    ``present_usb`` defaults to a live USB scan; pass an explicit set (or
    ``None`` to skip filtering) to make the scan deterministic in tests.
    """
    if present_usb is _AUTO:
        present_usb = enumerate_usb_ids()

    configs = launcher.configs
    names = candidate_configs(configs, present_usb)

    confirmed: List[Dict] = []
    port = port_base
    for name in names:
        if port > 65535:
            break
        started_here = False
        try:
            result = launcher.start(name=name, port=port, wait_sec=wait_sec)
            started_here = bool(result.get("started"))
            boards = discover_boards(
                host="127.0.0.1",
                ports=[port],
                chain=chain,
                timeout_sec=timeout_sec,
            )
        except Exception:
            # Adapter busy / not this config / OpenOCD failed — skip it. Only
            # stop what this pass spawned; never touch a foreign instance.
            _safe_stop(launcher, port)
            port += 1
            continue

        if boards:
            for b in boards:
                entry = dict(b)
                entry["config"] = name
                confirmed.append(entry)
            # Leave this instance running so the client can connect to `port`.
            port += 1
        else:
            if started_here:
                _safe_stop(launcher, port)
            port += 1
    return confirmed


def _safe_stop(launcher, port: int) -> None:
    try:
        launcher.stop(port=port)
    except Exception:
        pass
