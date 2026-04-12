# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from fcapz.gui.toolbar_icons import main_toolbar_icon


def test_main_toolbar_icons_produce_non_null_pixmaps() -> None:
    _ = QApplication.instance() or QApplication([])
    for key in (
        "connect",
        "disconnect",
        "configure",
        "arm",
        "capture",
        "continuous",
        "stop",
    ):
        ico = main_toolbar_icon(key)
        pm = ico.pixmap(QSize(24, 24))
        assert not pm.isNull(), key
        assert pm.width() >= 1 and pm.height() >= 1, key
