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


def _openocd_search_roots() -> list[Path]:
    """Dedicated/small dirs to ``**``-scan for an off-PATH OpenOCD.

    Only directories that hold toolchains (xPack's xpm dirs, common
    manual-extract roots, POSIX prefixes) — never a raw ``%LOCALAPPDATA%`` whose
    huge tree would make a recursive glob crawl. Each is safe to ``**``-glob.
    """
    home = Path.home()
    roots: list[Path] = [
        home / ".local" / "xPacks",
        home / "AppData" / "Roaming" / "xPacks",
        Path("C:/tools"),
        Path("/opt"),
        Path("/usr/local"),
    ]
    for env in ("APPDATA", "LOCALAPPDATA", "ProgramData"):
        v = os.environ.get(env)
        if v:
            roots.append(Path(v) / "xPacks")
            roots.append(Path(v) / "chocolatey" / "lib")
    return roots


def _find_openocd(explicit) -> Optional[str]:
    """Locate the OpenOCD binary: explicit/env, then PATH, then known installs.

    xPack OpenOCD (what Digilent/BRS boards use) and manual extracts land off
    ``PATH``, so ``shutil.which`` alone misses them; recursively probe a few
    dedicated toolchain roots before giving up. ``$FCAPZ_OPENOCD``/``--openocd``
    (passed as ``explicit``) and anything on ``PATH`` still win.
    """
    if explicit:
        return explicit
    found = shutil.which("openocd")
    # A .cmd/.bat/.ps1 shim (chocolatey/scoop/custom) spawns the real openocd as
    # a *grandchild*, which our process teardown can't reliably kill — leaving
    # OpenOCD holding the JTAG adapter. Prefer a real .exe if we can find one;
    # only fall back to the shim when no real binary turns up.
    if found and not _is_shim(found):
        return found
    exe = "openocd.exe" if os.name == "nt" else "openocd"
    patterns = (
        f"**/xpack-openocd-*/bin/{exe}",
        f"**/openocd-*/bin/{exe}",
        f"**/openocd/*/.content/bin/{exe}",  # xpm @xpack-dev-tools layout
    )
    for root in _openocd_search_roots():
        if not root.is_dir():
            continue
        for pat in patterns:
            for hit in sorted(root.glob(pat)):
                if hit.is_file():
                    return str(hit)
    return found  # shim as a last resort (better than nothing)


def _is_shim(path: str) -> bool:
    """True for a Windows launcher shim that wraps the real exe in a child."""
    return Path(path).suffix.lower() in (".cmd", ".bat", ".ps1")


def _default_cfg_dirs() -> list[str]:
    """When no configs are specified, offer the repo's bundled board configs.

    Finds an ``examples/`` dir (cwd first, then walking up from this package) and
    returns each immediate board subdirectory that holds a top-level ``*.cfg`` —
    so ``fcapz-web`` run from a source checkout can start OpenOCD for a shipped
    board with no flags. Returns ``[]`` when no ``examples/`` is around (e.g. a
    plain pip install), leaving the feature off unless flags are given.
    """
    bases = [Path.cwd(), *Path(__file__).resolve().parents]
    for base in bases:
        ex = base / "examples"
        if not ex.is_dir():
            continue
        dirs = [
            str(d) for d in sorted(ex.iterdir())
            if d.is_dir() and any(d.glob("*.cfg"))
        ]
        if dirs:
            return dirs
    return []


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

    An ``openocd`` binary (``--openocd``, ``$FCAPZ_OPENOCD``, on ``PATH``, or a
    known xPack/install location) and at least one config are required; otherwise
    the UI's "Start OpenOCD" feature stays disabled. Configs come from explicit
    ``--openocd-cfg`` files and/or every ``*.cfg`` discovered in the
    ``--openocd-cfg-dir`` folders; when neither is given, the repo's bundled
    ``examples/*/`` board configs are offered by default. Each is registered by
    filename stem (the name the UI starts it by).
    """
    openocd = _find_openocd(openocd)
    explicit = list(cfgs or [])
    dirs = list(cfg_dirs or [])
    if not explicit and not dirs:
        dirs = _default_cfg_dirs()
        if dirs:
            print(
                "INFO: no --openocd-cfg/--openocd-cfg-dir given; offering bundled "
                f"example board configs from {len(dirs)} examples/ dir(s).",
                file=sys.stderr,
            )
    cfgs = explicit + _discover_cfgs(dirs)
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
        "(default: $FCAPZ_OPENOCD, else found on PATH or a known xPack/chocolatey "
        "install). Configs default to the bundled examples/*/ board configs if "
        "no --openocd-cfg/--openocd-cfg-dir is given.",
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
