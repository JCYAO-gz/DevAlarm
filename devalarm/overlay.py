"""圆形悬浮窗口：纯圆环显示、拖动、双下角缩放与右键菜单。

窗口是 ``WS_POPUP`` 顶层分层窗口，画面由 :mod:`devalarm.layered` 输出。
``WM_NCHITTEST`` 让圆形之外的像素点击穿透；圆内左键拖动移动，左右下角
的缩放手柄拖动缩放，提醒状态下左键则作为“停止提醒”的点击。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PIL import Image

from . import geometry
from .layered import LayeredWindow

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_SETCURSOR = 0x0020
WM_MOUSEACTIVATE = 0x0021
WM_NCHITTEST = 0x0084
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

HTTRANSPARENT = -1
HTCLIENT = 1
MA_NOACTIVATE = 3
IDC_HAND = 32649
IDC_SIZENWSE = 32642
IDC_SIZENESW = 32643

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
SW_SHOWNOACTIVATE = 4

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
MF_STRING = 0x0000
MF_CHECKED = 0x0008
MF_POPUP = 0x0010
MF_SEPARATOR = 0x0800

ERROR_CLASS_ALREADY_EXISTS = 1410

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


_CLASS_NAME = "DevAlarmRing"
_INSTANCES: dict[int, "OverlayWindow"] = {}
_class_registered = False


def _class_wndproc(hwnd, msg, wparam, lparam):
    obj = _INSTANCES.get(hwnd) if hwnd else None
    if obj is None:
        return _init_api().DefWindowProcW(hwnd, msg, wparam, lparam)
    return obj._handle(hwnd, msg, wparam, lparam)


_CLASS_PROC = _WNDPROC(_class_wndproc)
_user32 = None
_gdi32 = None
_kernel32 = None


def _init_api():
    global _user32, _gdi32, _kernel32
    if _user32 is None:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure(_user32, _gdi32, _kernel32)
    return _user32


def _configure(u, g, k) -> None:
    u.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
    u.RegisterClassW.restype = wintypes.ATOM
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    u.CreateWindowExW.restype = wintypes.HWND
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.DestroyWindow.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    u.SetWindowPos.restype = wintypes.BOOL
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    u.GetWindowRect.restype = wintypes.BOOL
    u.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    u.GetCursorPos.restype = wintypes.BOOL
    u.SetCapture.argtypes = [wintypes.HWND]
    u.SetCapture.restype = wintypes.HWND
    u.ReleaseCapture.argtypes = []
    u.ReleaseCapture.restype = wintypes.BOOL
    u.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    u.LoadCursorW.restype = wintypes.HANDLE
    u.SetCursor.argtypes = [wintypes.HANDLE]
    u.SetCursor.restype = wintypes.HANDLE
    u.GetSystemMetrics.argtypes = [ctypes.c_int]
    u.GetSystemMetrics.restype = ctypes.c_int
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k.GetModuleHandleW.restype = wintypes.HMODULE
    u.CreatePopupMenu.argtypes = []
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.AppendMenuW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPCWSTR,
    ]
    u.AppendMenuW.restype = wintypes.BOOL
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.DestroyMenu.restype = wintypes.BOOL
    u.TrackPopupMenuEx.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.LPVOID,
    ]
    u.TrackPopupMenuEx.restype = wintypes.BOOL
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.restype = wintypes.BOOL
    u.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    u.PostMessageW.restype = wintypes.BOOL


def _signed_lparam(lparam: int) -> tuple[int, int]:
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    return x, y


class OverlayWindow:
    """圆形悬浮窗口：显示、拖动、左右下角缩放、右键菜单。"""

    def __init__(
        self,
        size: int,
        x: int,
        y: int,
        on_click=None,
        on_control=None,
        on_right_click=None,
        on_move_done=None,
        on_resize_start=None,
        on_resize=None,
        on_resize_end=None,
    ) -> None:
        if sys.platform != "win32":
            raise RuntimeError("悬浮窗口仅在 Windows 上可用")
        self._u = _init_api()
        self._register_class()
        self.on_click = on_click
        self.on_control = on_control
        self.on_right_click = on_right_click
        self.on_move_done = on_move_done
        self.on_resize_start = on_resize_start
        self.on_resize = on_resize
        self.on_resize_end = on_resize_end
        self._alert_mode = False
        self._drag_origin: tuple[int, int, int, int, bool] | None = None
        self._resize_origin: tuple[str, int, int, int, int, int, int] | None = None
        self._cursor = self._u.LoadCursorW(None, ctypes.c_void_p(IDC_HAND))
        self._cursor_nwse = self._u.LoadCursorW(None, ctypes.c_void_p(IDC_SIZENWSE))
        self._cursor_nesw = self._u.LoadCursorW(None, ctypes.c_void_p(IDC_SIZENESW))

        ex_style = (
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        )
        hwnd = self._u.CreateWindowExW(
            ex_style,
            _CLASS_NAME,
            "DevAlarm",
            WS_POPUP,
            x,
            y,
            size,
            size,
            None,
            None,
            _kernel32.GetModuleHandleW(None),
            None,
        )
        if not hwnd:
            raise OSError(ctypes.get_last_error(), "创建悬浮窗口失败")
        self.hwnd: int = hwnd
        _INSTANCES[self.hwnd] = self
        self._layer = LayeredWindow(self.hwnd)
        self._u.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self._u.SetWindowPos(
            self.hwnd,
            HWND_TOPMOST,
            x,
            y,
            size,
            size,
            SWP_SHOWWINDOW | SWP_NOACTIVATE,
        )

    # ---------------------------------------------------------------- 类注册
    def _register_class(self) -> None:
        global _class_registered
        if _class_registered:
            return
        wc = _WNDCLASSW()
        wc.lpfnWndProc = _CLASS_PROC
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        wc.hCursor = self._u.LoadCursorW(None, None)
        wc.lpszClassName = _CLASS_NAME
        if not self._u.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != ERROR_CLASS_ALREADY_EXISTS:
                raise OSError(err, "注册悬浮窗口类失败")
        _class_registered = True

    # ---------------------------------------------------------------- 消息处理
    def _handle(self, hwnd, msg, wparam, lparam):
        u = self._u
        if msg == WM_NCHITTEST:
            left, top, width, _height = self.rect()
            x, y = _signed_lparam(lparam)
            if not geometry.inside_hit_circle(x - left, y - top, width):
                return HTTRANSPARENT
            return HTCLIENT
        if msg == WM_LBUTTONDOWN:
            x, y = _signed_lparam(lparam)
            if self._alert_mode:
                self._drag_origin = None
                self._resize_origin = None
                if self.on_click is not None:
                    self.on_click()
                return 0
            left, top, width, height = self.rect()
            # 中央的开始/暂停按钮与上/下一事件箭头：单击立即生效，不进入拖动。
            control = geometry.control_at(x, y, width)
            if control is not None:
                self._drag_origin = None
                self._resize_origin = None
                if self.on_control is not None:
                    self.on_control(control)
                return 0
            handle = geometry.handle_at(x, y, width)
            pt = _POINT()
            u.GetCursorPos(ctypes.byref(pt))
            u.SetCapture(self.hwnd)
            if handle is not None:
                self._drag_origin = None
                self._resize_origin = (
                    handle,
                    pt.x,
                    pt.y,
                    left,
                    top,
                    width,
                    height,
                )
                u.SetCursor(self._handle_cursor(handle))
                if self.on_resize_start is not None:
                    self.on_resize_start()
            else:
                self._resize_origin = None
                self._drag_origin = (pt.x, pt.y, left, top, False)
            return 0
        if msg == WM_MOUSEMOVE:
            if self._resize_origin is not None:
                rect = self._resized_rect(self._resize_origin)
                if self.on_resize is not None:
                    self.on_resize(*rect)
            elif self._drag_origin is not None:
                sx, sy, left, top, moved = self._drag_origin
                pt = _POINT()
                u.GetCursorPos(ctypes.byref(pt))
                dx, dy = pt.x - sx, pt.y - sy
                if dx or dy:
                    u.SetWindowPos(
                        self.hwnd,
                        None,
                        left + dx,
                        top + dy,
                        0,
                        0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
                    )
                    self._drag_origin = (sx, sy, left, top, True)
            return 0
        if msg == WM_LBUTTONUP:
            if self._resize_origin is not None:
                rect = self._resized_rect(self._resize_origin)
                self._resize_origin = None
                u.ReleaseCapture()
                if self.on_resize_end is not None:
                    self.on_resize_end(*rect)
                return 0
            if self._drag_origin is not None:
                moved = self._drag_origin[4]
                self._drag_origin = None
                u.ReleaseCapture()
                if moved and self.on_move_done is not None:
                    left, top, _w, _h = self.rect()
                    self.on_move_done(left, top)
            return 0
        if msg == WM_RBUTTONUP:
            if self.on_right_click is not None:
                pt = _POINT()
                u.GetCursorPos(ctypes.byref(pt))
                self.on_right_click(pt.x, pt.y)
            return 0
        if msg == WM_SETCURSOR:
            if (lparam & 0xFFFF) == HTCLIENT:
                pt = _POINT()
                u.GetCursorPos(ctypes.byref(pt))
                left, top, width, _height = self.rect()
                handle = geometry.handle_at(pt.x - left, pt.y - top, width)
                u.SetCursor(self._handle_cursor(handle))
                return 1
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_DESTROY:
            _INSTANCES.pop(self.hwnd, None)
            return 0
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---------------------------------------------------------------- 缩放
    def _handle_cursor(self, handle: str | None):
        if not self._alert_mode:
            if handle == "left":
                return self._cursor_nwse
            if handle == "right":
                return self._cursor_nesw
        return self._cursor

    def _resized_rect(
        self, origin: tuple[str, int, int, int, int, int, int]
    ) -> tuple[int, int, int, int]:
        handle, sx, sy, left, top, width, height = origin
        pt = _POINT()
        self._u.GetCursorPos(ctypes.byref(pt))
        rect = geometry.resize_rect(
            handle, left, top, width, height, pt.x - sx, pt.y - sy
        )
        return self._clamp_to_virtual(*rect)

    def _clamp_to_virtual(
        self, left: int, top: int, width: int, height: int
    ) -> tuple[int, int, int, int]:
        """把缩放后的窗口夹在虚拟桌面内，避免手柄拖出屏幕后窗口消失。"""
        u = self._u
        vx = u.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = u.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = u.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = u.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if vw <= 0 or vh <= 0:
            return left, top, width, height
        left = min(max(left, vx), max(vx, vx + vw - width))
        top = min(max(top, vy), max(vy, vy + vh - height))
        return left, top, width, height

    # ---------------------------------------------------------------- 绘制
    def show_image(self, image: Image.Image) -> None:
        self._layer.show(image)

    def rect(self) -> tuple[int, int, int, int]:
        area = _RECT()
        self._u.GetWindowRect(self.hwnd, ctypes.byref(area))
        return (
            area.left,
            area.top,
            area.right - area.left,
            area.bottom - area.top,
        )

    def set_geometry(self, x: int, y: int, width: int, height: int) -> None:
        self._u.SetWindowPos(
            self.hwnd,
            HWND_TOPMOST,
            x,
            y,
            width,
            height,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

    def move_to(self, x: int, y: int) -> None:
        """只移动窗口，不改变尺寸、不触发移动完成回调。"""
        self._u.SetWindowPos(
            self.hwnd,
            None,
            x,
            y,
            0,
            0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )

    def set_alert_mode(self, alerting: bool) -> None:
        self._alert_mode = bool(alerting)
        if self._alert_mode:
            self._drag_origin = None
            self._resize_origin = None
            self._u.ReleaseCapture()

    @property
    def alert_mode(self) -> bool:
        return self._alert_mode

    # ---------------------------------------------------------------- 菜单
    def popup_menu(self, x: int, y: int, items) -> int:
        """弹出原生右键菜单，返回选中的命令编号（0 表示未选择）。"""
        u = self._u
        menu = u.CreatePopupMenu()
        if not menu:
            return 0

        def append(handle, entries) -> None:
            for item in entries:
                command, label = item[0], item[1]
                if label is None:
                    u.AppendMenuW(handle, MF_SEPARATOR, 0, None)
                    continue
                if len(item) >= 3 and isinstance(item[2], (list, tuple)):
                    submenu = u.CreatePopupMenu()
                    if not submenu:
                        continue
                    append(submenu, item[2])
                    u.AppendMenuW(handle, MF_POPUP, submenu, label)
                    continue
                flags = MF_STRING
                if len(item) >= 3 and item[2]:
                    flags |= MF_CHECKED
                u.AppendMenuW(handle, flags, command or 0, label)

        try:
            append(menu, items)
            u.SetForegroundWindow(self.hwnd)
            command = u.TrackPopupMenuEx(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD,
                x,
                y,
                self.hwnd,
                None,
            )
            u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            return int(command)
        finally:
            u.DestroyMenu(menu)

    def close(self) -> None:
        self._u.ReleaseCapture()
        self._layer.close()
        _INSTANCES.pop(self.hwnd, None)
        self._u.DestroyWindow(self.hwnd)
