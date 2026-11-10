"""디자인 토큰. 값은 docs/ui-design/SlideMemo-design.md(1~3장, 9장)가 기준이다.
색 hex는 src/ 안에서 이 파일에만 둔다."""
from __future__ import annotations

# ----- 1.1 앱 껍데기 -----
LIGHT: dict[str, str] = {
    "bg_canvas": "#FFFFFF",
    "bg_sunken": "#F4F5F7",
    "bg_raised": "#FFFFFF",
    "bg_muted": "#EAEBEE",
    "fg": "#1B1D22",
    "fg_secondary": "#4D5159",
    "fg_hint": "#767676",
    "fg_disabled": "#C9CCD2",
    "line": "#E0E2E6",
    "line_strong": "#C9CCD2",
    "line_control": "#80858E",
    "accent": "#5055B1",
    "accent_press": "#3F4391",
    "accent_text": "#5055B1",
    "accent_weak": "#ECEDF8",
    "accent_strong": "#3F4391",
    "on_accent": "#FFFFFF",
    "danger": "#B01219",
    "danger_fill": "#B01219",
    "danger_weak": "#FCE9EA",
    "chip_selected": "#1B1D22",
    "contrast": "#2E3138",
    "focus": "#1B1D22",
    "overlay_hover": "rgba(27,29,34,0.08)",
    "overlay_press": "rgba(27,29,34,0.16)",
    "scroll": "#C9CCD2",
    "highlight": "#FFDD95",
}

DARK: dict[str, str] = {
    "bg_canvas": "#282828",
    "bg_sunken": "#1F1F1F",
    "bg_raised": "#363636",
    "bg_muted": "#474747",
    "fg": "#FAFAFA",
    "fg_secondary": "#BEBEBE",
    "fg_hint": "#A7A7A7",
    "fg_disabled": "#6C6C6C",
    "line": "#606060",
    "line_strong": "#6C6C6C",
    "line_control": "#898989",
    "accent": "#8A8ECF",
    "accent_press": "#AEB1DF",
    "accent_text": "#AEB1DF",
    "accent_weak": "#2D3068",
    "accent_strong": "#AEB1DF",
    "on_accent": "#1B1D22",
    "danger": "#EF8A8F",
    "danger_fill": "#B01219",
    "danger_weak": "#590000",
    "chip_selected": "#FAFAFA",
    "contrast": "#606060",
    "focus": "#FAFAFA",
    "overlay_hover": "rgba(250,250,250,0.08)",
    "overlay_press": "rgba(250,250,250,0.16)",
    "scroll": "#6C6C6C",
    "highlight": "#FFDD95",
}

MODES: dict[str, dict[str, str]] = {"light": LIGHT, "dark": DARK}

# 흰 글자 고정 자리(위험 단추, 툴팁·토스트)와 3.1 먹색 후보
WHITE = "#FFFFFF"
BLACK = "#000000"
INK_DARK = "#1B1D22"
HIGHLIGHT_FG = "#1B1D22"  # 검색어 강조 글자. 메모 색과 무관하게 고정 (4.2, 9장 17)
SELECTION_BG = "#5055B1"  # 두 화면 모두 고정 (9장 15)
SELECTION_FG = "#FFFFFF"

# ----- 2.1~2.8 글자, 간격, 크기, 반경, 그림자, 움직임 -----
FONT_FAMILY = "Pretendard"
LETTER_SPACING_PERCENT = 99  # 자간 -0.01em 근사
MEMO_BODY_DEFAULT_PT = 12  # 96dpi에서 16px (9장 13)

# 이름 → (크기 px, 줄높이 px, 굵기)
TYPE: dict[str, tuple[int, int, int]] = {
    "caption": (12, 18, 400),
    "label": (12, 18, 500),
    "body": (14, 22, 400),
    "body_strong": (14, 22, 500),
    "memo_body": (16, 24, 400),
    "title": (18, 28, 700),
}

SPACE = (2, 4, 8, 12, 16, 20, 24, 32)

