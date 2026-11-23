# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Identities the broker hands out: the target (cable) and the core on it.

A :class:`TargetSpec` is the CLI's global transport options.  Its
:meth:`~TargetSpec.identity` names the physical cable and device, so two
clients that spell the same board differently (hw_server's port left at the
OpenOCD default, an empty usb_blaster device name) share one transport.  The
other options are its :meth:`~TargetSpec.settings`; the runtime refuses a
second client whose settings differ from the transport it already holds.

A :class:`CoreRef` names one core on a target, with the target's image
generation: the count of transport (re)connects in the runtime.  A job that
gives the generation it expects fails with ``ImageChanged`` instead of acting
on a core that may now hold another bitstream.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from typing import Any

# The CLI's global transport options, with their CLI defaults.
TARGET_DEFAULTS: dict[str, Any] = {
    "backend": "hw_server",
    "host": "127.0.0.1",
    "port": 6666,
    "tap": "xc7a100t.tap",
    "hardware": None,
    "quartus_stp": None,
    "tck_mhz": 6.0,
    "serial_port": None,
    "baud": 1_000_000,
    "two_chain_burst": False,
    "burst": False,
    "no_burst": False,
}

_USB_BLASTER_AUTO = ("", "auto", "xc7a100t.tap")
_LOOPBACK = ("", "localhost", "127.0.0.1", "::1", "[::1]")


def _host(host: str) -> str:
    """*host* with the loopback spellings folded into one."""
    h = str(host or "").strip().lower()
    return "127.0.0.1" if h in _LOOPBACK else h


@dataclass(frozen=True)
class TargetSpec:
    backend: str = "hw_server"
    host: str = "127.0.0.1"
    port: int = 6666
    tap: str = "xc7a100t.tap"
    hardware: str | None = None
    quartus_stp: str | None = None
    tck_mhz: float = 6.0
    serial_port: str | None = None
    baud: int = 1_000_000
    two_chain_burst: bool = False
    burst: bool = False
    no_burst: bool = False

    @classmethod
    def from_args(cls, args: Any) -> TargetSpec:
        """The spec of an argparse namespace holding the CLI global options."""
        return cls(**{k: getattr(args, k, v) for k, v in TARGET_DEFAULTS.items()})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetSpec:
        unknown = set(data) - set(TARGET_DEFAULTS)
        if unknown:
            raise ValueError(f"target: unknown fields {sorted(unknown)}")
        return cls(**{**TARGET_DEFAULTS, **data})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def resolved(self) -> TargetSpec:
        """This spec with its paths made absolute, for the runtime, whose
        working directory is not the caller's.  A bare program name
        (``quartus_stp``) is left to the search path."""
        stp = self.quartus_stp
        if stp and not os.path.isabs(stp) and (
            os.sep in stp or (os.altsep and os.altsep in stp)
        ):
            return replace(self, quartus_stp=os.path.abspath(stp))
        return self

    def identity(self) -> tuple:
        """The physical cable and device, with the CLI's defaults resolved."""
        b = self.backend
        if b == "serial":
            return (b, str(self.serial_port or "").strip())
        if b == "ftdi":
            return (b, self.hardware or None)
        if b == "usb_blaster":
            tap = "auto" if self.tap in _USB_BLASTER_AUTO else self.tap
            return (b, self.hardware or None, tap)
        if b == "hw_server":
            port = 3121 if self.port == 6666 else self.port
            return (b, _host(self.host), port, self.tap.removesuffix(".tap"))
        return (b, _host(self.host), self.port, self.tap)

    def auto_selected(self) -> bool:
        """Whether a local USB backend picks its adapter itself (no
        ``hardware`` given): it may be the same cable as a named one."""
        return self.backend in ("ftdi", "usb_blaster") and not self.hardware

    def key(self) -> str:
        """:meth:`identity` as a string, for logs, status and CoreRefs."""
        return ":".join("" if part is None else str(part) for part in self.identity())

    def settings(self) -> tuple:
        """The options that are not the identity: how the cable is driven."""
        if self.backend == "serial":
            return (self.baud,)
        if self.backend == "ftdi":
            return (self.tap, self.tck_mhz, self.burst, self.no_burst, self.two_chain_burst)
        if self.backend == "usb_blaster":
            return (self.quartus_stp, self.no_burst)
        if self.backend == "openocd":
            return (self.burst, self.no_burst, self.two_chain_burst)
        return (self.no_burst, self.two_chain_burst)


@dataclass(frozen=True)
class CoreRef:
    """One core on a target, as the runtime knows it."""

    authority: str      # who runs operations on it: "local:<runtime id>"
    target: str         # TargetSpec.key()
    kind: str           # "ela", "eio" or "axi"
    chain: int
    slot: int | None    # core-manager slot, None without a manager
    image_gen: int      # target (re)connect count in the runtime

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoreRef:
        return cls(**data)

    def __str__(self) -> str:
        slot = "" if self.slot is None else f" slot {self.slot}"
        return f"{self.kind} chain {self.chain}{slot} on {self.target} (image {self.image_gen})"
