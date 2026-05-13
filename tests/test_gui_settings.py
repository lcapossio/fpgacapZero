# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from fcapz.analyzer import CaptureConfig, ProbeSpec, SequencerStage, TriggerConfig
from fcapz.gui.settings import (
    GuiSettings,
    ProbeProfile,
    append_trigger_history,
    apply_probe_profile,
    default_gui_config_path,
    gui_settings_from_mapping,
    gui_settings_to_mapping,
    ir_table_preset,
    load_gui_settings,
    save_gui_settings,
    trigger_history_entry_from_config,
)
from fcapz.transport import OpenOcdTransport


class TestIrTablePreset(unittest.TestCase):
    def test_xilinx7(self) -> None:
        t = ir_table_preset("xilinx7")
        self.assertEqual(t, OpenOcdTransport.IR_TABLE_XILINX7)

    def test_ultrascale_aliases(self) -> None:
        self.assertEqual(ir_table_preset("us"), OpenOcdTransport.IR_TABLE_US)

    def test_unknown(self) -> None:
        with self.assertRaises(ValueError):
            ir_table_preset("nosuch")


class TestGuiSettingsRoundTrip(unittest.TestCase):
    def test_save_load_roundtrip(self) -> None:
        s = GuiSettings()
        s.connection.port = 4444
        s.connection.hardware = "DE25-Nano [USB-1]"
        s.connection.quartus_stp = r"C:\altera_lite\quartus\bin64\quartus_stp.exe"
        s.connection.program = None
        s.viewers.default_viewer = "surfer"
        s.viewers.open_viewer_after_capture = True
        s.viewers.reuse_external_viewer = True
        s.viewers.gtkwave_executable = r"C:\Tools\gtkwave.exe"
        s.probe_profiles["demo"] = ProbeProfile(name="demo", probes="clk:1:0,data:8:1")
        s.trigger_history = [{"pretrigger": 4, "posttrigger": 8}]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gui.toml"
            save_gui_settings(s, path)
            loaded = load_gui_settings(path)
            self.assertEqual(loaded.connection.port, 4444)
            self.assertEqual(loaded.connection.hardware, "DE25-Nano [USB-1]")
            self.assertEqual(
                loaded.connection.quartus_stp,
                r"C:\altera_lite\quartus\bin64\quartus_stp.exe",
            )
            self.assertIsNone(loaded.connection.program)
            self.assertEqual(loaded.viewers.default_viewer, "surfer")
            self.assertTrue(loaded.viewers.open_viewer_after_capture)
            self.assertTrue(loaded.viewers.reuse_external_viewer)
            self.assertEqual(loaded.viewers.gtkwave_executable, r"C:\Tools\gtkwave.exe")
            self.assertEqual(loaded.probe_profiles["demo"].probes, "clk:1:0,data:8:1")
            self.assertEqual(len(loaded.trigger_history), 1)
            self.assertEqual(loaded.trigger_history[0]["pretrigger"], 4)
            self.assertEqual(loaded.connection.connect_timeout_sec, 60.0)
            self.assertEqual(loaded.connection.hw_ready_timeout_sec, 60.0)
            self.assertEqual(loaded.connection.hw_post_program_delay_ms, 200)
            self.assertEqual(loaded.connection.hw_ready_poll_interval_ms, 20)
            self.assertFalse(loaded.connection.program_on_connect)
            self.assertEqual(loaded.ui.font_size_pt, 8)
            self.assertEqual(loaded.ui.log_font_size_pt, 10)

    def test_ui_font_roundtrip(self) -> None:
        s = GuiSettings()
        s.ui.font_size_pt = 11
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gui.toml"
            save_gui_settings(s, path)
            loaded = load_gui_settings(path)
            self.assertEqual(loaded.ui.font_size_pt, 11)

    def test_log_font_roundtrip(self) -> None:
        s = GuiSettings()
        s.ui.log_font_size_pt = 12
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gui.toml"
            save_gui_settings(s, path)
            loaded = load_gui_settings(path)
            self.assertEqual(loaded.ui.log_font_size_pt, 12)

    def test_connection_timeouts_roundtrip(self) -> None:
        s = GuiSettings()
        s.connection.connect_timeout_sec = 42.0
        s.connection.hw_ready_timeout_sec = 99.0
        s.connection.hw_post_program_delay_ms = 150
        s.connection.hw_ready_poll_interval_ms = 33
        s.connection.program_on_connect = False
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gui.toml"
            save_gui_settings(s, path)
            loaded = load_gui_settings(path)
            self.assertEqual(loaded.connection.connect_timeout_sec, 42.0)
            self.assertEqual(loaded.connection.hw_ready_timeout_sec, 99.0)
            self.assertEqual(loaded.connection.hw_post_program_delay_ms, 150)
            self.assertEqual(loaded.connection.hw_ready_poll_interval_ms, 33)
            self.assertFalse(loaded.connection.program_on_connect)

    def test_missing_file_is_default(self) -> None:
        p = Path("__no_such_gui__.toml")
        self.assertFalse(p.is_file())
        g = load_gui_settings(p)
        self.assertEqual(g.connection.backend, "hw_server")
        self.assertEqual(g.probe_profiles, {})
        self.assertEqual(g.ui.font_size_pt, 8)
        self.assertEqual(g.ui.log_font_size_pt, 10)


