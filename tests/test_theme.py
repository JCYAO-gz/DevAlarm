from __future__ import annotations

import unittest

from devalarm.theme import DEFAULT_THEME_KEY, THEMES, Theme, get_theme, list_themes


class ThemeTests(unittest.TestCase):
    def test_default_theme_registered(self) -> None:
        self.assertIn("tech", THEMES)
        self.assertEqual(get_theme("tech").key, "tech")
        self.assertEqual(get_theme(None).key, DEFAULT_THEME_KEY)
        self.assertEqual(get_theme("missing").key, DEFAULT_THEME_KEY)

    def test_only_tech_for_now(self) -> None:
        self.assertEqual([theme.key for theme in list_themes()], ["tech"])

    def test_theme_is_immutable(self) -> None:
        theme = get_theme("tech")
        with self.assertRaises(Exception):
            theme.key = "other"  # type: ignore[misc]

    def test_colors_and_motion_are_sane(self) -> None:
        theme = get_theme("tech")
        for color in (
            theme.disc, theme.disc_hi, theme.grid, theme.track,
            theme.ring, theme.ring_hi, theme.ring_light, theme.glow,
            theme.text, theme.text_dim, theme.alert_ring, theme.alert_hi,
            theme.handle, theme.handle_active,
        ):
            self.assertEqual(len(color), 3)
            self.assertTrue(all(0 <= value <= 255 for value in color))
        self.assertGreater(theme.ring_width, 0)
        self.assertGreater(theme.pulse_hz, 0)
        self.assertGreater(theme.shake_hz, 0)
        self.assertGreater(theme.shake_amplitude_ratio, 0)

    def test_custom_theme_can_be_used_directly(self) -> None:
        theme = Theme(
            key="custom",
            name="自定义",
            description="",
            disc=(0, 0, 0),
            disc_hi=(1, 1, 1),
            disc_alpha=200,
            grid=(2, 2, 2),
            track=(3, 3, 3),
            ring=(4, 4, 4),
            ring_hi=(5, 5, 5),
            ring_light=(6, 6, 6),
            glow=(7, 7, 7),
            text=(8, 8, 8),
            text_dim=(9, 9, 9),
            alert_ring=(10, 10, 10),
            alert_hi=(11, 11, 11),
            handle=(12, 12, 12),
            handle_active=(13, 13, 13),
        )
        self.assertEqual(get_theme(theme).key, "custom")


if __name__ == "__main__":
    unittest.main()
