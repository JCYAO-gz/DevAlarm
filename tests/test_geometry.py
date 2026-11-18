from __future__ import annotations

import unittest

from devalarm import geometry
from devalarm.geometry import Arc


class ArcTests(unittest.TestCase):
    def test_full_and_empty(self) -> None:
        full = geometry.remaining_arc(1.0)
        self.assertTrue(full.full)
        self.assertEqual(full.segments(), ())
        empty = geometry.remaining_arc(0.0)
        self.assertEqual(empty.sweep, 0.0)
        self.assertEqual(empty.segments(), ())

    def test_arc_starts_at_top(self) -> None:
        for ratio in (0.25, 0.5, 0.75, 1.0):
            arc = geometry.remaining_arc(ratio)
            self.assertAlmostEqual(arc.start, 270.0, msg=ratio)

    def test_half_ring_keeps_top_as_gap(self) -> None:
        # 起点顶部顺时针拖出左半圈，缺口停在顶部与右侧（逆时针扩大）
        arc = geometry.remaining_arc(0.5)
        self.assertAlmostEqual(arc.sweep, 180.0)
        self.assertEqual(arc.segments(), ((270.0, 360.0), (0.0, 90.0)))

    def test_three_quarters_wraps_zero(self) -> None:
        arc = geometry.remaining_arc(0.75)
        self.assertAlmostEqual(arc.sweep, 270.0)
        self.assertEqual(
            arc.segments(),
            ((270.0, 360.0), (0.0, 90.0), (90.0, 180.0)),
        )

    def test_quarter_ring(self) -> None:
        arc = geometry.remaining_arc(0.25)
        self.assertAlmostEqual(arc.sweep, 90.0)
        self.assertEqual(arc.segments(), ((270.0, 360.0),))

    def test_arc_from_start(self) -> None:
        arc = geometry.arc_from_start(270.0, 90.0)
        self.assertEqual(arc.segments(), ((270.0, 360.0),))
        self.assertEqual(geometry.arc_from_start(0.0, 0.0).segments(), ())

    def test_arc_clamps_values(self) -> None:
        self.assertTrue(geometry.remaining_arc(9.0).full)
        self.assertEqual(geometry.remaining_arc(-1.0).sweep, 0.0)
        self.assertIsInstance(geometry.remaining_arc(0.3), Arc)


class HitTests(unittest.TestCase):
    def test_circle_hit(self) -> None:
        self.assertTrue(geometry.inside_hit_circle(200, 200, 400))
        self.assertTrue(geometry.inside_hit_circle(200, 15, 400))
        self.assertFalse(geometry.inside_hit_circle(0, 0, 400))
        self.assertFalse(geometry.inside_hit_circle(200, 2, 400))

    def test_handles_are_at_bottom_corners(self) -> None:
        self.assertTrue(geometry.inside_hit_circle(200, 200, 400))
        left = geometry.handle_at(70, 330, 400)
        right = geometry.handle_at(330, 330, 400)
        self.assertEqual(left, "left")
        self.assertEqual(right, "right")
        self.assertIsNone(geometry.handle_at(200, 200, 400))
        self.assertIsNone(geometry.handle_at(200, 60, 400))

    def test_handles_scale_with_window(self) -> None:
        self.assertEqual(geometry.handle_at(44, 199, 240), "left")
        self.assertEqual(geometry.handle_at(196, 199, 240), "right")


class ControlHitTests(unittest.TestCase):
    def test_pause_button(self) -> None:
        self.assertEqual(geometry.control_at(200, 288, 400), "pause")

    def test_prev_next_arrows(self) -> None:
        self.assertEqual(geometry.control_at(200 - 126, 198, 400), "prev")
        self.assertEqual(geometry.control_at(200 + 126, 198, 400), "next")

    def test_misses_central_text(self) -> None:
        self.assertIsNone(geometry.control_at(200, 198, 400))
        self.assertIsNone(geometry.control_at(200, 120, 400))
        self.assertIsNone(geometry.control_at(200, 340, 400))

    def test_scales_with_window(self) -> None:
        # 240 像素窗口是 0.6 倍逻辑画布
        self.assertEqual(geometry.control_at(120, 173, 240), "pause")
        self.assertEqual(geometry.control_at(120 - 75.6, 118.8, 240), "prev")
        self.assertEqual(geometry.control_at(120 + 75.6, 118.8, 240), "next")


class ResizeTests(unittest.TestCase):
    def test_right_handle_anchors_left_and_top(self) -> None:
        rect = geometry.resize_rect("right", 100, 100, 400, 400, 100, 0)
        self.assertEqual(rect, (100, 100, 500, 500))

    def test_left_handle_anchors_right_and_top(self) -> None:
        rect = geometry.resize_rect("left", 100, 100, 400, 400, -100, 0)
        self.assertEqual(rect, (0, 100, 500, 500))

    def test_vertical_drag_is_used_when_larger(self) -> None:
        rect = geometry.resize_rect("right", 100, 100, 400, 400, 5, 80)
        self.assertEqual(rect, (100, 100, 480, 480))

    def test_size_clamps(self) -> None:
        big = geometry.resize_rect("right", 100, 100, 400, 400, 1000, 0)
        self.assertEqual(big[2], geometry.MAX_SIZE)
        small = geometry.resize_rect("left", 100, 100, 400, 400, 1000, 0)
        self.assertEqual(small[2], geometry.MIN_SIZE)
        self.assertEqual(small[0], 100 + 400 - geometry.MIN_SIZE)
        self.assertEqual(small[1], 100)

    def test_size_for_scale(self) -> None:
        self.assertEqual(geometry.size_for_scale(1.0), 400)
        self.assertEqual(geometry.size_for_scale(0.1), 240)
        self.assertEqual(geometry.size_for_scale(9.0), 800)
        self.assertEqual(geometry.size_for_scale(1.25), 500)


if __name__ == "__main__":
    unittest.main()
