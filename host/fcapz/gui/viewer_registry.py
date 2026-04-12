# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Resolve waveform viewer instances from GUI settings and PATH."""

from __future__ import annotations

from .settings import GuiSettings, viewer_executable_override
from .viewers import (
    CustomCommandViewer,
    GtkWaveViewer,
    SurferViewer,
    WaveTraceViewer,
    WaveformViewer,
)

_BuiltinViewer = type[GtkWaveViewer] | type[SurferViewer] | type[WaveTraceViewer]


def viewers_for_settings(settings: GuiSettings) -> list[tuple[str, WaveformViewer]]:
    """Label + viewer instance for the history-panel dropdown."""
    out: list[tuple[str, WaveformViewer]] = []
    triples: list[tuple[str, _BuiltinViewer, str]] = [
        ("GTKWave", GtkWaveViewer, "gtkwave"),
        ("Surfer", SurferViewer, "surfer"),
        ("WaveTrace", WaveTraceViewer, "wavetrace"),
    ]
    for label, cls, ovr_key in triples:
        ovr = viewer_executable_override(settings, ovr_key)
        try:
            if ovr is not None:
                out.append((label, cls(executable=ovr)))
            elif cls.detect_executable() is not None:
                out.append((label, cls()))
        except ValueError:
            continue
    if settings.viewers.custom_argv:
        out.append(
            (
                "Custom command",
                CustomCommandViewer(list(settings.viewers.custom_argv)),
            ),
        )
    return out
