# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""``fcapz-web`` entry point: run the web frontend server with uvicorn."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def _default_static_dir() -> Optional[str]:
    """The bundled built frontend, if present (shipped under fcapz/web/static)."""
    d = Path(__file__).resolve().parent / "static"
    return str(d) if d.is_dir() else None


def _discover_cfgs(cfg_dirs) -> list[str]:
    """Glob ``*.cfg`` (non-recursive) in each ``--openocd-cfg-dir``, sorted."""
    found: list[str] = []
    for raw in cfg_dirs or ():
        d = Path(raw).expanduser()
        if not d.is_dir():
            print(f"WARNING: --openocd-cfg-dir not a directory, skipping: {d}", file=sys.stderr)
            continue
        found.extend(str(p) for p in sorted(d.glob("*.cfg")))
    return found


def _build_openocd_launcher(openocd, cfgs, cfg_dirs=None):
    """Build the OpenOcdLauncher from CLI flags, or None if not fully configured.

    An ``openocd`` binary (``--openocd``, ``$FCAPZ_OPENOCD``, or found on ``PATH``)
    and at least one config are required; otherwise the UI's "Start OpenOCD"
    feature stays disabled. Configs come from explicit ``--openocd-cfg`` files
    and/or from every ``*.cfg`` discovered in the ``--openocd-cfg-dir`` folders.
    Each is registered by filename stem (the name the UI starts it by).
    """
    openocd = openocd or shutil.which("openocd")
    cfgs = list(cfgs or []) + _discover_cfgs(cfg_dirs)
    if not openocd and not cfgs:
        return None
    if not openocd or not cfgs:
        print(
            "WARNING: enabling the UI 'Start OpenOCD' feature needs both an openocd "
            "binary (--openocd / $FCAPZ_OPENOCD / on PATH) and at least one config "
            "(--openocd-cfg / --openocd-cfg-dir); it stays disabled.",
            file=sys.stderr,
        )
        return None

    from ..openocd_launcher import OpenOcdLauncher

    configs: dict[str, str] = {}
    for raw in cfgs:
        path = Path(raw).expanduser()
        if not path.is_file():
            print(f"WARNING: OpenOCD config not found, skipping: {path}", file=sys.stderr)
            continue
        resolved = str(path.resolve())
        if path.stem in configs and configs[path.stem] != resolved:
            print(
                f"WARNING: duplicate OpenOCD config name {path.stem!r}; keeping "
                f"{configs[path.stem]}, ignoring {resolved}",
                file=sys.stderr,
            )
            continue
        configs[path.stem] = resolved
    if not configs:
        print("WARNING: no valid OpenOCD configs; 'Start OpenOCD' disabled.", file=sys.stderr)
        return None
    return OpenOcdLauncher(openocd=openocd, configs=configs)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fcapz-web",
        description="fpgacapZero web frontend — drive the board from a browser.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Use 0.0.0.0 to reach it from other machines "
        "(set --token when you do).",
    )
    parser.add_argument("--port", type=int, default=7373, help="HTTP port (default 7373)")
    parser.add_argument(
        "--token",
        default=os.environ.get("FCAPZ_WEB_TOKEN"),
        help="Bearer token required on the API (default: $FCAPZ_WEB_TOKEN or none)",
    )
    parser.add_argument(
        "--static-dir",
        default=None,
        help="Directory of built frontend assets to serve (default: bundled, if built)",
    )
    parser.add_argument(
        "--openocd",
        default=os.environ.get("FCAPZ_OPENOCD"),
        help="Path to the openocd executable, to let the UI start OpenOCD "
        "(default: $FCAPZ_OPENOCD, else 'openocd' on PATH). Needs at least one "
        "config via --openocd-cfg or --openocd-cfg-dir.",
    )
    parser.add_argument(
        "--openocd-cfg",
        action="append",
        default=None,
        metavar="PATH",
        help="An OpenOCD config the UI may launch (repeatable). Registered by "
        "its filename stem; only these configs can be started.",
    )
    parser.add_argument(
        "--openocd-cfg-dir",
        action="append",
        default=[d] if (d := os.environ.get("FCAPZ_OPENOCD_CFG_DIR")) else None,
        metavar="DIR",
        help="Auto-discover OpenOCD configs: register every *.cfg in DIR "
        "(repeatable; non-recursive; default: $FCAPZ_OPENOCD_CFG_DIR). Lets you "
        "point at e.g. examples/arty_a7 instead of listing each --openocd-cfg.",
    )
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        metavar="ORIGIN",
        help="Allow cross-origin API access from this origin (repeatable). Not "
        "needed for the bundled UI (same-origin, and dev proxies /api); use only "
        "if you serve the frontend from a different origin. Off by default.",
    )
    args = parser.parse_args(argv)

    import uvicorn

    from .app import _is_loopback, create_app

    static_dir = args.static_dir or _default_static_dir()
    if not _is_loopback(args.host) and not args.token:
        print(
            f"WARNING: binding {args.host} without --token — the connected board is "
            "reachable by anyone who can reach this port.",
            file=sys.stderr,
        )
    launcher = _build_openocd_launcher(args.openocd, args.openocd_cfg, args.openocd_cfg_dir)
    app = create_app(
        token=args.token,
        static_dir=static_dir,
        openocd_launcher=launcher,
        bind_host=args.host,
        cors_origins=tuple(args.cors_origin or ()),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