# 이름 → (높이, 좌우 여백)
CONTROL: dict[str, tuple[int, int]] = {"sm": (24, 8), "md": (32, 12)}

RADIUS: dict[str, int] = {
    "control": 8,  # 단추, 입력, 콤보, 메뉴, 팝업, 툴팁, 토스트, 말풍선, 달력 칸
    "small": 4,  # 체크박스, 색 견본
    "surface": 12,  # 메모 창 바깥, 바 단추 묶음
    "tab_inner": 8,  # 세로 탭 안쪽 모서리
    "full": 9999,  # 칩, 배지, 색 점, 슬라이더 손잡이, 녹음 단추
}

# 이름 → (아래로 y, 흐림, 불투명도)
SHADOW: dict[str, tuple[int, int, float]] = {
    "sm": (1, 3, 0.20),
    "md": (4, 10, 0.20),
    "xl": (16, 32, 0.20),
}

MOTION_FAST_MS = 150
MOTION_BASE_MS = 240
EASING_BEZIER = (0.4, 0.0, 0.2, 1.0)
TOAST_MS = 4000

# 설정 창과 앱이 같은 값을 읽는다 (6.3의 5번)
TAB_WIDTH_DEFAULT = 40
TAB_HEIGHT_DEFAULT = 112

# ----- 3. 메모 색 -----
DARK_MEMO_FACE = "#282828"
CUSTOM_LIGHT_FACE_L = 0.975
CUSTOM_FACE_CHROMA_RATIO = 0.15
CUSTOM_FACE_CHROMA_MAX = 0.022
BAND_MIN_CONTRAST = 3.0
MAX_CUSTOM_COLORS = 6
DEFAULT_MEMO_COLOR = "yellow"

# 키 → (이름, 밝은 면, 밝은 띠, 어두운 띠)
MEMO_PRESETS: dict[str, tuple[str, str, str, str]] = {
    "gray": ("회색", "#F4F4F4", "#767676", "#898989"),
    "yellow": ("노랑", "#FFF7E7", "#A96800", "#BE7B00"),
    "orange": ("주황", "#FFF6F1", "#D34701", "#E65F08"),
    "pink": ("분홍", "#FFF5F7", "#D13E76", "#E65588"),
    "purple": ("보라", "#F9F5FF", "#805CEC", "#9672F5"),
    "blue": ("파랑", "#EFF8FF", "#2A72E5", "#368AED"),
    "teal": ("청록", "#EEF9FB", "#04819C", "#0E96B0"),
    "green": ("초록", "#EDFAF4", "#058765", "#259A77"),
}

# 3.2 링크 색은 1장 토큰에서 온다
MEMO_LINK_ON_LIGHT = LIGHT["accent"]
MEMO_LINK_ON_DARK = DARK["accent_text"]

# ----- 9장 9: 글자색·형광펜 (이름, 밝은 화면, 어두운 화면) -----
TEXT_COLORS: tuple[tuple[str, str, str], ...] = (
    ("회색", "#5C6068", "#BEBEBE"),
    ("빨강", "#B01219", "#F28B8B"),
    ("주황", "#A8420C", "#F4A06B"),
    ("노랑", "#855A00", "#E8C45A"),
    ("초록", "#1E7A3C", "#6FCF8E"),
    ("청록", "#0B6E80", "#5CC6D6"),
    ("파랑", "#2459C2", "#8AB4F8"),
    ("인디고", "#5055B1", "#AEB1DF"),
    ("보라", "#7A3BC4", "#C59BF2"),
    ("분홍", "#B3245F", "#F28AB4"),
)

HIGHLIGHTS: tuple[tuple[str, str, str], ...] = (
    ("노랑", "#FFDD95", "#6B5200"),
    ("초록", "#C9EFD6", "#1F5A35"),
    ("파랑", "#D3E3FF", "#24427A"),
    ("분홍", "#FFD3E1", "#6E2342"),
    ("보라", "#E6DAFF", "#4A3080"),
)