class TestApplyProbeProfile(unittest.TestCase):
    def test_fills_probes_when_absent(self) -> None:
        args = argparse.Namespace(probes=None)
        st = GuiSettings(
            probe_profiles={"u": ProbeProfile(name="u", probes="x:2:0")},
        )
        self.assertIsNone(apply_probe_profile(args, profile_name="u", settings=st))
        self.assertEqual(args.probes, "x:2:0")

    def test_cli_probes_override(self) -> None:
        args = argparse.Namespace(probes="manual:1:0")
        st = GuiSettings(
            probe_profiles={"u": ProbeProfile(name="u", probes="x:2:0")},
        )
        self.assertIsNone(apply_probe_profile(args, profile_name="u", settings=st))
        self.assertEqual(args.probes, "manual:1:0")

    def test_unknown_profile(self) -> None:
        args = argparse.Namespace(probes=None)
        err = apply_probe_profile(args, profile_name="nope", settings=GuiSettings())
        self.assertIsNotNone(err)
        self.assertIn("nope", err)


class TestTriggerHistory(unittest.TestCase):
    def test_append_caps(self) -> None:
        g = GuiSettings()
        for i in range(15):
            append_trigger_history(g, {"i": i})
        self.assertEqual(len(g.trigger_history), 10)
        self.assertEqual(g.trigger_history[0]["i"], 14)

    def test_save_load_preserves_empty_trigger_sequence(self) -> None:
        """tomli_w cannot encode None; entries use [] when no sequencer."""
        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=255),
            sample_width=8,
            depth=512,
            sample_clock_hz=50_000_000,
            probes=[],
            channel=0,
            decimation=0,
            ext_trigger_mode=0,
            sequence=None,
            probe_sel=0,
            stor_qual_mode=0,
            stor_qual_value=0,
            stor_qual_mask=0,
            trigger_holdoff=0,
            trigger_delay=0,
        )
        g = GuiSettings()
        append_trigger_history(g, trigger_history_entry_from_config(cfg))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gui.toml"
            save_gui_settings(g, path)
            loaded = load_gui_settings(path)
        self.assertEqual(loaded.trigger_history[0].get("trigger_sequence"), [])


