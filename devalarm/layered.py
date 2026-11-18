"""Windows 分层窗口：把 RGBA 图像逐像素合成到无边框窗口。

Tk 自带的 ``-alpha`` 会把整窗（含文字与圆环）一起变透明；这里改用 Win32
``UpdateLayeredWindow``，画面里 alpha 为 0 的像素完全透明，圆环外可以点击
穿透到下层窗口。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PIL import Image, ImageChops

WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
BI_RGB = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class LayeredWindow:
    """把 RGBA 图像逐像素合成到指定窗口上。"""

    def __init__(self, hwnd: int) -> None:
        if sys.platform != "win32":
            raise RuntimeError("分层窗口仅在 Windows 上可用")
        self.hwnd = wintypes.HWND(hwnd)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._configure_signatures()

        ex_style = self._user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        self._user32.SetWindowLongW(
            self.hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED
        )

        self._screen = self._user32.GetDC(None)
        self._mem = self._gdi32.CreateCompatibleDC(self._screen)
        self._bitmap = None
        self._bits = ctypes.c_void_p()
        self._size: tuple[int, int] | None = None
        if not self._screen or not self._mem:
            raise OSError(ctypes.get_last_error(), "创建绘图上下文失败")

    def _configure_signatures(self) -> None:
        u, g = self._user32, self._gdi32
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(_BITMAPINFO),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.DeleteObject.restype = wintypes.BOOL
        g.DeleteDC.argtypes = [wintypes.HDC]
        g.DeleteDC.restype = wintypes.BOOL
        u.GetDC.argtypes = [wintypes.HWND]
        u.GetDC.restype = wintypes.HDC
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        u.ReleaseDC.restype = ctypes.c_int
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongW.restype = ctypes.c_long
        u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        u.SetWindowLongW.restype = ctypes.c_long
        u.UpdateLayeredWindow.argtypes = [
            wintypes.HWND,
            wintypes.HDC,
            ctypes.POINTER(_POINT),
            ctypes.POINTER(_SIZE),
            wintypes.HDC,
            ctypes.POINTER(_POINT),
            wintypes.COLORREF,
            ctypes.POINTER(_BLENDFUNCTION),
            wintypes.DWORD,
        ]
        u.UpdateLayeredWindow.restype = wintypes.BOOL
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
        u.GetWindowRect.restype = wintypes.BOOL

    def _ensure_bitmap(self, width: int, height: int) -> None:
        if self._size == (width, height):
            return
        if self._bitmap:
            self._gdi32.SelectObject(self._mem, None)
            self._gdi32.DeleteObject(self._bitmap)
        info = _BITMAPINFO()
        header = info.bmiHeader
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # 负值表示自上而下
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        bitmap = self._gdi32.CreateDIBSection(
            self._screen,
            ctypes.byref(info),
            DIB_RGB_COLORS,
            ctypes.byref(bits),
            None,
            0,
        )
        if not bitmap:
            raise OSError(ctypes.get_last_error(), "CreateDIBSection 失败")
        self._gdi32.SelectObject(self._mem, bitmap)
        self._bitmap = bitmap
        self._bits = bits
        self._size = (width, height)

    @staticmethod
    def _premultiplied_bgra(image: Image.Image) -> bytes:
        rgba = image if image.mode == "RGBA" else image.convert("RGBA")
        alpha = rgba.getchannel("A")
        r = ImageChops.multiply(rgba.getchannel("R"), alpha)
        g = ImageChops.multiply(rgba.getchannel("G"), alpha)
        b = ImageChops.multiply(rgba.getchannel("B"), alpha)
        # 内存字节序为 B, G, R, A，即 UpdateLayeredWindow 需要的 BGRA
        return Image.merge("RGBA", (b, g, r, alpha)).tobytes()

    def show(self, image: Image.Image) -> None:
        width, height = image.size
        self._ensure_bitmap(width, height)
        data = self._premultiplied_bgra(image)
        ctypes.memmove(self._bits, data, len(data))
        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        src = _POINT(0, 0)
        area = _RECT()
        self._user32.GetWindowRect(self.hwnd, ctypes.byref(area))
        dst = _POINT(area.left, area.top)
        size = _SIZE(width, height)
        if not self._user32.UpdateLayeredWindow(
            self.hwnd,
            self._screen,
            ctypes.byref(dst),
            ctypes.byref(size),
            self._mem,
            ctypes.byref(src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        ):
            raise OSError(ctypes.get_last_error(), "UpdateLayeredWindow 失败")

    def close(self) -> None:
        if self._bitmap:
            self._gdi32.SelectObject(self._mem, None)
            self._gdi32.DeleteObject(self._bitmap)
            self._bitmap = None
        if self._mem:
            self._gdi32.DeleteDC(self._mem)
            self._mem = None
        if self._screen:
            self._user32.ReleaseDC(None, self._screen)
            self._screen = None
        self._size = None
