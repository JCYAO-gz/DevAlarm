"""DevAlarm 核心计时逻辑。

本模块不依赖任何 UI 库，时间源由调用方注入（通常是 ``time.monotonic()``），
方便单元测试。状态机只有两态：

    RUNNING --倒计时结束--> ALERT --点击 / 超时--> RUNNING（下一事件）

提醒期间不累计任何事件时间；大量时间跳变（休眠、卡顿）最多触发一次提醒，
避免启动后一下子重放十几个事件。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Sequence

MIN_EVENT_SECONDS = 1
MAX_EVENT_SECONDS = 24 * 3600
MAX_NAME_LEN = 12
MAX_REMINDER_LEN = 24
DEFAULT_ALERT_SECONDS = 10
MIN_ALERT_SECONDS = 1
MAX_ALERT_SECONDS = 120

PHASE_RUNNING = "running"
PHASE_ALERT = "alert"

FALLBACK_REMINDER = "时间到了！"


@dataclass(frozen=True)
class Event:
    """一个循环事件，例如「坐 40 分钟」。

    ``kind`` 预留给未来的绝对时间闹钟（``alarm``）。当前版本只产生
    ``interval``，调度器也按循环间隔处理；后续可在 ``Cycle`` 中按
    ``kind`` 分流。
    """

    uid: str
    name: str
    seconds: int
    reminder: str = ""
    kind: str = "interval"

    def __post_init__(self) -> None:
        uid = str(self.uid).strip()
        name = str(self.name).strip()
        reminder = str(self.reminder or "").strip()
        kind = str(self.kind or "interval").strip()
        if not uid:
            raise ValueError("事件 id 不能为空")
        if not name:
            raise ValueError("事件名称不能为空")
        if len(name) > MAX_NAME_LEN:
            raise ValueError(f"事件名称不能超过 {MAX_NAME_LEN} 个字符")
        if isinstance(self.seconds, bool) or not isinstance(self.seconds, int):
            raise ValueError("事件时长必须是整数秒")
        if not MIN_EVENT_SECONDS <= self.seconds <= MAX_EVENT_SECONDS:
            raise ValueError("单个事件时长必须在 1 秒到 24 小时之间")
        if len(reminder) > MAX_REMINDER_LEN:
            raise ValueError(f"提醒文案不能超过 {MAX_REMINDER_LEN} 个字符")
        if not kind:
            raise ValueError("事件类型不能为空")
        object.__setattr__(self, "uid", uid)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "reminder", reminder)
        object.__setattr__(self, "kind", kind)

    @property
    def display_reminder(self) -> str:
        return self.reminder or FALLBACK_REMINDER


DEFAULT_EVENTS: tuple[Event, ...] = (
    Event("water", "喝水", 60, "时间到了！"),
    Event("stand", "站立", 2 * 60, "时间到了！"),
    Event("sit", "坐", 3 * 60, "时间到了！"),
)

# 旧版本的默认事件。配置文件里若仍是这一组（说明用户没改过），
# 读取时平滑升级为新的 DEFAULT_EVENTS。不要修改，仅供迁移判断。
LEGACY_DEFAULT_EVENTS: tuple[Event, ...] = (
    Event("sit", "坐", 40 * 60, "站起来活动一下，保护好腰背"),
    Event("stand", "站", 20 * 60, "坐下休息，或者去接杯水"),
    Event("walk", "走动", 3 * 60, "回到座位，继续专注"),
)


def new_uid(taken: set[str] | None = None) -> str:
    taken = taken or set()
    while True:
        uid = uuid.uuid4().hex[:8]
        if uid not in taken:
            return uid


def clamp_alert_seconds(value: int | float) -> int:
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_ALERT_SECONDS
    return max(MIN_ALERT_SECONDS, min(MAX_ALERT_SECONDS, seconds))


def format_duration(seconds: int | float) -> str:
    """总时长 -> 圆环中央的 “40min” / “1.5min” / “30s”。"""
    total = max(0, int(round(float(seconds))))
    if total < 60:
        return f"{total}s"
    minutes = total / 60.0
    if abs(minutes - round(minutes)) < 1e-9:
        return f"{int(round(minutes))}min"
    return f"{minutes:.1f}min"


def format_minutes_input(seconds: int) -> str:
    """配置页分钟输入框的初值：整分钟不带小数点，其余最多三位小数。"""
    minutes = seconds / 60.0
    if abs(minutes - round(minutes)) < 1e-6:
        return str(int(round(minutes)))
    return f"{minutes:.3f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class Snapshot:
    """某一时刻的对外状态，渲染层只依赖它。"""

    index: int
    total: int
    current: Event
    upcoming: Event
    elapsed: float
    remaining: float
    progress: float
    phase: str
    alert_text: str
    alert_total: int
    alert_remaining: float
    entered_alert: bool = False
    advanced: bool = False
    paused: bool = False

    @property
    def alerting(self) -> bool:
        return self.phase == PHASE_ALERT


def _upcoming(events: Sequence[Event], index: int) -> Event:
    return events[(index + 1) % len(events)]


def make_snapshot(
    events: Sequence[Event],
    index: int,
    elapsed: float = 0.0,
    phase: str = PHASE_RUNNING,
    alert_elapsed: float = 0.0,
    alert_seconds: int = DEFAULT_ALERT_SECONDS,
    entered_alert: bool = False,
    advanced: bool = False,
    paused: bool = False,
) -> Snapshot:
    """根据事件列表直接构造快照，供预览与单元测试使用。"""
    events = tuple(events)
    if not events:
        raise ValueError("至少需要一个事件")
    if not 0 <= index < len(events):
        raise ValueError("index 越界")
    current = events[index]
    elapsed = max(0.0, min(float(elapsed), float(current.seconds)))
    total_alert = clamp_alert_seconds(alert_seconds)
    alerting = phase == PHASE_ALERT
    alert_remaining = (
        max(0.0, total_alert - float(alert_elapsed)) if alerting else 0.0
    )
    return Snapshot(
        index=index,
        total=len(events),
        current=current,
        upcoming=_upcoming(events, index),
        elapsed=elapsed,
        remaining=max(0.0, current.seconds - elapsed),
        progress=elapsed / current.seconds,
        phase=PHASE_ALERT if alerting else PHASE_RUNNING,
        alert_text=current.display_reminder,
        alert_total=total_alert,
        alert_remaining=alert_remaining,
        entered_alert=entered_alert,
        advanced=advanced,
        paused=bool(paused) and not alerting,
    )


class Cycle:
    """多事件循环 + 到点提醒状态机。

    用法::

        cycle = Cycle(events, alert_seconds=10)
        snap = cycle.tick(time.monotonic())   # 每帧调用一次
        if snap.alerting and clicked:
            snap = cycle.dismiss(time.monotonic())
    """

    def __init__(
        self,
        events: Sequence[Event],
        alert_seconds: int = DEFAULT_ALERT_SECONDS,
        index: int = 0,
        elapsed: float = 0.0,
    ) -> None:
        events = tuple(events)
        if not events:
            raise ValueError("至少需要一个事件")
        if not 0 <= index < len(events):
            raise ValueError("index 越界")
        self._events = events
        self._index = index
        self._elapsed = max(0.0, min(float(elapsed), float(events[index].seconds)))
        self._alert_seconds = clamp_alert_seconds(alert_seconds)
        self._last: float | None = None
        self._now = 0.0
        self._alert_end: float | None = None
        self._alert_total = 0
        self._paused = False

    # ------------------------------------------------------------------ 属性
    @property
    def events(self) -> tuple[Event, ...]:
        return self._events

    @property
    def index(self) -> int:
        return self._index

    @property
    def alert_seconds(self) -> int:
        return self._alert_seconds

    @property
    def alerting(self) -> bool:
        return self._alert_end is not None

    @property
    def paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------ 控制
    def tick(self, now: float) -> Snapshot:
        """推进到 now（单调时钟秒），返回当前状态快照。"""
        now = float(now)
        self._now = now
        entered_alert = False
        advanced = False

        if self._last is None:
            self._last = now
        dt = max(0.0, now - self._last)
        self._last = now

        if self._alert_end is not None:
            # 提醒期间不累计事件时间；超时只前进一个事件，丢弃溢出时间。
            if now >= self._alert_end - 1e-9:
                self._advance()
                advanced = True
        elif self._paused:
            # 暂停期间冻结已用时间，恢复后从原进度继续。
            pass
        else:
            self._elapsed += dt
            total = float(self._events[self._index].seconds)
            if self._elapsed >= total - 1e-9:
                self._elapsed = total
                self._alert_total = max(1, int(self._alert_seconds))
                self._alert_end = now + self._alert_total
                entered_alert = True

        return self._snapshot(entered_alert, advanced)

    def toggle_pause(self) -> bool:
        """开始 / 暂停计时，返回切换后的暂停状态；提醒中不生效。"""
        if self._alert_end is not None:
            self._paused = False
            return False
        self._paused = not self._paused
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused) and self._alert_end is None

    def switch(self, delta: int, now: float) -> Snapshot:
        """直接切换到上/下一个事件（``delta`` 为 -1/1），保留暂停状态。"""
        now = float(now)
        self._now = now
        self._last = now
        self._index = (self._index + int(delta)) % len(self._events)
        self._elapsed = 0.0
        self._alert_end = None
        self._alert_total = 0
        return self._snapshot()

    def dismiss(self, now: float) -> Snapshot:
        """提醒中点击：立即结束提醒并进入下一事件；非提醒状态无动作。"""
        now = float(now)
        self._now = now
        self._last = now
        if self._alert_end is not None:
            self._advance()
            return self._snapshot(advanced=True)
        return self._snapshot()

    def skip(self, now: float) -> Snapshot:
        """立即跳过当前事件（预留的调试 / 扩展能力）。"""
        now = float(now)
        self._now = now
        self._last = now
        self._advance()
        return self._snapshot(advanced=True)

    def set_events(
        self,
        events: Sequence[Event],
        alert_seconds: int | None = None,
    ) -> None:
        """热更新事件配置，尽量保留当前进度。

        - 按 ``uid`` 找到当前事件：保留已用时间；若新时长更短则重新计时。
        - 当前事件已删除，或保存时正处于提醒态：回到第一个事件 RUNNING。
        """
        events = tuple(events)
        if not events:
            raise ValueError("至少需要一个事件")
        if alert_seconds is not None:
            self._alert_seconds = clamp_alert_seconds(alert_seconds)

        was_alerting = self._alert_end is not None
        current_uid = self._events[self._index].uid
        self._events = events
        if was_alerting:
            self._index = 0
            self._elapsed = 0.0
            self._alert_end = None
            self._alert_total = 0
            return

        new_index = next(
            (i for i, event in enumerate(events) if event.uid == current_uid),
            None,
        )
        if new_index is None:
            self._index = 0
            self._elapsed = 0.0
            return
        self._index = new_index
        if self._elapsed >= events[new_index].seconds:
            self._elapsed = 0.0

    def snapshot(self) -> Snapshot:
        return self._snapshot()

    # ------------------------------------------------------------------ 内部
    def _advance(self) -> None:
        self._index = (self._index + 1) % len(self._events)
        self._elapsed = 0.0
        self._alert_end = None
        self._alert_total = 0

    def _snapshot(
        self,
        entered_alert: bool = False,
        advanced: bool = False,
    ) -> Snapshot:
        current = self._events[self._index]
        alerting = self._alert_end is not None
        alert_remaining = (
            max(0.0, self._alert_end - self._now) if alerting else 0.0
        )
        return Snapshot(
            index=self._index,
            total=len(self._events),
            current=current,
            upcoming=_upcoming(self._events, self._index),
            elapsed=self._elapsed,
            remaining=max(0.0, current.seconds - self._elapsed),
            progress=min(1.0, self._elapsed / current.seconds),
            phase=PHASE_ALERT if alerting else PHASE_RUNNING,
            alert_text=current.display_reminder,
            alert_total=self._alert_total,
            alert_remaining=alert_remaining,
            entered_alert=entered_alert,
            advanced=advanced,
            paused=self._paused and not alerting,
        )
