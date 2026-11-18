"""几何计算：逻辑画布、圆弧、圆形命中、缩放手柄与 1:1 缩放。

这里全部是纯函数，不依赖 UI 与 Pillow，方便单元测试。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 逻辑画布：渲染器内部统一按 400 × 400 设计，再按 scale 缩放。
LOG_SIZE = 400.0
CENTER = LOG_SIZE / 2.0

# 圆环与圆盘
R_OUT = 174.0          # 圆环外缘
RING_W = 20.0          # 圆环宽度
R_MID = R_OUT - RING_W / 2.0
R_IN = R_OUT - RING_W  # 圆盘半径，与圆环内缘相接

# 命中与裁剪
CLIP_RADIUS = 196.0    # 画面裁剪为圆形，之外完全透明（留给提醒外发光）
HIT_RADIUS = 190.0     # 圆形命中范围
HANDLE_RADIUS = 184.0  # 左右下角缩放手柄所在半径
HANDLE_HIT = 30.0      # 手柄热区半径（逻辑像素）
HANDLE_ANGLES = {"left": 135.0, "right": 45.0}

# 中央控制区：分钟数下方的开始/暂停按钮，事件名左右两侧的上/下一事件箭头。
PAUSE_BUTTON_Y = 288.0  # 按钮圆心（逻辑画布 y）
PAUSE_BUTTON_R = 15.0   # 按钮圆半径
PAUSE_HIT_R = 22.0      # 点击热区半径
ARROW_Y = 198.0         # 箭头圆心的 y（与事件名同一行）
ARROW_OFFSET = 126.0    # 箭头相对画布中心的水平偏移
ARROW_HIT_R = 21.0      # 箭头点击热区半径

# 倒计时环：起点固定在 12 点钟方向（PIL 角 270°），剩余弧从起点顺时针
# 延伸。随着剩余时间减少，弧的末端逆时针退回起点，缺口从顶部逆时针扩大。
TAIL_ANGLE = 270.0  # 顶部（12 点钟）

# 窗口尺寸与缩放
DEFAULT_SIZE = 400
MIN_SIZE = 240
MAX_SIZE = 800
MIN_SCALE = MIN_SIZE / LOG_SIZE
MAX_SCALE = MAX_SIZE / LOG_SIZE


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clamp_scale(scale: float) -> float:
    return clamp(float(scale), MIN_SCALE, MAX_SCALE)


def clamp_size(size: float) -> int:
    return int(round(clamp(float(size), MIN_SIZE, MAX_SIZE)))


def size_for_scale(scale: float) -> int:
    return clamp_size(LOG_SIZE * clamp_scale(scale))


@dataclass(frozen=True)
class Arc:
    """PIL 角度制的一段顺时针圆弧。"""

    start: float
    sweep: float

    @property
    def full(self) -> bool:
        return self.sweep >= 360.0 - 1e-9

    def segments(self, max_step: float = 90.0) -> tuple[tuple[float, float], ...]:
        """拆成若干不超过 90° 的小段，跨 0° 时也不会画错方向。

        整圆由渲染器用 ``ellipse(outline=...)`` 单独处理，因此返回空元组。
        """
        if self.sweep <= 1e-9 or self.full:
            return ()
        result: list[tuple[float, float]] = []
        start = self.start % 360.0
        remaining = self.sweep
        while remaining > 1e-9:
            step = min(max_step, remaining)
            seg_start = start % 360.0
            end = (seg_start + step) % 360.0
            if end < 1e-9:
                end = 360.0
            result.append((round(seg_start, 4), round(end, 4)))
            start += step
            remaining -= step
        return tuple(result)


def remaining_arc(remaining: float, tail: float = TAIL_ANGLE) -> Arc:
    """剩余比例 0..1 -> 圆环上的剩余弧。

    起点固定在 ``tail``（默认顶部 12 点钟），剩余弧从起点顺时针延伸；
    ``remaining=0`` 没有弧，``remaining=1`` 是整圆。剩余越少，弧的末端
    越向起点逆时针退回，缺口从顶部逆时针扩大。
    """
    ratio = clamp(float(remaining), 0.0, 1.0)
    if ratio <= 1e-9:
        return Arc(tail % 360.0, 0.0)
    if ratio >= 1.0 - 1e-9:
        return Arc(tail % 360.0, 360.0)
    return Arc(tail % 360.0, 360.0 * ratio)


def arc_from_start(start: float, sweep: float) -> Arc:
    """从指定角度顺时针扫过 sweep 度（提醒倒计时小弧使用）。"""
    return Arc(start % 360.0, clamp(float(sweep), 0.0, 360.0))


def point_at(angle: float, radius: float) -> tuple[float, float]:
    """PIL 角度（0° 在 3 点钟，顺时针）上的点。"""
    rad = math.radians(angle)
    return CENTER + radius * math.cos(rad), CENTER + radius * math.sin(rad)


def handle_positions() -> dict[str, tuple[float, float]]:
    """左右下角缩放手柄在逻辑画布上的中心点。"""
    return {
        name: point_at(angle, HANDLE_RADIUS)
        for name, angle in HANDLE_ANGLES.items()
    }


def distance_from_center(x: float, y: float, size: float) -> float:
    """客户端坐标到圆心的距离（按窗口实际尺寸缩放）。"""
    half = size / 2.0
    return math.hypot(x - half, y - half)


def inside_hit_circle(x: float, y: float, size: float) -> bool:
    """指针是否落在圆形命中范围内。"""
    return distance_from_center(x, y, size) <= HIT_RADIUS * size / LOG_SIZE


def control_at(x: float, y: float, size: float) -> str | None:
    """返回指针所在的控制区：``pause`` / ``prev`` / ``next``，否则 None。

    坐标是窗口客户区像素，按窗口尺寸换算到逻辑画布。
    """
    scale = size / LOG_SIZE
    if scale <= 0:
        return None
    lx, ly = x / scale, y / scale
    if math.hypot(lx - CENTER, ly - PAUSE_BUTTON_Y) <= PAUSE_HIT_R:
        return "pause"
    for name, dx in (("prev", -ARROW_OFFSET), ("next", ARROW_OFFSET)):
        if math.hypot(lx - (CENTER + dx), ly - ARROW_Y) <= ARROW_HIT_R:
            return name
    return None


def handle_at(x: float, y: float, size: float) -> str | None:
    """返回指针所在的缩放手柄（left/right），否则 None。"""
    scale = size / LOG_SIZE
    hit = max(16.0, HANDLE_HIT * scale)
    for name, (hx, hy) in handle_positions().items():
        if math.hypot(x - hx * scale, y - hy * scale) <= hit:
            return name
    return None


def resize_rect(
    handle: str,
    left: int,
    top: int,
    width: int,
    height: int,
    dx: int,
    dy: int,
) -> tuple[int, int, int, int]:
    """拖动左右下角手柄时计算新矩形。

    - 顶边固定，窗口始终为正方形；
    - 右手柄保持左边不动，左手柄保持右边不动；
    - 取水平/垂直位移中更明显的一个，斜向拖动也跟手。
    """
    size = max(width, height)
    horizontal = dx if handle == "right" else -dx
    delta = horizontal if abs(horizontal) >= abs(dy) else dy
    target = clamp_size(size + delta)
    new_left = left if handle == "right" else left + size - target
    return new_left, top, target, target


def resize_cursor(handle: str) -> str:
    """左右下角对应的 Windows 缩放光标名称。"""
    return "nwse" if handle == "left" else "nesw"
