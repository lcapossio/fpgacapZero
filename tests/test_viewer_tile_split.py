# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import unittest

from fcapz.gui.viewer_tile import split_work_area_vertical


class TestSplitWorkAreaVertical(unittest.TestCase):
    def test_tall_work_area_host_gets_usable_strip(self) -> None:
        top, bottom = split_work_area_vertical(0, 0, 1920, 1080)
        assert top is not None and bottom is not None
        tx, ty, tw, th = top
        bx, by, bw, bh = bottom
        self.assertEqual((tx, ty, tw), (0, 0, 1920))
        self.assertEqual((bx, bw), (0, 1920))
        self.assertEqual(ty + th, by)
        self.assertEqual(th + bh, 1080)
        self.assertGreaterEqual(bh, 300)
        self.assertGreaterEqual(bh, int(1080 * 0.35))
        self.assertGreaterEqual(th, 120)

    def test_rects_use_full_width(self) -> None:
        top, bottom = split_work_area_vertical(40, 100, 800, 600)
        assert top is not None and bottom is not None
        self.assertEqual(top[0], 40)
        self.assertEqual(top[1], 100)
        self.assertEqual(top[2], 800)
        self.assertEqual(bottom[2], 800)

    def test_heights_sum_to_work_area(self) -> None:
        for h in (100, 200, 999, 1200):
            with self.subTest(h=h):
                r = split_work_area_vertical(0, 0, 640, h)
                assert r is not None
                top, bottom = r
                self.assertEqual(top[3] + bottom[3], h)
                self.assertEqual(bottom[1], top[1] + top[3])

    def test_invalid_returns_none(self) -> None:
        self.assertIsNone(split_work_area_vertical(0, 0, 0, 100))
        self.assertIsNone(split_work_area_vertical(0, 0, 100, 1))
