"""无窗口生成渲染预览图，便于调整视觉细节。

用法::

    python tools/preview.py

输出到 ``preview/``：每个状态一张透明 PNG，另加一张深色背景的拼图。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from devalarm.core import DEFAULT_EVENTS, PHASE_ALERT, make_snapshot  # noqa: E402
from devalarm.render import RingRenderer  # noqa: E402

OUT_DIR = ROOT / "preview"
CELL = 400


def _label_font(size: int = 13) -> ImageFont.ImageFont:
    for name in ("consola.ttf", "cour.ttf", "msyh.ttc"):
        path = Path(r"C:\Windows\Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                break
    return ImageFont.load_default()


def _sheet(frames: list[tuple[str, Image.Image]]) -> Image.Image:
    margin = 26
    label_h = 26
    cols = 2
    rows = (len(frames) + cols - 1) // cols
    width = cols * CELL + (cols + 1) * margin
    height = rows * (CELL + label_h) + (rows + 1) * margin
    sheet = Image.new("RGB", (width, height), (12, 16, 24))
    draw = ImageDraw.Draw(sheet)

    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(18, 24, 35), width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(18, 24, 35), width=1)

    font = _label_font()
    for index, (name, image) in enumerate(frames):
        row, col = divmod(index, cols)
        x = margin + col * (CELL + margin)
        y = margin + row * (CELL + label_h + margin)
        assert image.size == (CELL, CELL), image.size
        sheet.paste(image, (x, y), image)
        draw.text(
            (x + 2, y + CELL + 5),
            name,
            font=font,
            fill=(120, 168, 220),
        )
    return sheet


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    started = time.perf_counter()
    renderer = RingRenderer(scale=1.0)
    build_ms = (time.perf_counter() - started) * 1000.0
    print(f"renderer build: {build_ms:.1f} ms, size={renderer.size}")

    sit = DEFAULT_EVENTS[0]
    cases = [
        ("00-start", make_snapshot(DEFAULT_EVENTS, 0, elapsed=0.0), 0.0),
        ("01-half", make_snapshot(DEFAULT_EVENTS, 0, elapsed=sit.seconds * 0.5), 0.0),
        ("02-near-end", make_snapshot(DEFAULT_EVENTS, 0, elapsed=sit.seconds * 0.9), 0.0),
        (
            "03-paused",
            make_snapshot(DEFAULT_EVENTS, 0, elapsed=sit.seconds * 0.4, paused=True),
            0.0,
        ),
        (
            "04-alert",
            make_snapshot(
                DEFAULT_EVENTS,
                0,
                elapsed=float(sit.seconds),
                phase=PHASE_ALERT,
                alert_elapsed=3.0,
                alert_seconds=10,
            ),
            0.18,
        ),
    ]

    frames: list[tuple[str, Image.Image]] = []
    for name, snapshot, t in cases:
        render_started = time.perf_counter()
        image = renderer.render(snapshot, t=t)
        for _ in range(4):
            image = renderer.render(snapshot, t=t)
        frame_ms = (time.perf_counter() - render_started) / 5.0 * 1000.0
        path = OUT_DIR / f"{name}.png"
        image.save(path)
        frames.append((name, image))
        print(f"{name:14s} {frame_ms:6.1f} ms  -> {path.name}")

    sheet_path = OUT_DIR / "preview.png"
    _sheet(frames).save(sheet_path)
    print(f"sheet -> {sheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
