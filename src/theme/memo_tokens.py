"""메모 면 위의 색 계산. SlideMemo-design.md 3.0.1(직접 만든 색), 3.1~3.2(계산 토큰)."""
from __future__ import annotations

import math
import re

from theme import tokens as T

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
RGB = tuple[float, float, float]

TEXT_MIN_CONTRAST = 4.5
BORDER_MIN_CONTRAST = 3.0
_RATIO_STEP = 0.05
_LIGHTNESS_STEP = 0.02


# ----- 색 변환 -----
def _rgb(hex_color: str) -> RGB:
    if not _HEX_RE.fullmatch(hex_color):
        raise ValueError(f"잘못된 색 값: {hex_color!r}")
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _hex(rgb: RGB) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in rgb)


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def contrast(a: str, b: str) -> float:
    """WCAG 대비."""

    def luminance(hex_color: str) -> float:
        r, g, b_ = (_to_linear(c) for c in _rgb(hex_color))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def to_oklch(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_to_linear(c) for c in _rgb(hex_color))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    lightness = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
    a_ = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
    b_ = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
    return lightness, math.hypot(a_, b_), math.degrees(math.atan2(b_, a_)) % 360


def from_oklch(lightness: float, chroma: float, hue: float) -> str:
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3
    linear = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
    )
    return _hex(tuple(_from_linear(max(0.0, c)) for c in linear))


def mix(fg: str, bg: str, ratio: float) -> str:
    """bg 위에 fg를 ratio만큼 섞은 불투명 색."""
    f, b = _rgb(fg), _rgb(bg)
    return _hex(tuple(x * ratio + y * (1 - ratio) for x, y in zip(f, b)))


# ----- 3.0.1 직접 만든 색 -----
def _band_with_contrast(picked: str, face: str, step: float) -> str:
    """picked에서 시작해 face와의 대비가 3:1이 될 때까지 L을 step씩 옮긴다."""
    lightness, chroma, hue = to_oklch(picked)
    band = picked.upper()
    while contrast(band, face) < T.BAND_MIN_CONTRAST and 0.0 <= lightness <= 1.0:
        lightness += step
        band = from_oklch(max(0.0, min(1.0, lightness)), chroma, hue)
    return band


def custom_tones(picked: str) -> tuple[str, str, str]:
    """고른 색 → (밝은 면, 밝은 띠, 어두운 띠)."""
    _, chroma, hue = to_oklch(picked)
    face_chroma = min(chroma * T.CUSTOM_FACE_CHROMA_RATIO, T.CUSTOM_FACE_CHROMA_MAX)
    face = from_oklch(T.CUSTOM_LIGHT_FACE_L, face_chroma, hue)
    return (
        face,
        _band_with_contrast(picked, face, -_LIGHTNESS_STEP),
        _band_with_contrast(picked, T.DARK_MEMO_FACE, _LIGHTNESS_STEP),
    )


def face_and_band(color: str, mode: str) -> tuple[str, str]:
    """프리셋 키 또는 #RRGGBB → (면, 띠). 저장값은 신뢰 경계라 형식이 틀리면 ValueError."""
    if color in T.MEMO_PRESETS:
        _, face, band, dark_band = T.MEMO_PRESETS[color]
    else:
        face, band, dark_band = custom_tones(color)
    return (T.DARK_MEMO_FACE, dark_band) if mode == "dark" else (face, band)


# ----- 3.1~3.2 계산 토큰 -----
def pick_ink(face: str) -> str:
    return max((T.INK_DARK, T.WHITE), key=lambda ink: contrast(ink, face))


def solve_ratio(ink: str, base: str, ratio: float, minimum: float, *against: str) -> str:
    """base 위에 ink를 섞되, against 면들(없으면 base)과의 대비가 minimum에 못 미치면
    비율을 5%씩 올린다."""
    surfaces = against or (base,)
    while True:
        color = mix(ink, base, ratio)
        if ratio >= 1.0 or all(contrast(color, s) >= minimum for s in surfaces):
            return color
        ratio = min(1.0, ratio + _RATIO_STEP)


def memo_tokens(color: str, mode: str) -> dict[str, str]:
    """메모 색(프리셋 키 또는 #RRGGBB)과 화면 모드 → memo.qss 토큰."""
    if mode not in T.MODES:
        raise ValueError(f"잘못된 화면 모드: {mode!r}")
    face, band = face_and_band(color, mode)
    ink = pick_ink(face)
    black_ink = ink == T.INK_DARK
    field = mix(T.WHITE, face, 0.55) if black_ink else mix(T.BLACK, face, 0.22)
    link = T.MEMO_LINK_ON_LIGHT if black_ink else T.MEMO_LINK_ON_DARK
    if contrast(link, face) < TEXT_MIN_CONTRAST:
        link = ink  # 항상 밑줄이 함께 간다
    return {
        "memo_face": face,
        "memo_band": band,
        "memo_fg": ink,
        "memo_fg_secondary": solve_ratio(ink, face, 0.76, TEXT_MIN_CONTRAST),
        "memo_field": field,
        "memo_hint": solve_ratio(ink, field, 0.68, TEXT_MIN_CONTRAST),
        "memo_border": solve_ratio(ink, face, 0.55, BORDER_MIN_CONTRAST, face, field),
        "memo_divider": mix(ink, face, 0.14),
        "memo_edge": mix(ink, face, 0.24),
        "memo_frame": mix(ink, face, 0.18),
        "memo_hover": mix(ink, face, 0.08),
        "memo_selected": mix(ink, face, 0.16),
        "memo_scroll": mix(ink, face, 0.30),
        "memo_table_line": mix(ink, face, 0.30),
        "memo_table_head": mix(ink, face, 0.06),
        "memo_link": link,
    }
