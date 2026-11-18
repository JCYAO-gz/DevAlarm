from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from devalarm.core import DEFAULT_EVENTS, LEGACY_DEFAULT_EVENTS, Event
from devalarm.store import Config, load_config, parse_events, save_config
from devalarm.theme import DEFAULT_THEME_KEY


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_file_uses_defaults(self) -> None:
        config = load_config(self.path)
        self.assertEqual(len(config.events), len(DEFAULT_EVENTS))
        self.assertEqual(config.alert_seconds, 10)
        self.assertEqual(config.scale, 1.0)
        self.assertEqual(config.theme, DEFAULT_THEME_KEY)
        self.assertIsNone(config.window_pos)
        self.assertTrue(config.autostart)

    def test_roundtrip(self) -> None:
        config = Config(
            events=[
                Event("a1", "专注", 25 * 60, "休息 5 分钟"),
                Event("b2", "休息", 5 * 60, ""),
            ],
            alert_seconds=12,
            scale=1.25,
            window_pos=(120, 340),
            theme="tech",
        )
        save_config(config, self.path)
        loaded = load_config(self.path)
        self.assertEqual(loaded.events, config.events)
        self.assertEqual(loaded.alert_seconds, 12)
        self.assertEqual(loaded.scale, 1.25)
        self.assertEqual(loaded.window_pos, (120, 340))
        self.assertEqual(loaded.theme, "tech")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["events"][0]["kind"], "interval")
        self.assertEqual(data["events"][0]["uid"], "a1")

    def test_autostart_roundtrip(self) -> None:
        config = Config(autostart=False)
        save_config(config, self.path)
        self.assertFalse(load_config(self.path).autostart)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIs(data["autostart"], False)

    def test_autostart_invalid_value_falls_back_to_true(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "events": [{"name": "坐", "seconds": 60}],
                    "autostart": "no",
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(load_config(self.path).autostart)

    def test_legacy_defaults_are_upgraded_and_persisted(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "events": [
                        {
                            "uid": e.uid,
                            "kind": e.kind,
                            "name": e.name,
                            "seconds": e.seconds,
                            "reminder": e.reminder,
                        }
                        for e in LEGACY_DEFAULT_EVENTS
                    ],
                    "alert_seconds": 15,
                    "scale": 1.25,
                    "window": [300, 400],
                    "theme": "tech",
                }
            ),
            encoding="utf-8",
        )
        config = load_config(self.path)
        self.assertEqual(config.events, list(DEFAULT_EVENTS))
        # 其他设置保留
        self.assertEqual(config.alert_seconds, 15)
        self.assertEqual(config.scale, 1.25)
        self.assertEqual(config.window_pos, (300, 400))
        # 已写回文件，下次启动不会再走旧事件
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([e["name"] for e in saved["events"]], ["喝水", "站立", "坐"])
        self.assertEqual(saved["scale"], 1.25)

    def test_customized_events_are_not_migrated(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "events": [
                        {"uid": "sit", "name": "坐", "seconds": 2400,
                         "reminder": "我改过的文案"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        config = load_config(self.path)
        self.assertEqual(config.events[0].reminder, "我改过的文案")

    def test_corrupt_file_falls_back(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        config = load_config(self.path)
        self.assertEqual(len(config.events), len(DEFAULT_EVENTS))

    def test_non_object_root_falls_back(self) -> None:
        self.path.write_text("[]", encoding="utf-8")
        self.assertEqual(len(load_config(self.path).events), len(DEFAULT_EVENTS))

    def test_invalid_events_fall_back(self) -> None:
        self.path.write_text(
            json.dumps({"version": 1, "events": []}), encoding="utf-8"
        )
        self.assertEqual(len(load_config(self.path).events), len(DEFAULT_EVENTS))

    def test_clamps_values_and_theme(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "events": [{"name": "坐", "seconds": 60}],
                    "alert_seconds": 9999,
                    "scale": 9,
                    "theme": "missing",
                    "window": [-20, 40],
                }
            ),
            encoding="utf-8",
        )
        config = load_config(self.path)
        self.assertEqual(config.alert_seconds, 120)
        self.assertEqual(config.scale, 2.0)
        self.assertEqual(config.theme, DEFAULT_THEME_KEY)
        self.assertEqual(config.window_pos, (-20, 40))

    def test_alert_scale_low_clamped(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "events": [{"name": "坐", "seconds": 60}],
                    "alert_seconds": -3,
                    "scale": 0.1,
                }
            ),
            encoding="utf-8",
        )
        config = load_config(self.path)
        self.assertEqual(config.alert_seconds, 1)
        self.assertEqual(config.scale, 0.6)

    def test_missing_uid_is_generated(self) -> None:
        events = parse_events(
            [{"name": "坐", "seconds": 60}, {"name": "站", "seconds": 120}]
        )
        self.assertTrue(events[0].uid)
        self.assertNotEqual(events[0].uid, events[1].uid)

    def test_duplicate_uid_is_replaced(self) -> None:
        events = parse_events(
            [
                {"uid": "same", "name": "坐", "seconds": 60},
                {"uid": "same", "name": "站", "seconds": 120},
            ]
        )
        self.assertEqual(events[0].uid, "same")
        self.assertNotEqual(events[1].uid, "same")

    def test_unknown_kind_is_skipped(self) -> None:
        events = parse_events(
            [
                {"name": "坐", "seconds": 60},
                {"kind": "alarm", "name": "9 点提醒", "seconds": 60},
            ]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "坐")

    def test_all_unknown_kinds_is_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_events([{"kind": "alarm", "name": "闹钟", "seconds": 60}])

    def test_event_validation(self) -> None:
        with self.assertRaises(ValueError):
            parse_events([{"name": "", "seconds": 60}])
        with self.assertRaises(ValueError):
            parse_events([{"name": "坐", "seconds": 0}])
        with self.assertRaises(ValueError):
            parse_events([{"name": "坐", "seconds": "60"}])
        with self.assertRaises(ValueError):
            parse_events([{"name": "坐", "seconds": 60, "reminder": "长" * 30}])

    def test_save_is_valid_json_and_leaves_no_temp(self) -> None:
        save_config(Config(), self.path)
        json.loads(self.path.read_text(encoding="utf-8"))
        leftovers = list(self.path.parent.glob("config-*.tmp"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
