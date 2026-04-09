# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Load and store GUI / CLI shared preferences in a TOML file."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..analyzer import CaptureConfig
from ..transport import OpenOcdTransport

_TRIGGER_HISTORY_MAX = 10


def default_gui_config_path() -> Path:
    """Per-user path: ``~/.config/fpgacapzero/gui.toml`` or Windows ``%APPDATA%``."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "fpgacapzero" / "gui.toml"
    return Path.home() / ".config" / "fpgacapzero" / "gui.toml"


def live_wave_dir(gui_config_path: Path) -> Path:
    """Directory for ``capture.vcd`` + sidecars when reusing one external viewer instance."""
    return gui_config_path.parent / "live-wave"


def ir_table_preset(name: str) -> dict[int, int]:
    """
    Map a short preset name to an IR-length table for OpenOCD / hw_server transports.

    Aliases: ``xilinx7``, ``7series`` → 7-series table; ``ultrascale``, ``us`` → US+ table.
    """
    key = name.strip().lower().replace("-", "_")
    if key in ("xilinx7", "7series", "series7"):
        return dict(OpenOcdTransport.IR_TABLE_XILINX7)
    if key in ("ultrascale", "us", "xilinx_ultrascale"):
        return dict(OpenOcdTransport.IR_TABLE_US)
    raise ValueError(f"unknown ir_table preset {name!r}")


@dataclass
class ConnectionSettings:
    backend: str = "hw_server"
    host: str = "127.0.0.1"
    port: int = 6666
    tap: str = "xc7a100t.tap"
    program: str | None = None
    ir_table: str = "xilinx7"
    #: OpenOCD TCP ``create_connection`` timeout (seconds).
    connect_timeout_sec: float = 60.0
    #: After ``fpga -file``, poll until VERSION non-zero (seconds); GUI default is patient.
    hw_ready_timeout_sec: float = 60.0


@dataclass
class ViewerSettings:
    default_viewer: str = "gtkwave"
    gtkwave_executable: str | None = None
    surfer_executable: str | None = None
    wavetrace_executable: str | None = None
    custom_argv: list[str] = field(default_factory=list)
    #: GUI: spawn the selected external viewer after each new capture lands in history.
    open_viewer_after_capture: bool = False
    #: GUI: keep one viewer process; overwrite a fixed ``live-wave`` tree so viewers can reload.
    reuse_external_viewer: bool = False


@dataclass
class ProbeProfile:
    """Named ``--probes`` string (``name:width:lsb,...``)."""

    name: str
    probes: str


@dataclass
class GuiSettings:
    connection: ConnectionSettings = field(default_factory=ConnectionSettings)
    viewers: ViewerSettings = field(default_factory=ViewerSettings)
    probe_profiles: dict[str, ProbeProfile] = field(default_factory=dict)
    trigger_history: list[dict[str, Any]] = field(default_factory=list)


def _loads_toml(raw: str) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(raw)
    import tomli

    return tomli.loads(raw)


def _dumps_toml(data: dict[str, Any]) -> bytes:
    import io

    import tomli_w

    buf = io.BytesIO()
    tomli_w.dump(data, buf)
    return buf.getvalue()


def _empty_to_none(s: str | None) -> str | None:
    if s is None or s == "":
        return None
    return s


def _none_to_str(s: str | None) -> str:
    return s if s else ""


def gui_settings_from_mapping(data: Mapping[str, Any]) -> GuiSettings:
    """Build :class:`GuiSettings` from a TOML-loaded mapping."""
    conn_raw = dict(data.get("connection") or {})
    if "program" in conn_raw:
        program = _empty_to_none(str(conn_raw.get("program", "")))
    else:
        program = None
    conn = ConnectionSettings(
        backend=str(conn_raw.get("backend", "hw_server")),
        host=str(conn_raw.get("host", "127.0.0.1")),
        port=int(conn_raw.get("port", 6666)),
        tap=str(conn_raw.get("tap", "xc7a100t.tap")),
        program=program,
        ir_table=str(conn_raw.get("ir_table", "xilinx7")),
        connect_timeout_sec=float(conn_raw.get("connect_timeout_sec", 60.0)),
        hw_ready_timeout_sec=float(conn_raw.get("hw_ready_timeout_sec", 60.0)),
    )

    vraw = dict(data.get("viewers") or {})

    def _opt_viewer_key(key: str) -> str | None:
        if key not in vraw:
            return None
        return _empty_to_none(str(vraw.get(key, "")))

    custom = vraw.get("custom_argv")
    if isinstance(custom, list):
        custom_list = [str(x) for x in custom]
    else:
        custom_list = []
    ovc = vraw.get("open_viewer_after_capture")
    if isinstance(ovc, bool):
        open_after = ovc
    else:
        open_after = str(ovc or "").strip().lower() in ("1", "true", "yes")
    rev = vraw.get("reuse_external_viewer")
    if isinstance(rev, bool):
        reuse_ev = rev
    else:
        reuse_ev = str(rev or "").strip().lower() in ("1", "true", "yes")
    viewers = ViewerSettings(
        default_viewer=str(vraw.get("default", "gtkwave")),
        gtkwave_executable=_opt_viewer_key("gtkwave_executable"),
        surfer_executable=_opt_viewer_key("surfer_executable"),
        wavetrace_executable=_opt_viewer_key("wavetrace_executable"),
        custom_argv=custom_list,
        open_viewer_after_capture=open_after,
        reuse_external_viewer=reuse_ev,
    )

    profiles: dict[str, ProbeProfile] = {}
    praw = data.get("probe_profiles")
    if isinstance(praw, dict):
        for name, body in praw.items():
            if not isinstance(body, dict):
                continue
            probes = str(body.get("probes", "")).strip()
            if probes:
                profiles[str(name)] = ProbeProfile(name=str(name), probes=probes)

    hist = data.get("trigger_history")
    trigger_history: list[dict[str, Any]] = []
    if isinstance(hist, list):
        for entry in hist:
            if isinstance(entry, dict):
                trigger_history.append(dict(entry))

    return GuiSettings(
        connection=conn,
        viewers=viewers,
        probe_profiles=profiles,
        trigger_history=trigger_history[:_TRIGGER_HISTORY_MAX],
    )


def gui_settings_to_mapping(settings: GuiSettings) -> dict[str, Any]:
    """Serialize for TOML output."""
    probe_blob: dict[str, dict[str, str]] = {}
    for name, prof in settings.probe_profiles.items():
        probe_blob[name] = {"probes": prof.probes}

    return {
        "connection": {
            "backend": settings.connection.backend,
            "host": settings.connection.host,
            "port": settings.connection.port,
            "tap": settings.connection.tap,
            "program": _none_to_str(settings.connection.program),
            "ir_table": settings.connection.ir_table,
            "connect_timeout_sec": settings.connection.connect_timeout_sec,
            "hw_ready_timeout_sec": settings.connection.hw_ready_timeout_sec,
        },
        "viewers": {
            "default": settings.viewers.default_viewer,
            "gtkwave_executable": _none_to_str(settings.viewers.gtkwave_executable),
            "surfer_executable": _none_to_str(settings.viewers.surfer_executable),
            "wavetrace_executable": _none_to_str(settings.viewers.wavetrace_executable),
            "custom_argv": list(settings.viewers.custom_argv),
            "open_viewer_after_capture": settings.viewers.open_viewer_after_capture,
            "reuse_external_viewer": settings.viewers.reuse_external_viewer,
        },
        "probe_profiles": probe_blob,
        "trigger_history": list(settings.trigger_history),
    }


def load_gui_settings(path: Path | None = None) -> GuiSettings:
    """Load settings from ``path``; missing file → defaults."""
    p = path or default_gui_config_path()
    if not p.is_file():
        return GuiSettings()
    raw = p.read_text(encoding="utf-8")
    data = _loads_toml(raw)
    if not isinstance(data, dict):
        return GuiSettings()
    return gui_settings_from_mapping(data)


def save_gui_settings(settings: GuiSettings, path: Path | None = None) -> None:
    """Write settings to ``path`` (parent dirs created as needed)."""
    p = path or default_gui_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = gui_settings_to_mapping(settings)
    data = _dumps_toml(blob)
    p.write_bytes(data)


def trigger_history_entry_from_config(cfg: CaptureConfig) -> dict[str, Any]:
    """Serialize capture/trigger fields for ``trigger_history`` in ``gui.toml``."""
    ext = {0: "disabled", 1: "or", 2: "and"}.get(int(cfg.ext_trigger_mode), "disabled")
    probes = (
        ",".join(f"{p.name}:{p.width}:{p.lsb}" for p in cfg.probes) if cfg.probes else ""
    )
    return {
        "pretrigger": int(cfg.pretrigger),
        "posttrigger": int(cfg.posttrigger),
        "trigger_mode": str(cfg.trigger.mode),
        "trigger_value": int(cfg.trigger.value),
        "trigger_mask": int(cfg.trigger.mask),
        "sample_clock_hz": int(cfg.sample_clock_hz),
        "channel": int(cfg.channel),
        "decimation": int(cfg.decimation),
        "probe_sel": int(cfg.probe_sel),
        "ext_trigger_mode": ext,
        "stor_qual_mode": int(cfg.stor_qual_mode),
        "stor_qual_value": int(cfg.stor_qual_value),
        "stor_qual_mask": int(cfg.stor_qual_mask),
        "trigger_delay": int(cfg.trigger_delay),
        "probes": probes,
        "trigger_sequence": (
            [
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
                for s in cfg.sequence
            ]
            if cfg.sequence
            else None
        ),
    }


def append_trigger_history(settings: GuiSettings, entry: Mapping[str, Any]) -> None:
    """Prepend a snapshot and cap at :data:`_TRIGGER_HISTORY_MAX` entries."""
    settings.trigger_history.insert(0, dict(entry))
    del settings.trigger_history[_TRIGGER_HISTORY_MAX:]


def apply_probe_profile(
    args: Any,
    *,
    profile_name: str,
    settings: GuiSettings,
) -> str | None:
    """
    If ``args.probes`` is unset, set it from ``settings.probe_profiles[profile_name]``.

    Returns an error message, or ``None`` on success.
    """
    prof = settings.probe_profiles.get(profile_name)
    if prof is None:
        known = ", ".join(sorted(settings.probe_profiles)) or "(none)"
        return f"unknown probe profile {profile_name!r} (known: {known})"
    if getattr(args, "probes", None) is None:
        args.probes = prof.probes
    return None


def viewer_executable_override(settings: GuiSettings, viewer_key: str) -> Path | None:
    """Return a configured override path for a built-in viewer, if any."""
    key = viewer_key.strip().lower()
    raw: str | None = None
    if key in ("gtkwave", "gtk"):
        raw = settings.viewers.gtkwave_executable
    elif key in ("surfer",):
        raw = settings.viewers.surfer_executable
    elif key in ("wavetrace", "wavetraceviewer"):
        raw = settings.viewers.wavetrace_executable
    if not raw:
        return None
    return Path(raw)
