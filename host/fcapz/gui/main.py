# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Console entry for the PySide6 GUI (``fcapz-gui``)."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print(
            "fcapz-gui requires PySide6. Install with: pip install 'fpgacapzero[gui]'",
            file=sys.stderr,
        )
        return 1
    from .app_window import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
