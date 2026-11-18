from __future__ import annotations

import unittest

from devalarm.core import (
    DEFAULT_EVENTS,
    Event,
    Cycle,
    PHASE_ALERT,
    PHASE_RUNNING,
    format_duration,
    format_minutes_input,
    make_snapshot,
)


def events(*specs: tuple[str, int, str]) -> tuple[Event, ...]:
    return tuple(
        Event(uid=f"e{i}", name=name, seconds=seconds, reminder=reminder)
        for i, (name, seconds, reminder) in enumerate(specs)
    )


class EventTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        self.assertEqual(len(DEFAULT_EVENTS), 3)
        self.assertEqual([e.name for e in DEFAULT_EVENTS], ["喝水", "站立", "坐"])
        self.assertEqual([e.seconds for e in DEFAULT_EVENTS], [60, 120, 180])
        self.assertTrue(all(e.reminder == "时间到了！" for e in DEFAULT_EVENTS))

    def test_rejects_bad_fields(self) -> None:
        with self.assertRaises(ValueError):
            Event("e1", "", 60)
        with self.assertRaises(ValueError):
            Event("e1", "名称太长" * 4, 60)
        with self.assertRaises(ValueError):
            Event("e1", "坐", 0)
        with self.assertRaises(ValueError):
            Event("e1", "坐", 60, "提醒文案" * 10)
        with self.assertRaises(ValueError):
            Event("", "坐", 60)

    def test_display_reminder_falls_back(self) -> None:
        self.assertEqual(Event("e1", "坐", 60).display_reminder, "时间到了！")
        self.assertEqual(Event("e1", "坐", 60, "动一动").display_reminder, "动一动")


class FormatTests(unittest.TestCase):
    def test_duration(self) -> None:
        self.assertEqual(format_duration(30), "30s")
        self.assertEqual(format_duration(2400), "40min")
        self.assertEqual(format_duration(90), "1.5min")
        self.assertEqual(format_minutes_input(90), "1.5")
        self.assertEqual(format_minutes_input(2400), "40")


class CycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = events(("坐", 10, "起来"), ("站", 5, "坐下"))

    def test_enters_alert_at_deadline(self) -> None:
        cycle = Cycle(self.items, alert_seconds=8)
        snap = cycle.tick(0.0)
        self.assertEqual(snap.phase, PHASE_RUNNING)
        self.assertFalse(snap.entered_alert)
        snap = cycle.tick(10.0)
        self.assertEqual(snap.phase, PHASE_ALERT)
        self.assertTrue(snap.entered_alert)
        self.assertEqual(snap.index, 0)
        self.assertAlmostEqual(snap.alert_remaining, 8.0)
        self.assertEqual(snap.progress, 1.0)
        self.assertEqual(snap.alert_text, "起来")

    def test_alert_freezes_and_auto_advances_once(self) -> None:
        cycle = Cycle(self.items, alert_seconds=10)
        cycle.tick(0.0)
        cycle.tick(10.0)  # 进入提醒
        snap = cycle.tick(15.0)  # 提醒中，不累计事件时间
        self.assertEqual(snap.phase, PHASE_ALERT)
        self.assertAlmostEqual(snap.elapsed, 10.0)
        self.assertAlmostEqual(snap.alert_remaining, 5.0)
        self.assertFalse(snap.advanced)

        snap = cycle.tick(25.0)  # 提醒超时，只前进一个事件
        self.assertEqual(snap.phase, PHASE_RUNNING)
        self.assertEqual(snap.index, 1)
        self.assertEqual(snap.elapsed, 0.0)
        self.assertTrue(snap.advanced)

    def test_huge_jump_enters_alert_only_once(self) -> None:
        cycle = Cycle(self.items, alert_seconds=5)
        cycle.tick(0.0)
        snap = cycle.tick(3600.0)  # 休眠一小时
        self.assertEqual(snap.phase, PHASE_ALERT)
        self.assertEqual(snap.index, 0)
        snap = cycle.tick(7200.0)
        self.assertEqual(snap.phase, PHASE_RUNNING)
        self.assertEqual(snap.index, 1)
        self.assertEqual(snap.elapsed, 0.0)

    def test_dismiss_advances_immediately(self) -> None:
        cycle = Cycle(self.items, alert_seconds=30)
        cycle.tick(0.0)
        cycle.tick(10.0)
        snap = cycle.dismiss(12.0)
        self.assertTrue(snap.advanced)
        self.assertEqual(snap.index, 1)
        self.assertEqual(snap.phase, PHASE_RUNNING)
        self.assertEqual(snap.elapsed, 0.0)
        snap = cycle.tick(12.0)
        self.assertFalse(snap.advanced)
        self.assertEqual(snap.index, 1)

    def test_dismiss_ignored_while_running(self) -> None:
        cycle = Cycle(self.items)
        cycle.tick(0.0)
        snap = cycle.dismiss(1.0)
        self.assertEqual(snap.index, 0)
        self.assertFalse(snap.advanced)

    def test_alert_seconds_are_clamped(self) -> None:
        cycle = Cycle(self.items, alert_seconds=999)
        self.assertEqual(cycle.alert_seconds, 120)
        cycle = Cycle(self.items, alert_seconds=0)
        self.assertEqual(cycle.alert_seconds, 1)

    def test_set_events_preserves_current_by_uid(self) -> None:
        cycle = Cycle(self.items)
        cycle.tick(0.0)
        cycle.tick(5.0)
        new_items = (
            Event("e0", "坐", 20 * 60, "起来"),
            Event("e1", "站", 5, "坐下"),
        )
        cycle.set_events(new_items)
        snap = cycle.tick(5.0)
        self.assertEqual(snap.current.uid, "e0")
        self.assertAlmostEqual(snap.elapsed, 5.0)
        self.assertEqual(snap.current.seconds, 1200)

    def test_set_events_resets_when_current_too_short(self) -> None:
        cycle = Cycle(self.items)
        cycle.tick(0.0)
        cycle.tick(8.0)
        cycle.set_events((Event("e0", "坐", 5), Event("e1", "站", 5)))
        snap = cycle.tick(8.0)
        self.assertEqual(snap.index, 0)
        self.assertEqual(snap.elapsed, 0.0)

    def test_set_events_removed_current_restarts_first(self) -> None:
        cycle = Cycle(self.items)
        cycle.tick(0.0)
        cycle.tick(5.0)
        cycle.set_events((Event("e9", "新事件", 60),))
        snap = cycle.tick(5.0)
        self.assertEqual(snap.index, 0)
        self.assertEqual(snap.current.uid, "e9")
        self.assertEqual(snap.elapsed, 0.0)

    def test_set_events_while_alerting_stops_alert(self) -> None:
        cycle = Cycle(self.items, alert_seconds=10)
        cycle.tick(0.0)
        cycle.tick(10.0)
        self.assertTrue(cycle.alerting)
        cycle.set_events(self.items, alert_seconds=6)
        snap = cycle.tick(10.0)
        self.assertFalse(snap.alerting)
        self.assertEqual(snap.index, 0)
        self.assertEqual(cycle.alert_seconds, 6)

    def test_pause_freezes_elapsed_and_resumes(self) -> None:
        cycle = Cycle(self.items)
        cycle.tick(0.0)
        cycle.tick(4.0)
        self.assertTrue(cycle.toggle_pause())
        self.assertTrue(cycle.paused)
        snap = cycle.tick(9.0)  # 暂停期间时间流逝不累计
        self.assertTrue(snap.paused)
        self.assertAlmostEqual(snap.elapsed, 4.0)
        self.assertFalse(cycle.toggle_pause())
        snap = cycle.tick(10.0)
        self.assertFalse(snap.paused)
        self.assertAlmostEqual(snap.elapsed, 5.0)

    def test_paused_never_enters_alert(self) -> None:
        cycle = Cycle(self.items, alert_seconds=5)
        cycle.tick(0.0)
        cycle.tick(9.0)
        cycle.set_paused(True)
        snap = cycle.tick(120.0)
        self.assertEqual(snap.phase, PHASE_RUNNING)
        self.assertAlmostEqual(snap.elapsed, 9.0)

    def test_toggle_pause_ignored_during_alert(self) -> None:
        cycle = Cycle(self.items, alert_seconds=10)
        cycle.tick(0.0)
        cycle.tick(10.0)
        self.assertTrue(cycle.alerting)
        self.assertFalse(cycle.toggle_pause())
        self.assertFalse(cycle.paused)
        self.assertFalse(cycle.tick(11.0).paused)

    def test_switch_moves_to_neighbour_and_keeps_pause(self) -> None:
        cycle = Cycle(self.items)
        cycle.tick(0.0)
        cycle.tick(3.0)
        cycle.toggle_pause()
        snap = cycle.switch(1, 4.0)
        self.assertEqual(snap.index, 1)
        self.assertEqual(snap.elapsed, 0.0)
        self.assertTrue(snap.paused)
        self.assertEqual(snap.current.uid, "e1")
        snap = cycle.switch(-1, 4.0)  # 向前回绕到上一个事件
        self.assertEqual(snap.index, 0)
        self.assertTrue(snap.paused)
        self.assertEqual(cycle.switch(-1, 4.0).index, 1)

    def test_switch_during_alert_cancels_it(self) -> None:
        cycle = Cycle(self.items, alert_seconds=10)
        cycle.tick(0.0)
        cycle.tick(10.0)
        self.assertTrue(cycle.alerting)
        snap = cycle.switch(1, 11.0)
        self.assertFalse(snap.alerting)
        self.assertFalse(snap.paused)
        self.assertEqual(snap.index, 1)
        self.assertAlmostEqual(cycle.tick(12.0).elapsed, 1.0)

    def test_snapshot_upcoming_wraps(self) -> None:
        snap = make_snapshot(self.items, 1, elapsed=1.0)
        self.assertEqual(snap.upcoming.uid, "e0")
        self.assertEqual(snap.total, 2)
        self.assertAlmostEqual(snap.remaining, 4.0)

    def test_make_alert_snapshot(self) -> None:
        snap = make_snapshot(
            self.items, 0, elapsed=10, phase=PHASE_ALERT,
            alert_elapsed=3, alert_seconds=8,
        )
        self.assertTrue(snap.alerting)
        self.assertAlmostEqual(snap.alert_remaining, 5.0)
        self.assertEqual(snap.alert_total, 8)


if __name__ == "__main__":
    unittest.main()
