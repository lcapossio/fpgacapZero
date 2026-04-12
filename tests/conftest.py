# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import os
import sys
from pathlib import Path

# Headless Qt for widget tests (CI, SSH). Override with QT_QPA_PLATFORM=windows etc. if needed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


ROOT = Path(__file__).resolve().parent.parent
# The fcapz package lives at host/fcapz/, so make `host/` the import root.
# This lets `from fcapz import ...` resolve in editable installs and during
# direct test runs from the repo without needing pip install.
HOST = ROOT / "host"
host_str = str(HOST)
if host_str not in sys.path:
    sys.path.insert(0, host_str)
