# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Save and restore a full capture setup (trigger and capture settings).

A capture profile is a flat mapping of every setting a user picks for a
capture: pre/post-trigger lengths, the trigger comparator and sequencer,
storage qualification, decimation, holdoff, delay, run-length capture,
probes, and so on.  The keys are the ``fcapz`` CLI option names with ``_``
for ``-``.  Settings the core reports itself (sample width, depth) are not
part of a profile.

The same mapping is stored three ways:

* as a JSON file (``{"format": "fcapz.capture.v1", "capture": {...}}``),
* by name in ``gui.toml`` under ``[capture_profiles.NAME]``, shared by the
  GUI and the CLI,
* as the GUI's trigger history entries (which may omit keys).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .analyzer import CaptureConfig, ProbeSpec, SequencerStage, TriggerConfig

CAPTURE_PROFILE_FORMAT = "fcapz.capture.v1"

TRIGGER_MODES = ("value_match", "edge_detect", "both")
EXT_TRIGGER_MODES = ("disabled", "or", "and")

#: key -> (kind, default).  Kinds: "int" (non-negative), "bigint" (non-negative,
#: also "0x.." text), "bool", "str".
_FIELDS: dict[str, tuple[str, Any]] = {
    "pretrigger": ("int", 8),
    "posttrigger": ("int", 16),
    "trigger_mode": ("str", "value_match"),
    "trigger_value": ("bigint", 0),
    "trigger_mask": ("bigint", 0xFF),
    "sample_clock_hz": ("int", 100_000_000),
    "channel": ("int", 0),
    "decimation": ("int", 0),
    "probe_sel": ("int", 0),
    "ext_trigger_mode": ("str", "disabled"),
    "stor_qual_mode": ("int", 0),
    "stor_qual_value": ("bigint", 0),
    "stor_qual_mask": ("bigint", 0),
    "startup_arm": ("bool", False),
    "trigger_holdoff": ("int", 0),
    "trigger_delay": ("int", 0),
    "rle": ("bool", False),
    "post_clocks": ("int", 0),
    "probes": ("str", ""),
}

#: GUI display hint kept with a profile; not a capture setting.
_GUI_KEYS = ("trigger_value_radix",)

_STAGE_FIELDS: dict[str, tuple[str, Any]] = {
    "cmp_a": ("int", 0),
    "cmp_b": ("int", 0),
    "combine": ("int", 0),
    "next_state": ("int", 0),
    "is_final": ("bool", False),
    "count": ("int", 1),
    "value_a": ("bigint", 0),
    "mask_a": ("bigint", 0xFFFFFFFF),
    "value_b": ("bigint", 0),
    "mask_b": ("bigint", 0xFFFFFFFF),
}

_UINT16_KEYS = ("trigger_holdoff", "trigger_delay")

#: Largest value of each sequencer stage field (its SEQ_CFG bits).
_STAGE_MAX = {"cmp_a": 8, "cmp_b": 8, "combine": 3, "next_state": 3, "count": 0xFFFF}


def _coerce(where: str, kind: str, raw: Any) -> Any:
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        raise ValueError(f"{where}: expected true/false, got {raw!r}")
    if kind == "str":
        if isinstance(raw, str):
            return raw.strip()
        raise ValueError(f"{where}: expected text, got {raw!r}")
    if isinstance(raw, bool):
        raise ValueError(f"{where}: expected a number, got {raw!r}")
    if isinstance(raw, int):
        value = raw
    elif kind == "bigint" and isinstance(raw, str):
        try:
            value = int(raw.strip(), 0)
        except ValueError:
            raise ValueError(f"{where}: expected a number, got {raw!r}") from None
    else:
        raise ValueError(f"{where}: expected a number, got {raw!r}")
    if value < 0:
        raise ValueError(f"{where}: must be >= 0, got {value}")
    return value


def _check_keys(where: str, data: Mapping[str, Any], known: tuple[str, ...]) -> None:
    unknown = sorted(str(k) for k in data if k not in known)
    if unknown:
        raise ValueError(f"{where}: unknown setting(s) {', '.join(unknown)}")


