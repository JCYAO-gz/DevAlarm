"""生成 assets/devalarm.ico 与 devalarm.png。

深空蓝玻璃圆盘 + 蓝色发光圆环 + 右侧亮青色缺口，与科技 HUD 主题一致。
先按 4 倍尺寸绘制再缩小，保证 16px 图标仍然清晰。
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SS = 4
SIZE = 256
LOG = 400.0
CENTER = SIZE * SS / 2.0
R_OUT = 172.0 / LOG * SIZE * SS
RING_W = 30.0 / LOG * SIZE * SS


def _circle(draw: ImageDraw.ImageDraw, radius: float, fill) -> None:
    draw.ellipse(
        (CENTER - radius, CENTER - radius, CENTER + radius, CENTER + radius),
        fill=fill,
    )


def build() -> tuple[Path, Path]:
    canvas = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))

    disc = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    disc_draw = ImageDraw.Draw(disc)
    for step in range(72):
        ratio = step / 71.0
        radius = R_OUT * (1.0 - ratio * 0.90)
        blue = int(16 + 30 * (1.0 - ratio))
        green = int(26 + 14 * (1.0 - ratio))
        alpha = int(235 * (0.82 + 0.18 * (1.0 - ratio)))
        _circle(disc_draw, radius, (blue, green, 52, alpha))
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).ellipse(
        (
            CENTER - R_OUT * 1.02,
            CENTER - R_OUT * 1.02,
            CENTER + R_OUT * 1.02,
            CENTER + R_OUT * 1.02,
        ),
        fill=255,
    )
    canvas.alpha_composite(Image.composite(disc, Image.new("RGBA", canvas.size), mask))

    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    ring_radius = R_OUT - RING_W / 2.0
    width = RING_W
    glow_draw.arc(
        (
            CENTER - ring_radius,
            CENTER - ring_radius,
            CENTER + ring_radius,
            CENTER + ring_radius,
        ),
        start=25,
        end=335,
        fill=(40, 122, 255, 210),
        width=int(width),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(RING_W * 0.55))
    canvas.alpha_composite(glow)

    ring = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    box = (
        CENTER - ring_radius,
        CENTER - ring_radius,
        CENTER + ring_radius,
        CENTER + ring_radius,
    )
    ring_draw.arc(box, start=30, end=330, fill=(76, 150, 255, 255), width=int(width))
    ring_draw.arc(
        box, start=48, end=312, fill=(196, 236, 255, 255), width=int(width * 0.30)
    )
    ring_draw.arc(
        (
            CENTER - ring_radius + width * 0.4,
            CENTER - ring_radius + width * 0.4,
            CENTER + ring_radius - width * 0.4,
            CENTER + ring_radius - width * 0.4,
        ),
        start=38,
        end=322,
        fill=(40, 122, 255, 120),
        width=int(width * 0.2),
    )
    canvas.alpha_composite(ring)

    ticks = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    tick_draw = ImageDraw.Draw(ticks)
    tick_radius = R_OUT - RING_W - 16.0 / LOG * SIZE * SS
    for degree in range(0, 360, 30):
        angle = math.radians(degree)
        x = CENTER + math.cos(angle) * tick_radius
        y = CENTER + math.sin(angle) * tick_radius
        tick_draw.ellipse(
            (x - 3.2 * SS, y - 3.2 * SS, x + 3.2 * SS, y + 3.2 * SS),
            fill=(96, 174, 255, 165),
        )
    canvas.alpha_composite(ticks)

    tip_angle = math.radians(32)
    tip_x = CENTER + math.cos(tip_angle) * ring_radius
    tip_y = CENTER + math.sin(tip_angle) * ring_radius
    tip_glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    tip_draw = ImageDraw.Draw(tip_glow)
    tip_draw.ellipse(
        (
            tip_x - 34 * SS,
            tip_y - 34 * SS,
            tip_x + 34 * SS,
            tip_y + 34 * SS,
        ),
        fill=(96, 218, 255, 220),
    )
    tip_glow = tip_glow.filter(ImageFilter.GaussianBlur(16 * SS))
    canvas.alpha_composite(tip_glow)

    icon = canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    png_path = assets / "devalarm.png"
    ico_path = assets / "devalarm.ico"
    icon.save(png_path)
    icon.save(
        ico_path,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return ico_path, png_path


if __name__ == "__main__":
    ico, png = build()
    print(f"已生成 {ico}")
    print(f"已生成 {png}")
