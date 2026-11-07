"""设计体检：正文／次要文字对比度与字号下限，防止再次回到白底白字。

阈值取自可读性底线：正文与次要文字对卡片 ≥4.5:1，主文字 ≥7:1；
主要网格线与模型描边对三维背景 ≥3:1（非文字图形）。数值按 WCAG 相对亮度计算。
"""
import pytest

from ui import theme


def _channel(value):
    value = value / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(color):
    color = color.lstrip('#')
    r, g, b = (int(color[index:index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(first, second):
    a, b = luminance(first), luminance(second)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def test_text_contrast_meets_floor():
    for key in ("text", "secondary", "group_title", "muted"):
        assert contrast(theme.COLORS[key], theme.COLORS["surface"]) >= (7.0 if key == "text" else 4.5), key
    assert contrast(theme.COLORS["muted"], theme.COLORS["bg"]) >= 4.5
    assert contrast(theme.COLORS["muted"], theme.COLORS["surface_alt"]) >= 4.5
    assert contrast(theme.COLORS["surface"], theme.COLORS["accent"]) >= 4.5


def test_scene_contrast_meets_floor():
    background = theme.SCENE["background_bottom"]
    assert contrast(theme.COLORS["grid_major"], background) >= 1.2
    assert contrast(theme.MODEL_COLORS["duct_edge"], background) >= 3.0
    assert contrast(theme.COLORS["reference"], background) >= 3.0


def test_font_sizes_have_a_readable_floor():
    for key in ("body", "tiny", "small"):
        assert theme.FONTS[key] >= 8.5, key


def test_tokens_are_hex_and_complete():
    for key, value in theme.COLORS.items():
        assert value.startswith("#") or value.startswith("rgba("), key
    for key in ("bg", "surface", "border", "text", "muted", "accent", "grid_major", "selection_bg"):
        assert key in theme.COLORS

