"""DevAlarm 程序员闹钟入口。

``--windowed`` 打包后没有控制台，启动异常写入
``%APPDATA%\\DevAlarm\\error.log``，方便用户反馈问题。
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime


def _log_error() -> None:
    try:
        from devalarm.store import config_dir

        path = config_dir() / "error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 启动失败\n"
            )
            traceback.print_exc(file=handle)
    except Exception:  # noqa: BLE001 - 日志失败不能掩盖原始异常
        pass
    if sys.stderr is not None:
        traceback.print_exc()


def main() -> int:
    try:
        from devalarm.ui import run

        run()
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001
        _log_error()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
