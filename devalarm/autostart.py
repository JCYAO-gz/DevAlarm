"""开机自动启动：维护当前用户注册表 Run 项，无需管理员权限。

写入 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 的 ``DevAlarm`` 值：

- 打包运行（PyInstaller）时指向 exe 自身；
- 源码运行时指向 ``pythonw.exe main.py``，避免每次启动弹出控制台。

每次程序启动都会按``Config.autostart``重写或删除该项，程序被移动、
重新打包后路径会自动修正。非 Windows 平台静默跳过。
"""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DevAlarm"


def launch_command() -> str:
    """当前进程对应的开机启动命令（带引号，路径含空格也安全）。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else python
    return f'"{interpreter}" "{main_py}"'


def is_enabled() -> bool:
    """注册表启动项是否已存在且指向当前程序的启动命令。"""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    return str(value) == launch_command()


def set_enabled(enabled: bool) -> None:
    """写入或删除开机启动项；注册表访问失败时抛出 OSError 由调用方降级。"""
    if sys.platform != "win32":
        return
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            return
        try:
            winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
