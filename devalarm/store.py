"""配置读写：%APPDATA%\\DevAlarm\\config.json。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core import (
    DEFAULT_ALERT_SECONDS,
    DEFAULT_EVENTS,
    LEGACY_DEFAULT_EVENTS,
    MAX_ALERT_SECONDS,
    MAX_EVENT_SECONDS,
    MAX_NAME_LEN,
    MAX_REMINDER_LEN,
    MIN_ALERT_SECONDS,
    Event,
    clamp_alert_seconds,
)
from .theme import DEFAULT_THEME_KEY, THEMES

APP_DIR_NAME = "DevAlarm"
CONFIG_VERSION = 1
MIN_SCALE = 0.6
MAX_SCALE = 2.0


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


@dataclass
class Config:
    events: list[Event] = field(default_factory=lambda: list(DEFAULT_EVENTS))
    alert_seconds: int = DEFAULT_ALERT_SECONDS
    scale: float = 1.0
    window_pos: tuple[int, int] | None = None
    theme: str = DEFAULT_THEME_KEY
    autostart: bool = True


def parse_events(raw: Any) -> list[Event]:
    """把 JSON 中的 events 解析为 Event 列表，非法数据抛 ValueError。

    未知 ``kind``（例如未来才会支持的绝对时间闹钟）暂时跳过，
    避免旧版本读取新配置时直接崩溃。
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("至少需要配置一个循环事件")
    events: list[Event] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("事件配置格式错误")
        kind = str(item.get("kind", "interval")).strip().lower()
        if kind != "interval":
            print(
                f"[DevAlarm] 暂不支持的事件类型 {kind!r}，已跳过",
                file=sys.stderr,
            )
            continue
        uid = str(item.get("uid", "")).strip()
        if not uid or uid in seen:
            uid = uuid.uuid4().hex[:8]
            while uid in seen:
                uid = uuid.uuid4().hex[:8]
        seen.add(uid)

        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError("事件名称不能为空")
        if len(name) > MAX_NAME_LEN:
            raise ValueError(f"事件名称不能超过 {MAX_NAME_LEN} 个字符")

        seconds = item.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError(f"事件“{name}”的时长格式错误")
        seconds = int(round(float(seconds)))
        if not 1 <= seconds <= MAX_EVENT_SECONDS:
            raise ValueError(f"事件“{name}”的时长必须在 1 秒到 24 小时之间")

        reminder = str(item.get("reminder", "") or "").strip()
        if len(reminder) > MAX_REMINDER_LEN:
            raise ValueError(
                f"事件“{name}”的提醒文案不能超过 {MAX_REMINDER_LEN} 个字符"
            )
        events.append(Event(uid=uid, name=name, seconds=seconds, reminder=reminder))
    if not events:
        raise ValueError("至少需要配置一个循环事件")
    return events


def _parse_theme(raw: Any) -> str:
    if isinstance(raw, str) and raw in THEMES:
        return raw
    return DEFAULT_THEME_KEY


def _clamp_scale(value: Any) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(MAX_SCALE, max(MIN_SCALE, scale))


def _clamp_alert(value: Any) -> int:
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_ALERT_SECONDS
    return min(MAX_ALERT_SECONDS, max(MIN_ALERT_SECONDS, seconds))


def _parse_bool(raw: Any, default: bool) -> bool:
    """JSON 布尔容错：缺省或类型不对时用默认值。"""
    if isinstance(raw, bool):
        return raw
    return default


def _parse_pos(raw: Any) -> tuple[int, int] | None:
    if (
        isinstance(raw, (list, tuple))
        and len(raw) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in raw)
    ):
        return int(raw[0]), int(raw[1])
    return None


def _is_legacy_defaults(events: list[Event]) -> bool:
    """事件是否仍是旧版本那一组未改动过的默认值。"""
    fields = lambda items: [  # noqa: E731 - 局部小工具
        (e.uid, e.name, e.seconds, e.reminder) for e in items
    ]
    return fields(events) == fields(LEGACY_DEFAULT_EVENTS)


def load_config(path: Path | None = None) -> Config:
    """读取配置；文件缺失或损坏时回退到默认配置。

    若配置文件里仍是旧版默认事件（用户没改过），自动升级为新默认事件，
    并保留提醒时长、缩放、窗口位置与主题。
    """
    path = path or config_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("根节点不是对象")
        config = Config(
            events=parse_events(data.get("events")),
            alert_seconds=_clamp_alert(
                data.get("alert_seconds", DEFAULT_ALERT_SECONDS)
            ),
            scale=_clamp_scale(data.get("scale", 1.0)),
            window_pos=_parse_pos(data.get("window")),
            theme=_parse_theme(data.get("theme")),
            autostart=_parse_bool(data.get("autostart"), True),
        )
        if _is_legacy_defaults(config.events):
            config.events = list(DEFAULT_EVENTS)
            try:
                save_config(config, path)
            except Exception as exc:  # noqa: BLE001 - 写回失败不影响启动
                print(f"[DevAlarm] 升级默认事件后写回配置失败：{exc}", file=sys.stderr)
        return config
    except FileNotFoundError:
        return Config()
    except Exception as exc:  # noqa: BLE001 - 配置损坏不应阻止程序启动
        print(f"[DevAlarm] 读取配置失败，使用默认配置：{exc}", file=sys.stderr)
        return Config()


def save_config(config: Config, path: Path | None = None) -> None:
    """原子写入配置文件。"""
    path = path or config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CONFIG_VERSION,
        "events": [
            {
                "uid": event.uid,
                "kind": event.kind,
                "name": event.name,
                "seconds": int(event.seconds),
                "reminder": event.reminder,
            }
            for event in config.events
        ],
        "alert_seconds": clamp_alert_seconds(config.alert_seconds),
        "scale": round(_clamp_scale(config.scale), 2),
        "window": list(config.window_pos) if config.window_pos else None,
        "theme": _parse_theme(config.theme),
        "autostart": bool(config.autostart),
    }
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        prefix="config-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
