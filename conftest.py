# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Repository-root conftest: make ``import fcapz`` resolve to ``host/fcapz/``.

The fcapz Python package lives at ``host/fcapz/``.  ``pyproject.toml``
declares ``where = ["host"]`` so an editable install (``pip install -e .``)
exposes it as the top-level ``fcapz`` package.  When running tests directly
from the repo without installing, we replicate that by inserting ``host/``
at the front of ``sys.path``.

This conftest sits at the repo root so it applies to both ``tests/`` and
``examples/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = ROOT / "host"
host_str = str(HOST)
if host_str not in sys.path:
    sys.path.insert(0, host_str)
