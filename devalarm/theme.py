"""圆形科技风主题定义与注册表。

一个主题描述整个圆环 HUD 的配色与提醒动效参数。新增皮肤只需构造
``Theme`` 并调用 ``register_theme()``，设置页与渲染器会自动列出并使用。

当前内置主题：
- ``tech``：科技 HUD（默认），蓝色发光圆环 + 深色玻璃圆盘
"""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]

DEFAULT_THEME_KEY = "tech"


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    description: str

    # 圆盘与背景
    disc: RGB
    disc_hi: RGB
    disc_alpha: int
    grid: RGB
    track: RGB

    # 进度圆环
    ring: RGB
    ring_hi: RGB
    ring_light: RGB
    glow: RGB
    text: RGB
    text_dim: RGB

    # 提醒状态
    alert_ring: RGB
    alert_hi: RGB

    # 手柄与动效
    handle: RGB
    handle_active: RGB
    ring_width: float = 20.0
    pulse_hz: float = 1.8
    shake_hz: float = 2.6
    shake_amplitude_ratio: float = 0.012


THEMES: dict[str, Theme] = {}


def register_theme(theme: Theme) -> Theme:
    """把主题加入全局注册表，返回主题本身便于模块级使用。"""
    THEMES[theme.key] = theme
    return theme


TECH_THEME = register_theme(
    Theme(
        key="tech",
        name="科技 HUD",
        description=(
            "深空蓝玻璃圆盘上的发光倒计时环。极坐标网格、刻度与扫描线"
            "组成轻量 HUD，剩余进度以蓝色光子弧显示，到点后整环转为青白脉冲。"
        ),
        disc=(8, 16, 30),
        disc_hi=(14, 32, 58),
        disc_alpha=252,
        grid=(28, 66, 112),
        track=(17, 37, 62),
        ring=(38, 108, 255),
        ring_hi=(92, 174, 255),
        ring_light=(196, 236, 255),
        glow=(40, 122, 255),
        text=(226, 242, 255),
        text_dim=(112, 152, 198),
        alert_ring=(96, 218, 255),
        alert_hi=(255, 255, 255),
        handle=(70, 138, 214),
        handle_active=(156, 226, 255),
        ring_width=20.0,
        pulse_hz=1.8,
        shake_hz=2.6,
        shake_amplitude_ratio=0.012,
    )
)


def get_theme(theme: Theme | str | None = None) -> Theme:
    """按 key 取主题；未知 key 回退到默认主题。"""
    if isinstance(theme, Theme):
        return theme
    return THEMES.get(theme or DEFAULT_THEME_KEY, THEMES[DEFAULT_THEME_KEY])


def list_themes() -> list[Theme]:
    return list(THEMES.values())
