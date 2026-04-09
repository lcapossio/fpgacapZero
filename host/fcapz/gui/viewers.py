# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Launch external waveform viewers for captured VCD files."""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar


class WaveformViewer(ABC):
    """Abstract viewer: resolve executable on PATH, then spawn with a VCD path."""

    name: ClassVar[str]
    supports_save_file: ClassVar[bool]

    @staticmethod
    @abstractmethod
    def detect_executable() -> Path | None:
        """Return the viewer binary if found on ``PATH``, else ``None``."""

    @abstractmethod
    def open(self, vcd_path: Path, *, save_file: Path | None = None) -> None:
        """Open ``vcd_path`` in the viewer; optionally pass a layout save file."""

    def _spawn(self, argv: Sequence[str]) -> None:
        subprocess.Popen(list(argv), start_new_session=True)


def _which(*candidates: str) -> Path | None:
    for name in candidates:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


class GtkWaveViewer(WaveformViewer):
    name = "GTKWave"
    supports_save_file = True

    def __init__(self, executable: Path | None = None) -> None:
        exe = executable or self.detect_executable()
        if exe is None:
            raise ValueError("gtkwave not found on PATH")
        self._executable = exe

    @staticmethod
    def detect_executable() -> Path | None:
        return _which("gtkwave")

    def open(self, vcd_path: Path, *, save_file: Path | None = None) -> None:
        if not vcd_path.is_file():
            raise FileNotFoundError(vcd_path)
        cmd = [str(self._executable), str(vcd_path)]
        if save_file is not None:
            cmd += ["--save", str(save_file)]
        self._spawn(cmd)


class SurferViewer(WaveformViewer):
    """Surfer desktop (wgpu/egui); spawned as its own window."""

    name = "Surfer"
    supports_save_file = True

    def __init__(self, executable: Path | None = None) -> None:
        exe = executable or self.detect_executable()
        if exe is None:
            raise ValueError("surfer not found on PATH")
        self._executable = exe

    @staticmethod
    def detect_executable() -> Path | None:
        return _which("surfer")

    def open(self, vcd_path: Path, *, save_file: Path | None = None) -> None:
        if not vcd_path.is_file():
            raise FileNotFoundError(vcd_path)
        if save_file is not None and not save_file.is_file():
            raise FileNotFoundError(save_file)
        cmd = [str(self._executable)]
        if save_file is not None:
            cmd += ["--command-file", str(save_file)]
        cmd.append(str(vcd_path))
        self._spawn(cmd)


class WaveTraceViewer(WaveformViewer):
    name = "WaveTrace"
    supports_save_file = False

    def __init__(self, executable: Path | None = None) -> None:
        exe = executable or self.detect_executable()
        if exe is None:
            raise ValueError("wavetrace not found on PATH")
        self._executable = exe

    @staticmethod
    def detect_executable() -> Path | None:
        return _which("wavetrace", "WaveTrace")

    def open(self, vcd_path: Path, *, save_file: Path | None = None) -> None:
        if save_file is not None:
            raise ValueError("WaveTrace viewer does not support save_file in this binding")
        if not vcd_path.is_file():
            raise FileNotFoundError(vcd_path)
        self._spawn([str(self._executable), str(vcd_path)])


class CustomCommandViewer(WaveformViewer):
    """
    Escape hatch: argv template with ``{VCD}`` and optional ``{SAVE}`` placeholders.

    Example: ``["mytool", "--wave", "{VCD}", "--layout", "{SAVE}"]``
    """

    name = "Custom command"
    supports_save_file = True

    def __init__(self, argv_template: Sequence[str]) -> None:
        if not argv_template:
            raise ValueError("argv_template must not be empty")
        self._argv_template = [str(x) for x in argv_template]

    @staticmethod
    def detect_executable() -> Path | None:
        return None

    def open(self, vcd_path: Path, *, save_file: Path | None = None) -> None:
        if not vcd_path.is_file():
            raise FileNotFoundError(vcd_path)
        if save_file is None and any("{SAVE}" in p for p in self._argv_template):
            raise ValueError("template references {SAVE} but save_file was not provided")
        save_str = str(save_file) if save_file is not None else ""
        cmd = [
            p.replace("{VCD}", str(vcd_path)).replace("{SAVE}", save_str)
            for p in self._argv_template
        ]
        self._spawn(cmd)


BUILTIN_VIEWER_CLASSES: tuple[type[WaveformViewer], ...] = (
    GtkWaveViewer,
    SurferViewer,
    WaveTraceViewer,
)


def default_viewer_factories() -> list[Callable[[], WaveformViewer | None]]:
    """
    Factories for PATH-discoverable viewers. Each returns an instance or ``None``
    if the executable is missing.
    """

    out: list[Callable[[], WaveformViewer | None]] = []

    def _factory(cls: type[WaveformViewer]) -> Callable[[], WaveformViewer | None]:
        def _try() -> WaveformViewer | None:
            if cls.detect_executable() is None:
                return None
            return cls()

        return _try

    for c in BUILTIN_VIEWER_CLASSES:
        out.append(_factory(c))
    return out


def available_builtin_viewers() -> list[WaveformViewer]:
    """Instantiate all viewers whose executables are currently on ``PATH``."""
    found: list[WaveformViewer] = []
    for make in default_viewer_factories():
        v = make()
        if v is not None:
            found.append(v)
    return found


def viewer_by_name(name: str, *, custom_argv: Sequence[str] | None = None) -> WaveformViewer:
    """
    Resolve a viewer by short name (case-insensitive).

    ``custom`` requires ``custom_argv`` (placeholder argv, see :class:`CustomCommandViewer`).
    """

    key = name.strip().lower()
    if key in ("custom", "customcommand"):
        if custom_argv is None:
            raise ValueError("custom viewer requires custom_argv")
        return CustomCommandViewer(custom_argv)
    mapping: dict[str, type[WaveformViewer]] = {
        c.name.lower().replace(" ", ""): c for c in BUILTIN_VIEWER_CLASSES
    }
    cls = mapping.get(key)
    if cls is None:
        raise KeyError(f"unknown viewer {name!r}")
    exe = cls.detect_executable()
    if exe is None:
        raise ValueError(f"{cls.name} not found on PATH")
    return cls()
