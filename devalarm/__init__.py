"""DevAlarm 程序员闹钟。"""

from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "DevAlarm"
APP_TITLE = "DevAlarm 程序员闹钟"
__version__ = "1.0"
APP_VERSION = f"V{__version__}"
APP_AUTHOR = "JCYAO"
APP_DESCRIPTION = (
    "一个常驻桌面的圆形倒计时闹钟：蓝色科技圆环随剩余时间缩短，"
    "中央显示当前事件与总时长。到点后窗口左右摇晃、发光并循环响铃，"
    "点击圆环立即进入下一事件。支持多事件循环、拖拽移动、左右下角缩放，"
    "事件与提醒时长可在设置中修改并自动保存。"
)

__author__ = APP_AUTHOR


def resource_path(*parts: str) -> Path:
    """定位打包资源：开发时取项目目录，PyInstaller 单文件时取解包目录。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


ICON_FILE = resource_path("assets", "devalarm.ico")
SOUND_FILE = resource_path("assets", "alert.wav")