def normalize_capture_profile(data: Mapping[str, Any]) -> dict[str, Any]:
    """Check a profile mapping and return it complete, with every setting.

    Missing settings take the CLI defaults.  Unknown keys, wrong types and
    out-of-range values raise :class:`ValueError`, so a typo in a hand-written
    profile is not silently ignored.
    """
    if not isinstance(data, Mapping):
        raise ValueError("capture profile must be a mapping")
    _check_keys(
        "capture profile", data, (*_FIELDS, "trigger_sequence", *_GUI_KEYS)
    )
    out: dict[str, Any] = {}
    for key, (kind, default) in _FIELDS.items():
        out[key] = _coerce(key, kind, data[key]) if key in data else default
    if out["trigger_mode"] not in TRIGGER_MODES:
        raise ValueError(
            f"trigger_mode: expected one of {', '.join(TRIGGER_MODES)}, "
            f"got {out['trigger_mode']!r}"
        )
    ext = out["ext_trigger_mode"].lower()
    if ext not in EXT_TRIGGER_MODES:
        raise ValueError(
            f"ext_trigger_mode: expected one of {', '.join(EXT_TRIGGER_MODES)}, "
            f"got {out['ext_trigger_mode']!r}"
        )
    out["ext_trigger_mode"] = ext
    if out["stor_qual_mode"] > 2:
        raise ValueError(f"stor_qual_mode: must be 0, 1 or 2, got {out['stor_qual_mode']}")
    for key in _UINT16_KEYS:
        if out[key] > 0xFFFF:
            raise ValueError(f"{key}: must be 0..65535, got {out[key]}")
    if out["sample_clock_hz"] < 1:
        raise ValueError("sample_clock_hz: must be >= 1")
    if out["decimation"] > 0xFF_FFFF:
        raise ValueError(f"decimation: must be 0..16777215, got {out['decimation']}")
    if out["post_clocks"] and not out["rle"]:
        raise ValueError("post_clocks: needs rle (run-length capture)")
    if out["probes"]:
        parse_probe_spec(out["probes"])  # raises on a malformed spec

    stages_raw = data.get("trigger_sequence", [])
    if not isinstance(stages_raw, (list, tuple)):
        raise ValueError("trigger_sequence: expected a list of stages")
    stages: list[dict[str, Any]] = []
    for i, stage in enumerate(stages_raw):
        where = f"trigger_sequence[{i}]"
        if not isinstance(stage, Mapping):
            raise ValueError(f"{where}: expected a mapping")
        _check_keys(where, stage, tuple(_STAGE_FIELDS))
        fields = {
            key: _coerce(f"{where}.{key}", kind, stage[key]) if key in stage else default
            for key, (kind, default) in _STAGE_FIELDS.items()
        }
        for key, top in _STAGE_MAX.items():
            if fields[key] > top:
                raise ValueError(f"{where}.{key}: must be 0..{top}, got {fields[key]}")
        stages.append(fields)
    out["trigger_sequence"] = stages

    if "trigger_value_radix" in data:
        radix = data["trigger_value_radix"]
        if isinstance(radix, bool) or radix not in (2, 8, 10, 16):
            raise ValueError(f"trigger_value_radix: must be 2, 8, 10 or 16, got {radix!r}")
        out["trigger_value_radix"] = int(radix)
    return out


def parse_probe_spec(spec: str) -> list[ProbeSpec]:
    """Parse ``name:width:lsb,...`` (the ``--probes`` syntax).

    Width and LSB are the last two ``:`` fields, so a name may hold ``:``
    (``bus[7:0]:8:0``).
    """
    probes: list[ProbeSpec] = []
    for part in spec.split(","):
        fields = part.strip().rsplit(":", 2)
        if len(fields) != 3 or not fields[0]:
            raise ValueError(f"invalid probe spec {part.strip()!r}, expected name:width:lsb")
        try:
            width, lsb = int(fields[1]), int(fields[2])
        except ValueError:
            raise ValueError(
                f"invalid probe spec {part.strip()!r}, expected name:width:lsb"
            ) from None
        if width < 1 or lsb < 0:
            raise ValueError(f"invalid probe spec {part.strip()!r}: width >= 1, lsb >= 0")
        probes.append(ProbeSpec(name=fields[0].strip(), width=width, lsb=lsb))
    return probes


def _probe_spec(probes: list[ProbeSpec]) -> str:
    """*probes* in the ``--probes`` syntax; refuses names it cannot carry."""
    for p in probes:
        if "," in p.name or p.name != p.name.strip() or not p.name:
            raise ValueError(
                f"probe name {p.name!r}: a capture profile cannot hold a probe "
                "name that is empty, has a ',' or starts or ends with a space"
            )
    return ",".join(f"{p.name}:{p.width}:{p.lsb}" for p in probes)


def capture_profile_from_config(
    cfg: CaptureConfig,
    *,
    trigger_value_radix: int | None = None,
) -> dict[str, Any]:
    """Every user setting of *cfg* as a profile mapping."""
    out: dict[str, Any] = {
        "pretrigger": int(cfg.pretrigger),
        "posttrigger": int(cfg.posttrigger),
        "trigger_mode": str(cfg.trigger.mode),
        "trigger_value": int(cfg.trigger.value),
        "trigger_mask": int(cfg.trigger.mask),
        "sample_clock_hz": int(cfg.sample_clock_hz),
        "channel": int(cfg.channel),
        "decimation": int(cfg.decimation),
        "probe_sel": int(cfg.probe_sel),
        "ext_trigger_mode": EXT_TRIGGER_MODES[int(cfg.ext_trigger_mode)]
        if 0 <= int(cfg.ext_trigger_mode) < len(EXT_TRIGGER_MODES) else "disabled",
        "stor_qual_mode": int(cfg.stor_qual_mode),
        "stor_qual_value": int(cfg.stor_qual_value),
        "stor_qual_mask": int(cfg.stor_qual_mask),
        "startup_arm": bool(cfg.startup_arm),
        "trigger_holdoff": int(cfg.trigger_holdoff),
        "trigger_delay": int(cfg.trigger_delay),
        "rle": bool(cfg.rle),
        "post_clocks": int(cfg.post_clocks),
        "probes": _probe_spec(cfg.probes),
        "trigger_sequence": [
            {
                "cmp_a": int(s.cmp_mode_a),
                "cmp_b": int(s.cmp_mode_b),
                "combine": int(s.combine),
                "next_state": int(s.next_state),
                "is_final": bool(s.is_final),
                "count": int(s.count_target),
                "value_a": int(s.value_a),
                "mask_a": int(s.mask_a),
                "value_b": int(s.value_b),
                "mask_b": int(s.mask_b),
            }
            for s in (cfg.sequence or [])
        ],
    }
    if trigger_value_radix in (2, 8, 10, 16):
        out["trigger_value_radix"] = int(trigger_value_radix)
    return out


