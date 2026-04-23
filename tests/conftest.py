# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# Headless Qt for widget tests (CI, SSH). Override with QT_QPA_PLATFORM=windows etc. if needed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


ROOT = Path(__file__).resolve().parent.parent
TEST_TMP_ROOT = ROOT / ".codex_pytest_tmp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
for env_name in ("TMPDIR", "TMP", "TEMP", "PYTEST_DEBUG_TEMPROOT"):
    os.environ[env_name] = str(TEST_TMP_ROOT)
tempfile.tempdir = str(TEST_TMP_ROOT)


def _safe_temp_path(prefix: str = "tmp") -> Path:
    path = TEST_TMP_ROOT / f"{prefix}{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _safe_mkdtemp(
    suffix: str | None = None,
    prefix: str | None = None,
    dir: str | os.PathLike[str] | None = None,
) -> str:
    base = Path(dir) if dir is not None else TEST_TMP_ROOT
    base.mkdir(parents=True, exist_ok=True)
    stem = prefix or "tmp"
    while True:
        candidate = base / f"{stem}{uuid.uuid4().hex}{suffix or ''}"
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return str(candidate)
        except FileExistsError:
            continue


class _SafeTemporaryDirectory:
    """Workspace-local replacement for tempfile.TemporaryDirectory on Windows."""

    def __init__(
        self,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | os.PathLike[str] | None = None,
        ignore_cleanup_errors: bool = False,
    ) -> None:
        self.name = _safe_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        self._ignore_cleanup_errors = ignore_cleanup_errors

    def cleanup(self) -> None:
        shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()


tempfile.mkdtemp = _safe_mkdtemp
tempfile.TemporaryDirectory = _SafeTemporaryDirectory


@pytest.fixture
def tmp_path() -> Path:
    path = _safe_temp_path("pytest-")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

# The fcapz package lives at host/fcapz/, so make `host/` the import root.
# This lets `from fcapz import ...` resolve in editable installs and during
# direct test runs from the repo without needing pip install.
HOST = ROOT / "host"
host_str = str(HOST)
if host_str not in sys.path:
    sys.path.insert(0, host_str)
