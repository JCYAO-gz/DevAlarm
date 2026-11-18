"""生成 README 顶部的效果图 ``assets/showcase.png``。

用与程序相同的 :class:`~devalarm.render.RingRenderer` 渲染三种状态
（运行中 / 已暂停 / 提醒），再拼成一张深色背景的展示图。修改界面后
重新运行即可更新效果图：

    python tools/make_showcase.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from devalarm import APP_VERSION  # noqa: E402
from devalarm.core import DEFAULT_EVENTS, PHASE_ALERT, make_snapshot  # noqa: E402
from devalarm.render import RingRenderer  # noqa: E402

OUT = ROOT / "assets" / "showcase.png"

WIDTH = 1240
HEIGHT = 600
MARGIN = 44
GAP = 36
RING = 360
RING_Y = 132

BG_TOP = (6, 10, 17)
BG_BOTTOM = (10, 16, 27)
GRID = (13, 19, 30)
ACCENT = (47, 125, 255)
TEXT = (232, 242, 255)
MUTED = (124, 150, 184)
SUB = (128, 158, 198)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = ("msyhbd.ttc", "msyh.ttc") if bold else ("msyh.ttc", "msyhbd.ttc")
    names += ("segoeui.ttf", "arial.ttf")
    for name in names:
        path = fonts / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _background() -> Image.Image:
    top = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    bottom = Image.new("RGB", (WIDTH, HEIGHT), BG_BOTTOM)
    mask = Image.linear_gradient("L").resize((WIDTH, HEIGHT))
    canvas = Image.composite(bottom, top, mask)

    draw = ImageDraw.Draw(canvas)
    for x in range(0, WIDTH, 40):
        draw.line([(x, 0), (x, HEIGHT)], fill=GRID)
    for y in range(0, HEIGHT, 40):
        draw.line([(0, y), (WIDTH, y)], fill=GRID)

    # 三个圆环背后的柔和蓝光
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for index in range(3):
        cx = MARGIN + index * (RING + GAP) + RING // 2
        cy = RING_Y + RING // 2
        glow_draw.ellipse(
            [cx - 230, cy - 230, cx + 230, cy + 230],
            fill=(40, 110, 255, 42),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    return Image.alpha_composite(canvas.convert("RGBA"), glow)


def _header(canvas: Image.Image) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([MARGIN, 42, MARGIN + 6, 82], radius=3, fill=ACCENT)
    draw.text(
        (MARGIN + 20, 36),
        "DevAlarm 程序员闹钟",
        font=_font(32, bold=True),
        fill=TEXT,
    )
    draw.text(
        (MARGIN + 22, 86),
        "常驻桌面的圆形倒计时 · 坐-站-走节律提醒",
        font=_font(16),
        fill=SUB,
    )

    chip = [WIDTH - MARGIN - 86, 44, WIDTH - MARGIN, 78]
    draw.rounded_rectangle(
        chip, radius=17, fill=(12, 22, 38), outline=(38, 84, 146), width=1
    )
    draw.text(
        ((chip[0] + chip[2]) // 2, (chip[1] + chip[3]) // 2),
        APP_VERSION,
        font=_font(15, bold=True),
        fill=(126, 184, 255),
        anchor="mm",
    )


def main() -> int:
    canvas = _background()
    _header(canvas)
    draw = ImageDraw.Draw(canvas)

    for index in range(1, 3):
        x = MARGIN + index * (RING + GAP) - GAP // 2
        draw.line([(x, RING_Y + 10), (x, 564)], fill=(18, 27, 42))

    sit = DEFAULT_EVENTS[0]
    cases = [
        (
            "运行中",
            "圆环倒计时 · 暂停按钮 · 切换事件箭头",
            make_snapshot(DEFAULT_EVENTS, 0, elapsed=sit.seconds * 0.35),
            0.0,
        ),
        (
            "已暂停",
            "时间冻结，按钮变为 ▶",
            make_snapshot(
                DEFAULT_EVENTS,
                0,
                elapsed=sit.seconds * 0.35,
                paused=True,
            ),
            0.0,
        ),
        (
            "提醒",
            "圆环向外发光并循环响铃",
            make_snapshot(
                DEFAULT_EVENTS,
                0,
                elapsed=float(sit.seconds),
                phase=PHASE_ALERT,
                alert_elapsed=3.0,
                alert_seconds=10,
            ),
            0.0,
        ),
    ]

    renderer = RingRenderer(scale=RING / 400)
    assert renderer.size == RING, renderer.size
    label_font = _font(18, bold=True)
    sub_font = _font(14)

    for index, (title, subtitle, snapshot, t) in enumerate(cases):
        frame = renderer.render(snapshot, t=t)
        x = MARGIN + index * (RING + GAP)
        canvas.paste(frame, (x, RING_Y), frame)

        cx = x + RING // 2
        draw.text((cx, 508), title, font=label_font, fill=TEXT, anchor="mm")
        draw.text((cx, 536), subtitle, font=sub_font, fill=MUTED, anchor="mm")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUT, optimize=True)
    size_kb = OUT.stat().st_size / 1024
    print(f"效果图已生成：{OUT}（{WIDTH}x{HEIGHT}，{size_kb:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