class TestFromMapping(unittest.TestCase):
    def test_probe_profiles_table(self) -> None:
        data = gui_settings_to_mapping(
            GuiSettings(
                probe_profiles={"a": ProbeProfile(name="a", probes="z:1:0")},
            ),
        )
        back = gui_settings_from_mapping(data)
        self.assertEqual(back.probe_profiles["a"].probes, "z:1:0")

    def test_old_connection_without_quartus_fields_loads(self) -> None:
        back = gui_settings_from_mapping(
            {
                "connection": {
                    "backend": "hw_server",
                    "host": "127.0.0.1",
                    "port": 3121,
                    "tap": "xc7a100t",
                },
            },
        )

        self.assertIsNone(back.connection.hardware)
        self.assertIsNone(back.connection.quartus_stp)


class TestDefaultPath(unittest.TestCase):
    def test_returns_path(self) -> None:
        p = default_gui_config_path()
        self.assertTrue(p.name.endswith(".toml"))
        self.assertIn("fpgacapzero", str(p).lower())


class TestTriggerHistoryEntry(unittest.TestCase):
    def test_serializes_capture_config(self) -> None:
        cfg = CaptureConfig(
            pretrigger=4,
            posttrigger=8,
            trigger=TriggerConfig(mode="value_match", value=1, mask=255),
            sample_width=8,
            depth=1024,
            sample_clock_hz=50_000_000,
            probes=[ProbeSpec("lo", 4, 0)],
            channel=0,
            decimation=0,
            ext_trigger_mode=1,
            sequence=None,
            probe_sel=2,
            stor_qual_mode=0,
            stor_qual_value=0,
            stor_qual_mask=0,
            trigger_holdoff=9,
            trigger_delay=3,
        )
        d = trigger_history_entry_from_config(cfg)
        self.assertEqual(d["pretrigger"], 4)
        self.assertEqual(d["posttrigger"], 8)
        self.assertEqual(d["trigger_mode"], "value_match")
        self.assertEqual(d["trigger_value"], 1)
        self.assertEqual(d["trigger_mask"], 255)
        self.assertEqual(d["sample_clock_hz"], 50_000_000)
        self.assertEqual(d["ext_trigger_mode"], "or")
        self.assertEqual(d["probes"], "lo:4:0")
        self.assertEqual(d["probe_sel"], 2)
        self.assertNotIn("startup_arm", d)
        self.assertEqual(d["trigger_holdoff"], 9)
        self.assertEqual(d["trigger_delay"], 3)
        self.assertEqual(d["trigger_sequence"], [])
        self.assertNotIn("trigger_value_radix", d)
        d16 = trigger_history_entry_from_config(cfg, trigger_value_radix=16)
        self.assertEqual(d16["trigger_value_radix"], 16)

    def test_serializes_trigger_sequence_when_set(self) -> None:
        cfg = CaptureConfig(
            pretrigger=1,
            posttrigger=2,
            trigger=TriggerConfig(mode="value_match", value=0, mask=255),
            sample_width=8,
            depth=512,
            sample_clock_hz=100_000_000,
            probes=[],
            channel=0,
            decimation=0,
            ext_trigger_mode=0,
            sequence=[
                SequencerStage(
                    cmp_mode_a=1,
                    cmp_mode_b=0,
                    combine=2,
                    next_state=1,
                    is_final=True,
                    count_target=3,
                    value_a=0x10,
                    mask_a=0xFF,
                    value_b=0,
                    mask_b=0xFFFFFFFF,
                ),
            ],
            probe_sel=0,
            stor_qual_mode=0,
            stor_qual_value=0,
            stor_qual_mask=0,
            trigger_holdoff=0,
            trigger_delay=0,
        )
        d = trigger_history_entry_from_config(cfg)
        self.assertIsInstance(d["trigger_sequence"], list)
        self.assertEqual(len(d["trigger_sequence"]), 1)
        s0 = d["trigger_sequence"][0]
        self.assertEqual(s0["cmp_a"], 1)
        self.assertEqual(s0["combine"], 2)
        self.assertEqual(s0["count"], 3)
        self.assertTrue(s0["is_final"])
        self.assertEqual(s0["value_a"], 0x10)


if __name__ == "__main__":
    unittest.main()
