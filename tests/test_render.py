from __future__ import annotations

import math
import unittest

from PIL import Image

from devalarm import geometry
from devalarm.core import DEFAULT_EVENTS, PHASE_ALERT, make_snapshot
from devalarm.render import RingRenderer
from devalarm.theme import get_theme


def _is_blue(pixel: tuple[int, int, int, int]) -> bool:
    red, green, blue, alpha = pixel
    return alpha > 100 and blue > 150 and blue - red > 60


def _blue_count(image: Image.Image, radius: float = geometry.R_MID) -> int:
    center = image.width / 2.0
    limit = (geometry.R_OUT + 12.0) * image.width / geometry.LOG_SIZE
    inner = (geometry.R_OUT - geometry.RING_W - 2.0) * image.width / geometry.LOG_SIZE
    count = 0
    for y in range(image.height):
        for x in range(image.width):
            distance = ((x - center) ** 2 + (y - center) ** 2) ** 0.5
            if inner <= distance <= limit and _is_blue(image.getpixel((x, y))):
                count += 1
    return count


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.renderer = RingRenderer(scale=1.0)

    def test_output_size_follows_scale(self) -> None:
        for scale, size in ((0.6, 240), (1.0, 400), (1.25, 500), (2.0, 800)):
            image = RingRenderer(scale=scale).render(
                make_snapshot(DEFAULT_EVENTS, 0)
            )
            self.assertEqual(image.size, (size, size))

    def test_outside_circle_is_transparent(self) -> None:
        image = self.renderer.render(make_snapshot(DEFAULT_EVENTS, 0))
        for point in ((0, 0), (399, 0), (0, 399), (399, 399), (200, 2)):
            self.assertEqual(image.getpixel(point)[3], 0, point)
        self.assertGreater(image.getpixel((200, 200))[3], 200)

    def test_remaining_ring_shrinks(self) -> None:
        full = self.renderer.render(make_snapshot(DEFAULT_EVENTS, 0))
        nearly_done = self.renderer.render(
            make_snapshot(DEFAULT_EVENTS, 0, elapsed=DEFAULT_EVENTS[0].seconds * 0.9)
        )
        self.assertGreater(_blue_count(full), _blue_count(nearly_done) * 3)

    def _ring_pixel(self, image: Image.Image, angle: float):
        size = image.width
        center = size // 2
        radius = geometry.R_MID * size / geometry.LOG_SIZE
        x = round(center + radius * math.cos(math.radians(angle)))
        y = round(center + radius * math.sin(math.radians(angle)))
        return image.getpixel((x, y))

    def test_gap_grows_counterclockwise_from_top(self) -> None:
        # 剩余 50%：弧从顶部(270°)顺时针覆盖右半圈，缺口在左半圈。
        image = self.renderer.render(
            make_snapshot(DEFAULT_EVENTS, 0, elapsed=DEFAULT_EVENTS[0].seconds * 0.5)
        )
        self.assertTrue(_is_blue(self._ring_pixel(image, 315.0)))   # 右上
        self.assertTrue(_is_blue(self._ring_pixel(image, 45.0)))    # 右下
        self.assertFalse(_is_blue(self._ring_pixel(image, 225.0)))  # 左上
        self.assertFalse(_is_blue(self._ring_pixel(image, 135.0)))  # 左下

    def test_gap_expands_counterclockwise(self) -> None:
        # 剩余 75%：缺口只吃掉左上象限；左下仍有弧。
        image = self.renderer.render(
            make_snapshot(DEFAULT_EVENTS, 0, elapsed=DEFAULT_EVENTS[0].seconds * 0.25)
        )
        self.assertFalse(_is_blue(self._ring_pixel(image, 225.0)))
        self.assertTrue(_is_blue(self._ring_pixel(image, 135.0)))

    def test_alert_ring_is_brighter_and_full(self) -> None:
        snap = make_snapshot(
            DEFAULT_EVENTS,
            0,
            elapsed=float(DEFAULT_EVENTS[0].seconds),
            phase=PHASE_ALERT,
            alert_elapsed=3.0,
            alert_seconds=10,
        )
        alert = self.renderer.render(snap, t=0.4)
        normal = self.renderer.render(
            make_snapshot(DEFAULT_EVENTS, 0, elapsed=DEFAULT_EVENTS[0].seconds * 0.9)
        )
        center = alert.width // 2
        radius = round(geometry.R_MID * alert.width / geometry.LOG_SIZE)
        self.assertTrue(_is_blue(alert.getpixel((center, center - radius))))
        self.assertGreater(_blue_count(alert), _blue_count(normal))

    def test_pause_button_toggles_icon(self) -> None:
        running = self.renderer.render(make_snapshot(DEFAULT_EVENTS, 0))
        paused = self.renderer.render(
            make_snapshot(DEFAULT_EVENTS, 0, paused=True)
        )
        diff = 0
        for y in range(272, 310):
            for x in range(178, 223):
                a = running.getpixel((x, y))
                b = paused.getpixel((x, y))
                diff += sum(abs(u - v) for u, v in zip(a, b))
        self.assertGreater(diff, 5000)

    def test_switch_arrows_are_visible(self) -> None:
        image = self.renderer.render(make_snapshot(DEFAULT_EVENTS, 0))
        for cx in (
            geometry.CENTER - geometry.ARROW_OFFSET,
            geometry.CENTER + geometry.ARROW_OFFSET,
        ):
            brightest = 0
            for dx in range(-10, 11):
                for dy in range(-10, 11):
                    pixel = image.getpixel(
                        (int(cx) + dx, int(geometry.ARROW_Y) + dy)
                    )
                    brightest = max(brightest, pixel[2] - pixel[0])
            self.assertGreater(brightest, 40, cx)

    def test_alert_glow_spreads_outward(self) -> None:
        glow = self.renderer._alert_glow
        center = glow.width // 2
        inner = glow.getpixel((center + 176, center))[3]
        outer = glow.getpixel((center + 192, center))[3]
        self.assertGreater(inner, 20)
        self.assertLess(outer, inner)

    def test_alert_glow_pulses(self) -> None:
        center = self.renderer._alert_glow.width // 2
        point = (center + 176, center)
        bright = self.renderer._glow_frame(1.0).getpixel(point)[3]
        dim = self.renderer._glow_frame(0.5).getpixel(point)[3]
        self.assertGreater(bright, dim)

    def test_handle_marks_are_visible(self) -> None:
        image = self.renderer.render(make_snapshot(DEFAULT_EVENTS, 0))
        for name, (x, y) in geometry.handle_positions().items():
            alpha = sum(
                image.getpixel((int(x) + dx, int(y) + dy))[3]
                for dx in range(-7, 8)
                for dy in range(-7, 8)
            )
            self.assertGreater(alpha, 0, name)

    def test_text_changes_with_event(self) -> None:
        first = self.renderer.render(make_snapshot(DEFAULT_EVENTS, 0))
        second = self.renderer.render(make_snapshot(DEFAULT_EVENTS, 1))
        center = first.width // 2
        diff = 0
        for y in range(center - 70, center + 70, 3):
            for x in range(center - 120, center + 120, 3):
                a = first.getpixel((x, y))
                b = second.getpixel((x, y))
                diff += abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
        self.assertGreater(diff, 10000)

    def test_theme_ring_width_and_colors_apply(self) -> None:
        theme = get_theme("tech")
        self.assertEqual(theme.ring, (38, 108, 255))
        image = RingRenderer(theme=theme).render(make_snapshot(DEFAULT_EVENTS, 0))
        pixels = [
            image.getpixel((200, 200 + offset))
            for offset in range(155, 175)
        ]
        self.assertTrue(any(_is_blue(pixel) for pixel in pixels))


if __name__ == "__main__":
    unittest.main()
