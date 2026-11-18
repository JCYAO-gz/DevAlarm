"""DevAlarm 悬浮窗口主循环与设置对话框。

窗口本身由 :mod:`devalarm.overlay` 创建并用分层窗口绘制；Tk 只负责
隐藏的对话框宿主与设置界面，主循环通过 ``after`` 每 50ms 推进一次
:class:`~devalarm.core.Cycle`。
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox, ttk

from PIL import Image

from . import (
    APP_AUTHOR,
    APP_DESCRIPTION,
    APP_TITLE,
    APP_VERSION,
    ICON_FILE,
    SOUND_FILE,
)
from . import autostart, geometry
from .core import (
    MAX_ALERT_SECONDS,
    MAX_EVENT_SECONDS,
    MAX_NAME_LEN,
    MAX_REMINDER_LEN,
    MIN_ALERT_SECONDS,
    Cycle,
    Event,
    clamp_alert_seconds,
    format_duration,
    format_minutes_input,
    new_uid,
)
from .overlay import OverlayWindow
from .render import RingRenderer
from .sound import AlarmSound
from .store import Config, config_file, load_config, save_config
from .theme import get_theme, list_themes

FRAME_MS = 50
ALERT_FRAME_MS = 33
RESIZE_FRAME_MS = 16

UI_FONT = ("Microsoft YaHei UI", 10)
UI_FONT_BOLD = ("Microsoft YaHei UI", 11, "bold")
UI_FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
UI_FONT_SMALL = ("Microsoft YaHei UI", 9)

DLG_BG = "#070b12"
DLG_PANEL = "#0d1622"
DLG_FIELD = "#0a111b"
DLG_FG = "#dbe9ff"
DLG_MUTED = "#7891ad"
DLG_ACCENT = "#2f7dff"
DLG_ACCENT_HI = "#5c9bff"
DLG_SEL = "#11305c"
DLG_ERROR = "#ff7a8a"
DLG_LINE = "#16263a"

MONITORINFOF_PRIMARY = 0x1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

if sys.platform == "win32":

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]


def monitor_work_areas() -> list[tuple[tuple[int, int, int, int], bool]]:
    """返回 (工作区矩形, 是否主显示器) 列表，坐标为物理像素。"""
    if sys.platform != "win32":
        return []
    try:
        user32 = ctypes.windll.user32
        results: list[tuple[tuple[int, int, int, int], bool]] = []
        proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.RECT),
            ctypes.c_void_p,
        )

        def _collect(hmonitor, _hdc, _rect, _data):
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                work = info.rcWork
                results.append(
                    (
                        (work.left, work.top, work.right, work.bottom),
                        bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    )
                )
            return 1

        user32.EnumDisplayMonitors(0, 0, proc_type(_collect), 0)
        return results
    except Exception:  # noqa: BLE001 - 拿不到显示器信息时退回 Tk 屏幕尺寸
        return []


def enable_dpi_awareness() -> None:
    """让窗口按物理像素渲染，避免高 DPI 下发虚。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001 - 老系统没有 shcore
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def _rgb_hex(color: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % color


def _row_to_event(row: dict[str, str]) -> Event:
    """把设置页的一行转换为 Event，非法时抛出中文 ValueError。"""
    name = str(row.get("name", "")).strip()
    if not name:
        raise ValueError("事件名称不能为空")
    if len(name) > MAX_NAME_LEN:
        raise ValueError(f"事件名称不能超过 {MAX_NAME_LEN} 个字符")
    text = str(row.get("minutes", "")).strip()
    if not text:
        raise ValueError("时长不能为空")
    try:
        minutes = float(text)
    except ValueError as exc:
        raise ValueError("时长必须是数字（单位：分钟）") from exc
    if not math.isfinite(minutes):
        raise ValueError("时长必须是有效数字")
    if minutes <= 0:
        raise ValueError("时长必须大于 0 分钟")
    seconds = int(round(minutes * 60))
    if seconds < 1:
        raise ValueError("时长至少 1 秒")
    if seconds > MAX_EVENT_SECONDS:
        raise ValueError("单个事件不能超过 24 小时")
    reminder = str(row.get("reminder", "")).strip()
    if len(reminder) > MAX_REMINDER_LEN:
        raise ValueError(f"提醒文案不能超过 {MAX_REMINDER_LEN} 个字符")
    return Event(
        uid=str(row["uid"]),
        name=name,
        seconds=seconds,
        reminder=reminder,
        kind=str(row.get("kind", "interval")),
    )


# ===================================================================== 设置对话框
class ConfigDialog(tk.Toplevel):
    """事件 / 皮肤 / 关于三页设置对话框。"""

    PAGES = (("events", "事件"), ("skin", "皮肤"), ("about", "关于"))

    def __init__(
        self,
        master: tk.Misc,
        *,
        events,
        alert_seconds: int,
        theme: str,
        autostart_enabled: bool,
        anchor: tuple[int, int, int, int] | None,
        on_save,
        on_cancel,
        on_preview_theme,
        on_test_sound,
    ) -> None:
        super().__init__(master)
        self.withdraw()
        self.title("DevAlarm 设置")
        self.configure(bg=DLG_BG)
        self.resizable(True, True)
        try:
            if ICON_FILE.exists():
                self.iconbitmap(default=str(ICON_FILE))
        except tk.TclError:
            pass
        try:
            self.transient(master)
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        self._on_save = on_save
        self._on_cancel = on_cancel
        self._on_preview_theme = on_preview_theme
        self._on_test_sound = on_test_sound
        self._anchor = anchor
        self._closed = False
        self._suppress_select = False
        self._loading = False

        self._rows: list[dict[str, str]] = [
            {
                "uid": event.uid,
                "kind": event.kind,
                "name": event.name,
                "minutes": format_minutes_input(event.seconds),
                "reminder": event.reminder,
            }
            for event in events
        ]
        self._selected = 0

        self._name_var = tk.StringVar()
        self._minutes_var = tk.StringVar()
        self._reminder_var = tk.StringVar()
        self._alert_var = tk.StringVar(value=str(alert_seconds))
        self._theme_var = tk.StringVar(value=theme)
        self._autostart_var = tk.BooleanVar(value=bool(autostart_enabled))
        for var in (self._name_var, self._minutes_var, self._reminder_var):
            var.trace_add("write", self._on_field_changed)

        self._build()
        self._refresh()
        self._place()
        self.deiconify()
        self._apply_dark_titlebar()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(80, self._focus_default)

    # ---------------------------------------------------------------- 组件
    def _label(self, parent: tk.Misc, text: str, **kwargs) -> tk.Label:
        options = {
            "bg": DLG_BG,
            "fg": DLG_FG,
            "font": UI_FONT,
            "anchor": "w",
        }
        options.update(kwargs)
        return tk.Label(parent, text=text, **options)

    def _button(self, parent: tk.Misc, text: str, command, accent=False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=DLG_ACCENT if accent else DLG_PANEL,
            fg="#ffffff" if accent else DLG_FG,
            activebackground=DLG_ACCENT_HI if accent else "#17283d",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=13,
            pady=5,
            cursor="hand2",
            font=UI_FONT,
            highlightthickness=0,
        )

    def _entry(self, parent: tk.Misc, var: tk.StringVar, width: int = 30):
        return tk.Entry(
            parent,
            textvariable=var,
            width=width,
            bg=DLG_FIELD,
            fg=DLG_FG,
            insertbackground=DLG_FG,
            relief="flat",
            bd=0,
            font=UI_FONT,
            highlightthickness=1,
            highlightbackground=DLG_LINE,
            highlightcolor=DLG_ACCENT,
            disabledbackground=DLG_FIELD,
            disabledforeground=DLG_MUTED,
        )

    def _build(self) -> None:
        header = tk.Frame(self, bg=DLG_BG)
        header.pack(fill="x", padx=20, pady=(16, 8))
        self._label(
            header,
            "DevAlarm 设置",
            font=UI_FONT_TITLE,
            fg="#f2f8ff",
        ).pack(side="left")
        self._label(
            header,
            "程序员的圆环节律钟",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        ).pack(side="left", padx=(12, 0), pady=(8, 0))

        tabs = tk.Frame(self, bg=DLG_BG)
        tabs.pack(fill="x", padx=20)
        self._tab_buttons: dict[str, tk.Button] = {}
        for key, text in self.PAGES:
            button = tk.Button(
                tabs,
                text=text,
                command=lambda k=key: self.show_page(k),
                bg=DLG_BG,
                fg=DLG_MUTED,
                activebackground=DLG_PANEL,
                activeforeground=DLG_FG,
                relief="flat",
                bd=0,
                padx=16,
                pady=6,
                cursor="hand2",
                font=UI_FONT,
                highlightthickness=0,
            )
            button.pack(side="left", padx=(0, 4))
            self._tab_buttons[key] = button

        tk.Frame(self, bg=DLG_LINE, height=1).pack(fill="x", padx=20, pady=(4, 0))

        self._body = tk.Frame(self, bg=DLG_BG, width=780, height=438)
        self._body.pack(fill="both", expand=True, padx=20, pady=(4, 0))
        self._body.pack_propagate(False)
        self._body.grid_rowconfigure(0, weight=1)
        self._body.grid_columnconfigure(0, weight=1)

        self._pages: dict[str, tk.Frame] = {}
        for key, _text in self.PAGES:
            page = tk.Frame(self._body, bg=DLG_BG)
            page.grid(row=0, column=0, sticky="nsew")
            self._pages[key] = page
        self._build_events_page(self._pages["events"])
        self._build_skin_page(self._pages["skin"])
        self._build_about_page(self._pages["about"])

        footer = tk.Frame(self, bg=DLG_BG)
        footer.pack(fill="x", padx=20, pady=(6, 16))
        self._footer_hint = self._label(
            footer,
            "修改会在保存后生效。",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        )
        self._footer_hint.pack(side="left")
        self._button(footer, "保存", self._save, accent=True).pack(
            side="right", padx=(8, 0)
        )
        self._button(footer, "取消", self._cancel).pack(side="right")

    def _build_events_page(self, page: tk.Frame) -> None:
        left = tk.Frame(page, bg=DLG_BG)
        left.pack(side="left", fill="both", padx=(0, 16), pady=14)
        self._label(left, "循环事件", font=UI_FONT_BOLD).pack(anchor="w")
        self._label(
            left,
            "按顺序循环，每个事件倒计时结束后进入下一个。",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
            wraplength=250,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        list_frame = tk.Frame(
            left,
            bg=DLG_LINE,
            highlightthickness=1,
            highlightbackground=DLG_LINE,
        )
        list_frame.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            list_frame,
            width=32,
            height=9,
            bg=DLG_FIELD,
            fg=DLG_FG,
            selectbackground=DLG_SEL,
            selectforeground="#e9f3ff",
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=UI_FONT,
            exportselection=False,
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "DevAlarm.Vertical.TScrollbar",
            background=DLG_PANEL,
            troughcolor=DLG_FIELD,
            bordercolor=DLG_BG,
            arrowcolor=DLG_MUTED,
            darkcolor=DLG_PANEL,
            lightcolor=DLG_PANEL,
            relief="flat",
            width=10,
        )
        style.map(
            "DevAlarm.Vertical.TScrollbar",
            background=[("active", DLG_ACCENT)],
            arrowcolor=[("active", "#ffffff")],
        )
        scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.listbox.yview,
            style="DevAlarm.Vertical.TScrollbar",
        )
        scrollbar.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Delete>", lambda _e: self._delete())

        buttons = tk.Frame(left, bg=DLG_BG)
        buttons.pack(fill="x", pady=(8, 0))
        self._button(buttons, "新增", self._add).pack(side="left")
        self._button(buttons, "删除", self._delete).pack(side="left", padx=6)
        self._button(buttons, "↑", self._move_up).pack(side="left")
        self._button(buttons, "↓", self._move_down).pack(side="left", padx=(6, 0))

        right = tk.Frame(page, bg=DLG_BG)
        right.pack(side="left", fill="both", expand=True, pady=14)
        right.grid_columnconfigure(0, weight=1)

        self._edit_title = self._label(right, "", font=UI_FONT_BOLD)
        self._edit_title.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self._label(right, "事件名称（最多 12 个字）").grid(row=1, column=0, sticky="w")
        self._name_entry = self._entry(right, self._name_var, width=32)
        self._name_entry.grid(row=2, column=0, sticky="ew", ipady=5, pady=(3, 10))

        time_row = tk.Frame(right, bg=DLG_BG)
        time_row.grid(row=3, column=0, sticky="ew")
        self._label(time_row, "时长（分钟）").pack(side="left")
        self._minutes_entry = self._entry(time_row, self._minutes_var, width=10)
        self._minutes_entry.pack(side="left", padx=(12, 0), ipady=5)
        self._label(time_row, "分钟", fg=DLG_MUTED).pack(side="left", padx=(8, 0))
        self._label(
            time_row,
            "支持小数，如 1.5",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        ).pack(side="left", padx=(14, 0))

        self._label(right, "提醒文案（最多 24 个字，留空显示“时间到了！”）").grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        self._reminder_entry = self._entry(right, self._reminder_var, width=32)
        self._reminder_entry.grid(row=5, column=0, sticky="ew", ipady=5, pady=(3, 8))

        self._hint = self._label(
            right,
            "",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
            wraplength=430,
            justify="left",
        )
        self._hint.grid(row=6, column=0, sticky="w")

        tk.Frame(right, bg=DLG_LINE, height=1).grid(
            row=7, column=0, sticky="ew", pady=10
        )

        alert_row = tk.Frame(right, bg=DLG_BG)
        alert_row.grid(row=8, column=0, sticky="ew")
        self._label(alert_row, "提醒时长（秒）").pack(side="left")
        self._alert_entry = self._entry(alert_row, self._alert_var, width=6)
        self._alert_entry.pack(side="left", padx=(12, 0), ipady=5)
        self._label(
            alert_row,
            f"到点后摇晃、发光并响铃的时间（{MIN_ALERT_SECONDS}–{MAX_ALERT_SECONDS} 秒）",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        ).pack(side="left", padx=(12, 0))
        test_button = self._button(right, "试听铃声", self._test_sound)
        test_button.grid(row=9, column=0, sticky="w", pady=(10, 0))
        if self._on_test_sound is None:
            test_button.configure(state="disabled")

        self._summary = self._label(
            right,
            "",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        )
        self._summary.grid(row=10, column=0, sticky="w", pady=(12, 0))

    def _build_skin_page(self, page: tk.Frame) -> None:
        content = tk.Frame(page, bg=DLG_BG)
        content.pack(fill="both", expand=True, pady=14)
        self._label(content, "皮肤主题", font=UI_FONT_BOLD).pack(anchor="w")
        self._label(
            content,
            "主题通过注册表扩展，新增皮肤会自动出现在这里。切换后立即预览。",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        ).pack(anchor="w", pady=(2, 12))

        for theme in list_themes():
            card = tk.Frame(
                content,
                bg=DLG_PANEL,
                highlightthickness=1,
                highlightbackground=DLG_LINE,
            )
            card.pack(fill="x", pady=(0, 10))
            top = tk.Frame(card, bg=DLG_PANEL)
            top.pack(fill="x", padx=14, pady=(10, 2))
            radio = tk.Radiobutton(
                top,
                text=theme.name,
                value=theme.key,
                variable=self._theme_var,
                command=self._on_theme_changed,
                bg=DLG_PANEL,
                fg=DLG_FG,
                activebackground=DLG_PANEL,
                activeforeground=DLG_FG,
                selectcolor=DLG_FIELD,
                font=UI_FONT_BOLD,
                anchor="w",
                cursor="hand2",
                highlightthickness=0,
                bd=0,
            )
            radio.pack(side="left")
            swatches = tk.Canvas(
                top,
                width=112,
                height=20,
                bg=DLG_PANEL,
                highlightthickness=0,
                bd=0,
            )
            swatches.pack(side="right")
            for index, color in enumerate(
                (theme.ring, theme.ring_hi, theme.alert_ring, theme.text)
            ):
                x = 10 + index * 28
                swatches.create_oval(
                    x,
                    4,
                    x + 13,
                    17,
                    fill=_rgb_hex(color),
                    outline="",
                )
            self._label(
                card,
                theme.description,
                bg=DLG_PANEL,
                fg=DLG_MUTED,
                font=UI_FONT_SMALL,
                wraplength=690,
                justify="left",
            ).pack(fill="x", padx=14, pady=(0, 12))

        self._label(
            content,
            "当前版本仅提供科技 HUD 主题；更多皮肤会通过同一注册表加入。",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        ).pack(anchor="w")

    def _build_about_page(self, page: tk.Frame) -> None:
        content = tk.Frame(page, bg=DLG_BG)
        content.pack(fill="both", expand=True, pady=14)
        self._label(
            content,
            APP_TITLE,
            font=UI_FONT_TITLE,
            fg="#f2f8ff",
        ).pack(anchor="w")
        self._label(
            content,
            f"{APP_VERSION} · {APP_AUTHOR}",
            fg=DLG_ACCENT_HI,
            font=UI_FONT_BOLD,
        ).pack(anchor="w", pady=(2, 12))
        self._label(
            content,
            APP_DESCRIPTION,
            fg=DLG_FG,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        bullet = (
            "圆环显示剩余时间，从顶部起点逆时针缩短。\n"
            "分钟下方的按钮开始 / 暂停计时，事件名两侧的箭头切换上一个 / 下一个事件。\n"
            "左键拖动移动窗口，拖动左右下角手柄可缩放。\n"
            "到点后窗口摇晃、圆环向外发光并循环响铃；点击圆环或等待提醒结束即进入下一事件。\n"
            "右键可打开设置、关于或退出。"
        )
        self._label(
            content,
            bullet,
            fg=DLG_MUTED,
            justify="left",
            wraplength=720,
        ).pack(anchor="w", pady=(0, 12))

        start_box = tk.Frame(content, bg=DLG_BG)
        start_box.pack(fill="x", pady=(0, 10))
        tk.Checkbutton(
            start_box,
            text="开机自动启动（登录 Windows 后自动运行）",
            variable=self._autostart_var,
            bg=DLG_BG,
            fg=DLG_FG,
            activebackground=DLG_BG,
            activeforeground=DLG_FG,
            selectcolor=DLG_FIELD,
            font=UI_FONT,
            anchor="w",
            cursor="hand2",
            highlightthickness=0,
            bd=0,
        ).pack(anchor="w")
        self._label(
            start_box,
            "默认开启；取消勾选并保存后会删除开机启动项。",
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
        ).pack(anchor="w", padx=(22, 0))

        tk.Frame(content, bg=DLG_LINE, height=1).pack(fill="x", pady=6)
        self._label(
            content,
            "配置文件",
            font=UI_FONT_BOLD,
        ).pack(anchor="w", pady=(6, 2))
        self._label(
            content,
            str(config_file()),
            fg=DLG_MUTED,
            font=UI_FONT_SMALL,
            wraplength=720,
            justify="left",
        ).pack(anchor="w")

    # ---------------------------------------------------------------- 分页
    def show_page(self, key: str) -> None:
        key = key if key in self._pages else "events"
        page = self._pages[key]
        page.tkraise()
        for name, button in self._tab_buttons.items():
            active = name == key
            button.configure(
                bg=DLG_ACCENT if active else DLG_BG,
                fg="#ffffff" if active else DLG_MUTED,
            )
        if key == "events":
            self.after(60, self._focus_default)

    def _focus_default(self) -> None:
        if not self.winfo_exists():
            return
        try:
            if self._rows:
                self._name_entry.focus_set()
            else:
                self.listbox.focus_set()
        except tk.TclError:
            pass

    def _fit_body(self) -> None:
        """按当前 DPI 下各页的自然尺寸设定内容区初始大小。

        这只是初始（也是最小）尺寸；窗口可被拖动放大，``_body`` 由
        ``pack(fill=both, expand=True)`` 吸收多出来的空间。
        """
        width = max(page.winfo_reqwidth() for page in self._pages.values())
        height = max(page.winfo_reqheight() for page in self._pages.values())
        self._body.configure(
            width=max(780, width + 4),
            height=max(438, height + 4),
        )

    def _apply_dark_titlebar(self) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            hwnd = user32.GetParent(wintypes.HWND(self.winfo_id()))
            if not hwnd:
                hwnd = wintypes.HWND(self.winfo_id())
            value = ctypes.c_int(1)
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute.argtypes = [
                wintypes.HWND,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            for attribute in (20, 19):  # Win11 / Win10 1903+
                if (
                    dwm.DwmSetWindowAttribute(
                        hwnd,
                        attribute,
                        ctypes.byref(value),
                        ctypes.sizeof(value),
                    )
                    == 0
                ):
                    break
        except Exception:  # noqa: BLE001 - 老系统没有 DWM 深色标题栏
            pass

    def _place(self) -> None:
        # 未映射的 Toplevel 用 winfo_width 会得到 1，必须用请求尺寸。
        self.update_idletasks()
        self._fit_body()
        self.update_idletasks()
        width = max(self.winfo_width(), self.winfo_reqwidth())
        height = max(self.winfo_height(), self.winfo_reqheight())
        # 内容不能被拖得比自然尺寸更小，放大后由 pack 自动分配多余空间。
        self.minsize(width, height)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if self._anchor is None:
            x = (sw - width) // 2
            y = (sh - height) // 2
        else:
            ax, ay, aw, ah = self._anchor
            x = ax + (aw - width) // 2
            y = ay - height - 12
            if y < 8:
                y = ay + ah + 12
        x = min(max(8, x), max(8, sw - width - 8))
        y = min(max(8, y), max(8, sh - height - 48))
        self.geometry(f"+{x}+{y}")

    # ---------------------------------------------------------------- 事件数据
    def _sync_selected_fields(self) -> None:
        if not self._rows:
            return
        row = self._rows[self._selected]
        row["name"] = self._name_var.get()
        row["minutes"] = self._minutes_var.get()
        row["reminder"] = self._reminder_var.get()

    @staticmethod
    def _row_label(index: int, row: dict[str, str]) -> str:
        name = str(row.get("name", "")).strip() or "（未命名）"
        minutes = str(row.get("minutes", "")).strip() or "—"
        return f"{index + 1}. {name}    {minutes} 分钟"

    def _refresh(self, load_fields: bool = True) -> None:
        self._suppress_select = True
        try:
            self.listbox.delete(0, "end")
            for index, row in enumerate(self._rows):
                self.listbox.insert("end", self._row_label(index, row))
            if self._rows:
                self._selected = min(max(0, self._selected), len(self._rows) - 1)
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(self._selected)
                self.listbox.activate(self._selected)
                self.listbox.see(self._selected)
        finally:
            self._suppress_select = False
        if load_fields:
            self._load_selected()
        self._update_total()

    def _load_selected(self) -> None:
        self._loading = True
        try:
            if self._rows:
                row = self._rows[self._selected]
                self._name_var.set(str(row.get("name", "")))
                self._minutes_var.set(str(row.get("minutes", "")))
                self._reminder_var.set(str(row.get("reminder", "")))
                self._edit_title.configure(
                    text=f"编辑事件 {self._selected + 1} / {len(self._rows)}"
                )
                for entry in (
                    self._name_entry,
                    self._minutes_entry,
                    self._reminder_entry,
                ):
                    entry.configure(state="normal")
            else:
                self._name_var.set("")
                self._minutes_var.set("")
                self._reminder_var.set("")
                self._edit_title.configure(text="没有事件")
                for entry in (
                    self._name_entry,
                    self._minutes_entry,
                    self._reminder_entry,
                ):
                    entry.configure(state="disabled")
        finally:
            self._loading = False
        self._refresh_hint()

    def _on_select(self, _event=None) -> None:
        if self._suppress_select:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        self._sync_selected_fields()
        self._selected = int(selection[0])
        self._load_selected()

    def _on_field_changed(self, *_args) -> None:
        if self._loading or not self._rows:
            return
        row = self._rows[self._selected]
        row["name"] = self._name_var.get()
        row["minutes"] = self._minutes_var.get()
        row["reminder"] = self._reminder_var.get()
        index = self._selected
        if self.listbox.size() > index:
            self.listbox.delete(index)
            self.listbox.insert(index, self._row_label(index, row))
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(index)
            self.listbox.activate(index)
        self._refresh_hint()
        self._update_total()

    def _refresh_hint(self) -> None:
        if not self._rows:
            self._hint.configure(text="至少需要一个事件。", fg=DLG_ERROR)
            return
        try:
            event = _row_to_event(self._rows[self._selected])
        except ValueError as exc:
            self._hint.configure(text=str(exc), fg=DLG_ERROR)
            return
        reminder_len = len(event.reminder)
        self._hint.configure(
            text=(
                f"提醒文案 {reminder_len}/{MAX_REMINDER_LEN}；"
                "留空时提醒中央显示“时间到了！”。"
            ),
            fg=DLG_MUTED,
        )

    def _update_total(self) -> None:
        total = 0
        invalid = False
        for row in self._rows:
            try:
                total += _row_to_event(row).seconds
            except ValueError:
                invalid = True
        if not self._rows:
            text = "至少需要一个事件"
        elif invalid:
            text = f"共 {len(self._rows)} 个事件 · 请完成未填好的字段"
        else:
            text = f"共 {len(self._rows)} 个事件 · 一轮 {format_duration(total)}"
        self._summary.configure(text=text)

    def _add(self) -> None:
        self._sync_selected_fields()
        taken = {str(row["uid"]) for row in self._rows}
        self._rows.append(
            {
                "uid": new_uid(taken),
                "kind": "interval",
                "name": "新事件",
                "minutes": "5",
                "reminder": "",
            }
        )
        self._selected = len(self._rows) - 1
        self._refresh()
        self._name_entry.focus_set()
        self._name_entry.selection_range(0, "end")

    def _delete(self) -> None:
        if len(self._rows) <= 1:
            messagebox.showinfo(
                "删除事件", "至少需要保留一个循环事件。", parent=self
            )
            return
        del self._rows[self._selected]
        self._selected = min(self._selected, len(self._rows) - 1)
        self._refresh()

    def _move(self, delta: int) -> None:
        self._sync_selected_fields()
        target = self._selected + delta
        if not 0 <= target < len(self._rows):
            return
        self._rows[self._selected], self._rows[target] = (
            self._rows[target],
            self._rows[self._selected],
        )
        self._selected = target
        self._refresh()

    def _move_up(self) -> None:
        self._move(-1)

    def _move_down(self) -> None:
        self._move(1)

    def _test_sound(self) -> None:
        if self._on_test_sound is not None:
            self._on_test_sound()

    # ---------------------------------------------------------------- 保存
    def _save(self) -> None:
        if self._closed:
            return
        self._sync_selected_fields()
        events: list[Event] = []
        for index, row in enumerate(self._rows):
            try:
                events.append(_row_to_event(row))
            except ValueError as exc:
                self._selected = index
                self._refresh()
                self._hint.configure(text=str(exc), fg=DLG_ERROR)
                messagebox.showerror("无法保存", str(exc), parent=self)
                return
        text = self._alert_var.get().strip()
        try:
            alert_seconds = int(round(float(text)))
        except ValueError:
            messagebox.showerror(
                "无法保存", "提醒时长必须是数字（单位：秒）。", parent=self
            )
            self._alert_entry.focus_set()
            return
        if not MIN_ALERT_SECONDS <= alert_seconds <= MAX_ALERT_SECONDS:
            messagebox.showerror(
                "无法保存",
                f"提醒时长必须在 {MIN_ALERT_SECONDS}–{MAX_ALERT_SECONDS} 秒之间。",
                parent=self,
            )
            self._alert_entry.focus_set()
            return
        theme_key = self._theme_var.get()
        self._closed = True
        try:
            self._on_save(
                tuple(events),
                alert_seconds,
                theme_key,
                bool(self._autostart_var.get()),
            )
        finally:
            self.destroy()

    def _cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._on_cancel()
        finally:
            self.destroy()

    def _on_theme_changed(self) -> None:
        if self._on_preview_theme is not None:
            self._on_preview_theme(self._theme_var.get())


# ===================================================================== 主应用
class AlarmApp:
    """圆形悬浮闹钟的主循环与交互粘合层。"""

    def __init__(self) -> None:
        self.config: Config = load_config()
        self.renderer = RingRenderer(self.config.scale, self.config.theme)
        self.config.scale = self.renderer.scale
        self.config.theme = self.renderer.theme.key
        self.events = tuple(self.config.events)
        self.cycle = Cycle(self.events, self.config.alert_seconds)
        self.sound = AlarmSound(SOUND_FILE)
        self._t0 = time.monotonic()
        self._warned: set[tuple[str, str]] = set()

        self._pending_click = False
        self._pending_control: str | None = None
        self._pending_menu: tuple[int, int] | None = None
        self._pending_move: tuple[int, int] | None = None
        self._pending_resize: tuple[int, int, int, int] | None = None
        self._pending_resize_end = False
        self._resizing = False
        self._resize_source: Image.Image | None = None
        self._last_frame: Image.Image | None = None

        self._alert_active = False
        self._alert_start: float | None = None
        self._alert_base: tuple[int, int] | None = None

        self._dialog: ConfigDialog | None = None
        self._dialog_anchor: tuple[int, int, int, int] | None = None
        self._saved_theme_key = self.renderer.theme.key
        self._after_id: str | None = None
        self._closing = False

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg="#060912")
        try:
            if ICON_FILE.exists():
                self.root.iconbitmap(default=str(ICON_FILE))
        except tk.TclError:
            pass
        self.root.overrideredirect(True)
        self.root.geometry("1x1+-10000+-10000")

        size = self.renderer.size
        if self.config.window_pos is None:
            x, y = self._default_position(size)
        else:
            x, y = self.config.window_pos
        x, y = self._clamp_position(x, y, size)

        self.overlay = OverlayWindow(
            size,
            x,
            y,
            on_click=self._on_click,
            on_control=self._on_control,
            on_right_click=self._on_right_click,
            on_move_done=self._on_move_done,
            on_resize_start=self._on_resize_start,
            on_resize=self._on_resize,
            on_resize_end=self._on_resize_end,
        )
        self.config.window_pos = (x, y)
        self._save_quiet()

        if not self.sound.available:
            self._warn(
                ("sound", "missing"),
                f"未找到铃声文件或系统不支持播放：{SOUND_FILE}",
            )

        # 每次启动都按配置同步启动项，程序升级或移动后路径自动修正。
        self._apply_autostart(self.config.autostart)

        self.cycle.tick(self._t0)
        self._after_id = self.root.after(20, self._tick)

    # ---------------------------------------------------------------- 位置
    def _default_position(self, size: int) -> tuple[int, int]:
        areas = monitor_work_areas()
        if areas:
            rect = next((area for area, primary in areas if primary), areas[0][0])
            left, top, right, bottom = rect
            return (left + right - size) // 2, bottom - size - 24
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        return (width - size) // 2, height - size - 80

    @staticmethod
    def _clamp_position(x: int, y: int, size: int) -> tuple[int, int]:
        if sys.platform != "win32":
            return int(x), int(y)
        try:
            user32 = ctypes.windll.user32
            vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        except Exception:  # noqa: BLE001
            return int(x), int(y)
        if vw <= 0 or vh <= 0:
            return int(x), int(y)
        x = min(max(int(x), vx), max(vx, vx + vw - size))
        y = min(max(int(y), vy), max(vy, vy + vh - size))
        return x, y

    # ---------------------------------------------------------------- 回调
    def _on_click(self) -> None:
        self._pending_click = True

    def _on_control(self, control: str) -> None:
        self._pending_control = control

    def _on_right_click(self, x: int, y: int) -> None:
        self._pending_menu = (int(x), int(y))

    def _on_move_done(self, x: int, y: int) -> None:
        self._pending_move = (int(x), int(y))

    def _on_resize_start(self) -> None:
        self._resizing = True
        self._resize_source = self._last_frame
        self._pending_resize_end = False

    def _on_resize(self, x: int, y: int, width: int, height: int) -> None:
        self._pending_resize = (int(x), int(y), int(width), int(height))
        self._pending_resize_end = False

    def _on_resize_end(self, x: int, y: int, width: int, height: int) -> None:
        self._pending_resize = (int(x), int(y), int(width), int(height))
        self._pending_resize_end = True

    # ---------------------------------------------------------------- 主循环
    def _tick(self) -> None:
        if self._closing:
            return
        delay = FRAME_MS
        try:
            now = time.monotonic()
            snapshot = self.cycle.tick(now)

            if snapshot.entered_alert:
                self._begin_alert(now)

            if self._pending_control is not None:
                control = self._pending_control
                self._pending_control = None
                if control == "pause":
                    self.cycle.toggle_pause()
                    snapshot = self.cycle.snapshot()
                elif control in ("prev", "next"):
                    # 切换事件会同时清掉提醒态，下面的 _end_alert 负责停铃复位。
                    snapshot = self.cycle.switch(
                        -1 if control == "prev" else 1, now
                    )

            if self._pending_click:
                self._pending_click = False
                if self.cycle.alerting:
                    snapshot = self.cycle.dismiss(now)

            if self._alert_active and not snapshot.alerting:
                self._end_alert()

            if self._pending_menu is not None:
                x, y = self._pending_menu
                self._pending_menu = None
                self._show_menu(x, y)

            if self._pending_move is not None:
                x, y = self._pending_move
                self._pending_move = None
                self.config.window_pos = (x, y)
                if self._alert_active and self._alert_base is not None:
                    self._alert_base = (x, y)
                self._save_quiet()

            if self._resizing:
                engaged = self._apply_resize_preview()
                if engaged:
                    delay = RESIZE_FRAME_MS
                else:
                    self._render(snapshot, now)
            elif snapshot.alerting:
                self._shake(snapshot, now)
                self._render(snapshot, now)
                delay = ALERT_FRAME_MS
            else:
                self._render(snapshot, now)
        except Exception as exc:  # noqa: BLE001 - 主循环不应因单帧异常退出
            self._warn(("tick", str(exc)), f"界面刷新失败：{exc}")
        finally:
            if not self._closing:
                self._after_id = self.root.after(delay, self._tick)

    def _render(self, snapshot, now: float) -> None:
        image = self.renderer.render(snapshot, t=now - self._t0)
        self.overlay.show_image(image)
        self._last_frame = image

    def _begin_alert(self, now: float) -> None:
        if self._alert_active:
            return
        self._alert_active = True
        self._alert_start = now
        left, top, _width, _height = self.overlay.rect()
        self._alert_base = (left, top)
        self.overlay.set_alert_mode(True)
        self.sound.start()

    def _shake(self, snapshot, now: float) -> None:
        if (
            not self._alert_active
            or self._alert_start is None
            or self._alert_base is None
        ):
            return
        age = max(0.0, now - self._alert_start)
        width = self.overlay.rect()[2]
        theme = self.renderer.theme
        amplitude = max(2.0, width * theme.shake_amplitude_ratio)
        offset = int(
            round(
                amplitude
                * math.sin(2.0 * math.pi * theme.shake_hz * age)
            )
        )
        self.overlay.move_to(self._alert_base[0] + offset, self._alert_base[1])

    def _end_alert(self) -> None:
        self.sound.stop()
        self.overlay.set_alert_mode(False)
        if self._alert_base is not None:
            self.overlay.move_to(*self._alert_base)
        self._alert_active = False
        self._alert_start = None
        self._alert_base = None

    # ---------------------------------------------------------------- 缩放
    def _apply_resize_preview(self) -> bool:
        """应用一次缩放预览；返回是否仍处于缩放中。"""
        if self._pending_resize is None:
            return self._resizing
        x, y, width, height = self._pending_resize
        self._pending_resize = None
        final = self._pending_resize_end
        self._pending_resize_end = False
        self.overlay.set_geometry(x, y, width, height)
        if final:
            self._commit_resize(x, y, width, height)
            return False
        source = self._resize_source
        if source is not None:
            try:
                preview = source.resize((width, height), Image.Resampling.LANCZOS)
            except (ValueError, OSError):
                preview = None
            if preview is not None:
                self.overlay.show_image(preview)
        return True

    def _commit_resize(self, x: int, y: int, width: int, height: int) -> None:
        scale = geometry.clamp_scale(width / geometry.LOG_SIZE)
        renderer = RingRenderer(scale, self.renderer.theme.key)
        size = renderer.size
        self.renderer = renderer
        self.overlay.set_geometry(x, y, size, size)
        self.config.scale = renderer.scale
        self.config.window_pos = (x, y)
        self._resize_source = None
        self._last_frame = None
        self._resizing = False
        self._save_quiet()

    # ---------------------------------------------------------------- 菜单
    def _show_menu(self, x: int, y: int) -> None:
        items = [
            (1, "设置…"),
            (2, f"关于 DevAlarm {APP_VERSION} · {APP_AUTHOR}"),
            (0, None),
            (3, "退出"),
        ]
        command = self.overlay.popup_menu(x, y, items)
        if command == 1:
            self._open_dialog("events")
        elif command == 2:
            self._open_dialog("about")
        elif command == 3:
            self.quit()

    # ---------------------------------------------------------------- 设置
    def _open_dialog(self, page: str) -> None:
        if self._dialog is not None:
            try:
                if self._dialog.winfo_exists():
                    self._dialog.show_page(page)
                    self._dialog.lift()
                    self._dialog.focus_force()
                    return
            except tk.TclError:
                pass
            self._dialog = None
        self._dialog_anchor = self.overlay.rect()
        self._saved_theme_key = self.renderer.theme.key
        self._dialog = ConfigDialog(
            self.root,
            events=self.cycle.events,
            alert_seconds=self.cycle.alert_seconds,
            theme=self.renderer.theme.key,
            autostart_enabled=self.config.autostart,
            anchor=self._dialog_anchor,
            on_save=self._apply_settings,
            on_cancel=self._cancel_settings,
            on_preview_theme=self._preview_theme,
            on_test_sound=self._test_sound,
        )
        self._dialog.show_page(page)

    def _apply_settings(
        self,
        events,
        alert_seconds: int,
        theme_key: str,
        autostart_enabled: bool,
    ) -> None:
        self._dialog = None
        if self._alert_active:
            self._end_alert()
        self.events = tuple(events)
        self.config.events = list(events)
        self.config.alert_seconds = clamp_alert_seconds(alert_seconds)
        self.cycle.set_events(self.events, self.config.alert_seconds)

        target = get_theme(theme_key)
        if target.key != self.renderer.theme.key:
            self._rebuild_theme(target.key)
        self.config.theme = self.renderer.theme.key
        self.config.autostart = bool(autostart_enabled)
        self._apply_autostart(self.config.autostart)
        self._saved_theme_key = self.renderer.theme.key
        self._save_quiet()

    def _apply_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            self._warn(("autostart", str(exc)), f"更新开机启动项失败：{exc}")

    def _cancel_settings(self) -> None:
        self._dialog = None
        if self.renderer.theme.key != self._saved_theme_key:
            self._restore_theme(self._saved_theme_key)

    def _preview_theme(self, theme_key: str) -> None:
        if not self._dialog:
            return
        target = get_theme(theme_key)
        if target.key == self.renderer.theme.key:
            return
        self._rebuild_theme(target.key, keep_anchor=False)

    def _restore_theme(self, theme_key: str) -> None:
        self._rebuild_theme(theme_key, keep_anchor=True)

    def _rebuild_theme(self, theme_key: str, keep_anchor: bool = False) -> None:
        left, top, width, height = self.overlay.rect()
        if keep_anchor and self._dialog_anchor is not None:
            ax, ay, aw, ah = self._dialog_anchor
            left, top, width, height = ax, ay, aw, ah
        center_x = left + width // 2
        center_y = top + height // 2
        self.renderer = RingRenderer(self.renderer.scale, theme_key)
        size = self.renderer.size
        x = center_x - size // 2
        y = center_y - size // 2
        x, y = self._clamp_position(x, y, size)
        self.overlay.set_geometry(x, y, size, size)
        self._last_frame = None
        if keep_anchor:
            self.config.window_pos = (x, y)
            self._save_quiet()

    def _test_sound(self) -> None:
        if self._alert_active:
            return
        if not self.sound.preview():
            parent = self._dialog if self._dialog is not None else self.root
            messagebox.showwarning(
                "试听铃声",
                "铃声文件缺失或系统无法播放，请检查 assets/alert.wav。",
                parent=parent,
            )

    # ---------------------------------------------------------------- 工具
    def _warn(self, key: tuple[str, str], message: str) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        if sys.stderr is not None:
            print(f"[DevAlarm] {message}", file=sys.stderr)

    def _save_quiet(self) -> None:
        try:
            save_config(self.config)
        except Exception as exc:  # noqa: BLE001 - 保存失败不影响计时
            self._warn(("save", str(exc)), f"保存配置失败：{exc}")

    # ---------------------------------------------------------------- 生命周期
    def quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self.sound.stop()
        if self._dialog is not None:
            try:
                self._dialog.destroy()
            except tk.TclError:
                pass
            self._dialog = None
        try:
            left, top, width, height = self.overlay.rect()
            if self._alert_base is not None:
                left, top = self._alert_base
            self.config.window_pos = (left, top)
            self.config.scale = self.renderer.scale
            self._save_quiet()
        finally:
            try:
                self.overlay.close()
            finally:
                self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def run() -> None:
    enable_dpi_awareness()
    AlarmApp().run()
