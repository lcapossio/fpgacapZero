# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Capture profiles: the format, gui.toml storage and the CLI."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path

from fcapz import cli
from fcapz.analyzer import CaptureConfig, ProbeSpec, SequencerStage, TriggerConfig
from fcapz.capture_profile import (
    CAPTURE_PROFILE_FORMAT,
    capture_config_from_profile,
    capture_profile_from_config,
    is_profile_path,
    load_capture_profile,
    normalize_capture_profile,
    read_capture_profile_file,
    save_capture_profile,
    write_capture_profile_file,
)
from fcapz.probes import PROBE_FILE_FORMAT
from fcapz.gui.settings import (
    GuiSettings,
    load_gui_settings,
    save_gui_settings,
    trigger_history_entry_from_config,
)


def _full_config() -> CaptureConfig:
    """A config with every setting away from its default."""
    return CaptureConfig(
        pretrigger=5,
        posttrigger=77,
        trigger=TriggerConfig(mode="edge_detect", value=(1 << 70) | 0xA5, mask=(1 << 72) - 1),
        sample_width=96,
        depth=4096,
        sample_clock_hz=50_000_000,
        probes=[ProbeSpec("a", 4, 0), ProbeSpec("bus", 64, 4)],
        channel=2,
        decimation=9,
        ext_trigger_mode=2,
        sequence=[
            SequencerStage(cmp_mode_a=1, cmp_mode_b=3, combine=2, next_state=1,
                           is_final=False, count_target=4, value_a=0x10,
                           mask_a=0xFF, value_b=0x20, mask_b=0xF0),
            SequencerStage(cmp_mode_a=0, is_final=True, value_a=0x33),
        ],
        probe_sel=3,
        stor_qual_mode=2,
        stor_qual_value=0x55,
        stor_qual_mask=0x0F,
        startup_arm=True,
        trigger_holdoff=1000,
        trigger_delay=65535,
        rle=True,
        post_clocks=12345,
    )


class FormatTests(unittest.TestCase):
    def test_a_config_survives_the_round_trip(self):
        cfg = _full_config()
        back = capture_config_from_profile(
            capture_profile_from_config(cfg), sample_width=96, depth=4096
        )
        self.assertEqual(back, cfg)

    def test_probe_names_may_hold_colons(self):
        cfg = dataclasses.replace(
            _full_config(), probes=[ProbeSpec("bus[7:0]", 8, 0), ProbeSpec("u::s", 4, 8)]
        )
        back = capture_config_from_profile(
            capture_profile_from_config(cfg), sample_width=96, depth=4096
        )
        self.assertEqual(back.probes, cfg.probes)

    def test_probe_names_a_profile_cannot_hold_are_refused(self):
        for name in ("a,b", " a", "a "):
            cfg = dataclasses.replace(_full_config(), probes=[ProbeSpec(name, 4, 0)])
            with self.assertRaisesRegex(ValueError, "probe name"):
                capture_profile_from_config(cfg)

    def test_the_round_trip_goes_through_json(self):
        cfg = _full_config()
        blob = json.loads(json.dumps(capture_profile_from_config(cfg)))
        self.assertEqual(capture_config_from_profile(blob, sample_width=96, depth=4096), cfg)

    def test_missing_settings_take_the_cli_defaults(self):
        p = normalize_capture_profile({"posttrigger": 3})
        self.assertEqual(p["posttrigger"], 3)
        self.assertEqual(p["pretrigger"], 8)
        self.assertEqual(p["trigger_mask"], 0xFF)
        self.assertEqual(p["ext_trigger_mode"], "disabled")
        self.assertEqual(p["trigger_sequence"], [])
        self.assertEqual(p["probes"], "")

    def test_values_and_masks_may_be_written_in_hex(self):
        p = normalize_capture_profile({
            "trigger_value": "0xA5",
            "trigger_sequence": [{"value_a": "0x10", "mask_a": "0b1111"}],
        })
        self.assertEqual(p["trigger_value"], 0xA5)
        self.assertEqual(p["trigger_sequence"][0]["value_a"], 0x10)
        self.assertEqual(p["trigger_sequence"][0]["mask_a"], 0xF)
        self.assertEqual(p["trigger_sequence"][0]["count"], 1)

    def test_bad_profiles_are_refused(self):
        cases = {
            "unknown key": {"pretriger": 4},
            "bool for a number": {"pretrigger": True},
            "text for a count": {"pretrigger": "4"},
            "negative": {"posttrigger": -1},
            "bad mode": {"trigger_mode": "rising"},
            "bad ext mode": {"ext_trigger_mode": "xor"},
            "number for a flag": {"rle": 1},
            "stor qual mode": {"stor_qual_mode": 3},
            "holdoff range": {"trigger_holdoff": 0x10000},
            "delay range": {"trigger_delay": 0x10000},
            "probe spec": {"probes": "a:4"},
            "probe width": {"probes": "a:0:0"},
            "stage key": {"trigger_sequence": [{"cmp": 1}]},
            "stage list": {"trigger_sequence": {"cmp_a": 1}},
            "radix": {"trigger_value_radix": 3},
        }
        for label, data in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                normalize_capture_profile(data)

    def test_the_error_names_the_unknown_key(self):
        with self.assertRaisesRegex(ValueError, "pretriger"):
            normalize_capture_profile({"pretriger": 4})

    def test_the_gui_radix_hint_is_kept(self):
        p = capture_profile_from_config(_full_config(), trigger_value_radix=2)
        self.assertEqual(normalize_capture_profile(p)["trigger_value_radix"], 2)

    def test_trigger_history_entries_leave_out_startup_arm(self):
        entry = trigger_history_entry_from_config(_full_config())
        self.assertNotIn("startup_arm", entry)
        # Otherwise a history entry is a profile.
        normalize_capture_profile(entry)

    def test_profile_references(self):
        self.assertTrue(is_profile_path("x.json"))
        self.assertTrue(is_profile_path("X.JSON"))
        self.assertTrue(is_profile_path("dir/x"))
        self.assertTrue(is_profile_path("dir\\x"))
        self.assertFalse(is_profile_path("fast"))


class FileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_load(self):
        path = self.dir / "p.json"
        save_capture_profile(path, _full_config(), name="full")
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["format"], CAPTURE_PROFILE_FORMAT)
        self.assertEqual(doc["name"], "full")
        self.assertEqual(load_capture_profile(path, sample_width=96, depth=4096), _full_config())

    def test_a_file_of_another_format_is_refused(self):
        path = self.dir / "p.json"
        path.write_text(json.dumps({"format": PROBE_FILE_FORMAT, "capture": {}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, CAPTURE_PROFILE_FORMAT):
            read_capture_profile_file(path)

    def test_bad_json_and_bad_settings_name_the_file(self):
        path = self.dir / "p.json"
        path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            read_capture_profile_file(path)
        write_capture_profile_file(path, {})
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["capture"]["pretriger"] = 1
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "p.json.*pretriger"):
            read_capture_profile_file(path)


class GuiTomlTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "gui.toml"

    def tearDown(self):
        self._tmp.cleanup()

    def test_profiles_survive_gui_toml(self):
        prof = capture_profile_from_config(_full_config(), trigger_value_radix=16)
        save_gui_settings(GuiSettings(capture_profiles={"full": prof}), self.path)
        loaded = load_gui_settings(self.path).capture_profiles
        self.assertEqual(loaded, {"full": normalize_capture_profile(prof)})
        self.assertEqual(
            capture_config_from_profile(loaded["full"], sample_width=96, depth=4096),
            _full_config(),
        )

    def test_a_bad_profile_is_skipped_and_the_rest_load(self):
        self.path.write_text(
            "[capture_profiles.good]\nposttrigger = 3\n"
            "[capture_profiles.bad]\npretrigger = \"x\"\n",
            encoding="utf-8",
        )
        with self.assertLogs("fcapz.gui.settings", "WARNING") as logs:
            loaded = load_gui_settings(self.path).capture_profiles
        self.assertEqual(list(loaded), ["good"])
        self.assertIn("bad", logs.output[0])


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.gui = self.dir / "gui.toml"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--gui-config", str(self.gui), *argv])
        return code, out.getvalue(), err.getvalue()

    def _config(self, *argv) -> CaptureConfig:
        """Parse a capture command line the way main() does and build its config."""
        argv = ["--gui-config", str(self.gui), "capture", "--out", "x.json",
                "--sample-width", "16", "--depth", "1024", *argv]
        parser = cli.build_parser()
        args = parser.parse_args(argv)
        if args.capture_profile:
            args = cli._apply_capture_profile(parser, args, argv)
        self.assertIsNone(cli._apply_named_probe_profile(args))
        return cli._build_config(args)

    def test_save_list_show_delete(self):
        code, out, _ = self._run(
            "capture-profile", "save", "fast", "--pretrigger", "4", "--posttrigger", "100",
            "--trigger-value", "0xA5", "--probes", "a:4:0,b:4:4",
            "--trigger-sequence", '[{"cmp_a": 0, "is_final": true, "value_a": "0x10"}]',
        )
        self.assertEqual(code, 0, out)
        code, out, _ = self._run("capture-profile", "list")
        self.assertEqual(code, 0)
        self.assertIn("fast", out)
        self.assertIn("value=0xA5", out)
        self.assertIn("stages=1", out)
        code, out, _ = self._run("capture-profile", "show", "fast")
        shown = json.loads(out)
        self.assertEqual(shown["posttrigger"], 100)
        self.assertEqual(shown["probes"], "a:4:0,b:4:4")
        self.assertEqual(shown["trigger_sequence"][0]["value_a"], 0x10)
        code, out, _ = self._run("capture-profile", "delete", "fast")
        self.assertEqual(code, 0)
        self.assertEqual(load_gui_settings(self.gui).capture_profiles, {})

    def test_save_from_a_profile_changes_only_what_is_given(self):
        self._run("capture-profile", "save", "base", "--pretrigger", "4",
                  "--trigger-holdoff", "7", "--rle")
        path = self.dir / "copy.json"
        code, _, err = self._run("capture-profile", "save", str(path),
                                 "--capture-profile", "base", "--pretrigger", "2")
        self.assertEqual(code, 0, err)
        prof = read_capture_profile_file(path)
        self.assertEqual(prof["pretrigger"], 2)
        self.assertEqual(prof["trigger_holdoff"], 7)
        self.assertTrue(prof["rle"])

    def test_capture_takes_the_profile_and_the_command_line_wins(self):
        self._run("capture-profile", "save", "p", "--pretrigger", "4", "--posttrigger", "50",
                  "--trigger-value", "0x5A", "--decimation", "3", "--probes", "x:8:0",
                  "--sample-clock-hz", "25000000", "--stor-qual-mode", "1",
                  "--trigger-sequence", '[{"is_final": true, "value_a": 7}]')
        cfg = self._config("--capture-profile", "p", "--posttrigger", "8",
                           "--pretrigger", "8")
        self.assertEqual(cfg.posttrigger, 8)
        # Explicitly the argparse default: still beats the profile.
        self.assertEqual(cfg.pretrigger, 8)
        self.assertEqual(cfg.trigger.value, 0x5A)
        self.assertEqual(cfg.decimation, 3)
        self.assertEqual(cfg.stor_qual_mode, 1)
        self.assertEqual(cfg.sample_clock_hz, 25_000_000)
        self.assertEqual(cfg.probes, [ProbeSpec("x", 8, 0)])
        self.assertEqual(len(cfg.sequence), 1)
        self.assertEqual(cfg.sequence[0].value_a, 7)
        self.assertEqual(cfg.sample_width, 16)

    def test_explicit_probes_replace_the_profile_probes(self):
        self._run("capture-profile", "save", "p", "--probes", "x:8:0",
                  "--sample-clock-hz", "25000000")
        cfg = self._config("--capture-profile", "p", "--probes", "y:4:0")
        self.assertEqual(cfg.probes, [ProbeSpec("y", 4, 0)])
        probe_file = self.dir / "d.prob"
        probe_file.write_text(json.dumps({
            "format": PROBE_FILE_FORMAT, "sample_width": 16, "sample_clock_hz": 1000,
            "probes": [{"name": "z", "width": 2, "lsb": 0}],
        }), encoding="utf-8")
        cfg = self._config("--capture-profile", "p", "--probe-file", str(probe_file))
        self.assertEqual(cfg.probes, [ProbeSpec("z", 2, 0)])
        self.assertEqual(cfg.sample_clock_hz, 1000)

    def test_a_profile_file_works_without_gui_toml(self):
        path = self.dir / "f.json"
        save_capture_profile(path, _full_config())
        cfg = self._config("--capture-profile", str(path))
        self.assertEqual(cfg.trigger, _full_config().trigger)
        self.assertTrue(cfg.startup_arm)

    def test_errors(self):
        code, _, err = self._run("capture-profile", "show", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown capture profile 'nope'", err)
        code, _, err = self._run("capture-profile", "delete", "nope")
        self.assertEqual(code, 2)
        code, _, err = self._run("capture-profile", "save", str(self.dir / "no" / "x.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot write", err)
        code, _, err = self._run("capture", "--out", "x", "--capture-profile", "missing")
        self.assertEqual(code, 2)
        self.assertIn("unknown capture profile", err)
        code, out, _ = self._run("capture-profile", "list")
        self.assertIn("no capture profiles", out)


if __name__ == "__main__":
    unittest.main()
