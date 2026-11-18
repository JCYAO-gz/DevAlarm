"""生成 assets/alert.wav：2 秒可无缝循环的科技提示音。

四声上行短脉冲（A5 → C#6 → E6 → A6），每声带轻微泛音与指数衰减，
首尾都归零，循环播放时不会有爆音。
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100
DURATION = 2.0
VOLUME = 0.30
NOTES = (880.0, 1108.73, 1318.51, 1760.0)
STEP = DURATION / len(NOTES)


def _envelope(age: float) -> float:
    attack = 0.008
    if age < 0.0 or age > 0.46:
        return 0.0
    if age < attack:
        return age / attack
    decay = math.exp(-(age - attack) / 0.135)
    fade = min(1.0, max(0.0, (0.46 - age) / 0.05))
    return decay * fade


def _sample(age: float, freq: float) -> float:
    envelope = _envelope(age)
    if envelope <= 0.0:
        return 0.0
    fundamental = math.sin(2.0 * math.pi * freq * age)
    second = 0.32 * math.sin(2.0 * math.pi * freq * 2.0 * age)
    shimmer = 0.16 * math.sin(2.0 * math.pi * freq * 3.0 * age)
    ping = 0.22 * math.exp(-age / 0.035) * math.sin(
        2.0 * math.pi * freq * 1.5 * age
    )
    return envelope * (fundamental + second + shimmer + ping)


def build() -> Path:
    samples: list[float] = []
    total = int(SAMPLE_RATE * DURATION)
    for index in range(total):
        t = index / SAMPLE_RATE
        note_index = min(len(NOTES) - 1, int(t / STEP))
        age = t - note_index * STEP
        value = _sample(age, NOTES[note_index])
        # 极轻的低频底噪，让铃声更有“设备感”，但保持安静
        value += 0.015 * math.sin(2.0 * math.pi * 55.0 * t)
        fade_in = min(1.0, t / 0.01)
        fade_out = min(1.0, (DURATION - t) / 0.02)
        samples.append(value * fade_in * fade_out)
    peak = max(1e-9, max(abs(value) for value in samples))
    gain = VOLUME / peak
    frames = b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, value * gain)) * 32767))
        for value in samples
    )
    path = Path(__file__).resolve().parent.parent / "assets" / "alert.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames)
    return path


if __name__ == "__main__":
    output = build()
    print(f"已生成 {output}（{DURATION:.1f}s 无缝循环）")
