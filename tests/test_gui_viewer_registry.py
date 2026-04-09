# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

from fcapz.gui.settings import GuiSettings
from fcapz.gui.viewer_registry import viewers_for_settings


class TestViewerRegistry(unittest.TestCase):
    def test_empty_settings_returns_list(self) -> None:
        v = viewers_for_settings(GuiSettings())
        self.assertIsInstance(v, list)


if __name__ == "__main__":
    unittest.main()
