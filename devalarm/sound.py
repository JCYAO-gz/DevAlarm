"""循环铃声控制。

使用 ``winsound`` 异步循环播放 WAV；文件缺失、没有声卡或被系统禁止时
静默降级，绝不影响计时与界面。
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import winsound
except ImportError:  # 非 Windows 平台仅用于导入测试
    winsound = None  # type: ignore[assignment]


class AlarmSound:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._playing = False
        self._warned = False

    @property
    def available(self) -> bool:
        return winsound is not None and self.path.exists()

    def start(self) -> bool:
        if winsound is None:
            return False
        if not self.path.exists():
            self._warn(f"铃声文件不存在：{self.path}")
            return False
        try:
            winsound.PlaySound(
                str(self.path),
                winsound.SND_FILENAME
                | winsound.SND_ASYNC
                | winsound.SND_LOOP
                | winsound.SND_NODEFAULT,
            )
        except (RuntimeError, OSError) as exc:
            self._warn(f"播放铃声失败：{exc}")
            return False
        self._playing = True
        return True

    def preview(self) -> bool:
        """试听：只播放一遍，不循环、不影响正在进行的提醒。"""
        if winsound is None:
            return False
        if not self.path.exists():
            self._warn(f"铃声文件不存在：{self.path}")
            return False
        try:
            winsound.PlaySound(
                str(self.path),
                winsound.SND_FILENAME
                | winsound.SND_ASYNC
                | winsound.SND_NODEFAULT,
            )
        except (RuntimeError, OSError) as exc:
            self._warn(f"播放铃声失败：{exc}")
            return False
        return True

    def stop(self) -> None:
        if winsound is None or not self._playing:
            self._playing = False
            return
        try:
            winsound.PlaySound(None, 0)
        except (RuntimeError, OSError):
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except (RuntimeError, OSError):
                pass
        self._playing = False

    @property
    def playing(self) -> bool:
        return self._playing

    def _warn(self, message: str) -> None:
        if self._warned:
            return
        self._warned = True
        if sys.stderr is not None:
            print(f"[DevAlarm] {message}", file=sys.stderr)