def capture_config_from_profile(
    data: Mapping[str, Any],
    *,
    sample_width: int = 8,
    depth: int = 1024,
) -> CaptureConfig:
    """Build a :class:`CaptureConfig` from a profile.

    *sample_width* and *depth* describe the core; take them from
    :meth:`Analyzer.probe` (``"sample_width"``, ``"depth"``).
    """
    p = normalize_capture_profile(data)
    return CaptureConfig(
        pretrigger=p["pretrigger"],
        posttrigger=p["posttrigger"],
        trigger=TriggerConfig(
            mode=p["trigger_mode"], value=p["trigger_value"], mask=p["trigger_mask"]
        ),
        sample_width=sample_width,
        depth=depth,
        sample_clock_hz=p["sample_clock_hz"],
        probes=parse_probe_spec(p["probes"]) if p["probes"] else [],
        channel=p["channel"],
        decimation=p["decimation"],
        ext_trigger_mode=EXT_TRIGGER_MODES.index(p["ext_trigger_mode"]),
        sequence=[
            SequencerStage(
                cmp_mode_a=s["cmp_a"],
                cmp_mode_b=s["cmp_b"],
                combine=s["combine"],
                next_state=s["next_state"],
                is_final=s["is_final"],
                count_target=s["count"],
                value_a=s["value_a"],
                mask_a=s["mask_a"],
                value_b=s["value_b"],
                mask_b=s["mask_b"],
            )
            for s in p["trigger_sequence"]
        ] or None,
        probe_sel=p["probe_sel"],
        stor_qual_mode=p["stor_qual_mode"],
        stor_qual_value=p["stor_qual_value"],
        stor_qual_mask=p["stor_qual_mask"],
        startup_arm=p["startup_arm"],
        trigger_holdoff=p["trigger_holdoff"],
        trigger_delay=p["trigger_delay"],
        rle=p["rle"],
        post_clocks=p["post_clocks"],
    )


def capture_profile_file_dict(
    data: Mapping[str, Any], *, name: str | None = None
) -> dict[str, Any]:
    """The JSON document for a profile file."""
    doc: dict[str, Any] = {"format": CAPTURE_PROFILE_FORMAT}
    if name:
        doc["name"] = name
    doc["capture"] = normalize_capture_profile(data)
    return doc


def write_capture_profile_file(
    path: str | Path, data: Mapping[str, Any], *, name: str | None = None
) -> None:
    """Write a profile to a JSON file."""
    doc = capture_profile_file_dict(data, name=name)
    Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def read_capture_profile_file(path: str | Path) -> dict[str, Any]:
    """Read a profile JSON file and return its complete, checked mapping."""
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p}: not valid JSON ({exc})") from None
    if not isinstance(doc, dict) or doc.get("format") != CAPTURE_PROFILE_FORMAT:
        raise ValueError(f"{p}: not a {CAPTURE_PROFILE_FORMAT} capture profile")
    _check_keys(str(p), doc, ("format", "name", "capture"))
    try:
        return normalize_capture_profile(doc.get("capture", {}))
    except ValueError as exc:
        raise ValueError(f"{p}: {exc}") from None


def save_capture_profile(path: str | Path, cfg: CaptureConfig, *, name: str | None = None) -> None:
    """Save every user setting of *cfg* to a JSON profile file."""
    write_capture_profile_file(path, capture_profile_from_config(cfg), name=name)


def load_capture_profile(
    path: str | Path,
    *,
    sample_width: int = 8,
    depth: int = 1024,
) -> CaptureConfig:
    """Load a JSON profile file as a :class:`CaptureConfig` for a core of
    *sample_width* bits and *depth* samples."""
    return capture_config_from_profile(
        read_capture_profile_file(path), sample_width=sample_width, depth=depth
    )


def is_profile_path(ref: str) -> bool:
    """Whether a ``NAME|FILE`` profile reference names a file.

    A reference is a file if it ends in ``.json`` or contains a path
    separator; anything else is a profile name in ``gui.toml``.
    """
    return ref.lower().endswith(".json") or "/" in ref or "\\" in ref
