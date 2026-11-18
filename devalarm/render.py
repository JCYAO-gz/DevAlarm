"""圆形科技风渲染。

渲染分两层：

- **静态层**：圆盘、极坐标网格、刻度、轨道环与缩放手柄，只在尺寸或主题
  变化时重建一次；
- **动态层**：剩余进度弧、头部辉光、中央文字与到点提醒帧，每帧重绘。

所有绘制先按 2 倍超采样完成，再缩小到目标尺寸，保证圆弧与文字边缘平滑。
圆外像素通过圆形遮罩强制为全透明，实现“纯圆环悬浮”。
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import geometry
from .core import PHASE_ALERT, Snapshot, format_duration
from .theme import Theme, get_theme

SS_STATIC = 2
SS_DYNAMIC_MAX_SIZE = 520  # 尺寸较大时不再逐帧超采样，避免帧率下降
TEXT_CACHE_LIMIT = 256


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _font_dir() -> Path:
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    return Path(windir) / "Fonts"


def _resolve_font(*names: str) -> str | None:
    root = _font_dir()
    for name in names:
        path = root / name
        if path.exists():
            return str(path)
    return None


_NAME_FONT = _resolve_font("msyhbd.ttc", "msyh.ttc", "simhei.ttf")
_BODY_FONT = _resolve_font("msyh.ttc", "msyhbd.ttc", "simsun.ttc")
_MONO_FONT = _resolve_font("consolab.ttf", "consola.ttf", "cour.ttf")

_font_cache: dict[tuple[str | None, int], ImageFont.FreeTypeFont] = {}


def _load_font(path: str | None, size_px: int) -> ImageFont.FreeTypeFont:
    key = (path, size_px)
    font = _font_cache.get(key)
    if font is None:
        try:
            font = ImageFont.truetype(path, size_px) if path else ImageFont.load_default()
        except OSError:
            font = ImageFont.load_default()
        if len(_font_cache) > 128:
            _font_cache.clear()
        _font_cache[key] = font
    return font


class RingRenderer:
    """把 ``Snapshot`` 渲染为正方形 RGBA 图像。"""

    def __init__(
        self,
        scale: float = 1.0,
        theme: Theme | str | None = None,
    ) -> None:
        self.scale = geometry.clamp_scale(scale)
        self.size = geometry.size_for_scale(self.scale)
        self.theme = get_theme(theme)
        self._ss = SS_STATIC if self.size <= SS_DYNAMIC_MAX_SIZE else 1
        self._k = self.size / geometry.LOG_SIZE * self._ss
        self._text_cache: dict[tuple, Image.Image] = {}
        # 顶部静态标签的暗色，避免抢走中央文字的注意力
        self._label_color = _mix(self.theme.text_dim, self.theme.disc, 0.35)
        self._mask = self._build_mask()
        self._static = self._build_static()
        self._head_glow = self._build_head_glow()
        self._alert_glow = self._build_alert_glow()
        self._glow_frames: dict[int, Image.Image] = {}

    # ---------------------------------------------------------------- 公共接口
    def render(self, snapshot: Snapshot, t: float = 0.0) -> Image.Image:
        """渲染一帧；``t`` 是连续时间，用于提醒脉冲与旋转扫描。"""
        image = self._static.copy()
        layer = Image.new(
            "RGBA", (round(geometry.LOG_SIZE * self._k),) * 2, (0, 0, 0, 0)
        )
        draw = ImageDraw.Draw(layer)
        strength = 0.0

        if snapshot.phase == PHASE_ALERT:
            strength = self._pulse_strength(t)
            self._draw_alert(draw, snapshot, t)
            self._draw_alert_text(layer, snapshot)
        else:
            self._draw_progress(layer, draw, snapshot, t)
            self._draw_running_text(layer, snapshot)

        if self._ss > 1:
            layer = layer.reduce(self._ss)
        image.alpha_composite(layer)
        if strength > 0.0:
            # 向外扩散的辉光按最终尺寸预渲染，逐帧只调整整体透明度。
            image.alpha_composite(self._glow_frame(strength))
        image.putalpha(ImageChops.multiply(image.getchannel("A"), self._mask))
        return image

    def _pulse_strength(self, t: float) -> float:
        """提醒脉冲强度 0..1，供环光与向外辉光共用。"""
        pulse = 0.5 + 0.5 * math.cos(2.0 * math.pi * self.theme.pulse_hz * t)
        return 0.5 + 0.5 * pulse

    # ---------------------------------------------------------------- 静态层
    def _build_mask(self) -> Image.Image:
        """圆形遮罩：圆外强制透明，边缘在缩小时自然羽化。"""
        size = self.size
        big = size * 2
        mask = Image.new("L", (big, big), 0)
        draw = ImageDraw.Draw(mask)
        center = big / 2.0
        radius = geometry.CLIP_RADIUS / geometry.LOG_SIZE * size * 2.0
        draw.ellipse(
            [center - radius, center - radius, center + radius, center + radius],
            fill=255,
        )
        return mask.reduce(2)

    def _build_static(self) -> Image.Image:
        k = SS_STATIC * self.size / geometry.LOG_SIZE
        big = round(geometry.LOG_SIZE * k)
        image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        c = geometry.CENTER * k
        image.alpha_composite(self._build_disc(k))

        # 装饰必须画在独立的透明层上再合成：ImageDraw 直接往已有着色的
        # 图像上画半透明像素会“替换”alpha，在圆盘上打出透明孔洞。
        deco = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(deco)
        self._draw_grid(draw, k, c)
        self._draw_track(draw, k, c)
        self._draw_ticks(draw, k, c)
        self._draw_dashed_outer(draw, k, c)
        self._draw_handles(draw, k)
        self._draw_label_guides(draw, k)
        image.alpha_composite(deco)
        self._draw_static_labels(image, k)

        if SS_STATIC > 1:
            image = image.reduce(SS_STATIC)
        return self._apply_mask(image)

    def _build_disc(self, k: float) -> Image.Image:
        big = round(geometry.LOG_SIZE * k)
        disc = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(disc)
        c = geometry.CENTER * k
        radius = geometry.R_IN * k
        steps = max(1, int(radius))
        for i in range(steps, 0, -1):
            ratio = i / steps
            color = _mix(self.theme.disc_hi, self.theme.disc, ratio ** 1.4)
            alpha = int(self.theme.disc_alpha)
            draw.ellipse(
                [c - i, c - i, c + i, c + i],
                fill=(*color, max(0, min(255, alpha))),
            )
        # 内侧细高光，增加玻璃质感
        draw.ellipse(
            [c - radius, c - radius, c + radius, c + radius],
            outline=(*self.theme.ring, 52),
            width=max(1, round(1.2 * k)),
        )
        arc_r = radius - 6 * k
        draw.arc(
            [c - arc_r, c - arc_r, c + arc_r, c + arc_r],
            196,
            326,
            fill=(*self.theme.ring_hi, 46),
            width=max(1, round(1.4 * k)),
        )
        return disc

    def _draw_grid(self, draw: ImageDraw.ImageDraw, k: float, c: float) -> None:
        grid = self.theme.grid
        for ratio, alpha in ((0.34, 18), (0.62, 15), (0.86, 12), (0.97, 10)):
            r = geometry.R_IN * ratio * k
            draw.ellipse(
                [c - r, c - r, c + r, c + r],
                outline=(*grid, alpha),
                width=max(1, round(1.0 * k)),
            )
        r0 = geometry.R_IN * 0.30 * k
        r1 = geometry.R_IN * 0.98 * k
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            draw.line(
                [
                    c + r0 * math.cos(rad),
                    c + r0 * math.sin(rad),
                    c + r1 * math.cos(rad),
                    c + r1 * math.sin(rad),
                ],
                fill=(*grid, 16),
                width=max(1, round(0.9 * k)),
            )

    def _draw_track(self, draw: ImageDraw.ImageDraw, k: float, c: float) -> None:
        r = geometry.R_OUT * k
        draw.ellipse(
            [c - r, c - r, c + r, c + r],
            outline=(*self.theme.track, 255),
            width=max(1, round(geometry.RING_W * k)),
        )
        # 轨道内侧阴影线，强调圆环厚度
        r_in = (geometry.R_IN + 1.5) * k
        draw.ellipse(
            [c - r_in, c - r_in, c + r_in, c + r_in],
            outline=(*self.theme.glow, 18),
            width=max(1, round(1.2 * k)),
        )

    def _draw_ticks(self, draw: ImageDraw.ImageDraw, k: float, c: float) -> None:
        for angle in range(0, 360, 6):
            major = angle % 30 == 0
            inner = geometry.R_OUT + (5 if major else 4)
            outer = geometry.R_OUT + (13 if major else 8)
            x1, y1 = geometry.point_at(angle, inner)
            x2, y2 = geometry.point_at(angle, outer)
            draw.line(
                [x1 * k, y1 * k, x2 * k, y2 * k],
                fill=(*self.theme.grid, 150 if major else 88),
                width=max(1, round((1.5 if major else 1.0) * k)),
            )

    def _draw_dashed_outer(
        self, draw: ImageDraw.ImageDraw, k: float, c: float
    ) -> None:
        radius = 188.0 * k
        for start in range(0, 360, 12):
            draw.arc(
                [c - radius, c - radius, c + radius, c + radius],
                start,
                start + 4,
                fill=(*self.theme.grid, 54),
                width=max(1, round(1.0 * k)),
            )

    def _draw_handles(self, draw: ImageDraw.ImageDraw, k: float) -> None:
        color = self.theme.handle
        radius = geometry.HANDLE_RADIUS * k
        for name, angle in geometry.HANDLE_ANGLES.items():
            c = geometry.CENTER * k
            box = [c - radius, c - radius, c + radius, c + radius]
            # 两段外侧亮弧夹住一个短横，提示“这里可以拖动缩放”
            draw.arc(
                box,
                angle - 15.0,
                angle + 15.0,
                fill=(*color, 44),
                width=max(1, round(7.0 * k)),
            )
            draw.arc(
                box,
                angle - 10.0,
                angle + 10.0,
                fill=(*color, 200),
                width=max(1, round(2.6 * k)),
            )
            for delta in (-10.0, 10.0):
                px, py = geometry.point_at(angle + delta, geometry.HANDLE_RADIUS)
                dot = 2.0 * k
                draw.ellipse(
                    [px * k - dot, py * k - dot, px * k + dot, py * k + dot],
                    fill=(*color, 225),
                )

    def _draw_label_guides(self, draw: ImageDraw.ImageDraw, k: float) -> None:
        line_color = (*self.theme.grid, 110)
        for direction in (-1, 1):
            x0 = geometry.CENTER + direction * 38
            x1 = geometry.CENTER + direction * 66
            draw.line(
                [x0 * k, 94 * k, x1 * k, 94 * k],
                fill=line_color,
                width=max(1, round(1.0 * k)),
            )

    def _draw_static_labels(self, image: Image.Image, k: float) -> None:
        sprite = self._text_sprite(
            "DEV.ALARM",
            8.5,
            self._label_color,
            bold=False,
            mono=True,
            k=k,
        )
        self._paste_center(image, sprite, geometry.CENTER, 94.0, k)

    # ---------------------------------------------------------------- 动态层
    def _draw_progress(
        self,
        layer: Image.Image,
        draw: ImageDraw.ImageDraw,
        snapshot: Snapshot,
        t: float,
    ) -> None:
        remaining = max(0.0, min(1.0, 1.0 - snapshot.progress))
        if remaining <= 0.0005:
            return
        arc = geometry.remaining_arc(remaining)
        theme = self.theme
        k = self._k

        for pad, extra, color, alpha in (
            (7.0, 14.0, theme.glow, 34),
            (4.0, 8.0, theme.glow, 62),
            (1.5, 3.0, theme.ring_hi, 96),
        ):
            self._paint_arc(
                draw,
                arc,
                geometry.R_OUT + pad,
                geometry.RING_W + extra,
                color,
                alpha,
                k,
            )
        self._paint_arc(
            draw, arc, geometry.R_OUT, geometry.RING_W, theme.ring, 255, k
        )
        self._paint_arc(
            draw, arc, geometry.R_OUT - 4.0, 3.0, theme.ring_light, 190, k
        )

        if not arc.full:
            head = geometry.point_at(arc.start, geometry.R_MID)
            tail = geometry.point_at(arc.start + arc.sweep, geometry.R_MID)
            cap = geometry.RING_W / 2.0
            for angle, point in ((arc.start, head), (arc.start + arc.sweep, tail)):
                radius = cap * k
                draw.ellipse(
                    [
                        point[0] * k - radius,
                        point[1] * k - radius,
                        point[0] * k + radius,
                        point[1] * k + radius,
                    ],
                    fill=(*theme.ring, 255),
                )
                inner = (cap - 3.2) * k
                draw.ellipse(
                    [
                        point[0] * k - inner,
                        point[1] * k - inner,
                        point[0] * k + inner,
                        point[1] * k + inner,
                    ],
                    fill=(*theme.ring_hi, 210),
                )
            # 辉光跟随移动的末端（起点固定在顶部不动）
            self._paste_glow(layer, tail[0] * k, tail[1] * k)

    def _draw_alert(
        self, draw: ImageDraw.ImageDraw, snapshot: Snapshot, t: float
    ) -> None:
        theme = self.theme
        k = self._k
        strength = self._pulse_strength(t)
        full = geometry.remaining_arc(1.0)

        for pad, extra, alpha in (
            (13.0, 26.0, 26),
            (8.0, 16.0, 42),
            (4.0, 8.0, 68),
        ):
            self._paint_arc(
                draw,
                full,
                geometry.R_OUT + pad,
                geometry.RING_W + extra,
                theme.alert_ring,
                int(alpha * strength),
                k,
            )
        self._paint_arc(
            draw,
            full,
            geometry.R_OUT,
            geometry.RING_W,
            theme.alert_ring,
            255,
            k,
        )
        self._paint_arc(
            draw,
            full,
            geometry.R_OUT - 4.0,
            3.0,
            theme.alert_hi,
            int(120 + 100 * strength),
            k,
        )

        # 环上旋转的扫描弧
        sweep = geometry.arc_from_start((t * 150.0) % 360.0, 54.0)
        self._paint_arc(
            draw,
            sweep,
            geometry.R_OUT - 1.5,
            5.0,
            theme.alert_hi,
            int(90 + 90 * strength),
            k,
        )
        # 环内细倒计时弧：提醒剩余时间
        total = max(1, snapshot.alert_total)
        fraction = max(0.0, min(1.0, snapshot.alert_remaining / total))
        if fraction > 0.001:
            alert_arc = geometry.arc_from_start(270.0, 360.0 * fraction)
            self._paint_arc(
                draw,
                alert_arc,
                geometry.R_IN - 12.0,
                9.0,
                theme.alert_ring,
                46,
                k,
            )
            self._paint_arc(
                draw,
                alert_arc,
                geometry.R_IN - 12.0,
                2.6,
                theme.alert_hi,
                200,
                k,
            )

    def _paint_arc(
        self,
        draw: ImageDraw.ImageDraw,
        arc: geometry.Arc,
        radius: float,
        width: float,
        color: tuple[int, int, int],
        alpha: int,
        k: float,
    ) -> None:
        alpha = max(0, min(255, int(alpha)))
        if alpha <= 0 or width <= 0:
            return
        c = geometry.CENTER * k
        r = radius * k
        box = [c - r, c - r, c + r, c + r]
        stroke = max(1, round(width * k))
        if arc.full:
            draw.ellipse(box, outline=(*color, alpha), width=stroke)
            return
        for start, end in arc.segments():
            draw.arc(box, start, end, fill=(*color, alpha), width=stroke)

    def _build_head_glow(self) -> Image.Image:
        k = self._k
        size = max(8, int(64 * k))
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        c = size / 2.0
        for i in range(size // 2, 0, -1):
            ratio = i / (size / 2.0)
            alpha = int(150 * (1.0 - ratio) ** 2.2)
            if alpha <= 0:
                continue
            draw.ellipse(
                [c - i, c - i, c + i, c + i],
                fill=(*self.theme.glow, alpha),
            )
        return image.filter(ImageFilter.GaussianBlur(max(1.0, 2.5 * k)))

    def _build_alert_glow(self) -> Image.Image:
        """提醒时从圆环向外扩散的柔和辉光（按最终尺寸预渲染一次）。

        由内向外画一圈圈透明度递减的细环再整体模糊，比逐帧 GaussianBlur
        便宜；动画时只调制整体透明度。
        """
        size = self.size
        scale = size / geometry.LOG_SIZE
        glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(glow)
        c = size / 2.0
        inner = (geometry.R_OUT - 6.0) * scale
        outer = (geometry.CLIP_RADIUS - 3.0) * scale
        steps = max(1, int(round(outer - inner)))
        for i in range(steps):
            t = (i + 1) / steps
            radius = inner + (outer - inner) * t
            alpha = int(150 * (1.0 - t) ** 2.2)
            if alpha <= 0:
                continue
            color = _mix(self.theme.alert_hi, self.theme.alert_ring, t ** 0.6)
            draw.ellipse(
                [c - radius, c - radius, c + radius, c + radius],
                outline=(*color, alpha),
                width=1,
            )
        return glow.filter(ImageFilter.GaussianBlur(max(1.0, 4.5 * scale)))

    def _glow_frame(self, strength: float) -> Image.Image:
        """按脉冲强度取预计算的外发光帧（量化成 6 档后缓存）。"""
        level = max(0, min(6, int(round(strength * 6))))
        frame = self._glow_frames.get(level)
        if frame is None:
            frame = self._alert_glow.copy()
            frame.putalpha(
                frame.getchannel("A").point(lambda value: value * level // 6)
            )
            if len(self._glow_frames) >= 7:
                self._glow_frames.clear()
            self._glow_frames[level] = frame
        return frame

    def _paste_glow(self, layer: Image.Image, x: float, y: float) -> None:
        glow = self._head_glow
        left = int(round(x - glow.width / 2))
        top = int(round(y - glow.height / 2))
        layer.alpha_composite(glow, (left, top))

    # ---------------------------------------------------------------- 文字
    def _draw_running_text(self, layer: Image.Image, snapshot: Snapshot) -> None:
        k = self._k
        theme = self.theme
        cx = geometry.CENTER

        name, name_size = self._fit_text(
            snapshot.current.name, 220.0, 44.0, bold=True
        )
        self._paste_center(
            layer,
            self._text_sprite(
                name,
                name_size,
                theme.text,
                bold=True,
                glow=0.5,
                blur=3.0,
                k=k,
            ),
            cx,
            198.0,
            k,
        )
        self._paste_center(
            layer,
            self._text_sprite(
                format_duration(snapshot.current.seconds),
                16.0,
                theme.ring_hi,
                bold=False,
                mono=True,
                k=k,
            ),
            cx,
            242.0,
            k,
        )
        self._draw_controls(layer, snapshot)

    def _draw_controls(self, layer: Image.Image, snapshot: Snapshot) -> None:
        """分钟下方的开始/暂停按钮，以及事件名两侧的上/下一事件箭头。"""
        k = self._k
        theme = self.theme
        draw = ImageDraw.Draw(layer)

        # ---------------------------------------------------- 开始 / 暂停按钮
        cx = geometry.CENTER * k
        cy = geometry.PAUSE_BUTTON_Y * k
        radius = geometry.PAUSE_BUTTON_R * k
        paused = snapshot.paused
        edge = theme.alert_ring if paused else theme.ring_hi
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(*theme.ring, 30),
            outline=(*edge, 225 if paused else 170),
            width=max(1, round(1.7 * k)),
        )
        icon = theme.alert_hi if paused else theme.text
        if paused:
            # ▶ 继续
            size = radius * 0.52
            draw.polygon(
                [
                    (cx - size * 0.62, cy - size),
                    (cx - size * 0.62, cy + size),
                    (cx + size, cy),
                ],
                fill=(*icon, 240),
            )
            self._paste_center(
                layer,
                self._text_sprite(
                    "已暂停",
                    8.5,
                    theme.alert_ring,
                    bold=False,
                    k=k,
                ),
                geometry.CENTER,
                geometry.PAUSE_BUTTON_Y + 30.0,
                k,
            )
        else:
            # ❚❚ 暂停
            bar_w = max(1.0, radius * 0.22)
            bar_h = radius * 0.86
            gap = radius * 0.30
            for direction in (-1, 1):
                x0 = cx + direction * gap - bar_w / 2
                draw.rounded_rectangle(
                    [x0, cy - bar_h / 2, x0 + bar_w, cy + bar_h / 2],
                    radius=bar_w / 2,
                    fill=(*icon, 235),
                )

        # ---------------------------------------------------- 上一 / 下一事件
        for name, direction in (("prev", -1), ("next", 1)):
            ax = (geometry.CENTER + direction * geometry.ARROW_OFFSET) * k
            ay = geometry.ARROW_Y * k
            size = 7.5 * k
            thin = max(1.0, 1.9 * k)
            points = [
                (ax - direction * size * 0.42, ay - size),
                (ax + direction * size * 0.42, ay),
                (ax - direction * size * 0.42, ay + size),
            ]
            # 外描边 + 主色，保证在深色圆盘上也清晰
            draw.line(points, fill=(*theme.glow, 90), width=int(thin * 2.6), joint="curve")
            draw.line(points, fill=(*theme.ring_hi, 225), width=int(thin), joint="curve")

    def _draw_alert_text(self, layer: Image.Image, snapshot: Snapshot) -> None:
        k = self._k
        theme = self.theme
        cx = geometry.CENTER
        self._paste_center(
            layer,
            self._text_sprite(
                "!!  ALERT  !!",
                9.5,
                theme.alert_hi,
                bold=True,
                mono=True,
                glow=0.8,
                blur=3.0,
                k=k,
            ),
            cx,
            132.0,
            k,
        )

        lines, size = self._wrap_text(snapshot.alert_text, 258.0, 26.0)
        line_height = size * 1.24
        start_y = 189.0 - (len(lines) - 1) * line_height / 2.0
        for i, line in enumerate(lines):
            self._paste_center(
                layer,
                self._text_sprite(
                    line,
                    size,
                    theme.alert_hi,
                    bold=True,
                    glow=0.9,
                    blur=4.0,
                    k=k,
                ),
                cx,
                start_y + i * line_height,
                k,
            )

        self._paste_center(
            layer,
            self._text_sprite(
                f"{snapshot.current.name} · {format_duration(snapshot.current.seconds)}",
                12.5,
                theme.ring_hi,
                bold=False,
                k=k,
            ),
            cx,
            252.0,
            k,
        )

    def _text_sprite(
        self,
        text: str,
        size: float,
        color: tuple[int, int, int],
        *,
        bold: bool = False,
        mono: bool = False,
        glow: float = 0.0,
        blur: float = 0.0,
        k: float | None = None,
    ) -> Image.Image:
        k = self._k if k is None else k
        px = max(1, int(round(size * k)))
        key = (text, px, color, bold, mono, round(glow, 3), round(blur, 3))
        cached = self._text_cache.get(key)
        if cached is not None:
            return cached

        path = _MONO_FONT if mono else (_NAME_FONT if bold else _BODY_FONT)
        font = _load_font(path, px)
        probe = Image.new("L", (8, 8))
        bbox = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
        width = max(1, bbox[2] - bbox[0])
        height = max(1, bbox[3] - bbox[1])
        pad = max(2, int(math.ceil(blur * k * 2.0))) + 2
        mask = Image.new("L", (width + pad * 2, height + pad * 2), 0)
        ImageDraw.Draw(mask).text(
            (pad - bbox[0], pad - bbox[1]), text, font=font, fill=255
        )

        text_layer = Image.new("RGBA", mask.size, (*color, 255))
        text_layer.putalpha(mask)
        sprite = text_layer
        if glow > 0.001 and blur > 0.001:
            glow_mask = mask.filter(
                ImageFilter.GaussianBlur(max(0.5, blur * k))
            )
            glow_layer = Image.new("RGBA", mask.size, (*color, 0))
            glow_layer.putalpha(
                glow_mask.point(lambda value: int(value * min(1.0, glow)))
            )
            sprite = Image.alpha_composite(glow_layer, text_layer)

        if len(self._text_cache) >= TEXT_CACHE_LIMIT:
            self._text_cache.clear()
        self._text_cache[key] = sprite
        return sprite

    def _fit_text(
        self, text: str, max_width: float, base_size: float, bold: bool = True
    ) -> tuple[str, float]:
        text = text.strip() or "—"
        path = _NAME_FONT if bold else _BODY_FONT
        size = base_size
        while size > 16.0:
            font = _load_font(path, max(1, int(round(size * self._k))))
            if font.getlength(text) <= max_width * self._k:
                return text, size
            size -= 1.0
        size = 16.0
        font = _load_font(path, max(1, int(round(size * self._k))))
        while len(text) > 1 and font.getlength(text + "…") > max_width * self._k:
            text = text[:-1]
        return text + "…", size

    def _wrap_text(
        self, text: str, max_width: float, base_size: float, max_lines: int = 3
    ) -> tuple[list[str], float]:
        """按宽度换行，并优先在中文标点处断开，最多 ``max_lines`` 行。"""
        text = text.strip() or "—"
        punctuation = "，。！？；：、,.!?;:"
        limit = max_width * self._k
        for size in range(int(base_size), 13, -1):
            font = _load_font(_NAME_FONT, max(1, int(round(size * self._k))))
            lines: list[str] = []
            rest = text
            while rest and len(lines) < max_lines:
                if font.getlength(rest) <= limit:
                    lines.append(rest)
                    rest = ""
                    break
                cut = 1
                for index in range(1, len(rest) + 1):
                    if font.getlength(rest[:index]) <= limit:
                        cut = index
                    else:
                        break
                floor = max(1, int(cut * 0.55))
                for index in range(cut, floor - 1, -1):
                    if rest[index - 1] in punctuation:
                        cut = index
                        break
                lines.append(rest[:cut])
                rest = rest[cut:].lstrip()
            if not rest:
                return lines, float(size)

        # 极端情况：用最小字号截断
        size = 14.0
        font = _load_font(_NAME_FONT, max(1, int(round(size * self._k))))
        lines: list[str] = []
        rest = text
        while rest and len(lines) < max_lines:
            if font.getlength(rest) <= limit:
                lines.append(rest)
                rest = ""
                break
            cut = 1
            for index in range(1, len(rest) + 1):
                if font.getlength(rest[:index]) <= limit:
                    cut = index
                else:
                    break
            lines.append(rest[:cut])
            rest = rest[cut:]
        if rest:
            while lines and font.getlength(lines[-1] + "…") > limit:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "…"
        return lines, size

    def _paste_center(
        self,
        target: Image.Image,
        sprite: Image.Image,
        cx: float,
        cy: float,
        k: float,
    ) -> None:
        left = int(round(cx * k - sprite.width / 2))
        top = int(round(cy * k - sprite.height / 2))
        target.alpha_composite(sprite, (left, top))

    def _apply_mask(self, image: Image.Image) -> Image.Image:
        image.putalpha(ImageChops.multiply(image.getchannel("A"), self._mask))
        return image
