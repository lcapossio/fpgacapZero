# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from pathlib import Path


def test_read_version_prefers_source_tree_version_file(monkeypatch):
    """A stale installed package must not mask the checked-out VERSION file."""
    import importlib.metadata

    from fcapz import _version as version_mod

    wrong_installed_version = "99.99.99"

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda _package_name: wrong_installed_version,
    )

    repo_root = Path(__file__).resolve().parents[1]
    expected = (repo_root / "VERSION").read_text(encoding="utf-8").strip()

    assert version_mod._read_version() == expected
    assert expected != wrong_installed_version
