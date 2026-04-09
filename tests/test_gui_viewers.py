# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from fcapz.gui.viewers import (
    CustomCommandViewer,
    GtkWaveViewer,
    SurferViewer,
    WaveTraceViewer,
    available_builtin_viewers,
    default_viewer_factories,
    viewer_by_name,
)

pytestmark = pytest.mark.gui


class TestGtkWaveViewer(unittest.TestCase):
    def test_open_invokes_gtkwave_with_vcd(self) -> None:
        vcd = Path("dump.vcd")
        vcd.write_text("$timescale\n", encoding="utf-8")
        try:
            exe = Path("/opt/bin/gtkwave")
            viewer = GtkWaveViewer(executable=exe)
            with patch("fcapz.gui.viewers.subprocess.Popen") as popen:
                viewer.open(vcd)
            popen.assert_called_once()
            args, kwargs = popen.call_args
            self.assertEqual(args[0], [str(exe), str(vcd)])
            self.assertEqual(kwargs.get("start_new_session"), True)
        finally:
            vcd.unlink()

    def test_open_with_save_file(self) -> None:
        vcd = Path("dump2.vcd")
        gtkw = Path("layout.gtkw")
        vcd.write_text("!", encoding="utf-8")
        gtkw.write_text("!", encoding="utf-8")
        try:
            exe = Path("/gw/gtkwave")
            viewer = GtkWaveViewer(executable=exe)
            with patch("fcapz.gui.viewers.subprocess.Popen") as popen:
                viewer.open(vcd, save_file=gtkw)
            popen.assert_called_once()
            self.assertEqual(
                popen.call_args[0][0],
                [str(exe), str(vcd), "--save", str(gtkw)],
            )
        finally:
            vcd.unlink()
            gtkw.unlink()

    def test_open_missing_vcd_raises(self) -> None:
        viewer = GtkWaveViewer(executable=Path("/bin/gtkwave"))
        with self.assertRaises(FileNotFoundError):
            viewer.open(Path("nonexistent.vcd"))


class TestSurferAndWaveTrace(unittest.TestCase):
    def test_surfer_rejects_save_file(self) -> None:
        vcd = Path("s.vcd")
        vcd.write_text("x", encoding="utf-8")
        try:
            viewer = SurferViewer(executable=Path("/bin/surfer"))
            with self.assertRaises(ValueError):
                viewer.open(vcd, save_file=Path("x.surf"))
        finally:
            vcd.unlink()

    def test_surfer_open(self) -> None:
        vcd = Path("s2.vcd")
        vcd.write_text("x", encoding="utf-8")
        try:
            exe = Path("/surfer")
            viewer = SurferViewer(executable=exe)
            with patch("fcapz.gui.viewers.subprocess.Popen") as popen:
                viewer.open(vcd)
            self.assertEqual(popen.call_args[0][0], [str(exe), str(vcd)])
        finally:
            vcd.unlink()


class TestCustomCommandViewer(unittest.TestCase):
    def test_placeholder_expansion(self) -> None:
        vcd = Path("c.vcd")
        sav = Path("c.save")
        vcd.write_text("v", encoding="utf-8")
        sav.write_text("s", encoding="utf-8")
        try:
            viewer = CustomCommandViewer(["tool", "-f", "{VCD}", "-o", "{SAVE}"])
            with patch("fcapz.gui.viewers.subprocess.Popen") as popen:
                viewer.open(vcd, save_file=sav)
            self.assertEqual(
                popen.call_args[0][0],
                ["tool", "-f", str(vcd), "-o", str(sav)],
            )
        finally:
            vcd.unlink()
            sav.unlink()

    def test_save_required_when_template_has_save(self) -> None:
        vcd = Path("c2.vcd")
        vcd.write_text("v", encoding="utf-8")
        try:
            viewer = CustomCommandViewer(["x", "{VCD}", "{SAVE}"])
            with self.assertRaises(ValueError):
                viewer.open(vcd)
        finally:
            vcd.unlink()


class TestRegistry(unittest.TestCase):
    def test_default_factories_are_callable(self) -> None:
        factories = default_viewer_factories()
        self.assertEqual(len(factories), 3)
        for f in factories:
            r = f()
            self.assertTrue(r is None or hasattr(r, "open"))

    @patch.object(GtkWaveViewer, "detect_executable", return_value=None)
    @patch.object(SurferViewer, "detect_executable", return_value=None)
    @patch.object(WaveTraceViewer, "detect_executable", return_value=None)
    def test_available_empty_when_no_path(self, _wt, _sf, _gw) -> None:
        self.assertEqual(available_builtin_viewers(), [])

    def test_viewer_by_name_custom(self) -> None:
        v = viewer_by_name("custom", custom_argv=["echo", "{VCD}"])
        self.assertIsInstance(v, CustomCommandViewer)

    def test_viewer_by_name_unknown(self) -> None:
        with self.assertRaises(KeyError):
            viewer_by_name("nosuchviewer")


if __name__ == "__main__":
    unittest.main()
