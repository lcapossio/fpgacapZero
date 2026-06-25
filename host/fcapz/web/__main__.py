# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""``fcapz-web`` entry point: run the web frontend server with uvicorn."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


def _default_static_dir() -> Optional[str]:
    """The bundled built frontend, if present (shipped under fcapz/web/static)."""
    d = Path(__file__).resolve().parent / "static"
    return str(d) if d.is_dir() else None


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
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")
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
    args = parser.parse_args(argv)

    import uvicorn

    from .app import create_app

    static_dir = args.static_dir or _default_static_dir()
    if args.host not in ("127.0.0.1", "localhost") and not args.token:
        print(
            f"WARNING: binding {args.host} without --token — the connected board is "
            "reachable by anyone who can reach this port.",
            file=sys.stderr,
        )
    app = create_app(token=args.token, static_dir=static_dir)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
