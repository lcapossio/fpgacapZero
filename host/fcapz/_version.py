# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Single source of truth for the fcapz package version.

The canonical value lives in the ``VERSION`` text file at the repo root.
``pyproject.toml`` reads it via ``[tool.setuptools.dynamic] version =
{file = "VERSION"}``, ``tools/sync_version.py`` reads it to regenerate
``rtl/fcapz_version.vh``, and this module reads it (or the installed
package metadata) to expose ``__version__`` and ``_version_tuple()`` at
runtime so tests and Analyzer.probe() comparisons stay coupled to the
RTL VERSION register without anyone hardcoding numbers in two places.
"""

from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    """Resolve the package version, in order of preference.

    1. ``importlib.metadata`` — works after ``pip install`` (editable or
       wheel), reads the value setuptools wrote into ``PKG-INFO`` from
       the ``VERSION`` file.
    2. Direct ``VERSION`` file read — works in development without
       ``pip install -e .``, e.g. when running tests via the repo-root
       conftest that just inserts ``host/`` into ``sys.path``.
    3. Fallback ``"0+unknown"`` so importing fcapz never fails on a
       missing install.  Tests should never see this; CI install-smoke
       catches it.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("fpgacapzero")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass

    try:
        # host/fcapz/_version.py → host/fcapz → host → repo root
        repo_root = Path(__file__).resolve().parent.parent.parent
        version_file = repo_root / "VERSION"
        if version_file.is_file():
            return version_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    return "0+unknown"


__version__ = _read_version()


def _version_tuple() -> tuple[int, int, int]:
    """Return ``(major, minor, patch)`` parsed from ``__version__``.

    Used by tests and by ``Analyzer.probe()`` comparisons so nobody
    hardcodes 0/3/0 in three places.  Tolerates trailing pre-release /
    build metadata after a ``-`` or ``+``.  Out-of-range or malformed
    components fall through to ``(0, 0, 0)``.
    """
    base = __version__.split("-", 1)[0].split("+", 1)[0]
    parts = base.split(".")
    if len(parts) < 3:
        parts = parts + ["0"] * (3 - len(parts))
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return (0, 0, 0)
